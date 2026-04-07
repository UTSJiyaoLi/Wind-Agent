"""MinerU v2 解析核心实现与公共处理逻辑。"""

import copy
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Optional

import tiktoken
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


DATA_DIR = Path("/share/home/lijiyao/CCCC/Data")
DEFAULT_PDF_PATH = DATA_DIR / "wind_data" / "DOC_000224__en__doc.pdf"
DEFAULT_JSONL_PATH = DATA_DIR / "chunks_jsonl_mineru_v2_en_kb" / "DOC_000224__en__doc.jsonl"
DEFAULT_ASSET_DIR = DATA_DIR / "mineru_assets_parse_v2_en_kb"

PARENT_CHUNK_SIZE = 800
CHILD_CHUNK_SIZE = 250
CHILD_CHUNK_OVERLAP = 80
SEMANTIC_GROUP_SIZE = 15
MIN_PARENT_TOKENS = 80
MIN_PARENT_CHARS = 120
MIN_PARENT_SENTENCES = 2
MIN_CHILD_TOKENS = 40
MIN_CHILD_CHARS = 80
MIN_FILTER_PAGES = 0
MAX_FILTER_PAGES = 100000
MAX_VISUALS_PER_CHUNK = 4
MAX_EQUATIONS_PER_CHUNK = 4
NEAREST_BLOCK_DISTANCE = 4

try:
    ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    ENCODING = None
TEXT_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=CHILD_CHUNK_SIZE,
    chunk_overlap=CHILD_CHUNK_OVERLAP,
    separators=[
        "\n\n",
        "\n",
        "。",
        "！",
        "？",
        ". ",
        "! ",
        "? ",
        "；",
        "; ",
        "，",
        ", ",
        " ",
        "",
    ],
    length_function=lambda text: token_len(text or ""),
)

NOISE_FULL_PATTERNS = [
    r"^\s*\d+\s*$",
    r"^\s*page\s+\d+\s*$",
    r"^\s*springer[- ]verlag.*$",
    r"^\s*(?:doi|https?://|www\.)\S+\s*$",
    r"^\s*all rights reserved.*$",
    r"^\s*copyright .*",
]
NOISE_PARTIAL_PATTERNS = [
    r"springer[- ]verlag",
    r"available online",
    r"all rights reserved",
    r"https?://\S+",
    r"\bdoi\b\s*:?\s*\S+",
]
REFERENCE_HEADER_PATTERNS = [
    r"^references$",
    r"^bibliography$",
    r"^acknowledg(?:e)?ments?$",
]

def simple_doc_name(pdf_path: str | Path) -> str:
    stem = Path(pdf_path).stem
    match = re.match(r"^(DOC_\d+)", stem, flags=re.IGNORECASE)
    return match.group(1) if match else stem


def stable_id(*parts: Any) -> str:
    return hashlib.md5("||".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, set):
        return sorted(_to_json_safe(v) for v in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def sanitize_output_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    cleaned = _to_json_safe(copy.deepcopy(metadata)) if metadata else {}
    if "parser" not in cleaned:
        cleaned["parser"] = "mineru-gpu"
    return cleaned


def token_len(text: str) -> int:
    if ENCODING is None:
        return len((text or "").split())
    return len(ENCODING.encode(text or ""))


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sentence_split(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    sentences = re.split(r"(?<=[。！？!?；;\.])\s+|(?<=[。！？!?；;])|\n+", text)
    return [s.strip() for s in sentences if s.strip()]


def detect_lang(text: str) -> str:
    if not text:
        return "en"

    counts = Counter()
    for ch in text:
        code = ord(ch)
        if 0x3040 <= code <= 0x309F or 0x30A0 <= code <= 0x30FF:
            counts["ja"] += 3
        elif 0x4E00 <= code <= 0x9FFF:
            counts["cjk"] += 1
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            counts["en"] += 1

    if counts["ja"] > 0:
        return "ja"
    if counts["cjk"] > 0 and counts["en"] == 0:
        return "zh"
    if counts["cjk"] > counts["en"]:
        return "zh"
    return "en"


def default_semantic_chunk(text: str, group_size: int = SEMANTIC_GROUP_SIZE) -> list[str]:
    sentences = sentence_split(text)
    if not sentences:
        return []
    grouped = []
    for i in range(0, len(sentences), group_size):
        chunk = " ".join(sentences[i:i + group_size]).strip()
        if chunk:
            grouped.append(chunk)
    return grouped


def is_probable_author_line(text: str) -> bool:
    s = clean_text(text)
    if not s or len(s) > 180:
        return False
    if any(ch.isdigit() for ch in s):
        return False
    if len(re.findall(r"\b[A-Z][a-z]+\b", s)) >= 2 and s.count(",") + s.count(" and ") + s.count(";") >= 1:
        return True
    initials = re.findall(r"\b[A-Z]\.-?[A-Z]?\.\s*[A-Z][a-z]+\b", s)
    return len(initials) >= 2


def is_noise_line(text: str) -> bool:
    s = clean_text(text)
    if not s:
        return True
    s_low = s.lower()
    for pat in NOISE_FULL_PATTERNS:
        if re.fullmatch(pat, s_low):
            return True
    if is_probable_author_line(s):
        return True
    if len(s) < 40 and token_len(s) < 12:
        if not re.search(r"[。！？!?]", s) and s.count(" ") < 6:
            return True
    return False


def strip_partial_noise(text: str) -> str:
    s = clean_text(text)
    if not s:
        return ""
    for pat in NOISE_PARTIAL_PATTERNS:
        s = re.sub(pat, " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def truncate_before_references(lines: list[str]) -> list[str]:
    kept = []
    for line in lines:
        line_low = clean_text(line).lower()
        if any(re.fullmatch(p, line_low) for p in REFERENCE_HEADER_PATTERNS):
            break
        kept.append(line)
    return kept


def filter_page_lines(lines: list[str]) -> list[str]:
    lines = truncate_before_references(lines)
    kept = []
    for line in lines:
        line = strip_partial_noise(line)
        if not line or is_noise_line(line):
            continue
        kept.append(line)
    return kept


def is_valid_parent_text(text: str) -> bool:
    text = clean_text(text)
    if not text or is_noise_line(text):
        return False
    sent_cnt = len(sentence_split(text))
    return token_len(text) >= MIN_PARENT_TOKENS or len(text) >= MIN_PARENT_CHARS or sent_cnt >= MIN_PARENT_SENTENCES


def is_valid_child_text(text: str) -> bool:
    text = clean_text(text)
    if not text or is_noise_line(text):
        return False
    return token_len(text) >= MIN_CHILD_TOKENS or len(text) >= MIN_CHILD_CHARS


def _find_mineru_command() -> str:
    for name in ["mineru", "magic-pdf"]:
        binary = shutil.which(name)
        if binary:
            return binary
    raise RuntimeError("MinerU executable not found. Expected `mineru` or `magic-pdf` in PATH.")


def _run_mineru(
    pdf_path: str,
    output_dir: str,
    backend: str = "pipeline",
    method: str = "auto",
    start_page: int | None = None,
    end_page: int | None = None,
) -> Path:
    binary = _find_mineru_command()
    with tempfile.TemporaryDirectory(prefix="mineru_input_") as staged_dir:
        src_pdf = Path(pdf_path)
        staged_pdf = Path(staged_dir) / f"input{src_pdf.suffix.lower() or '.pdf'}"
        try:
            staged_pdf.symlink_to(src_pdf)
        except Exception:
            shutil.copy2(src_pdf, staged_pdf)

        cmd = [binary, "-p", str(staged_pdf), "-o", output_dir, "-b", backend, "-m", method, "-f", "true", "-t", "true"]
        if start_page is not None:
            cmd.extend(["-s", str(max(0, start_page - 1))])
        if end_page is not None:
            cmd.extend(["-e", str(max(0, end_page - 1))])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                "MinerU parse failed.\n"
                f"cmd: {' '.join(cmd)}\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )

    stem_candidates = {Path(pdf_path).stem, "input"}
    candidates: list[Path] = []
    for stem in stem_candidates:
        candidates.extend(Path(output_dir).rglob(f"{stem}_content_list.json"))
    if not candidates:
        candidates.extend(Path(output_dir).rglob("*_content_list.json"))
    if not candidates:
        candidates.extend(Path(output_dir).rglob("content_list.json"))
    if not candidates:
        raise RuntimeError(f"MinerU finished but no content list json found in {output_dir}")
    return sorted(candidates)[0]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(str(v)) for v in value if clean_text(str(v))]
    value = clean_text(str(value))
    return [value] if value else []


def _copy_asset(content_list_path: Path, rel_path: str | None, target_dir: Path) -> str | None:
    if not rel_path:
        return None
    src = content_list_path.parent / rel_path
    if not src.exists():
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    dst = target_dir / src.name
    if not dst.exists():
        shutil.copy2(src, dst)
    return str(dst)


def _extract_block_text(block: dict[str, Any]) -> str:
    block_type = block.get("type", "text")
    if block_type in {"text", "title"}:
        return clean_text(block.get("text") or block.get("content") or "")
    if block_type in {"equation", "interline_equation"}:
        latex = clean_text(block.get("latex") or "")
        text = clean_text(block.get("text") or block.get("content") or "")
        return latex or text
    if block_type == "table":
        parts = []
        parts.extend(_as_list(block.get("table_caption")))
        parts.extend(_as_list(block.get("table_body")))
        parts.extend(_as_list(block.get("table_footnote")))
        parts.extend(_as_list(block.get("html")))
        parts.extend(_as_list(block.get("text")))
        return clean_text("\n".join(parts))
    if block_type == "image":
        parts = []
        parts.extend(_as_list(block.get("image_caption")))
        parts.extend(_as_list(block.get("image_footnote")))
        parts.extend(_as_list(block.get("text")))
        return clean_text("\n".join(parts))
    return clean_text(block.get("text") or block.get("content") or "")


def _normalize_page_idx(block: dict[str, Any]) -> int | None:
    value = block.get("page_idx")
    if value is None:
        value = block.get("page_no")
        if value is not None:
            try:
                return int(value) - 1
            except Exception:
                return None
    try:
        return int(value)
    except Exception:
        return None


def _bbox_as_list(bbox: Any) -> list[float] | None:
    if not bbox or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    return [round(float(v), 2) for v in bbox]


def _first_non_empty(values: list[str]) -> str:
    for value in values:
        if clean_text(value):
            return clean_text(value)
    return ""


def _build_page_documents(
    pdf_path: str,
    content_list_path: Path,
    content_list: list[dict[str, Any]],
    asset_save_dir: Path,
    min_filter_pages: int,
    max_filter_pages: int,
    page_number_offset: int = 0,
) -> list[Document]:
    pdf_path = str(pdf_path)
    pdf_name = Path(pdf_path).name
    doc_id = Path(pdf_path).stem
    page_buffers: dict[int, dict[str, Any]] = defaultdict(
        lambda: {
            "blocks": [],
            "figures_info": [],
            "tables_info": [],
            "equations_info": [],
            "image_refs": [],
            "table_refs": [],
        }
    )

    for order_in_page, block in enumerate(content_list):
        page_idx = _normalize_page_idx(block)
        if page_idx is None or page_idx < min_filter_pages or page_idx > max_filter_pages:
            continue

        page_no = page_idx + 1 + page_number_offset
        state = page_buffers[page_no]
        block_type = str(block.get("type", "text") or "text")
        block_text = _extract_block_text(block)
        bbox = _bbox_as_list(block.get("bbox"))

        if block_type in {"text", "title", "equation", "interline_equation"} and block_text:
            state["blocks"].append(
                {
                    "type": block_type,
                    "text": block_text,
                    "bbox": bbox,
                    "order_on_page": len(state["blocks"]),
                }
            )

        if block_type == "image":
            captions = _as_list(block.get("image_caption"))
            footnotes = _as_list(block.get("image_footnote"))
            rel_path = block.get("img_path") or block.get("image_path") or block.get("path")
            copied = _copy_asset(content_list_path, rel_path, asset_save_dir / "images")
            title = _first_non_empty(captions + footnotes + _as_list(block.get("text")))
            record = {
                "kind": "figure",
                "page": page_no,
                "page_no": page_no,
                "title": title,
                "caption": captions,
                "footnote": footnotes,
                "bbox": bbox,
                "block_index": len(state["blocks"]),
                "source_rel_path": rel_path,
                "asset_path": copied,
                "order_on_page": len(state["figures_info"]) + len(state["tables_info"]) + 1,
            }
            state["figures_info"].append(record)
            if copied:
                state["image_refs"].append(copied)

        elif block_type == "table":
            captions = _as_list(block.get("table_caption"))
            footnotes = _as_list(block.get("table_footnote"))
            html = clean_text(block.get("table_body") or block.get("html") or block.get("text") or "")
            title = _first_non_empty(captions + footnotes)
            record = {
                "kind": "table",
                "page": page_no,
                "page_no": page_no,
                "title": title,
                "caption": captions,
                "footnote": footnotes,
                "bbox": bbox,
                "html": html,
                "block_index": len(state["blocks"]),
                "order_on_page": len(state["figures_info"]) + len(state["tables_info"]) + 1,
            }
            state["tables_info"].append(record)
            if html:
                state["table_refs"].append(html)

        elif block_type in {"equation", "interline_equation"}:
            latex = clean_text(block.get("latex") or "")
            text = clean_text(block.get("text") or block.get("content") or "")
            state["equations_info"].append(
                {
                    "kind": "equation",
                    "page": page_no,
                    "page_no": page_no,
                    "title": latex[:120] if latex else text[:120],
                    "formula_text": latex or text,
                    "formula_latex": latex,
                    "bbox": bbox,
                    "block_index": len(state["blocks"]) - 1 if state["blocks"] else 0,
                    "equation_type": block_type,
                    "order_on_page": len(state["equations_info"]) + 1,
                }
            )

    raw_docs: list[Document] = []
    lang_votes: list[str] = []

    for page_no in sorted(page_buffers.keys()):
        state = page_buffers[page_no]
        raw_lines = [b["text"] for b in state["blocks"] if b.get("text")]
        filtered_lines = filter_page_lines(raw_lines)
        page_text = clean_text("\n\n".join(filtered_lines))
        if not page_text:
            continue

        page_lang = detect_lang(page_text)
        lang_votes.append(page_lang)
        visuals_info = state["figures_info"] + state["tables_info"]
        visuals_info.sort(key=lambda x: (x.get("block_index", 0), x.get("order_on_page", 0)))

        metadata = {
            "unique_id": stable_id(doc_id, page_no, page_text),
            "doc_id": doc_id,
            "source": pdf_path,
            "source_file": pdf_name,
            "source_path": pdf_path,
            "page": page_no,
            "page_no": page_no,
            "lang": page_lang,
            "doc_lang": page_lang,
            "parser": "parse_mineru_v2",
            "content_type": "text",
            "chunk_level": "page",
            "token_count": token_len(page_text),
            "text_hash": stable_id(page_text),
            "block_count": len(state["blocks"]),
            "filtered_line_count": len(filtered_lines),
            "image_refs": state["image_refs"],
            "table_refs": state["table_refs"],
            "figures_info": state["figures_info"],
            "tables_info": state["tables_info"],
            "visuals_info": visuals_info,
            "equations_info": state["equations_info"],
            "has_formula": bool(state["equations_info"]),
        }
        raw_docs.append(Document(page_content=page_text, metadata=metadata))

    if raw_docs and lang_votes:
        doc_lang = Counter(lang_votes).most_common(1)[0][0]
        for doc in raw_docs:
            doc.metadata["doc_lang"] = doc_lang
            doc.metadata["lang"] = doc_lang
    return raw_docs


def load_pdf(
    pdf_path: str | Path = DEFAULT_PDF_PATH,
    asset_save_dir: str | Path = DEFAULT_ASSET_DIR,
    min_filter_pages: int = MIN_FILTER_PAGES,
    max_filter_pages: int = MAX_FILTER_PAGES,
    mineru_backend: str = "pipeline",
    mineru_method: str = "auto",
    start_page: int | None = None,
    max_pages: int | None = None,
) -> list[Document]:
    pdf_path = str(pdf_path)
    asset_save_dir = Path(asset_save_dir)
    asset_save_dir.mkdir(parents=True, exist_ok=True)

    mineru_end_page = None
    if start_page is not None and max_pages is not None:
        mineru_end_page = start_page + max_pages - 1

    with tempfile.TemporaryDirectory(prefix="mineru_parse_v2_") as tmp_dir:
        content_list_path = _run_mineru(
            pdf_path=pdf_path,
            output_dir=tmp_dir,
            backend=mineru_backend,
            method=mineru_method,
            start_page=start_page,
            end_page=mineru_end_page,
        )
        with content_list_path.open("r", encoding="utf-8") as f:
            content_list = json.load(f)
        if not isinstance(content_list, list):
            raise ValueError(f"Unexpected MinerU output format: {content_list_path}")
        return _build_page_documents(
            pdf_path=pdf_path,
            content_list_path=content_list_path,
            content_list=content_list,
            asset_save_dir=asset_save_dir,
            min_filter_pages=min_filter_pages,
            max_filter_pages=max_filter_pages,
            page_number_offset=max(0, (start_page or 1) - 1),
        )


def _pick_nearby_items(
    items: list[dict[str, Any]],
    limit: int,
    min_block_index: int,
    max_block_index: int,
) -> list[dict[str, Any]]:
    if not items:
        return []
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        block_index = int(item.get("block_index", 0))
        if min_block_index <= block_index <= max_block_index:
            distance = 0
        elif block_index < min_block_index:
            distance = min_block_index - block_index
        else:
            distance = block_index - max_block_index
        ranked.append((distance, item))
    ranked.sort(key=lambda x: (x[0], x[1].get("block_index", 0)))

    selected = []
    for distance, item in ranked:
        if distance > NEAREST_BLOCK_DISTANCE and selected:
            break
        selected.append(copy.deepcopy(item))
        if len(selected) >= limit:
            break
    return selected


def texts_split(
    raw_docs: list[Document],
    semantic_chunk_fn: Optional[Callable[[str, int], list[str]]] = None,
    semantic_group_size: int = SEMANTIC_GROUP_SIZE,
    parent_chunk_size: int = PARENT_CHUNK_SIZE,
    include_parents: bool = False,
) -> list[Document]:
    if semantic_chunk_fn is None:
        semantic_chunk_fn = default_semantic_chunk

    output_docs: list[Document] = []
    parent_docs: list[Document] = []

    for page_doc in raw_docs:
        grouped_chunks = semantic_chunk_fn(page_doc.page_content, semantic_group_size)
        if not grouped_chunks:
            grouped_chunks = [page_doc.page_content]

        page_uid = page_doc.metadata.get("unique_id") or stable_id(page_doc.page_content)
        merged_groups = []
        buffer = []
        buffer_tokens = 0
        for group in grouped_chunks:
            group = clean_text(group)
            if not group:
                continue
            group_tokens = token_len(group)
            if buffer and buffer_tokens + group_tokens > parent_chunk_size:
                merged_groups.append(clean_text(" ".join(buffer)))
                buffer = [group]
                buffer_tokens = group_tokens
            else:
                buffer.append(group)
                buffer_tokens += group_tokens
        if buffer:
            merged_groups.append(clean_text(" ".join(buffer)))

        for group_index, group_text in enumerate(merged_groups):
            group_text = clean_text(group_text)
            if not is_valid_parent_text(group_text):
                continue

            related_visuals = _pick_nearby_items(
                page_doc.metadata.get("visuals_info", []),
                limit=MAX_VISUALS_PER_CHUNK,
                min_block_index=group_index,
                max_block_index=group_index + semantic_group_size,
            )
            related_equations = _pick_nearby_items(
                page_doc.metadata.get("equations_info", []),
                limit=MAX_EQUATIONS_PER_CHUNK,
                min_block_index=group_index,
                max_block_index=group_index + semantic_group_size,
            )

            parent_metadata = copy.deepcopy(page_doc.metadata)
            parent_id = stable_id(page_uid, "parent", group_index, group_text)
            parent_metadata.update(
                {
                    "unique_id": parent_id,
                    "chunk_id": parent_id,
                    "parent_id": None,
                    "chunk_level": "parent",
                    "group_index": group_index,
                    "token_count": token_len(group_text),
                    "text_hash": stable_id(group_text),
                    "retrieval_enabled": include_parents,
                    "related_visuals": related_visuals,
                    "related_equations": related_equations,
                    "related_figure_titles": [item.get("title", "") for item in related_visuals if item.get("kind") == "figure"],
                    "related_table_titles": [item.get("title", "") for item in related_visuals if item.get("kind") == "table"],
                    "equation_titles": [item.get("title", "") for item in related_equations],
                    "has_formula": bool(page_doc.metadata.get("equations_info")) or bool(related_equations),
                }
            )
            parent_doc = Document(page_content=group_text, metadata=parent_metadata)
            parent_docs.append(parent_doc)

            child_docs = TEXT_SPLITTER.create_documents([group_text], metadatas=[parent_metadata])
            valid_child_count = 0
            for child_index, child_doc in enumerate(child_docs):
                child_text = clean_text(child_doc.page_content)
                if not is_valid_child_text(child_text):
                    continue
                if child_text == group_text and token_len(group_text) <= CHILD_CHUNK_SIZE:
                    continue

                child_metadata = copy.deepcopy(parent_metadata)
                child_id = stable_id(parent_id, "child", child_index, child_text)
                child_metadata.update(
                    {
                        "unique_id": child_id,
                        "chunk_id": child_id,
                        "parent_id": parent_id,
                        "chunk_level": "child",
                        "child_index": child_index,
                        "token_count": token_len(child_text),
                        "text_hash": stable_id(child_text),
                        "retrieval_enabled": True,
                    }
                )
                output_docs.append(Document(page_content=child_text, metadata=child_metadata))
                valid_child_count += 1

            if valid_child_count == 0 and is_valid_child_text(group_text):
                fallback_meta = copy.deepcopy(parent_metadata)
                fallback_child_id = stable_id(parent_id, "child", 0, group_text)
                fallback_meta.update(
                    {
                        "unique_id": fallback_child_id,
                        "chunk_id": fallback_child_id,
                        "parent_id": parent_id,
                        "chunk_level": "child",
                        "child_index": 0,
                        "retrieval_enabled": True,
                    }
                )
                output_docs.append(Document(page_content=group_text, metadata=fallback_meta))

    if include_parents:
        return parent_docs + output_docs
    return output_docs


def write_langchain_jsonl(docs: list[Document], output_path: str | Path = DEFAULT_JSONL_PATH) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_output_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp_output_path.open("w", encoding="utf-8") as file:
        for doc in docs:
            file.write(
                json.dumps(
                    {
                        "page_content": doc.page_content,
                        "metadata": sanitize_output_metadata(doc.metadata),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    tmp_output_path.replace(output_path)
    return output_path


def append_langchain_jsonl(docs: list[Document], output_path: str | Path = DEFAULT_JSONL_PATH) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as file:
        for doc in docs:
            file.write(
                json.dumps(
                    {
                        "page_content": doc.page_content,
                        "metadata": sanitize_output_metadata(doc.metadata),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return output_path


def summarize_docs(docs: list[Document]) -> dict[str, Any]:
    page_docs = [doc for doc in docs if doc.metadata.get("chunk_level") == "page"]
    return {
        "doc_count": len(page_docs),
        "pages": sorted({doc.metadata.get("page") for doc in page_docs if doc.metadata.get("page") is not None}),
        "figure_count": sum(len(doc.metadata.get("figures_info", [])) for doc in page_docs),
        "table_count": sum(len(doc.metadata.get("tables_info", [])) for doc in page_docs),
        "equation_count": sum(len(doc.metadata.get("equations_info", [])) for doc in page_docs),
    }

