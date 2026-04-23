"""Lightweight typhoon probability tool wrapper used by graph registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class TyphoonProbabilityTool:
    def invoke(self, payload: dict[str, Any]) -> str:
        p = dict(payload or {})
        model_scope = str(p.get("model_scope") or "scs").lower()
        lat = p.get("lat")
        lon = p.get("lon")
        radius_km = p.get("radius_km")
        if lat is None or lon is None or radius_km is None:
            raise ValueError("lat/lon/radius_km are required for typhoon probability tool")

        # Minimal deterministic payload. Real algorithm can be plugged in later.
        metrics = {
            "N_storm": 0,
            "N_hit": 0,
            "p_storm": 0.0,
            "p_year": 0.0,
            "N_all": 0,
            "N_enterSCS": 0,
            "p_cond_impact_given_SCS": 0.0,
            "p_abs_impact_and_SCS": 0.0,
        }
        result = {"success": True, "model_scope": model_scope, "input": p, "metrics": metrics}
        return json.dumps(result, ensure_ascii=False)


def build_typhoon_probability_tool() -> TyphoonProbabilityTool:
    return TyphoonProbabilityTool()

