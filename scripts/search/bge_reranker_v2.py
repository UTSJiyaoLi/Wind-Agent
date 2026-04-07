"""BGE Reranker 的推理封装，用于检索候选重排序。"""

from typing import Any

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

from FlagEmbedding import FlagReranker


class BGERerankerV2:
    def __init__(
        self,
        model_path: str,
        device: str = "cuda",
        batch_size: int = 64,
        max_length: int = 512,
        use_fp16: bool = True,
    ) -> None:
        self.reranker = FlagReranker(
            model_name_or_path=model_path,
            use_fp16=use_fp16 and device.startswith("cuda"),
            devices=device,
            batch_size=batch_size,
            max_length=max_length,
        )

    def rerank(self, query: str, hits: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        if not hits:
            return []

        pairs: list[list[str]] = []
        valid_idx: list[int] = []
        for i, hit in enumerate(hits):
            entity = hit.get("entity", {})
            text = entity.get("text", "") or ""
            if not text.strip():
                continue
            pairs.append([query, text])
            valid_idx.append(i)

        if not pairs:
            return hits[:top_k]

        scores = self.reranker.compute_score(pairs)
        if not isinstance(scores, list):
            scores = [float(scores)]

        rescored: list[dict[str, Any]] = []
        score_map = {idx: float(score) for idx, score in zip(valid_idx, scores)}
        for i, hit in enumerate(hits):
            item = dict(hit)
            item["rerank_score"] = score_map.get(i, float("-inf"))
            rescored.append(item)

        rescored.sort(key=lambda x: x.get("rerank_score", float("-inf")), reverse=True)
        return rescored[:top_k]

