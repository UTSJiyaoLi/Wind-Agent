# Wind Resource Agent

## 当前默认运行拓扑

- 前端：本地浏览器打开 `docs/local_rag_web_v3.0.html`
- 后端：统一运行在 `lijiyao -> gpu6000`
- 连接：本地通过 SSH 端口转发访问 `gpu6000:127.0.0.1:8787`
- 容器：优先使用服务器现有 `apptainer` 镜像；不满足时在本地 WSL2 构建

## 一键操作

### 1) 在远端启动 Wind 服务（tmux + apptainer）

```powershell
.\scripts\ops\start_remote_rag_backend_gpu6000.cmd
```

或使用统一运维入口（仅管理 `wind-*` 会话，不触碰 fish 系统）：

```powershell
.\scripts\ops\wind_services.cmd status
.\scripts\ops\wind_services.cmd start
.\scripts\ops\wind_services.cmd health
.\scripts\ops\wind_services.cmd restart
.\scripts\ops\wind_services.cmd stop
```

### 2) 本地开隧道并打开 Web UI（自动选择本地空闲端口）

```powershell
.\scripts\ops\start_rag_web_local.cmd
```

可手动指定本地端口：

```powershell
.\scripts\ops\start_rag_web_local.cmd 19087
```

### 3) Web UI 参数

- `Mode`: `RAG` 或 `Wind Agent Tool`
- `RAG Backend URL`: 启动脚本自动注入（默认本地随机空闲端口）

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

启用 LangSmith 上报时使用以下变量：

- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_API_KEY`

## 配置分层（建议）

- 本地：复制 `.env.local.example` 为 `.env.local`（不入库）
- 服务器：复制 `.env.server.example` 到服务器仓库根目录 `.env.server`（不入库）
- 运维脚本优先读取环境变量，避免把敏感配置写入脚本正文

## 测试

```powershell
conda activate rag_task
pytest -q
```
