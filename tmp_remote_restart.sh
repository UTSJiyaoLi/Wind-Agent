#!/usr/bin/env bash
set -euo pipefail

ROOT="/share/home/lijiyao/CCCC/Wind-Agent"
LOGDIR="/share/home/lijiyao/CCCC/.logs"
IMG="/share/home/lijiyao/CCCC/apptainer/inforhub.sif"
BIND="/share/home/lijiyao/CCCC:/share/home/lijiyao/CCCC"
mkdir -p "$LOGDIR"

for s in wind-agent-api wind-agent-ui wind-rag-unified; do
  tmux kill-session -t "$s" 2>/dev/null || true
done

API_CMD="cd $ROOT; apptainer exec --bind $BIND $IMG python -m uvicorn api.app:app --host 0.0.0.0 --port 8005 > $LOGDIR/wind_agent_api.log 2>&1"
UI_CMD="cd $ROOT; WIND_AGENT_API_BASE=http://127.0.0.1:8005 apptainer exec --bind $BIND $IMG streamlit run ui/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 > $LOGDIR/wind_agent_ui_live.log 2>&1"
RAG_CMD="cd $ROOT; apptainer exec --bind $BIND $IMG python scripts/search/rag_local_api.py --host 127.0.0.1 --port 8787 --uri http://127.0.0.1:19530 --collection winddata_bge_m3_bm25 --model-path /share/home/lijiyao/CCCC/Models/BAAI/bge-m3 --llm-base-url http://127.0.0.1:8001 --llm-model /share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct --orchestrator-base-url http://127.0.0.1:8003 --orchestrator-model /share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct --hydrate-full-metadata --full-metadata-jsonl /share/home/lijiyao/CCCC/Data/embedding/full_metadata.jsonl --full-metadata-idx /share/home/lijiyao/CCCC/Data/embedding/full_metadata.idx.json --obs-enabled true --obs-backend jsonl --obs-trace-dir storage/traces --obs-redaction-mode summary_id > $LOGDIR/wind_rag_unified.log 2> $LOGDIR/wind_rag_unified.err"

tmux new-session -d -s wind-agent-api "$API_CMD"
tmux new-session -d -s wind-agent-ui "$UI_CMD"
tmux new-session -d -s wind-rag-unified "$RAG_CMD"

sleep 4

echo "=== tmux ==="
tmux ls

echo "=== ports ==="
ss -ltnp | egrep ':8005|:8501|:8787' || true

echo "=== health ==="
curl -s http://127.0.0.1:8005/health || true
echo
curl -s http://127.0.0.1:8787/health || true
echo
