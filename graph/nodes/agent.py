"""Agent 节点实现：请求预处理、意图识别、流程规划、RAG/工具执行与结果解释。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import requests

from tools.wind_analysis_tool import build_wind_analysis_tool

from graph.state import AgentFlowState, TraceDetails


def trace(state: AgentFlowState, step: str, status: str, message: str, details: TraceDetails = None) -> None:
    events = list(state.get("trace", []))
    events.append(
        {
            "step": step,
            "status": status,
            "message": message,
            "details": details or {},
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

    folder_hint_pattern = r'([A-Za-z0-9_./\\-]+)\s*(?:文件夹|folder|目录)'
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
            # 仅路径不存在且像文件夹名称时，尝试名称匹配
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


def _default_llm_config() -> dict[str, Any]:
    return {
        "base_url": os.getenv("ORCH_LLM_BASE_URL", os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8001")),
        "model": os.getenv("ORCH_LLM_MODEL", os.getenv("VLLM_MODEL", "")),
        "api_key": os.getenv("ORCH_LLM_API_KEY", os.getenv("VLLM_API_KEY", "EMPTY")),
        "timeout_seconds": int(os.getenv("ORCH_LLM_TIMEOUT", "60")),
    }


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


def input_preprocess(state: AgentFlowState) -> AgentFlowState:
    query = state.get("user_query") or ""
    if not query:
        # 兼容旧入口字段
        query = str(state.get("request", "")).strip()  # type: ignore[arg-type]

    hint = state.get("file_path")
    if not hint:
        hinted = str(state.get("excel_path_hint", "")).strip()  # type: ignore[arg-type]
        hint = hinted or None

    file_paths, data_folder, matched_warnings = _resolve_excel_candidates(query, hint)
    file_path = file_paths[0] if file_paths else None

    next_state: AgentFlowState = {
        "user_query": query,
        "session_id": str(state.get("session_id") or "default"),
        "file_path": file_path,
        "file_paths": file_paths,
        "data_folder": data_folder,
        "warnings": list(state.get("warnings", [])),
        "workflow_results": list(state.get("workflow_results", [])),
        "trace": list(state.get("trace", [])),
    }
    next_state["warnings"].extend(matched_warnings)
    if state.get("llm_config"):
        next_state["llm_config"] = dict(state.get("llm_config") or {})

    trace(
        next_state,
        step="input_preprocess",
        status="ok",
        message="Captured user query and resolved excel files/folder.",
        details={
            "file_path": file_path,
            "file_paths_count": len(file_paths),
            "data_folder": data_folder,
            "session_id": next_state["session_id"],
        },
    )
    return next_state


def intent_router(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    query = state.get("user_query", "")
    file_paths = list(state.get("file_paths", []))

    fallback_intent = "tool" if file_paths else "rag"
    fallback_confidence = 0.6 if file_paths else 0.5

    prompt = (
        "You are an intent router for a wind-agent system. "
        "Classify user request into one intent: rag, tool, workflow. "
        "Return strict JSON only: {\"intent\":\"...\",\"confidence\":0.xx}."
    )
    user_payload = json.dumps(
        {"query": query, "file_paths_count": len(file_paths), "data_folder": state.get("data_folder")},
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
        intent = str(parsed.get("intent", fallback_intent)).strip().lower()
        if intent not in {"rag", "tool", "workflow"}:
            raise ValueError(f"Unsupported intent from LLM: {intent}")
        confidence = float(parsed.get("confidence", fallback_confidence))
        trace(
            next_state,
            step="intent_router",
            status="ok",
            message="Routed user intent via orchestrator LLM.",
            details={"intent": intent, "confidence": confidence},
        )
    except Exception as exc:
        intent = fallback_intent
        confidence = fallback_confidence
        _append_warning(next_state, f"Intent router fallback used: {exc}")
        trace(
            next_state,
            step="intent_router",
            status="warn",
            message="Intent router fallback used.",
            details={"intent": intent, "confidence": confidence, "reason": str(exc)},
        )

    next_state["intent"] = intent
    next_state["intent_confidence"] = confidence

    if intent in {"tool", "workflow"} and not file_paths:
        _append_warning(next_state, "Intent requires data analysis but no valid .xlsx/.xls file path was provided.")

    return next_state


def workflow_planner(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")

    if intent == "workflow":
        prompt = (
            "You are a workflow planner. Generate execution plan in JSON list. "
            "Allowed step types: rag, tool, llm. "
            "Always keep 2~4 steps and include rag/tool only when needed. Return JSON only."
        )
        user_payload = json.dumps(
            {
                "query": state.get("user_query", ""),
                "file_paths_count": len(state.get("file_paths", [])),
                "available_tools": ["analyze_wind_resource"],
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
            plan = json.loads(raw)
            if not isinstance(plan, list):
                raise ValueError("workflow plan must be a list")
            next_state["workflow_plan"] = plan
            trace(next_state, "workflow_planner", "ok", "Built workflow plan from LLM.", {"plan": plan})
            return next_state
        except Exception as exc:
            _append_warning(next_state, f"Workflow planner fallback used: {exc}")
            next_state["workflow_plan"] = [
                {"step": 1, "type": "rag", "name": "domain_knowledge"},
                {"step": 2, "type": "tool", "name": "analyze_wind_resource"},
                {"step": 3, "type": "llm", "goal": "summarize and provide recommendations"},
            ]
            trace(
                next_state,
                "workflow_planner",
                "warn",
                "Workflow planner fallback used.",
                {"reason": str(exc), "plan": next_state["workflow_plan"]},
            )
            return next_state

    if intent == "tool":
        next_state["workflow_plan"] = [{"step": 1, "type": "tool", "name": "analyze_wind_resource"}]
    else:
        next_state["workflow_plan"] = [{"step": 1, "type": "rag", "name": "domain_knowledge"}]

    trace(next_state, "workflow_planner", "ok", "Built workflow plan.", {"plan": next_state.get("workflow_plan", [])})
    return next_state


def rag_executor(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")
    if intent != "rag":
        trace(next_state, "rag_executor", "skip", "Skipped rag executor because intent is not rag.")
        return next_state

    try:
        rag_result = _run_rag_query(next_state, str(state.get("user_query", "")))
        next_state["rag_result"] = rag_result
        results = list(next_state.get("workflow_results", []))
        results.append({"type": "rag", "name": "domain_knowledge", "result": rag_result})
        next_state["workflow_results"] = results
        trace(next_state, "rag_executor", "ok", "Executed RAG endpoint.")
    except Exception as exc:
        next_state["rag_result"] = {"error": str(exc)}
        _append_warning(next_state, f"RAG execution fallback used: {exc}")
        trace(next_state, "rag_executor", "warn", "RAG execution fallback used.", {"reason": str(exc)})
    return next_state


def tool_executor(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")
    if intent not in {"tool", "workflow"}:
        trace(next_state, "tool_executor", "skip", "Skipped tool executor because intent is rag.")
        return next_state

    plan = list(state.get("workflow_plan", []))
    if not plan:
        plan = [{"step": 1, "type": "tool", "name": "analyze_wind_resource"}]

    file_paths = list(state.get("file_paths", []))
    tool = build_wind_analysis_tool()

    workflow_results = list(next_state.get("workflow_results", []))
    batch_results: list[dict[str, Any]] = []

    for item in plan:
        step_type = str(item.get("type", "")).strip().lower()

        if step_type == "rag":
            try:
                rag_result = _run_rag_query(next_state, str(state.get("user_query", "")))
                next_state["rag_result"] = rag_result
                workflow_results.append({"type": "rag", "name": item.get("name", "domain_knowledge"), "result": rag_result})
                trace(next_state, "tool_executor", "ok", "Executed workflow rag step.", {"step": item})
            except Exception as exc:
                _append_warning(next_state, f"Workflow rag step failed: {exc}")
                trace(next_state, "tool_executor", "warn", "Workflow rag step failed.", {"step": item, "reason": str(exc)})
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
                workflow_results.append({"type": "llm", "goal": item.get("goal"), "result": {"text": llm_text}})
                trace(next_state, "tool_executor", "ok", "Executed workflow llm step.", {"step": item})
            except Exception as exc:
                _append_warning(next_state, f"Workflow llm step fallback used: {exc}")
                trace(next_state, "tool_executor", "warn", "Workflow llm step failed.", {"step": item, "reason": str(exc)})
            continue

        if step_type != "tool":
            _append_warning(next_state, f"Unsupported workflow step type: {step_type}")
            trace(next_state, "tool_executor", "warn", "Unsupported workflow step type.", {"step": item})
            continue

        if not file_paths:
            next_state["error"] = "Missing excel file path for tool execution."
            trace(next_state, "tool_executor", "error", next_state["error"])
            next_state["workflow_results"] = workflow_results
            return next_state

        for file_path in file_paths:
            path = Path(file_path)
            if not path.exists() or not path.is_file():
                _append_warning(next_state, f"Excel file not found, skipped: {file_path}")
                trace(next_state, "tool_executor", "warn", "Excel file missing, skipped.", {"file_path": file_path})
                continue

            next_state["selected_tool"] = "analyze_wind_resource"
            next_state["tool_input"] = {"excel_path": str(path)}
            raw = tool.invoke({"excel_path": str(path)})
            output = json.loads(raw)
            batch_item = {"excel_path": str(path.resolve()), "result": output}
            batch_results.append(batch_item)
            workflow_results.append({"type": "tool", "name": "analyze_wind_resource", "result": batch_item})
            trace(next_state, "tool_executor", "ok", "Executed wind analysis tool.", {"excel_path": str(path.resolve())})

    next_state["workflow_results"] = workflow_results

    if batch_results:
        if len(batch_results) == 1:
            next_state["tool_result"] = batch_results[0]["result"]
            next_state["file_path"] = batch_results[0]["excel_path"]
        else:
            next_state["tool_result"] = {
                "success": all(bool((item["result"] or {}).get("success")) for item in batch_results),
                "batch_results": batch_results,
            }
            next_state["file_path"] = batch_results[0]["excel_path"]
        trace(next_state, "tool_executor", "ok", "Workflow tool execution completed.", {"batch_count": len(batch_results)})
    else:
        _append_warning(next_state, "No tool output produced from workflow execution.")
        trace(next_state, "tool_executor", "warn", "No tool output produced from workflow execution.")

    return next_state


def answer_synthesizer(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)

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
            max_tokens=500,
        )
    except Exception as exc:
        _append_warning(next_state, f"Answer synthesizer fallback used: {exc}")
        if isinstance(tool_result, dict) and "batch_results" in tool_result:
            final_answer = f"分析完成：共处理 {len(tool_result.get('batch_results', []))} 个文件。"
        elif isinstance(tool_result, dict) and bool(tool_result.get("success", False)):
            data = tool_result.get("data") or {}
            weibull = data.get("weibull_fit") or {}
            final_answer = (
                f"分析完成：valid_rows={data.get('valid_rows')}，"
                f"Weibull(k={weibull.get('shape_k')}, A={weibull.get('scale_a')})。"
            )
        elif rag_result:
            final_answer = "流程执行完成，已获取 RAG 结果，但总结模型不可用。"
        else:
            final_answer = f"流程执行完成，但结果异常：{state.get('warnings', [])}"

    next_state["final_answer"] = final_answer
    trace(next_state, "answer_synthesizer", "ok", "Generated final answer.")
    return next_state
