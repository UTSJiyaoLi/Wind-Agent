"""LangGraph 构图与执行入口，定义风资源分析图与 Agent 图并提供运行函数。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from graph.nodes.agent import answer_synthesizer, input_preprocess, intent_router, tool_executor, workflow_planner
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
    graph.add_node("intent_router", intent_router)
    graph.add_node("workflow_planner", workflow_planner)
    graph.add_node("tool_executor", tool_executor)
    graph.add_node("answer_synthesizer", answer_synthesizer)

    graph.set_entry_point("input_preprocess")
    graph.add_edge("input_preprocess", "intent_router")
    graph.add_edge("intent_router", "workflow_planner")
    graph.add_edge("workflow_planner", "tool_executor")
    graph.add_edge("tool_executor", "answer_synthesizer")
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
    llm_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    app = build_wind_agent_graph()
    state: AgentFlowState = {
        "user_query": request,
        "session_id": "default",
    }
    if excel_path_hint:
        state["file_path"] = excel_path_hint
    if llm_config:
        state["llm_config"] = dict(llm_config)

    result = app.invoke(state)

    return {
        "success": not bool(result.get("error")),
        "request": request,
        "resolved_excel_path": result.get("file_path"),
        "summary": result.get("final_answer", ""),
        "analysis": result.get("tool_result"),
        "trace": result.get("trace", []),
        "error": result.get("error"),
    }
