"""Generate map visualization artifacts for typhoon probability outputs."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

SCS_POLYGON = [
    [0.0, 105.0],
    [0.0, 121.0],
    [25.0, 121.0],
    [25.0, 105.0],
    [0.0, 105.0],
]


def _read_summary_csv(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        row = next(reader, None)
    if not row:
        raise ValueError(f"CSV has no data rows: {path}")

    lat = float(row.get("lat0") or row.get("lat") or 0.0)
    lon = float(row.get("lon0") or row.get("lon") or 0.0)
    radius = float(row.get("R_km") or row.get("radius_km") or 0.0)
    scope = "scs" if "N_enterSCS" in row else "total"
    return {
        "model_scope": scope,
        "lat": lat,
        "lon": lon,
        "radius_km": radius,
        "metrics": row,
    }


def _extract_from_typhoon_result(result: dict[str, Any]) -> dict[str, Any]:
    input_row = dict(result.get("input") or {})
    if not input_row and isinstance(result.get("batch_results"), list) and result["batch_results"]:
        input_row = dict((result["batch_results"][0] or {}).get("input") or {})
    if not input_row:
        raise ValueError("typhoon_result has no input payload")

    return {
        "model_scope": str(result.get("model_scope") or input_row.get("model_scope") or "total").lower(),
        "lat": float(input_row.get("lat")),
        "lon": float(input_row.get("lon")),
        "radius_km": float(input_row.get("radius_km") or 0.0),
        "metrics": result.get("metrics") or {},
    }


def _build_map_spec(payload: dict[str, Any]) -> dict[str, Any]:
    scope = str(payload.get("model_scope") or "total").strip().lower()
    lat = float(payload["lat"])
    lon = float(payload["lon"])
    radius_km = float(payload.get("radius_km") or (100 if scope == "scs" else 200))

    bounds = [[0.0, 100.0], [50.0, 180.0]]
    if scope == "scs":
        bounds = [[0.0, 105.0], [25.0, 121.0]]

    return {
        "model_scope": scope,
        "center": {"lat": lat, "lon": lon},
        "radius_km": radius_km,
        "fit_bounds": bounds,
        "tile_layers": {
            "total": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            "scs": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        },
        "scs_polygon": SCS_POLYGON,
        "metrics": payload.get("metrics") or {},
    }


def _build_html(spec: dict[str, Any]) -> str:
    spec_json = json.dumps(spec, ensure_ascii=False)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Typhoon Map</title>
  <link rel=\"stylesheet\" href=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.css\" crossorigin=\"\" />
  <style>
    html,body,#map {{ height:100%; margin:0; }}
    #meta {{ position:absolute; top:8px; left:8px; z-index:9999; background:#fff; border:1px solid #ccc; border-radius:8px; padding:8px; font:12px/1.4 sans-serif; max-width:360px; }}
  </style>
</head>
<body>
  <div id=\"map\"></div>
  <div id=\"meta\"></div>
  <script src=\"https://unpkg.com/leaflet@1.9.4/dist/leaflet.js\" crossorigin=\"\"></script>
  <script>
    const spec = {spec_json};
    const scope = spec.model_scope || "total";
    const tileUrl = scope === "scs" ? spec.tile_layers.scs : spec.tile_layers.total;
    const map = L.map('map');
    L.tileLayer(tileUrl, {{maxZoom: 12, attribution: '&copy; map contributors'}}).addTo(map);
    map.fitBounds(spec.fit_bounds);

    if (scope === 'scs' && Array.isArray(spec.scs_polygon)) {{
      L.polygon(spec.scs_polygon, {{color:'#f59e0b', weight:2, fillOpacity:0.08}}).addTo(map).bindPopup('SCS model range');
    }}

    const center = spec.center || {{lat:0, lon:0}};
    L.marker([center.lat, center.lon]).addTo(map).bindPopup('Target point');

    const radiusMeters = Number(spec.radius_km || 0) * 1000;
    if (radiusMeters > 0) {{
      L.circle([center.lat, center.lon], {{radius: radiusMeters, color:'#16a34a', weight:2, fillOpacity:0.08}}).addTo(map).bindPopup('Impact radius');
    }}

    const meta = document.getElementById('meta');
    meta.textContent = `scope=${{scope}} | center=(${{center.lat}}, ${{center.lon}}) | R=${{spec.radius_km}} km`;
  </script>
</body>
</html>"""


def run_typhoon_map_visualization(payload: dict[str, Any]) -> dict[str, Any]:
    source = "direct"
    map_payload: dict[str, Any]

    csv_path = str(payload.get("summary_csv_path") or "").strip()
    if csv_path:
        path = Path(csv_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"summary_csv_path not found: {path}")
        map_payload = _read_summary_csv(path)
        source = "summary_csv"
    elif isinstance(payload.get("typhoon_result"), dict):
        map_payload = _extract_from_typhoon_result(payload.get("typhoon_result") or {})
        source = "typhoon_result"
    else:
        if payload.get("lat") is None or payload.get("lon") is None:
            raise ValueError("Provide summary_csv_path or typhoon_result or direct lat/lon")
        map_payload = {
            "model_scope": payload.get("model_scope", "total"),
            "lat": float(payload.get("lat")),
            "lon": float(payload.get("lon")),
            "radius_km": float(payload.get("radius_km") or 0.0),
            "metrics": payload.get("metrics") or {},
        }

    spec = _build_map_spec(map_payload)

    out_dir = Path(payload.get("output_dir") or (Path(__file__).resolve().parents[1] / "storage" / "maps"))
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = out_dir / f"typhoon_map_{spec['model_scope']}_{ts}.html"
    html_path.write_text(_build_html(spec), encoding="utf-8")

    return {
        "success": True,
        "source": source,
        "map_spec": spec,
        "html_path": str(html_path),
    }
