from pathlib import Path
import sys
import json

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph.nodes import agent as agent_node


def test_graph_routing_typhoon_batch_goes_to_workflow(monkeypatch) -> None:
    def _fake_llm(*args, **kwargs) -> str:  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("llm not available")

    monkeypatch.setattr(agent_node, "_call_orchestrator_llm", _fake_llm)

    state = {
        "request_id": "r-workflow-1",
        "user_query": "请计算台风概率并生成地图，可视化SCS，lat=20.9, lon=112.2, R=100km",
        "session_id": "default",
        "file_paths": [],
        "warnings": [],
        "trace": [],
    }
    out = agent_node.domain_router(state)  # type: ignore[arg-type]
    out = agent_node.mode_router(out)
    out = agent_node.policy_gate(out)
    out = agent_node.flow_entry(out)
    assert out["route_to"] == "workflow_planner"
    assert out["rule_id"] == "R-102"
    assert out["intent"] == "workflow"


def test_graph_routing_low_confidence_goes_to_clarify(monkeypatch) -> None:
    def _fake_llm(*args, **kwargs) -> str:  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("llm not available")

    monkeypatch.setattr(agent_node, "_call_orchestrator_llm", _fake_llm)

    state = {
        "request_id": "r-clarify-1",
        "user_query": "?",
        "session_id": "default",
        "file_paths": [],
        "warnings": [],
        "trace": [],
    }
    out = agent_node.domain_router(state)  # type: ignore[arg-type]
    out = agent_node.mode_router(out)
    out = agent_node.policy_gate(out)
    out = agent_node.flow_entry(out)
    assert out["route_to"] == "clarify_node"
    assert out["rule_id"] == "R-001"


def test_graph_routing_missing_excel_goes_to_clarify(monkeypatch) -> None:
    def _fake_llm(state, messages, **kwargs) -> str:  # noqa: ANN001, ANN002, ANN003
        prompt = messages[0]["content"]
        if "business-domain router" in prompt:
            return '{"domain":"wind_analysis","confidence":0.92,"candidates":["wind_analysis","knowledge"]}'
        if "execution-mode router" in prompt:
            return '{"mode":"create","confidence":0.91}'
        raise RuntimeError("unexpected call")

    monkeypatch.setattr(agent_node, "_call_orchestrator_llm", _fake_llm)

    state = {
        "request_id": "r-missing-slot-1",
        "user_query": "请分析这个风资源数据",
        "session_id": "default",
        "file_paths": [],
        "warnings": [],
        "trace": [],
    }
    out = agent_node.domain_router(state)  # type: ignore[arg-type]
    out = agent_node.mode_router(out)
    out = agent_node.policy_gate(out)
    out = agent_node.flow_entry(out)
    assert out["route_to"] == "clarify_node"
    assert out["rule_id"] == "R-003"
    assert "excel_path" in out["missing_slots"]


def test_routing_policy_threshold_override(monkeypatch, tmp_path) -> None:
    def _fake_llm(*args, **kwargs) -> str:  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("llm not available")

    monkeypatch.setattr(agent_node, "_call_orchestrator_llm", _fake_llm)

    policy_path = tmp_path / "routing_policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "thresholds": {
                    "domain_confidence": 0.95,
                    "mode_confidence": 0.65,
                },
                "rules": [
                    {
                        "id": "R-001",
                        "match": "domain_confidence_below",
                        "route_to": "clarify_node",
                        "reason": "domain confidence too low by override",
                    },
                    {
                        "id": "R-101",
                        "match": "mode_is_query",
                        "route_to": "rag_executor",
                        "reason": "query mode",
                    },
                    {
                        "id": "R-999",
                        "match": "default",
                        "route_to": "clarify_node",
                        "reason": "fallback",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_ROUTING_POLICY_PATH", str(policy_path))

    state = {
        "request_id": "r-policy-override-1",
        "user_query": "你好",
        "session_id": "default",
        "file_paths": [],
        "warnings": [],
        "trace": [],
    }
    out = agent_node.domain_router(state)  # type: ignore[arg-type]
    out = agent_node.mode_router(out)
    out = agent_node.policy_gate(out)
    out = agent_node.flow_entry(out)
    assert out["route_to"] == "clarify_node"
    assert out["rule_id"] == "R-001"
