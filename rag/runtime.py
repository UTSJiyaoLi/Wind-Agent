"""RAG 运行时配置与资源初始化：命令行参数解析、Embedding 与 Reranker 实例管理。"""

from __future__ import annotations

import argparse
import os

from observability.tracer import build_tracer_from_args

# 兼容某些容器中 FlagEmbedding 与 transformers 的版本差异。
try:
    from transformers.models.gemma2 import modeling_gemma2 as _gemma2_modeling

    for _name in (
        "GEMMA2_START_DOCSTRING",
        "GEMMA2_INPUTS_DOCSTRING",
        "GEMMA2_RETURN_INTRODUCTION",
        "GEMMA2_GENERATION_EXAMPLE",
    ):
        if not hasattr(_gemma2_modeling, _name):
            setattr(_gemma2_modeling, _name, "")
except Exception:
    pass

from FlagEmbedding import BGEM3FlagModel
from pymilvus import MilvusClient

try:
    from scripts.search.bge_reranker_v2 import BGERerankerV2
except Exception:
    from bge_reranker_v2 import BGERerankerV2


def _strtobool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


class Runtime:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.client = MilvusClient(uri=args.uri)
        self.embed_model = None
        self.reranker = None
        self.tracer = build_tracer_from_args(args)

    def get_embed_model(self) -> BGEM3FlagModel:
        if self.embed_model is None:
            self.embed_model = BGEM3FlagModel(
                self.args.model_path,
                use_fp16=True,
                device=self.args.device,
            )
        return self.embed_model

    def get_reranker(self) -> BGERerankerV2:
        if self.reranker is None:
            self.reranker = BGERerankerV2(
                model_path=self.args.reranker_model_path,
                device=self.args.device,
                batch_size=self.args.reranker_batch_size,
            )
        return self.reranker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local RAG API for HTML frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)

    parser.add_argument("--uri", default=os.getenv("RAG_MILVUS_URI", "http://127.0.0.1:19530"))
    parser.add_argument("--collection", default=os.getenv("RAG_COLLECTION", "winddata_bge_m3_bm25"))
    parser.add_argument("--model-path", default=os.getenv("RAG_EMBED_MODEL_PATH", "C:/codex_coding/Models/bge-m3"))
    parser.add_argument("--device", default=os.getenv("RAG_DEVICE", "cuda"))

    parser.add_argument("--coarse-k", type=int, default=int(os.getenv("RAG_COARSE_K", "60")))
    parser.add_argument("--bm25-k", type=int, default=int(os.getenv("RAG_BM25_K", "60")))
    parser.add_argument("--merge-k", type=int, default=int(os.getenv("RAG_MERGE_K", "80")))
    parser.add_argument("--dedup-doc-k", type=int, default=int(os.getenv("RAG_DEDUP_DOC_K", "20")))
    parser.add_argument("--doc-top-m", type=int, default=int(os.getenv("RAG_DOC_TOP_M", "2")))
    parser.add_argument("--max-rerank-candidates", type=int, default=int(os.getenv("RAG_MAX_RERANK_CANDIDATES", "40")))
    parser.add_argument("--top-k", type=int, default=int(os.getenv("RAG_TOP_K", "4")))

    parser.add_argument("--merge-bge-weight", type=float, default=float(os.getenv("RAG_MERGE_BGE_WEIGHT", "1.2")))
    parser.add_argument("--merge-bm25-weight", type=float, default=float(os.getenv("RAG_MERGE_BM25_WEIGHT", "1.0")))
    parser.add_argument("--merge-rrf-k", type=int, default=int(os.getenv("RAG_MERGE_RRF_K", "60")))

    parser.add_argument("--use-reranker", action="store_true", default=_strtobool(os.getenv("RAG_USE_RERANKER", "false")))
    parser.add_argument("--reranker-model-path", default=os.getenv("RAG_RERANKER_MODEL_PATH", "C:/codex_coding/Models/BAAI/bge-reranker-v2-m3"))
    parser.add_argument("--reranker-batch-size", type=int, default=int(os.getenv("RAG_RERANKER_BATCH_SIZE", "64")))
    parser.add_argument("--hydrate-full-metadata", action="store_true", default=_strtobool(os.getenv("RAG_HYDRATE_FULL_METADATA", "false")))
    parser.add_argument("--full-metadata-jsonl", default=os.getenv("RAG_FULL_METADATA_JSONL", ""))
    parser.add_argument("--full-metadata-idx", default=os.getenv("RAG_FULL_METADATA_IDX", ""))

    parser.add_argument("--llm-base-url", default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:9001"))
    parser.add_argument("--llm-model", default=os.getenv("VLLM_MODEL", ""))
    parser.add_argument("--llm-api-key", default=os.getenv("VLLM_API_KEY", "EMPTY"))
    parser.add_argument("--llm-timeout-seconds", type=int, default=int(os.getenv("VLLM_TIMEOUT", "120")))
    parser.add_argument(
        "--orchestrator-base-url",
        default=os.getenv("ORCH_LLM_BASE_URL", os.getenv("VLLM_BASE_URL", "http://127.0.0.1:9001")),
    )
    parser.add_argument("--orchestrator-model", default=os.getenv("ORCH_LLM_MODEL", os.getenv("VLLM_MODEL", "")))
    parser.add_argument("--orchestrator-api-key", default=os.getenv("ORCH_LLM_API_KEY", os.getenv("VLLM_API_KEY", "EMPTY")))
    parser.add_argument("--orchestrator-timeout-seconds", type=int, default=int(os.getenv("ORCH_LLM_TIMEOUT", "60")))
    parser.add_argument("--llm-context-chars", type=int, default=int(os.getenv("RAG_LLM_CONTEXT_CHARS", "700")))
    parser.add_argument("--llm-temperature", type=float, default=float(os.getenv("RAG_LLM_TEMPERATURE", "0.2")))
    parser.add_argument("--llm-max-tokens", type=int, default=int(os.getenv("RAG_LLM_MAX_TOKENS", "768")))
    parser.add_argument("--enable-query-rewrite", action="store_true", default=_strtobool(os.getenv("RAG_ENABLE_QUERY_REWRITE", "true")))
    parser.add_argument("--query-rewrite-mode", default=os.getenv("RAG_QUERY_REWRITE_MODE", "heuristic"), choices=["heuristic", "llm", "hybrid"])
    parser.add_argument("--query-rewrite-max-variants", type=int, default=int(os.getenv("RAG_QUERY_REWRITE_MAX_VARIANTS", "1")))
    parser.add_argument("--query-rewrite-llm-timeout", type=int, default=int(os.getenv("RAG_QUERY_REWRITE_LLM_TIMEOUT", "20")))
    parser.add_argument("--enable-domain-expansion", action="store_true", default=_strtobool(os.getenv("RAG_ENABLE_DOMAIN_EXPANSION", "true")))
    parser.add_argument("--domain-expansion-max-variants", type=int, default=int(os.getenv("RAG_DOMAIN_EXPANSION_MAX_VARIANTS", "3")))
    parser.add_argument("--enable-context-orchestration", action="store_true", default=_strtobool(os.getenv("RAG_ENABLE_CONTEXT_ORCHESTRATION", "true")))
    parser.add_argument("--context-budget-strategy", default=os.getenv("RAG_CONTEXT_BUDGET_STRATEGY", "dynamic"), choices=["dynamic", "fixed"])
    parser.add_argument("--context-min-items", type=int, default=int(os.getenv("RAG_CONTEXT_MIN_ITEMS", "3")))
    parser.add_argument(
        "--system-prompt",
        default=os.getenv(
            "RAG_SYSTEM_PROMPT",
            "You are a rigorous assistant. Prioritize the provided context and explicitly state uncertainty when context is insufficient.",
        ),
    )
    parser.add_argument("--obs-enabled", type=_strtobool, default=_strtobool(os.getenv("OBS_ENABLED", "true")))
    parser.add_argument("--obs-backend", default=os.getenv("OBS_BACKEND", "jsonl"), choices=["jsonl", "langsmith", "none"])
    parser.add_argument("--obs-trace-dir", default=os.getenv("OBS_TRACE_DIR", "storage/traces"))
    parser.add_argument("--obs-redaction-mode", default=os.getenv("OBS_REDACTION_MODE", "summary_id"))
    parser.add_argument("--langsmith-endpoint", default=os.getenv("LANGSMITH_ENDPOINT", ""))
    parser.add_argument("--langsmith-project", default=os.getenv("LANGSMITH_PROJECT", "wind-agent-rag-eval"))
    parser.add_argument("--langsmith-api-key", default=os.getenv("LANGSMITH_API_KEY", ""))
    return parser.parse_args()


