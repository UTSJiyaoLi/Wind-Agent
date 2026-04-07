# Remote Web UI Runbook v1

## 1. 目标运行方式

- 所有后端服务统一运行在 `gpu6000`。
- 本地只打开 Web UI 静态页面，通过 SSH 端口转发访问远端后端。
- 跳板链路：`local -> lijiyao@172.30.3.166 -> lijiyao@gpu6000`。

## 2. 启动顺序

### Step A: 启动远端统一后端

在本地 Windows 仓库根目录执行：

```powershell
.\scripts\ops\start_remote_rag_backend_gpu6000.cmd
```

该脚本会在 `gpu6000` 上用 `tmux` 启动：
- 会话名：`wind-rag-unified`
- 进程：`apptainer exec ... python scripts/search/rag_local_api.py --port 8787`

### Step B: 启动本地隧道并打开 Web UI

```powershell
.\scripts\ops\start_rag_web_local.cmd
```

该脚本会：
1. 打开隧道窗口（保持不关闭）。
2. 自动打开 `docs/local_rag_web_v3.0.html`。

## 3. Web UI 配置

- `Mode`: `RAG` 或 `Wind Agent Tool`
- `RAG Backend URL`: `http://127.0.0.1:8787`

## 4. 容器策略

### 4.1 优先使用服务器已有 Apptainer 镜像

脚本默认路径：
- `/share/home/lijiyao/CCCC/wind-agent-offline_20260403.sif`

如版本更新，只需修改：
- `scripts/ops/start_remote_rag_backend_gpu6000.cmd` 里的 `REMOTE_SIF`

### 4.2 本地 WSL2 构建（备用）

给定构建目录：
- `\\wsl$\Ubuntu\home\lijiyao\container_build`

在 WSL2 执行：

```bash
cd /mnt/c/wind-agent
bash scripts/ops/build_apptainer_in_wsl2.sh
```

默认输出：
- `/home/lijiyao/container_build/artifacts/containers/wind-agent-offline_20260403.tar`

## 5. 日常维护规范

- 新增脚本时同步补文档和用途说明。
- 定期清理无用产物：`__pycache__`、`*.pyc`、过期日志、临时调试脚本。
- 保留运行必需脚本与当前主路径（Web UI + 远端后端）。
