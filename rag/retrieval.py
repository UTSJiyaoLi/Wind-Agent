"""RAG 检索核心：查询改写、召回融合、重排、上下文编排与引用构建。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import requests
from pymilvus import AnnSearchRequest

try:
    from scripts.search.search import (
        FullMetadataOffsetStore,
        build_dense_bge_requests,
        build_llm_contexts,
        dedup_by_doc_keep_topm,
        merge_two_branches,
        normalize_sparse_vector,
        run_hybrid_search,
    )
except Exception:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "search"))
    from search import (  # type: ignore
        FullMetadataOffsetStore,
        build_dense_bge_requests,
        build_llm_contexts,
        dedup_by_doc_keep_topm,
        merge_two_branches,
        normalize_sparse_vector,
        run_hybrid_search,
    )

DOMAIN_EXPANSION_RULES: list[tuple[str, list[str]]] = [
    ("dwm", ["dynamic wake meandering", "wake model"]),
    ("wake model", ["jensen wake model", "gaussian wake model", "engineering wake model"]),
    ("wake", ["wake deficit", "wake recovery", "wake interaction"]),
    ("offshore", ["marine boundary layer", "atmospheric stability"]),
    ("turbulence", ["turbulence intensity", "TI"]),
    ("micro-siting", ["wind farm layout optimization", "turbine spacing"]),
    ("wind farm planning", ["micro-siting", "layout optimization", "turbine spacing"]),
    ("aep", ["annual energy production"]),
    ("yaw", ["wake steering", "yaw misalignment"]),
    ("scada", ["supervisory control and data acquisition", "operational data"]),
]


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
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(str(x.get("text", "")) for x in content if isinstance(x, dict) and x.get("type") == "text").strip()
    return str(content).strip()


def _norm_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _dedup_texts(rows: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in rows:
        t = " ".join(str(item or "").split())
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _heuristic_rewrite(query: str) -> list[str]:
    q = " ".join(str(query or "").split())
    low = q.lower()
    prefixes = [
        "explain ",
        "describe ",
        "tell me ",
        "what is ",
        "how does ",
        "in doc_",
    ]
    stripped = q
    for p in prefixes:
        if low.startswith(p):
            stripped = q[len(p):].strip()
            break

    rewrites: list[str] = []
    if stripped and stripped.lower() != low:
        rewrites.append(stripped)
    if "fig." in low or "fig " in low:
        rewrites.append(f"{stripped} figure caption title")
    if "table" in low:
        rewrites.append(f"{stripped} table title")
    if "wake" in low and "model" in low:
        rewrites.append(f"{stripped} dynamic wake meandering DWM Jensen Gaussian")
    return _dedup_texts(rewrites)


def _llm_rewrite(query: str, runtime: Any) -> list[str]:
    if not runtime.args.llm_model:
        return []
    prompt = (
        "Rewrite the user query for technical retrieval in wind-energy documents. "
        "Output only one rewritten query line, no explanation."
    )
    try:
        text = call_vllm_chat(
            base_url=runtime.args.llm_base_url,
            api_key=runtime.args.llm_api_key,
            model=runtime.args.llm_model,
            messages=[
                {"role": "system", "content": "You are a retrieval query rewriting assistant."},
                {"role": "user", "content": f"{prompt}\n\nQuery: {query}"},
            ],
            temperature=0.0,
            max_tokens=64,
            timeout_seconds=runtime.args.query_rewrite_llm_timeout,
        )
        row = text.splitlines()[0].strip() if text else ""
        return _dedup_texts([row])
    except Exception:
        return []


def _domain_expand(query: str, max_variants: int) -> list[str]:
    q_low = _norm_text(query)
    terms: list[str] = []
    for key, syns in DOMAIN_EXPANSION_RULES:
        if key in q_low:
            terms.extend(syns)
    terms = _dedup_texts(terms)
    out: list[str] = []
    for term in terms:
        out.append(f"{query} {term}")
        if len(out) >= max(0, max_variants):
            break
    return _dedup_texts(out)


def _build_query_candidates(runtime: Any, query: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [{"query": query, "source": "original", "weight": 1.0}]

    if runtime.args.enable_query_rewrite:
        rewrites: list[str] = []
        mode = runtime.args.query_rewrite_mode
        if mode in {"heuristic", "hybrid"}:
            rewrites.extend(_heuristic_rewrite(query))
        if mode in {"llm", "hybrid"}:
            rewrites.extend(_llm_rewrite(query, runtime))
        rewrites = _dedup_texts(rewrites)[: max(0, runtime.args.query_rewrite_max_variants)]
        rows.extend([{"query": r, "source": "rewrite", "weight": 0.95} for r in rewrites])

    if runtime.args.enable_domain_expansion:
        expanded = _domain_expand(query, runtime.args.domain_expansion_max_variants)
        rows.extend([{"query": e, "source": "domain_expansion", "weight": 0.85} for e in expanded])

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        q = _norm_text(row["query"])
        if not q or q in seen:
            continue
        seen.add(q)
        deduped.append(row)
    return deduped


def _safe_chunk_id(hit: dict[str, Any]) -> str:
    entity = hit.get("entity", {})
    return str(entity.get("chunk_id") or entity.get("id") or "").strip()


def _fuse_query_variant_hits(query_hits: list[dict[str, Any]], rrf_k: int, keep_k: int) -> list[dict[str, Any]]:
    scored: dict[str, dict[str, Any]] = {}
    for item in query_hits:
        hits = item.get("hits", [])
        weight = float(item.get("weight", 1.0))
        source = str(item.get("source", "q"))
        q_text = str(item.get("query", ""))
        for rank, hit in enumerate(hits, start=1):
            cid = _safe_chunk_id(hit)
            if not cid:
                continue
            if cid not in scored:
                row = dict(hit)
                row["multi_query_score"] = 0.0
                row["query_sources"] = []
                row["query_texts"] = []
                scored[cid] = row
            scored[cid]["multi_query_score"] += weight / float(rrf_k + rank)
            if source not in scored[cid]["query_sources"]:
                scored[cid]["query_sources"].append(source)
            if q_text and q_text not in scored[cid]["query_texts"]:
                scored[cid]["query_texts"].append(q_text)
    merged = list(scored.values())
    merged.sort(key=lambda x: x.get("multi_query_score", 0.0), reverse=True)
    return merged[:keep_k]


def _first_nonempty(source: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = source.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _basename_from_path(path_value: str) -> str:
    p = str(path_value or "").strip()
    if not p:
        return ""
    return os.path.basename(p.rstrip("/\\"))


def _extract_media_refs(metadata_full: dict[str, Any], context_row: dict[str, Any]) -> dict[str, Any]:
    table_fields = ["tables_info", "table_infos", "tables", "table_refs"]
    image_fields = ["images_info", "image_infos", "images", "image_refs", "figures_info", "visuals_info"]

    table_entries = []
    image_entries = []
    for key in table_fields:
        value = metadata_full.get(key)
        if isinstance(value, list):
            table_entries = value
            break
    for key in image_fields:
        value = metadata_full.get(key)
        if isinstance(value, list):
            image_entries = value
            break

    return {
        "content_type": context_row.get("content_type"),
        "has_table": bool(context_row.get("has_table")),
        "has_image": bool(context_row.get("has_image")),
        "table_count": int(context_row.get("table_count") or 0),
        "image_count": int(context_row.get("image_count") or 0),
        "tables_info": table_entries,
        "images_info": image_entries,
        "related_visuals": metadata_full.get("related_visuals", []),
        "related_table_titles": metadata_full.get("related_table_titles", []),
        "related_figure_titles": metadata_full.get("related_figure_titles", []),
    }


def build_citations_and_media(contexts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    citations: list[dict[str, Any]] = []
    media_refs: list[dict[str, Any]] = []
    for row in contexts:
        idx = f"CTX{row.get('rank')}"
        citation = {
            "index": idx,
            "rank": row.get("rank"),
            "doc_id": row.get("doc_id"),
            "chunk_id": row.get("chunk_id"),
            "page_no": row.get("page_no"),
            "file_name": row.get("file_name", ""),
            "source_path": row.get("source_path", ""),
            "source_address": row.get("source_address", ""),
            "score": row.get("score"),
        }
        citations.append(citation)

        media = dict(row.get("media_refs") or {})
        media["index"] = idx
        media["doc_id"] = row.get("doc_id")
        media["chunk_id"] = row.get("chunk_id")
        media_refs.append(media)
    return citations, media_refs


def build_preview_images(contexts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in contexts:
        idx = f"CTX{row.get('rank')}"
        media = row.get("media_refs") or {}
        candidates: list[dict[str, Any]] = []
        for key in ("images_info", "tables_info", "related_visuals"):
            value = media.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        candidates.append(item)
        for item in candidates:
            asset_path = str(item.get("asset_path") or "").strip()
            if not asset_path:
                continue
            title = str(item.get("title") or "").strip()
            kind = str(item.get("kind") or "image").strip().lower()
            rows.append(
                {
                    "index": idx,
                    "indices": [idx],
                    "kind": kind,
                    "title": title,
                    "page_no": row.get("page_no"),
                    "file_name": row.get("file_name"),
                    "asset_path": asset_path,
                    "asset_url": "/api/asset?path=" + quote(asset_path, safe=""),
                }
            )
    return rows


def render_citation_index(citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "Citation index: none"
    lines = ["Citation index:"]
    for c in citations:
        file_name = c.get("file_name") or _basename_from_path(c.get("source_path") or c.get("source_address") or "")
        source_addr = c.get("source_address") or c.get("source_path") or "-"
        lines.append(
            f"[{c.get('index')}] file={file_name or '-'} | "
            f"address={source_addr} | "
            f"page={c.get('page_no') or '-'} | chunk={c.get('chunk_id') or '-'}"
        )
    return "\n".join(lines)


def summarize_media_for_prompt(contexts: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in contexts:
        idx = f"CTX{row.get('rank')}"
        file_name = row.get("file_name") or "-"
        page_no = row.get("page_no") or "-"
        media = row.get("media_refs") or {}
        table_count = int(media.get("table_count") or 0)
        image_count = int(media.get("image_count") or 0)
        related_table_titles = media.get("related_table_titles") or []
        related_figure_titles = media.get("related_figure_titles") or []
        eq_info = (row.get("metadata_full") or {}).get("equations_info") or []
        has_formula = bool((row.get("metadata_full") or {}).get("has_formula"))

        t_title = related_table_titles[0] if isinstance(related_table_titles, list) and related_table_titles else "-"
        i_title = related_figure_titles[0] if isinstance(related_figure_titles, list) and related_figure_titles else "-"
        eq_hint = "yes" if (has_formula or (isinstance(eq_info, list) and len(eq_info) > 0)) else "no"
        lines.append(
            f"[{idx}] file={file_name} page={page_no} "
            f"tables={table_count} table_title={t_title} "
            f"images={image_count} image_title={i_title} "
            f"formula={eq_hint}"
        )
    return "\n".join(lines)


def _context_match_boost(row: dict[str, Any], query: str) -> int:
    q = (query or "").strip().lower()
    if not q:
        return 0
    score = 0
    meta = row.get("metadata_full") or {}
    titles = []
    for key in ("related_figure_titles", "related_table_titles"):
        value = meta.get(key)
        if isinstance(value, list):
            titles.extend([str(x).strip().lower() for x in value if str(x).strip()])
    text = str(row.get("text") or "").lower()
    for t in titles:
        if t and (t in q or q in t):
            score += 3
    if q.startswith("fig") and "fig" in text:
        score += 1
    return score


def _query_intent(query: str) -> str:
    q = (query or "").lower()
    visual_kw = ["fig", "figure", "image", "table", "chart", "plot", "diagram"]
    formula_kw = ["equation", "formula", "derive", "proof", "symbol"]
    if any(k in q for k in formula_kw):
        return "formula"
    if any(k in q for k in visual_kw):
        return "visual"
    return "general"


def _context_kind(row: dict[str, Any]) -> str:
    media = row.get("media_refs") or {}
    has_table = bool(media.get("table_count") or row.get("has_table"))
    has_image = bool(media.get("image_count") or row.get("has_image"))
    has_formula = bool((row.get("metadata_full") or {}).get("has_formula"))
    if has_formula:
        return "formula"
    if has_image or has_table:
        return "visual"
    return "text"


def _build_prompt_context_pack(
    contexts: list[dict[str, Any]], query: str, total_chars: int, min_items: int = 3
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    intent = _query_intent(query)
    total_chars = max(600, int(total_chars))

    if intent == "visual":
        alloc = {"visual": int(total_chars * 0.55), "formula": int(total_chars * 0.15), "text": int(total_chars * 0.30)}
    elif intent == "formula":
        alloc = {"visual": int(total_chars * 0.20), "formula": int(total_chars * 0.55), "text": int(total_chars * 0.25)}
    else:
        alloc = {"visual": int(total_chars * 0.30), "formula": int(total_chars * 0.20), "text": int(total_chars * 0.50)}

    selected: list[dict[str, Any]] = []
    used = {"visual": 0, "formula": 0, "text": 0}

    for row in contexts:
        kind = _context_kind(row)
        text = str(row.get("text") or "")
        if not text:
            continue
        cost = len(text)
        if used[kind] + cost <= alloc[kind]:
            selected.append(row)
            used[kind] += cost

    if len(selected) < min_items:
        for row in contexts:
            if row in selected:
                continue
            kind = _context_kind(row)
            used[kind] += len(str(row.get("text") or ""))
            selected.append(row)
            if len(selected) >= min_items:
                break

    selected = selected[: max(min_items, 8)]
    return selected, {
        "intent": intent,
        "total_chars_budget": total_chars,
        "allocation": alloc,
        "used_chars": used,
        "selected_count": len(selected),
        "selected_ranks": [r.get("rank") for r in selected],
    }


def retrieve_contexts(runtime: Any, query: str, retrieval_cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    args = runtime.args
    collection = str(retrieval_cfg.get("collection", args.collection)).strip() or args.collection
    coarse_k = int(retrieval_cfg.get("coarse_k", args.coarse_k))
    bm25_k = int(retrieval_cfg.get("bm25_k", args.bm25_k))
    merge_k = int(retrieval_cfg.get("merge_k", args.merge_k))
    dedup_doc_k = int(retrieval_cfg.get("dedup_doc_k", args.dedup_doc_k))
    doc_top_m = int(retrieval_cfg.get("doc_top_m", args.doc_top_m))
    top_k = int(retrieval_cfg.get("top_k", args.top_k))
    use_reranker = bool(retrieval_cfg.get("rerank", args.use_reranker))
    enable_rewrite = bool(retrieval_cfg.get("enable_query_rewrite", args.enable_query_rewrite))
    enable_expand = bool(retrieval_cfg.get("enable_domain_expansion", args.enable_domain_expansion))
    rewrite_max_variants = int(retrieval_cfg.get("query_rewrite_max_variants", args.query_rewrite_max_variants))
    expansion_max_variants = int(retrieval_cfg.get("domain_expansion_max_variants", args.domain_expansion_max_variants))
    enable_orchestration = bool(retrieval_cfg.get("enable_context_orchestration", args.enable_context_orchestration))

    model = runtime.get_embed_model()
    old_rewrite = args.enable_query_rewrite
    old_expand = args.enable_domain_expansion
    old_rw_n = args.query_rewrite_max_variants
    old_ex_n = args.domain_expansion_max_variants
    args.enable_query_rewrite = enable_rewrite
    args.enable_domain_expansion = enable_expand
    args.query_rewrite_max_variants = rewrite_max_variants
    args.domain_expansion_max_variants = expansion_max_variants
    query_candidates = _build_query_candidates(runtime, query)
    args.enable_query_rewrite = old_rewrite
    args.enable_domain_expansion = old_expand
    args.query_rewrite_max_variants = old_rw_n
    args.domain_expansion_max_variants = old_ex_n

    per_query_hits: list[dict[str, Any]] = []
    bge_hits_all: list[dict[str, Any]] = []
    bm25_hits_all: list[dict[str, Any]] = []

    for q_item in query_candidates:
        q_text = str(q_item["query"])
        emb = model.encode(
            [q_text],
            batch_size=1,
            max_length=512,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = np.asarray(emb["dense_vecs"][0], dtype=np.float32).tolist()
        sparse = normalize_sparse_vector(emb["lexical_weights"][0])
        dense_bge_reqs = build_dense_bge_requests(dense, sparse, limit_each=max(coarse_k, merge_k))
        bge_hits = run_hybrid_search(runtime.client, collection, dense_bge_reqs, coarse_k)
        bm25_req = AnnSearchRequest(
            data=[q_text],
            anns_field="bm25_sparse_vector",
            param={"metric_type": "BM25"},
            limit=max(bm25_k, merge_k),
        )
        bm25_hits = run_hybrid_search(runtime.client, collection, [bm25_req], bm25_k)

        merged_for_query = merge_two_branches(
            bge_hits=bge_hits,
            bm25_hits=bm25_hits,
            bge_weight=args.merge_bge_weight,
            bm25_weight=args.merge_bm25_weight,
            rrf_k=args.merge_rrf_k,
            merge_k=merge_k,
        )
        per_query_hits.append(
            {
                "query": q_text,
                "source": q_item.get("source", "q"),
                "weight": float(q_item.get("weight", 1.0)),
                "hits": merged_for_query,
            }
        )
        bge_hits_all.extend(bge_hits)
        bm25_hits_all.extend(bm25_hits)

    merged_hits = _fuse_query_variant_hits(per_query_hits, rrf_k=args.merge_rrf_k, keep_k=max(merge_k, top_k * 3))

    dedup_hits = dedup_by_doc_keep_topm(
        hits=merged_hits,
        keep_docs=dedup_doc_k,
        per_doc_top_m=max(1, doc_top_m),
    )
    rerank_candidates = dedup_hits[: max(1, args.max_rerank_candidates)]
    if use_reranker and rerank_candidates:
        final_hits = runtime.get_reranker().rerank(query, rerank_candidates, top_k)
    else:
        final_hits = rerank_candidates[:top_k]

    contexts = build_llm_contexts(final_hits, args.llm_context_chars)

    hydrated_full: dict[str, dict[str, Any]] = {}
    hydration_attempted = False
    hydration_hit = 0
    if args.hydrate_full_metadata and args.full_metadata_jsonl and args.full_metadata_idx and final_hits:
        hydration_attempted = True
        store = FullMetadataOffsetStore(args.full_metadata_jsonl, args.full_metadata_idx)
        try:
            ids = []
            for hit in final_hits:
                entity = hit.get("entity", {})
                cid = str(entity.get("chunk_id") or entity.get("id") or "").strip()
                if cid:
                    ids.append(cid)
                rid = str(entity.get("id") or "").strip()
                if rid and rid != cid:
                    ids.append(rid)
            hydrated_full = store.get_many(ids)
        finally:
            store.close()

    for i, row in enumerate(contexts):
        hit = final_hits[i] if i < len(final_hits) else {}
        entity = hit.get("entity", {}) if isinstance(hit, dict) else {}
        chunk_id = str(row.get("chunk_id") or entity.get("chunk_id") or entity.get("id") or "").strip()
        full = hydrated_full.get(chunk_id, {}) if chunk_id else {}
        if not full:
            alt_id = str(row.get("id") or entity.get("id") or "").strip()
            if alt_id:
                full = hydrated_full.get(alt_id, {})
        full = full if isinstance(full, dict) else {}
        if full:
            hydration_hit += 1

        file_name = _first_nonempty(full, ["source_file", "file_name", "filename", "pdf_name", "title"])
        source_path = _first_nonempty(full, ["source_path", "path", "file_path", "source"])
        source_address = _first_nonempty(full, ["url", "source_url", "address", "uri"])
        if not source_address:
            source_address = source_path

        if not file_name:
            file_name = _first_nonempty(entity, ["source_file", "file_name", "filename", "title"])
        if not source_path:
            source_path = _first_nonempty(entity, ["source_path", "path", "file_path", "source"])
        if not source_address:
            source_address = _first_nonempty(entity, ["url", "source_url", "address", "uri"]) or source_path
        if not file_name:
            file_name = _basename_from_path(source_path or source_address)

        row["file_name"] = file_name
        row["source_path"] = source_path
        row["source_address"] = source_address
        row["metadata_full"] = full
        row["media_refs"] = _extract_media_refs(full, row)

    contexts.sort(key=lambda r: (_context_match_boost(r, query), float(r.get("score") or 0.0)), reverse=True)
    for i, row in enumerate(contexts, start=1):
        row["rank"] = i

    prompt_contexts = contexts
    orchestration_info: dict[str, Any] = {"enabled": False}
    if enable_orchestration:
        prompt_contexts, orchestration_info = _build_prompt_context_pack(
            contexts=contexts,
            query=query,
            total_chars=args.llm_context_chars,
            min_items=args.context_min_items,
        )
        orchestration_info["enabled"] = True

    metrics = {
        "collection": collection,
        "query_candidates": query_candidates,
        "coarse_dense_bge_size": len(bge_hits_all),
        "bm25_size": len(bm25_hits_all),
        "merge_size": len(merged_hits),
        "dedup_size": len(dedup_hits),
        "final_size": len(contexts),
        "hydration_attempted": hydration_attempted,
        "hydrated_count": hydration_hit,
        "hydrated_rate": round(float(hydration_hit) / float(len(contexts) or 1), 4),
        "orchestration": orchestration_info,
    }
    return contexts, prompt_contexts, metrics

