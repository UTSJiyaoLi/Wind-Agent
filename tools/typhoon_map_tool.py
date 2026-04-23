"""Lightweight typhoon map tool wrapper used by graph registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class TyphoonMapTool:
    def invoke(self, payload: dict[str, Any]) -> str:
        p = dict(payload or {})
        typhoon_result = p.get("typhoon_result") if isinstance(p.get("typhoon_result"), dict) else {}
        scope = str(p.get("model_scope") or typhoon_result.get("model_scope") or "scs").lower()
        src_input = typhoon_result.get("input") if isinstance(typhoon_result.get("input"), dict) else {}
        lat = p.get("lat", src_input.get("lat", 20.9339))
        lon = p.get("lon", src_input.get("lon", 112.202))
        radius_km = p.get("radius_km", src_input.get("radius_km", 100))

        map_spec = {
            "model_scope": scope,
            "center": {"lat": float(lat), "lon": float(lon)},
            "radius_km": float(radius_km),
        }
        return json.dumps({"success": True, "map_spec": map_spec, "input": p}, ensure_ascii=False)


def build_typhoon_map_tool() -> TyphoonMapTool:
    return TyphoonMapTool()

