#!/usr/bin/env bash
set -euo pipefail

base=/share/home/lijiyao/CCCC/milvus_standalone
work="$base/runtime"
image=/share/home/lijiyao/CCCC/apptainer/milvus-standalone-v269.sif

mkdir -p "$work/volumes/milvus" "$work/logs"

cat > "$work/embedEtcd.yaml" <<'EOF'
listen-client-urls: http://0.0.0.0:2379
advertise-client-urls: http://0.0.0.0:2379
quota-backend-bytes: 4294967296
auto-compaction-mode: revision
auto-compaction-retention: "1000"
EOF

cat > "$work/user.yaml" <<'EOF'
etcd:
  use:
    embed: true
  data:
    dir: /var/lib/milvus/etcd
localStorage:
  path: /var/lib/milvus/data/
EOF

if [ -f "$work/milvus.pid" ]; then
    old_pid="$(cat "$work/milvus.pid" || true)"
    if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
        echo "Milvus already running: pid=$old_pid"
        exit 0
    fi
fi

nohup apptainer exec \
  --bind "$work/volumes/milvus:/var/lib/milvus,$work/embedEtcd.yaml:/milvus/configs/embedEtcd.yaml,$work/user.yaml:/milvus/configs/user.yaml" \
  "$image" \
  env LD_PRELOAD= MALLOC_CONF= MILVUSCONF=/milvus/configs ETCD_USE_EMBED=true ETCD_DATA_DIR=/var/lib/milvus/etcd ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml COMMON_STORAGETYPE=local DEPLOY_MODE=STANDALONE \
  milvus run standalone > "$work/logs/milvus.log" 2>&1 &

pid=$!
echo "$pid" > "$work/milvus.pid"
echo "started pid=$pid"

for _ in $(seq 1 30); do
    if curl -sS --max-time 2 http://127.0.0.1:9091/healthz >/dev/null 2>&1 \
      && env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
         curl -sS --max-time 3 -H 'Content-Type: application/json' -d '{}' \
         http://127.0.0.1:19530/v2/vectordb/collections/list >/dev/null 2>&1; then
        echo "health=OK"
        exit 0
    fi
    sleep 2
done

echo "health check failed"
tail -n 120 "$work/logs/milvus.log" || true
exit 1
