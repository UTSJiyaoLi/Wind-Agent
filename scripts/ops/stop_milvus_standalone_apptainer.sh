#!/usr/bin/env bash
set -euo pipefail

base=/share/home/lijiyao/CCCC/milvus_standalone
work="$base/runtime"

if [ ! -f "$work/milvus.pid" ]; then
    echo "no pid file"
    exit 0
fi

pid="$(cat "$work/milvus.pid" || true)"
if [ -z "${pid:-}" ]; then
    echo "empty pid file"
    rm -f "$work/milvus.pid"
    exit 0
fi

if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    sleep 3
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" || true
    fi
    echo "stopped pid=$pid"
else
    echo "pid not running: $pid"
fi

rm -f "$work/milvus.pid"
