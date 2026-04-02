from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException

from orchestration.langgraph_flow import run_wind_analysis_flow
from schemas.api import CreateTaskRequest, CreateTaskResponse, TaskStateResponse, TaskStatus
from storage.task_store import TASK_STORE

app = FastAPI(title="Wind Agent API", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/tasks", response_model=CreateTaskResponse)
def create_task(req: CreateTaskRequest, background_tasks: BackgroundTasks) -> CreateTaskResponse:
    record = TASK_STORE.create()
    background_tasks.add_task(_run_task, record.task_id, req.excel_path)
    return CreateTaskResponse(task_id=record.task_id, status=record.status)


@app.get("/tasks/{task_id}", response_model=TaskStateResponse)
def get_task(task_id: str) -> TaskStateResponse:
    record = TASK_STORE.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    return TaskStateResponse(
        task_id=record.task_id,
        status=record.status,
        message=record.message,
        result=record.result,
        error=record.error,
    )


def _run_task(task_id: str, excel_path: str) -> None:
    TASK_STORE.mark_running(task_id)
    try:
        flow_result = run_wind_analysis_flow(excel_path)
        TASK_STORE.mark_success(task_id, flow_result)
    except Exception as exc:  # noqa: BLE001
        TASK_STORE.mark_failed(task_id, str(exc))
