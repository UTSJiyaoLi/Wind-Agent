# 风电文档 RAG 检索实验项目

## 1. 项目简介

这是一个围绕风电领域文档构建的 RAG 检索实验项目，核心流程包括：

1. 使用 MinerU 解析 PDF 并进行分块（parent/child chunk）
2. 生成标准 JSONL 文本块数据
3. 使用 BGE-M3 生成向量并写入 Milvus（Dense + Sparse + BM25）
4. 进行混合检索、去重、重排（Reranker）
5. 通过 Recall 指标和 RAGAS 进行检索质量评估

本 README 聚焦当前更直接可复现的脚本化流程（已按功能拆分到 `scripts/` 下）。

---

## 2. 主要能力

- PDF -> 结构化文本块（支持批量）
- Parent/Child 分层分块与噪声清洗
- Milvus 混合检索（Dense + BGE Sparse + BM25）
- 分支融合（RRF）、文档去重、可选 BGE Reranker
- 检索评估（`evaluate_recall_quality.py` / `ragas_retrieval_eval.py`）

---

## 3. 项目结构

```text
.
├─Data/                                 # 数据目录（示例：embedding、原始文档等）
├─Models/                               # 本地模型目录（示例：bge-m3）
├─scripts/
│  ├─parse/                             # 解析与分块脚本
│  ├─ingest/                            # 入库脚本
│  ├─search/                            # 检索脚本（含 reranker / smoke test / LangChain RAG）
│  ├─eval/                              # 评估脚本
│  └─pipeline/                          # 一键流程与统一配置逻辑
├─configs/
│  └─pipeline_config.example.jsonc      # 统一配置模板
├─docs/
│  ├─workflow.md
│  └─workflow_detailed.md
├─Data/
│  └─eval/                              # 评测集与评测结果
├─requirements.txt                      # 锁定版本依赖
└─scripts/ops/                          # Milvus 启停与进度脚本
```

---

## 4. 环境要求

建议 Python 3.10+。

### 4.1 Python 依赖（锁定版本）

```bash
pip install -r requirements.txt
```

`requirements.txt` 已按项目脚本使用的核心依赖锁定版本。

### 4.2 外部依赖

- Milvus（本地或远程）
- MinerU CLI（命令名需为 `mineru` 或 `magic-pdf`）
- 可选：Apptainer（如果使用仓库内 `.sh` 脚本启动 Milvus）

---

## 5. 快速开始

> 注意：多个脚本里带有历史默认路径（如 `/share/home/...` 或 `C:\\codex_coding\\...`），实际运行时请用命令行参数覆盖。

### 5.1 统一配置（推荐）

先基于模板创建自己的配置文件（PowerShell）：

```powershell
Copy-Item .\configs\pipeline_config.example.jsonc .\pipeline_config.json
```

然后在各脚本里通过 `--config` 使用（CLI 参数优先级高于配置文件）。

### 5.2 解析 PDF 为 JSONL（单文件）

```bash
python scripts/parse/parse_mineru_v2.py \
  --config ./pipeline_config.json \
  --pdf-path ./Data/your.pdf \
  --asset-dir ./Data/embedding/mineru_assets \
  --output-jsonl ./Data/embedding/your_chunks.jsonl \
  --mineru-backend pipeline \
  --mineru-method auto
```

### 5.3 批量解析 PDF

```bash
python scripts/parse/parse_mineru_v2_batch.py \
  --config ./pipeline_config.json \
  --input-dir ./Data/raw_pdfs \
  --output-dir ./Data/embedding \
  --asset-dir ./Data/embedding/mineru_assets \
  --output-name winddata_en_all.jsonl \
  --pattern "DOC_*__en__*.pdf"
```

### 5.4 入库 Milvus

```bash
python scripts/ingest/ingest_winddata_milvus.py \
  --config ./pipeline_config.json \
  --jsonl-path ./Data/embedding/winddata_en_all.jsonl \
  --collection-name winddata_bge_m3_bm25 \
  --uri http://127.0.0.1:19530 \
  --model-path ./Models/bge-m3 \
  --device cuda \
  --drop-old
```

### 5.5 检索测试

```bash
python scripts/search/search.py \
  --config ./pipeline_config.json \
  --collection winddata_bge_m3_bm25 \
  --uri http://127.0.0.1:19530 \
  --model-path ./Models/bge-m3 \
  --query "wind turbine wake model and wind farm planning" \
  --use-reranker \
  --reranker-model-path ./Models/BAAI/bge-reranker-v2-m3
```

### 5.6 检索质量评估

```bash
python scripts/eval/evaluate_recall_quality.py \
  --config ./pipeline_config.json \
  --collection winddata_bge_m3_bm25 \
  --uri http://127.0.0.1:19530 \
  --model-path ./Models/bge-m3 \
  --evalset ./Data/eval/ragas_evalset_weak.jsonl \
  --output ./Data/eval/recall_quality_report.json \
  --use-reranker
```

或：

```bash
python scripts/eval/ragas_retrieval_eval.py \
  --config ./pipeline_config.json \
  --collection winddata_bge_m3_bm25 \
  --uri http://127.0.0.1:19530 \
  --model-path ./Models/bge-m3 \
  --evalset ./Data/eval/ragas_evalset_weak.jsonl \
  --output ./Data/eval/ragas_eval_result.json \
  --use-reranker
```

### 5.7 一键端到端执行

```bash
python scripts/pipeline/run_pipeline.py --config ./pipeline_config.json
```

常用参数：

- `--parse-mode single|batch`
- `--eval-script recall|ragas`
- `--skip-parse --skip-ingest --skip-search --skip-eval`

### 5.8 LangChain + Milvus + vLLM 生成回答

新增脚本：`scripts/search/rag_langchain.py`  
检索阶段复用现有 Milvus 混合检索管线，生成阶段通过 LangChain 调用 vLLM 的 OpenAI 兼容接口。

```bash
python scripts/search/rag_langchain.py \
  --config ./pipeline_config.json \
  --collection winddata_bge_m3_bm25 \
  --uri http://127.0.0.1:19530 \
  --model-path ./Models/bge-m3 \
  --query "wind turbine wake model and wind farm planning" \
  --llm-base-url http://127.0.0.1:8001 \
  --llm-model /share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct \
  --llm-api-key EMPTY \
  --save-answer-json ./Data/embedding/rag_answer.json
```

可选参数：

- `--use-reranker --reranker-model-path ./Models/BAAI/bge-reranker-v2-m3`
- `--top-k 4 --llm-context-chars 700`
- `--llm-temperature 0.2 --llm-max-tokens 768`

### 5.9 本地可双击打开的 Web（已接入 RAG）

页面文件：`docs/local_rag_web.html`

特点：

- 可直接双击打开（无需启动本地后端）
- 提供 `LLM Direct`（直连 vLLM）和 `RAG`（调用本地后端 `/api/chat`）
- 内置统一协议对象：`mode/provider/model/messages/generation_config/retrieval_config`
- 可查看 RAG 返回的 `citations`（文件名/地址/页码/chunk）、`media_refs`（表格/图片字段）、`contexts` 与 `retrieval_metrics`

先建立 SSH 隧道（示例，分别转发 vLLM 与 Milvus）：

```bash
ssh -L 9001:127.0.0.1:8001 -J lijiyao@172.30.3.166 lijiyao@gpu6000
ssh -L 19530:127.0.0.1:19530 -J lijiyao@172.30.3.166 lijiyao@gpu6000
```

启动本地 RAG API（建议在 `conda rag_task` 环境中）：

```bash
python scripts/search/rag_local_api.py \
  --host 127.0.0.1 \
  --port 8787 \
  --uri http://127.0.0.1:19530 \
  --collection winddata_bge_m3_bm25 \
  --model-path ./Models/bge-m3 \
  --llm-base-url http://127.0.0.1:9001 \
  --llm-model /share/home/lijiyao/CCCC/Models/vlms/Qwen3-VL-8B-Instruct
```

可选：若要从 `full_metadata` 中提取更完整的文件/图片/表格字段，可追加：

```bash
  --hydrate-full-metadata \
  --full-metadata-jsonl ./Data/embedding/full_metadata.jsonl \
  --full-metadata-idx ./Data/embedding/full_metadata.idx.json
```

最后双击打开 `docs/local_rag_web.html`：

- `LLM Base URL` 填 `http://127.0.0.1:9001`
- `RAG Backend URL` 填 `http://127.0.0.1:8787`
- `Mode` 选 `RAG` 即可走 Milvus 检索 + vLLM 生成

---

## 6. 常见问题

### Q1. 报错 `MinerU executable not found`

请先确保 `mineru` 或 `magic-pdf` 命令在 `PATH` 中可执行。

### Q2. CUDA 不可用

将 `--device cuda` 改为 `--device cpu`（速度会下降）。

### Q3. Milvus 无法连接

确认 `--uri` 与 Milvus 实际地址一致，且服务已启动。

### Q4. `retrieval_smoke_test.py` 是否在主流程中必跑

不是。主流程是 `parse -> ingest -> search -> eval`。  
`retrieval_smoke_test.py` 只是用于连通性与快速排障，不在 `run_pipeline.py` 的默认链路中。

---

## 7. 本次已实现

- 已补充 `requirements.txt` 并锁定核心依赖版本
- 已增加端到端一键脚本 `scripts/pipeline/run_pipeline.py`（parse -> ingest -> search -> eval）
- 已为脚本增加统一配置管理（`scripts/pipeline/script_config.py` + `--config`）
