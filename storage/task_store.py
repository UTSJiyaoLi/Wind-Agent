"""任务状态存储与落盘管理，支持任务创建、更新与查询。"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from schemas.api import TaskStatus


@dataclass
class TaskRecord:
    task_id: str
    status: TaskStatus
    message: str
    created_at: str
    updated_at: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TaskStore:
    def __init__(self, task_dir: str = "storage/tasks") -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, TaskRecord] = {}
        self._task_dir = Path(task_dir)
        self._task_dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> TaskRecord:
        with self._lock:
            task_id = uuid4().hex
            now = datetime.utcnow().isoformat()
            record = TaskRecord(
                task_id=task_id,
                status=TaskStatus.pending,
                message="Task queued",
                created_at=now,
                updated_at=now,
            )
            self._tasks[task_id] = record
            self._persist(record)
            return record

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            return self._tasks.get(task_id)

    def mark_running(self, task_id: str) -> None:
        self._update(task_id, status=TaskStatus.running, message="Task is running")

    def mark_success(self, task_id: str, result: Dict[str, Any]) -> None:
        self._update(task_id, status=TaskStatus.success, message="Task completed", result=result, error=None)

    def mark_failed(self, task_id: str, error: str) -> None:
        self._update(task_id, status=TaskStatus.failed, message="Task failed", error=error)

    def _update(self, task_id: str, **changes: Any) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record is None:
                return
            for key, value in changes.items():
                setattr(record, key, value)
            record.updated_at = datetime.utcnow().isoformat()
            self._persist(record)

    def _persist(self, record: TaskRecord) -> None:
        out = {
            "task_id": record.task_id,
            "status": record.status.value,
            "message": record.message,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "result": record.result,
            "error": record.error,
        }
        (self._task_dir / f"{record.task_id}.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


TASK_STORE = TaskStore()

