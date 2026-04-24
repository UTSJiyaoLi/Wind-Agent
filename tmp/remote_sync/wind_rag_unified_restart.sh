#!/usr/bin/env bash
cd /share/home/lijiyao/CCCC/Wind-Agent || exit 1
export CUDA_VISIBLE_DEVICES=0
export PLANNER_LLM_BASE_URL=http://127.0.0.1:8003
export PLANNER_LLM_MODEL=/share/home/lijiyao/CCCC/Models/llms/Llama-3.1-8B-Instruct
export PLANNER_LLM_API_KEY=EMPTY
export PLANNER_LLM_TIMEOUT=60
apptainer exec --nv --bind /share/home/lijiyao/CCCC:/share/home/lijiyao/CCCC /share/home/lijiyao/CCCC/apptainer/inforhub.sif python scripts/search/rag_local_api.py --host 127.0.0.1 --port 8787 --uri http://127.0.0.1:19530 --collection winddata_bge_m3_bm25 --model-path /share/home/lijiyao/CCCC/Models/BAAI/bge-m3 --llm-base-url http://127.0.0.1:8001 --llm-model /share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct --orchestrator-base-url http://127.0.0.1:8001 --orchestrator-model /share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct --planner-base-url http://127.0.0.1:8003 --planner-model /share/home/lijiyao/CCCC/Models/llms/Llama-3.1-8B-Instruct --device cuda --reranker-model-path /share/home/lijiyao/CCCC/Models/BAAI/bge-reranker-v2-m3 --hydrate-full-metadata --full-metadata-jsonl /share/home/lijiyao/CCCC/Data/embedding/full_metadata.jsonl --full-metadata-idx /share/home/lijiyao/CCCC/Data/embedding/full_metadata.idx.json --obs-enabled true --obs-backend jsonl --obs-trace-dir storage/traces --obs-redaction-mode summary_id > /share/home/lijiyao/CCCC/.logs/wind_rag_unified.log 2> /share/home/lijiyao/CCCC/.logs/wind_rag_unified.err
