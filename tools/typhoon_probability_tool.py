"""Lightweight typhoon probability tool wrapper used by graph registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from services.typhoon_probability_service import run_typhoon_probability


@dataclass
class TyphoonProbabilityTool:
    def invoke(self, payload: dict[str, Any]) -> str:
        result = run_typhoon_probability(payload)
        return json.dumps(result, ensure_ascii=False)


def build_typhoon_probability_tool() -> TyphoonProbabilityTool:
    return TyphoonProbabilityTool()
