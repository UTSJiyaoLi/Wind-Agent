from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class WindAnalysisInput(BaseModel):
    """Input schema for wind analysis tool."""

    excel_path: str = Field(..., description="Path to Excel file containing date, windSpd, windDire columns")


class DirectionMetric(BaseModel):
    label: str
    center_degree: float
    occurrence_probability: float
    mean_wind_speed_gt3: Optional[float] = None


class WeibullFitResult(BaseModel):
    shape_k: float
    scale_a: float
    mean_wind_speed: float


class WindAnalysisData(BaseModel):
    total_rows: int
    valid_rows: int
    dropped_rows: int
    direction_metrics: List[DirectionMetric]
    weibull_fit: WeibullFitResult


class WindAnalysisOutput(BaseModel):
    success: bool
    message: str
    input_file: str
    output_dir: str
    charts: Dict[str, str]
    data: Optional[WindAnalysisData] = None
    warnings: List[str] = Field(default_factory=list)
