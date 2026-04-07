"""检索召回质量评估脚本。"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality across new pipeline stages.")
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--collection", default="winddata_bge_m3_bm25")
    parser.add_argument("--uri", default="http://127.0.0.1:19530")
    parser.add_argument("--model-path", default="/share/home/lijiyao/CCCC/Models/BAAI/bge-m3")
    parser.add_argument("--reranker-model-path", default="/share/home/lijiyao/CCCC/Models/BAAI/bge-reranker-v2-m3")
    parser.add_argument("--evalset", default="/share/home/lijiyao/CCCC/vector_embedding/ragas_evalset_weak.jsonl")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--use-reranker", action="store_true")

    parser.add_argument("--coarse-k", type=int, default=60)
    parser.add_argument("--bm25-k", type=int, default=60)
    parser.add_argument("--merge-k", type=int, default=120)
    parser.add_argument("--dedup-doc-k", type=int, default=20)
    parser.add_argument("--doc-top-m", type=int, default=3)
    parser.add_argument("--max-rerank-candidates", type=int, default=120)
    parser.add_argument("--final-k", type=int, default=8)

    parser.add_argument("--merge-bge-weight", type=float, default=1.0)
    parser.add_argument("--merge-bm25-weight", type=float, default=1.0)
    parser.add_argument("--merge-rrf-k", type=int, default=60)

    parser.add_argument("--output", default="/share/home/lijiyao/CCCC/vector_embedding/recall_quality_report.json")
    args = parser.parse_args()
    return apply_config_overrides(args, section="evaluate_recall_quality")


def normalize_sparse_vector(lexical_weights: dict[str, Any]) -> dict[int, float]:
    sparse_vector: dict[int, float] = {}
    for key, value in lexical_weights.items():
        try:
            sparse_vector[int(key)] = float(value)
        except Exception:
            continue
    return sparse_vector


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


def dedup_keep_order(items: list[str], keep_k: Optional[int] = None) -> list[str]:
    out: list[str] = []
    seen = set()
    for x in items:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
        if keep_k is not None and len(out) >= keep_k:
            break
    return out


def metrics_for_stage(retrieved: list[str], refs: list[str]) -> dict[str, float]:
    ref_set = set(refs)
    ret_set = set(retrieved)
    hit = len(ref_set & ret_set)
    recall = hit / max(len(ref_set), 1)
    precision = hit / max(len(retrieved), 1)
    mrr = 0.0
    for idx, doc_id in enumerate(retrieved, start=1):
        if doc_id in ref_set:
            mrr = 1.0 / idx
            break
    return {"recall": recall, "precision": precision, "mrr": mrr}


def load_evalset(path: str) -> list[dict[str, Any]]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if not records:
        raise ValueError(f"empty evalset: {path}")
    return records


def avg(rows: list[float]) -> float:
    return float(sum(rows) / len(rows)) if rows else 0.0


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
        output_fields=["doc_id", "text", "chunk_id", "page_no", "id"],
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


def main() -> None:
    args = parse_args()
    evalset = load_evalset(args.evalset)
    client = MilvusClient(uri=args.uri)
    model = BGEM3FlagModel(args.model_path, use_fp16=args.device.startswith("cuda"), device=args.device)
    reranker = None
    if args.use_reranker:
        reranker = BGERerankerV2(args.reranker_model_path, device=args.device)

    detail = []
    stage_scores: dict[str, dict[str, list[float]]] = {
        "coarse_bge": {"recall": [], "precision": [], "mrr": []},
        "bm25": {"recall": [], "precision": [], "mrr": []},
        "merged": {"recall": [], "precision": [], "mrr": []},
        "dedup": {"recall": [], "precision": [], "mrr": []},
        "final": {"recall": [], "precision": [], "mrr": []},
    }

    for row in evalset:
        q = row["question"]
        refs = dedup_keep_order(row["reference_doc_ids"])

        emb = model.encode(
            [q],
            batch_size=1,
            max_length=512,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = np.asarray(emb["dense_vecs"][0], dtype=np.float32).tolist()
        sparse = normalize_sparse_vector(emb["lexical_weights"][0])

        dense_bge_reqs = build_dense_bge_requests(dense, sparse, limit_each=max(args.coarse_k, args.merge_k))
        bge_hits = run_hybrid_search(client, args.collection, dense_bge_reqs, args.coarse_k)

        bm25_req = AnnSearchRequest(
            data=[q],
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
        final_hits = rerank_candidates[: args.final_k]
        if reranker is not None and rerank_candidates:
            final_hits = reranker.rerank(q, rerank_candidates, args.final_k)

        stages = {
            "coarse_bge": dedup_keep_order([safe_doc_id(h) for h in bge_hits]),
            "bm25": dedup_keep_order([safe_doc_id(h) for h in bm25_hits]),
            "merged": dedup_keep_order([safe_doc_id(h) for h in merged_hits]),
            "dedup": dedup_keep_order([safe_doc_id(h) for h in dedup_hits]),
            "final": dedup_keep_order([safe_doc_id(h) for h in final_hits], args.final_k),
        }
        row_score = {"question": q, "refs": refs}
        for stage, docs in stages.items():
            m = metrics_for_stage(docs, refs)
            row_score[stage] = {"docs": docs, **m}
            for k in ("recall", "precision", "mrr"):
                stage_scores[stage][k].append(m[k])
        detail.append(row_score)

    summary = {}
    for stage in ("coarse_bge", "bm25", "merged", "dedup", "final"):
        summary[stage] = {
            "macro_recall": avg(stage_scores[stage]["recall"]),
            "macro_precision": avg(stage_scores[stage]["precision"]),
            "mrr": avg(stage_scores[stage]["mrr"]),
        }

    payload = {
        "collection": args.collection,
        "use_reranker": args.use_reranker,
        "params": {
            "coarse_k": args.coarse_k,
            "bm25_k": args.bm25_k,
            "merge_k": args.merge_k,
            "dedup_doc_k": args.dedup_doc_k,
            "doc_top_m": args.doc_top_m,
            "max_rerank_candidates": args.max_rerank_candidates,
            "final_k": args.final_k,
            "merge_bge_weight": args.merge_bge_weight,
            "merge_bm25_weight": args.merge_bm25_weight,
            "merge_rrf_k": args.merge_rrf_k,
        },
        "summary": summary,
        "details": detail,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("saved", args.output)
    print("summary", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

