#!/usr/bin/env bash
cd /share/home/lijiyao/CCCC/Wind-Agent || exit 1
export PLANNER_LLM_BASE_URL=http://127.0.0.1:8003
export PLANNER_LLM_MODEL=/share/home/lijiyao/CCCC/Models/llms/Llama-3.1-8B-Instruct
export PLANNER_LLM_API_KEY=EMPTY
export PLANNER_LLM_TIMEOUT=60
apptainer exec --bind /share/home/lijiyao/CCCC:/share/home/lijiyao/CCCC /share/home/lijiyao/CCCC/apptainer/inforhub.sif python -m uvicorn api.app:app --host 0.0.0.0 --port 8005 > /share/home/lijiyao/CCCC/.logs/wind_agent_api.log 2>&1
