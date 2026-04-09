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


class AgentTraceStep(BaseModel):
    step: str
    status: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class AgentChatResponse(BaseModel):
    success: bool
    request: str
    resolved_excel_path: Optional[str] = None
    resolved_excel_paths: List[str] = Field(default_factory=list)
    resolved_data_folder: Optional[str] = None
    summary: str = ""
    analysis: Optional[Dict[str, Any]] = None
    rag_result: Optional[Dict[str, Any]] = None
    workflow_results: List[Dict[str, Any]] = Field(default_factory=list)
    trace: List[AgentTraceStep] = Field(default_factory=list)
    error: Optional[str] = None

