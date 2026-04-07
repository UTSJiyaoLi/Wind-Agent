"""风资源分析服务与工具输出的单元测试。"""

from pathlib import Path

import pandas as pd

from services.wind_analysis_service import run_analysis


def test_run_analysis_success(tmp_path: Path):
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=100, freq="h"),
            "windSpd": [float((i % 12) + 1) for i in range(100)],
            "windDire": [float((i * 22.5) % 360) for i in range(100)],
        }
    )
    excel_path = tmp_path / "wind.xlsx"
    df.to_excel(excel_path, index=False)

    result = run_analysis(str(excel_path))

    assert result.success is True
    assert result.data is not None
    assert result.data.valid_rows == 100
    assert "wind_rose" in result.charts
    assert Path(result.charts["wind_rose"]).exists()
    assert Path(result.output_dir, "result.json").exists()


def test_run_analysis_missing_required_columns(tmp_path: Path):
    bad_df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=3, freq="D"),
            "windSpd": [3.2, 4.1, 5.0],
        }
    )
    bad_excel = tmp_path / "bad.xlsx"
    bad_df.to_excel(bad_excel, index=False)

    result = run_analysis(str(bad_excel))

    assert result.success is False
    assert result.data is None
    assert result.warnings
    assert "Missing required columns" in result.warnings[0]

