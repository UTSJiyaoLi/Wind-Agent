# 远端 CPU/GPU 节点服务清单

更新时间：2026-04-02 10:24 (Asia/Shanghai)
采集方式：从 `lijiyao` 跳板机批量 SSH 到 `cpu/gpu` 节点，采集 `tmux` 与常见 API 端口监听。

## 1) 节点范围

来自 `lijiyao` 主机 `/etc/hosts` 与可登录探测：

- GPU：`gpu1` `gpu2` `gpu3` `gpu4` `gpu5880` `gpu6000`
- CPU：`cpu1` ~ `cpu16`

共 22 台节点，全部可登录（用户 `lijiyao`）。

## 2) 总览

| 节点 | 登录状态 | tmux 会话数 | API/服务端口状态 |
| --- | --- | --- | --- |
| gpu6000 | OK | 5 | 有运行服务 |
| gpu5880 | OK | 0 | 无监听的目标 API 端口 |
| gpu1 | OK | 0 | 无监听的目标 API 端口 |
| gpu2 | OK | 0 | 无监听的目标 API 端口 |
| gpu3 | OK | 0 | 无监听的目标 API 端口 |
| gpu4 | OK | 0 | 无监听的目标 API 端口 |
| cpu1 | OK | 0 | 无监听的目标 API 端口 |
| cpu2 | OK | 0 | 无监听的目标 API 端口 |
| cpu3 | OK | 0 | 无监听的目标 API 端口 |
| cpu4 | OK | 0 | 无监听的目标 API 端口 |
| cpu5 | OK | 0 | 无监听的目标 API 端口 |
| cpu6 | OK | 0 | 无监听的目标 API 端口 |
| cpu7 | OK | 0 | 无监听的目标 API 端口 |
| cpu8 | OK | 0 | 无监听的目标 API 端口 |
| cpu9 | OK | 0 | 无监听的目标 API 端口 |
| cpu10 | OK | 0 | 无监听的目标 API 端口 |
| cpu11 | OK | 0 | 无监听的目标 API 端口 |
| cpu12 | OK | 0 | 无监听的目标 API 端口 |
| cpu13 | OK | 0 | 无监听的目标 API 端口 |
| cpu14 | OK | 0 | 无监听的目标 API 端口 |
| cpu15 | OK | 0 | 无监听的目标 API 端口 |
| cpu16 | OK | 0 | 无监听的目标 API 端口 |

## 3) gpu6000 详细端口映射

### 3.1 tmux 会话

- `fdapp`
- `milvus`
- `vllm`
- `wind-vllm-g1`
- `yolo`

### 3.2 API/服务端口

| 端口 | 监听地址 | 进程 | 说明 |
| --- | --- | --- | --- |
| 8787 | 127.0.0.1 | `python` (`rag_local_api.py`) | RAG 本地 API（仅本机可访问） |
| 8000 | 0.0.0.0 | `uvicorn` | yolo_fastapi 服务 |
| 8001 | 0.0.0.0 | `vllm` | vLLM（Qwen3-VL-8B-Instruct） |
| 8002 | 0.0.0.0 | `uvicorn` | retrieval_app |
| 8003 | 0.0.0.0 | `vllm` | vLLM（Llama-3.1-8B-Instruct，旧实例） |
| 8004 | 0.0.0.0 | `vllm` | vLLM（Llama-3.1-8B-Instruct，GPU1 新实例） |
| 9000 | 0.0.0.0 | `uvicorn` | fd_app_test |
| 9091 | * | `CGO_SQ` | Milvus 组件端口 |
| 19529 | * | `CGO_SQ` | Milvus 组件端口 |
| 19530 | * | `CGO_SQ` | Milvus 主端口 |
| 2379/2380 | * / 127.0.0.1 | `CGO_SQ` | etcd 相关端口 |

## 4) 当前无服务节点

以下节点已可登录，但未发现 tmux 会话，且未发现目标 API 端口监听：

- `gpu5880`, `gpu1`, `gpu2`, `gpu3`, `gpu4`
- `cpu1`~`cpu16`

## 5) 补充：非 CPU/GPU 节点检查结果

| 主机 | 状态 | 备注 |
| --- | --- | --- |
| lijiyao (172.30.3.166) | 可登录 | 有 tmux (`0`,`1`,`2`)；检测到部分监听端口（如 8005、3000 等） |
| dgx-spark (172.30.2.53) | 直连超时 | 直接 SSH 超时 |
| ubuntu-server (120.48.194.50) | 登录前失败 | 本地 `known_hosts` 指纹冲突（Host key changed） |

## 6) 备注

- 本清单的“API/服务端口”筛选范围：`8000/8001/8002/8003/8004/8787/8788/9000/9001/19530/19529/9091/8501/8502/3000/8080`。
- 若你要，我可以在下一步生成一个“持续巡检脚本”（一条命令自动刷新这份文档）。
