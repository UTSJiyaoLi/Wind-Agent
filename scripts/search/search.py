"""底层检索工具函数：Milvus 混合检索、候选融合、元数据装配等通用能力。"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np

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
from pymilvus import AnnSearchRequest, MilvusClient, RRFRanker

try:
    from scripts.pipeline.script_config import apply_config_overrides
except Exception:
    def apply_config_overrides(args, section):
        return args

try:
    from scripts.search.bge_reranker_v2 import BGERerankerV2
except Exception:
    from bge_reranker_v2 import BGERerankerV2


DEFAULT_COLLECTION = "winddata_bge_m3_bm25"
DEFAULT_URI = "http://127.0.0.1:19530"
DEFAULT_MODEL_PATH = "/share/home/lijiyao/CCCC/Models/BAAI/bge-m3"
DEFAULT_RERANKER_MODEL_PATH = "/share/home/lijiyao/CCCC/Models/BAAI/bge-reranker-v2-m3"
DEFAULT_QUERY = "wind turbine wake model and wind farm planning"
DEFAULT_FULL_METADATA_JSONL = "/share/home/lijiyao/CCCC/Data/embedding/full_metadata.jsonl"
DEFAULT_FULL_METADATA_IDX = "/share/home/lijiyao/CCCC/Data/embedding/full_metadata.idx.json"


class FullMetadataOffsetStore:
    def __init__(self, jsonl_path: str, idx_path: str):
        self.jsonl_path = Path(jsonl_path)
        self.idx_path = Path(idx_path)
        if not self.jsonl_path.exists():
            raise FileNotFoundError(f"Full metadata JSONL not found: {self.jsonl_path}")
        if not self.idx_path.exists():
            raise FileNotFoundError(f"Full metadata index not found: {self.idx_path}")

        with self.idx_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid metadata index file: {self.idx_path}")

        self.offset_map: dict[str, int] = {}
        for key, value in raw.items():
            try:
                self.offset_map[str(key)] = int(value)
            except Exception:
                continue

        self._fp = self.jsonl_path.open("rb")

    def get(self, row_id: str) -> Optional[dict[str, Any]]:
        offset = self.offset_map.get(row_id)
        if offset is None:
            return None
        self._fp.seek(offset)
        line = self._fp.readline()
        if not line:
            return None
        try:
            obj = json.loads(line.decode("utf-8"))
        except Exception:
            return None
        metadata_full = obj.get("metadata_full")
        if isinstance(metadata_full, dict):
            return metadata_full
        return None

    def get_many(self, row_ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row_id in row_ids:
            if not row_id or row_id in out:
                continue
            val = self.get(row_id)
            if val is not None:
                out[row_id] = val
        return out

    def close(self) -> None:
        try:
            self._fp.close()
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pipeline: dense+bge_sparse coarse -> bm25 branch -> branch merge -> doc top-m dedup "
            "-> reranker -> final top-k -> optional full metadata hydrate"
        )
    )
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--uri", default=DEFAULT_URI)
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--device", default="cuda")

    parser.add_argument("--coarse-k", type=int, default=60, help="Dense+BGE sparse coarse recall size")
    parser.add_argument("--bm25-k", type=int, default=60, help="BM25 branch recall size")
    parser.add_argument("--merge-k", type=int, default=80, help="Merged candidate pool size before dedup")

    parser.add_argument("--dedup-doc-k", type=int, default=20, help="Max number of docs after dedup")
    parser.add_argument("--doc-top-m", type=int, default=2, help="Max chunks to keep per doc before rerank")
    parser.add_argument("--max-rerank-candidates", type=int, default=40)
    parser.add_argument("--top-k", type=int, default=4, help="Final top-k for LLM")

    parser.add_argument("--merge-bge-weight", type=float, default=1.2)
    parser.add_argument("--merge-bm25-weight", type=float, default=1.0)
    parser.add_argument("--merge-rrf-k", type=int, default=60)

    parser.add_argument("--use-reranker", action="store_true")
    parser.add_argument("--reranker-model-path", default=DEFAULT_RERANKER_MODEL_PATH)
    parser.add_argument("--reranker-batch-size", type=int, default=64)

    parser.add_argument("--hydrate-full-metadata", action="store_true", help="Hydrate full metadata from external JSONL+index for final top-k chunks")
    parser.add_argument("--full-metadata-jsonl", default=DEFAULT_FULL_METADATA_JSONL)
    parser.add_argument("--full-metadata-idx", default=DEFAULT_FULL_METADATA_IDX)
    parser.add_argument("--include-full-metadata", action="store_true", help="Attach hydrated full metadata in output contexts")

    parser.add_argument("--llm-context-chars", type=int, default=500)
    parser.add_argument("--save-context-json", default="", help="Optional output path for LLM contexts")
    args = parser.parse_args()
    return apply_config_overrides(args, section="search")


def normalize_sparse_vector(lexical_weights: dict[str, Any]) -> dict[int, float]:
    sparse_vector: dict[int, float] = {}
    for key, value in lexical_weights.items():
        try:
            sparse_vector[int(key)] = float(value)
        except Exception:
            continue
    return sparse_vector


def safe_preview(text: str, n: int = 220) -> str:
    if text is None:
        return ""
    return str(text).replace("\n", " ")[:n]


def safe_doc_id(hit: dict[str, Any]) -> str:
    entity = hit.get("entity", {})
    doc_id = str(entity.get("doc_id", "")).strip()
    if doc_id:
        return doc_id
    return str(entity.get("id", "")).strip()


def safe_chunk_id(hit: dict[str, Any]) -> str:
    entity = hit.get("entity", {})
    chunk_id = str(entity.get("chunk_id", "")).strip()
    if chunk_id:
        return chunk_id
    return str(entity.get("id", "")).strip()


def build_dense_bge_requests(dense: list[float], sparse: dict[int, float], limit_each: int) -> list[AnnSearchRequest]:
    return [
        AnnSearchRequest(
            data=[dense],
            anns_field="dense_vector",
            param={"metric_type": "IP"},
            limit=limit_each,
        ),
        AnnSearchRequest(
            data=[sparse],
            anns_field="bge_sparse_vector",
            param={"metric_type": "IP"},
            limit=limit_each,
        ),
    ]


def run_hybrid_search(
    client: MilvusClient,
    collection: str,
    reqs: list[AnnSearchRequest],
    top_k: int,
) -> list[dict[str, Any]]:
    hits = client.hybrid_search(
        collection_name=collection,
        reqs=reqs,
        ranker=RRFRanker(),
        limit=top_k,
        output_fields=[
            "id",
            "doc_id",
            "chunk_id",
            "parent_id",
            "page_no",
            "lang",
            "content_type",
            "has_table",
            "has_image",
            "table_count",
            "image_count",
            "text",
        ],
    )
    return hits[0] if hits else []


def merge_two_branches(
    bge_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    bge_weight: float,
    bm25_weight: float,
    rrf_k: int,
    merge_k: int,
) -> list[dict[str, Any]]:
    scored: dict[str, dict[str, Any]] = {}

    def add_branch(hits: list[dict[str, Any]], weight: float, branch_name: str) -> None:
        for rank, hit in enumerate(hits, start=1):
            chunk_id = safe_chunk_id(hit)
            if not chunk_id:
                continue
            if chunk_id not in scored:
                item = dict(hit)
                item["merge_score"] = 0.0
                item["merge_sources"] = []
                scored[chunk_id] = item
            scored[chunk_id]["merge_score"] += float(weight) / float(rrf_k + rank)
            scored[chunk_id]["merge_sources"].append(branch_name)

    add_branch(bge_hits, bge_weight, "bge")
    add_branch(bm25_hits, bm25_weight, "bm25")

    merged = list(scored.values())
    merged.sort(key=lambda x: x.get("merge_score", 0.0), reverse=True)
    return merged[:merge_k]


def dedup_by_doc_keep_topm(hits: list[dict[str, Any]], keep_docs: int, per_doc_top_m: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    doc_count: dict[str, int] = defaultdict(int)
    selected_docs: set[str] = set()

    for hit in hits:
        doc_id = safe_doc_id(hit)
        if not doc_id:
            continue
        seen_doc = doc_id in selected_docs
        if not seen_doc and len(selected_docs) >= keep_docs:
            continue
        if doc_count[doc_id] >= per_doc_top_m:
            continue
        selected.append(hit)
        doc_count[doc_id] += 1
        selected_docs.add(doc_id)
    return selected


def build_llm_contexts(
    hits: list[dict[str, Any]],
    max_chars: int,
    hydrated_full: Optional[dict[str, dict[str, Any]]] = None,
    include_full_metadata: bool = False,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    hydrated_full = hydrated_full or {}

    for i, hit in enumerate(hits, start=1):
        entity = hit.get("entity", {})
        chunk_id = entity.get("chunk_id") or entity.get("id")
        row = {
            "rank": i,
            "id": entity.get("id"),
            "doc_id": entity.get("doc_id"),
            "chunk_id": chunk_id,
            "parent_id": entity.get("parent_id"),
            "page_no": entity.get("page_no"),
            "lang": entity.get("lang"),
            "content_type": entity.get("content_type"),
            "has_table": entity.get("has_table"),
            "has_image": entity.get("has_image"),
            "table_count": entity.get("table_count"),
            "image_count": entity.get("image_count"),
            "score": hit.get("distance"),
            "merge_score": hit.get("merge_score"),
            "rerank_score": hit.get("rerank_score"),
            "merge_sources": hit.get("merge_sources", []),
            "text": safe_preview(entity.get("text", ""), max_chars),
        }
        if include_full_metadata and chunk_id in hydrated_full:
            row["metadata_full"] = hydrated_full[chunk_id]
        contexts.append(row)
    return contexts


def main() -> None:
    args = parse_args()

    client = MilvusClient(uri=args.uri)
    print("collections", client.list_collections())
    print("stats", client.get_collection_stats(args.collection))

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
    print(f"stage_coarse_dense_bge size={len(bge_hits)}")

    bm25_req = AnnSearchRequest(
        data=[args.query],
        anns_field="bm25_sparse_vector",
        param={"metric_type": "BM25"},
        limit=max(args.bm25_k, args.merge_k),
    )
    bm25_hits = run_hybrid_search(client, args.collection, [bm25_req], args.bm25_k)
    print(f"stage_bm25 size={len(bm25_hits)}")

    merged_hits = merge_two_branches(
        bge_hits=bge_hits,
        bm25_hits=bm25_hits,
        bge_weight=args.merge_bge_weight,
        bm25_weight=args.merge_bm25_weight,
        rrf_k=args.merge_rrf_k,
        merge_k=args.merge_k,
    )
    print(f"stage_merge size={len(merged_hits)}")

    dedup_hits = dedup_by_doc_keep_topm(
        hits=merged_hits,
        keep_docs=args.dedup_doc_k,
        per_doc_top_m=max(1, args.doc_top_m),
    )
    print(f"stage_dedup docs<={args.dedup_doc_k} doc_top_m={args.doc_top_m} chunks={len(dedup_hits)}")

    rerank_candidates = dedup_hits[: max(1, args.max_rerank_candidates)]
    print(f"stage_rerank_candidates size={len(rerank_candidates)}")

    final_hits = rerank_candidates
    if args.use_reranker and rerank_candidates:
        reranker = BGERerankerV2(
            model_path=args.reranker_model_path,
            device=args.device,
            batch_size=args.reranker_batch_size,
        )
        final_hits = reranker.rerank(args.query, rerank_candidates, args.top_k)
        print("stage_rerank model=bge-reranker-v2")
    else:
        final_hits = final_hits[: args.top_k]

    hydrated_full: dict[str, dict[str, Any]] = {}
    hydrate_elapsed = 0.0
    if args.hydrate_full_metadata and final_hits:
        started = time.time()
        store = FullMetadataOffsetStore(args.full_metadata_jsonl, args.full_metadata_idx)
        try:
            final_ids = [safe_chunk_id(hit) for hit in final_hits]
            hydrated_full = store.get_many(final_ids)
        finally:
            store.close()
        hydrate_elapsed = time.time() - started
        print(f"stage_hydrate_full_metadata ids={len(final_hits)} hydrated={len(hydrated_full)} elapsed={hydrate_elapsed:.4f}s")

    llm_contexts = build_llm_contexts(
        final_hits,
        args.llm_context_chars,
        hydrated_full=hydrated_full,
        include_full_metadata=args.include_full_metadata,
    )

    payload = {
        "query": args.query,
        "pipeline": {
            "coarse_dense_bge_size": len(bge_hits),
            "bm25_size": len(bm25_hits),
            "merge_size": len(merged_hits),
            "dedup_size": len(dedup_hits),
            "rerank_candidate_size": len(rerank_candidates),
            "final_size": len(llm_contexts),
            "doc_top_m": args.doc_top_m,
            "use_reranker": args.use_reranker,
            "hydrate_full_metadata": args.hydrate_full_metadata,
            "hydrate_elapsed_seconds": round(hydrate_elapsed, 4),
        },
        "contexts": llm_contexts,
    }

    print("llm_ready_contexts")
    for row in llm_contexts:
        print(json.dumps(row, ensure_ascii=False))

    if args.save_context_json:
        with open(args.save_context_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"saved_context_json={args.save_context_json}")


if __name__ == "__main__":
    main()

