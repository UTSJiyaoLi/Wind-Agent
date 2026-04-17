# Wind-Agent 项目架构与功能综述

## 1. 项目定位

Wind-Agent 是一个面向风能与台风分析的混合 AI 系统，融合了：

- RAG（检索增强生成）问答能力
- 基于 LangGraph 的代理式工作流编排
- 专用风资源分析与台风概率/地图工具
- 面向 Excel 数据的批量分析与后台任务管理

该系统既支持“文档问答与知识检索”，也支持“工具调用驱动的专业分析”。

## 2. 核心功能

### 2.1 RAG 问答

- 提供 `POST /api/chat`、`POST /agent/chat` 等接口
- 支持 `mode=llm_direct`、`mode=rag`、`mode=wind_agent`
- 通过统一后端调用检索服务，按领域上下文生成带引用的回答

### 2.2 Agent 工作流

- 使用 `LangGraph` 进行统一流程编排
- 6 个核心节点：
  1. `input_preprocess`
  2. `intent_router`
  3. `workflow_planner`
  4. `rag_executor`
  5. `tool_executor`
  6. `answer_synthesizer`
- 支持混合执行：RAG 检索、工具调用、LLM 中间总结
- 支持读写统一 `state`，记录 `trace` 和 `warnings`

### 2.3 风资源分析

- 提供批量 Excel 分析能力
- 支持 `POST /tasks` 后台执行风资源分析
- 输入为 Excel 文件，包含 `date`、`windSpd`、`windDire` 等字段
- 输出包括分析结果、统计指标、图表路径等结构化内容

### 2.4 台风概率与地图分析

- 提供 `POST /typhoon/probability` 专用接口
- 支持台风概率分析与地图可视化工具组合
- 自动解析用户请求中的台风参数：纬度、经度、半径、阈值、时间范围、月份
- 支持 `analyze_typhoon_probability` 与 `analyze_typhoon_map` 工具链

## 3. 系统架构

### 3.1 接口层

- 入口文件：`api/app.py`
- 提供健康检查、任务管理、Agent 对话与台风概率接口
- 将请求转发到：
  - `graph.builder.run_wind_agent_flow`
  - `graph.builder.run_wind_analysis_flow`
  - `services.typhoon_probability_service.run_typhoon_probability`

### 3.2 统一后端层

- 统一聊天服务入口：`scripts/search/rag_local_api.py`
- 聚合多种模式请求
- 提供本地 Web UI 后端能力和跨模式调度

### 3.3 RAG 检索层

- 主要实现文件：`rag/retrieval.py`
- 核心能力：
  - 查询改写（启发式 + LLM）
  - 领域扩展规则
  - 稀疏检索与向量检索融合
  - 去重与重排
  - 检索质量评分与置信度估计
- 通过请求外部检索模块 `scripts/search/search.py` 实现实际检索逻辑

### 3.4 Agent 工作流层

- 编排入口：`graph/builder.py`
- Agent 流程节点组合：
  - `graph/nodes/agent.py`
  - `graph/nodes/wind_analysis.py`
- 状态模型：`graph/state.py`
- 工具注册：`graph/tool_registry.py`
- 流程约定与默认计划：`graph/workflow_contract.py`

### 3.5 工具与服务层

- 工具模块：
  - `tools/wind_analysis_tool.py`
  - `tools/typhoon_probability_tool.py`
  - `tools/typhoon_map_tool.py`
- 业务服务模块：
  - `services/wind_analysis_service.py`
  - `services/typhoon_probability_service.py`
  - `services/typhoon_map_service.py`
- 工具与服务分离，保持业务逻辑可复用

### 3.6 存储与可观测层

- 任务存储：`storage/task_store.py`
- 可观察性：`observability/tracer.py`
- 本地 JSONL tracing、LangSmith 上报选项
- 运行时配置通过环境变量控制

## 4. 关键技术点

### 4.1 混合 RAG + 工具代理体系

- 系统不是单一问答系统，而是结合“知识检索”和“工具执行”的混合型 agent
- 意图路由与工作流规划使用 LLM + 规则混合策略
- 台风类请求设置确定性 guardrail，强制走工具/流程路径

### 4.2 自然语言到执行计划转换

- `intent_router` 负责将用户请求分类为 `rag`、`tool`、`workflow`
- `workflow_planner` 生成可执行步序，包括 `rag`、`tool`、`llm`
- 通过 `normalize_workflow_plan` 校验并回退到默认计划

### 4.3 结构化工具注册与统一执行

- `ToolRegistry` 维护工具元信息与输入 schema
- 通过 `execute(name, payload)` 统一调用工具
- 支持 `timeout_seconds`、`max_retries`、`idempotent` 等元数据

### 4.4 Excel 文件路径自动解析

- 支持从用户文本中提取 Windows 路径、相对路径、目录名称
- 支持文件夹展开为批量 Excel 分析
- 支持在当前工作目录中模糊匹配目录名称

### 4.5 台风概率分析算法实现

- 基于历史 BST 台风轨迹数据解析
- 提供空间几何计算：
  - 大圆距离 (haversine)
  - 方向角计算
  - 椭圆风圈判断
  - 点在多边形内判断
- 支持按年份、月份、阈值、区域聚合事件概率

## 5. 典型请求与数据流

### 5.1 RAG 文档问答

1. 用户发送 `mode=rag` 请求
2. 后端调用 RAG 服务逻辑
3. 检索层执行查询改写、检索、去重、重排
4. LLM 基于检索上下文生成回答
5. 返回带引用的结果

### 5.2 Agent 工具分析

1. 用户发送 `mode=wind_agent` 请求或 `/agent/chat`
2. `input_preprocess` 解析请求与 Excel 数据路径
3. `intent_router` 判定为 `tool` 或 `workflow`
4. `workflow_planner` 构建执行计划
5. `tool_executor` 调用工具并记录 `workflow_results`
6. `answer_synthesizer` 生成最终分析结论

### 5.3 台风概率 + 地图流程

1. 用户请求中包含台风参数与“地图/可视化”意图
2. 规划器构建复合步骤：概率分析 -> 地图可视化 -> LLM 汇总
3. `analyze_typhoon_probability` 运行历史轨迹概率计算
4. `analyze_typhoon_map` 生成可视化输出文件
5. 最终返回分析结论与结果路径

## 6. 运行与部署

### 6.1 核心运行方式

- 本地 FastAPI：`api/app.py`
- 统一后端：`scripts/search/rag_local_api.py`
- 本地 Web UI：`docs/local_rag_web_v3.0.html`
- 远端容器/Apptainer：`scripts/ops/` 启动脚本

### 6.2 环境与配置

- 可通过 `.env.local` / `.env.server` 管理配置
- 观察性配置：`OBS_BACKEND=jsonl`、`OBS_ENABLED=true`、`OBS_TRACE_DIR=storage/traces`
- LLM 配置环境变量：`ORCH_LLM_BASE_URL`、`ORCH_LLM_MODEL`、`ORCH_LLM_API_KEY`
- RAG API 地址：`AGENT_RAG_API_URL`

## 7. 专利价值提示

### 7.1 组合创新

- 将风力发电与台风风险分析领域的专用工具，集成到一个可由自然语言驱动的混合 agent 平台
- 混合 RAG + 结构化工具执行的统一流程，可覆盖专业分析与文档问答两类需求

### 7.2 关键可专利点

- 基于自然语言请求自动解析 Excel 路径与文件夹批量分析的能力
- 台风概率分析与地图可视化工作流的自动规划与执行
- 由 LLM 驱动的 workflow planning 结合 deterministic guardrail 的混合路由策略
- 统一工具注册与结构化实现，支持多种专业分析工具的扩展

## 8. 参考关键文件

- `api/app.py`
- `scripts/search/rag_local_api.py`
- `rag/service.py`
- `rag/retrieval.py`
- `graph/builder.py`
- `graph/nodes/agent.py`
- `graph/nodes/wind_analysis.py`
- `graph/tool_registry.py`
- `graph/workflow_contract.py`
- `tools/wind_analysis_tool.py`
- `tools/typhoon_probability_tool.py`
- `tools/typhoon_map_tool.py`
- `services/wind_analysis_service.py`
- `services/typhoon_probability_service.py`
- `storage/task_store.py`
- `observability/tracer.py`
