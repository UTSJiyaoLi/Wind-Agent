# Wind-Agent 目录整理说明

最后整理时间：2026-04-02

## 当前顶层目录职责

- `api/`: FastAPI 服务入口与 API 相关代码
- `src/`: RAG 主体实现（retriever/reranker/parser/client 等）
- `scripts/`: 数据处理、检索、评估、运维脚本
- `Data/`: RAG 数据集、embedding、评估集与中间产物
- `Models/`: 本地模型与 reranker 权重
- `docs/`: 使用文档与网页演示文件
- `ui/`: Streamlit 前端
- `storage/`: 任务状态存储
- `wind_data/`: 风资源分析输入与输出
- `artifacts/`: 大体积二进制或分发包

## 本次归档移动

- `README copy.md` -> `docs/archive/README_rag_legacy.md`
- `wind-agent-slides-outline.md` -> `docs/archive/wind-agent-slides-outline.md`
- `wind_analysis_from_matlab.py` -> `scripts/legacy/wind_analysis_from_matlab.py`
- `ollama-linux-arm64.tar.zst` -> `artifacts/ollama/ollama-linux-arm64.tar.zst`
- `sha256sum.txt` -> `artifacts/ollama/sha256sum.txt`

## 说明

- 本次未改动任何 Python 业务代码。
- 根目录保留 `README.md`、`requirements.txt`、`start_frontend.ps1` 作为常用入口。
- `Data/` 与 `Models/` 为既有目录命名，暂不改名以避免路径兼容问题。
