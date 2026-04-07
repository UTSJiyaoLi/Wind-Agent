"""离线回归指标评估脚本。"""

import argparse
import json
from pathlib import Path
from typing import Any, Optional

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline retrieval regression: Recall/NDCG/MRR via /api/retrieve")
    parser.add_argument("--api-base", default="http://127.0.0.1:8787")
    parser.add_argument("--evalset", default="Data/eval/ragas_evalset_weak.jsonl")
    parser.add_argument("--output", default="Data/eval/offline_regression_report.json")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--model", default="/share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--collection", default="winddata_bge_m3_bm25")
    return parser.parse_args()


def load_evalset(path: str) -> list[dict[str, Any]]:
    p = Path(path)
    rows: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "question" in row and "reference_doc_ids" in row:
                rows.append(row)
    if not rows:
        raise ValueError(f"empty/invalid evalset: {path}")
    return rows


def dedup_keep_order(items: list[str], k: Optional[int] = None) -> list[str]:
    out: list[str] = []
    seen = set()
    for x in items:
        val = str(x or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
        if k is not None and len(out) >= k:
            break
    return out


def mrr_at_k(retrieved: list[str], refs: set[str]) -> float:
    for i, doc in enumerate(retrieved, start=1):
        if doc in refs:
            return 1.0 / float(i)
    return 0.0


def ndcg_at_k(retrieved: list[str], refs: set[str], k: int) -> float:
    import math

    dcg = 0.0
    for i, doc in enumerate(retrieved[:k], start=1):
        rel = 1.0 if doc in refs else 0.0
        dcg += rel / math.log2(i + 1.0)
    ideal_hits = min(len(refs), k)
    if ideal_hits <= 0:
        return 0.0
    idcg = 0.0
    for i in range(1, ideal_hits + 1):
        idcg += 1.0 / math.log2(i + 1.0)
    return dcg / idcg if idcg > 0 else 0.0


def avg(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def main() -> None:
    args = parse_args()
    evalset = load_evalset(args.evalset)
    url = args.api_base.rstrip("/") + "/api/retrieve"

    details: list[dict[str, Any]] = []
    all_recall: list[float] = []
    all_mrr: list[float] = []
    all_ndcg: list[float] = []

    session = requests.Session()
    for row in evalset:
        q = str(row["question"])
        refs = dedup_keep_order(list(row.get("reference_doc_ids", [])))
        ref_set = set(refs)

        payload = {
            "mode": "rag",
            "provider": "vllm",
            "model": args.model,
            "messages": [
                {"role": "system", "content": "retrieval only"},
                {"role": "user", "content": q},
            ],
            "generation_config": {"temperature": 0.0, "max_tokens": 32},
            "retrieval_config": {
                "top_k": args.top_k,
                "collection": args.collection,
                "rerank": bool(args.rerank),
            },
        }

        resp = session.post(url, json=payload, timeout=args.timeout_seconds)
        resp.raise_for_status()
        obj = resp.json()

        citations = obj.get("citations") or []
        retrieved_doc_ids = dedup_keep_order([str(c.get("doc_id") or "") for c in citations], k=args.top_k)

        hit = len(ref_set.intersection(set(retrieved_doc_ids)))
        recall = float(hit) / float(len(ref_set) or 1)
        mrr = mrr_at_k(retrieved_doc_ids, ref_set)
        ndcg = ndcg_at_k(retrieved_doc_ids, ref_set, args.top_k)

        all_recall.append(recall)
        all_mrr.append(mrr)
        all_ndcg.append(ndcg)

        details.append(
            {
                "question": q,
                "reference_doc_ids": refs,
                "retrieved_doc_ids": retrieved_doc_ids,
                "recall": recall,
                "mrr": mrr,
                "ndcg": ndcg,
                "retrieval_metrics": obj.get("retrieval_metrics", {}),
            }
        )

    report = {
        "api_base": args.api_base,
        "evalset": args.evalset,
        "top_k": args.top_k,
        "rerank": bool(args.rerank),
        "summary": {
            "macro_recall": avg(all_recall),
            "mrr": avg(all_mrr),
            "ndcg": avg(all_ndcg),
        },
        "details": details,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", str(out))
    print("summary", json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

