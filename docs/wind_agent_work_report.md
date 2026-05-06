# InforHub 项目工作汇报说明

## 1. 项目定位

`C:\Infor_hub` 当前这套代码，实质上是一套面向专业领域资料处理和智能分析的系统底座。

从代码能力看，它已经实现的重点不是“通用聊天”，而是下面这条链路：

1. 把专业资料解析成可用数据。
2. 把资料入库成可检索知识库。
3. 用 RAG 和 Agent 判断用户要的是问答还是分析。
4. 对指定场景调用专业分析工具。
5. 把结果整理成文本、结构化数据、图表和地图展示。

如果用于工作汇报，可以把它定义为：

> 一套面向专业信息处理的智能分析平台原型，已经完成知识入库、检索增强、任务路由、专业分析和结果展示的主链路打通。

## 2. 这个项目现在实际干了什么

按当前代码真实能力，项目已经完成了四类核心工作。

### 2.1 专业资料解析和知识库构建

项目已经具备把 PDF 等资料处理成知识库的能力。

对应实现：

- `scripts/parse/parse_mineru_v2.py`
- `scripts/parse/parse_mineru_v2_core.py`
- `scripts/ingest/ingest_winddata_milvus.py`
- `rag/runtime.py`

实际做的事情包括：

- 调用解析流程提取文档内容。
- 将文档切分为更适合检索的小片段。
- 为片段生成 dense / sparse 表示。
- 将结果写入 Milvus。
- 同时维护轻量元数据和完整元数据，便于检索和回溯。

这部分说明系统已经具备“把资料变成可搜索知识资产”的能力。

### 2.2 RAG 检索增强问答

项目已经实现了完整的 RAG 服务层，不是简单的“向量检索 + 大模型拼接回答”，而是带有增强逻辑。

对应实现：

- `rag/service.py`
- `rag/runtime.py`
- `observability/tracer.py`

已实现的关键能力包括：

- 自动模式路由。
- query rewrite。
- 领域扩展。
- 向量检索和 BM25 混合召回。
- rerank 和去重。
- 复杂问题拆分为子问题检索。
- 检索质量评分和答案质量评分。
- 可观测 trace 记录。

这部分本质上承担的是“从已有资料中筛选最相关内容并生成带依据回答”的职责。

### 2.3 Agent 决策和工作流编排

项目已经不是单一问答系统，而是有一套 LangGraph 编排的 Agent 流程。

对应实现：

- `graph/builder.py`
- `graph/nodes/agent.py`
- `graph/workflow_contract.py`
- `graph/tool_registry.py`

当前主流程包含这些节点：

1. `input_preprocess`
2. `domain_router`
3. `mode_router`
4. `policy_gate`
5. `flow_entry`
6. `clarify_node`
7. `fallback_or_escalation`
8. `workflow_planner`
9. `rag_executor`
10. `tool_executor`
11. `answer_synthesizer`

这条链路已经可以做到：

- 识别用户问题类型。
- 判断走 `llm_direct`、`rag` 还是分析工具。
- 检查参数是否完整。
- 必要时生成多步 workflow。
- 汇总中间结果并输出最终答复。

也就是说，当前项目已经具备“任务理解 + 路由 + 执行 + 汇总”的智能体雏形。

### 2.4 专业分析工具落地

当前代码里已经落地了两类专业工具。

#### 风况 / 风资源分析

对应实现：

- `tools/wind_analysis_tool.py`
- `services/wind_analysis_service.py`
- `graph/nodes/wind_analysis.py`
- `schemas/wind_analysis.py`

这部分可以读取 Excel 数据并输出：

- 有效样本统计
- 风向频率分布
- 平均风速统计
- Weibull 拟合结果
- 多张分析图
- 结构化 JSON 结果

测试也覆盖了这条链路：

- `tests/test_wind_analysis_tool.py`

#### 台风概率和地图展示

对应实现：

- `services/typhoon_probability_service.py`
- `services/typhoon_map_service.py`
- `tools/typhoon_probability_tool.py`
- `tools/typhoon_map_tool.py`
- `tests/test_typhoon_probability_service.py`
- `tests/test_typhoon_map_service.py`

这部分可以完成：

- 输入经纬度、半径、时间范围等参数。
- 读取历史统计结果。
- 计算命中概率、年尺度概率等指标。
- 输出地图展示需要的 `map_spec`。
- 生成可用于前端展示的 HTML 结果。

## 3. 这个项目是怎么干的

如果按系统执行顺序讲，当前代码大致分为五步。

### 3.1 资料进入系统

通过 `scripts/parse` 下的解析脚本，把 PDF 等资料解析成结构化文本片段。

### 3.2 资料入库

通过 `scripts/ingest/ingest_winddata_milvus.py` 对文本做 embedding 和索引构建，再写入 Milvus，形成知识库。

### 3.3 用户请求进入服务层

服务层由 `rag/service.py` 负责调度。

这里会先判断用户请求属于哪种模式：

- `llm_direct`
- `rag`
- `wind_agent`

前端在 `apps/web/app/page.tsx` 里已经支持这些模式切换和参数配置。

### 3.4 Agent 判断并执行

如果请求进入 Agent 流程，`graph/builder.py` 和 `graph/nodes/agent.py` 会进一步判断：

- 是普通问答还是专业分析。
- 是否缺少 Excel 路径或台风参数。
- 是否需要直接工具执行。
- 是否需要多步 workflow。

### 3.5 输出结果

最终结果由 `answer_synthesizer` 和前端 `ui_blocks` 机制统一整理输出。

当前前端支持展示：

- 文本回答
- 检索指标
- agentic 轨迹
- JSON 结果
- 图片 gallery
- 地图结果

对应前端主文件：

- `apps/web/app/page.tsx`

## 4. 当前项目和“信息收集器”目标的关系

如果回到“信息收集器”的业务目标，一般包含三层：

1. 收集信息
2. 评估筛选信息
3. 输出给用户

按当前代码看，三层能力的完成度并不完全一样。

### 当前已经比较完整的部分

- 已有资料解析与知识化。
- 检索增强和内容筛选。
- 专业分析和结果输出。
- 前端交互展示。

### 当前还不算完整的部分

- “自动抓取互联网上最新领域动态”这一步，在这份代码里不是主实现。
- “推荐算法”目前主要体现为检索召回、重排、路由和评分，不是独立的资讯推荐引擎。
- “自动生成标准汇报文档”目前有结构化结果和可视化基础，但还没有专门的报告生成模块。

所以更准确的汇报口径应该是：

> 当前项目已经完成了信息处理链路中的中后段能力建设，即资料知识化、智能筛选、专业分析和结果输出；对于“互联网最新动态自动采集”和“标准化报告自动生成”，当前已经具备扩展基础，但还不是这版代码的主落地点。

## 5. 当前项目的主要价值

### 5.1 技术价值

- 已经有知识库，不是裸模型问答。
- 已经有 Agent，不是固定单步调用。
- 已经有工具执行，不是纯文字回答。
- 已经有前端，不是只停留在脚本层。
- 已经有测试和 trace，不是不可维护的 Demo。

### 5.2 业务价值

- 可以把专业资料统一转为可检索资产。
- 可以把用户问题自动分配到合适的处理路径。
- 可以把分析结果整理成用户可读输出。
- 可以继续扩展更多垂直场景工具。

## 6. 汇报时建议怎么说

建议不要把当前项目讲成“已经完成的互联网情报抓取平台”，而应讲成“已经完成核心底座建设的专业智能分析平台”。

可以直接使用下面这段表述：

> 本阶段 InforHub 项目已经完成核心技术底座建设，形成了“资料解析入库 + 检索增强问答 + Agent 智能路由 + 专业分析工具执行 + 前端结果展示”的主链路。系统已经能够将专业资料转化为可检索知识库，并根据用户问题自动选择问答或分析流程，对重点内容进行筛选、整合和输出。当前代码重点验证了专业资料问答、风况分析、台风概率分析和地图展示等能力，说明系统已经具备从信息处理到结果交付的基础闭环。

## 7. 下一步建议

如果下一阶段要更贴近“自动收集最新领域动态，再推荐最有价值内容，最后生成汇报材料”的目标，建议重点补三块。

### 7.1 增加在线采集层

- 增加网页、RSS、行业资讯源采集。
- 增加定时任务和增量抓取。
- 增加去重和来源可信度控制。

### 7.2 增加推荐排序层

- 在现有检索和 rerank 基础上增加内容级推荐排序。
- 引入时间、新鲜度、来源权威度、主题匹配度等特征。
- 形成候选信息池和 Top 内容推送机制。

### 7.3 增加报告生成层

- 将现有回答、图表、指标整合为固定模板。
- 自动输出 Markdown、Word 或 PDF。
- 支持日报、周报、专题简报三类交付格式。

## 8. 结论

`C:\Infor_hub` 当前代码已经完成的核心不是“新闻抓取”，而是“专业资料知识化 + 智能检索 + 智能路由 + 专业分析 + 结果展示”。

如果作为工作汇报，最稳妥的结论是：

> InforHub 当前已经完成了信息处理和智能分析底座的建设，具备把专业资料转成知识库、基于用户需求自动筛选信息、调用专业工具分析并输出结果的能力。下一步在此基础上补齐在线采集、推荐排序和标准化报告生成，就可以更完整地演进为领导需要的信息收集与智能汇报平台。

## 9. 关键代码位置

- 知识库运行时：`rag/runtime.py`
- 检索与服务调度：`rag/service.py`
- Agent 编排入口：`graph/builder.py`
- Agent 主要节点：`graph/nodes/agent.py`
- Workflow 约束：`graph/workflow_contract.py`
- 风况分析节点：`graph/nodes/wind_analysis.py`
- 工具注册：`graph/tool_registry.py`
- 风况分析工具：`tools/wind_analysis_tool.py`
- 台风概率服务：`services/typhoon_probability_service.py`
- 台风地图服务：`services/typhoon_map_service.py`
- 资料解析：`scripts/parse/parse_mineru_v2.py`
- 向量入库：`scripts/ingest/ingest_winddata_milvus.py`
- 可观测性：`observability/tracer.py`
- 前端页面：`apps/web/app/page.tsx`
- 启动脚本：`wind_agent_chatui.cmd`
