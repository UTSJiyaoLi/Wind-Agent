# Wind Resource Agent

Wind Resource Agent is a FastAPI + RAG/LangGraph backend with a lightweight local Web UI for wind-energy intelligence workflows.

This README is public-friendly: no private usernames, hostnames, or internal infrastructure identifiers are required.

## What Is NOT Included In This Repository

To make the project reproducible, this section explicitly lists assets that are typically private/large and therefore not shipped in Git.

1. Foundation/chat model weights
2. Embedding model weights
3. Reranker model weights
4. Vector database persistent data (Milvus data directories)
5. Internal datasets and metadata indexes
6. Prebuilt apptainer/singularity images (`*.sif`, offline tar)
7. Local/remote secret env files (`.env.local`, `.env.server`)

### Required Asset Checklist

Prepare equivalents of the following in your own environment:

- LLM endpoint reachable by backend (local vLLM or remote API)
- Embedding model path
- Reranker model path
- Metadata files used by retrieval hydration
- Running Milvus service + collection already built
- Container image with Python/runtime deps (if using container deployment)

If these are missing, service may start but retrieval/agent calls will fail.

## Architecture

- Backend runtime: remote Linux server (recommended via `tmux` + `apptainer`)
- Frontend runtime: local browser (`docs/local_rag_web_v3.0.html`)
- Connectivity: local SSH tunnel to remote backend (`127.0.0.1:8787` by default)

## Prerequisites

### Local machine

- Windows PowerShell (`.cmd` scripts)
- `ssh` client in PATH
- Conda env `rag_task` for ops/check scripts

### Remote machine

- Linux + `tmux`, `curl`, `apptainer`
- Accessible model/data paths
- Milvus and model-serving endpoints available

## Generic Host Configuration

Use your own hosts:

- Jump host: `<jump-user>@<jump-host>`
- Target host: `<target-user>@<target-host>`

For `wind_services.py`, prefer env vars instead of hardcoded values:

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

If your setup differs, adjust:

- `scripts/ops/wind_services.py`
- `scripts/ops/start_rag_web_local.cmd`

## Quick Start

### 1) Start/ensure remote backend sessions

```powershell
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
```

Alternative wrapper:

```powershell
.\scripts\ops\start_remote_rag_backend_gpu6000.cmd
```

### 2) Open local tunnel + Web UI

```powershell
.\scripts\ops\start_rag_web_local.cmd
```

Optional fixed local port:

```powershell
.\scripts\ops\start_rag_web_local.cmd 19087
```

### 3) Web UI fields

- `Mode`: `RAG` or `Wind Agent Tool`
- `RAG Backend URL`: auto-injected by startup script

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

Then upload artifacts to your server and update image references in your ops config.

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

- `api/`: FastAPI endpoints
- `orchestration/`: LangGraph orchestration
- `services/`: domain/business logic
- `tools/`: tool wrappers
- `scripts/search/rag_local_api.py`: unified RAG/Agent backend
- `scripts/ops/`: ops scripts (remote start, tunnel, build)
- `docs/local_rag_web_v3.0.html`: local Web UI

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

- Local: copy `.env.local.example` -> `.env.local` (do not commit)
- Server: copy `.env.server.example` -> `.env.server` (do not commit)
- Keep secrets and internal paths in env vars, not in code/scripts

## Testing

```powershell
conda activate rag_task
pytest -q
```