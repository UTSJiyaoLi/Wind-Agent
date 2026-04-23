"""Lightweight typhoon map tool wrapper used by graph registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from services.typhoon_map_service import run_typhoon_map_visualization


@dataclass
class TyphoonMapTool:
    def invoke(self, payload: dict[str, Any]) -> str:
        result = run_typhoon_map_visualization(payload)
        return json.dumps(result, ensure_ascii=False)


def build_typhoon_map_tool() -> TyphoonMapTool:
    return TyphoonMapTool()
