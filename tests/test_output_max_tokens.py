import types
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.service import _resolve_final_answer_max_tokens


def _runtime(llm_max_tokens: int = 768):
    return types.SimpleNamespace(args=types.SimpleNamespace(llm_max_tokens=llm_max_tokens))


def test_only_rag_and_llm_direct_are_upscaled(monkeypatch):
    monkeypatch.setenv("RAG_LONG_ANSWER_MAX_TOKENS", "4096")
    runtime = _runtime()

    assert _resolve_final_answer_max_tokens("rag", 512, runtime) == 4096
    assert _resolve_final_answer_max_tokens("llm_direct", 1024, runtime) == 4096
    assert _resolve_final_answer_max_tokens("wind_agent", 768, runtime) == 768
    assert _resolve_final_answer_max_tokens("typhoon_model", 900, runtime) == 900


def test_keep_user_value_when_higher_than_config(monkeypatch):
    monkeypatch.setenv("RAG_LONG_ANSWER_MAX_TOKENS", "2048")
    runtime = _runtime()
    assert _resolve_final_answer_max_tokens("rag", 3072, runtime) == 3072
