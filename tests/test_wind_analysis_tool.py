from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.wind_analysis_tool import build_wind_analysis_tool


def test_wind_analysis_tool_generates_summary_and_charts(tmp_path: Path) -> None:
    excel_path = tmp_path / "sample.xlsx"
    df = pd.DataFrame(
        {
            "windDire": [0, 22.5, 45, 67.5, 90, 112.5, 135, 157.5, 180, 202.5, 225, 247.5, 270, 292.5, 315, 337.5],
            "windSpd": [4.2, 5.0, 6.1, 7.5, 8.2, 5.9, 4.8, 6.5, 7.1, 5.2, 4.7, 6.9, 7.4, 5.8, 4.9, 6.2],
        }
    )
    df.to_excel(excel_path, index=False)

    tool = build_wind_analysis_tool()
    raw = tool.invoke({"excel_path": str(excel_path)})
    out = json.loads(raw)

    assert out["success"] is True
    assert int(out["data"]["valid_rows"]) == len(df)
    charts = out["data"]["charts"]
    assert len(charts) >= 4
    for item in charts:
        assert Path(item["path"]).exists()
        assert str(item.get("data_url", "")).startswith("data:image/png;base64,")
