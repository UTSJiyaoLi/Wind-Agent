# Wind Agent

A lightweight Next.js Chat UI launcher for connecting to a remote backend through SSH tunnel.

## English

### What This Repository Provides

- Frontend project: `apps/web`
- Unified launcher: `wind_agent_chatui.cmd`

### Prerequisites

- Windows + `cmd` / PowerShell
- Node.js (`npm.cmd` in PATH)
- `ssh` (OpenSSH) or `plink` in PATH

### Start

Double-click or run:

```bat
C:\wind-agent\wind_agent_chatui.cmd
```

The script will:

1. Start SSH tunnel (unless `SKIP_TUNNEL=1`)
2. Start Next.js frontend
3. Open browser once

### Main Environment Variables

- `UI_PORT` (default: `3005`)
- `LOCAL_PORT` (default: `8787`)
- `REMOTE_HOST` (default: `127.0.0.1`)
- `REMOTE_PORT` (default: `8787`)
- `SKIP_TUNNEL=1` to skip tunnel

### Notes

- Keep tunnel window open while using the UI.
- If ports conflict, change `UI_PORT` / `LOCAL_PORT`.

---

## 中文说明

这个仓库用于启动 Next.js 前端, 通过 SSH 隧道连接远程后端。

### 仓库内容

- 前端工程: `apps/web`
- 统一启动脚本: `wind_agent_chatui.cmd`

### 运行前准备

- Windows 系统, 支持 cmd 或 PowerShell
- 已安装 Node.js (`npm.cmd` 在 PATH 中)
- 已安装 OpenSSH 或 plink

### 启动方式

可以双击脚本, 也可以命令行运行:

```bat
C:\wind-agent\wind_agent_chatui.cmd
```

脚本会自动执行:

1. 建立 SSH 隧道 (如果未设置 `SKIP_TUNNEL=1`)
2. 启动 Next.js 前端
3. 只打开一次浏览器页面

### 常用环境变量

- `UI_PORT` (默认 `3005`)
- `LOCAL_PORT` (默认 `8787`)
- `REMOTE_HOST` (默认 `127.0.0.1`)
- `REMOTE_PORT` (默认 `8787`)
- `SKIP_TUNNEL=1`: 跳过隧道, 仅启动前端

### 说明

- 使用过程中请保持隧道窗口不要关闭。
- 如果端口冲突, 请修改 `UI_PORT` 或 `LOCAL_PORT`。
