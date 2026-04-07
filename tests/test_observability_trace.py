from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from observability.tracer import JsonlTracer
from rag.service import handle_chat_request


def _runtime_with_tracer(trace_dir: Path) -> SimpleNamespace:
    args = SimpleNamespace(
        llm_model="demo-model",
        llm_temperature=0.2,
        llm_max_tokens=128,
        llm_base_url="http://127.0.0.1:9001",
        llm_api_key="EMPTY",
        llm_timeout_seconds=30,
        system_prompt="system",
    )
    return SimpleNamespace(args=args, tracer=JsonlTracer(enabled=True, trace_dir=str(trace_dir)))


def test_jsonl_trace_created_and_context_redacted(tmp_path: Path) -> None:
    runtime = _runtime_with_tracer(tmp_path / "traces")
    req = {
        "mode": "rag",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "解释风电尾流模型"}],
        "generation_config": {},
        "retrieval_config": {},
    }
    contexts = [
        {
            "rank": 1,
            "doc_id": "doc-1",
            "chunk_id": "chunk-1",
            "score": 0.91,
            "file_name": "a.pdf",
            "page_no": 3,
            "text": "SECRET_FULL_TEXT_SHOULD_NOT_APPEAR_IN_TRACE",
        }
    ]

    status, payload = handle_chat_request(
        request_path="/api/chat",
        req=req,
        runtime=runtime,
        run_wind_agent_flow=lambda *_args, **_kwargs: {"summary": "unused"},
        call_vllm_chat=lambda **_: "rag-answer",
        retrieve_contexts=lambda *_: (contexts, contexts, {"final_size": 1}),
        build_citations_and_media=lambda *_: ([{"index": "CTX1"}], [{"index": "CTX1"}]),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "ctx",
        summarize_media_for_prompt=lambda *_: "media",
        render_citation_index=lambda *_: "idx",
    )

    assert status == 200
    assert payload["mode"] == "rag"
    assert payload.get("request_id")

    files = list((tmp_path / "traces").glob("trace_*.jsonl"))
    assert files, "trace file should be created"
    raw = files[0].read_text(encoding="utf-8")
    assert "retrieved_contexts_summary" in raw
    assert "SECRET_FULL_TEXT_SHOULD_NOT_APPEAR_IN_TRACE" not in raw

    lines = [json.loads(line) for line in raw.splitlines() if line.strip()]
    span_names = {line.get("span") for line in lines if line.get("record_type") == "span"}
    assert "request" in span_names
    assert "retrieve" in span_names


def test_tracing_disabled_has_no_side_effects(tmp_path: Path) -> None:
    args = SimpleNamespace(
        llm_model="demo-model",
        llm_temperature=0.2,
        llm_max_tokens=128,
        llm_base_url="http://127.0.0.1:9001",
        llm_api_key="EMPTY",
        llm_timeout_seconds=30,
        system_prompt="system",
    )
    runtime = SimpleNamespace(args=args, tracer=JsonlTracer(enabled=False, trace_dir=str(tmp_path / "traces")))
    req = {
        "mode": "llm_direct",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "hello"}],
        "generation_config": {},
        "retrieval_config": {},
    }

    status, payload = handle_chat_request(
        request_path="/api/chat",
        req=req,
        runtime=runtime,
        run_wind_agent_flow=None,
        call_vllm_chat=lambda **_: "ok-direct",
        retrieve_contexts=lambda *_: ([], [], {}),
        build_citations_and_media=lambda *_: ([], []),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "",
        summarize_media_for_prompt=lambda *_: "",
        render_citation_index=lambda *_: "",
    )

    assert status == 200
    assert payload["mode"] == "llm_direct"
    assert payload["answer"] == "ok-direct"
    assert not list((tmp_path / "traces").glob("trace_*.jsonl"))
