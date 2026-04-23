"""Typhoon probability service backed by local summary.csv artifacts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TYPHOON_ROOT = PROJECT_ROOT / "typhoon forecasting" / "台风预测"


def _default_summary_path(model_scope: str) -> Path:
    scope = str(model_scope or "scs").strip().lower()
    if scope == "total":
        return TYPHOON_ROOT / "TC_Track_prob_JMA_Total" / "out_tc_prob" / "summary.csv"
    return TYPHOON_ROOT / "TC_Track_prob_JMA_SCS" / "out_tc_prob_scs" / "summary.csv"


def _summary_path_from_bst(model_scope: str, bst_path: str | None) -> Path:
    if bst_path:
        bst = Path(bst_path)
        if bst.exists():
            scope = str(model_scope or "").strip().lower()
            if scope == "total":
                candidate = bst.parent / "out_tc_prob" / "summary.csv"
                if candidate.exists():
                    return candidate
            else:
                candidate = bst.parent / "out_tc_prob_scs" / "summary.csv"
                if candidate.exists():
                    return candidate
                sibling = bst.parent.parent / "TC_Track_prob_JMA_SCS" / "out_tc_prob_scs" / "summary.csv"
                if sibling.exists():
                    return sibling
    return _default_summary_path(model_scope)


def _parse_months(raw: Any) -> list[int]:
    if raw is None:
        return list(range(1, 13))
    if isinstance(raw, list):
        months = [int(x) for x in raw if int(x) >= 1 and int(x) <= 12]
        return months or list(range(1, 13))
    text = str(raw).strip()
    if not text:
        return list(range(1, 13))
    text = text.strip("[]")
    tokens = text.replace(",", " ").split()
    months = [int(x) for x in tokens if x.isdigit() and 1 <= int(x) <= 12]
    return months or list(range(1, 13))


def _normalize_csv_months(raw: str) -> list[int]:
    return _parse_months(raw)


def _to_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except Exception:
        return default


def _to_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def _row_matches(row: dict[str, str], payload: dict[str, Any]) -> bool:
    lat = float(payload["lat"])
    lon = float(payload["lon"])
    radius_km = float(payload["radius_km"])
    year_start = int(payload["year_start"])
    year_end = int(payload["year_end"])
    wind_threshold_kt = int(payload["wind_threshold_kt"])
    months = _parse_months(payload.get("months"))

    return (
        abs(float(row["lat0"]) - lat) < 1e-6
        and abs(float(row["lon0"]) - lon) < 1e-6
        and abs(float(row["R_km"]) - radius_km) < 1e-6
        and int(row["year_start"]) == year_start
        and int(row["year_end"]) == year_end
        and int(float(row["windThreshold_kt"])) == wind_threshold_kt
        and _normalize_csv_months(row["months"]) == months
    )


def _pick_summary_row(summary_path: Path, payload: dict[str, Any]) -> dict[str, str]:
    if not summary_path.exists():
        return {}

    with summary_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return {}

    for row in rows:
        if _row_matches(row, payload):
            return row
    return rows[0]


def run_typhoon_probability(payload: dict[str, Any]) -> dict[str, Any]:
    p = dict(payload or {})
    model_scope = str(p.get("model_scope") or "scs").strip().lower()
    p["model_scope"] = model_scope

    if p.get("lat") is None or p.get("lon") is None:
        raise ValueError("lat/lon are required")

    default_radius = 200.0 if model_scope == "total" else 100.0
    default_boundary = 144 if model_scope == "total" else 72

    p["radius_km"] = float(_to_float(p.get("radius_km"), default_radius))
    p["year_start"] = int(_to_int(p.get("year_start"), 1976))
    p["year_end"] = int(_to_int(p.get("year_end"), 2025))
    p["wind_threshold_kt"] = int(_to_int(p.get("wind_threshold_kt"), 50))
    p["n_boundary"] = int(_to_int(p.get("n_boundary"), default_boundary))
    p["months"] = _parse_months(p.get("months"))

    summary_path = _summary_path_from_bst(model_scope, p.get("bst_path"))
    row = _pick_summary_row(summary_path, p)

    if model_scope == "total":
        metrics = {
            "N_storm": int(row.get("N_storm", 0) or 0),
            "N_hit": int(row.get("N_hit", 0) or 0),
            "p_storm": float(row.get("p_storm", 0.0) or 0.0),
            "lambda_per_year": float(row.get("lambda_per_year", 0.0) or 0.0),
            "p_year": float(row.get("p_year", 0.0) or 0.0),
        }
    else:
        metrics = {
            "N_all": int(row.get("N_all", 0) or 0),
            "N_enterSCS": int(row.get("N_enterSCS", 0) or 0),
            "N_hit": int(row.get("N_hit", 0) or 0),
            "p_cond_impact_given_SCS": float(row.get("p_cond_impact_given_SCS", 0.0) or 0.0),
            "p_abs_impact_and_SCS": float(row.get("p_abs_impact_and_SCS", 0.0) or 0.0),
            "lambda_per_year": float(row.get("lambda_per_year", 0.0) or 0.0),
            "p_year": float(row.get("p_year", 0.0) or 0.0),
        }

    return {
        "success": True,
        "model_scope": model_scope,
        "input": p,
        "config": {
            "summary_csv_path": str(summary_path),
            "n_boundary": p["n_boundary"],
        },
        "metrics": metrics,
    }
