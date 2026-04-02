import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import requests
import torch
try:
    from scripts.pipeline.script_config import apply_config_overrides
except Exception:
    def apply_config_overrides(args, section):
        return args



DEFAULT_JSONL_PATH = Path(r"C:\codex_coding\Data\embedding\winddata_en_all.jsonl")
DEFAULT_MODEL_PATH = Path(r"C:\codex_coding\Models\bge-m3")
DEFAULT_COLLECTION = "winddata_bge_m3_bm25"
DEFAULT_URI = "http://127.0.0.1:19530"
TEXT_MAX_LENGTH = 65535
PATH_MAX_LENGTH = 4096
ID_MAX_LENGTH = 128
LANG_MAX_LENGTH = 32
CONTENT_TYPE_MAX_LENGTH = 32
DENSE_DIM = 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest winddata JSONL into Milvus with lightweight metadata + external full metadata store.")
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--jsonl-path", default=str(DEFAULT_JSONL_PATH), help="Source JSONL with page_content + full metadata")
    parser.add_argument("--light-jsonl-path", default="", help="Output light JSONL for Milvus ingest")
    parser.add_argument("--full-metadata-jsonl-path", default="", help="Output full metadata JSONL")
    parser.add_argument("--full-metadata-idx-path", default="", help="Output full metadata offset index JSON")
    parser.add_argument("--skip-prepare", action="store_true", help="Skip split preparation and use existing light-jsonl-path")
    parser.add_argument("--prepare-only", action="store_true", help="Only prepare split artifacts, do not ingest")
    parser.add_argument("--force-rebuild-artifacts", action="store_true", help="Rebuild split artifacts even if they already exist")

    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION)
    parser.add_argument("--uri", default=DEFAULT_URI, help="Milvus REST endpoint, e.g. http://127.0.0.1:19530")
    parser.add_argument("--token", default="", help="Optional Milvus token, e.g. root:Milvus")
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--log-every", type=int, default=5)
    parser.add_argument("--drop-old", action="store_true")
    parser.add_argument("--metadata-scan-limit", type=int, default=2000, help="How many source rows to scan for metadata preview. <=0 means scan all.")
    args = parser.parse_args()
    return apply_config_overrides(args, section="ingest_winddata_milvus")


def iter_jsonl(jsonl_path: Path) -> Iterable[dict[str, Any]]:
    with jsonl_path.open("r", encoding="utf-8-sig") as file:
        for line_no, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at line {line_no}: {exc}") from exc


def batched(items: Iterable[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def count_jsonl_records(jsonl_path: Path) -> int:
    count = 0
    with jsonl_path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            if line.strip():
                count += 1
    return count


def preview_metadata_schema(jsonl_path: Path, scan_limit: int) -> dict[str, Any]:
    top_level_keys: set[str] = set()
    metadata_keys: set[str] = set()
    metadata_key_types: dict[str, set[str]] = {}
    scanned = 0

    for row in iter_jsonl(jsonl_path):
        scanned += 1
        for key in row.keys():
            top_level_keys.add(str(key))

        metadata = row.get("metadata")
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                key_name = str(key)
                metadata_keys.add(key_name)
                if key_name not in metadata_key_types:
                    metadata_key_types[key_name] = set()
                metadata_key_types[key_name].add(type(value).__name__)

        if scan_limit > 0 and scanned >= scan_limit:
            break

    return {
        "scanned_rows": scanned,
        "top_level_keys": sorted(top_level_keys),
        "metadata_keys": sorted(metadata_keys),
        "metadata_key_types": {k: sorted(v) for k, v in sorted(metadata_key_types.items(), key=lambda x: x[0])},
    }


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def safe_nullable_str(value: Any) -> Optional[str]:
    text = safe_str(value).strip()
    return text or None


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def normalize_sparse_vector(lexical_weights: dict[str, Any]) -> dict[int, float]:
    sparse_vector: dict[int, float] = {}
    for key, value in lexical_weights.items():
        try:
            term_id = int(key)
            weight = float(value)
        except Exception:
            continue
        if weight != 0.0:
            sparse_vector[term_id] = weight
    return sparse_vector


def resolve_device(requested_device: str) -> str:
    if requested_device.lower().startswith("cuda") and not torch.cuda.is_available():
        print("CUDA unavailable in current environment, falling back to cpu")
        return "cpu"
    return requested_device


def derive_default_paths(source_jsonl: Path, args: argparse.Namespace) -> tuple[Path, Path, Path]:
    base_dir = source_jsonl.parent
    light_path = Path(args.light_jsonl_path) if args.light_jsonl_path else base_dir / "milvus_ingest_light.jsonl"
    full_meta_path = Path(args.full_metadata_jsonl_path) if args.full_metadata_jsonl_path else base_dir / "full_metadata.jsonl"
    full_idx_path = Path(args.full_metadata_idx_path) if args.full_metadata_idx_path else base_dir / "full_metadata.idx.json"
    return light_path, full_meta_path, full_idx_path


def _count_from_metadata(metadata: dict[str, Any], explicit_key: str, fallback_keys: list[str]) -> int:
    explicit = safe_int(metadata.get(explicit_key), default=-1)
    if explicit >= 0:
        return explicit

    best = 0
    for key in fallback_keys:
        value = metadata.get(key)
        if isinstance(value, list):
            best = max(best, len(value))
        elif isinstance(value, dict):
            best = max(best, len(value))
    return best


def _fallback_chunk_id(doc_id: str, page_no: int, text: str, line_no: int) -> str:
    seed = f"{doc_id}|{page_no}|{line_no}|{text}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]
    return f"fallback_{digest}"


def build_light_record(source_row: dict[str, Any], line_no: int) -> dict[str, Any]:
    metadata = source_row.get("metadata") if isinstance(source_row.get("metadata"), dict) else {}
    text = safe_str(source_row.get("page_content"))

    doc_id = safe_str(metadata.get("doc_id"))
    page_no = safe_int(metadata.get("page_no"), default=safe_int(metadata.get("page"), default=0))
    chunk_id = safe_str(metadata.get("chunk_id") or metadata.get("unique_id"))
    if not chunk_id:
        chunk_id = _fallback_chunk_id(doc_id=doc_id or "unknown", page_no=page_no, text=text, line_no=line_no)

    table_count = _count_from_metadata(
        metadata,
        explicit_key="table_count",
        fallback_keys=["tables_info", "related_table_titles", "table_refs"],
    )
    image_count = _count_from_metadata(
        metadata,
        explicit_key="image_count",
        fallback_keys=["figures_info", "related_figure_titles", "image_refs"],
    )

    content_type = safe_str(metadata.get("content_type"), default="text")
    has_table = bool(table_count > 0 or content_type == "table")
    has_image = bool(image_count > 0 or content_type == "image")

    light_metadata = {
        "id": chunk_id,
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "parent_id": safe_nullable_str(metadata.get("parent_id")),
        "page_no": page_no,
        "lang": safe_str(metadata.get("lang")),
        "content_type": content_type,
        "has_table": has_table,
        "has_image": has_image,
        "table_count": table_count,
        "image_count": image_count,
    }
    return {
        "page_content": text,
        "metadata": light_metadata,
    }


def prepare_split_artifacts(
    source_jsonl_path: Path,
    light_jsonl_path: Path,
    full_metadata_jsonl_path: Path,
    full_metadata_idx_path: Path,
    force_rebuild: bool,
) -> dict[str, Any]:
    if (
        not force_rebuild
        and light_jsonl_path.exists()
        and full_metadata_jsonl_path.exists()
        and full_metadata_idx_path.exists()
    ):
        return {
            "skipped": True,
            "reason": "artifacts_already_exist",
            "light_jsonl_path": str(light_jsonl_path),
            "full_metadata_jsonl_path": str(full_metadata_jsonl_path),
            "full_metadata_idx_path": str(full_metadata_idx_path),
            "light_records": count_jsonl_records(light_jsonl_path),
        }

    light_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    full_metadata_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    full_metadata_idx_path.parent.mkdir(parents=True, exist_ok=True)

    offset_map: dict[str, int] = {}
    total_rows = 0

    with source_jsonl_path.open("r", encoding="utf-8-sig") as source, \
        light_jsonl_path.open("w", encoding="utf-8") as light_file, \
        full_metadata_jsonl_path.open("wb") as full_meta_file:

        for line_no, line in enumerate(source, start=1):
            line = line.strip()
            if not line:
                continue

            source_row = json.loads(line)
            light_row = build_light_record(source_row, line_no=line_no)
            light_metadata = light_row.get("metadata") if isinstance(light_row.get("metadata"), dict) else {}
            row_id = safe_str(light_metadata.get("id"))

            if row_id in offset_map:
                raise ValueError(f"Duplicate id detected while building artifacts: {row_id}")

            light_file.write(json.dumps(light_row, ensure_ascii=False) + "\n")

            full_obj = {
                "id": row_id,
                "metadata_full": source_row.get("metadata") if isinstance(source_row.get("metadata"), dict) else {},
            }
            offset = full_meta_file.tell()
            payload = (json.dumps(full_obj, ensure_ascii=False) + "\n").encode("utf-8")
            full_meta_file.write(payload)
            offset_map[row_id] = offset
            total_rows += 1

    with full_metadata_idx_path.open("w", encoding="utf-8") as idx_file:
        json.dump(offset_map, idx_file, ensure_ascii=False)

    return {
        "skipped": False,
        "light_jsonl_path": str(light_jsonl_path),
        "full_metadata_jsonl_path": str(full_metadata_jsonl_path),
        "full_metadata_idx_path": str(full_metadata_idx_path),
        "light_records": total_rows,
        "indexed_ids": len(offset_map),
    }


class MilvusRestClient:
    def __init__(self, uri: str, token: Optional[str] = None):
        self.base_url = uri.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"Content-Type": "application/json"})
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=300)
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 0:
            raise RuntimeError(f"Milvus API {path} failed: {body}")
        return body

    def list_collections(self) -> list[str]:
        body = self.post("/v2/vectordb/collections/list", {})
        return body.get("data") or []

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.list_collections()

    def drop_collection(self, collection_name: str) -> None:
        self.post("/v2/vectordb/collections/drop", {"collectionName": collection_name})

    def create_collection(self, payload: dict[str, Any]) -> None:
        self.post("/v2/vectordb/collections/create", payload)

    def insert(self, collection_name: str, data: list[dict[str, Any]]) -> dict[str, Any]:
        return self.post("/v2/vectordb/entities/insert", {"collectionName": collection_name, "data": data})

    def flush_collection(self, collection_name: str) -> None:
        self.post("/v2/vectordb/collections/flush", {"collectionName": collection_name})

    def load_collection(self, collection_name: str) -> None:
        self.post("/v2/vectordb/collections/load", {"collectionName": collection_name})


def build_collection_payload(collection_name: str) -> dict[str, Any]:
    return {
        "collectionName": collection_name,
        "schema": {
            "autoId": False,
            "enableDynamicField": False,
            "functions": [
                {
                    "name": "text_bm25_emb",
                    "type": "BM25",
                    "inputFieldNames": ["text"],
                    "outputFieldNames": ["bm25_sparse_vector"],
                    "params": {},
                }
            ],
            "fields": [
                {
                    "fieldName": "id",
                    "dataType": "VarChar",
                    "isPrimary": True,
                    "elementTypeParams": {"max_length": ID_MAX_LENGTH},
                },
                {
                    "fieldName": "doc_id",
                    "dataType": "VarChar",
                    "elementTypeParams": {"max_length": ID_MAX_LENGTH},
                },
                {
                    "fieldName": "chunk_id",
                    "dataType": "VarChar",
                    "elementTypeParams": {"max_length": ID_MAX_LENGTH},
                },
                {
                    "fieldName": "parent_id",
                    "dataType": "VarChar",
                    "nullable": True,
                    "elementTypeParams": {"max_length": ID_MAX_LENGTH},
                },
                {
                    "fieldName": "page_no",
                    "dataType": "Int64",
                },
                {
                    "fieldName": "lang",
                    "dataType": "VarChar",
                    "elementTypeParams": {"max_length": LANG_MAX_LENGTH},
                },
                {
                    "fieldName": "content_type",
                    "dataType": "VarChar",
                    "elementTypeParams": {"max_length": CONTENT_TYPE_MAX_LENGTH},
                },
                {
                    "fieldName": "has_table",
                    "dataType": "Bool",
                },
                {
                    "fieldName": "has_image",
                    "dataType": "Bool",
                },
                {
                    "fieldName": "table_count",
                    "dataType": "Int64",
                },
                {
                    "fieldName": "image_count",
                    "dataType": "Int64",
                },
                {
                    "fieldName": "text",
                    "dataType": "VarChar",
                    "elementTypeParams": {
                        "max_length": TEXT_MAX_LENGTH,
                        "enable_analyzer": True,
                        "enable_match": True,
                    },
                },
                {
                    "fieldName": "dense_vector",
                    "dataType": "FloatVector",
                    "elementTypeParams": {"dim": str(DENSE_DIM)},
                },
                {
                    "fieldName": "bge_sparse_vector",
                    "dataType": "SparseFloatVector",
                },
                {
                    "fieldName": "bm25_sparse_vector",
                    "dataType": "SparseFloatVector",
                },
            ],
        },
        "indexParams": [
            {
                "fieldName": "dense_vector",
                "indexName": "dense_vector_index",
                "metricType": "IP",
                "params": {"index_type": "AUTOINDEX"},
            },
            {
                "fieldName": "bge_sparse_vector",
                "indexName": "bge_sparse_vector_index",
                "metricType": "IP",
                "params": {
                    "index_type": "SPARSE_INVERTED_INDEX",
                    "inverted_index_algo": "DAAT_MAXSCORE",
                },
            },
            {
                "fieldName": "bm25_sparse_vector",
                "indexName": "bm25_sparse_vector_index",
                "metricType": "BM25",
                "params": {
                    "index_type": "SPARSE_INVERTED_INDEX",
                    "inverted_index_algo": "DAAT_MAXSCORE",
                },
            },
        ],
    }


def ensure_collection(client: MilvusRestClient, collection_name: str, drop_old: bool) -> None:
    if client.has_collection(collection_name):
        if not drop_old:
            raise ValueError(f"Collection `{collection_name}` already exists. Use --drop-old to recreate it.")
        client.drop_collection(collection_name)
    client.create_collection(build_collection_payload(collection_name))


def build_rows(batch: list[dict[str, Any]], embedding_model: Any, batch_size: int) -> list[dict[str, Any]]:
    texts = [safe_str(item.get("page_content")) for item in batch]
    embeddings = embedding_model.encode(
        texts,
        batch_size=batch_size,
        max_length=8192,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense_vecs = embeddings["dense_vecs"]
    lexical_weights = embeddings["lexical_weights"]

    rows: list[dict[str, Any]] = []
    for i, item in enumerate(batch):
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        row = {
            "id": safe_str(metadata.get("id")),
            "doc_id": safe_str(metadata.get("doc_id")),
            "chunk_id": safe_str(metadata.get("chunk_id")),
            "parent_id": safe_nullable_str(metadata.get("parent_id")),
            "page_no": safe_int(metadata.get("page_no")),
            "lang": safe_str(metadata.get("lang")),
            "content_type": safe_str(metadata.get("content_type"), default="text"),
            "has_table": bool(metadata.get("has_table")),
            "has_image": bool(metadata.get("has_image")),
            "table_count": safe_int(metadata.get("table_count")),
            "image_count": safe_int(metadata.get("image_count")),
            "text": texts[i],
            "dense_vector": np.asarray(dense_vecs[i], dtype=np.float32).tolist(),
            "bge_sparse_vector": normalize_sparse_vector(lexical_weights[i]),
        }
        rows.append(row)
    return rows


def main() -> None:
    args = parse_args()
    source_jsonl_path = Path(args.jsonl_path)
    if not source_jsonl_path.exists():
        raise FileNotFoundError(f"JSONL not found: {source_jsonl_path}")

    light_jsonl_path, full_metadata_jsonl_path, full_metadata_idx_path = derive_default_paths(source_jsonl_path, args)

    metadata_schema = preview_metadata_schema(source_jsonl_path, args.metadata_scan_limit)
    print("[0/5] Source metadata preview")
    print(json.dumps(metadata_schema, ensure_ascii=False, indent=2))

    if not args.skip_prepare:
        print("[1/5] Preparing split artifacts (light jsonl + full metadata + index)")
        prep_result = prepare_split_artifacts(
            source_jsonl_path=source_jsonl_path,
            light_jsonl_path=light_jsonl_path,
            full_metadata_jsonl_path=full_metadata_jsonl_path,
            full_metadata_idx_path=full_metadata_idx_path,
            force_rebuild=args.force_rebuild_artifacts,
        )
        print(json.dumps(prep_result, ensure_ascii=False, indent=2))
    else:
        print("[1/5] Skipping split preparation (--skip-prepare)")

    if args.prepare_only:
        print("prepare_only=true, exiting without ingest")
        return

    if not light_jsonl_path.exists():
        raise FileNotFoundError(f"Light JSONL not found: {light_jsonl_path}")

    resolved_device = resolve_device(args.device)
    token = args.token or None
    total_records = count_jsonl_records(light_jsonl_path)

    print(f"[2/5] Connecting to Milvus REST: {args.uri}")
    client = MilvusRestClient(uri=args.uri, token=token)

    from FlagEmbedding import BGEM3FlagModel

    print(f"[3/5] Loading BGE-M3 model: {args.model_path} ({resolved_device})")
    use_fp16 = resolved_device.lower().startswith("cuda")
    embedding_model = BGEM3FlagModel(args.model_path, use_fp16=use_fp16, device=resolved_device)

    print(f"[4/5] Preparing collection: {args.collection_name}")
    ensure_collection(client=client, collection_name=args.collection_name, drop_old=args.drop_old)

    total_rows = 0
    total_batches = 0
    started = time.time()
    print(f"[5/5] Ingesting light JSONL: {light_jsonl_path}")
    print(f"Total records: {total_records}")

    for batch in batched(iter_jsonl(light_jsonl_path), args.batch_size):
        rows = build_rows(batch, embedding_model, args.batch_size)
        result = client.insert(collection_name=args.collection_name, data=rows)
        total_rows += int(result.get("data", {}).get("insertCount", len(rows)))
        total_batches += 1
        if total_batches % args.log_every == 0:
            elapsed = time.time() - started
            rows_per_sec = total_rows / elapsed if elapsed > 0 else 0.0
            pct = (100.0 * total_rows / total_records) if total_records > 0 else 0.0
            remaining_rows = max(total_records - total_rows, 0)
            eta_sec = (remaining_rows / rows_per_sec) if rows_per_sec > 0 else -1.0
            eta_text = f"{eta_sec / 60:.1f}m" if eta_sec >= 0 else "unknown"
            print(
                f"Progress rows={total_rows}/{total_records} "
                f"({pct:.2f}%) batches={total_batches} "
                f"elapsed={elapsed:.1f}s rate={rows_per_sec:.2f} rows/s eta={eta_text}"
            )

    client.flush_collection(args.collection_name)
    client.load_collection(args.collection_name)
    elapsed = time.time() - started

    print(
        json.dumps(
            {
                "collection_name": args.collection_name,
                "source_jsonl_path": str(source_jsonl_path),
                "light_jsonl_path": str(light_jsonl_path),
                "full_metadata_jsonl_path": str(full_metadata_jsonl_path),
                "full_metadata_idx_path": str(full_metadata_idx_path),
                "inserted_rows": total_rows,
                "batches": total_batches,
                "elapsed_seconds": round(elapsed, 2),
                "uri": args.uri,
                "device": resolved_device,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
