import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.parse.parse_mineru_v2_core import append_langchain_jsonl
from scripts.parse.parse_mineru_v2_core import DEFAULT_ASSET_DIR
from scripts.parse.parse_mineru_v2_core import load_pdf
from scripts.parse.parse_mineru_v2_core import simple_doc_name
from scripts.parse.parse_mineru_v2_core import summarize_docs
from scripts.parse.parse_mineru_v2_core import texts_split
from scripts.pipeline.script_config import apply_config_overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch parse English PDFs with MinerU into one JSONL file.")
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--input-dir", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--asset-dir", default=str(DEFAULT_ASSET_DIR))
    parser.add_argument("--output-name", default="winddata_en_all.jsonl")
    parser.add_argument("--pattern", default="DOC_*__en__*.pdf")
    parser.add_argument("--mineru-backend", default="pipeline")
    parser.add_argument("--mineru-method", default="txt")
    parser.add_argument("--include-parents", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--summary-name", default="_batch_summary.json")
    args = parser.parse_args()
    return apply_config_overrides(args, section="parse_mineru_v2_batch")


def main() -> None:
    args = parse_args()
    if not args.input_dir or not args.output_dir:
        raise ValueError("Both --input-dir and --output-dir are required.")
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    asset_dir = Path(args.asset_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)
    output_jsonl = output_dir / args.output_name
    output_jsonl.unlink(missing_ok=True)

    pdf_paths = sorted(input_dir.glob(args.pattern))
    summary: list[dict] = []
    summary_path = output_dir / args.summary_name

    def flush_summary() -> None:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    for pdf_path in pdf_paths:
        simple_name = simple_doc_name(pdf_path)
        doc_asset_dir = asset_dir / simple_name
        # Previous per-document output mode:
        # doc_output_jsonl = output_dir / f"{simple_name}.jsonl"
        try:
            raw_docs = load_pdf(
                pdf_path=pdf_path,
                asset_save_dir=doc_asset_dir,
                mineru_backend=args.mineru_backend,
                mineru_method=args.mineru_method,
            )
            split_docs = texts_split(raw_docs, include_parents=args.include_parents)
            append_langchain_jsonl(split_docs, output_jsonl)
            record = {
                "pdf": str(pdf_path),
                "jsonl": str(output_jsonl),
                "doc_name": simple_name,
                "raw": summarize_docs(raw_docs),
                "split": len(split_docs),
                "status": "ok",
            }
        except Exception as exc:
            record = {
                "pdf": str(pdf_path),
                "jsonl": str(output_jsonl),
                "doc_name": simple_name,
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        summary.append(record)
        flush_summary()
        print(json.dumps(record, ensure_ascii=False))

    ok_count = sum(1 for item in summary if item.get("status") in {None, "ok"} and not item.get("skipped"))
    error_count = sum(1 for item in summary if item.get("status") == "error")
    skipped_count = sum(1 for item in summary if item.get("skipped"))
    print(
        json.dumps(
            {
                "count": len(summary),
                "ok": ok_count,
                "error": error_count,
                "skipped": skipped_count,
                "output_jsonl": str(output_jsonl),
                "summary_path": str(summary_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
