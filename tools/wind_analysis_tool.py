"""将风资源分析服务封装为 LangChain StructuredTool。"""

from __future__ import annotations

import json
from typing import Type

from pydantic import BaseModel, Field

from services.wind_analysis_service import run_analysis

try:
    from langchain_core.tools import StructuredTool
except Exception:  # noqa: BLE001
    StructuredTool = None


class WindAnalysisToolInput(BaseModel):
    excel_path: str = Field(..., description="Excel path containing date, windSpd, windDire")


def _run_wind_analysis(excel_path: str) -> str:
    result = run_analysis(excel_path)
    return json.dumps(result.model_dump(), ensure_ascii=False)


def build_wind_analysis_tool():
    if StructuredTool is None:
        raise RuntimeError("langchain-core is not installed; cannot build StructuredTool")

    return StructuredTool.from_function(
        func=_run_wind_analysis,
        name="wind_resource_analysis",
        description=(
            "Analyze wind resource from an Excel file with date, windSpd, windDire columns. "
            "Returns structured JSON with metrics and chart file paths."
        ),
        args_schema=WindAnalysisToolInput,
        return_direct=False,
    )

