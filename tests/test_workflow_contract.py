from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph.workflow_contract import build_default_plan, normalize_workflow_plan


def test_normalize_workflow_plan_rewrites_steps() -> None:
    plan = normalize_workflow_plan(
        [
            {"type": "rag", "name": "knowledge"},
            {"type": "tool", "name": "analyze_wind_resource"},
            {"type": "llm", "goal": "summary"},
        ]
    )
    assert len(plan) == 3
    assert [x["step"] for x in plan] == [1, 2, 3]
    assert plan[1]["tool"] == "analyze_wind_resource"
    assert plan[2]["goal"] == "summary"


def test_normalize_workflow_plan_rejects_bad_type() -> None:
    try:
        normalize_workflow_plan([{"type": "custom"}])
    except ValueError as exc:
        assert "unsupported workflow step type" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported workflow step type")


def test_default_plan_for_tool_intent() -> None:
    plan = build_default_plan("tool")
    assert len(plan) == 1
    assert plan[0]["type"] == "tool"
    assert plan[0]["tool"] == "analyze_wind_resource"
