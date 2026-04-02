from __future__ import annotations

import json
from typing import Any, Dict, Optional, TypedDict

from langgraph.graph import END, StateGraph

from schemas.wind_analysis import WindAnalysisInput
from tools.wind_analysis_tool import build_wind_analysis_tool


class WindFlowState(TypedDict, total=False):
    excel_path: str
    tool_output: Dict[str, Any]
    summary: str
    error: str


def _validate_input(state: WindFlowState) -> WindFlowState:
    payload = WindAnalysisInput(excel_path=state["excel_path"])
    return {"excel_path": payload.excel_path}


def _run_analysis_tool(state: WindFlowState) -> WindFlowState:
    tool = build_wind_analysis_tool()
    raw = tool.invoke({"excel_path": state["excel_path"]})
    output = json.loads(raw)
    return {"tool_output": output}


def _summarize(state: WindFlowState) -> WindFlowState:
    output = state.get("tool_output", {})
    success = output.get("success", False)
    if not success:
        warnings = output.get("warnings", [])
        return {"summary": f"Wind analysis failed: {'; '.join(warnings)}"}

    data = output.get("data") or {}
    weibull = data.get("weibull_fit") or {}
    shape_k = weibull.get("shape_k")
    scale_a = weibull.get("scale_a")
    valid_rows = data.get("valid_rows")
    return {
        "summary": (
            f"Wind analysis completed with {valid_rows} valid rows. "
            f"Weibull parameters: k={shape_k}, A={scale_a}."
        )
    }


def _should_continue(state: WindFlowState) -> str:
    if state.get("error"):
        return "end"
    return "summarize"


def build_wind_analysis_graph():
    graph = StateGraph(WindFlowState)
    graph.add_node("validate", _validate_input)
    graph.add_node("run_tool", _run_analysis_tool)
    graph.add_node("summarize", _summarize)

    graph.set_entry_point("validate")
    graph.add_edge("validate", "run_tool")
    graph.add_conditional_edges("run_tool", _should_continue, {"summarize": "summarize", "end": END})
    graph.add_edge("summarize", END)

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
