# 远端 CPU/GPU 节点服务清单

更新时间：2026-04-24 09:30 (Asia/Shanghai)
采集方式：`ssh -J lijiyao@172.30.3.166 lijiyao@gpu6000` + `tmux ls` + `tmux list-panes` + `curl /health` + 本地 `Get-NetTCPConnection/Win32_Process`。

## 1) gpu6000 当前会话

| tmux 会话 | 主要职责 | 启动方式摘要 |
| --- | --- | --- |
| `fish-yolo` | 鱼病 YOLO 服务 | `apptainer/yolo_fastapi.sif` -> `uvicorn :8000` |
| `vllm` | Fish VLM/LLM 推理 | `vllm.sif` -> `vllm serve :8001` |
| `fish-retrieval` | Fish 检索服务 | `apptainer/inforhub.sif` -> `uvicorn :8002` |
| `wind-vllm-orch` | Wind Orchestrator vLLM | `vllm.sif` -> `vllm serve :8003` |
| `fish-fdapp` | Fish 聚合应用 | `apptainer/yolo_vllm.sif` -> `uvicorn :8004` |
| `wind-agent-api` | Wind-Agent FastAPI | `inforhub.sif` + bind -> `uvicorn :8005` |
| `wind-rag-unified` | Wind RAG/Agent 统一后端 | `inforhub.sif` + bind -> `rag_local_api.py :8787` |

2026-04-24 运维变更记录：

- 已在不新增 tmux 会话的前提下，原地重启 `wind-agent-api` 与 `wind-rag-unified`。
- 已将 Wind-Agent 的模型分工调整为：
  - `8001 / Qwen3-VL-8B-Instruct`：负责 `llm_direct` 与 `rag`
  - `8003 / Llama-3.1-8B-Instruct`：负责 `workflow_planner` 的 LLM 规划
- 台风固定工作流仍优先走 deterministic plan，不依赖 planner LLM。
- 已按现有可用镜像原地重启鱼病相关 tmux 会话：
  - `fish-yolo` -> `/share/home/lijiyao/CCCC/apptainer/yolo_fastapi.sif`
  - `fish-fdapp` -> `/share/home/lijiyao/CCCC/apptainer/yolo_vllm.sif`
  - `fish-retrieval` -> `/share/home/lijiyao/CCCC/apptainer/inforhub.sif`
- 原 `wind-agent-offline_20260403.sif` 当前不可用，`fish-retrieval` 已改由 `inforhub.sif` 顶替。

## 2) gpu6000 端口快照

| 端口 | 监听地址 | 进程 | 说明 |
| --- | --- | --- | --- |
| 8000 | 0.0.0.0 | `uvicorn` | fish yolo app |
| 8001 | 0.0.0.0 | `vllm` | Qwen3-VL-8B-Instruct (`llm_direct` / `rag`) |
| 8002 | 0.0.0.0 | `python` | fish retrieval app |
| 8003 | 0.0.0.0 | `vllm` | Llama-3.1-8B-Instruct (`planner`) |
| 8004 | 0.0.0.0 | `uvicorn` | fish fd_app |
| 8005 | 0.0.0.0 | `python` | Wind-Agent API |
| 8787 | 127.0.0.1 | `python` | Wind RAG unified backend |
| 19530/19529/9091 | `*` | `CGO_SQ` | Milvus 组件端口 |

## 3) Wind-Agent 当前模型职责

- `wind-rag-unified` (`127.0.0.1:8787`)
  - `--llm-base-url http://127.0.0.1:8001`
  - `--llm-model /share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct`
  - `--planner-base-url http://127.0.0.1:8003`
  - `--planner-model /share/home/lijiyao/CCCC/Models/llms/Llama-3.1-8B-Instruct`
- `wind-agent-api` (`0.0.0.0:8005`)
  - 通过环境变量注入 `PLANNER_LLM_*`，将 planner 指向 `8003 / Llama`
  - 非 planner LLM 路径仍保持 `ORCH/VLLM -> 8001 / Qwen` 默认链路
- 代码层当前生效规则
  - `rag/service.py` 中 `llm_direct` 与 `rag` 继续使用 Qwen
  - `graph/nodes/agent.py` 中 `workflow_planner` 单独使用 planner 配置
  - `answer_synthesizer`、`domain_router`、`mode_router` 仍走默认 orchestrator 配置

## 4) 运行约束

- 当前未新增任何 Wind-Agent 服务会话；仍复用原有：
  - `wind-agent-api`
  - `wind-rag-unified`
  - `vllm`
  - `wind-vllm-orch`
- GPU 分配现状：
  - `8001 / Qwen vLLM` 绑定 `CUDA_VISIBLE_DEVICES=0`
  - `8003 / Llama vLLM` 绑定 `CUDA_VISIBLE_DEVICES=1`
  - `wind-rag-unified` 当前启动脚本显式导出 `CUDA_VISIBLE_DEVICES=0`
- “不要开子进程”的执行口径：
  - 本次发布未新开服务实例，仅对现有 tmux pane 执行 `respawn-pane -k`
  - 请求处理仍在现有 `8001/8003/8787/8005` 服务链路中完成
  
## 5) Wind-Agent 容器路径说明（2026-04-09 调整）

旧路径 `/share/home/lijiyao/CCCC/wind-agent-offline_20260403.sif` 当前不可用。

Wind-Agent 相关会话已统一改为：

- 镜像：`/share/home/lijiyao/CCCC/apptainer/inforhub.sif`
- 启动参数：`apptainer exec --bind /share/home/lijiyao/CCCC:/share/home/lijiyao/CCCC ...`

这样可以保证容器内能访问 `/share/home/lijiyao/CCCC/Wind-Agent` 代码与数据目录。

## 6) 本地前端映射（Windows 开发机）

- 本地 `127.0.0.1:3005` 当前进程链路：
  - `node next dev -p 3005`
  - 父进程命令：`cmd /k ""C:\wind-agent\tmp_start_react_next_chatui.cmd""`
- 结论：当前 3005 ChatUI 是由 `tmp_start_react_next_chatui.cmd` 拉起（该脚本由 `wind_agent_chatui.cmd` 生成并启动）。
- 保留建议：不要删除 `tmp_start_react_next_chatui.cmd`，避免影响现有 3005 服务。
