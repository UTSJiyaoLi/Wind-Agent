# Wind Resource Agent

A public-friendly FastAPI + RAG/LangGraph backend with a lightweight local Web UI for wind-energy intelligence workflows.

This repository intentionally avoids private usernames, hostnames, and internal infrastructure identifiers.

## Table of Contents

- [Overview](#overview)
- [What Is Not Included](#what-is-not-included)
- [Required Assets](#required-assets)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Generic Host Configuration](#generic-host-configuration)
- [Quick Start](#quick-start)
- [Operations](#operations)
- [WSL2 Offline Container Build (Optional)](#wsl2-offline-container-build-optional)
- [Post-Startup Smoke Checks](#post-startup-smoke-checks)
- [Project Layout](#project-layout)
- [API Surface](#api-surface)
- [Observability](#observability)
- [Config Hygiene](#config-hygiene)
- [Testing](#testing)

## Overview

Wind Resource Agent is a FastAPI + RAG/LangGraph backend with a lightweight local Web UI for wind-energy intelligence workflows.

## What Is Not Included

To keep the repository reproducible and Git-friendly, the following private or large assets are not included:

1. Foundation/chat model weights
2. Embedding model weights
3. Reranker model weights
4. Vector database persistent data (Milvus data directories)
5. Internal datasets and metadata indexes
6. Prebuilt Apptainer/Singularity images (`*.sif`, offline tar)
7. Local/remote secret env files (`.env.local`, `.env.server`)

## Required Assets

Prepare equivalents of the following in your own environment:

- LLM endpoint reachable by the backend (local vLLM or remote API)
- Embedding model path
- Reranker model path
- Metadata files used by retrieval hydration
- Running Milvus service with collection already built
- Container image with Python/runtime dependencies (if using container deployment)

If these are missing, the service may start, but retrieval and agent calls will fail.

## Architecture

- **Backend runtime:** remote Linux server (recommended via `tmux` + `apptainer`)
- **Frontend runtime:** local browser (`docs/local_rag_web_v3.0.html`)
- **Connectivity:** local SSH tunnel to remote backend (`127.0.0.1:8787` by default)

## Prerequisites

### Local machine

- Windows PowerShell (`.cmd` scripts)
- `ssh` client available in `PATH`
- Conda environment `rag_task` for ops/check scripts

### Remote machine

- Linux with `tmux`, `curl`, and `apptainer`
- Accessible model and data paths
- Available Milvus and model-serving endpoints

## Generic Host Configuration

Use your own hosts:

- Jump host: `<jump-user>@<jump-host>`
- Target host: `<target-user>@<target-host>`

For `wind_services.py`, prefer environment variables instead of hardcoded values:

- `WIND_JUMP_HOST`
- `WIND_TARGET_HOST`
- `WIND_REMOTE_REPO`
- `WIND_REMOTE_BIND`
- `WIND_REMOTE_IMG_INFORHUB`
- `WIND_REMOTE_IMG_VLLM`
- `WIND_REMOTE_LOGDIR`
- `WIND_REMOTE_MODEL_EMBED`
- `WIND_REMOTE_MODEL_CHAT`
- `WIND_REMOTE_MODEL_ORCH`
- `WIND_REMOTE_MODEL_RERANKER`
- `WIND_REMOTE_META_JSONL`
- `WIND_REMOTE_META_IDX`

If your setup differs, update:

- `scripts/ops/wind_services.py`
- `scripts/ops/start_rag_web_local.cmd`

## Quick Start

### 1. Start or verify remote backend sessions

```powershell
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
```

Alternative wrapper:

```powershell
.\scripts\ops\start_remote_rag_backend_gpu6000.cmd
```

### 2. Open the local tunnel and Web UI

```powershell
.\scripts\ops\start_rag_web_local.cmd
```

Optional fixed local port:

```powershell
.\scripts\ops\start_rag_web_local.cmd 19087
```

### 3. Web UI fields

- `Mode`: `RAG` or `Wind Agent Tool`
- `RAG Backend URL`: auto-injected by the startup script

## Operations

```powershell
.\scripts\ops\wind_services.cmd status
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
.\scripts\ops\wind_services.cmd restart
.\scripts\ops\wind_services.cmd stop
```

These scripts only manage `wind-*` tmux sessions.

## WSL2 Offline Container Build (Optional)

Use your own Linux user path:

- `\\wsl$\Ubuntu\home\<your-user>\container_build`

```bash
cd /mnt/c/wind-agent
bash scripts/ops/build_apptainer_in_wsl2.sh
```

Then upload the generated artifacts to your server and update image references in your ops config.

## Post-Startup Smoke Checks

```bash
# 1) health
curl -s http://127.0.0.1:8787/health

# 2) dependency self-check
python scripts/ops/check_langchain_stack.py

# 3) chat smoke test
curl -s -X POST http://127.0.0.1:8787/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"mode\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"What is wind turbine wake effect?\"}]}"
```

## Project Layout

```text
api/                         FastAPI endpoints
orchestration/               LangGraph orchestration
services/                    Domain and business logic
tools/                       Tool wrappers
scripts/search/rag_local_api.py  Unified RAG/Agent backend
scripts/ops/                 Ops scripts (remote start, tunnel, build)
docs/local_rag_web_v3.0.html Local Web UI
```

## API Surface

- `POST /api/chat`
  - `mode=llm_direct`
  - `mode=rag`
  - `mode=wind_agent`
- `POST /agent/chat`
- `POST /tasks`
- `GET /tasks/{task_id}`

## Observability

Default offline JSONL tracing:

- `OBS_BACKEND=jsonl`
- `OBS_ENABLED=true`
- `OBS_TRACE_DIR=storage/traces`
- `OBS_REDACTION_MODE=summary_id`

Optional LangSmith:

- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_API_KEY`

## Config Hygiene

- Local: copy `.env.local.example` to `.env.local` and do not commit it
- Server: copy `.env.server.example` to `.env.server` and do not commit it
- Keep secrets and internal paths in environment variables, not in code or scripts

## Testing

```powershell
conda activate rag_task
pytest -q
```
