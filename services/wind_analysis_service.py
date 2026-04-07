"""Wind analysis service aligned to demo.m with strict profile encapsulation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import weibull_min

from schemas.wind_analysis import (
    DirectionMetric,
    WeibullFitResult,
    WindAnalysisData,
    WindAnalysisInput,
    WindAnalysisOutput,
)


WIND_LABELS = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
]
DIR_CENTERS = np.arange(0, 360, 22.5)
REQUIRED_COLUMNS = {"date", "windSpd", "windDire"}
JP_16_DIR_TO_DEG: Dict[str, float] = {
    "北": 0.0,
    "北北東": 22.5,
    "北東": 45.0,
    "東北東": 67.5,
    "東": 90.0,
    "東南東": 112.5,
    "南東": 135.0,
    "南南東": 157.5,
    "南": 180.0,
    "南南西": 202.5,
    "南西": 225.0,
    "西南西": 247.5,
    "西": 270.0,
    "西北西": 292.5,
    "北西": 315.0,
    "北北西": 337.5,
}


@dataclass
class PreparedData:
    df: pd.DataFrame
    wind_speed: np.ndarray
    wind_dire: np.ndarray
    total_rows: int
    valid_rows: int


class WindAnalysisError(RuntimeError):
    pass


class WindAnalysisService:
    def analyze(self, payload: WindAnalysisInput) -> WindAnalysisOutput:
        input_path = Path(payload.excel_path).expanduser().resolve()
        output_dir = self._build_output_dir(input_path)
        warnings: List[str] = []

        try:
            profile = str(payload.analysis_profile or "demo_m_strict").strip().lower()
            if profile not in {"demo_m_strict"}:
                warnings.append(f"Unknown analysis_profile={payload.analysis_profile}, fallback to demo_m_strict")
                profile = "demo_m_strict"

            prepared = self._load_and_validate(input_path)
            charts = self._build_charts_demo_m_strict(prepared, output_dir)
            data = self._build_structured_data_demo_m_strict(prepared)

            result = WindAnalysisOutput(
                success=True,
                message=f"Wind analysis completed successfully ({profile})",
                input_file=str(input_path),
                output_dir=str(output_dir),
                charts=charts,
                data=data,
                warnings=warnings,
            )
            self._write_json(result, output_dir / "result.json")
            return result
        except Exception as exc:  # noqa: BLE001
            warnings.append(str(exc))
            result = WindAnalysisOutput(
                success=False,
                message="Wind analysis failed",
                input_file=str(input_path),
                output_dir=str(output_dir),
                charts={},
                data=None,
                warnings=warnings,
            )
            output_dir.mkdir(parents=True, exist_ok=True)
            self._write_json(result, output_dir / "result.json")
            return result

    def _build_output_dir(self, input_path: Path) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = input_path.parent / "outputs" / stamp
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _load_and_validate(self, input_path: Path) -> PreparedData:
        if not input_path.exists() or not input_path.is_file():
            raise WindAnalysisError(f"Input file does not exist: {input_path}")

        try:
            df = pd.read_excel(input_path)
        except Exception as exc:  # noqa: BLE001
            raise WindAnalysisError(f"Failed to read Excel file: {exc}") from exc

        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            df = self._try_parse_multiline_weather_format(input_path)
            missing2 = REQUIRED_COLUMNS - set(df.columns)
            if missing2:
                raise WindAnalysisError(f"Missing required columns: {sorted(missing2)}")

        total_rows = len(df)
        if total_rows == 0:
            raise WindAnalysisError("Input Excel has no rows")

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["windSpd"] = pd.to_numeric(df["windSpd"], errors="coerce")
        df["windDire"] = pd.to_numeric(df["windDire"], errors="coerce")
        df = df.sort_values("date")

        wind_speed = df["windSpd"].to_numpy(dtype=float)
        wind_dire = np.mod(df["windDire"].to_numpy(dtype=float), 360.0)

        # demo.m equivalent: remove NaN from windDire .* windSpeed
        valid = np.isfinite(wind_dire * wind_speed)
        wind_speed = wind_speed[valid]
        wind_dire = wind_dire[valid]
        df = df.loc[valid].reset_index(drop=True)

        if np.any(wind_speed < 0):
            keep = wind_speed >= 0
            wind_speed = wind_speed[keep]
            wind_dire = wind_dire[keep]
            df = df.loc[keep].reset_index(drop=True)

        if len(wind_speed) == 0:
            raise WindAnalysisError("All wind speeds are invalid after filtering")

        return PreparedData(
            df=df,
            wind_speed=wind_speed,
            wind_dire=wind_dire,
            total_rows=total_rows,
            valid_rows=len(df),
        )

    def _try_parse_multiline_weather_format(self, input_path: Path) -> pd.DataFrame:
        raw = pd.read_excel(input_path, header=None)
        if raw.empty:
            raise WindAnalysisError("Input Excel has no rows")

        def _norm(v: object) -> str:
            return str(v or "").strip().replace(" ", "")

        header_row_idx = None
        date_col = None
        speed_col = None
        dir_col = None

        for i in range(min(len(raw), 60)):
            row = raw.iloc[i]
            tokens = [_norm(v) for v in row.tolist()]
            if date_col is None:
                for c, t in enumerate(tokens):
                    if t in {"年月日", "日付", "date"}:
                        date_col = c
                        break
            if speed_col is None:
                for c, t in enumerate(tokens):
                    if "平均風速" in t or t.lower() in {"windspd", "windspeed"}:
                        speed_col = c
                        break
            if dir_col is None:
                for c, t in enumerate(tokens):
                    if "最多風向" in t or "風向" in t or t.lower() in {"winddire", "winddir"}:
                        dir_col = c
                        break
            if date_col is not None and speed_col is not None and dir_col is not None:
                header_row_idx = i
                break

        if header_row_idx is None or date_col is None or speed_col is None or dir_col is None:
            raise WindAnalysisError("Missing required columns: ['date', 'windDire', 'windSpd']")

        body = raw.iloc[header_row_idx + 1 :, [date_col, speed_col, dir_col]].copy()
        body.columns = ["date", "windSpd", "windDireRaw"]
        body["date"] = pd.to_datetime(body["date"], errors="coerce")
        body["windSpd"] = pd.to_numeric(body["windSpd"], errors="coerce")

        def _to_deg(v: object) -> float:
            s = str(v or "").strip()
            if not s:
                return np.nan
            num = pd.to_numeric(s, errors="coerce")
            if pd.notna(num):
                return float(num) % 360.0
            return float(JP_16_DIR_TO_DEG.get(s, np.nan))

        body["windDire"] = body["windDireRaw"].map(_to_deg)
        body = body.drop(columns=["windDireRaw"])
        return body

    def _build_structured_data_demo_m_strict(self, prepared: PreparedData) -> WindAnalysisData:
        wind_speed = prepared.wind_speed
        wind_dire = prepared.wind_dire

        direction_metrics: List[DirectionMetric] = []
        for label, wd in zip(WIND_LABELS, DIR_CENTERS):
            idx = np.isclose(wind_dire, wd, atol=1e-6)
            occurrence = float(idx.sum() / len(wind_dire))
            ws = wind_speed[idx]
            ws = ws[ws > 3]
            ws_mean = float(np.mean(ws)) if ws.size else None
            direction_metrics.append(
                DirectionMetric(
                    label=label,
                    center_degree=float(wd),
                    occurrence_probability=occurrence,
                    mean_wind_speed_gt3=ws_mean,
                )
            )

        shape_k, _, scale_a = weibull_min.fit(wind_speed, floc=0)
        weibull_fit = WeibullFitResult(
            shape_k=float(shape_k),
            scale_a=float(scale_a),
            mean_wind_speed=float(np.mean(wind_speed)),
        )

        return WindAnalysisData(
            total_rows=prepared.total_rows,
            valid_rows=prepared.valid_rows,
            dropped_rows=prepared.total_rows - prepared.valid_rows,
            direction_metrics=direction_metrics,
            weibull_fit=weibull_fit,
        )

    def _calc_occurrence_ws_mean_demo(self, wind_speed: np.ndarray, wind_dire: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        occ = []
        ws_mean = []
        for wd in DIR_CENTERS:
            idx = np.isclose(wind_dire, wd, atol=1e-6)
            occ.append(float(idx.sum() / max(1, len(wind_dire))))
            ws = wind_speed[idx]
            ws = ws[ws > 3]
            ws_mean.append(float(np.mean(ws)) if ws.size else np.nan)
        return np.asarray(occ, dtype=float), np.asarray(ws_mean, dtype=float)

    def _build_charts_demo_m_strict(self, prepared: PreparedData, output_dir: Path) -> Dict[str, str]:
        wind_speed = prepared.wind_speed
        wind_dire = prepared.wind_dire
        occurrence, ws_mean = self._calc_occurrence_ws_mean_demo(wind_speed, wind_dire)

        charts: Dict[str, str] = {}
        charts["polar_occurrence"] = str(self._plot_polar_occurrence_demo(occurrence, output_dir))
        charts["bar_occurrence"] = str(self._plot_bar_occurrence_demo(occurrence, output_dir))
        charts["bar_mean_speed"] = str(self._plot_bar_mean_speed_demo(ws_mean, output_dir))
        charts["histogram_pdf"] = str(self._plot_histogram_pdf_demo(wind_speed, output_dir))
        charts["histogram_weibull"] = str(self._plot_weibull_fit_demo(wind_speed, output_dir))
        charts["direction_speed_subplots"] = str(self._plot_direction_speed_subplots_demo(wind_speed, wind_dire, output_dir))
        charts["wind_rose_basic"] = str(self._plot_wind_rose_basic_demo(wind_speed, wind_dire, output_dir))
        charts["wind_rose"] = str(self._plot_wind_rose_shifted_demo(wind_speed, wind_dire, output_dir))
        charts["joint_probability_density"] = str(self._plot_jpd_demo(wind_speed, wind_dire, output_dir))
        return charts

    def _plot_polar_occurrence_demo(self, occurrence: np.ndarray, output_dir: Path) -> Path:
        theta = np.deg2rad(np.r_[DIR_CENTERS, DIR_CENTERS[0], DIR_CENTERS[1]])
        r = np.r_[occurrence, occurrence[0], occurrence[1]]
        fig = plt.figure(figsize=(12, 7.5))
        ax = fig.add_subplot(111, projection="polar")
        ax.plot(theta, r, "r-", linewidth=2.5)
        ax.set_theta_direction(-1)
        ax.set_theta_zero_location("N")
        ax.set_thetagrids(np.arange(0, 360, 22.5), labels=WIND_LABELS)
        fig.tight_layout()
        path = output_dir / "01_polar_occurrence.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_bar_occurrence_demo(self, occurrence: np.ndarray, output_dir: Path) -> Path:
        fig = plt.figure(figsize=(10, 5))
        c = np.array([113, 180, 255]) / 256.0
        plt.bar(WIND_LABELS, occurrence, facecolor=c, edgecolor=c, linewidth=0.1)
        plt.ylabel("Probability")
        fig.tight_layout()
        path = output_dir / "02_bar_occurrence.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_bar_mean_speed_demo(self, ws_mean: np.ndarray, output_dir: Path) -> Path:
        fig = plt.figure(figsize=(10, 5))
        c = np.array([113, 180, 255]) / 256.0
        plt.bar(WIND_LABELS, ws_mean, facecolor=c, edgecolor=c, linewidth=0.1)
        plt.ylabel("Avg. Wind Speed (m/s)")
        plt.axhline(3, linestyle="--", color="k")
        plt.ylim(0, 8)
        fig.tight_layout()
        path = output_dir / "03_bar_ws_mean.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_histogram_pdf_demo(self, wind_speed: np.ndarray, output_dir: Path) -> Path:
        fig = plt.figure(figsize=(10, 6))
        c = np.array([113, 180, 255]) / 256.0
        bins = np.arange(0, 16, 1)
        plt.hist(wind_speed, bins=bins, density=True, facecolor=c, edgecolor=c)
        plt.xlabel("Wind Speed (m/s)")
        plt.ylabel("Probability")
        plt.xlim(0, 15)
        plt.ylim(0, 0.4)
        fig.tight_layout()
        path = output_dir / "04_histogram_pdf.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_weibull_fit_demo(self, wind_speed: np.ndarray, output_dir: Path) -> Path:
        shape_k, _, scale_a = weibull_min.fit(wind_speed, floc=0)
        x_plot = np.linspace(0, 15, 200)
        y_plot = weibull_min.pdf(x_plot, shape_k, loc=0, scale=scale_a)
        fig = plt.figure(figsize=(10, 6))
        c = np.array([113, 180, 255]) / 256.0
        bins = np.arange(0, 15.5, 0.5)
        plt.hist(wind_speed, bins=bins, density=True, facecolor=c, edgecolor=c)
        plt.plot(x_plot, y_plot, "r-", linewidth=2, label=f"Weibull fit (A={scale_a:.2f}, k={shape_k:.2f})")
        plt.axvline(float(np.mean(wind_speed)), linestyle="--", color="k", label="Mean")
        plt.xlabel("Wind Speed (m/s)")
        plt.ylabel("Probability Density")
        plt.xlim(0, 15)
        plt.ylim(0, 0.4)
        plt.legend(loc="best")
        fig.tight_layout()
        path = output_dir / "05_weibull_fit.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_direction_speed_subplots_demo(self, wind_speed: np.ndarray, wind_dire: np.ndarray, output_dir: Path) -> Path:
        fig = plt.figure(figsize=(25, 20))
        c = np.array([113, 180, 255]) / 256.0
        for i, (label, wd) in enumerate(zip(WIND_LABELS, DIR_CENTERS), start=1):
            idx = np.isclose(wind_dire, wd, atol=1e-6)
            ws = wind_speed[idx]
            ws = ws[ws > 3]
            ax = fig.add_subplot(4, 4, i)
            ax.hist(ws, bins=[3, 7, 11, 15], density=True if ws.size > 0 else False, facecolor=c, edgecolor=c)
            ax.set_xlabel("Wind Speed (m/s)")
            ax.set_ylabel("Probability")
            ax.set_xlim(0, 20)
            ax.set_ylim(0, 1)
            ax.set_title(label)
        fig.tight_layout()
        path = output_dir / "06_direction_speed_subplots.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_wind_rose_basic_demo(self, wind_speed: np.ndarray, wind_dire: np.ndarray, output_dir: Path) -> Path:
        dtheta = 22.5
        edges = np.deg2rad(np.arange(0, 360 + dtheta, dtheta))
        fig = plt.figure(figsize=(9, 7))
        ax = fig.add_subplot(111, projection="polar")
        ax.set_theta_direction(-1)
        ax.set_theta_zero_location("N")

        conds = [
            ("11 - 15 m/s", wind_speed < 15, "#f3ed27"),
            ("7 - 11 m/s", wind_speed < 11, "#e97256"),
            ("3 - 7 m/s", (wind_speed < 7) & (wind_speed > 3), "#8005a8"),
        ]
        centers = np.deg2rad(DIR_CENTERS)
        for label, cond, color in conds:
            vals = np.deg2rad(wind_dire[cond])
            counts, _ = np.histogram(vals, bins=edges)
            r = counts / max(1, len(wind_speed))
            ax.bar(centers, r, width=np.deg2rad(dtheta), align="center", alpha=0.55, color=color, label=label)

        ax.set_thetagrids(DIR_CENTERS, labels=WIND_LABELS)
        ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1.0))
        fig.tight_layout()
        path = output_dir / "07_wind_rose_basic.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return path

    def _plot_wind_rose_shifted_demo(self, wind_speed: np.ndarray, wind_dire: np.ndarray, output_dir: Path) -> Path:
        dtheta = 22.5
        half = dtheta / 2.0
        edges_deg = np.arange(-half, 360 - half + dtheta, dtheta)
        edges = np.deg2rad(edges_deg)

        fig = plt.figure(figsize=(9, 7))
        ax = fig.add_subplot(111, projection="polar")
        ax.set_theta_direction(-1)
        ax.set_theta_zero_location("N")

        conds = [
            ("11 - 15 m/s", wind_speed < 15, "#f3ed27"),
            ("7 - 11 m/s", wind_speed < 11, "#e97256"),
            ("3 - 7 m/s", (wind_speed < 7) & (wind_speed > 3), "#8005a8"),
        ]
        centers = np.deg2rad(DIR_CENTERS)
        for label, cond, color in conds:
            vals = np.deg2rad(wind_dire[cond])
            counts, _ = np.histogram(vals, bins=edges)
            r = counts / max(1, len(wind_speed))
            ax.bar(centers, r, width=np.deg2rad(dtheta), align="center", alpha=0.55, color=color, label=label)

        ax.set_thetagrids(DIR_CENTERS, labels=WIND_LABELS)
        ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1.0))
        fig.tight_layout()
        path = output_dir / "08_wind_rose_shifted.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return path

    def _plot_jpd_demo(self, wind_speed: np.ndarray, wind_dire: np.ndarray, output_dir: Path) -> Path:
        speed_bin_width = 2.0
        speed_edges = np.arange(0, np.ceil(np.nanmax(wind_speed)) + speed_bin_width, speed_bin_width)
        dir_bin_width = 22.5
        dir_edges = np.arange(-dir_bin_width / 2.0, 360 - dir_bin_width / 2.0 + dir_bin_width, dir_bin_width)
        wind_dir_mod = np.mod(wind_dire, 360.0)

        counts, _, _ = np.histogram2d(wind_speed, wind_dir_mod, bins=[speed_edges, dir_edges])
        counts_prob = counts / max(1.0, float(np.sum(counts)))

        fig = plt.figure(figsize=(12, 7))
        ax = fig.add_subplot(111)
        x_centers = np.arange(0, 360, 22.5)
        y_centers = speed_edges[:-1] + speed_bin_width / 2.0
        im = ax.imshow(
            counts_prob,
            aspect="auto",
            origin="lower",
            extent=[x_centers[0] - 11.25, x_centers[-1] + 11.25, y_centers[0] - speed_bin_width / 2.0, y_centers[-1] + speed_bin_width / 2.0],
            cmap="viridis",
        )
        ax.set_xticks(x_centers)
        ax.set_xticklabels(WIND_LABELS)
        ax.set_xlabel("Wind Direction")
        ax.set_ylabel("Wind Speed (m/s)")
        ax.set_title("Joint Probability Density (Wind Speed & Direction)")
        fig.colorbar(im, ax=ax)
        fig.tight_layout()
        path = output_dir / "09_joint_probability_density.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _write_json(self, result: WindAnalysisOutput, path: Path) -> None:
        payload = json.dumps(result.model_dump(), indent=2, ensure_ascii=False)
        path.write_text(payload, encoding="utf-8")


def run_analysis(excel_path: str, analysis_profile: str = "demo_m_strict") -> WindAnalysisOutput:
    payload = WindAnalysisInput(excel_path=excel_path, analysis_profile=analysis_profile)
    return WindAnalysisService().analyze(payload)
