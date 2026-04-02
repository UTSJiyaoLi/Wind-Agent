import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.pipeline.script_config import apply_config_overrides


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click pipeline: parse -> ingest -> search -> eval.")
    parser.add_argument("--config", default="", help="Optional JSON config file path.")
    parser.add_argument("--python-exec", default=sys.executable, help="Python executable path.")
    parser.add_argument("--parse-mode", choices=["single", "batch"], default="single")
    parser.add_argument("--eval-script", choices=["recall", "ragas"], default="recall")
    parser.add_argument("--skip-parse", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--skip-eval", action="store_true")
    args = parser.parse_args()
    return apply_config_overrides(args, section="run_pipeline")


def _run_step(step_name: str, command: list[str]) -> None:
    print(f"[pipeline] start {step_name}: {' '.join(command)}")
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Step failed: {step_name}, exit_code={result.returncode}")
    print(f"[pipeline] done {step_name}")


def main() -> None:
    args = parse_args()
    py = args.python_exec
    repo_dir = Path(__file__).resolve().parents[2]

    def make_cmd(script_name: str) -> list[str]:
        cmd = [py, str(repo_dir / script_name)]
        if args.config:
            cmd.extend(["--config", args.config])
        return cmd

    if not args.skip_parse:
        parse_script = "parse_mineru_v2.py" if args.parse_mode == "single" else "parse_mineru_v2_batch.py"
        _run_step("parse", make_cmd(parse_script))

    if not args.skip_ingest:
        _run_step("ingest", make_cmd("ingest_winddata_milvus.py"))

    if not args.skip_search:
        _run_step("search", make_cmd("search.py"))

    if not args.skip_eval:
        eval_script = "evaluate_recall_quality.py" if args.eval_script == "recall" else "ragas_retrieval_eval.py"
        _run_step("eval", make_cmd(eval_script))

    print("[pipeline] all selected steps completed")


if __name__ == "__main__":
    main()
