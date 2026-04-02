import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.parse.parse_mineru_v2_core import DEFAULT_ASSET_DIR
from scripts.parse.parse_mineru_v2_core import DEFAULT_JSONL_PATH
from scripts.parse.parse_mineru_v2_core import DEFAULT_PDF_PATH
from scripts.parse.parse_mineru_v2_core import load_pdf
from scripts.parse.parse_mineru_v2_core import summarize_docs
from scripts.parse.parse_mineru_v2_core import texts_split
from scripts.parse.parse_mineru_v2_core import write_langchain_jsonl
from scripts.pipeline.script_config import apply_config_overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse PDF with MinerU to LangChain Document JSONL.")
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--pdf-path", default=str(DEFAULT_PDF_PATH))
    parser.add_argument("--asset-dir", default=str(DEFAULT_ASSET_DIR))
    parser.add_argument("--output-jsonl", default=str(DEFAULT_JSONL_PATH))
    parser.add_argument("--start-page", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--mineru-backend", default="pipeline")
    parser.add_argument("--mineru-method", default="auto")
    parser.add_argument("--include-parents", action="store_true")
    args = parser.parse_args()
    return apply_config_overrides(args, section="parse_mineru_v2")


def main() -> None:
    args = parse_args()
    raw_docs = load_pdf(
        pdf_path=args.pdf_path,
        asset_save_dir=args.asset_dir,
        mineru_backend=args.mineru_backend,
        mineru_method=args.mineru_method,
        start_page=args.start_page,
        max_pages=args.max_pages,
    )
    split_docs = texts_split(raw_docs, include_parents=args.include_parents)
    output_file = write_langchain_jsonl(split_docs, args.output_jsonl)
    print(json.dumps({"raw": summarize_docs(raw_docs), "split": len(split_docs), "output": str(output_file)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
