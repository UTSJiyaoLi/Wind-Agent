from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.conversation_store import ConversationStore


def test_conversation_store_records_slots_and_summary(tmp_path):
    store = ConversationStore(root_dir=str(tmp_path / "conversations"))

    memory = store.record_turn(
        session_id="sid-1",
        user_message="请继续刚才的台风分析，纬度 20.5，经度 110.2，半径 150km，用中文简洁回答。",
        assistant_message="已更新参数，继续分析。",
        mode="wind_agent",
        tool_input={"model_scope": "scs", "year_start": 1976, "year_end": 2025},
    )

    assert memory["last_mode"] == "wind_agent"
    assert memory["preferences"]["language"] == "zh-CN"
    assert memory["preferences"]["answer_style"] == "concise"
    assert memory["slots"]["lat"] == 20.5
    assert memory["slots"]["lon"] == 110.2
    assert memory["slots"]["radius_km"] == 150.0
    assert memory["slots"]["model_scope"] == "scs"
    assert "当前目标" in memory["summary"]


def test_conversation_store_returns_recent_messages(tmp_path):
    store = ConversationStore(root_dir=str(tmp_path / "conversations"))
    for idx in range(4):
        store.record_turn(
            session_id="sid-2",
            user_message=f"问题 {idx}",
            assistant_message=f"回答 {idx}",
            mode="llm_direct",
        )

    recent = store.get_recent_messages("sid-2", limit=3)
    assert len(recent) == 3
    assert recent[-1]["content"] == "回答 3"
