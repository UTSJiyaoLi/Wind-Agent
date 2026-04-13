"""Tool registry for wind agent workflow execution."""

from __future__ import annotations

import json
from typing import Any, Callable

from tools.wind_analysis_tool import build_wind_analysis_tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {
            "analyze_wind_resource": {
                "name": "analyze_wind_resource",
                "timeout_seconds": 120,
                "max_retries": 0,
                "idempotent": True,
                "input_schema": {"excel_path": "str", "analysis_profile": "str?"},
                "executor": self._execute_wind_analysis,
            }
        }

    def get(self, name: str) -> dict[str, Any]:
        key = str(name or "").strip()
        meta = self._tools.get(key)
        if not meta:
            raise KeyError(f"tool not registered: {name}")
        return meta

    def list_metadata(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for meta in self._tools.values():
            rows.append(
                {
                    "name": meta["name"],
                    "timeout_seconds": meta["timeout_seconds"],
                    "max_retries": meta["max_retries"],
                    "idempotent": meta["idempotent"],
                    "input_schema": meta["input_schema"],
                }
            )
        return rows

    def execute(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        meta = self.get(name)
        executor: Callable[[dict[str, Any]], dict[str, Any]] = meta["executor"]
        return executor(payload)

    @staticmethod
    def _execute_wind_analysis(payload: dict[str, Any]) -> dict[str, Any]:
        tool = build_wind_analysis_tool()
        raw = tool.invoke(payload)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("tool returned non-object JSON payload")
        return parsed


TOOL_REGISTRY = ToolRegistry()

