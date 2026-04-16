from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph.nodes import agent as agent_node


def test_intent_router_overrides_rag_for_typhoon_map_query(monkeypatch) -> None:
    def _fake_llm(*args, **kwargs) -> str:  # noqa: ANN001, ANN002, ANN003
        return '{"intent":"rag","confidence":0.99}'

    monkeypatch.setattr(agent_node, "_call_orchestrator_llm", _fake_llm)

    state = {
        "request_id": "t1",
        "user_query": "请计算该点台风概率并做地图可视化，使用SCS模型，坐标lat=20.9339, lon=112.202, R=100km。",
        "session_id": "default",
        "file_paths": [],
        "warnings": [],
        "trace": [],
    }
    out = agent_node.intent_router(state)  # type: ignore[arg-type]
    assert out["intent"] == "workflow"
    assert out["intent_confidence"] >= 0.7
