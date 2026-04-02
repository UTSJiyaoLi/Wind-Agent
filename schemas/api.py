from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

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
