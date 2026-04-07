# Wind Resource Agent

## 当前默认运行拓扑

- 前端：本地浏览器打开 `docs/local_rag_web_v3.0.html`
- 后端：统一运行在 `lijiyao -> gpu6000`
- 连接：本地通过 SSH 端口转发访问 `gpu6000:127.0.0.1:8787`
- 容器：优先使用服务器现有 `apptainer` 镜像；不满足时在本地 WSL2 构建

## 一键操作

### 1) 在远端启动后端（tmux + apptainer）

```powershell
.\scripts\ops\start_remote_rag_backend_gpu6000.cmd
```

### 2) 本地开隧道并打开 Web UI

```powershell
.\scripts\ops\start_rag_web_local.cmd
```

### 3) Web UI 参数

- `Mode`: `RAG` 或 `Wind Agent Tool`
- `RAG Backend URL`: `http://127.0.0.1:8787`

## WSL2 构建离线容器包（备用）

你给定的构建目录是：
- `\\wsl$\Ubuntu\home\lijiyao\container_build`

在 WSL2 中执行：

```bash
cd /mnt/c/wind-agent
bash scripts/ops/build_apptainer_in_wsl2.sh
```

输出 tar 默认在：
- `/home/lijiyao/container_build/artifacts/containers/wind-agent-offline_20260403.tar`

上传到服务器并转成 `sif` 后，更新 `scripts/ops/start_remote_rag_backend_gpu6000.cmd` 的 `REMOTE_SIF` 路径。
启动后先做三步检查（不做评测）：

```bash
# 1) health
curl -s http://127.0.0.1:8787/health

# 2) LangChain 依赖自检
python scripts/ops/check_langchain_stack.py

# 3) smoke 请求
curl -s -X POST http://127.0.0.1:8787/api/chat -H "Content-Type: application/json" -d "{\"mode\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"风电尾流是什么\"}]}"
```

## 目录说明（核心）

- `api/`: FastAPI 接口
- `orchestration/`: LangGraph 编排
- `services/`: 风资源分析逻辑
- `tools/`: 工具封装
- `scripts/search/rag_local_api.py`: RAG/Agent 统一后端服务
- `scripts/ops/`: 运维脚本（远端启动、隧道、容器构建）
- `docs/local_rag_web_v3.0.html`: 主 Web UI

## API 说明

- `POST /api/chat`
  - `mode=llm_direct`
  - `mode=rag`
  - `mode=wind_agent`
- `POST /agent/chat`
- `POST /tasks`
- `GET /tasks/{task_id}`

## 本地可观测（离线）

默认使用本地 JSONL tracing（不依赖外网）：

- `OBS_BACKEND=jsonl`
- `OBS_ENABLED=true`
- `OBS_TRACE_DIR=storage/traces`
- `OBS_REDACTION_MODE=summary_id`

LangSmith 变量仅做兼容预留（当前不启用上报）：

- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_API_KEY`

## 测试

```powershell
conda activate rag_task
pytest -q
```

