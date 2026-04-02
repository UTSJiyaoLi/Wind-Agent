# Wind Resource Agent (LangGraph + StructuredTool)

## 架构布局

- `schemas/`: pydantic 输入输出定义
- `services/`: 风资源核心分析逻辑（Weibull、图表、异常处理）
- `tools/`: LangChain `StructuredTool` 封装
- `orchestration/`: LangGraph 主流程编排
- `storage/`: 任务状态存储与落盘
- `api/`: FastAPI 应用层（异步任务接口）
- `ui/`: Streamlit 用户界面
- `examples/`: 调用示例
- `tests/`: 单元测试

## 核心能力

- 输入固定：Excel 路径，必须包含 `date`、`windSpd`、`windDire`
- 输出固定：结构化 JSON + 图表文件路径
- Weibull 拟合：`scipy.stats.weibull_min.fit(..., floc=0)`
- 风玫瑰速度分箱去重：`[3,7)`, `[7,11)`, `[11,15]`
- 稳健异常处理：缺列、空数据、读取失败、拟合/绘图异常统一结构化返回

## 环境

```powershell
conda activate rag_task
pip install pandas numpy scipy matplotlib pydantic openpyxl pytest langchain-core langgraph fastapi uvicorn streamlit requests
```

## 运行方式

### 1) 直接运行分析

```powershell
conda activate rag_task
python examples/run_analysis_local.py
```

### 2) 运行 LangGraph 主流程

```powershell
conda activate rag_task
python examples/run_langgraph_flow.py
```

### 3) 启动 API

```powershell
conda activate rag_task
uvicorn api.app:app --host 0.0.0.0 --port 8005
```

### 4) 启动 UI

```powershell
conda activate rag_task
streamlit run ui/streamlit_app.py --server.port 8501
```

UI 默认调用 `http://127.0.0.1:8005`。

## API 说明

- `POST /tasks`
  - body: `{"excel_path": "C:\\wind-agent\\wind_data\\wind condition @Akida.xlsx"}`
  - return: `task_id`
- `GET /tasks/{task_id}`
  - return: 状态 `pending/running/success/failed` + 结果

## 远端 vLLM（已启动）

- 远端服务: `gpu6000` 上 `0.0.0.0:8003`
- 本地转发: `127.0.0.1:18003 -> gpu6000:127.0.0.1:8003`
- 本地 API Base: `http://127.0.0.1:18003/v1`

## 测试

```powershell
conda activate rag_task
pytest -q
```
