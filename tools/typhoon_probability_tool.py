"""Expose typhoon probability engine as LangChain StructuredTool."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, model_validator

from services.typhoon_probability_service import run_typhoon_probability

try:
    from langchain_core.tools import StructuredTool
except Exception:  # noqa: BLE001
    StructuredTool = None


class TyphoonPointInput(BaseModel):
    lat: float = Field(..., description="Latitude in degrees")
    lon: float = Field(..., description="Longitude in degrees")
    radius_km: float | None = Field(default=None, description="Optional per-point radius")


class TyphoonProbabilityToolInput(BaseModel):
    model_scope: str = Field(default="total", description="Model scope switch: total or scs")
    lat: float | None = Field(default=None, description="Target latitude")
    lon: float | None = Field(default=None, description="Target longitude")
    radius_km: float | None = Field(default=None, description="Region radius in kilometers")
    year_start: int = Field(default=1976)
    year_end: int = Field(default=2025)
    months: list[int] | None = Field(default=None, description="Month list, values 1-12")
    wind_threshold_kt: int = Field(default=50, description="Wind threshold, 30 or 50")
    n_boundary: int | None = Field(default=None, description="Sampling density for target region")
    points: list[TyphoonPointInput] | None = Field(default=None, description="Batch points")
    bst_path: str | None = Field(default=None, description="Optional override path for bst_all.txt")

    @model_validator(mode="after")
    def validate_coords(self) -> "TyphoonProbabilityToolInput":
        if self.points:
            return self
        if self.lat is None or self.lon is None:
            raise ValueError("Either points or (lat, lon) must be provided")
        return self


def _run_typhoon_probability(**kwargs: Any) -> str:
    result = run_typhoon_probability(kwargs)
    return json.dumps(result, ensure_ascii=False)


def build_typhoon_probability_tool():
    if StructuredTool is None:
        raise RuntimeError("langchain-core is not installed; cannot build StructuredTool")

    return StructuredTool.from_function(
        func=_run_typhoon_probability,
        name="typhoon_probability",
        description=(
            "Compute typhoon impact probability for any coordinate from JMA bst_all.txt. "
            "Supports model_scope switch: total or scs, optional batch points, and tunable parameters."
        ),
        args_schema=TyphoonProbabilityToolInput,
        return_direct=False,
    )
