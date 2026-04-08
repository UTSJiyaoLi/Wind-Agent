"""统一聊天服务层：按模式分发 llm_direct/rag/wind_agent 请求并组装响应。"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional
from urllib.parse import quote


_WIND_DOMAIN_KEYWORDS = {
    "wind", "wind energy", "wind farm", "wind turbine", "wake", "weibull", "capacity factor",
    "yaw", "scada", "aep", "iec", "roughness", "hub height", "power curve",
    "风电", "风能", "风机", "风场", "风速", "风向", "尾流", "湍流", "切变", "功率曲线", "机组", "场址", "可利用率",
}
_TOOL_VERBS = {"分析", "计算", "绘图", "画图", "建模", "统计", "predict", "forecast", "analyze", "plot", "fit"}
_CHATY_TOKENS = {"你好", "hello", "hi", "thanks", "thank you", "你是谁", "讲个笑话", "天气", "翻译"}


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return str(msg.get("content", "")).strip()
    return ""


def _build_rag_user_prompt(user_query: str, context_blob: str, media_blob: str) -> str:
    return (
        f"用户问题:\n{user_query}\n\n"
        f"检索上下文:\n{context_blob}\n\n"
        f"图表与公式线索:\n{media_blob}\n\n"
        "请严格基于上下文回答。每个关键结论后加引用标签（如 [CTX1]）。"
        "若涉及图片、表格或公式，请明确写出可查看位置。最后给出“引用列表”。"
    )


def _build_tool_preview_images(agent_result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    analysis = agent_result.get("analysis") or {}
    charts = analysis.get("charts") or {}
    if not isinstance(charts, dict):
        return [], {}
    previews: list[dict[str, Any]] = []
    for i, (name, path) in enumerate(charts.items(), start=1):
        p = str(path or "").strip()
        if not p:
            continue
        previews.append(
            {
                "index": f"TOOL{i}",
                "indices": [f"TOOL{i}"],
                "kind": "chart",
                "title": name,
                "file_name": p.split("/")[-1].split("\\")[-1],
                "page_no": "",
                "asset_path": p,
                "asset_url": "/api/asset?path=" + quote(p, safe=""),
            }
        )
    return previews, {str(k): str(v) for k, v in charts.items()}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", str(text or "").lower()))


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _norm_score(v: Any) -> float:
    try:
        x = float(v)
    except Exception:
        return 0.0
    if x <= 0:
        return 0.0
    if x <= 1:
        return x
    return x / (x + 1.0)


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _as_bool(v: Any, default: bool) -> bool:
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_agentic_cfg(runtime: Any, req_agentic: dict[str, Any] | None) -> dict[str, Any]:
    args = runtime.args
    req_agentic = dict(req_agentic or {})
    return {
        "enabled": _as_bool(req_agentic.get("enabled"), getattr(args, "agentic_enabled", True)),
        "max_retries": max(0, _as_int(req_agentic.get("max_retries"), getattr(args, "agentic_max_retries", 2))),
        "min_top_score": _clip01(_as_float(req_agentic.get("min_top_score"), getattr(args, "agentic_min_top_score", 0.58))),
        "min_coverage": _clip01(_as_float(req_agentic.get("min_coverage"), getattr(args, "agentic_min_coverage", 0.55))),
        "retry_topk_step": max(1, _as_int(req_agentic.get("retry_topk_step"), getattr(args, "agentic_retry_topk_step", 2))),
        "max_topk": max(1, _as_int(req_agentic.get("max_topk"), getattr(args, "agentic_max_topk", 10))),
        "decompose_enabled": _as_bool(req_agentic.get("decompose_enabled"), True),
        "max_subquestions": max(1, min(3, _as_int(req_agentic.get("max_subquestions"), getattr(args, "agentic_max_subquestions", 3)))),
    }


def _grade_retrieval(metrics: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    top = _clip01(_norm_score(metrics.get("top_hit_score", 0.0)))
    coverage = _clip01(_as_float(metrics.get("coverage_estimate", 0.0), 0.0))
    score_gap = _as_float(metrics.get("score_gap", 0.0), 0.0)
    context_count = _as_int(metrics.get("context_count", metrics.get("final_size", 0)), 0)
    cand_cnt = _as_int(metrics.get("query_candidate_count", 0), 0)
    low_rel = top < float(cfg["min_top_score"])
    low_cov = coverage < float(cfg["min_coverage"])
    should_retry = (low_rel and low_cov) or context_count <= 0
    reasons: list[str] = []
    if context_count <= 0:
        reasons.append("empty_context")
    if low_rel:
        reasons.append("low_top_score")
    if low_cov:
        reasons.append("low_coverage")
    retrieval_score = round(_clip01(0.65 * top + 0.25 * coverage + 0.10 * _clip01(score_gap + 0.4)), 4)
    confidence = round(_clip01(0.5 * top + 0.5 * coverage), 4)
    return {
        "retrieval": retrieval_score,
        "top_hit_score": round(top, 4),
        "coverage": round(coverage, 4),
        "score_gap": round(score_gap, 4),
        "context_count": context_count,
        "query_candidate_count": cand_cnt,
        "should_retry": bool(should_retry),
        "reasons": reasons,
        "confidence": confidence,
    }


def _next_retry_cfg(base_cfg: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    out = dict(base_cfg or {})
    old_topk = _as_int(out.get("top_k", 4), 4)
    old_rw = _as_int(out.get("query_rewrite_max_variants", 1), 1)
    old_expand = _as_bool(out.get("enable_domain_expansion"), False)
    new_topk = min(int(cfg["max_topk"]), old_topk + int(cfg["retry_topk_step"]))
    new_rw = min(3, old_rw + 1)
    out["top_k"] = new_topk
    out["query_rewrite_max_variants"] = new_rw
    out["enable_domain_expansion"] = True
    action = {
        "increase_top_k": {"from": old_topk, "to": new_topk},
        "increase_rewrite_variants": {"from": old_rw, "to": new_rw},
        "enable_domain_expansion": {"from": old_expand, "to": True},
    }
    return out, action


def _extract_ctx_ids(answer: str) -> list[str]:
    return sorted(set(re.findall(r"\[?(CTX\d+)\]?", str(answer or ""), flags=re.IGNORECASE)))


def _grade_answer_rules(answer: str, prompt_contexts: list[dict[str, Any]]) -> dict[str, Any]:
    ans = str(answer or "")
    ans_tokens = _tokenize(ans)
    ctx_text = " ".join(str(x.get("text", "")) for x in (prompt_contexts or [])[:8])
    ctx_tokens = _tokenize(ctx_text)
    overlap = len(ans_tokens & ctx_tokens) / float(len(ans_tokens) or 1) if ans_tokens else 0.0
    ctx_refs = _extract_ctx_ids(ans)
    sentence_cnt = max(1, len(re.split(r"[。！？.!?\n]+", ans)))
    cite_density = len(ctx_refs) / float(sentence_cnt)
    cite_density_norm = _clip01(cite_density * 1.2)
    has_ctx = len(prompt_contexts or []) > 0
    hallucination_risk = 0.0
    if has_ctx and not ctx_refs:
        hallucination_risk += 0.45
    if has_ctx and overlap < 0.10:
        hallucination_risk += 0.35
    if re.search(r"(可能|猜测|大概|也许|I think|maybe)", ans, flags=re.IGNORECASE):
        hallucination_risk += 0.10
    hallucination_risk = _clip01(hallucination_risk)
    grounding = _clip01(0.55 * overlap + 0.35 * cite_density_norm + 0.10 * (1.0 - hallucination_risk))
    usefulness = _clip01(0.40 * grounding + 0.35 * (1.0 if len(ans) > 80 else len(ans) / 80.0) + 0.25 * (1.0 if has_ctx else 0.6))
    confidence = _clip01(0.5 * grounding + 0.5 * usefulness)
    return {
        "grounding": round(grounding, 4),
        "usefulness": round(usefulness, 4),
        "confidence": round(confidence, 4),
        "signals": {
            "token_overlap": round(overlap, 4),
            "citation_density": round(cite_density, 4),
            "hallucination_risk": round(hallucination_risk, 4),
            "ctx_ref_count": len(ctx_refs),
        },
        "source": "rules",
    }


def _grade_answer_with_llm(
    *,
    call_vllm_chat: Callable[..., str],
    llm_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int,
    query: str,
    answer: str,
    prompt_contexts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not llm_base_url or not model:
        return None
    snippet = "\n\n".join([f"[CTX{i}] {str(row.get('text') or '')[:220]}" for i, row in enumerate((prompt_contexts or [])[:4], start=1)])
    prompt = (
        "You are a strict grader. Score grounding/usefulness in [0,1]. "
        "Return JSON only: {\"grounding\":0.xx,\"usefulness\":0.xx,\"confidence\":0.xx,\"reason\":\"...\"}.\n\n"
        f"Question:\n{query}\n\nAnswer:\n{answer}\n\nContext snippets:\n{snippet}"
    )
    try:
        raw = call_vllm_chat(
            base_url=llm_base_url,
            api_key=api_key,
            model=model,
            messages=[
                {"role": "system", "content": "You are a factuality and usefulness grader."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=180,
            timeout_seconds=timeout_seconds,
        ).strip()
        parsed = json.loads(raw)
        return {
            "grounding": _clip01(_as_float(parsed.get("grounding"), 0.0)),
            "usefulness": _clip01(_as_float(parsed.get("usefulness"), 0.0)),
            "confidence": _clip01(_as_float(parsed.get("confidence"), 0.0)),
            "reason": str(parsed.get("reason", "")).strip(),
            "source": "llm",
        }
    except Exception:
        return None


def _is_compound_query(query: str) -> bool:
    q = str(query or "")
    if not q:
        return False
    rules = ["以及", "并且", "同时", "分别", "对比", "compare", "and", " vs ", "；", ";"]
    hit = sum(1 for r in rules if r.lower() in q.lower())
    if hit >= 1 and len(q) >= 16:
        return True
    return q.count("?") + q.count("？") >= 2


def _rule_decompose_query(query: str, max_n: int) -> list[str]:
    q = str(query or "").strip()
    if not q:
        return []
    parts = re.split(r"(?:以及|并且|同时|；|;|\n| and | vs |,|，)", q, flags=re.IGNORECASE)
    out: list[str] = []
    for p in parts:
        t = str(p).strip(" ，,;；。.!?")
        if len(t) < 5:
            continue
        if t not in out:
            out.append(t)
        if len(out) >= max_n:
            break
    return out


def _merge_unique_contexts(buckets: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for rows in buckets:
        for row in rows:
            cid = str(row.get("chunk_id") or row.get("id") or "").strip()
            key = cid or (str(row.get("doc_id") or "") + "::" + str(row.get("page_no") or "") + "::" + str(row.get("rank") or ""))
            if key not in merged or _as_float(row.get("score"), 0.0) > _as_float(merged[key].get("score"), 0.0):
                merged[key] = dict(row)
    out = list(merged.values())
    out.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    for i, row in enumerate(out, start=1):
        row["rank"] = i
    return out


def _build_ui_blocks(
    *,
    mode: str,
    answer: str,
    request_id: str,
    retrieval_metrics: dict[str, Any] | None = None,
    preview_images: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    agentic_trace: list[dict[str, Any]] | None = None,
    agentic_grades: dict[str, Any] | None = None,
    decomposition: dict[str, Any] | None = None,
    error: str | None = None,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    blocks.append({"type": "message", "role": "assistant", "content": answer})
    blocks.append({"type": "meta", "items": {"mode": mode, "request_id": request_id}})
    if error:
        blocks.append({"type": "alert", "level": "error", "content": error})
    if retrieval_metrics:
        blocks.append({"type": "metrics", "title": "Retrieval Metrics", "items": retrieval_metrics})
    if agentic_trace:
        blocks.append({"type": "agentic_trace_timeline", "title": "Agentic Trace", "items": agentic_trace})
    if agentic_grades:
        blocks.append({"type": "agentic_grades", "title": "Agentic Grades", "data": agentic_grades})
    if decomposition and decomposition.get("triggered"):
        blocks.append({"type": "subquestions", "title": "Sub Questions", "items": decomposition.get("subquestions", [])})
    if analysis:
        blocks.append({"type": "json", "title": "Analysis", "data": analysis})
    if preview_images:
        blocks.append({"type": "gallery", "title": "Preview Images", "items": preview_images})
    blocks.append(
        {
            "type": "actions",
            "items": [
                {"id": "save_result", "label": "Save Result JSON"},
                {"id": "copy_request_id", "label": "Copy Request ID"},
            ],
        }
    )
    return blocks


def _default_mode_when_router_unavailable(messages: list[dict[str, Any]]) -> str:
    # 安全回退优先级：工具分析 > 风电知识RAG > 通用直聊
    text = _last_user_message(messages)
    if not text:
        return "llm_direct"
    if _looks_like_wind_data_task(text):
        return "wind_agent"
    if _is_wind_domain_query(text):
        return "rag"
    return "llm_direct"


def _looks_like_wind_data_task(query: str) -> bool:
    q = str(query or "").lower()
    excel_path_pattern = re.compile(
        r"[a-z]:[\\/].*?\.(xlsx|xls)|[\\/].*?\.(xlsx|xls)|\.{1,2}[\\/].*?\.(xlsx|xls)",
        re.IGNORECASE,
    )
    if excel_path_pattern.search(query):
        return True
    if any(v in q for v in _TOOL_VERBS) and any(k in q for k in _WIND_DOMAIN_KEYWORDS):
        return True
    if any(ext in q for ext in (".xlsx", ".xls")):
        return True
    return False


def _is_wind_domain_query(query: str) -> bool:
    q = str(query or "").lower()
    return any(k in q for k in _WIND_DOMAIN_KEYWORDS)


def _is_general_chat(query: str) -> bool:
    q = str(query or "").lower().strip()
    if not q:
        return True
    if any(t in q for t in _CHATY_TOKENS):
        return True
    # 过短且不包含领域词，通常是寒暄/泛问。
    if len(q) <= 8 and not _is_wind_domain_query(q):
        return True
    return False


def _rule_based_auto_mode(query: str) -> tuple[str | None, str]:
    q = str(query or "").strip()
    if not q:
        return "llm_direct", "empty_query"
    if _looks_like_wind_data_task(q):
        return "wind_agent", "rule_wind_data_task"
    if _is_general_chat(q) and not _is_wind_domain_query(q):
        return "llm_direct", "rule_general_chat"
    return None, "no_rule_hit"


def _auto_select_mode_with_llm(
    messages: list[dict[str, Any]], runtime: Any, call_vllm_chat: Callable[..., str]
) -> tuple[str, dict[str, Any]]:
    query = _last_user_message(messages)
    if not query:
        return "llm_direct", {"router_stage": "rule", "reason": "empty_query"}
    rule_mode, rule_reason = _rule_based_auto_mode(query)
    if rule_mode:
        return rule_mode, {"router_stage": "rule", "reason": rule_reason}
    base_url = str(getattr(runtime.args, "orchestrator_base_url", "") or getattr(runtime.args, "llm_base_url", "")).strip()
    model = str(getattr(runtime.args, "orchestrator_model", "") or getattr(runtime.args, "llm_model", "")).strip()
    api_key = str(getattr(runtime.args, "orchestrator_api_key", "") or getattr(runtime.args, "llm_api_key", "EMPTY"))
    timeout_seconds = int(getattr(runtime.args, "orchestrator_timeout_seconds", 20))
    if not base_url or not model:
        fallback = _default_mode_when_router_unavailable(messages)
        return fallback, {"router_stage": "fallback", "reason": "router_llm_unavailable"}
    prompt = (
        "你是 Wind Agent 的意图路由器。"
        "请将用户请求分类到一个且仅一个模式：rag、wind_agent、llm_direct。"
        "判断原则："
        "1) 风电/风资源专业知识问答或需要风电文档依据 -> rag；"
        "2) 明确要求对风数据文件进行计算分析/图表生成 -> wind_agent；"
        "3) 通用问题、闲聊、写作改写、翻译、编程常识等不依赖风电知识库 -> llm_direct。"
        "若问句同时包含寒暄和专业问题，优先专业问题。"
        "仅返回严格 JSON：{\"mode\":\"...\",\"confidence\":0.xx,\"reason\":\"...\"}。"
    )
    try:
        token = call_vllm_chat(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=120,
            timeout_seconds=timeout_seconds,
        ).strip()
        parsed = json.loads(token)
        mode = str(parsed.get("mode", "")).strip().lower()
        if mode in {"rag", "wind_agent", "llm_direct"}:
            # 二次守护：模型误分时用领域规则纠偏
            if mode == "rag" and not _is_wind_domain_query(query):
                return "llm_direct", {"router_stage": "llm_guard", "reason": "llm_rag_but_non_domain"}
            if mode == "llm_direct" and _is_wind_domain_query(query):
                return "rag", {"router_stage": "llm_guard", "reason": "llm_direct_but_domain"}
            return mode, {"router_stage": "llm", "reason": str(parsed.get("reason", "")).strip(), "confidence": parsed.get("confidence")}
        # 某些模型可能在 JSON 外附带文本，做轻量容错
        lowered = token.lower()
        for candidate in ("wind_agent", "llm_direct", "rag"):
            if candidate in lowered:
                return candidate, {"router_stage": "llm_fuzzy", "reason": "token_contains_candidate"}
    except Exception:
        pass
    fallback = _default_mode_when_router_unavailable(messages)
    return fallback, {"router_stage": "fallback", "reason": "router_llm_error"}


def _llm_decompose_query(
    query: str,
    max_n: int,
    runtime: Any,
    call_vllm_chat: Callable[..., str],
) -> list[str]:
    base_url = str(getattr(runtime.args, "orchestrator_base_url", "") or getattr(runtime.args, "llm_base_url", "")).strip()
    model = str(getattr(runtime.args, "orchestrator_model", "") or getattr(runtime.args, "llm_model", "")).strip()
    api_key = str(getattr(runtime.args, "orchestrator_api_key", "") or getattr(runtime.args, "llm_api_key", "EMPTY"))
    timeout_seconds = int(getattr(runtime.args, "orchestrator_timeout_seconds", 20))
    if not base_url or not model:
        return []
    prompt = (
        f"Split the question into up to {max_n} focused sub-questions for retrieval. "
        "Return JSON only: {\"subquestions\": [\"...\"]}."
    )
    try:
        raw = call_vllm_chat(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[
                {"role": "system", "content": "You split complex questions for retrieval."},
                {"role": "user", "content": prompt + "\n\nQuestion: " + query},
            ],
            temperature=0.0,
            max_tokens=220,
            timeout_seconds=timeout_seconds,
        )
        parsed = json.loads(raw)
        rows = parsed.get("subquestions")
        if not isinstance(rows, list):
            return []
        out: list[str] = []
        for item in rows:
            t = str(item or "").strip()
            if len(t) < 5:
                continue
            if t not in out:
                out.append(t)
            if len(out) >= max_n:
                break
        return out
    except Exception:
        return []


def _synthesize_subanswers(
    *,
    query: str,
    parts: list[dict[str, Any]],
    call_vllm_chat: Callable[..., str],
    llm_base_url: str,
    api_key: str,
    model: str,
    timeout_seconds: int,
) -> str:
    rows = []
    for i, p in enumerate(parts, start=1):
        rows.append(f"子问题{i}: {p.get('query')}\n回答{i}: {p.get('answer')}")
    joined = "\n\n".join(rows)
    if not llm_base_url or not model:
        return joined
    prompt = (
        "你是风电知识助手。请把多个子问题答案汇总为一个最终答案，保留证据意识，不确定处要标注。"
        "输出中文，不要杜撰。\n\n"
        f"原问题:\n{query}\n\n子问题材料:\n{joined}"
    )
    try:
        return call_vllm_chat(
            base_url=llm_base_url,
            api_key=api_key,
            model=model,
            messages=[
                {"role": "system", "content": "You synthesize evidence-aware answers."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=700,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        return joined


def _run_agentic_retrieve(
    *,
    runtime: Any,
    tracer: Any,
    request_id: str,
    query: str,
    retrieval_cfg: dict[str, Any],
    retrieve_contexts: Callable[[Any, str, dict[str, Any]], tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]],
    agentic_cfg: dict[str, Any],
) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    grades: dict[str, Any] = {}
    current_cfg = dict(retrieval_cfg or {})
    max_round = 0 if not agentic_cfg.get("enabled") else int(agentic_cfg.get("max_retries", 2))
    final_contexts: list[dict[str, Any]] = []
    final_prompt_contexts: list[dict[str, Any]] = []
    final_metrics: dict[str, Any] = {}
    for round_idx in range(0, max_round + 1):
        call_cfg = dict(current_cfg)
        call_cfg["_trace_id"] = request_id
        contexts, prompt_contexts, metrics = retrieve_contexts(runtime, query, call_cfg)
        retrieval_grade = _grade_retrieval(metrics, agentic_cfg)
        grades["retrieval"] = retrieval_grade
        final_contexts, final_prompt_contexts, final_metrics = contexts, prompt_contexts, metrics
        trace_item = {
            "round": round_idx,
            "step": "grade_retrieval",
            "retrieval_metrics": {
                "top_hit_score": metrics.get("top_hit_score"),
                "score_gap": metrics.get("score_gap"),
                "context_count": metrics.get("context_count", metrics.get("final_size")),
                "query_candidate_count": metrics.get("query_candidate_count"),
                "coverage_estimate": metrics.get("coverage_estimate"),
            },
            "grade": retrieval_grade,
            "decision": "retry" if retrieval_grade.get("should_retry") and round_idx < max_round else "continue",
        }
        trace.append(trace_item)
        tracer.event(request_id, "agentic_step", metadata={"step": "grade_retrieval", **trace_item})
        if not retrieval_grade.get("should_retry") or round_idx >= max_round:
            break
        next_cfg, action = _next_retry_cfg(current_cfg, agentic_cfg)
        current_cfg = next_cfg
        action_row = {"round": round_idx + 1, "type": "retry_retrieve", "action": action}
        actions.append(action_row)
        trace.append(action_row)
        tracer.event(request_id, "agentic_step", metadata={"step": "retry_retrieve", **action_row})
    return {
        "contexts": final_contexts,
        "prompt_contexts": final_prompt_contexts,
        "retrieval_metrics": final_metrics,
        "agentic_trace": trace,
        "agentic_actions": actions,
        "agentic_grades": grades,
    }


def handle_chat_request(
    *,
    request_path: str,
    req: dict[str, Any],
    runtime: Any,
    run_wind_agent_flow: Optional[Callable[..., dict[str, Any]]],
    call_vllm_chat: Callable[..., str],
    retrieve_contexts: Callable[[Any, str, dict[str, Any]], tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]],
    build_citations_and_media: Callable[[list[dict[str, Any]]], tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    build_preview_images: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    format_contexts_for_prompt: Callable[[list[dict[str, Any]]], str],
    summarize_media_for_prompt: Callable[[list[dict[str, Any]]], str],
    render_citation_index: Callable[[list[dict[str, Any]]], str],
) -> tuple[int, dict[str, Any]]:
    started = time.time()
    tracer = getattr(runtime, "tracer", None)
    if tracer is None:
        from observability.tracer import BaseTracer

        tracer = BaseTracer()
    request_id = tracer.new_trace_id()
    mode = str(req.get("mode", "auto") or "auto").strip().lower()
    requested_mode = mode
    provider = req.get("provider", "vllm")
    messages = req.get("messages") or []
    generation_cfg = req.get("generation_config") or {}
    retrieval_cfg = req.get("retrieval_config") or {}
    agentic_cfg = _resolve_agentic_cfg(runtime, req.get("agentic") if isinstance(req.get("agentic"), dict) else None)

    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list.")

    user_content = _last_user_message(messages)
    with tracer.span(
        request_id,
        "request",
        metadata={
            "request_path": request_path,
            "provider": provider,
            "requested_mode": requested_mode,
            "user_query_summary": tracer.summarize_text(user_content, max_len=100),
        },
    ) as request_span:
        if mode == "auto":
            with tracer.span(request_id, "route") as route_span:
                mode, route_meta = _auto_select_mode_with_llm(messages, runtime, call_vllm_chat)
                route_span.add({"actual_mode": mode, **route_meta})

        request_span.add({"actual_mode": mode})

        if mode == "wind_agent":
            if run_wind_agent_flow is None:
                raise RuntimeError("wind_agent mode unavailable: cannot import run_wind_agent_flow")
            if not user_content:
                raise ValueError("No user message found for wind_agent query.")
            orch_cfg = {
                "base_url": str(getattr(runtime.args, "orchestrator_base_url", "") or getattr(runtime.args, "llm_base_url", "")),
                "model": str(getattr(runtime.args, "orchestrator_model", "") or getattr(runtime.args, "llm_model", "")),
                "api_key": str(getattr(runtime.args, "orchestrator_api_key", "") or getattr(runtime.args, "llm_api_key", "EMPTY")),
                "timeout_seconds": int(getattr(runtime.args, "orchestrator_timeout_seconds", 60)),
            }
            with tracer.span(request_id, "wind_agent", metadata={"query_summary": tracer.summarize_text(user_content)}) as agent_span:
                agent_result = run_wind_agent_flow(user_content, llm_config=orch_cfg)
                agent_span.add({"success": bool(agent_result.get("success"))})
            preview_images, tool_charts = _build_tool_preview_images(agent_result)
            return 200, {
                "ok": True,
                "mode": mode,
                "provider": provider,
                "model": "wind_analysis_tool",
                "answer": agent_result.get("summary") or "Agent finished.",
                "analysis": agent_result.get("analysis"),
                "trace": agent_result.get("trace", []),
                "contexts": [],
                "citations": [],
                "media_refs": [],
                "preview_images": preview_images,
                "tool_charts": tool_charts,
                "retrieval_metrics": {},
                "elapsed_seconds": round(time.time() - started, 4),
                "error": agent_result.get("error"),
                "success": agent_result.get("success"),
                "request_id": request_id,
                "ui_blocks": _build_ui_blocks(
                    mode=mode,
                    answer=agent_result.get("summary") or "Agent finished.",
                    request_id=request_id,
                    preview_images=preview_images,
                    analysis=agent_result.get("analysis"),
                    error=agent_result.get("error"),
                ),
            }

        model = (req.get("model") or runtime.args.llm_model).strip()
        if not model:
            raise ValueError("Missing model in request and server default.")

        temperature = float(generation_cfg.get("temperature", runtime.args.llm_temperature))
        max_tokens = int(generation_cfg.get("max_tokens", runtime.args.llm_max_tokens))
        llm_base_url = (generation_cfg.get("base_url") or runtime.args.llm_base_url).strip()
        api_key = str(generation_cfg.get("api_key") or runtime.args.llm_api_key)

        if mode == "llm_direct":
            with tracer.span(request_id, "generate_llm_direct", metadata={"model": model}) as gen_span:
                answer = call_vllm_chat(
                    base_url=llm_base_url,
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=runtime.args.llm_timeout_seconds,
                )
                gen_span.add({"answer_chars": len(str(answer or ""))})
            return 200, {
                "ok": True,
                "mode": mode,
                "provider": provider,
                "model": model,
                "answer": answer,
                "contexts": [],
                "citations": [],
                "media_refs": [],
                "retrieval_metrics": {},
                "elapsed_seconds": round(time.time() - started, 4),
                "request_id": request_id,
                "ui_blocks": _build_ui_blocks(mode=mode, answer=answer, request_id=request_id),
            }

        if mode == "rag":
            if not user_content:
                raise ValueError("No user message found for RAG query.")
            decomposition = {"enabled": bool(agentic_cfg.get("decompose_enabled")), "triggered": False, "subquestions": []}

            def run_single_query(q_text: str) -> dict[str, Any]:
                with tracer.span(request_id, "retrieve", metadata={"query_summary": tracer.summarize_text(q_text)}) as retr_span:
                    retr_result = _run_agentic_retrieve(
                        runtime=runtime,
                        tracer=tracer,
                        request_id=request_id,
                        query=q_text,
                        retrieval_cfg=dict(retrieval_cfg or {}),
                        retrieve_contexts=retrieve_contexts,
                        agentic_cfg=agentic_cfg,
                    )
                    metrics = retr_result["retrieval_metrics"]
                    retr_span.add(
                        {
                            "query_candidates": len(metrics.get("query_candidates") or []),
                            "final_size": int(metrics.get("final_size") or 0),
                            "dedup_size": int(metrics.get("dedup_size") or 0),
                        }
                    )
                return retr_result

            if request_path != "/api/retrieve" and agentic_cfg.get("decompose_enabled") and _is_compound_query(user_content):
                sub_qs = _rule_decompose_query(user_content, int(agentic_cfg.get("max_subquestions", 3)))
                if len(sub_qs) <= 1:
                    sub_qs = _llm_decompose_query(user_content, int(agentic_cfg.get("max_subquestions", 3)), runtime, call_vllm_chat)
                if len(sub_qs) > 1:
                    decomposition["triggered"] = True
                    decomposition["subquestions"] = sub_qs[: int(agentic_cfg.get("max_subquestions", 3))]
                    tracer.event(
                        request_id,
                        "agentic_step",
                        metadata={"step": "decompose_query", "subquestion_count": len(decomposition["subquestions"]), "subquestions": decomposition["subquestions"]},
                    )

            if decomposition.get("triggered"):
                sub_payloads: list[dict[str, Any]] = []
                for sub_query in decomposition["subquestions"]:
                    sub_ret = run_single_query(sub_query)
                    sub_contexts = sub_ret["contexts"]
                    sub_prompt_contexts = sub_ret["prompt_contexts"]
                    sub_metrics = sub_ret["retrieval_metrics"]
                    sub_trace = sub_ret.get("agentic_trace", [])
                    sub_actions = sub_ret.get("agentic_actions", [])
                    sub_grades = dict(sub_ret.get("agentic_grades", {}))
                    sub_citations, sub_media_refs = build_citations_and_media(sub_contexts)
                    sub_preview_images = build_preview_images(sub_contexts)
                    context_blob = format_contexts_for_prompt(sub_prompt_contexts)
                    media_blob = summarize_media_for_prompt(sub_prompt_contexts)
                    rag_messages = [
                        {"role": "system", "content": runtime.args.system_prompt},
                        {"role": "user", "content": _build_rag_user_prompt(sub_query, context_blob, media_blob)},
                    ]
                    sub_answer = call_vllm_chat(
                        base_url=llm_base_url,
                        api_key=api_key,
                        model=model,
                        messages=rag_messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        timeout_seconds=runtime.args.llm_timeout_seconds,
                    )
                    answer_grade = _grade_answer_rules(sub_answer, sub_prompt_contexts)
                    if answer_grade.get("confidence", 0.0) < 0.55:
                        llm_grade = _grade_answer_with_llm(
                            call_vllm_chat=call_vllm_chat,
                            llm_base_url=llm_base_url,
                            api_key=api_key,
                            model=model,
                            timeout_seconds=runtime.args.llm_timeout_seconds,
                            query=sub_query,
                            answer=sub_answer,
                            prompt_contexts=sub_prompt_contexts,
                        )
                        if llm_grade is not None:
                            answer_grade = llm_grade
                    sub_grades["grounding"] = answer_grade.get("grounding")
                    sub_grades["usefulness"] = answer_grade.get("usefulness")
                    sub_grades["answer_grading"] = answer_grade
                    sub_payloads.append(
                        {
                            "query": sub_query,
                            "answer": sub_answer,
                            "contexts": sub_contexts,
                            "prompt_contexts": sub_prompt_contexts,
                            "retrieval_metrics": sub_metrics,
                            "agentic_trace": sub_trace,
                            "agentic_actions": sub_actions,
                            "agentic_grades": sub_grades,
                            "citations": sub_citations,
                            "media_refs": sub_media_refs,
                            "preview_images": sub_preview_images,
                        }
                    )
                merged_contexts = _merge_unique_contexts([x["contexts"] for x in sub_payloads])
                citations, media_refs = build_citations_and_media(merged_contexts)
                preview_images = build_preview_images(merged_contexts)
                answer = _synthesize_subanswers(
                    query=user_content,
                    parts=sub_payloads,
                    call_vllm_chat=call_vllm_chat,
                    llm_base_url=llm_base_url,
                    api_key=api_key,
                    model=model,
                    timeout_seconds=runtime.args.llm_timeout_seconds,
                )
                answer = f"{answer}\n\n请按以下 CTX 映射核对出处：\n{render_citation_index(citations)}"
                avg_retrieval = 0.0
                avg_grounding = 0.0
                avg_usefulness = 0.0
                if sub_payloads:
                    avg_retrieval = sum(_as_float(x.get("agentic_grades", {}).get("retrieval", {}).get("retrieval"), 0.0) for x in sub_payloads) / len(sub_payloads)
                    avg_grounding = sum(_as_float(x.get("agentic_grades", {}).get("grounding"), 0.0) for x in sub_payloads) / len(sub_payloads)
                    avg_usefulness = sum(_as_float(x.get("agentic_grades", {}).get("usefulness"), 0.0) for x in sub_payloads) / len(sub_payloads)
                agentic_grades = {
                    "retrieval": round(avg_retrieval, 4),
                    "grounding": round(avg_grounding, 4),
                    "usefulness": round(avg_usefulness, 4),
                    "subquestion_count": len(sub_payloads),
                }
                agentic_trace: list[dict[str, Any]] = []
                agentic_actions: list[dict[str, Any]] = []
                for idx, sub in enumerate(sub_payloads, start=1):
                    agentic_trace.append({"step": "subquestion", "id": idx, "query": sub.get("query")})
                    agentic_trace.extend(sub.get("agentic_trace") or [])
                    agentic_actions.extend(sub.get("agentic_actions") or [])
                retrieval_metrics = {
                    "decomposed": True,
                    "subquestion_count": len(sub_payloads),
                    "merged_context_count": len(merged_contexts),
                    "query_candidate_count": sum(_as_int((x.get("retrieval_metrics") or {}).get("query_candidate_count"), 0) for x in sub_payloads),
                }
                decomposition["details"] = [
                    {"query": x.get("query"), "retrieval_metrics": x.get("retrieval_metrics"), "agentic_grades": x.get("agentic_grades")}
                    for x in sub_payloads
                ]
                tracer.event(request_id, "agentic_step", metadata={"step": "grade_answer", "decomposed": True, "grounding": agentic_grades.get("grounding")})
                return 200, {
                    "ok": True,
                    "mode": mode,
                    "provider": provider,
                    "model": model,
                    "answer": answer,
                    "contexts": merged_contexts,
                    "citations": citations,
                    "media_refs": media_refs,
                    "preview_images": preview_images,
                    "retrieval_metrics": retrieval_metrics,
                    "agentic_trace": agentic_trace,
                    "agentic_grades": agentic_grades,
                    "agentic_actions": agentic_actions,
                    "decomposition": decomposition,
                    "elapsed_seconds": round(time.time() - started, 4),
                    "request_id": request_id,
                    "ui_blocks": _build_ui_blocks(
                        mode=mode,
                        answer=answer,
                        request_id=request_id,
                        retrieval_metrics=retrieval_metrics,
                        preview_images=preview_images,
                        agentic_trace=agentic_trace,
                        agentic_grades=agentic_grades,
                        decomposition=decomposition,
                    ),
                }

            retr_result = run_single_query(user_content)
            contexts = retr_result["contexts"]
            prompt_contexts = retr_result["prompt_contexts"]
            retrieval_metrics = retr_result["retrieval_metrics"]
            agentic_trace = retr_result.get("agentic_trace", [])
            agentic_actions = retr_result.get("agentic_actions", [])
            agentic_grades = dict(retr_result.get("agentic_grades", {}))
            citations, media_refs = build_citations_and_media(contexts)
            preview_images = build_preview_images(contexts)
            tracer.event(
                request_id,
                "retrieved_contexts_summary",
                metadata={"contexts": tracer.redact_contexts(contexts), "citation_count": len(citations)},
            )
            if request_path == "/api/retrieve":
                return 200, {
                    "ok": True,
                    "mode": mode,
                    "provider": provider,
                    "model": model,
                    "query": user_content,
                    "answer": "",
                    "contexts": contexts,
                    "prompt_contexts": prompt_contexts,
                    "citations": citations,
                    "media_refs": media_refs,
                    "preview_images": preview_images,
                    "retrieval_metrics": retrieval_metrics,
                    "agentic_trace": agentic_trace,
                    "agentic_grades": agentic_grades,
                    "agentic_actions": agentic_actions,
                    "decomposition": decomposition,
                    "elapsed_seconds": round(time.time() - started, 4),
                    "request_id": request_id,
                    "ui_blocks": _build_ui_blocks(
                        mode=mode,
                        answer="",
                        request_id=request_id,
                        retrieval_metrics=retrieval_metrics,
                        preview_images=preview_images,
                        agentic_trace=agentic_trace,
                        agentic_grades=agentic_grades,
                        decomposition=decomposition,
                    ),
                }
            context_blob = format_contexts_for_prompt(prompt_contexts)
            media_blob = summarize_media_for_prompt(prompt_contexts)
            rag_messages = [
                {"role": "system", "content": runtime.args.system_prompt},
                {"role": "user", "content": _build_rag_user_prompt(user_content, context_blob, media_blob)},
            ]
            with tracer.span(request_id, "generate_rag_answer", metadata={"model": model}) as gen_span:
                answer = call_vllm_chat(
                    base_url=llm_base_url,
                    api_key=api_key,
                    model=model,
                    messages=rag_messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=runtime.args.llm_timeout_seconds,
                )
                gen_span.add({"answer_chars": len(str(answer or "")), "prompt_context_count": len(prompt_contexts)})
            answer_grade = _grade_answer_rules(answer, prompt_contexts)
            if answer_grade.get("confidence", 0.0) < 0.55:
                llm_grade = _grade_answer_with_llm(
                    call_vllm_chat=call_vllm_chat,
                    llm_base_url=llm_base_url,
                    api_key=api_key,
                    model=model,
                    timeout_seconds=runtime.args.llm_timeout_seconds,
                    query=user_content,
                    answer=answer,
                    prompt_contexts=prompt_contexts,
                )
                if llm_grade is not None:
                    answer_grade = llm_grade
            agentic_grades["grounding"] = answer_grade.get("grounding")
            agentic_grades["usefulness"] = answer_grade.get("usefulness")
            agentic_grades["answer_grading"] = answer_grade
            tracer.event(
                request_id,
                "agentic_step",
                metadata={
                    "step": "grade_answer",
                    "grounding": agentic_grades.get("grounding"),
                    "usefulness": agentic_grades.get("usefulness"),
                    "source": answer_grade.get("source"),
                },
            )
            answer = f"{answer}\n\n请按以下 CTX 映射核对出处：\n{render_citation_index(citations)}"
            return 200, {
                "ok": True,
                "mode": mode,
                "provider": provider,
                "model": model,
                "answer": answer,
                "contexts": contexts,
                "citations": citations,
                "media_refs": media_refs,
                "preview_images": preview_images,
                "retrieval_metrics": retrieval_metrics,
                "agentic_trace": agentic_trace,
                "agentic_grades": agentic_grades,
                "agentic_actions": agentic_actions,
                "decomposition": decomposition,
                "elapsed_seconds": round(time.time() - started, 4),
                "request_id": request_id,
                "ui_blocks": _build_ui_blocks(
                    mode=mode,
                    answer=answer,
                    request_id=request_id,
                    retrieval_metrics=retrieval_metrics,
                    preview_images=preview_images,
                    agentic_trace=agentic_trace,
                    agentic_grades=agentic_grades,
                    decomposition=decomposition,
                ),
            }

        return 400, {"ok": False, "error": f"Unsupported mode: {mode}", "request_id": request_id}
