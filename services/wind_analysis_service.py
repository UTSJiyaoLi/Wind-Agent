"""Wind analysis service facade."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from schemas.wind_analysis import WindAnalysisInput
from tools.wind_analysis_tool import build_wind_analysis_tool


class WindAnalysisResult(BaseModel):
    success: bool
    warnings: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


def run_analysis(excel_path: str) -> WindAnalysisResult:
    validated = WindAnalysisInput(excel_path=excel_path)
    tool = build_wind_analysis_tool()
    raw = tool.invoke({"excel_path": validated.excel_path})
    payload = json.loads(raw)
    return WindAnalysisResult(**payload)

