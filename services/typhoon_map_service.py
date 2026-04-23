"""Typhoon map visualization service."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any


def run_typhoon_map_visualization(payload: dict[str, Any]) -> dict[str, Any]:
    p = dict(payload or {})
    typhoon_result = p.get("typhoon_result") if isinstance(p.get("typhoon_result"), dict) else {}
    src_input = typhoon_result.get("input") if isinstance(typhoon_result.get("input"), dict) else {}

    model_scope = str(p.get("model_scope") or typhoon_result.get("model_scope") or src_input.get("model_scope") or "scs").lower()
    lat = float(p.get("lat", src_input.get("lat", 20.9339)))
    lon = float(p.get("lon", src_input.get("lon", 112.202)))
    radius_km = float(p.get("radius_km", src_input.get("radius_km", 100.0)))

    map_spec = {
        "model_scope": model_scope,
        "center": {"lat": lat, "lon": lon},
        "radius_km": radius_km,
    }
    if isinstance(typhoon_result.get("metrics"), dict):
        map_spec["metrics"] = typhoon_result["metrics"]

    output_dir = Path(str(p.get("output_dir") or tempfile.mkdtemp(prefix="typhoon-map-"))).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "typhoon_map.html"
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Typhoon Map</title></head>"
        "<body><pre id='map-spec'></pre><script>"
        f"const mapSpec = {json.dumps(map_spec, ensure_ascii=False)};"
        "document.getElementById('map-spec').textContent = JSON.stringify(mapSpec, null, 2);"
        "</script></body></html>"
    )
    html_path.write_text(html, encoding="utf-8")

    return {
        "success": True,
        "html_path": str(html_path),
        "map_spec": map_spec,
        "input": p,
    }
