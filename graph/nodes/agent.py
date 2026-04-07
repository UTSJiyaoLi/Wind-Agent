"""Agent 节点实现：请求预处理、意图识别、流程规划、工具执行与结果解释。"""

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


def _default_llm_config() -> dict[str, Any]:
    return {
        "base_url": os.getenv("ORCH_LLM_BASE_URL", os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8001")),
        "model": os.getenv("ORCH_LLM_MODEL", os.getenv("VLLM_MODEL", "")),
        "api_key": os.getenv("ORCH_LLM_API_KEY", os.getenv("VLLM_API_KEY", "EMPTY")),
        "timeout_seconds": int(os.getenv("ORCH_LLM_TIMEOUT", "60")),
    }


def _call_orchestrator_llm(state: AgentFlowState, messages: list[dict[str, str]], *, temperature: float = 0.1, max_tokens: int = 256) -> str:
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


def input_preprocess(state: AgentFlowState) -> AgentFlowState:
    query = state.get("user_query") or ""
    if not query:
        # 兼容旧入口字段
        query = str(state.get("request", "")).strip()  # type: ignore[arg-type]

    file_path = state.get("file_path")
    if not file_path:
        hinted = str(state.get("excel_path_hint", "")).strip()  # type: ignore[arg-type]
        file_path = hinted or _extract_excel_path(query)

    next_state: AgentFlowState = {
        "user_query": query,
        "session_id": str(state.get("session_id") or "default"),
        "file_path": file_path,
        "warnings": list(state.get("warnings", [])),
        "workflow_results": list(state.get("workflow_results", [])),
        "trace": list(state.get("trace", [])),
    }
    if state.get("llm_config"):
        next_state["llm_config"] = dict(state.get("llm_config") or {})

    trace(
        next_state,
        step="input_preprocess",
        status="ok",
        message="Captured user query and resolved optional file path.",
        details={"file_path": file_path, "session_id": next_state["session_id"]},
    )
    return next_state


def intent_router(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    query = state.get("user_query", "")
    file_path = state.get("file_path")

    fallback_intent = "tool" if file_path else "rag"
    fallback_confidence = 0.6 if file_path else 0.5

    prompt = (
        "You are an intent router for a wind-agent system. "
        "Classify user request into one intent: rag, tool, workflow. "
        "Return strict JSON only: {\"intent\":\"...\",\"confidence\":0.xx}."
    )
    user_payload = json.dumps({"query": query, "file_path": file_path}, ensure_ascii=False)

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
            intent = fallback_intent
        confidence = float(parsed.get("confidence", fallback_confidence))
    except Exception:
        intent = fallback_intent
        confidence = fallback_confidence

    next_state["intent"] = intent
    next_state["intent_confidence"] = confidence

    if intent in {"tool", "workflow"} and not file_path:
        warns = list(next_state.get("warnings", []))
        warns.append("Intent requires data analysis but no valid .xlsx/.xls file path was provided.")
        next_state["warnings"] = warns

    trace(
        next_state,
        step="intent_router",
        status="ok",
        message="Routed user intent.",
        details={"intent": intent, "confidence": confidence},
    )
    return next_state


def workflow_planner(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")

    if intent == "workflow":
        prompt = (
            "You are a workflow planner. Generate a concise execution plan in JSON list. "
            "Allowed step types: rag, tool, llm. "
            "Return JSON only."
        )
        user_payload = json.dumps(
            {
                "query": state.get("user_query", ""),
                "file_path": state.get("file_path"),
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
        except Exception:
            next_state["workflow_plan"] = [
                {"step": 1, "type": "tool", "name": "analyze_wind_resource"},
                {"step": 2, "type": "llm", "goal": "summarize and provide recommendations"},
            ]
    elif intent == "tool":
        next_state["workflow_plan"] = [{"step": 1, "type": "tool", "name": "analyze_wind_resource"}]
    else:
        next_state["workflow_plan"] = []

    trace(
        next_state,
        step="workflow_planner",
        status="ok",
        message="Built workflow plan.",
        details={"plan": next_state.get("workflow_plan", [])},
    )
    return next_state


def tool_executor(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)
    intent = state.get("intent", "rag")
    file_path = state.get("file_path")

    if intent not in {"tool", "workflow"}:
        return next_state

    if not file_path:
        next_state["error"] = "Missing excel file path for tool execution."
        trace(next_state, "tool_executor", "error", next_state["error"])
        return next_state

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        next_state["error"] = f"Excel file not found: {file_path}"
        trace(next_state, "tool_executor", "error", next_state["error"], {"file_path": file_path})
        return next_state

    next_state["selected_tool"] = "analyze_wind_resource"
    next_state["tool_input"] = {"excel_path": str(path)}

    tool = build_wind_analysis_tool()
    raw = tool.invoke({"excel_path": str(path)})
    output = json.loads(raw)
    next_state["tool_result"] = output

    results = list(next_state.get("workflow_results", []))
    results.append({"type": "tool", "name": "analyze_wind_resource", "result": output})
    next_state["workflow_results"] = results

    trace(next_state, "tool_executor", "ok", "Executed wind analysis tool.")
    return next_state


def answer_synthesizer(state: AgentFlowState) -> AgentFlowState:
    next_state: AgentFlowState = dict(state)

    if state.get("error"):
        next_state["final_answer"] = f"执行失败：{state.get('error')}"
        return next_state

    intent = state.get("intent", "rag")
    tool_result = state.get("tool_result")

    if intent == "rag":
        next_state["final_answer"] = "这是知识问答请求，已路由到 RAG 通道处理。"
        trace(next_state, "answer_synthesizer", "ok", "Generated final answer for rag intent.")
        return next_state

    if intent in {"tool", "workflow"} and not tool_result:
        next_state["final_answer"] = "这是分析请求，但未找到可执行的数据文件。请提供 .xlsx/.xls 文件路径。"
        trace(next_state, "answer_synthesizer", "warn", "Missing tool result for analysis intent.")
        return next_state

    prompt = (
        "You are a senior wind-energy analyst. "
        "Explain the analysis result in concise Chinese: key findings, risks/warnings, and next suggestions."
    )
    user_payload = json.dumps(
        {
            "query": state.get("user_query", ""),
            "intent": intent,
            "tool_result": tool_result,
            "workflow_plan": state.get("workflow_plan", []),
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
            max_tokens=400,
        )
    except Exception:
        success = bool((tool_result or {}).get("success", False))
        if success:
            data = (tool_result or {}).get("data") or {}
            weibull = data.get("weibull_fit") or {}
            final_answer = (
                f"分析完成：valid_rows={data.get('valid_rows')}，"
                f"Weibull(k={weibull.get('shape_k')}, A={weibull.get('scale_a')})。"
            )
        else:
            final_answer = f"分析执行完成，但结果异常：{(tool_result or {}).get('warnings', [])}"

    next_state["final_answer"] = final_answer
    trace(next_state, "answer_synthesizer", "ok", "Generated final answer with orchestrator LLM.")
    return next_state
