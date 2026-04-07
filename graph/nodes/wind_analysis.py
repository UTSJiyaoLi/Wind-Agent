"""风资源分析节点实现：输入校验、工具调用与结果摘要。"""

from __future__ import annotations

import json

from schemas.wind_analysis import WindAnalysisInput
from tools.wind_analysis_tool import build_wind_analysis_tool

from graph.state import WindFlowState


def validate_input(state: WindFlowState) -> WindFlowState:
    payload = WindAnalysisInput(excel_path=state["excel_path"])
    return {"excel_path": payload.excel_path}


def run_analysis_tool(state: WindFlowState) -> WindFlowState:
    tool = build_wind_analysis_tool()
    raw = tool.invoke({"excel_path": state["excel_path"]})
    output = json.loads(raw)
    return {"tool_output": output}


def summarize(state: WindFlowState) -> WindFlowState:
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


def should_continue(state: WindFlowState) -> str:
    if state.get("error"):
        return "end"
    return "summarize"


