# 远端 CPU/GPU 节点服务清单

更新时间：2026-04-09 16:49 (Asia/Shanghai)
采集方式：`ssh lijiyao@gpu6000` + `tmux ls` + `tmux list-panes` + `ss -ltnp`。

## 1) gpu6000 当前会话

| tmux 会话 | 主要职责 | 启动方式摘要 |
| --- | --- | --- |
| `fish-yolo` | 鱼病 YOLO 服务 | `yolo_fastapi.sif` -> `uvicorn :8000` |
| `vllm` | Fish VLM/LLM 推理 | `vllm.sif` -> `vllm serve :8001` |
| `fish-retrieval` | Fish 检索服务 | `wind-agent-offline_20260403.sif` -> `uvicorn :8002` |
| `wind-vllm-orch` | Wind Orchestrator vLLM | `vllm.sif` -> `vllm serve :8003` |
| `fish-fdapp` | Fish 聚合应用 | `yolo_vllm.sif` -> `uvicorn :8004` |
| `wind-agent-api` | Wind-Agent FastAPI | `inforhub.sif` + bind -> `uvicorn :8005` |
| `wind-agent-ui` | Wind-Agent Streamlit 前端 | `inforhub.sif` + bind -> `streamlit :8501` |
| `wind-rag-unified` | Wind RAG/Agent 统一后端 | `inforhub.sif` + bind -> `rag_local_api.py :8787` |

## 2) gpu6000 端口快照

| 端口 | 监听地址 | 进程 | 说明 |
| --- | --- | --- | --- |
| 8000 | 0.0.0.0 | `uvicorn` | fish yolo app |
| 8001 | 0.0.0.0 | `vllm` | Qwen3-VL-8B-Instruct |
| 8002 | 0.0.0.0 | `python` | fish retrieval app |
| 8003 | 0.0.0.0 | `vllm` | Llama-3.1-8B-Instruct (orchestrator) |
| 8004 | 0.0.0.0 | `uvicorn` | fish fd_app |
| 8005 | 0.0.0.0 | `python` | Wind-Agent API |
| 8501 | 0.0.0.0 | `streamlit` | Wind-Agent UI |
| 8787 | 127.0.0.1 | `python` | Wind RAG unified backend |
| 19530/19529/9091 | `*` | `CGO_SQ` | Milvus 组件端口 |

## 3) Wind-Agent 容器路径说明（2026-04-09 调整）

旧路径 `/share/home/lijiyao/CCCC/wind-agent-offline_20260403.sif` 当前不可用。

Wind-Agent 相关会话已统一改为：

- 镜像：`/share/home/lijiyao/CCCC/apptainer/inforhub.sif`
- 启动参数：`apptainer exec --bind /share/home/lijiyao/CCCC:/share/home/lijiyao/CCCC ...`

这样可以保证容器内能访问 `/share/home/lijiyao/CCCC/Wind-Agent` 代码与数据目录。
