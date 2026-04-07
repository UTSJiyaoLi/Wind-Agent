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


def _build_ui_blocks(
    *,
    mode: str,
    answer: str,
    request_id: str,
    retrieval_metrics: dict[str, Any] | None = None,
    preview_images: list[dict[str, Any]] | None = None,
    analysis: dict[str, Any] | None = None,
    error: str | None = None,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    blocks.append({"type": "message", "role": "assistant", "content": answer})
    blocks.append({"type": "meta", "items": {"mode": mode, "request_id": request_id}})
    if error:
        blocks.append({"type": "alert", "level": "error", "content": error})
    if retrieval_metrics:
        blocks.append({"type": "metrics", "title": "Retrieval Metrics", "items": retrieval_metrics})
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
            trace_retrieval_cfg = dict(retrieval_cfg or {})
            trace_retrieval_cfg["_trace_id"] = request_id
            with tracer.span(request_id, "retrieve", metadata={"query_summary": tracer.summarize_text(user_content)}) as retr_span:
                contexts, prompt_contexts, retrieval_metrics = retrieve_contexts(runtime, user_content, trace_retrieval_cfg)
                retr_span.add(
                    {
                        "query_candidates": len(retrieval_metrics.get("query_candidates") or []),
                        "final_size": int(retrieval_metrics.get("final_size") or 0),
                        "dedup_size": int(retrieval_metrics.get("dedup_size") or 0),
                    }
                )
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
                    "elapsed_seconds": round(time.time() - started, 4),
                    "request_id": request_id,
                    "ui_blocks": _build_ui_blocks(
                        mode=mode,
                        answer="",
                        request_id=request_id,
                        retrieval_metrics=retrieval_metrics,
                        preview_images=preview_images,
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
                "elapsed_seconds": round(time.time() - started, 4),
                "request_id": request_id,
                "ui_blocks": _build_ui_blocks(
                    mode=mode,
                    answer=answer,
                    request_id=request_id,
                    retrieval_metrics=retrieval_metrics,
                    preview_images=preview_images,
                ),
            }

        return 400, {"ok": False, "error": f"Unsupported mode: {mode}", "request_id": request_id}


