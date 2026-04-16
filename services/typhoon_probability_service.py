"""Typhoon probability engine translated from MATLAB baseline scripts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from services.typhoon_data_store import resolve_bst_path


DEFAULT_SCS_POLYGON_LON = [105.0, 121.0, 121.0, 105.0, 105.0]
DEFAULT_SCS_POLYGON_LAT = [0.0, 0.0, 25.0, 25.0, 0.0]
TYPHOON_KEYWORDS = ("typhoon", "台风", "tropical cyclone", "飓风")


@dataclass(frozen=True)
class TrackRow:
    storm_id: int
    time: datetime
    lat: float
    lon: float
    dir50: int
    r50_long_nm: float
    r50_short_nm: float
    dir30: int
    r30_long_nm: float
    r30_short_nm: float


def _to_datetime(yymmddhh: int) -> datetime:
    raw = f"{int(yymmddhh):08d}"
    yy = int(raw[0:2])
    year = 1900 + yy if yy >= 51 else 2000 + yy
    month = int(raw[2:4])
    day = int(raw[4:6])
    hour = int(raw[6:8])
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _split_dir_long(value: float) -> tuple[int, float]:
    intval = int(round(value))
    return intval // 10000, float(intval % 10000)


def _as_float(token: str) -> float:
    try:
        return float(token)
    except Exception:
        return math.nan


@lru_cache(maxsize=4)
def _parse_bst_cached(path_str: str, mtime_ns: int) -> tuple[TrackRow, ...]:
    _ = mtime_ns
    rows: list[TrackRow] = []
    cur_id: int | None = None
    remain = 0

    with open(path_str, "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("66666"):
                parts = line.split()
                if len(parts) >= 3:
                    cur_id = int(float(parts[1]))
                    remain = int(float(parts[2]))
                else:
                    cur_id = None
                    remain = 0
                continue

            if cur_id is None or remain <= 0:
                continue

            parts = line.split()
            if len(parts) < 7:
                remain -= 1
                continue

            yymmddhh = int(float(parts[0]))
            lat = _as_float(parts[3]) * 0.1
            lon = _as_float(parts[4]) * 0.1

            dir50 = 0
            r50_long_nm = 0.0
            r50_short_nm = 0.0
            dir30 = 0
            r30_long_nm = 0.0
            r30_short_nm = 0.0

            if len(parts) >= 11:
                dir50, r50_long_nm = _split_dir_long(_as_float(parts[7]))
                r50_short_nm = float(round(_as_float(parts[8])))
                dir30, r30_long_nm = _split_dir_long(_as_float(parts[9]))
                r30_short_nm = float(round(_as_float(parts[10])))

            rows.append(
                TrackRow(
                    storm_id=cur_id,
                    time=_to_datetime(yymmddhh),
                    lat=lat,
                    lon=lon,
                    dir50=dir50,
                    r50_long_nm=r50_long_nm,
                    r50_short_nm=r50_short_nm,
                    dir30=dir30,
                    r30_long_nm=r30_long_nm,
                    r30_short_nm=r30_short_nm,
                )
            )
            remain -= 1

    return tuple(rows)


def _load_rows(bst_path: Path) -> tuple[TrackRow, ...]:
    return _parse_bst_cached(str(bst_path), bst_path.stat().st_mtime_ns)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)
    dphi = phi2 - phi1
    dlam = lam2 - lam1
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * radius * math.asin(math.sqrt(a))


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)
    dlam = lam2 - lam1
    x = math.sin(dlam) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _wrap_to_180(lon: float) -> float:
    wrapped = (lon + 180.0) % 360.0 - 180.0
    if wrapped == -180.0:
        return 180.0
    return wrapped


def _destination_point(lat: float, lon: float, az_deg: float, dist_km: float) -> tuple[float, float]:
    radius = 6371.0
    phi1, lam1 = math.radians(lat), math.radians(lon)
    az = math.radians(az_deg)
    d = dist_km / radius
    phi2 = math.asin(math.sin(phi1) * math.cos(d) + math.cos(phi1) * math.sin(d) * math.cos(az))
    lam2 = lam1 + math.atan2(math.sin(az) * math.sin(d) * math.cos(phi1), math.cos(d) - math.sin(phi1) * math.sin(phi2))
    return math.degrees(phi2), _wrap_to_180(math.degrees(lam2))


def _dircode_to_bearing_deg(code: int) -> float:
    mapping = {
        1: 45.0,
        2: 90.0,
        3: 135.0,
        4: 180.0,
        5: 225.0,
        6: 270.0,
        7: 315.0,
        8: 0.0,
        9: 0.0,
    }
    return mapping.get(int(round(code)), 0.0)


def _point_in_polygon(lon: float, lat: float, poly_lon: list[float], poly_lat: list[float]) -> bool:
    def _point_on_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> bool:
        cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
        if abs(cross) > 1e-9:
            return False
        dot = (px - x1) * (px - x2) + (py - y1) * (py - y2)
        return dot <= 1e-9

    inside = False
    n = min(len(poly_lon), len(poly_lat))
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = poly_lon[i], poly_lat[i]
        xj, yj = poly_lon[j], poly_lat[j]
        if _point_on_segment(lon, lat, xi, yi, xj, yj):
            return True
        intersects = ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def _make_circle_samples(lat0: float, lon0: float, radius_km: float, n_boundary: int) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = [(lat0, lon0)]
    if radius_km <= 0:
        return samples
    for idx in range(max(8, int(n_boundary))):
        az = 360.0 * idx / float(max(8, int(n_boundary)))
        samples.append(_destination_point(lat0, lon0, az, radius_km))
    return samples


def _points_inside_wind_ellipse(
    samples: list[tuple[float, float]],
    center_lat: float,
    center_lon: float,
    a_km: float,
    b_km: float,
    phi_deg: float,
) -> bool:
    for latp, lonp in samples:
        dist = _haversine_km(latp, lonp, center_lat, center_lon)
        alpha = _bearing_deg(center_lat, center_lon, latp, lonp)
        theta = math.radians((alpha - phi_deg) % 360.0)
        denom = math.sqrt((b_km * math.cos(theta)) ** 2 + (a_km * math.sin(theta)) ** 2)
        radius = (a_km * b_km / denom) if denom > 0 else 0.0
        if dist <= radius:
            return True
    return False


def _normalize_months(months: Iterable[int] | None) -> list[int]:
    if months is None:
        return list(range(1, 13))
    parsed = sorted({int(x) for x in months if 1 <= int(x) <= 12})
    return parsed or list(range(1, 13))


def _filter_rows(rows: tuple[TrackRow, ...], year_start: int, year_end: int, months: list[int]) -> list[TrackRow]:
    return [r for r in rows if year_start <= r.time.year <= year_end and r.time.month in months]


def _group_by_storm(rows: list[TrackRow]) -> dict[int, list[TrackRow]]:
    grouped: dict[int, list[TrackRow]] = {}
    for row in rows:
        grouped.setdefault(row.storm_id, []).append(row)
    for sid in grouped:
        grouped[sid].sort(key=lambda x: x.time)
    return grouped


def _yearly_metrics(hit_years: list[int], year_start: int, year_end: int) -> tuple[list[dict[str, int]], float, float]:
    years = list(range(year_start, year_end + 1))
    rows: list[dict[str, int]] = []
    total_hits = 0
    for year in years:
        count = sum(1 for y in hit_years if y == year)
        total_hits += count
        rows.append({"year": year, "hit_storms": count})
    lam = total_hits / float(len(years) or 1)
    p_year = 1.0 - math.exp(-lam)
    return rows, lam, p_year


def _calc_single_point(
    *,
    grouped: dict[int, list[TrackRow]],
    model_scope: str,
    lat: float,
    lon: float,
    radius_km: float,
    wind_threshold_kt: int,
    n_boundary: int,
    scs_lon: list[float],
    scs_lat: list[float],
    year_start: int,
    year_end: int,
) -> dict[str, Any]:
    samples = _make_circle_samples(lat, lon, radius_km, n_boundary)
    storm_ids_all = sorted(grouped.keys())
    n_all = len(storm_ids_all)
    if n_all == 0:
        raise ValueError("No typhoon samples in the selected time window.")

    if model_scope == "scs":
        candidate_ids: list[int] = []
        for sid in storm_ids_all:
            records = grouped[sid]
            if any(_point_in_polygon(r.lon, r.lat, scs_lon, scs_lat) for r in records):
                candidate_ids.append(sid)
    else:
        candidate_ids = storm_ids_all

    if not candidate_ids:
        raise ValueError("No storms satisfy selected scope in this time window.")

    per_storm: list[dict[str, Any]] = []
    hit_years: list[int] = []

    for sid in candidate_ids:
        records = grouped[sid]
        min_center_dist = min(_haversine_km(r.lat, r.lon, lat, lon) for r in records)
        eval_records = records
        if model_scope == "scs":
            eval_records = [r for r in records if _point_in_polygon(r.lon, r.lat, scs_lon, scs_lat)]

        hit = False
        first_hit_time = ""
        for row in eval_records:
            if wind_threshold_kt == 50:
                dir_code = row.dir50
                r_long_nm = row.r50_long_nm
                r_short_nm = row.r50_short_nm
            else:
                dir_code = row.dir30
                r_long_nm = row.r30_long_nm
                r_short_nm = row.r30_short_nm

            if not math.isfinite(r_long_nm) or r_long_nm <= 0:
                continue

            a_km = r_long_nm * 1.852
            b_km = r_short_nm * 1.852
            phi = _dircode_to_bearing_deg(dir_code)
            if int(round(dir_code)) == 9:
                b_km = a_km

            if _points_inside_wind_ellipse(samples, row.lat, row.lon, a_km, b_km, phi):
                hit = True
                first_hit_time = row.time.isoformat()
                break

        if hit:
            hit_years.append(min(r.time for r in records).year)

        per_storm.append(
            {
                "storm_id": sid,
                "hit": hit,
                "min_center_dist_km": round(min_center_dist, 6),
                "first_hit_time_utc": first_hit_time,
            }
        )

    n_hit = sum(1 for x in per_storm if bool(x["hit"]))
    hits_by_year, lam, p_year = _yearly_metrics(hit_years, year_start, year_end)

    if model_scope == "scs":
        n_enter_scs = len(candidate_ids)
        p_cond = n_hit / float(n_enter_scs)
        p_abs = n_hit / float(n_all)
        metrics = {
            "N_all": n_all,
            "N_enterSCS": n_enter_scs,
            "N_hit": n_hit,
            "p_cond_impact_given_SCS": p_cond,
            "p_abs_impact_and_SCS": p_abs,
            "lambda_per_year": lam,
            "p_year": p_year,
        }
    else:
        p_storm = n_hit / float(n_all)
        metrics = {
            "N_storm": n_all,
            "N_hit": n_hit,
            "p_storm": p_storm,
            "lambda_per_year": lam,
            "p_year": p_year,
        }

    return {
        "input": {
            "model_scope": model_scope,
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "wind_threshold_kt": wind_threshold_kt,
        },
        "metrics": metrics,
        "hits_by_year": hits_by_year,
        "per_storm": per_storm,
    }


def _normalize_points(points: list[dict[str, Any]] | None, *, lat: float | None, lon: float | None, radius_km: float) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    if points:
        for item in points:
            if "lat" not in item or "lon" not in item:
                continue
            out.append(
                {
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "radius_km": float(item.get("radius_km", radius_km)),
                }
            )
    elif lat is not None and lon is not None:
        out.append({"lat": float(lat), "lon": float(lon), "radius_km": float(radius_km)})

    if not out:
        raise ValueError("lat/lon is required, or provide non-empty points list.")
    return out


def run_typhoon_probability(payload: dict[str, Any]) -> dict[str, Any]:
    model_scope = str(payload.get("model_scope", "total") or "total").strip().lower()
    if model_scope not in {"total", "scs"}:
        raise ValueError("model_scope must be one of: total, scs")

    year_start = int(payload.get("year_start", 1976))
    year_end = int(payload.get("year_end", 2025))
    if year_end < year_start:
        raise ValueError("year_end must be >= year_start")

    months = _normalize_months(payload.get("months"))
    wind_threshold_kt = int(payload.get("wind_threshold_kt", 50))
    if wind_threshold_kt not in {30, 50}:
        raise ValueError("wind_threshold_kt must be 30 or 50")

    default_radius = 200.0 if model_scope == "total" else 100.0
    radius_raw = payload.get("radius_km")
    if radius_raw is None:
        radius_km = default_radius
    else:
        radius_km = float(radius_raw)

    default_n_boundary = 144 if model_scope == "total" else 72
    n_boundary_raw = payload.get("n_boundary")
    if n_boundary_raw is None:
        n_boundary = default_n_boundary
    else:
        n_boundary = int(n_boundary_raw)

    scs_lon = [float(x) for x in payload.get("scs_poly_lon", DEFAULT_SCS_POLYGON_LON)]
    scs_lat = [float(x) for x in payload.get("scs_poly_lat", DEFAULT_SCS_POLYGON_LAT)]

    points = _normalize_points(payload.get("points"), lat=payload.get("lat"), lon=payload.get("lon"), radius_km=radius_km)

    bst_path, source = resolve_bst_path(payload.get("bst_path"))
    rows = _load_rows(bst_path)
    filtered = _filter_rows(rows, year_start, year_end, months)
    grouped = _group_by_storm(filtered)

    warnings: list[str] = []
    if source == "built_in":
        warnings.append("Using built-in bst_all.txt path.")

    results: list[dict[str, Any]] = []
    for point in points:
        result = _calc_single_point(
            grouped=grouped,
            model_scope=model_scope,
            lat=float(point["lat"]),
            lon=float(point["lon"]),
            radius_km=float(point["radius_km"]),
            wind_threshold_kt=wind_threshold_kt,
            n_boundary=n_boundary,
            scs_lon=scs_lon,
            scs_lat=scs_lat,
            year_start=year_start,
            year_end=year_end,
        )
        results.append(result)

    response: dict[str, Any] = {
        "success": True,
        "model_scope": model_scope,
        "database": {"bst_path": str(bst_path), "source": source},
        "config": {
            "year_start": year_start,
            "year_end": year_end,
            "months": months,
            "wind_threshold_kt": wind_threshold_kt,
            "n_boundary": n_boundary,
        },
        "warnings": warnings,
    }

    if len(results) == 1:
        response.update(results[0])
    else:
        response["batch_results"] = results
        response["summary"] = {
            "points": len(results),
            "hit_points": sum(1 for r in results if (r.get("metrics") or {}).get("N_hit", 0) > 0),
        }

    return response
