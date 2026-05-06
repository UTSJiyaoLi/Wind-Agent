from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from storage.conversation_store import ConversationStore
from rag import service as rag_service


def test_merge_session_messages_uses_stored_history(monkeypatch, tmp_path):
    store = ConversationStore(root_dir=str(tmp_path / "conversations"))
    store.record_turn(
        session_id="sid-ctx",
        user_message="上一轮问题",
        assistant_message="上一轮回答",
        mode="llm_direct",
    )
    monkeypatch.setattr(rag_service, "CHAT_SESSION_STORE", store)

    merged = rag_service._merge_session_messages(
        "sid-ctx",
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "继续说一下"},
        ],
    )

    assert merged[0]["role"] == "system"
    assert any(msg["content"] == "上一轮问题" for msg in merged)
    assert any(msg["content"] == "上一轮回答" for msg in merged)
    assert merged[-1]["content"] == "继续说一下"


def test_augment_query_with_memory_only_for_followups():
    memory = {"summary": "当前目标: 分析台风风险"}

    assert rag_service._augment_query_with_memory("继续说一下", memory).endswith("分析台风风险")
    assert rag_service._augment_query_with_memory("请解释 IEC 湍流模型", memory) == "请解释 IEC 湍流模型"
