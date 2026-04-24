"""LangGraph 构图与执行入口，定义风资源分析图与 Agent 图并提供运行函数。"""

from __future__ import annotations

from uuid import uuid4
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from graph.nodes.agent import (
    answer_synthesizer,
    clarify_node,
    domain_router,
    fallback_or_escalation,
    flow_entry,
    input_preprocess,
    mode_router,
    next_agent_route,
    policy_gate,
    rag_executor,
    tool_executor,
    workflow_planner,
)
from graph.nodes.wind_analysis import run_analysis_tool, should_continue, summarize, validate_input
from graph.state import AgentFlowState, WindFlowState


def build_wind_analysis_graph():
    graph = StateGraph(WindFlowState)
    graph.add_node("validate", validate_input)
    graph.add_node("run_tool", run_analysis_tool)
    graph.add_node("summarize", summarize)

    graph.set_entry_point("validate")
    graph.add_edge("validate", "run_tool")
    graph.add_conditional_edges("run_tool", should_continue, {"summarize": "summarize", "end": END})
    graph.add_edge("summarize", END)

    return graph.compile()


def build_wind_agent_graph():
    graph = StateGraph(AgentFlowState)
    graph.add_node("input_preprocess", input_preprocess)
    graph.add_node("domain_router", domain_router)
    graph.add_node("mode_router", mode_router)
    graph.add_node("policy_gate", policy_gate)
    graph.add_node("flow_entry", flow_entry)
    graph.add_node("clarify_node", clarify_node)
    graph.add_node("fallback_or_escalation", fallback_or_escalation)
    graph.add_node("workflow_planner", workflow_planner)
    graph.add_node("rag_executor", rag_executor)
    graph.add_node("tool_executor", tool_executor)
    graph.add_node("answer_synthesizer", answer_synthesizer)

    graph.set_entry_point("input_preprocess")
    graph.add_edge("input_preprocess", "domain_router")
    graph.add_edge("domain_router", "mode_router")
    graph.add_edge("mode_router", "policy_gate")
    graph.add_edge("policy_gate", "flow_entry")
    graph.add_conditional_edges(
        "flow_entry",
        next_agent_route,
        {
            "clarify_node": "clarify_node",
            "fallback_or_escalation": "fallback_or_escalation",
            "rag_executor": "rag_executor",
            "tool_executor": "tool_executor",
            "workflow_planner": "workflow_planner",
        },
    )
    graph.add_edge("clarify_node", "answer_synthesizer")
    graph.add_edge("fallback_or_escalation", "answer_synthesizer")
    graph.add_edge("workflow_planner", "tool_executor")
    graph.add_edge("tool_executor", "answer_synthesizer")
    graph.add_edge("rag_executor", "answer_synthesizer")
    graph.add_edge("answer_synthesizer", END)
    return graph.compile()


def run_wind_analysis_flow(excel_path: str) -> Dict[str, Any]:
    app = build_wind_analysis_graph()
    state: WindFlowState = {"excel_path": excel_path}
    result = app.invoke(state)

    tool_output = result.get("tool_output")
    if tool_output is None:
        raise RuntimeError("LangGraph flow completed without tool output")

    return {
        "summary": result.get("summary", ""),
        "analysis": tool_output,
    }


def run_wind_agent_flow(
    request: str,
    excel_path_hint: Optional[str] = None,
    tool_input_hint: Optional[Dict[str, Any]] = None,
    llm_config: Optional[Dict[str, Any]] = None,
    planner_llm_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    app = build_wind_agent_graph()
    request_id = uuid4().hex
    state: AgentFlowState = {
        "request_id": request_id,
        "user_query": request,
        "session_id": "default",
    }
    if excel_path_hint:
        state["file_path"] = excel_path_hint
    if tool_input_hint:
        state["tool_input_hint"] = dict(tool_input_hint)
    if llm_config:
        state["llm_config"] = dict(llm_config)
    if planner_llm_config:
        state["planner_llm_config"] = dict(planner_llm_config)

    result = app.invoke(state)

    return {
        "request_id": result.get("request_id", request_id),
        "success": not bool(result.get("error")),
        "request": request,
        "selected_tool": result.get("selected_tool"),
        "resolved_excel_path": result.get("file_path"),
        "resolved_excel_paths": result.get("file_paths", []),
        "resolved_data_folder": result.get("data_folder"),
        "summary": result.get("final_answer", ""),
        "analysis": result.get("tool_result"),
        "rag_result": result.get("rag_result"),
        "workflow_results": result.get("workflow_results", []),
        "domain": result.get("domain"),
        "domain_confidence": result.get("domain_confidence"),
        "mode": result.get("mode"),
        "mode_confidence": result.get("mode_confidence"),
        "route_to": result.get("route_to"),
        "route_reason": result.get("route_reason"),
        "rule_id": result.get("rule_id"),
        "trace": result.get("trace", []),
        "error": result.get("error"),
    }
