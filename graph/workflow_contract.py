"""Workflow step contract for wind agent execution."""

from __future__ import annotations

from typing import Any

ALLOWED_STEP_TYPES = {"rag", "tool", "llm"}


def normalize_workflow_plan(raw_plan: Any, *, default_tool: str = "analyze_wind_resource") -> list[dict[str, Any]]:
    """Normalize and validate workflow plan into a strict list shape.

    Output schema (per step):
    - step: int (1-based)
    - type: one of rag/tool/llm
    - name: step name
    - goal: optional goal text
    - tool: required for tool steps
    """
    if not isinstance(raw_plan, list):
        raise ValueError("workflow plan must be a list")

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_plan, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"workflow step #{idx} must be an object")
        step_type = str(item.get("type", "")).strip().lower()
        if step_type not in ALLOWED_STEP_TYPES:
            raise ValueError(f"unsupported workflow step type at #{idx}: {step_type}")

        out: dict[str, Any] = {
            "step": idx,
            "type": step_type,
            "name": str(item.get("name") or f"{step_type}_{idx}"),
        }
        if step_type == "tool":
            out["tool"] = str(item.get("tool") or item.get("name") or default_tool)
        if item.get("goal") is not None:
            out["goal"] = str(item.get("goal"))
        normalized.append(out)

    if not normalized:
        raise ValueError("workflow plan is empty")

    return normalized


def build_default_plan(intent: str) -> list[dict[str, Any]]:
    intent_norm = str(intent or "rag").strip().lower()
    if intent_norm == "tool":
        return [{"step": 1, "type": "tool", "name": "analyze_wind_resource", "tool": "analyze_wind_resource"}]
    if intent_norm == "workflow":
        return [
            {"step": 1, "type": "rag", "name": "domain_knowledge"},
            {"step": 2, "type": "tool", "name": "analyze_wind_resource", "tool": "analyze_wind_resource"},
            {"step": 3, "type": "llm", "name": "workflow_summary", "goal": "summarize and provide recommendations"},
        ]
    return [{"step": 1, "type": "rag", "name": "domain_knowledge"}]

