"""RAG 服务层路由与响应组装的单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

from rag.service import handle_chat_request


def _runtime() -> SimpleNamespace:
    args = SimpleNamespace(
        llm_model="demo-model",
        llm_temperature=0.2,
        llm_max_tokens=256,
        llm_base_url="http://127.0.0.1:9001",
        llm_api_key="EMPTY",
        llm_timeout_seconds=30,
        system_prompt="system",
    )
    return SimpleNamespace(args=args)


def test_handle_chat_request_llm_direct() -> None:
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
        runtime=_runtime(),
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
    assert payload["ok"] is True
    assert payload["mode"] == "llm_direct"
    assert payload["answer"] == "ok-direct"


def test_handle_chat_request_rag_retrieve_path() -> None:
    req = {
        "mode": "rag",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "query"}],
        "generation_config": {},
        "retrieval_config": {"top_k": 2},
    }
    contexts = [{"rank": 1, "doc_id": "d1", "chunk_id": "c1"}]

    status, payload = handle_chat_request(
        request_path="/api/retrieve",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=None,
        call_vllm_chat=lambda **_: "{\"mode\":\"wind_agent\",\"confidence\":0.98,\"reason\":\"analysis request\"}",
        retrieve_contexts=lambda *_: (contexts, contexts, {"final_size": 1}),
        build_citations_and_media=lambda *_: ([{"index": "CTX1"}], [{"index": "CTX1"}]),
        build_preview_images=lambda *_: [{"index": "CTX1"}],
        format_contexts_for_prompt=lambda *_: "",
        summarize_media_for_prompt=lambda *_: "",
        render_citation_index=lambda *_: "",
    )

    assert status == 200
    assert payload["mode"] == "rag"
    assert payload["answer"] == ""
    assert payload["contexts"] == contexts
    assert payload["retrieval_metrics"]["final_size"] == 1


def test_handle_chat_request_wind_agent_path() -> None:
    req = {
        "mode": "wind_agent",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "analyze this"}],
        "generation_config": {},
        "retrieval_config": {},
    }

    status, payload = handle_chat_request(
        request_path="/api/chat",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=lambda *_args, **_kwargs: {
            "summary": "agent-ok",
            "analysis": {"success": True},
            "trace": [{"step": "plan_request"}],
            "error": None,
            "success": True,
        },
        call_vllm_chat=lambda **_: "{\"mode\":\"wind_agent\",\"confidence\":0.98,\"reason\":\"analysis request\"}",
        retrieve_contexts=lambda *_: ([], [], {}),
        build_citations_and_media=lambda *_: ([], []),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "",
        summarize_media_for_prompt=lambda *_: "",
        render_citation_index=lambda *_: "",
    )

    assert status == 200
    assert payload["mode"] == "wind_agent"
    assert payload["answer"] == "agent-ok"
    assert payload["success"] is True


def test_handle_chat_request_auto_mode_routes_to_rag() -> None:
    req = {
        "mode": "auto",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "风能特征有哪些？"}],
        "generation_config": {},
        "retrieval_config": {},
    }

    status, payload = handle_chat_request(
        request_path="/api/chat",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=lambda *_args, **_kwargs: {"summary": "unused"},
        call_vllm_chat=lambda **_: "rag-answer",
        retrieve_contexts=lambda *_: ([{"rank": 1}], [{"rank": 1}], {"final_size": 1}),
        build_citations_and_media=lambda *_: ([{"index": "CTX1"}], [{"index": "CTX1"}]),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "ctx",
        summarize_media_for_prompt=lambda *_: "media",
        render_citation_index=lambda *_: "idx",
    )

    assert status == 200
    assert payload["mode"] == "rag"
    assert payload["answer"] == "rag-answer\n\n请按以下 CTX 映射核对出处：\nidx"


def test_handle_chat_request_auto_mode_routes_to_wind_agent() -> None:
    req = {
        "mode": "auto",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "请分析这个风速数据"}],
        "generation_config": {},
        "retrieval_config": {},
    }

    status, payload = handle_chat_request(
        request_path="/api/chat",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=lambda *_args, **_kwargs: {
            "summary": "auto-agent",
            "analysis": {"success": True},
            "trace": [],
            "error": None,
            "success": True,
        },
        call_vllm_chat=lambda **_: "{\"mode\":\"wind_agent\",\"confidence\":0.98,\"reason\":\"analysis request\"}",
        retrieve_contexts=lambda *_: ([], [], {}),
        build_citations_and_media=lambda *_: ([], []),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "",
        summarize_media_for_prompt=lambda *_: "",
        render_citation_index=lambda *_: "",
    )

    assert status == 200
    assert payload["mode"] == "wind_agent"
    assert payload["answer"] == "auto-agent"



