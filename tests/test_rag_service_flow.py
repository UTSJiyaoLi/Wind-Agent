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
            "analysis": {"success": True, "charts": {"wind_rose": "/tmp/wind_rose.png"}},
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
    assert isinstance(payload.get("preview_images"), list)


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


def test_handle_chat_request_auto_mode_routes_to_llm_direct_for_general_query() -> None:
    req = {
        "mode": "auto",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "帮我写一段周报开头"}],
        "generation_config": {},
        "retrieval_config": {},
    }

    status, payload = handle_chat_request(
        request_path="/api/chat",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=lambda *_args, **_kwargs: {"summary": "unused"},
        call_vllm_chat=lambda **_: "direct-answer",
        retrieve_contexts=lambda *_: ([{"rank": 1}], [{"rank": 1}], {"final_size": 1}),
        build_citations_and_media=lambda *_: ([{"index": "CTX1"}], [{"index": "CTX1"}]),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "ctx",
        summarize_media_for_prompt=lambda *_: "media",
        render_citation_index=lambda *_: "idx",
    )

    assert status == 200
    assert payload["mode"] == "llm_direct"
    assert payload["answer"] == "direct-answer"


def test_agentic_retrieve_retries_when_low_scores() -> None:
    req = {
        "mode": "rag",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "风电尾流模型是什么"}],
        "generation_config": {},
        "retrieval_config": {"top_k": 2},
        "agentic": {"enabled": True, "max_retries": 2, "min_top_score": 0.9, "min_coverage": 0.9},
    }
    calls = {"n": 0}

    def _retrieve(*_args):
        calls["n"] += 1
        i = calls["n"]
        return (
            [{"rank": 1, "doc_id": f"d{i}", "chunk_id": f"c{i}", "score": 0.1, "text": "wake text"}],
            [{"rank": 1, "doc_id": f"d{i}", "chunk_id": f"c{i}", "score": 0.1, "text": "wake text"}],
            {
                "final_size": 1,
                "query_candidate_count": 1,
                "top_hit_score": 0.1,
                "score_gap": 0.0,
                "coverage_estimate": 0.1,
                "context_count": 1,
            },
        )

    status, payload = handle_chat_request(
        request_path="/api/retrieve",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=None,
        call_vllm_chat=lambda **_: "unused",
        retrieve_contexts=_retrieve,
        build_citations_and_media=lambda *_: ([{"index": "CTX1"}], [{"index": "CTX1"}]),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "",
        summarize_media_for_prompt=lambda *_: "",
        render_citation_index=lambda *_: "",
    )

    assert status == 200
    assert calls["n"] == 3
    assert payload["mode"] == "rag"
    assert len(payload.get("agentic_actions", [])) == 2
    assert any(x.get("type") == "retry_retrieve" for x in payload.get("agentic_trace", []))


def test_agentic_retrieve_no_retry_when_good_scores() -> None:
    req = {
        "mode": "rag",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "风电尾流模型是什么"}],
        "generation_config": {},
        "retrieval_config": {"top_k": 2},
        "agentic": {"enabled": True, "max_retries": 2, "min_top_score": 0.5, "min_coverage": 0.5},
    }
    calls = {"n": 0}

    def _retrieve(*_args):
        calls["n"] += 1
        return (
            [{"rank": 1, "doc_id": "d1", "chunk_id": "c1", "score": 0.9, "text": "wake text"}],
            [{"rank": 1, "doc_id": "d1", "chunk_id": "c1", "score": 0.9, "text": "wake text"}],
            {
                "final_size": 1,
                "query_candidate_count": 2,
                "top_hit_score": 0.95,
                "score_gap": 0.2,
                "coverage_estimate": 0.9,
                "context_count": 1,
            },
        )

    status, payload = handle_chat_request(
        request_path="/api/retrieve",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=None,
        call_vllm_chat=lambda **_: "unused",
        retrieve_contexts=_retrieve,
        build_citations_and_media=lambda *_: ([{"index": "CTX1"}], [{"index": "CTX1"}]),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "",
        summarize_media_for_prompt=lambda *_: "",
        render_citation_index=lambda *_: "",
    )

    assert status == 200
    assert calls["n"] == 1
    assert payload.get("agentic_actions", []) == []


def test_agentic_decomposition_for_compound_query() -> None:
    req = {
        "mode": "rag",
        "provider": "vllm",
        "messages": [{"role": "user", "content": "请分别分析风速分布以及尾流影响，并给出建议"}],
        "generation_config": {},
        "retrieval_config": {"top_k": 2},
        "agentic": {"enabled": True, "decompose_enabled": True, "max_subquestions": 3},
    }

    def _retrieve(*_args):
        return (
            [{"rank": 1, "doc_id": "d1", "chunk_id": "c1", "score": 0.9, "text": "wake text"}],
            [{"rank": 1, "doc_id": "d1", "chunk_id": "c1", "score": 0.9, "text": "wake text"}],
            {
                "final_size": 1,
                "query_candidate_count": 2,
                "top_hit_score": 0.95,
                "score_gap": 0.2,
                "coverage_estimate": 0.9,
                "context_count": 1,
            },
        )

    status, payload = handle_chat_request(
        request_path="/api/chat",
        req=req,
        runtime=_runtime(),
        run_wind_agent_flow=None,
        call_vllm_chat=lambda **_: "sub-answer [CTX1]",
        retrieve_contexts=_retrieve,
        build_citations_and_media=lambda *_: ([{"index": "CTX1"}], [{"index": "CTX1"}]),
        build_preview_images=lambda *_: [],
        format_contexts_for_prompt=lambda *_: "ctx",
        summarize_media_for_prompt=lambda *_: "media",
        render_citation_index=lambda *_: "idx",
    )

    assert status == 200
    assert payload["mode"] == "rag"
    assert payload.get("decomposition", {}).get("triggered") is True
    assert len(payload.get("decomposition", {}).get("subquestions", [])) >= 2



