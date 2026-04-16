"""Wind Agent 的 FastAPI 入口，提供健康检查、任务接口与 Agent 对话接口。"""

from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException

from graph.builder import run_wind_agent_flow, run_wind_analysis_flow
from services.typhoon_probability_service import run_typhoon_probability
from schemas.api import (
    AgentChatRequest,
    AgentChatResponse,
    CreateTaskRequest,
    CreateTaskResponse,
    TyphoonProbabilityRequest,
    TaskStateResponse,
    TaskStatus,
)
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


@app.post("/agent/chat", response_model=AgentChatResponse)
def agent_chat(req: AgentChatRequest) -> AgentChatResponse:
    try:
        result = run_wind_agent_flow(req.request, req.excel_path, req.wind_agent_input)
        return AgentChatResponse(**result)
    except Exception as exc:  # noqa: BLE001
        return AgentChatResponse(
            success=False,
            request=req.request,
            summary="Agent execution failed.",
            error=str(exc),
            trace=[],
        )


@app.post("/typhoon/probability")
def typhoon_probability(req: TyphoonProbabilityRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    return run_typhoon_probability(payload)


def _run_task(task_id: str, excel_path: str) -> None:
    TASK_STORE.mark_running(task_id)
    try:
        flow_result = run_wind_analysis_flow(excel_path)
        TASK_STORE.mark_success(task_id, flow_result)
    except Exception as exc:  # noqa: BLE001
        TASK_STORE.mark_failed(task_id, str(exc))
