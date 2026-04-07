# Wind Agent 调整方案 v1

## 第 0 章：当前已完成工作盘点
- 已有风资源分析工具链：`schema + service + tool`。
- 已有 LangGraph 基础编排：请求解析、参数校验、工具调用、总结。
- 已有 FastAPI 任务接口与 Agent 聊天接口。
- 已有统一 RAG/LLM/Agent 网关雏形（`/api/chat` 多 mode）。
- 已有前端与部署链路（Web UI、Docker、远端转发脚本）。

## 第 1 章：与 structure.md 的核心差距
- 当前服务层“双入口并存”（FastAPI 一套、`rag_local_api.py` 一套），边界不统一。
- LangGraph 仍以单工具链路为主，缺少完整 `rag/tool/workflow` 三路节点。
- 缺少统一 AgentState 契约（尤其 `rag_result/workflow_plan/workflow_results`）。
- 意图识别、工具选择、总结逻辑耦合在单文件。
- 存在中文乱码字符串，影响提示词与测试稳定性。

## 第 2 章：编排层重构（最高优先级）
- 拆分 `orchestration/langgraph_flow.py` 为：
  - `graph/state.py`
  - `graph/nodes/*`
  - `graph/builder.py`
- MVP 节点链路：
  - `input_preprocess -> intent_router -> (rag_node/tool_node/workflow_node) -> answer_synthesizer`
- `intent_router` 先用“规则 + LLM 兜底”。
- `workflow_node` 第一版只做 2-3 步轻量计划执行。

## 第 3 章：服务层统一（高优先级）
- 对外统一 FastAPI 入口；`rag_local_api.py` 逐步下沉为内部 service。
- 主入口建议统一为 `POST /api/chat`：
  - `mode=llm_direct`
  - `mode=rag`
  - `mode=wind_agent`
  - `mode=workflow`
- `POST /agent/chat` 保留兼容，但内部转发到同一编排服务。
- 增加 `session_id` 与上传文件流程，减少“文本中硬编码文件路径”依赖。

## 第 4 章：RAG 与 Agent 融合（高优先级）
- 把 `rag_local_api.py` 的检索与上下文拼装抽到 `rag/service.py`。
- 编排层只决定“是否调用 RAG”，不耦合 Milvus 实现细节。
- 统一引用输出字段：`citations/media_refs/retrieval_metrics`。
- 修复 RAG prompt 与测试中的乱码文本。

## 第 5 章：工具层标准化（中优先级）
- 新增 `tools/registry.py` 做工具注册中心。
- `tool_selector_node` 独立，先规则路由，后续可切 LLM 工具选择器。
- 工具层保持结构化 JSON 输出，不在工具层生成自然语言。

## 第 6 章：状态与会话治理（中优先级）
- 落地统一 `AgentState`（建议字段）：
  - `user_query/session_id/file_path`
  - `intent/intent_confidence`
  - `retrieved_context/rag_result`
  - `selected_tool/tool_input/tool_result`
  - `workflow_plan/workflow_results`
  - `final_answer/warnings`
- 任务与 trace 持久化按 session 维度组织。
- 严格区分 `error` 与 `warnings` 的语义与传播。

## 第 7 章：测试与质量保障（中优先级）
- 补齐三类测试：
  - `intent_router` 单测
  - `/api/chat` 集成测试
  - RAG mock 测试
- 回归场景：
  - 分析意图但无路径
  - 路径不存在
  - RAG 无召回
  - workflow 中途失败
- 统一 UTF-8 编码，消除乱码断言与提示词风险。

## 第 8 章：工程卫生与发布治理（中优先级）
- 清理 `__pycache__/*.pyc` 与不应跟踪的临时产物。
- README 重组为：开发、部署、API、架构四段。
- 配置集中到 `configs/`，减少参数散落。

## 第 9 章：分阶段落地计划（建议两周）
1. 第 1 周：编排层拆分 + FastAPI 统一入口 + AgentState 定稿。
2. 第 2 周：RAG 抽服务 + 工具注册中心 + 测试补齐 + 编码清理。
3. 第 2 周末：冻结协议，更新前端调用与 README。

---

## 附录 A：代码改造对照清单（按文件）

### A1. 首批新增文件
- `graph/state.py`
- `graph/builder.py`
- `graph/nodes/input_preprocess.py`
- `graph/nodes/intent_router.py`
- `graph/nodes/rag_node.py`
- `graph/nodes/tool_selector.py`
- `graph/nodes/tool_executor.py`
- `graph/nodes/workflow_node.py`
- `graph/nodes/answer_synthesizer.py`
- `tools/registry.py`
- `rag/service.py`
- `rag/runtime.py`
- `rag/retrieval.py`

### A2. 首批修改文件
- `api/app.py`：统一调用新 `graph/builder.py`。
- `orchestration/langgraph_flow.py`：保留兼容壳，内部转调新 graph（后续可删除）。
- `scripts/search/rag_local_api.py`：逐步剥离检索逻辑到 `rag/service.py`。
- `schemas/api.py`：扩展统一 chat 协议与 response 字段。
- `tests/test_agent_flow.py`：迁移到新节点链路并修复乱码。
- `README.md`：更新架构图与调用路径。

### A3. 接口过渡策略
1. 保留旧接口，不中断调用方。
2. 新代码走新 graph。
3. 旧实现仅做兼容转发。
4. 测试通过后再删除旧路径。

### A4. 每次提交建议粒度
1. 只拆目录与 state，不改行为。
2. 再接入 `intent_router + tool_node`。
3. 再接入 `rag_node`。
4. 最后接入 `workflow_node` 和统一 `answer_synthesizer`。
