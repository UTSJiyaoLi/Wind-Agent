"""API 请求与响应的数据模型定义。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class CreateTaskRequest(BaseModel):
    excel_path: str = Field(..., description="Excel path containing date, windSpd, windDire")


class CreateTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus


class TaskStateResponse(BaseModel):
    task_id: str
    status: TaskStatus
    message: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AgentChatRequest(BaseModel):
    request: str = Field(..., description="User natural language request")
    excel_path: Optional[str] = Field(
        default=None,
        description="Optional explicit excel path. If omitted, agent will try to parse from request text.",
    )
    wind_agent_input: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional structured tool input, e.g. typhoon probability parameters.",
    )


class TyphoonPointInput(BaseModel):
    lat: float
    lon: float
    radius_km: Optional[float] = None


class TyphoonProbabilityRequest(BaseModel):
    model_scope: str = Field(default="total", description="total or scs")
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_km: Optional[float] = None
    year_start: int = 1976
    year_end: int = 2025
    months: Optional[List[int]] = None
    wind_threshold_kt: int = 50
    n_boundary: Optional[int] = None
    points: Optional[List[TyphoonPointInput]] = None
    bst_path: Optional[str] = None


class AgentTraceStep(BaseModel):
    step: str
    status: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class AgentChatResponse(BaseModel):
    request_id: Optional[str] = None
    success: bool
    request: str
    selected_tool: Optional[str] = None
    resolved_excel_path: Optional[str] = None
    resolved_excel_paths: List[str] = Field(default_factory=list)
    resolved_data_folder: Optional[str] = None
    summary: str = ""
    analysis: Optional[Dict[str, Any]] = None
    rag_result: Optional[Dict[str, Any]] = None
    workflow_results: List[Dict[str, Any]] = Field(default_factory=list)
    trace: List[AgentTraceStep] = Field(default_factory=list)
    error: Optional[str] = None

