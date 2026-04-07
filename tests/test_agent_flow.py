"""Agent 流程的单元测试。"""

from pathlib import Path

import pandas as pd

from orchestration.langgraph_flow import run_wind_agent_flow


def test_run_wind_agent_flow_success(tmp_path: Path):
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=32, freq="h"),
            "windSpd": [float((i % 8) + 1) for i in range(32)],
            "windDire": [float((i * 45) % 360) for i in range(32)],
        }
    )
    excel_path = tmp_path / "wind_agent.xlsx"
    df.to_excel(excel_path, index=False)

    result = run_wind_agent_flow(f"请分析这个文件: {excel_path}")

    assert result["success"] is True
    assert result["analysis"] is not None
    assert result["analysis"]["success"] is True
    assert result["resolved_excel_path"] is not None
    assert len(result["trace"]) >= 3


def test_run_wind_agent_flow_missing_excel_path():
    result = run_wind_agent_flow("帮我分析风资源数据")
    assert result["success"] is True
    assert result["analysis"] is None
    assert "rag" in result["summary"].lower()
    assert any(step["step"] == "intent_router" for step in result["trace"])


def test_run_wind_agent_flow_general_chat_no_tool():
    result = run_wind_agent_flow("你好，你是做什么的？")
    assert result["success"] is True
    assert result["analysis"] is None
    assert "rag" in result["summary"].lower()
    assert any(step["step"] == "intent_router" for step in result["trace"])

