"""Pure-Python wind analysis tool converted from demo.m workflow."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import weibull_min

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.size"] = 10
plt.rcParams["font.family"] = "DejaVu Sans"


def _resolve_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {str(c).strip().lower(): c for c in df.columns}
    for key in candidates:
        col = lower_map.get(key.lower())
        if col is not None:
            return str(col)
    return None


def _ensure_output_dir(root: Path) -> Path:
    out_dir = root / "wind_data" / "outputs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _save_fig(path: Path) -> None:
    plt.tight_layout()
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close()


def _plot_item(path: Path, title: str) -> dict[str, str]:
    data_url = ""
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
    except Exception:
        data_url = ""
    return {"title": title, "path": str(path.resolve()), "data_url": data_url}


def _wind_direction_binning(wind_dir_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    # 16 sectors centered at 0:22.5:337.5, width 22.5.
    centers = np.arange(0.0, 360.0, 22.5)
    edges = np.arange(-11.25, 360.0 + 22.5, 22.5)
    idx = np.digitize(np.mod(wind_dir_deg, 360.0), edges, right=False) - 1
    idx = np.mod(idx, 16)
    return idx, centers


@dataclass
class WindAnalysisTool:
    project_root: Path

    def invoke(self, payload: dict[str, Any]) -> str:
        excel_path = str((payload or {}).get("excel_path", "")).strip()
        if not excel_path:
            return json.dumps({"success": False, "warnings": ["excel_path is required"], "data": {}}, ensure_ascii=False)

        xlsx = Path(excel_path).expanduser()
        if not xlsx.exists() or not xlsx.is_file():
            return json.dumps({"success": False, "warnings": [f"excel file not found: {excel_path}"], "data": {}}, ensure_ascii=False)

        try:
            raw = pd.read_excel(xlsx)
        except Exception as exc:
            return json.dumps({"success": False, "warnings": [f"failed to read excel: {exc}"], "data": {}}, ensure_ascii=False)

        dir_col = _resolve_column(raw, ["winddire", "wind_dir", "direction"])
        spd_col = _resolve_column(raw, ["windspd", "wind_speed", "windspeed"])
        if not dir_col or not spd_col:
            return json.dumps(
                {"success": False, "warnings": [f"missing required columns, got={list(map(str, raw.columns))}"], "data": {}},
                ensure_ascii=False,
            )

        wind_dir = pd.to_numeric(raw[dir_col], errors="coerce")
        wind_speed = pd.to_numeric(raw[spd_col], errors="coerce")

        # demo.m: inan = isnan(windDire .* windSpeed)
        valid = ~(wind_dir.isna() | wind_speed.isna())
        wind_dir = np.mod(wind_dir[valid].to_numpy(dtype=float), 360.0)
        wind_speed = wind_speed[valid].to_numpy(dtype=float)
        if wind_speed.size == 0:
            return json.dumps({"success": False, "warnings": ["no valid rows after NaN filtering"], "data": {}}, ensure_ascii=False)

        out_dir = _ensure_output_dir(self.project_root)
        charts: list[dict[str, str]] = []
        warnings: list[str] = []

        dir_labels = np.array(["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"])
        sector_idx, centers = _wind_direction_binning(wind_dir)
        occurance = np.array([(sector_idx == i).sum() / len(wind_dir) for i in range(16)], dtype=float)
        ws_mean = np.zeros(16, dtype=float)
        for i in range(16):
            s = wind_speed[sector_idx == i]
            s = s[s > 3.0]
            ws_mean[i] = float(np.mean(s)) if s.size else 0.0

        # 1) polar plot of occurrence
        theta = np.deg2rad(np.r_[centers, centers[0], centers[1]])
        rr = np.r_[occurance, occurance[0], occurance[1]]
        plt.figure(figsize=(8 * 0.59, 5 * 0.59))
        ax = plt.subplot(111, projection="polar")
        ax.plot(theta, rr, "r-", linewidth=2.5)
        ax.set_theta_direction(-1)
        ax.set_theta_zero_location("N")
        ax.set_thetagrids(np.arange(0, 360, 22.5), labels=dir_labels.tolist())
        p = out_dir / "01_polar_occurrence.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Polar Occurrence"))

        # 2) direction probability bar
        plt.figure(figsize=(12 / 2.54, 6 / 2.54))
        plt.bar(dir_labels, occurance, color=np.array([113, 180, 255]) / 256, edgecolor=np.array([113, 180, 255]) / 256, linewidth=0.1)
        plt.ylabel("Probability")
        plt.xticks(rotation=30, ha="right")
        p = out_dir / "02_direction_probability_bar.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Direction Probability"))

        # 3) mean wind speed by direction
        plt.figure(figsize=(12 / 2.54, 6 / 2.54))
        plt.bar(dir_labels, ws_mean, color=np.array([113, 180, 255]) / 256, edgecolor=np.array([113, 180, 255]) / 256, linewidth=0.1)
        plt.ylabel("Avg. Wind Speed (m/s)")
        plt.axhline(3, color="k", linestyle="--")
        plt.ylim([0, 8])
        plt.xticks(rotation=30, ha="right")
        p = out_dir / "03_mean_speed_by_direction.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Average Wind Speed by Direction"))

        # 4) histogram (bin=1, pdf)
        plt.figure(figsize=(10 / 2.54, 6 / 2.54))
        bins_1 = np.arange(0, max(15.0, np.ceil(float(wind_speed.max())) + 1.0), 1.0)
        plt.hist(wind_speed, bins=bins_1, density=True, color=np.array([113, 180, 255]) / 256, edgecolor=np.array([113, 180, 255]) / 256)
        plt.xlabel("Wind Speed (m/s)")
        plt.ylabel("Probability")
        plt.xlim([0, 15])
        plt.ylim([0, 0.4])
        p = out_dir / "04_histogram_bin1_pdf.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Histogram (BinWidth=1)"))

        # 5) histogram + Weibull (bin=0.5)
        shape_k = None
        scale_a = None
        plt.figure(figsize=(10 / 2.54, 6 / 2.54))
        bins_05 = np.arange(0, max(15.0, np.ceil(float(wind_speed.max())) + 0.5), 0.5)
        plt.hist(wind_speed, bins=bins_05, density=True, color=np.array([113, 180, 255]) / 256, edgecolor=np.array([113, 180, 255]) / 256)
        try:
            c, loc, scale = weibull_min.fit(wind_speed, floc=0.0)
            shape_k = float(c)
            scale_a = float(scale)
            x_plot = np.linspace(0.0, 15.0, 200)
            y_plot = weibull_min.pdf(x_plot, c, loc=loc, scale=scale)
            plt.plot(x_plot, y_plot, "r-", linewidth=2, label=f"Weibull fit (A={scale_a:.2f}, k={shape_k:.2f})")
            plt.legend(loc="upper right")
        except Exception as exc:
            warnings.append(f"weibull_fit_failed: {exc}")
        plt.axvline(float(np.mean(wind_speed)), color="k", linestyle="--")
        plt.xlabel("Wind Speed (m/s)")
        plt.ylabel("Probability Density")
        plt.xlim([0, 15])
        plt.ylim([0, 0.4])
        p = out_dir / "05_histogram_weibull_bin05.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Histogram + Weibull (BinWidth=0.5)"))

        # 6) 4x4 histograms by direction
        fig, axes = plt.subplots(4, 4, figsize=(28 / 2.54, 22 / 2.54), dpi=140)
        bin_edges = [3, 7, 11, 15]
        for i, ax in enumerate(axes.flatten()):
            s = wind_speed[sector_idx == i]
            s = s[s > 3.0]
            if s.size:
                ax.hist(s, bins=bin_edges, density=False, weights=np.ones_like(s) / len(s), color=np.array([113, 180, 255]) / 256, edgecolor=np.array([113, 180, 255]) / 256)
            ax.set_xlabel("Wind Speed (m/s)")
            ax.set_ylabel("Probability")
            ax.set_xlim([0, 20])
            ax.set_ylim([0, 1])
            ax.set_title(dir_labels[i])
            ax.tick_params(axis="both", labelsize=8)
        p = out_dir / "06_subplots_hist_by_direction.png"
        plt.tight_layout()
        plt.savefig(p, dpi=180, bbox_inches="tight")
        plt.close(fig)
        charts.append(_plot_item(p, "Wind Speed Distribution by Direction (4x4)"))

        # 7) stacked polar histogram (version 1, cumulative masks as demo.m)
        plt.figure(figsize=(8 / 2.54, 8 / 2.54))
        ax = plt.subplot(111, projection="polar")
        ax.set_theta_direction(-1)
        ax.set_theta_zero_location("N")
        edges = np.deg2rad(np.arange(0, 360 + 22.5, 22.5))
        ax.hist(np.deg2rad(wind_dir[wind_speed < 15]), bins=edges, density=True, color="#f3ed27", alpha=0.85, label="11 - 15 m/s")
        ax.hist(np.deg2rad(wind_dir[wind_speed < 11]), bins=edges, density=True, color="#e97256", alpha=0.75, label="7 - 11 m/s")
        ax.hist(np.deg2rad(wind_dir[(wind_speed < 7) & (wind_speed > 3)]), bins=edges, density=True, color="#8005a8", alpha=0.7, label="3 - 7 m/s")
        ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15))
        p = out_dir / "07_polar_hist_stacked_v1.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Polar Histogram by Speed Bin (v1)"))

        # 8) stacked polar histogram (version 2, shifted edges)
        plt.figure(figsize=(8 / 2.54, 8 / 2.54))
        ax = plt.subplot(111, projection="polar")
        ax.set_theta_direction(-1)
        ax.set_theta_zero_location("N")
        shifted_deg = np.arange(-11.25, 360 - 11.25 + 22.5, 22.5)
        shifted_edges = np.deg2rad(shifted_deg)
        ax.hist(np.deg2rad(wind_dir[wind_speed < 15]), bins=shifted_edges, density=True, color="#f3ed27", alpha=0.85, label="11 - 15 m/s")
        ax.hist(np.deg2rad(wind_dir[wind_speed < 11]), bins=shifted_edges, density=True, color="#e97256", alpha=0.75, label="7 - 11 m/s")
        ax.hist(np.deg2rad(wind_dir[(wind_speed < 7) & (wind_speed > 3)]), bins=shifted_edges, density=True, color="#8005a8", alpha=0.7, label="3 - 7 m/s")
        ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.15))
        p = out_dir / "08_polar_hist_stacked_v2.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Polar Histogram by Speed Bin (v2)"))

        # 9) histogram + Weibull (bin=1)
        shape_k_bin1 = None
        scale_a_bin1 = None
        plt.figure(figsize=(10 / 2.54, 6 / 2.54))
        plt.hist(wind_speed, bins=bins_1, density=True, color=np.array([113, 180, 255]) / 256, edgecolor=np.array([113, 180, 255]) / 256)
        try:
            c1, loc1, scale1 = weibull_min.fit(wind_speed, floc=0.0)
            shape_k_bin1 = float(c1)
            scale_a_bin1 = float(scale1)
            x_plot = np.linspace(0.0, 15.0, 200)
            y_plot = weibull_min.pdf(x_plot, c1, loc=loc1, scale=scale1)
            plt.plot(x_plot, y_plot, "r-", linewidth=2, label=f"Weibull fit (A={scale_a_bin1:.2f}, k={shape_k_bin1:.2f})")
            plt.legend(loc="upper right")
        except Exception as exc:
            warnings.append(f"weibull_fit_bin1_failed: {exc}")
        plt.axvline(float(np.mean(wind_speed)), color="k", linestyle="--")
        plt.xlabel("Wind Speed (m/s)")
        plt.ylabel("Probability Density")
        plt.xlim([0, 15])
        plt.ylim([0, 0.4])
        p = out_dir / "09_histogram_weibull_bin1.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Histogram + Weibull (BinWidth=1)"))

        # 10) Joint probability density full range
        speed_bin_width = 2.0
        speed_edges = np.arange(0.0, np.ceil(float(np.max(wind_speed))) + speed_bin_width, speed_bin_width)
        dir_bin_width = 22.5
        dir_edges = np.arange(-dir_bin_width / 2.0, 360 - dir_bin_width / 2.0 + dir_bin_width, dir_bin_width)
        dir_edges = np.r_[dir_edges, dir_edges[-1] + dir_bin_width]
        counts, _, _ = np.histogram2d(wind_speed, wind_dir, bins=[speed_edges, dir_edges])
        denom = float(np.sum(counts))
        counts_prob = counts / denom if denom > 0 else counts
        plt.figure(figsize=(16 * 0.95 / 2.54, 8 * 0.95 / 2.54))
        x_centers = np.arange(0.0, 360.0, 22.5) - 12.25
        y_centers = speed_edges[:-1] + speed_bin_width / 2.0
        plt.imshow(
            counts_prob,
            origin="lower",
            aspect="auto",
            extent=[x_centers.min(), x_centers.max(), y_centers.min(), y_centers.max()],
            cmap="viridis",
        )
        plt.xticks(np.arange(0.0, 360.0, 22.5), dir_labels.tolist(), rotation=35, ha="right")
        plt.xlabel("Wind Direction")
        plt.ylabel("Wind Speed (m/s)")
        plt.title("Joint Probability Density (Wind Speed & Direction)")
        plt.colorbar()
        p = out_dir / "10_joint_probability_density_full.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Joint Probability Density (Full)"))

        # 11) Joint probability density within [3, 15] bins [3,7), [7,11), [11,15]
        speed_edges_3 = np.array([3.0, 7.0, 11.0, 15.0])
        counts3, _, _ = np.histogram2d(wind_speed, wind_dir, bins=[speed_edges_3, dir_edges])
        denom3 = float(np.sum(counts3))
        probs3 = counts3 / denom3 if denom3 > 0 else counts3
        plt.figure(figsize=(16 * 0.9 / 2.54, 12 * 0.9 / 2.54))
        speed_centers = (speed_edges_3[:-1] + speed_edges_3[1:]) / 2.0
        plt.imshow(
            probs3,
            origin="lower",
            aspect="auto",
            extent=[x_centers.min(), x_centers.max(), speed_centers.min(), speed_centers.max()],
            cmap="viridis",
        )
        plt.xticks(np.arange(0.0, 360.0, 22.5), dir_labels.tolist(), rotation=35, ha="right")
        plt.yticks(speed_centers, ["3-7", "7-11", "11-15"])
        plt.xlabel("Wind Direction")
        plt.ylabel("Wind Speed Bin (m/s)")
        plt.title("Joint Probability Density")
        plt.colorbar()
        p = out_dir / "11_joint_probability_density_3bins.png"
        _save_fig(p)
        charts.append(_plot_item(p, "Joint Probability Density (3 Bins)"))

        data = {
            "source_excel": str(xlsx.resolve()),
            "valid_rows": int(len(wind_speed)),
            "mean_wind_speed": float(np.mean(wind_speed)),
            "max_wind_speed": float(np.max(wind_speed)),
            "direction_occurrence": {str(dir_labels[i]): float(occurance[i]) for i in range(16)},
            "direction_mean_speed": {str(dir_labels[i]): float(ws_mean[i]) for i in range(16)},
            "weibull_fit": {"shape_k": shape_k, "scale_a": scale_a},
            "weibull_fit_bin1": {"shape_k": shape_k_bin1, "scale_a": scale_a_bin1},
            "charts": charts,
            "output_dir": str(out_dir.resolve()),
        }
        return json.dumps({"success": True, "warnings": warnings, "data": data}, ensure_ascii=False)


def build_wind_analysis_tool() -> WindAnalysisTool:
    return WindAnalysisTool(project_root=Path(__file__).resolve().parents[1])
