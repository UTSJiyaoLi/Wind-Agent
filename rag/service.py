"""统一聊天服务层：按模式分发 llm_direct/rag/wind_agent 请求并组装响应。"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional


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


def _default_mode_when_router_unavailable(messages: list[dict[str, Any]]) -> str:
    # 最小安全回退：避免关键词硬编码误路由，默认走 RAG。
    # 若文本中出现明确文件路径，再回退到 wind_agent。
    text = _last_user_message(messages)
    if not text:
        return "rag"
    excel_path_pattern = re.compile(r"[a-z]:[\\/].*?\.(xlsx|xls)|[\\/].*?\.(xlsx|xls)|\.{1,2}[\\/].*?\.(xlsx|xls)", re.IGNORECASE)
    if excel_path_pattern.search(text):
        return "wind_agent"
    return "rag"


def _auto_select_mode_with_llm(messages: list[dict[str, Any]], runtime: Any, call_vllm_chat: Callable[..., str]) -> str:
    query = _last_user_message(messages)
    if not query:
        return "rag"
    base_url = str(getattr(runtime.args, "orchestrator_base_url", "") or getattr(runtime.args, "llm_base_url", "")).strip()
    model = str(getattr(runtime.args, "orchestrator_model", "") or getattr(runtime.args, "llm_model", "")).strip()
    api_key = str(getattr(runtime.args, "orchestrator_api_key", "") or getattr(runtime.args, "llm_api_key", "EMPTY"))
    timeout_seconds = int(getattr(runtime.args, "orchestrator_timeout_seconds", 20))
    if not base_url or not model:
        return _default_mode_when_router_unavailable(messages)
    prompt = (
        "你是 Wind Agent 的意图路由器。"
        "请将用户请求分类到一个且仅一个模式：rag、wind_agent、llm_direct。"
        "判断原则："
        "1) 涉及知识问答/概念解释 -> rag；"
        "2) 明确要求对风数据文件进行计算分析/图表生成 -> wind_agent；"
        "3) 明显闲聊且不涉及风能知识或分析 -> llm_direct。"
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
            return mode
        # 某些模型可能在 JSON 外附带文本，做轻量容错
        lowered = token.lower()
        for candidate in ("wind_agent", "llm_direct", "rag"):
            if candidate in lowered:
                return candidate
    except Exception:
        pass
    return _default_mode_when_router_unavailable(messages)


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
    mode = str(req.get("mode", "auto") or "auto").strip().lower()
    provider = req.get("provider", "vllm")
    messages = req.get("messages") or []
    generation_cfg = req.get("generation_config") or {}
    retrieval_cfg = req.get("retrieval_config") or {}

    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list.")

    if mode == "auto":
        mode = _auto_select_mode_with_llm(messages, runtime, call_vllm_chat)

    if mode == "wind_agent":
        if run_wind_agent_flow is None:
            raise RuntimeError("wind_agent mode unavailable: cannot import run_wind_agent_flow")
        user_content = _last_user_message(messages)
        if not user_content:
            raise ValueError("No user message found for wind_agent query.")
        orch_cfg = {
            "base_url": str(getattr(runtime.args, "orchestrator_base_url", "") or getattr(runtime.args, "llm_base_url", "")),
            "model": str(getattr(runtime.args, "orchestrator_model", "") or getattr(runtime.args, "llm_model", "")),
            "api_key": str(getattr(runtime.args, "orchestrator_api_key", "") or getattr(runtime.args, "llm_api_key", "EMPTY")),
            "timeout_seconds": int(getattr(runtime.args, "orchestrator_timeout_seconds", 60)),
        }
        agent_result = run_wind_agent_flow(user_content, llm_config=orch_cfg)
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
            "retrieval_metrics": {},
            "elapsed_seconds": round(time.time() - started, 4),
            "error": agent_result.get("error"),
            "success": agent_result.get("success"),
        }

    model = (req.get("model") or runtime.args.llm_model).strip()
    if not model:
        raise ValueError("Missing model in request and server default.")

    temperature = float(generation_cfg.get("temperature", runtime.args.llm_temperature))
    max_tokens = int(generation_cfg.get("max_tokens", runtime.args.llm_max_tokens))
    llm_base_url = (generation_cfg.get("base_url") or runtime.args.llm_base_url).strip()
    api_key = str(generation_cfg.get("api_key") or runtime.args.llm_api_key)

    if mode == "llm_direct":
        answer = call_vllm_chat(
            base_url=llm_base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=runtime.args.llm_timeout_seconds,
        )
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
        }

    if mode == "rag":
        user_content = _last_user_message(messages)
        if not user_content:
            raise ValueError("No user message found for RAG query.")

        contexts, prompt_contexts, retrieval_metrics = retrieve_contexts(runtime, user_content, retrieval_cfg)
        citations, media_refs = build_citations_and_media(contexts)
        preview_images = build_preview_images(contexts)

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
            }

        context_blob = format_contexts_for_prompt(prompt_contexts)
        media_blob = summarize_media_for_prompt(prompt_contexts)
        rag_messages = [
            {"role": "system", "content": runtime.args.system_prompt},
            {"role": "user", "content": _build_rag_user_prompt(user_content, context_blob, media_blob)},
        ]
        answer = call_vllm_chat(
            base_url=llm_base_url,
            api_key=api_key,
            model=model,
            messages=rag_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=runtime.args.llm_timeout_seconds,
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
            "elapsed_seconds": round(time.time() - started, 4),
        }

    return 400, {"ok": False, "error": f"Unsupported mode: {mode}"}


