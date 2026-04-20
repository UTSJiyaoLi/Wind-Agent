"""定义 LangGraph 运行时状态结构（分析流与 Agent 流）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class WindFlowState(TypedDict, total=False):
    excel_path: str
    tool_output: Dict[str, Any]
    summary: str
    error: str


class AgentFlowState(TypedDict, total=False):
    request_id: str
    user_query: str
    session_id: str
    file_path: Optional[str]
    file_paths: List[str]
    data_folder: Optional[str]

    intent: str
    intent_confidence: float
    domain: str
    domain_confidence: float
    domain_candidates: List[str]
    mode: str
    mode_confidence: float
    normalized_query: str

    retrieved_context: str
    rag_result: Dict[str, Any]

    selected_tool: str
    tool_input: Dict[str, Any]
    tool_input_hint: Dict[str, Any]
    tool_result: Dict[str, Any]

    workflow_plan: List[Dict[str, Any]]
    workflow_results: List[Dict[str, Any]]
    slots: Dict[str, Any]
    missing_slots: List[str]
    risk_level: str
    need_confirm: bool
    tool_capability_match: bool
    route_to: str
    route_reason: str
    rule_id: str
    scores: Dict[str, float]
    clarify_question: str
    fallback_reason: str

    final_answer: str
    warnings: List[str]

    # 兼容字段（便于现有 API 返回结构不变）
    trace: List[Dict[str, Any]]
    error: str
    llm_config: Dict[str, Any]


TraceDetails = Optional[Dict[str, Any]]
