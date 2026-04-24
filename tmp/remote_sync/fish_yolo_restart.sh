#!/usr/bin/env bash
cd /share/home/lijiyao/CCCC/Fish-Disease-Detection-System || exit 1
export TMUX_START_TS=""
apptainer exec --nv /share/home/lijiyao/CCCC/apptainer/yolo_fastapi.sif uvicorn server.yolo_app:app --host 0.0.0.0 --port 8000 > .logs/yolo.log 2> .logs/yolo.err
