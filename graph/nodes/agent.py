"""Agent nodes: preprocess, routing, workflow planning, execution, and answer synthesis."""

from __future__ import annotations

import json
import os
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from graph.state import AgentFlowState, TraceDetails
from graph.tool_registry import TOOL_REGISTRY
from graph.workflow_contract import build_default_plan, normalize_workflow_plan


def trace(state: AgentFlowState, step: str, status: str, message: str, details: TraceDetails = None) -> None:
    merged_details = dict(details or {})
    if state.get("request_id"):
        merged_details.setdefault("request_id", state.get("request_id"))
    events = list(state.get("trace", []))
    events.append(
        {
            "step": step,
            "status": status,
            "message": message,
            "details": merged_details,
        }
    )
    state["trace"] = events


def _append_warning(state: AgentFlowState, warning: str) -> None:
    warnings = list(state.get("warnings", []))
    warnings.append(warning)
    state["warnings"] = warnings


def _extract_excel_path(text: str) -> str | None:
    patterns = [
        r'([A-Za-z]:[\\/][^"\n\r]*?\.(?:xlsx|xls))',
        r'((?:\.{1,2}[\\/]|[\\/])[^"\n\r]*?\.(?:xlsx|xls))',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip("'").strip('"')
    return None


def _extract_path_like_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    patterns = [
        r'([A-Za-z]:[\\/][^"\n\r]+)',
        r'((?:\.{1,2}[\\/]|[\\/])[^"\n\r]+)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            token = match.group(1).strip().strip("'").strip('"').rstrip(".,;")
            if token:
                tokens.append(token)

    folder_hint_pattern = r'([A-Za-z0-9_./\\-]+)\s*(?:鏂囦欢澶箌folder|鐩綍)'
    for match in re.finditer(folder_hint_pattern, text, flags=re.IGNORECASE):
        token = match.group(1).strip().strip("'").strip('"').rstrip(".,;")
        if token:
            tokens.append(token)
    return tokens


def _dedup_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _list_excel_in_dir(folder: Path) -> list[str]:
    files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".xlsx", ".xls"}]
    files.sort(key=lambda p: str(p).lower())
    return [str(p.resolve()) for p in files]


def _find_dirs_by_name(name_hint: str, max_hits: int = 5) -> list[Path]:
    needle = name_hint.strip().lower().replace("\\", "/").rstrip("/")
    if not needle:
        return []

    cwd = Path.cwd()
    hits: list[Path] = []
    for path in cwd.rglob("*"):
        if not path.is_dir():
            continue
        if needle in path.name.lower():
            hits.append(path.resolve())
            if len(hits) >= max_hits:
                break
    return hits


def _resolve_excel_candidates(query: str, explicit_hint: str | None) -> tuple[list[str], str | None, list[str]]:
    warnings: list[str] = []
    seeds: list[str] = []

    if explicit_hint:
        seeds.append(explicit_hint)

    extracted_excel = _extract_excel_path(query)
    if extracted_excel:
        seeds.append(extracted_excel)

    seeds.extend(_extract_path_like_tokens(query))
    seeds = _dedup_keep_order(seeds)

    files: list[str] = []
    matched_folder: str | None = None

    def _resolve_path(seed: str) -> Path | None:
        candidate = Path(seed).expanduser()
        if candidate.exists():
            return candidate.resolve()
        relative = (Path.cwd() / seed).resolve()
        if relative.exists():
            return relative
        return None

    for seed in seeds:
        resolved = _resolve_path(seed)
        if resolved is None:
            # If path does not exist and looks like a folder name hint, try fuzzy folder match.
            if all(ch not in seed for ch in [":", "\\", "/", ".xlsx", ".xls"]):
                dir_hits = _find_dirs_by_name(seed)
                if dir_hits:
                    if matched_folder is None:
                        matched_folder = str(dir_hits[0])
                    for hit in dir_hits:
                        files.extend(_list_excel_in_dir(hit))
                else:
                    warnings.append(f"Path/folder hint not found: {seed}")
            continue

        if resolved.is_file():
            if resolved.suffix.lower() in {".xlsx", ".xls"}:
                files.append(str(resolved))
            else:
                warnings.append(f"Ignored non-excel file: {resolved}")
            continue

        if resolved.is_dir():
            if matched_folder is None:
                matched_folder = str(resolved)
            files.extend(_list_excel_in_dir(resolved))
            continue

    files = _dedup_keep_order(files)
    return files, matched_folder, warnings


def _looks_like_typhoon_query(query: str) -> bool:
    q = str(query or "").lower()
    keywords = ("typhoon", "tropical cyclone", "bst_all", "jma", "scs", "台风", "风圈")
    return any(k in q for k in keywords)


def _looks_like_wind_analysis_query(query: str) -> bool:
    q = str(query or "").lower()
    keywords = (
        "wind analysis",
        "wind condition",
        "wind resource",
        "weibull",
        "风况",
        "风资源",
        "风速分布",
        "风向",
    )
    return any(k in q for k in keywords)


def _looks_like_map_query(query: str) -> bool:
    q = str(query or "").lower()
    keywords = ("map", "visual", "visualize", "geo", "leaflet", "地图", "可视化")
    return any(k in q for k in keywords)


def _looks_like_typhoon_param_query(query: str) -> bool:
    q = str(query or "")
    has_lat = bool(re.search(r"(?:lat|latitude|纬度)\s*[:=]?\s*[-+]?\d+(?:\.\d+)?", q, flags=re.IGNORECASE))
    has_lon = bool(re.search(r"(?:lon|lng|longitude|经度)\s*[:=]?\s*[-+]?\d+(?:\.\d+)?", q, flags=re.IGNORECASE))
    has_radius = bool(
        re.search(r"(?:\br\b|radius|半径)\s*[:=]?\s*[-+]?\d+(?:\.\d+)?\s*(?:km)?", q, flags=re.IGNORECASE)
        or re.search(r"[-+]?\d+(?:\.\d+)?\s*km", q, flags=re.IGNORECASE)
    )
    return has_lat and has_lon and has_radius


def _extract_first_float(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return float(match.group(1))
        except Exception:
            continue
    return None


def _extract_months(text: str) -> list[int] | None:
    match = re.search(r"(?:months?|月份)\s*[:=]?\s*([0-9,\s-]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).replace(" ", "")
    months: set[int] = set()
    for token in raw.split(","):
        if not token:
            continue
        if "-" in token:
            parts = token.split("-", 1)
            try:
                start = int(parts[0])
                end = int(parts[1])
            except Exception:
                continue
            for month in range(start, end + 1):
                if 1 <= month <= 12:
                    months.add(month)
            continue
        try:
            month = int(token)
        except Exception:
            continue
        if 1 <= month <= 12:
            months.add(month)
    return sorted(months) if months else None


def _build_typhoon_tool_input(query: str, hint: dict[str, Any] | None) -> dict[str, Any]:
    payload: dict[str, Any] = dict(hint or {})
    if "model_scope" not in payload:
        payload["model_scope"] = "scs" if re.search(r"\bscs\b|南海", query, flags=re.IGNORECASE) else "total"

    if "lat" not in payload:
        payload["lat"] = _extract_first_float(
            query,
            [
                r"(?:lat|latitude|纬度)\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)",
                r"([-+]?\d+(?:\.\d+)?)\s*(?:[,\s]+)\s*[-+]?\d+(?:\.\d+)?",
            ],
        )
    if "lon" not in payload:
        payload["lon"] = _extract_first_float(
            query,
            [
                r"(?:lon|lng|longitude|经度)\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)",
                r"[-+]?\d+(?:\.\d+)?\s*(?:[,\s]+)\s*([-+]?\d+(?:\.\d+)?)",
            ],
        )

    if "radius_km" not in payload:
        payload["radius_km"] = _extract_first_float(
            query,
            [
                r"(?:R|radius(?:[_\-\s]*km)?|半径(?:[_\-\s]*km)?)\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)",
                r"([-+]?\d+(?:\.\d+)?)\s*km",
            ],
        )
    if "wind_threshold_kt" not in payload:
        kt = _extract_first_float(query, [r"(30|50)\s*kt", r"(30|50)\s*节"])
        if kt is not None:
            payload["wind_threshold_kt"] = int(kt)

    months = _extract_months(query)
    if months and "months" not in payload:
        payload["months"] = months

    year_start = _extract_first_float(query, [r"(19\d{2}|20\d{2})\s*[-~至到]\s*(19\d{2}|20\d{2})"])
    year_end_match = re.search(r"(19\d{2}|20\d{2})\s*[-~至到]\s*(19\d{2}|20\d{2})", query)
    if year_start is not None and year_end_match and "year_start" not in payload and "year_end" not in payload:
        payload["year_start"] = int(year_start)
        payload["year_end"] = int(float(year_end_match.group(2)))

    if payload.get("lat") is None or payload.get("lon") is None:
        payload.pop("lat", None)
        payload.pop("lon", None)
    return payload


def _infer_preferred_tool(state: AgentFlowState) -> str:
    hint = state.get("tool_input_hint")
    if isinstance(hint, dict) and any(k in hint for k in ("model_scope", "lat", "lon", "points")):
        return "analyze_typhoon_probability"
    if _looks_like_typhoon_query(str(state.get("user_query", ""))):
        return "analyze_typhoon_probability"
    return "analyze_wind_resource"


def _build_visual_workflow_plan(default_tool: str) -> list[dict[str, Any]]:
    if default_tool != "analyze_typhoon_probability":
        return build_default_plan("workflow", default_tool=default_tool)
    return [
        {"step": 1, "type": "tool", "name": "analyze_typhoon_probability", "tool": "analyze_typhoon_probability"},
        {"step": 2, "type": "tool", "name": "analyze_typhoon_map", "tool": "analyze_typhoon_map"},
        {"step": 3, "type": "llm", "name": "workflow_summary", "goal": "summarize map and risk findings"},
    ]


def _default_llm_config() -> dict[str, Any]:
    return {
        "base_url": os.getenv("ORCH_LLM_BASE_URL", os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8001")),
        "model": os.getenv("ORCH_LLM_MODEL", os.getenv("VLLM_MODEL", "")),
        "api_key": os.getenv("ORCH_LLM_API_KEY", os.getenv("VLLM_API_KEY", "EMPTY")),
        "timeout_seconds": int(os.getenv("ORCH_LLM_TIMEOUT", "60")),
    }


def _resolve_llm_max_tokens(state: AgentFlowState, default_value: int) -> int:
    cfg = state.get("llm_config") or {}
    try:
        raw = cfg.get("max_tokens", default_value) if isinstance(cfg, dict) else default_value
        value = int(raw)
    except Exception:
        value = int(default_value)
    return max(32, min(8192, value))


def _call_orchestrator_llm(
    state: AgentFlowState,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    max_tokens: int = 256,
) -> str:
    cfg = dict(_default_llm_config())
    cfg.update(state.get("llm_config") or {})
    base_url = str(cfg.get("base_url") or "").strip()
    model = str(cfg.get("model") or "").strip()
    api_key = str(cfg.get("api_key") or "EMPTY")
    timeout_seconds = int(cfg.get("timeout_seconds") or 60)

    if not base_url or not model:
        raise RuntimeError("Orchestrator LLM config is incomplete (base_url/model required).")

    url = base_url.rstrip("/") + "/v1/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content", "")
    return str(content).strip()


def _run_rag_query(state: AgentFlowState, query: str) -> dict[str, Any]:
    rag_api = os.getenv("AGENT_RAG_API_URL", "http://127.0.0.1:8787/api/chat")
    timeout = int(os.getenv("AGENT_RAG_TIMEOUT_SECONDS", "90"))
    payload = {
        "mode": "rag",
        "messages": [{"role": "user", "content": query}],
    }
    resp = requests.post(rag_api, json=payload, timeout=timeout)
    resp.raise_for_status()
    output = resp.json()
    if not isinstance(output, dict):
        raise RuntimeError("RAG endpoint returned non-dict payload.")
    return output


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_typhoon_fallback_summary(tool_result: dict[str, Any]) -> str | None:
    def _pick_probability_result(payload: dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(payload.get("metrics"), dict):
            return payload
        batch = payload.get("batch_results")
        if isinstance(batch, list):
            for item in batch:
                if not isinstance(item, dict):
                    continue
                if str(item.get("tool") or "") != "analyze_typhoon_probability":
                    continue
                result = item.get("result")
                if isinstance(result, dict) and isinstance(result.get("metrics"), dict):
                    return result
        return None

    prob = _pick_probability_result(tool_result)
    if not prob:
        return None

    metrics = prob.get("metrics") or {}
    model_scope = str(prob.get("model_scope") or prob.get("input", {}).get("model_scope") or "").lower()

    if model_scope == "scs":
        return (
            "台风概率分析完成（SCS）。"
            f"N_all={metrics.get('N_all')}，"
            f"N_enterSCS={metrics.get('N_enterSCS')}，"
            f"N_hit={metrics.get('N_hit')}，"
            f"P(impact|SCS)={metrics.get('p_cond_impact_given_SCS')}，"
            f"P(impact∩SCS)={metrics.get('p_abs_impact_and_SCS')}。"
        )

    return (
        "台风概率分析完成（Total）。"
        f"N_storm={metrics.get('N_storm')}，"
        f"N_hit={metrics.get('N_hit')}，"
        f"P_storm={metrics.get('p_storm')}，"
        f"P_year={metrics.get('p_year')}。"
    )


def _new_step_result(*, step: dict[str, Any], status: str, data: dict[str, Any] | None = None, error: str | None = None, started_at: float | None = None) -> dict[str, Any]:
    started = started_at if started_at is not None else time.time()
    return {
        "step": int(step.get("step", 0) or 0),
        "type": str(step.get("type", "")),
        "name": str(step.get("name", "")),
        "tool": step.get("tool"),
        "status": status,
        "started_at": _utc_now_iso(),
        "duration_ms": int(max(0.0, (time.time() - started) * 1000.0)),
        "data": data or {},
        "error": error,
    }


def input_preprocess(state: AgentFlowState) -> AgentFlowState:
    query = state.get("user_query") or ""
    if not query:
        # Backward-compatible fallback for legacy entry field.
        query = str(state.get("request", "")).strip()  # type: ignore[arg-type]

    hint = state.get("file_path")
    if not hint:
        hinted = str(state.get("excel_path_hint", "")).strip()  # type: ignore[arg-type]
        hint = hinted or None

    file_paths, data_folder, matched_warnings = _resolve_excel_candidates(query, hint)
    file_path = file_paths[0] if file_paths else None
    tool_input_hint = state.get("tool_input_hint")

    next_state: AgentFlowState = {
        "request_id": str(state.get("request_id") or ""),
        "user_query": query,
        "session_id": str(state.get("session_id") or "default"),
        "file_path": file_path,
        "file_paths": file_paths,
        "data_folder": data_folder,
        "warnings": list(state.get("warnings", [])),
        "workflow_results": list(state.get("workflow_results", [])),
        "trace": list(state.get("trace", [])),
    }
    if isinstance(tool_input_hint, dict):
        next_state["tool_input_hint"] = dict(tool_input_hint)
    next_state["warnings"].extend(matched_warnings)
    if state.get("llm_config"):
        next_state["llm_config"] = dict(state.get("llm_config") or {})

    trace(
        next_state,
        step="input_preprocess",
        status="ok",
        message="Captured user query and resolved excel files/folder.",
        details={
            "request_id": next_state.get("request_id"),
            "file_path": file_path,
            "file_paths_count": len(file_paths),
            "data_folder": data_folder,
            "session_id": next_state["session_id"],
        },
    )
    return next_state


def _default_routing_policy() -> dict[str, Any]:
    return {
        "thresholds": {
            "domain_confidence": 0.60,
            "mode_confidence": 0.65,
        },
        "rules": [
            {
                "id": "R-001",
                "match": "domain_confidence_below",
                "route_to": "clarify_node",
                "reason": "business domain confidence below threshold",
            },
            {
                "id": "R-002",
                "match": "mode_confidence_below",
                "route_to": "clarify_node",
                "reason": "execution mode confidence below threshold",
            },
            {
                "id": "R-003",
                "match": "missing_slots_for_execution",
                "route_to": "clarify_node",
                "reason": "required slots are missing for execution",
            },
            {
                "id": "R-004",
                "match": "high_risk_confirm",
                "route_to": "clarify_node",
                "reason": "high-risk action requires explicit confirmation",
            },
            {
                "id": "R-005",
                "match": "tool_mismatch",
                "route_to": "fallback_or_escalation",
                "reason": "tool capability mismatch",
            },
            {
                "id": "R-101",
                "match": "mode_is_query",
                "route_to": "rag_executor",
                "reason": "query mode with complete context",
            },
            {
                "id": "R-102",
                "match": "mode_is_batch",
                "route_to": "workflow_planner",
                "reason": "batch mode requires multi-step workflow",
            },
            {
                "id": "R-103",
                "match": "mode_in_mutation",
                "route_to": "tool_executor",
                "reason": "single tool execution mode",
            },
            {
                "id": "R-999",
                "match": "default",
                "route_to": "clarify_node",
                "reason": "default clarify fallback",
            },
        ],
    }


def _default_routing_policy_path() -> Path:
    # graph/nodes/agent.py -> project root
    root = Path(__file__).resolve().parents[2]
    return root / "configs" / "agent_routing_policy.json"


def _load_routing_policy(state: AgentFlowState) -> dict[str, Any]:
    policy = deepcopy(_default_routing_policy())
    cfg_path_raw = os.getenv("AGENT_ROUTING_POLICY_PATH", str(_default_routing_policy_path()))
    cfg_path = Path(cfg_path_raw).expanduser()
    if cfg_path.exists():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                thresholds = loaded.get("thresholds")
                if isinstance(thresholds, dict):
                    policy["thresholds"].update(
                        {
                            "domain_confidence": float(
                                thresholds.get("domain_confidence", policy["thresholds"]["domain_confidence"])
                            ),
                            "mode_confidence": float(
                                thresholds.get("mode_confidence", policy["thresholds"]["mode_confidence"])
                            ),
                        }
                    )
                if isinstance(loaded.get("rules"), list):
                    policy["rules"] = [r for r in loaded["rules"] if isinstance(r, dict)] or policy["rules"]
        except Exception as exc:
            _append_warning(state, f"Routing policy config load failed, using defaults: {exc}")
    return policy


def _rule_matches(
    rule_match: str,
    *,
    domain_confidence: float,
    mode_confidence: float,
    mode: str,
    missing_slots: list[str],
    tool_capability_match: bool,
    risk_level: str,
    need_confirm: bool,
    thresholds: dict[str, float],
) -> bool:
    if rule_match == "domain_confidence_below":
        return domain_confidence < float(thresholds.get("domain_confidence", 0.60))
    if rule_match == "mode_confidence_below":
        return mode_confidence < float(thresholds.get("mode_confidence", 0.65))
    if rule_match == "missing_slots_for_execution":
        return bool(missing_slots) and mode in {"create", "update", "approve", "batch"}
    if rule_match == "high_risk_confirm":
        return need_confirm and risk_level == "high"
    if rule_match == "tool_mismatch":
        return not tool_capability_match
    if rule_match == "mode_is_query":
        return mode == "query"
    if rule_match == "mode_is_batch":
        return mode == "batch"
    if rule_match == "mode_in_mutation":
        return mode in {"create", "update", "approve"}
    if rule_match == "default":
        return True
    return False


def _infer_slots_and_missing(state: AgentFlowState) -> tuple[dict[str, Any], list[str]]:
    slots: dict[str, Any] = {}
    missing_slots: list[str] = []
    query = str(state.get("user_query", ""))
    file_paths = list(state.get("file_paths", []))

    if file_paths:
        slots["excel_paths"] = file_paths
    if state.get("data_folder"):
        slots["data_folder"] = state.get("data_folder")

    hint = state.get("tool_input_hint") if isinstance(state.get("tool_input_hint"), dict) else None
    typhoon_payload = _build_typhoon_tool_input(query, hint)
    slots["typhoon_payload"] = typhoon_payload

    domain = str(state.get("domain") or "").strip().lower()
    mode = str(state.get("mode") or "").strip().lower()
    if domain == "wind_analysis" and mode in {"create", "update", "batch"} and not file_paths:
        missing_slots.append("excel_path")

    if domain == "typhoon" and mode in {"create", "update", "batch"}:
        has_point = bool(typhoon_payload.get("points"))
        has_lat_lon = typhoon_payload.get("lat") is not None and typhoon_payload.get("lon") is not None
        if not has_point and not has_lat_lon:
            missing_slots.append("lat_lon")
        if typhoon_payload.get("radius_km") is None and not has_point:
            missing_slots.append("radius_km")

    return slots, _dedup_keep_order(missing_slots)


def _build_clarify_question(state: AgentFlowState) -> str:
    missing = list(state.get("missing_slots", []))
    if "excel_path" in missing:
        return "请提供可访问的 .xlsx/.xls 文件路径或数据文件夹。"
    if "lat_lon" in missing and "radius_km" in missing:
        return "请补充台风分析参数：lat、lon、radius_km（单位 km）。"
    if "lat_lon" in missing:
        return "请补充台风分析参数：lat 和 lon。"
    if "radius_km" in missing:
        return "请补充台风分析参数：radius_km（单位 km）。"
    return "请补充业务域或执行意图的关键信息，以便我正确路由。"


def _intent_from_mode(mode: str) -> str:
    norm = str(mode or "").strip().lower()
    if norm == "query":
        return "rag"
    if norm == "batch":
        return "workflow"
    if norm in {"create", "update", "approve"}:
        return "tool"
    return "rag"


def domain_router(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    query = str(state.get("user_query", "")).strip()
    file_paths = list(state.get("file_paths", []))
    preferred_tool = _infer_preferred_tool(state)

    if _looks_like_typhoon_query(query) or preferred_tool == "analyze_typhoon_probability":
        fallback_domain, fallback_confidence, fallback_candidates = "typhoon", 0.90, ["typhoon", "knowledge"]
    elif _looks_like_wind_analysis_query(query):
        fallback_domain, fallback_confidence, fallback_candidates = "wind_analysis", 0.85, ["wind_analysis", "knowledge"]
    elif file_paths:
        fallback_domain, fallback_confidence, fallback_candidates = "wind_analysis", 0.85, ["wind_analysis", "knowledge"]
    elif len(query) <= 1:
        fallback_domain, fallback_confidence, fallback_candidates = "unknown", 0.45, ["unknown", "knowledge"]
    else:
        fallback_domain, fallback_confidence, fallback_candidates = "knowledge", 0.68, ["knowledge", "unknown"]

    prompt = (
        "You are a business-domain router. "
        "Classify query into one domain: knowledge, wind_analysis, typhoon, unknown. "
        "Return strict JSON only: {\"domain\":\"...\",\"confidence\":0.xx,\"candidates\":[\"...\",\"...\"]}."
    )
    user_payload = json.dumps(
        {
            "query": query,
            "file_paths_count": len(file_paths),
            "data_folder": state.get("data_folder"),
            "tool_input_hint": state.get("tool_input_hint"),
            "typhoon_query": _looks_like_typhoon_query(query),
        },
        ensure_ascii=False,
    )

    try:
        raw = _call_orchestrator_llm(
            next_state,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.0,
            max_tokens=120,
        )
        parsed = json.loads(raw)
        domain = str(parsed.get("domain", fallback_domain)).strip().lower()
        if domain not in {"knowledge", "wind_analysis", "typhoon", "unknown"}:
            raise ValueError(f"Unsupported domain: {domain}")
        confidence = float(parsed.get("confidence", fallback_confidence))
        candidates_raw = parsed.get("candidates", fallback_candidates)
        if isinstance(candidates_raw, list):
            candidates = [str(item).strip().lower() for item in candidates_raw if str(item).strip()]
        else:
            candidates = list(fallback_candidates)
        candidates = _dedup_keep_order(candidates or list(fallback_candidates))
    except Exception as exc:
        domain = fallback_domain
        confidence = fallback_confidence
        candidates = list(fallback_candidates)
        _append_warning(next_state, f"Domain router fallback used: {exc}")

    if _looks_like_typhoon_query(query) and domain != "typhoon":
        domain = "typhoon"
        confidence = max(confidence, 0.70)
        candidates = _dedup_keep_order(["typhoon"] + candidates)

    next_state["normalized_query"] = query
    next_state["domain"] = domain
    next_state["domain_confidence"] = confidence
    next_state["domain_candidates"] = candidates
    scores = dict(next_state.get("scores", {}))
    scores["domain"] = confidence
    next_state["scores"] = scores

    trace(
        next_state,
        "domain_router",
        "ok",
        "Identified business domain.",
        {"domain": domain, "confidence": confidence, "candidates": candidates},
    )
    return next_state


def mode_router(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    domain = str(state.get("domain", "unknown")).strip().lower()
    query = str(state.get("normalized_query", state.get("user_query", ""))).strip()

    if domain == "knowledge":
        fallback_mode, fallback_confidence = "query", 0.90
    elif domain == "typhoon":
        if _looks_like_map_query(query) or _looks_like_typhoon_param_query(query):
            fallback_mode, fallback_confidence = "batch", 0.88
        else:
            fallback_mode, fallback_confidence = "create", 0.82
    elif domain == "wind_analysis":
        fallback_mode, fallback_confidence = "create", 0.84
    else:
        fallback_mode, fallback_confidence = "clarify", 0.50

    prompt = (
        "You are an execution-mode router inside a business domain. "
        "Classify mode into one of: query, create, update, approve, batch, clarify, unknown. "
        "Return strict JSON only: {\"mode\":\"...\",\"confidence\":0.xx}."
    )
    user_payload = json.dumps(
        {
            "domain": domain,
            "query": query,
            "file_paths_count": len(state.get("file_paths", [])),
            "tool_input_hint": state.get("tool_input_hint"),
        },
        ensure_ascii=False,
    )
    try:
        raw = _call_orchestrator_llm(
            next_state,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.0,
            max_tokens=80,
        )
        parsed = json.loads(raw)
        mode = str(parsed.get("mode", fallback_mode)).strip().lower()
        if mode not in {"query", "create", "update", "approve", "batch", "clarify", "unknown"}:
            raise ValueError(f"Unsupported mode: {mode}")
        confidence = float(parsed.get("confidence", fallback_confidence))
    except Exception as exc:
        mode = fallback_mode
        confidence = fallback_confidence
        _append_warning(next_state, f"Mode router fallback used: {exc}")

    if domain == "knowledge" and mode not in {"query", "clarify"}:
        mode = "query"
        confidence = max(confidence, 0.70)
    if domain == "wind_analysis" and mode == "query":
        # Wind-analysis requests should execute deterministic analysis tools instead of RAG query path.
        mode = "create"
        confidence = max(confidence, 0.70)
    if domain == "typhoon" and mode != "clarify":
        # Typhoon requests should run deterministic workflow (probability + map) instead of single-tool path.
        mode = "batch"
        confidence = max(confidence, 0.70)

    next_state["mode"] = mode
    next_state["mode_confidence"] = confidence
    slots, missing_slots = _infer_slots_and_missing(next_state)
    next_state["slots"] = slots
    next_state["missing_slots"] = missing_slots
    scores = dict(next_state.get("scores", {}))
    scores["mode"] = confidence
    next_state["scores"] = scores
    trace(
        next_state,
        "mode_router",
        "ok",
        "Identified execution mode.",
        {"mode": mode, "confidence": confidence, "missing_slots": missing_slots},
    )
    return next_state


def policy_gate(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    mode = str(state.get("mode", "unknown")).strip().lower()
    domain = str(state.get("domain", "unknown")).strip().lower()
    preferred_tool = _infer_preferred_tool(state)

    if mode in {"approve", "update"}:
        risk_level = "high"
    elif mode == "batch":
        risk_level = "medium"
    else:
        risk_level = "low"
    need_confirm = risk_level == "high"

    tool_capability_match = True
    intent = _intent_from_mode(mode)
    if intent in {"tool", "workflow"}:
        try:
            if domain == "wind_analysis":
                TOOL_REGISTRY.get("analyze_wind_resource")
            elif preferred_tool == "analyze_typhoon_probability":
                TOOL_REGISTRY.get("analyze_typhoon_probability")
                if intent == "workflow":
                    TOOL_REGISTRY.get("analyze_typhoon_map")
            else:
                TOOL_REGISTRY.get(preferred_tool)
        except Exception:
            tool_capability_match = False

    next_state["risk_level"] = risk_level
    next_state["need_confirm"] = need_confirm
    next_state["tool_capability_match"] = tool_capability_match
    scores = dict(next_state.get("scores", {}))
    scores["risk"] = 1.0 if risk_level == "high" else (0.6 if risk_level == "medium" else 0.2)
    next_state["scores"] = scores
    trace(
        next_state,
        "policy_gate",
        "ok",
        "Evaluated risk and capability constraints.",
        {
            "risk_level": risk_level,
            "need_confirm": need_confirm,
            "tool_capability_match": tool_capability_match,
            "preferred_tool": preferred_tool,
        },
    )
    return next_state


def flow_entry(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    policy = _load_routing_policy(next_state)
    thresholds = policy.get("thresholds", {})
    rules = policy.get("rules", [])
    domain_confidence = float(state.get("domain_confidence", 0.0) or 0.0)
    mode_confidence = float(state.get("mode_confidence", 0.0) or 0.0)
    mode = str(state.get("mode", "unknown")).strip().lower()
    missing_slots = list(state.get("missing_slots", []))
    tool_capability_match = bool(state.get("tool_capability_match", True))
    risk_level = str(state.get("risk_level", "low")).strip().lower()
    need_confirm = bool(state.get("need_confirm", False))
    rule_id, route_to, route_reason = "R-999", "clarify_node", "default clarify fallback"
    for rule in rules:
        rule_match = str(rule.get("match", "")).strip()
        if not _rule_matches(
            rule_match,
            domain_confidence=domain_confidence,
            mode_confidence=mode_confidence,
            mode=mode,
            missing_slots=missing_slots,
            tool_capability_match=tool_capability_match,
            risk_level=risk_level,
            need_confirm=need_confirm,
            thresholds={
                "domain_confidence": float(thresholds.get("domain_confidence", 0.60) or 0.60),
                "mode_confidence": float(thresholds.get("mode_confidence", 0.65) or 0.65),
            },
        ):
            continue
        rule_id = str(rule.get("id", "R-999"))
        route_to = str(rule.get("route_to", "clarify_node"))
        route_reason = str(rule.get("reason", "default clarify fallback"))
        break

    next_state["route_to"] = route_to
    next_state["route_reason"] = route_reason
    next_state["rule_id"] = rule_id
    next_state["clarify_question"] = _build_clarify_question(next_state) if route_to == "clarify_node" else ""

    if route_to == "rag_executor":
        next_state["intent"] = "rag"
        next_state["intent_confidence"] = mode_confidence
    elif route_to == "tool_executor":
        next_state["intent"] = "tool"
        next_state["intent_confidence"] = mode_confidence
        if not next_state.get("workflow_plan"):
            next_state["workflow_plan"] = build_default_plan("tool", default_tool=_infer_preferred_tool(next_state))
    elif route_to == "workflow_planner":
        next_state["intent"] = "workflow"
        next_state["intent_confidence"] = mode_confidence
    else:
        next_state["intent"] = "rag"
        next_state["intent_confidence"] = max(0.5, mode_confidence)

    trace(
        next_state,
        "flow_entry",
        "ok",
        "Selected graph branch by routing rules.",
        {
            "route_to": route_to,
            "route_reason": route_reason,
            "rule_id": rule_id,
            "domain_confidence": domain_confidence,
            "mode_confidence": mode_confidence,
        },
    )
    return next_state


def next_agent_route(state: AgentFlowState) -> str:
    route = str(state.get("route_to") or "").strip()
    if route in {"clarify_node", "fallback_or_escalation", "rag_executor", "tool_executor", "workflow_planner"}:
        return route
    return "clarify_node"


def clarify_node(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    question = str(state.get("clarify_question") or "").strip() or _build_clarify_question(state)
    next_state["final_answer"] = f"为继续执行，我需要补充信息：{question}"
    trace(
        next_state,
        "clarify_node",
        "ok",
        "Generated clarify question for missing or ambiguous routing context.",
        {"question": question},
    )
    return next_state


def fallback_or_escalation(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    reason = str(state.get("route_reason") or state.get("fallback_reason") or "tool capability mismatch")
    next_state["fallback_reason"] = reason
    next_state["final_answer"] = f"当前请求无法自动执行：{reason}。请检查工具能力或转人工处理。"
    trace(
        next_state,
        "fallback_or_escalation",
        "warn",
        "Routed to fallback/escalation branch.",
        {"reason": reason},
    )
    return next_state


def intent_router(state: AgentFlowState) -> AgentFlowState:
    # Backward-compat entrypoint: keep old function name while routing through new graph stages.
    next_state = domain_router(state)
    next_state = mode_router(next_state)
    next_state = policy_gate(next_state)
    next_state = flow_entry(next_state)
    trace(
        next_state,
        "intent_router",
        "ok",
        "Backward-compatible intent routing finished via domain/mode/policy/flow stages.",
        {"intent": next_state.get("intent"), "route_to": next_state.get("route_to"), "rule_id": next_state.get("rule_id")},
    )
    return next_state


def workflow_planner(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")
    preferred_tool = _infer_preferred_tool(state)
    query_text = str(state.get("user_query", ""))
    if intent == "workflow" and _looks_like_typhoon_query(query_text):
        default_plan = _build_visual_workflow_plan(preferred_tool)
    else:
        default_plan = build_default_plan(intent, default_tool=preferred_tool)

    if intent == "workflow":
        # Typhoon workflow is fixed and should always include map generation.
        if _looks_like_typhoon_query(query_text):
            next_state["workflow_plan"] = normalize_workflow_plan(default_plan, default_tool=preferred_tool)
            trace(next_state, "workflow_planner", "ok", "Built deterministic typhoon workflow plan.", {"plan": next_state["workflow_plan"]})
            return next_state

        prompt = (
            "You are a workflow planner. Generate execution plan in JSON list. "
            "Allowed step types: rag, tool, llm. "
            "Always keep 2~4 steps and include rag/tool only when needed. Return JSON only."
        )
        user_payload = json.dumps(
            {
                "query": state.get("user_query", ""),
                "file_paths_count": len(state.get("file_paths", [])),
                "available_tools": ["analyze_wind_resource", "analyze_typhoon_probability", "analyze_typhoon_map"],
            },
            ensure_ascii=False,
        )
        try:
            raw = _call_orchestrator_llm(
                next_state,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_payload},
                ],
                temperature=0.0,
                max_tokens=300,
            )
            plan = normalize_workflow_plan(json.loads(raw), default_tool=preferred_tool)
            plan = [s for s in plan if str(s.get("type", "")).lower() != "rag"]
            if not plan:
                plan = normalize_workflow_plan(default_plan, default_tool=preferred_tool)
            next_state["workflow_plan"] = plan
            trace(next_state, "workflow_planner", "ok", "Built workflow plan from LLM.", {"plan": plan})
            return next_state
        except Exception as exc:
            _append_warning(next_state, f"Workflow planner fallback used: {exc}")
            next_state["workflow_plan"] = default_plan
            trace(
                next_state,
                "workflow_planner",
                "warn",
                "Workflow planner fallback used.",
                {"reason": str(exc), "plan": next_state["workflow_plan"]},
            )
            return next_state

    next_state["workflow_plan"] = default_plan

    trace(next_state, "workflow_planner", "ok", "Built workflow plan.", {"plan": next_state.get("workflow_plan", [])})
    return next_state


def rag_executor(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")
    if intent != "rag":
        trace(next_state, "rag_executor", "skip", "Skipped rag executor because intent is not rag.")
        return next_state

    try:
        t0 = time.time()
        rag_result = _run_rag_query(next_state, str(state.get("user_query", "")))
        next_state["rag_result"] = rag_result
        results = list(next_state.get("workflow_results", []))
        results.append(
            _new_step_result(
                step={"step": 1, "type": "rag", "name": "domain_knowledge"},
                status="ok",
                data={"rag_result": rag_result},
                started_at=t0,
            )
        )
        next_state["workflow_results"] = results
        trace(next_state, "rag_executor", "ok", "Executed RAG endpoint.")
    except Exception as exc:
        next_state["rag_result"] = {"error": str(exc)}
        _append_warning(next_state, f"RAG execution fallback used: {exc}")
        results = list(next_state.get("workflow_results", []))
        results.append(
            _new_step_result(
                step={"step": 1, "type": "rag", "name": "domain_knowledge"},
                status="error",
                error=str(exc),
            )
        )
        next_state["workflow_results"] = results
        trace(next_state, "rag_executor", "warn", "RAG execution fallback used.", {"reason": str(exc)})
    return next_state


def tool_executor(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")
    if intent not in {"tool", "workflow"}:
        trace(next_state, "tool_executor", "skip", "Skipped tool executor because intent is rag.")
        return next_state

    preferred_tool = _infer_preferred_tool(state)
    try:
        plan = normalize_workflow_plan(
            list(state.get("workflow_plan", [])) or build_default_plan(intent, default_tool=preferred_tool),
            default_tool=preferred_tool,
        )
    except Exception as exc:
        _append_warning(next_state, f"Invalid workflow plan, fallback applied: {exc}")
        plan = build_default_plan(intent, default_tool=preferred_tool)
    next_state["workflow_plan"] = plan

    file_paths = list(state.get("file_paths", []))

    workflow_results = list(next_state.get("workflow_results", []))
    batch_results: list[dict[str, Any]] = []
    last_typhoon_result: dict[str, Any] | None = None

    for item in plan:
        step_type = str(item.get("type", "")).strip().lower()
        step_started = time.time()

        if step_type == "rag":
            workflow_results.append(
                _new_step_result(
                    step=item,
                    status="skip",
                    data={"reason": "rag_disabled_for_non_rag_modes"},
                    started_at=step_started,
                )
            )
            trace(next_state, "tool_executor", "skip", "Skipped workflow rag step (disabled outside rag mode).", {"step": item})
            continue

        if step_type == "llm":
            payload = json.dumps(
                {
                    "query": state.get("user_query", ""),
                    "goal": item.get("goal", "summarize"),
                    "intermediate_results": workflow_results,
                },
                ensure_ascii=False,
            )
            try:
                llm_text = _call_orchestrator_llm(
                    next_state,
                    messages=[
                        {"role": "system", "content": "Summarize current workflow progress in concise Chinese."},
                        {"role": "user", "content": payload},
                    ],
                    temperature=0.2,
                    max_tokens=220,
                )
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="ok",
                        data={"goal": item.get("goal"), "text": llm_text},
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "ok", "Executed workflow llm step.", {"step": item})
            except Exception as exc:
                _append_warning(next_state, f"Workflow llm step fallback used: {exc}")
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="error",
                        error=str(exc),
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "warn", "Workflow llm step failed.", {"step": item, "reason": str(exc)})
            continue

        if step_type != "tool":
            _append_warning(next_state, f"Unsupported workflow step type: {step_type}")
            workflow_results.append(
                _new_step_result(
                    step=item,
                    status="error",
                    error=f"unsupported step type: {step_type}",
                    started_at=step_started,
                )
            )
            trace(next_state, "tool_executor", "warn", "Unsupported workflow step type.", {"step": item})
            continue

        tool_name = str(item.get("tool") or item.get("name") or preferred_tool)
        next_state["selected_tool"] = tool_name

        if tool_name == "analyze_typhoon_probability":
            payload = _build_typhoon_tool_input(
                str(state.get("user_query", "")),
                state.get("tool_input_hint") if isinstance(state.get("tool_input_hint"), dict) else None,
            )
            if "lat" not in payload and "points" not in payload:
                next_state["error"] = "Missing lat/lon for typhoon probability execution."
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="error",
                        error=next_state["error"],
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "error", next_state["error"])
                next_state["workflow_results"] = workflow_results
                return next_state

            next_state["tool_input"] = payload
            try:
                output = TOOL_REGISTRY.execute(tool_name, payload)
                if isinstance(output, dict):
                    last_typhoon_result = output
                batch_item = {"tool": tool_name, "input": payload, "result": output}
                batch_results.append(batch_item)
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="ok",
                        data=batch_item,
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "ok", "Executed typhoon probability tool.", {"tool": tool_name})
            except Exception as exc:
                _append_warning(next_state, f"Tool execution failed ({tool_name}): {exc}")
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="error",
                        error=str(exc),
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "warn", "Tool execution failed.", {"tool": tool_name, "reason": str(exc)})
            continue

        if tool_name == "analyze_typhoon_map":
            map_payload: dict[str, Any] = {}
            if isinstance(state.get("tool_input_hint"), dict):
                map_payload.update(dict(state.get("tool_input_hint") or {}))
            if isinstance(last_typhoon_result, dict):
                map_payload["typhoon_result"] = last_typhoon_result
            elif isinstance(next_state.get("tool_result"), dict):
                map_payload["typhoon_result"] = dict(next_state.get("tool_result") or {})

            next_state["tool_input"] = map_payload
            try:
                output = TOOL_REGISTRY.execute(tool_name, map_payload)
                batch_item = {"tool": tool_name, "input": map_payload, "result": output}
                batch_results.append(batch_item)
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="ok",
                        data=batch_item,
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "ok", "Executed typhoon map tool.", {"tool": tool_name})
            except Exception as exc:
                _append_warning(next_state, f"Tool execution failed ({tool_name}): {exc}")
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="error",
                        error=str(exc),
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "warn", "Tool execution failed.", {"tool": tool_name, "reason": str(exc)})
            continue

        if not file_paths:
            next_state["error"] = "Missing excel file path for tool execution."
            trace(next_state, "tool_executor", "error", next_state["error"])
            workflow_results.append(
                _new_step_result(
                    step=item,
                    status="error",
                    error=next_state["error"],
                    started_at=step_started,
                )
            )
            next_state["workflow_results"] = workflow_results
            return next_state

        for file_path in file_paths:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                _append_warning(next_state, f"Excel file not found, skipped: {file_path}")
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="error",
                        error=f"excel file not found: {file_path}",
                        started_at=step_started,
                    )
                )
                trace(next_state, "tool_executor", "warn", "Excel file missing, skipped.", {"file_path": file_path})
                continue

            payload = {"excel_path": str(path)}
            next_state["tool_input"] = payload
            try:
                output = TOOL_REGISTRY.execute(tool_name, payload)
                batch_item = {"tool": tool_name, "excel_path": str(path.resolve()), "result": output}
                batch_results.append(batch_item)
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="ok",
                        data=batch_item,
                        started_at=step_started,
                    )
                )
                trace(
                    next_state,
                    "tool_executor",
                    "ok",
                    "Executed wind analysis tool.",
                    {"excel_path": str(path.resolve()), "tool": tool_name},
                )
            except Exception as exc:
                _append_warning(next_state, f"Tool execution failed ({tool_name}): {exc}")
                workflow_results.append(
                    _new_step_result(
                        step=item,
                        status="error",
                        error=str(exc),
                        started_at=step_started,
                    )
                )
                trace(
                    next_state,
                    "tool_executor",
                    "warn",
                    "Tool execution failed.",
                    {"excel_path": str(path.resolve()), "tool": tool_name, "reason": str(exc)},
                )

    next_state["workflow_results"] = workflow_results

    if batch_results:
        if len(batch_results) == 1:
            next_state["tool_result"] = batch_results[0]["result"]
            next_state["file_path"] = batch_results[0].get("excel_path")
        else:
            next_state["tool_result"] = {
                "success": all(bool((item["result"] or {}).get("success")) for item in batch_results),
                "batch_results": batch_results,
            }
            next_state["file_path"] = batch_results[0].get("excel_path")
        trace(next_state, "tool_executor", "ok", "Workflow tool execution completed.", {"batch_count": len(batch_results)})
    else:
        _append_warning(next_state, "No tool output produced from workflow execution.")
        trace(next_state, "tool_executor", "warn", "No tool output produced from workflow execution.")

    return next_state


def answer_synthesizer(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)

    if str(state.get("final_answer") or "").strip():
        trace(next_state, "answer_synthesizer", "ok", "Reused prebuilt final answer from upstream branch.")
        return next_state
    if state.get("error"):
        next_state["final_answer"] = f"执行失败：{state.get('error')}"
        return next_state

    intent = state.get("intent", "rag")
    tool_result = state.get("tool_result")
    rag_result = state.get("rag_result") or {}
    workflow_results = state.get("workflow_results", [])

    if intent == "rag":
        answer = str(rag_result.get("answer") or rag_result.get("output_text") or "").strip()
        if answer:
            next_state["final_answer"] = answer
            trace(next_state, "answer_synthesizer", "ok", "Returned answer from rag result.")
            return next_state
        if rag_result.get("error"):
            next_state["final_answer"] = f"RAG 服务暂不可用：{rag_result.get('error')}"
            trace(next_state, "answer_synthesizer", "warn", "RAG service unavailable, returned fallback text.")
            return next_state
        next_state["final_answer"] = "RAG 已执行，但未返回可解析答案。"
        trace(next_state, "answer_synthesizer", "warn", "RAG result has no answer text.")
        return next_state

    if intent in {"tool", "workflow"} and not tool_result and not workflow_results:
        next_state["final_answer"] = "这是分析请求，但未找到可执行的数据文件。请提供 .xlsx/.xls 文件路径或文件夹。"
        trace(next_state, "answer_synthesizer", "warn", "Missing workflow result for analysis intent.")
        return next_state

    prompt = (
        "You are a senior wind-energy analyst. "
        "Explain the final result in concise Chinese: key findings, risks/warnings, and next suggestions."
    )
    user_payload = json.dumps(
        {
            "query": state.get("user_query", ""),
            "intent": intent,
            "tool_result": tool_result,
            "rag_result": rag_result,
            "workflow_plan": state.get("workflow_plan", []),
            "workflow_results": workflow_results,
            "warnings": state.get("warnings", []),
        },
        ensure_ascii=False,
    )

    try:
        final_answer = _call_orchestrator_llm(
            next_state,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.2,
            max_tokens=_resolve_llm_max_tokens(next_state, 500),
        )
    except Exception as exc:
        _append_warning(next_state, f"Answer synthesizer fallback used: {exc}")
        if isinstance(tool_result, dict) and "batch_results" in tool_result:
            typhoon_text = _build_typhoon_fallback_summary(tool_result)
            if typhoon_text:
                final_answer = typhoon_text
                next_state["final_answer"] = final_answer
                trace(next_state, "answer_synthesizer", "ok", "Generated fallback typhoon summary from tool result.")
                return next_state
            batch_count = len(tool_result.get("batch_results", []))
            detail_text = json.dumps(tool_result, ensure_ascii=False)[:6000]
            final_answer = (
                f"分析完成：共处理 {batch_count} 个结果项。\n\n"
                f"由于总结模型暂不可用，以下为结构化结果摘要（截断展示）：\n{detail_text}"
            )
        elif isinstance(tool_result, dict) and bool(tool_result.get("success", False)):
            typhoon_text = _build_typhoon_fallback_summary(tool_result)
            if typhoon_text:
                final_answer = typhoon_text
                next_state["final_answer"] = final_answer
                trace(next_state, "answer_synthesizer", "ok", "Generated fallback typhoon summary from tool result.")
                return next_state
            data = tool_result.get("data") or {}
            weibull = data.get("weibull_fit") or {}
            final_answer = (
                f"分析完成：valid_rows={data.get('valid_rows')}，"
                f"Weibull(k={weibull.get('shape_k')}, A={weibull.get('scale_a')})。"
            )
        elif rag_result:
            final_answer = "流程执行完成，已获得 RAG 结果，但总结模型当前不可用。"
        else:
            final_answer = f"流程执行完成，但结果异常：{state.get('warnings', [])}"

    next_state["final_answer"] = final_answer
    trace(next_state, "answer_synthesizer", "ok", "Generated final answer.")
    return next_state

