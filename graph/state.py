"""定义 LangGraph 运行时状态结构（分析流与 Agent 流）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class WindFlowState(TypedDict, total=False):
    excel_path: str
    tool_output: Dict[str, Any]
    summary: str
    error: str


class AgentFlowState(TypedDict, total=False):
    user_query: str
    session_id: str
    file_path: Optional[str]

    intent: str
    intent_confidence: float

    retrieved_context: str
    rag_result: Dict[str, Any]

    selected_tool: str
    tool_input: Dict[str, Any]
    tool_result: Dict[str, Any]

    workflow_plan: List[Dict[str, Any]]
    workflow_results: List[Dict[str, Any]]

    final_answer: str
    warnings: List[str]

    # 兼容字段（便于现有 API 返回结构不变）
    trace: List[Dict[str, Any]]
    error: str
    llm_config: Dict[str, Any]


TraceDetails = Optional[Dict[str, Any]]
