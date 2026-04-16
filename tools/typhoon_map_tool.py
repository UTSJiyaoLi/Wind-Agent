"""Expose typhoon map visualization as a structured tool."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from services.typhoon_map_service import run_typhoon_map_visualization

try:
    from langchain_core.tools import StructuredTool
except Exception:  # noqa: BLE001
    StructuredTool = None


class TyphoonMapToolInput(BaseModel):
    summary_csv_path: str | None = Field(default=None, description="Path to summary.csv from typhoon model")
    typhoon_result: dict[str, Any] | None = Field(default=None, description="Direct typhoon probability result object")
    model_scope: str | None = Field(default=None, description="total or scs")
    lat: float | None = None
    lon: float | None = None
    radius_km: float | None = None
    output_dir: str | None = Field(default=None, description="Optional output directory for map html")


def _run_typhoon_map_visualization(**kwargs: Any) -> str:
    out = run_typhoon_map_visualization(kwargs)
    return json.dumps(out, ensure_ascii=False)


def build_typhoon_map_tool():
    if StructuredTool is None:
        raise RuntimeError("langchain-core is not installed; cannot build StructuredTool")

    return StructuredTool.from_function(
        func=_run_typhoon_map_visualization,
        name="typhoon_map_visualization",
        description=(
            "Generate a map visualization html from typhoon probability summary csv or prior tool result. "
            "The map fetches online tiles and overlays total/scs model range."
        ),
        args_schema=TyphoonMapToolInput,
        return_direct=False,
    )
