from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

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


@dataclass
class PreparedData:
    df: pd.DataFrame
    wind_speed: np.ndarray
    wind_dire_q: np.ndarray
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
            prepared = self._load_and_validate(input_path)
            charts = self._build_charts(prepared, output_dir)
            data = self._build_structured_data(prepared)

            result = WindAnalysisOutput(
                success=True,
                message="Wind analysis completed successfully",
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
            raise WindAnalysisError(f"Missing required columns: {sorted(missing)}")

        total_rows = len(df)
        if total_rows == 0:
            raise WindAnalysisError("Input Excel has no rows")

        df = df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["windSpd"] = pd.to_numeric(df["windSpd"], errors="coerce")
        df["windDire"] = pd.to_numeric(df["windDire"], errors="coerce")
        df = df.sort_values("date")

        mask = np.isfinite(df["windSpd"].to_numpy()) & np.isfinite(df["windDire"].to_numpy())
        df = df.loc[mask].reset_index(drop=True)

        if df.empty:
            raise WindAnalysisError("No valid rows after cleaning windSpd/windDire")

        wind_speed = df["windSpd"].to_numpy(dtype=float)
        wind_dire = df["windDire"].to_numpy(dtype=float)

        if np.any(wind_speed < 0):
            wind_speed = np.where(wind_speed < 0, np.nan, wind_speed)
            keep = np.isfinite(wind_speed)
            df = df.loc[keep].reset_index(drop=True)
            wind_speed = wind_speed[keep]
            wind_dire = wind_dire[keep]

        if len(wind_speed) == 0:
            raise WindAnalysisError("All wind speeds are invalid after filtering")

        wind_dire_q = (np.round((wind_dire % 360) / 22.5) * 22.5) % 360

        return PreparedData(
            df=df,
            wind_speed=wind_speed,
            wind_dire_q=wind_dire_q,
            total_rows=total_rows,
            valid_rows=len(df),
        )

    def _build_structured_data(self, prepared: PreparedData) -> WindAnalysisData:
        wind_speed = prepared.wind_speed
        wind_dire_q = prepared.wind_dire_q

        direction_metrics: List[DirectionMetric] = []
        for label, wd in zip(WIND_LABELS, DIR_CENTERS):
            idx = np.isclose(wind_dire_q, wd)
            occurrence = float(idx.sum() / len(wind_dire_q))
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

    def _build_charts(self, prepared: PreparedData, output_dir: Path) -> Dict[str, str]:
        wind_speed = prepared.wind_speed
        wind_dire_q = prepared.wind_dire_q

        occurrence = []
        ws_mean = []
        for wd in DIR_CENTERS:
            idx = np.isclose(wind_dire_q, wd)
            occurrence.append(idx.sum() / len(wind_dire_q))
            ws = wind_speed[idx]
            ws = ws[ws > 3]
            ws_mean.append(np.nan if len(ws) == 0 else ws.mean())

        occurrence = np.asarray(occurrence, dtype=float)
        ws_mean = np.asarray(ws_mean, dtype=float)

        charts: Dict[str, str] = {}

        charts["polar_occurrence"] = str(self._plot_polar_occurrence(occurrence, output_dir))
        charts["bar_occurrence"] = str(self._plot_bar_occurrence(occurrence, output_dir))
        charts["bar_mean_speed"] = str(self._plot_bar_mean_speed(ws_mean, output_dir))
        charts["histogram_weibull"] = str(self._plot_weibull(wind_speed, output_dir))
        charts["wind_rose"] = str(self._plot_wind_rose(wind_speed, wind_dire_q, output_dir))

        return charts

    def _plot_polar_occurrence(self, occurrence: np.ndarray, output_dir: Path) -> Path:
        theta = np.deg2rad(np.r_[DIR_CENTERS, DIR_CENTERS[0]])
        r = np.r_[occurrence, occurrence[0]]

        fig = plt.figure(figsize=(8, 5))
        ax = fig.add_subplot(111, projection="polar")
        ax.plot(theta, r, linewidth=2.2)
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_thetagrids(DIR_CENTERS, labels=WIND_LABELS)
        ax.set_title("Occurrence probability by wind direction")
        fig.tight_layout()

        path = output_dir / "01_polar_occurrence.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_bar_occurrence(self, occurrence: np.ndarray, output_dir: Path) -> Path:
        fig = plt.figure(figsize=(10, 5))
        plt.bar(WIND_LABELS, occurrence)
        plt.ylabel("Probability")
        plt.title("Wind direction occurrence probability")
        fig.tight_layout()

        path = output_dir / "02_bar_occurrence.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_bar_mean_speed(self, ws_mean: np.ndarray, output_dir: Path) -> Path:
        fig = plt.figure(figsize=(10, 5))
        plt.bar(WIND_LABELS, ws_mean)
        plt.ylabel("Avg Wind Speed (m/s)")
        plt.axhline(3, linestyle="--")
        plt.title("Average wind speed by direction (wind speed > 3 m/s)")
        fig.tight_layout()

        path = output_dir / "03_bar_ws_mean.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_weibull(self, wind_speed: np.ndarray, output_dir: Path) -> Path:
        shape_k, _, scale_a = weibull_min.fit(wind_speed, floc=0)
        x_plot = np.linspace(0, max(15, float(np.nanmax(wind_speed)) + 1), 300)
        y_plot = weibull_min.pdf(x_plot, shape_k, loc=0, scale=scale_a)

        fig = plt.figure(figsize=(10, 6))
        bins = np.arange(0, max(15.5, float(np.nanmax(wind_speed)) + 1), 0.5)
        plt.hist(wind_speed, bins=bins, density=True, alpha=0.65, label="Observed")
        plt.plot(x_plot, y_plot, linewidth=2, label=f"Weibull fit (A={scale_a:.2f}, k={shape_k:.2f})")
        plt.axvline(float(np.mean(wind_speed)), linestyle="--", label="Mean")
        plt.xlabel("Wind Speed (m/s)")
        plt.ylabel("Probability Density")
        plt.legend()
        plt.title("Wind speed histogram with Weibull fit")
        fig.tight_layout()

        path = output_dir / "04_weibull_fit.png"
        fig.savefig(path, dpi=180)
        plt.close(fig)
        return path

    def _plot_wind_rose(self, wind_speed: np.ndarray, wind_dire_q: np.ndarray, output_dir: Path) -> Path:
        # Non-overlapping bins: [3,7), [7,11), [11,15]
        speed_bins: List[Tuple[float, float, bool]] = [
            (3.0, 7.0, False),
            (7.0, 11.0, False),
            (11.0, 15.0, True),
        ]
        speed_labels = ["3-7 m/s", "7-11 m/s", "11-15 m/s"]

        dir_edges = np.deg2rad(np.arange(-11.25, 360, 22.5))
        counts_by_speed = []

        for lo, hi, include_right in speed_bins:
            if include_right:
                in_bin = (wind_speed >= lo) & (wind_speed <= hi)
            else:
                in_bin = (wind_speed >= lo) & (wind_speed < hi)
            counts, _ = np.histogram(np.deg2rad(wind_dire_q[in_bin]), bins=dir_edges)
            counts_by_speed.append(counts / len(wind_speed))

        counts_by_speed = np.asarray(counts_by_speed)
        theta_centers = np.deg2rad(DIR_CENTERS)
        width = np.deg2rad(22.5)

        fig = plt.figure(figsize=(9, 7))
        ax = fig.add_subplot(111, projection="polar")
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)

        bottom = np.zeros_like(theta_centers, dtype=float)
        for i, label in enumerate(speed_labels):
            ax.bar(
                theta_centers,
                counts_by_speed[i],
                width=width,
                bottom=bottom,
                align="center",
                alpha=0.8,
                label=label,
            )
            bottom += counts_by_speed[i]

        ax.set_thetagrids(DIR_CENTERS, labels=WIND_LABELS)
        ax.set_title("Wind rose by speed range")
        ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1.0))
        fig.tight_layout()

        path = output_dir / "05_wind_rose.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return path

    def _write_json(self, result: WindAnalysisOutput, path: Path) -> None:
        payload = json.dumps(result.model_dump(), indent=2, ensure_ascii=False)
        path.write_text(payload, encoding="utf-8")


def run_analysis(excel_path: str) -> WindAnalysisOutput:
    payload = WindAnalysisInput(excel_path=excel_path)
    return WindAnalysisService().analyze(payload)
