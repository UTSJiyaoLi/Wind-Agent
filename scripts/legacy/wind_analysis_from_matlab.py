# -*- coding: utf-8 -*-
"""
Wind analysis in Python
Equivalent and cleaned-up version of the provided MATLAB script.

Input file:
    /mnt/data/wind condition @Akida.xlsx
Outputs:
    figures saved into /mnt/data/wind_outputs/
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import weibull_min

# -----------------------------
# 1. Load data
# -----------------------------
file_path = "/mnt/data/wind condition @Akida.xlsx"
df = pd.read_excel(file_path)

df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date").reset_index(drop=True)

wind_dire = df["windDire"].to_numpy(dtype=float)
wind_speed = df["windSpd"].to_numpy(dtype=float)

mask = np.isfinite(wind_dire) & np.isfinite(wind_speed)
wind_dire = wind_dire[mask]
wind_speed = wind_speed[mask]
df = df.loc[mask].copy()

# Standard 16-direction labels and centers
wind_labels = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
               'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
dir_centers = np.arange(0, 360, 22.5)

# snap to the nearest 22.5 deg in case of floating-point noise
wind_dire_q = (np.round((wind_dire % 360) / 22.5) * 22.5) % 360

# output folder
out_dir = Path("/mnt/data/wind_outputs")
out_dir.mkdir(parents=True, exist_ok=True)

# -----------------------------
# 2. Occurrence probability and mean wind speed by direction
# -----------------------------
occurrence = []
ws_mean = []

for wd in dir_centers:
    idx = np.isclose(wind_dire_q, wd)
    occurrence.append(idx.sum() / len(wind_dire_q))

    ws = wind_speed[idx]
    ws = ws[ws > 3]
    ws_mean.append(np.nan if len(ws) == 0 else ws.mean())

occurrence = np.array(occurrence)
ws_mean = np.array(ws_mean)

# -----------------------------
# 3. Polar plot of occurrence probability
# -----------------------------
theta = np.deg2rad(np.r_[dir_centers, dir_centers[0]])
r = np.r_[occurrence, occurrence[0]]

fig = plt.figure(figsize=(8, 5))
ax = fig.add_subplot(111, projection="polar")
ax.plot(theta, r, linewidth=2.5)
ax.set_theta_zero_location("N")
ax.set_theta_direction(-1)
ax.set_thetagrids(dir_centers, labels=wind_labels)
ax.set_title("Occurrence probability by wind direction")
plt.tight_layout()
plt.savefig(out_dir / "01_polar_occurrence.png", dpi=200)
plt.close()

# -----------------------------
# 4. Bar chart: occurrence probability
# -----------------------------
fig = plt.figure(figsize=(10, 5))
plt.bar(wind_labels, occurrence)
plt.ylabel("Probability")
plt.title("Wind direction occurrence probability")
plt.tight_layout()
plt.savefig(out_dir / "02_bar_occurrence.png", dpi=200)
plt.close()

# -----------------------------
# 5. Bar chart: average wind speed by direction (wind speed > 3 m/s)
# -----------------------------
fig = plt.figure(figsize=(10, 5))
plt.bar(wind_labels, ws_mean)
plt.ylabel("Avg. Wind Speed (m/s)")
plt.axhline(3, linestyle="--")
plt.ylim(0, 8)
plt.title("Average wind speed by direction (wind speed > 3 m/s)")
plt.tight_layout()
plt.savefig(out_dir / "03_bar_ws_mean.png", dpi=200)
plt.close()

# -----------------------------
# 6. Histogram of wind speed
# -----------------------------
fig = plt.figure(figsize=(10, 6))
bins = np.arange(0, 16, 1)
plt.hist(wind_speed, bins=bins, density=True)
plt.xlabel("Wind Speed (m/s)")
plt.ylabel("Probability Density")
plt.xlim(0, 15)
plt.ylim(0, 0.4)
plt.title("Wind speed histogram")
plt.tight_layout()
plt.savefig(out_dir / "04_hist_wind_speed.png", dpi=200)
plt.close()

# -----------------------------
# 7. Weibull fit
# -----------------------------
# two-parameter Weibull: fix location=0
shape_k, loc, scale_A = weibull_min.fit(wind_speed, floc=0)

x_plot = np.linspace(0, 15, 300)
y_plot = weibull_min.pdf(x_plot, shape_k, loc=0, scale=scale_A)

fig = plt.figure(figsize=(10, 6))
bins = np.arange(0, 15.5, 0.5)
plt.hist(wind_speed, bins=bins, density=True, alpha=0.7, label="Observed")
plt.plot(x_plot, y_plot, linewidth=2, label=f"Weibull fit (A={scale_A:.2f}, k={shape_k:.2f})")
plt.axvline(wind_speed.mean(), linestyle="--", label="Mean")
plt.xlabel("Wind Speed (m/s)")
plt.ylabel("Probability Density")
plt.xlim(0, 15)
plt.ylim(0, 0.4)
plt.legend()
plt.title("Wind speed histogram with Weibull fit")
plt.tight_layout()
plt.savefig(out_dir / "05_weibull_fit.png", dpi=200)
plt.close()

# -----------------------------
# 8. Wind speed distribution for each direction
# -----------------------------
fig, axes = plt.subplots(4, 4, figsize=(15, 12))
axes = axes.flatten()

for i, wd in enumerate(dir_centers):
    idx = np.isclose(wind_dire_q, wd)
    ws = wind_speed[idx]
    ws = ws[ws > 3]

    ax = axes[i]
    ax.hist(ws, bins=[3, 7, 11, 15], density=True)
    ax.set_xlim(0, 20)
    ax.set_ylim(0, 1)
    ax.set_title(wind_labels[i])
    ax.set_xlabel("Wind Speed (m/s)")
    ax.set_ylabel("Probability")

fig.suptitle("Wind speed distribution by wind direction", y=1.02)
plt.tight_layout()
plt.savefig(out_dir / "06_hist_by_direction.png", dpi=200)
plt.close()

# -----------------------------
# 9. Wind rose style stacked polar histogram
#    Important: use non-overlapping bins
# -----------------------------
speed_bins = [(3, 7), (7, 11), (11, 15)]
speed_bin_labels = ["3-7 m/s", "7-11 m/s", "11-15 m/s"]
dir_edges = np.deg2rad(np.arange(-11.25, 360 + 22.5, 22.5))

counts_by_speed = []
for lo, hi in speed_bins:
    mask_bin = (wind_speed >= lo) & (wind_speed < hi)
    counts, _ = np.histogram(np.deg2rad(wind_dire_q[mask_bin]), bins=dir_edges)
    counts_by_speed.append(counts / len(wind_speed))

counts_by_speed = np.array(counts_by_speed)
theta_centers = np.deg2rad(dir_centers)
width = np.deg2rad(22.5)

fig = plt.figure(figsize=(9, 7))
ax = fig.add_subplot(111, projection="polar")
ax.set_theta_zero_location("N")
ax.set_theta_direction(-1)
bottom = np.zeros_like(theta_centers, dtype=float)

for i in range(len(speed_bins)):
    ax.bar(theta_centers, counts_by_speed[i], width=width, bottom=bottom, align="center", alpha=0.8, label=speed_bin_labels[i])
    bottom += counts_by_speed[i]

ax.set_thetagrids(dir_centers, labels=wind_labels)
ax.set_title("Wind rose by speed range")
ax.legend(loc="upper left", bbox_to_anchor=(1.05, 1.0))
plt.tight_layout()
plt.savefig(out_dir / "07_wind_rose.png", dpi=200, bbox_inches="tight")
plt.close()

# -----------------------------
# 10. Joint probability density (all speed bins)
# -----------------------------
speed_bin_width = 2
speed_edges = np.arange(0, np.ceil(wind_speed.max()) + speed_bin_width, speed_bin_width)
dir_edges_deg = np.arange(-11.25, 360 + 22.5, 22.5)

counts, _, _ = np.histogram2d(
    wind_speed,
    wind_dire_q,
    bins=[speed_edges, dir_edges_deg]
)
counts_prob = counts / counts.sum()

fig = plt.figure(figsize=(12, 6))
plt.imshow(
    counts_prob,
    origin="lower",
    aspect="auto",
    extent=[0, 360, speed_edges[0], speed_edges[-1]]
)
plt.xticks(dir_centers, wind_labels)
plt.xlabel("Wind Direction")
plt.ylabel("Wind Speed (m/s)")
plt.title("Joint Probability Density (Wind Speed & Direction)")
plt.colorbar(label="Probability")
plt.tight_layout()
plt.savefig(out_dir / "08_jpd_all.png", dpi=200)
plt.close()

# -----------------------------
# 11. Joint probability density for 3 speed ranges
# -----------------------------
speed_edges_3 = np.array([3, 7, 11, 15])
speed_centers_3 = (speed_edges_3[:-1] + speed_edges_3[1:]) / 2
speed_labels_3 = ["3-7", "7-11", "11-15"]

counts3, _, _ = np.histogram2d(
    wind_speed,
    wind_dire_q,
    bins=[speed_edges_3, dir_edges_deg]
)
total_in_bins = counts3.sum()
probs3 = counts3 / total_in_bins if total_in_bins > 0 else counts3

fig = plt.figure(figsize=(12, 5))
plt.imshow(
    probs3,
    origin="lower",
    aspect="auto",
    extent=[0, 360, 0, len(speed_labels_3)]
)
plt.xticks(dir_centers, wind_labels)
plt.yticks(np.arange(len(speed_labels_3)) + 0.5, speed_labels_3)
plt.xlabel("Wind Direction")
plt.ylabel("Wind Speed Bin (m/s)")
plt.title("Joint Probability Density (3 speed bins)")
plt.colorbar(label="Probability")
plt.tight_layout()
plt.savefig(out_dir / "09_jpd_3bins.png", dpi=200)
plt.close()

# -----------------------------
# 12. Summary table export
# -----------------------------
summary_df = pd.DataFrame({
    "wind_direction": wind_labels,
    "occurrence_probability": occurrence,
    "mean_wind_speed_gt3": ws_mean,
})

summary_df.to_csv(out_dir / "summary_by_direction.csv", index=False)

print("Done.")
print(f"Input rows: {len(df)}")
print(f"Weibull fit: A={scale_A:.4f}, k={shape_k:.4f}")
print(f"Outputs saved to: {out_dir}")
