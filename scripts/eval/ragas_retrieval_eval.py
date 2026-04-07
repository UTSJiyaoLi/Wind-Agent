"""基于 RAGAS 的检索评测脚本。"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from FlagEmbedding import BGEM3FlagModel
from pymilvus import AnnSearchRequest, MilvusClient, RRFRanker
from ragas import EvaluationDataset, evaluate
from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import NonLLMContextPrecisionWithReference, NonLLMContextRecall

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
    parser = argparse.ArgumentParser(description="RAGAS retrieval eval (ID-based) for Milvus hybrid search.")
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--collection", default="winddata_bge_m3_bm25")
    parser.add_argument("--uri", default="http://127.0.0.1:19530")
    parser.add_argument("--model-path", default="/share/home/lijiyao/CCCC/Models/BAAI/bge-m3")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--evalset", default="ragas_evalset_weak.jsonl")
    parser.add_argument("--output", default="ragas_eval_result.json")
    parser.add_argument("--use-reranker", action="store_true")
    parser.add_argument("--reranker-model-path", default="/share/home/lijiyao/CCCC/Models/BAAI/bge-reranker-v2-m3")
    parser.add_argument("--reranker-batch-size", type=int, default=64)
    args = parser.parse_args()
    return apply_config_overrides(args, section="ragas_retrieval_eval")


def normalize_sparse_vector(lexical_weights: dict[str, Any]) -> dict[int, float]:
    sparse_vector: dict[int, float] = {}
    for key, value in lexical_weights.items():
        try:
            sparse_vector[int(key)] = float(value)
        except Exception:
            continue
    return sparse_vector


def build_hybrid_reqs(query: str, dense: list[float], sparse: dict[int, float], limit: int) -> list[AnnSearchRequest]:
    return [
        AnnSearchRequest(
            data=[dense],
            anns_field="dense_vector",
            param={"metric_type": "IP"},
            limit=limit,
        ),
        AnnSearchRequest(
            data=[sparse],
            anns_field="bge_sparse_vector",
            param={"metric_type": "IP"},
            limit=limit,
        ),
        AnnSearchRequest(
            data=[query],
            anns_field="bm25_sparse_vector",
            param={"metric_type": "BM25"},
            limit=limit,
        ),
    ]


def dedup_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def load_evalset(path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    if not records:
        raise ValueError(f"empty evalset: {path}")
    return records


def main() -> None:
    args = parse_args()
    evalset = load_evalset(args.evalset)
    client = MilvusClient(uri=args.uri)
    model = BGEM3FlagModel(args.model_path, use_fp16=args.device.startswith("cuda"), device=args.device)
    reranker = None
    if args.use_reranker:
        reranker = BGERerankerV2(
            model_path=args.reranker_model_path,
            device=args.device,
            batch_size=args.reranker_batch_size,
        )

    ragas_samples: list[SingleTurnSample] = []
    debug_rows: list[dict[str, Any]] = []

    for row in evalset:
        question = row["question"]
        reference_doc_ids = dedup_keep_order(row["reference_doc_ids"])

        emb = model.encode(
            [question],
            batch_size=1,
            max_length=512,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = np.asarray(emb["dense_vecs"][0], dtype=np.float32).tolist()
        sparse = normalize_sparse_vector(emb["lexical_weights"][0])

        hits = client.hybrid_search(
            collection_name=args.collection,
            reqs=build_hybrid_reqs(question, dense, sparse, args.top_k * 2),
            ranker=RRFRanker(),
            limit=args.top_k,
            output_fields=["doc_id", "chunk_id", "page_no", "id", "text"],
        )
        hit_list = hits[0] if hits else []
        if reranker is not None and hit_list:
            hit_list = reranker.rerank(question, hit_list, args.top_k)
        retrieved_doc_ids = dedup_keep_order([hit.get("entity", {}).get("doc_id", "") for hit in hit_list])

        ragas_samples.append(
            SingleTurnSample(
                user_input=question,
                retrieved_contexts=retrieved_doc_ids,
                reference_contexts=reference_doc_ids,
            )
        )

        ref_set = set(reference_doc_ids)
        ret_set = set(retrieved_doc_ids)
        hit_cnt = len(ref_set & ret_set)
        prec = hit_cnt / max(len(ret_set), 1)
        rec = hit_cnt / max(len(ref_set), 1)
        debug_rows.append(
            {
                "question": question,
                "reference_doc_ids": reference_doc_ids,
                "retrieved_doc_ids": retrieved_doc_ids,
                "manual_precision": prec,
                "manual_recall": rec,
            }
        )

    dataset = EvaluationDataset(samples=ragas_samples)
    ragas_result = evaluate(
        dataset=dataset,
        metrics=[NonLLMContextPrecisionWithReference(), NonLLMContextRecall()],
    )

    manual_precision = sum(x["manual_precision"] for x in debug_rows) / len(debug_rows)
    manual_recall = sum(x["manual_recall"] for x in debug_rows) / len(debug_rows)

    result_payload = {
        "collection": args.collection,
        "top_k": args.top_k,
        "evalset": args.evalset,
        "use_reranker": args.use_reranker,
        "ragas_summary": str(ragas_result),
        "manual_macro_precision": manual_precision,
        "manual_macro_recall": manual_recall,
        "details": debug_rows,
    }
    Path(args.output).write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("ragas_result", ragas_result)
    print("manual_macro_precision", round(manual_precision, 4))
    print("manual_macro_recall", round(manual_recall, 4))
    print("saved", args.output)


if __name__ == "__main__":
    main()

