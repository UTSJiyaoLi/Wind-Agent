@echo off
setlocal

rem Start/refresh rag_local_api.py on gpu6000 in a tmux session via jump host.
rem This script runs from local Windows and executes remote apptainer command.

set "JUMP_HOST=lijiyao@172.30.3.166"
set "TARGET_HOST=lijiyao@gpu6000"
set "TMUX_SESSION=wind-rag-unified"
set "REMOTE_REPO=/share/home/lijiyao/CCCC/Wind-Agent"
set "REMOTE_SIF=/share/home/lijiyao/CCCC/wind-agent-offline_20260403.sif"
set "REMOTE_MODEL=/share/home/lijiyao/CCCC/Models/BAAI/bge-m3"
set "REMOTE_CHAT_LLM_BASE=http://127.0.0.1:8001"
set "REMOTE_CHAT_LLM_MODEL=/share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct"
set "REMOTE_ORCH_LLM_BASE=http://127.0.0.1:8003"
set "REMOTE_ORCH_LLM_MODEL=/share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct"
set "REMOTE_META_JSONL=/share/home/lijiyao/CCCC/Data/embedding/full_metadata.jsonl"
set "REMOTE_META_IDX=/share/home/lijiyao/CCCC/Data/embedding/full_metadata.idx.json"

set "REMOTE_CMD=cd %REMOTE_REPO% && tmux kill-session -t %TMUX_SESSION% 2>/dev/null; tmux new -d -s %TMUX_SESSION% ""apptainer exec %REMOTE_SIF% python scripts/search/rag_local_api.py --host 127.0.0.1 --port 8787 --uri http://127.0.0.1:19530 --collection winddata_bge_m3_bm25 --model-path %REMOTE_MODEL% --llm-base-url %REMOTE_CHAT_LLM_BASE% --llm-model %REMOTE_CHAT_LLM_MODEL% --orchestrator-base-url %REMOTE_ORCH_LLM_BASE% --orchestrator-model %REMOTE_ORCH_LLM_MODEL% --hydrate-full-metadata --full-metadata-jsonl %REMOTE_META_JSONL% --full-metadata-idx %REMOTE_META_IDX% --obs-enabled true --obs-backend jsonl --obs-trace-dir storage/traces --obs-redaction-mode summary_id"" && tmux ls | grep %TMUX_SESSION%"

echo Starting remote backend on gpu6000 (tmux session: %TMUX_SESSION%) ...
ssh -J %JUMP_HOST% %TARGET_HOST% "%REMOTE_CMD%"
if errorlevel 1 (
  echo [ERROR] failed to start remote backend.
  exit /b 1
)

echo Remote backend started.
echo Next step: run scripts\ops\start_rag_web_local.cmd

endlocal
