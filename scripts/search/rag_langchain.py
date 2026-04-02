import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import requests
from FlagEmbedding import BGEM3FlagModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pymilvus import AnnSearchRequest, MilvusClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.search.bge_reranker_v2 import BGERerankerV2
from scripts.search.search import (
    FullMetadataOffsetStore,
    apply_config_overrides,
    build_dense_bge_requests,
    build_llm_contexts,
    dedup_by_doc_keep_topm,
    merge_two_branches,
    normalize_sparse_vector,
    run_hybrid_search,
    safe_chunk_id,
)

DEFAULT_SYSTEM_PROMPT = (
    "你是一个严谨的风电技术助手。请仅根据给定检索上下文回答。"
    "如果上下文不足，请明确说明不确定，并指出还缺什么信息。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangChain + Milvus + vLLM RAG")
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--collection", default="winddata_bge_m3_bm25")
    parser.add_argument("--uri", default="http://127.0.0.1:19530")
    parser.add_argument("--model-path", default="C:/codex_coding/Models/bge-m3")
    parser.add_argument("--query", required=True)
    parser.add_argument("--device", default="cuda")

    parser.add_argument("--coarse-k", type=int, default=60)
    parser.add_argument("--bm25-k", type=int, default=60)
    parser.add_argument("--merge-k", type=int, default=80)
    parser.add_argument("--dedup-doc-k", type=int, default=20)
    parser.add_argument("--doc-top-m", type=int, default=2)
    parser.add_argument("--max-rerank-candidates", type=int, default=40)
    parser.add_argument("--top-k", type=int, default=4)

    parser.add_argument("--merge-bge-weight", type=float, default=1.2)
    parser.add_argument("--merge-bm25-weight", type=float, default=1.0)
    parser.add_argument("--merge-rrf-k", type=int, default=60)

    parser.add_argument("--use-reranker", action="store_true")
    parser.add_argument("--reranker-model-path", default="C:/codex_coding/Models/BAAI/bge-reranker-v2-m3")
    parser.add_argument("--reranker-batch-size", type=int, default=64)

    parser.add_argument("--hydrate-full-metadata", action="store_true")
    parser.add_argument("--full-metadata-jsonl", default="")
    parser.add_argument("--full-metadata-idx", default="")
    parser.add_argument("--include-full-metadata", action="store_true")

    parser.add_argument("--llm-context-chars", type=int, default=700)
    parser.add_argument("--llm-base-url", default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--llm-model", default=os.getenv("VLLM_MODEL", ""))
    parser.add_argument("--llm-api-key", default=os.getenv("VLLM_API_KEY", "EMPTY"))
    parser.add_argument("--llm-timeout-seconds", type=int, default=120)
    parser.add_argument("--llm-temperature", type=float, default=0.2)
    parser.add_argument("--llm-max-tokens", type=int, default=768)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--save-answer-json", default="")
    parser.add_argument("--save-context-json", default="")

    args = parser.parse_args()
    return apply_config_overrides(args, section="search")


def format_contexts_for_prompt(contexts: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in contexts:
        blocks.append(
            "\n".join(
                [
                    f"[Context #{item.get('rank')}]",
                    f"doc_id: {item.get('doc_id')}",
                    f"chunk_id: {item.get('chunk_id')}",
                    f"score: {item.get('score')}",
                    f"text: {item.get('text')}",
                ]
            )
        )
    return "\n\n".join(blocks)


def call_vllm_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout_seconds: int,
) -> str:
    url = base_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"vLLM empty choices: {data}")

    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(str(part.get("text", "")))
        return "\n".join(t for t in texts if t).strip()

    return str(content).strip()


def retrieve_contexts(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    client = MilvusClient(uri=args.uri)
    model = BGEM3FlagModel(args.model_path, use_fp16=True, device=args.device)

    embeddings = model.encode(
        [args.query],
        batch_size=1,
        max_length=512,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )

    dense = np.asarray(embeddings["dense_vecs"][0], dtype=np.float32).tolist()
    sparse = normalize_sparse_vector(embeddings["lexical_weights"][0])

    dense_bge_reqs = build_dense_bge_requests(dense, sparse, limit_each=max(args.coarse_k, args.merge_k))
    bge_hits = run_hybrid_search(client, args.collection, dense_bge_reqs, args.coarse_k)

    bm25_req = AnnSearchRequest(
        data=[args.query],
        anns_field="bm25_sparse_vector",
        param={"metric_type": "BM25"},
        limit=max(args.bm25_k, args.merge_k),
    )
    bm25_hits = run_hybrid_search(client, args.collection, [bm25_req], args.bm25_k)

    merged_hits = merge_two_branches(
        bge_hits=bge_hits,
        bm25_hits=bm25_hits,
        bge_weight=args.merge_bge_weight,
        bm25_weight=args.merge_bm25_weight,
        rrf_k=args.merge_rrf_k,
        merge_k=args.merge_k,
    )

    dedup_hits = dedup_by_doc_keep_topm(
        hits=merged_hits,
        keep_docs=args.dedup_doc_k,
        per_doc_top_m=max(1, args.doc_top_m),
    )

    rerank_candidates = dedup_hits[: max(1, args.max_rerank_candidates)]

    final_hits = rerank_candidates
    if args.use_reranker and rerank_candidates:
        reranker = BGERerankerV2(
            model_path=args.reranker_model_path,
            device=args.device,
            batch_size=args.reranker_batch_size,
        )
        final_hits = reranker.rerank(args.query, rerank_candidates, args.top_k)
    else:
        final_hits = final_hits[: args.top_k]

    hydrated_full: dict[str, dict[str, Any]] = {}
    if args.hydrate_full_metadata and args.full_metadata_jsonl and args.full_metadata_idx and final_hits:
        store = FullMetadataOffsetStore(args.full_metadata_jsonl, args.full_metadata_idx)
        try:
            final_ids = [safe_chunk_id(hit) for hit in final_hits]
            hydrated_full = store.get_many(final_ids)
        finally:
            store.close()

    contexts = build_llm_contexts(
        final_hits,
        args.llm_context_chars,
        hydrated_full=hydrated_full,
        include_full_metadata=args.include_full_metadata,
    )

    metrics = {
        "coarse_dense_bge_size": len(bge_hits),
        "bm25_size": len(bm25_hits),
        "merge_size": len(merged_hits),
        "dedup_size": len(dedup_hits),
        "rerank_candidate_size": len(rerank_candidates),
        "final_size": len(contexts),
    }
    return contexts, metrics


def main() -> None:
    args = parse_args()

    if not args.llm_model:
        raise ValueError("Missing --llm-model (or set VLLM_MODEL)")

    started = time.time()
    contexts, retrieval_metrics = retrieve_contexts(args)

    context_blob = format_contexts_for_prompt(contexts)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}"),
            (
                "human",
                "用户问题:\n{question}\n\n检索上下文:\n{context}\n\n"
                "请你基于以上上下文回答，并在最后给出引用的 context 编号。",
            ),
        ]
    )

    def _invoke_vllm(prompt_value: Any) -> str:
        msgs = []
        for msg in prompt_value.to_messages():
            if msg.type == "ai":
                role = "assistant"
            elif msg.type == "human":
                role = "user"
            else:
                role = "system"
            msgs.append({"role": role, "content": str(msg.content)})
        return call_vllm_chat(
            base_url=args.llm_base_url,
            api_key=args.llm_api_key,
            model=args.llm_model,
            messages=msgs,
            temperature=args.llm_temperature,
            max_tokens=args.llm_max_tokens,
            timeout_seconds=args.llm_timeout_seconds,
        )

    chain = prompt | RunnableLambda(_invoke_vllm)
    answer = chain.invoke(
        {
            "system_prompt": args.system_prompt,
            "question": args.query,
            "context": context_blob,
        }
    )

    elapsed = time.time() - started
    print("\n=== RAG ANSWER ===")
    print(answer)
    print("\n=== RETRIEVAL METRICS ===")
    print(json.dumps(retrieval_metrics, ensure_ascii=False, indent=2))

    payload = {
        "query": args.query,
        "answer": answer,
        "retrieval_metrics": retrieval_metrics,
        "contexts": contexts,
        "llm": {
            "base_url": args.llm_base_url,
            "model": args.llm_model,
            "temperature": args.llm_temperature,
            "max_tokens": args.llm_max_tokens,
        },
        "elapsed_seconds": round(elapsed, 4),
    }

    if args.save_context_json:
        with open(args.save_context_json, "w", encoding="utf-8") as f:
            json.dump({"query": args.query, "contexts": contexts}, f, ensure_ascii=False, indent=2)
        print(f"saved_context_json={args.save_context_json}")

    if args.save_answer_json:
        with open(args.save_answer_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"saved_answer_json={args.save_answer_json}")


if __name__ == "__main__":
    main()
