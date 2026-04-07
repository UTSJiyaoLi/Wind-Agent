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


def test_run_analysis_multiline_weather_excel_format(tmp_path: Path):
    rows = [
        ["meta", None, None, None, None],
        ["站点信息", "秋田", "秋田", "秋田", None],
        ["年月日", "平均風速(m/s)", "品質情報", "最多風向(16方位)", "品質情報"],
        [None, None, None, None, None],
        ["2014/12/24", "3.1", "8", "東南東", "8"],
        ["2014/12/25", "5.8", "8", "北", "8"],
        ["2014/12/26", "7.5", "8", "西北西", "8"],
    ]
    df = pd.DataFrame(rows)
    excel_path = tmp_path / "multiline_weather.xlsx"
    df.to_excel(excel_path, index=False, header=False)

    result = run_analysis(str(excel_path))

    assert result.success is True
    assert result.data is not None
    assert result.data.valid_rows >= 3
    assert "histogram_weibull" in result.charts

