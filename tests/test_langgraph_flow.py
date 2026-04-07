"""LangGraph 流程的单元测试。"""

from pathlib import Path

import pandas as pd

from orchestration.langgraph_flow import run_wind_analysis_flow


def test_run_wind_analysis_flow_success(tmp_path: Path):
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=64, freq="h"),
            "windSpd": [float((i % 10) + 1) for i in range(64)],
            "windDire": [float((i * 22.5) % 360) for i in range(64)],
        }
    )
    excel_path = tmp_path / "wind.xlsx"
    df.to_excel(excel_path, index=False)

    result = run_wind_analysis_flow(str(excel_path))

    assert "summary" in result
    assert "analysis" in result
    assert result["analysis"]["success"] is True
    assert "charts" in result["analysis"]

