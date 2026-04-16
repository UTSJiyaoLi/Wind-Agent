#!/usr/bin/env python
"""Manage Wind-Agent tmux services on gpu6000 (wind-* whitelist only)."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

ALLOWED_SESSIONS = ("wind-vllm-orch", "wind-agent-api", "wind-agent-ui", "wind-rag-unified")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            os.environ.setdefault(k, v)


def _run_ssh(remote_script: str, *, jump_host: str, target_host: str) -> int:
    cmd = ["ssh", "-J", jump_host, target_host, f"bash -lc {shlex.quote(remote_script)}"]
    proc = subprocess.run(cmd, text=True)
    return int(proc.returncode)


def _build_remote_start_script() -> str:
    root = os.getenv("WIND_REMOTE_REPO", "/share/home/lijiyao/CCCC/Wind-Agent")
    bind = os.getenv("WIND_REMOTE_BIND", "/share/home/lijiyao/CCCC:/share/home/lijiyao/CCCC")
    inforhub_img = os.getenv("WIND_REMOTE_IMG_INFORHUB", "/share/home/lijiyao/CCCC/apptainer/inforhub.sif")
    vllm_img = os.getenv("WIND_REMOTE_IMG_VLLM", "/share/home/lijiyao/CCCC/apptainer/vllm.sif")
    logdir = os.getenv("WIND_REMOTE_LOGDIR", "/share/home/lijiyao/CCCC/.logs")
    model_embed = os.getenv("WIND_REMOTE_MODEL_EMBED", "/share/home/lijiyao/CCCC/Models/BAAI/bge-m3")
    model_chat = os.getenv("WIND_REMOTE_MODEL_CHAT", "/share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct")
    model_orch = os.getenv("WIND_REMOTE_MODEL_ORCH", "/share/home/lijiyao/CCCC/Models/llms/Llama-3.1-8B-Instruct")
    model_reranker = os.getenv("WIND_REMOTE_MODEL_RERANKER", "/share/home/lijiyao/CCCC/Models/BAAI/bge-reranker-v2-m3")
    rag_device = os.getenv("WIND_REMOTE_RAG_DEVICE", "cuda")
    rag_enable_nv = str(os.getenv("WIND_REMOTE_RAG_ENABLE_NV", "true")).strip().lower() in {"1", "true", "yes", "on"}
    rag_enable_query_rewrite = os.getenv("WIND_REMOTE_RAG_ENABLE_QUERY_REWRITE", "true")
    rag_enable_domain_expansion = os.getenv("WIND_REMOTE_RAG_ENABLE_DOMAIN_EXPANSION", "false")
    meta_jsonl = os.getenv("WIND_REMOTE_META_JSONL", "/share/home/lijiyao/CCCC/Data/embedding/full_metadata.jsonl")
    meta_idx = os.getenv("WIND_REMOTE_META_IDX", "/share/home/lijiyao/CCCC/Data/embedding/full_metadata.idx.json")
    obs_backend = os.getenv("OBS_BACKEND", "jsonl")
    obs_enabled = os.getenv("OBS_ENABLED", "true")
    obs_trace_dir = os.getenv("OBS_TRACE_DIR", "storage/traces")
    obs_redaction_mode = os.getenv("OBS_REDACTION_MODE", "summary_id")

    env_prefix = (
        "if [ -f ./.env.server ]; then set -a; . ./.env.server; set +a; fi; "
        f"OBS_BACKEND={shlex.quote(obs_backend)} OBS_ENABLED={shlex.quote(obs_enabled)} "
        f"OBS_TRACE_DIR={shlex.quote(obs_trace_dir)} OBS_REDACTION_MODE={shlex.quote(obs_redaction_mode)} "
        f"RAG_ENABLE_QUERY_REWRITE={shlex.quote(rag_enable_query_rewrite)} "
        f"RAG_ENABLE_DOMAIN_EXPANSION={shlex.quote(rag_enable_domain_expansion)}"
    )

    sessions = {
        "wind-vllm-orch": (
            f"cd {root}; {env_prefix} apptainer exec --nv {vllm_img} "
            f"vllm serve {model_orch} --host 0.0.0.0 --port 8003 --dtype float16 --max-model-len 8192 "
            f"> {logdir}/wind_vllm_orch.log 2> {logdir}/wind_vllm_orch.err"
        ),
        "wind-agent-api": (
            f"cd {root}; {env_prefix} apptainer exec --bind {bind} {inforhub_img} "
            f"python -m uvicorn api.app:app --host 0.0.0.0 --port 8005 "
            f"> {logdir}/wind_agent_api.log 2>&1"
        ),
        "wind-agent-ui": (
            f"cd {root}; {env_prefix} WIND_AGENT_API_BASE=http://127.0.0.1:8005 apptainer exec --bind {bind} {inforhub_img} "
            f"streamlit run ui/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 "
            f"> {logdir}/wind_agent_ui.log 2>&1"
        ),
        "wind-rag-unified": (
            f"cd {root}; {env_prefix} apptainer exec {'--nv ' if rag_enable_nv else ''}--bind {bind} {inforhub_img} "
            "python scripts/search/rag_local_api.py --host 127.0.0.1 --port 8787 "
            "--uri http://127.0.0.1:19530 --collection winddata_bge_m3_bm25 "
            f"--model-path {model_embed} --llm-base-url http://127.0.0.1:8001 --llm-model {model_chat} "
            f"--orchestrator-base-url http://127.0.0.1:8003 --orchestrator-model {model_chat} "
            f"--device {rag_device} --reranker-model-path {model_reranker} "
            f"--hydrate-full-metadata --full-metadata-jsonl {meta_jsonl} --full-metadata-idx {meta_idx} "
            f"--obs-enabled {obs_enabled} --obs-backend {obs_backend} --obs-trace-dir {obs_trace_dir} --obs-redaction-mode {obs_redaction_mode} "
            f"> {logdir}/wind_rag_unified.log 2> {logdir}/wind_rag_unified.err"
        ),
    }

    lines = [
        "set -e",
        f"mkdir -p {shlex.quote(logdir)}",
        f"cd {shlex.quote(root)}",
    ]
    for name in ALLOWED_SESSIONS:
        cmd = sessions[name]
        lines.append(
            f"if ! tmux has-session -t {name} 2>/dev/null; then tmux new -d -s {name} {shlex.quote(cmd)}; fi"
        )
    lines.append("echo '[wind-services] started/ensured sessions:'")
    lines.append("tmux ls | grep '^wind-' || true")
    return "; ".join(lines)


def _build_remote_stop_script() -> str:
    cmds = [f"tmux kill-session -t {s} 2>/dev/null || true" for s in ALLOWED_SESSIONS]
    cmds.append("echo '[wind-services] stopped sessions (if existed)'")
    cmds.append("tmux ls | grep '^wind-' || true")
    return "; ".join(cmds)


def _build_remote_status_script() -> str:
    lines = ["echo '=== wind tmux sessions ==='"]
    for s in ALLOWED_SESSIONS:
        lines.append(f"if tmux has-session -t {s} 2>/dev/null; then echo '{s}: up'; else echo '{s}: down'; fi")
    lines.extend(
        [
            "echo '=== wind ports ==='",
            "ss -lntp | grep -E ':(8003|8005|8501|8787)\\b' || true",
        ]
    )
    return "; ".join(lines)


def _build_remote_health_script() -> str:
    return "; ".join(
        [
            "echo '=== health: wind-rag ==='",
            "curl -sS --max-time 6 http://127.0.0.1:8787/health || true",
            "echo",
            "echo '=== health: wind-api ==='",
            "curl -sS --max-time 6 http://127.0.0.1:8005/health || true",
            "echo",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage wind-* services on gpu6000")
    parser.add_argument("action", choices=["start", "stop", "status", "restart", "health"])
    parser.add_argument("--jump-host", default=os.getenv("WIND_JUMP_HOST", "lijiyao@172.30.3.166"))
    parser.add_argument("--target-host", default=os.getenv("WIND_TARGET_HOST", "lijiyao@gpu6000"))
    parser.add_argument("--dotenv", default=".env.local")
    args = parser.parse_args()

    _load_dotenv(Path(args.dotenv))

    if args.action == "start":
        remote = _build_remote_start_script()
    elif args.action == "stop":
        remote = _build_remote_stop_script()
    elif args.action == "status":
        remote = _build_remote_status_script()
    elif args.action == "health":
        remote = _build_remote_health_script()
    else:
        rc1 = _run_ssh(_build_remote_stop_script(), jump_host=args.jump_host, target_host=args.target_host)
        rc2 = _run_ssh(_build_remote_start_script(), jump_host=args.jump_host, target_host=args.target_host)
        return 0 if rc1 == 0 and rc2 == 0 else 1

    return _run_ssh(remote, jump_host=args.jump_host, target_host=args.target_host)


if __name__ == "__main__":
    sys.exit(main())
