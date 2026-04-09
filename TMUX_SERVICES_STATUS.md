# Wind-Agent Tmux 服务清单（gpu6000）

更新时间：2026-04-08（本地执行）
主机：`gpu6000`

## 1. 当前 tmux 会话

- `vllm`
- `wind-agent-ui`
- `wind-rag-unified`
- `wind-vllm-orch`

## 2. 服务总览

| 服务 | tmux 会话 | 端口 | 进程 PID | 启动时间 (server) | 运行时长 | 容器镜像 | 模型/功能 |
|---|---|---:|---:|---|---|---|---|
| RAG 后端 (`rag_local_api.py`) | `wind-rag-unified` | `127.0.0.1:8787` | `2090061` | Wed Apr 8 14:37:06 2026 | `30:11` | `/share/home/lijiyao/CCCC/wind-agent-offline_20260403.sif` | 检索问答、Agent 编排入口 |
| Web UI (`streamlit`) | `wind-agent-ui` | `0.0.0.0:8501` | `1476243` | Fri Apr 3 10:29:16 2026 | `5-04:38:01` | `/share/home/lijiyao/CCCC/wind-agent-offline_20260403.sif` | Wind-Agent 前端界面 |
| 主 LLM 服务 (`vllm`) | `vllm` | `0.0.0.0:8001` | `1360928` | Tue Mar 10 13:38:42 2026 | `29-01:28:35` | `/share/home/lijiyao/CCCC/apptainer/vllm.sif` | `/share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct` |
| 编排 LLM 服务 (`vllm`) | `wind-vllm-orch` | `0.0.0.0:8003` | `2094586` | Wed Apr 8 14:52:29 2026 | `14:48` | `/share/home/lijiyao/CCCC/apptainer/vllm-openai.sif` | `/share/home/lijiyao/CCCC/Models/llms/Llama-3.1-8B-Instruct` |
| Milvus 向量库 | （独立进程，非 tmux） | `*:19530`, `*:9091` | `3810067` | Tue Mar 24 14:32:12 2026 | `15-00:35:05` | `/share/home/lijiyao/CCCC/apptainer/milvus-standalone-v269.sif` | 向量检索数据库 |

## 3. 健康检查结果

- `http://127.0.0.1:8787/health`：`ok=true`
- `http://127.0.0.1:8001/v1/models`：可返回模型列表（Qwen3-VL-8B-Instruct）
- `http://127.0.0.1:8003/v1/models`：可返回模型列表（Llama-3.1-8B-Instruct）
- `http://127.0.0.1:9091/healthz`：`OK`

## 4. 端口监听快照

- `127.0.0.1:8787` -> `python (rag_local_api.py)`
- `0.0.0.0:8501` -> `streamlit`
- `0.0.0.0:8001` -> `vllm`
- `0.0.0.0:8003` -> `vllm`
- `*:19530` -> `milvus`
- `*:9091` -> `milvus`

## 5. GPU 占用快照（nvidia-smi）

- `GPU0`: used `88161 MiB` / total `97887 MiB`（主要承载 8001）
- `GPU1`: used `88761 MiB` / total `97887 MiB`（主要承载 8003）
- `GPU2~GPU7`: 基本空闲

## 6. 建议维护命令（服务器）

```bash
# 查看 tmux 会话
tmux ls

# 进入某个会话查看日志
tmux attach -t wind-rag-unified
tmux attach -t wind-agent-ui
tmux attach -t vllm
tmux attach -t wind-vllm-orch

# 快速健康检查
curl -s http://127.0.0.1:8787/health
curl -s http://127.0.0.1:8001/v1/models
curl -s http://127.0.0.1:8003/v1/models
curl -s http://127.0.0.1:9091/healthz
```
