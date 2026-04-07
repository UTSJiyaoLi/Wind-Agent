# Agentic RAG 合规清单（本地离线版）

本文用于评估当前仓库是否符合 Agentic RAG 关键特征，并给出整改建议与验收标准。

参考依据：
- LangSmith self-hosted 说明（企业能力）：https://docs.langchain.com/langsmith/self-hosted
- LangSmith 产品页：https://www.langchain.com/langsmith

---

## 1) 路由决策（是否检索）

- 状态：`PASS`
- 证据：
  - `rag/service.py` 中 `mode=auto` 实现了规则 + LLM 路由；
  - 当前支持 `rag / wind_agent / llm_direct` 三分流。
- 差距：
  - 路由质量尚未形成离线指标（仅逻辑存在，未评测）。
- 建议：
  - 在本地评测集上统计三分类准确率与误路由分布。
- 验收标准：
  - 至少可输出每类请求命中率与 confusion matrix。

## 2) 反馈回路（重写/重检索）

- 状态：`PARTIAL`
- 证据：
  - `rag/retrieval.py` 已有 query rewrite / domain expansion；
  - 支持多 query candidate 融合。
- 差距：
  - 缺少“检索质量不达标 -> 自动重检索”的显式循环控制。
- 建议：
  - 增加 retrieval grader（如相关性阈值）与最多 N 次重试策略。
- 验收标准：
  - 出现低相关召回时可观察到二次检索路径和终止条件。

## 3) 评估节点（relevance/grounding/usefulness）

- 状态：`FAIL`
- 证据：
  - 目前无在线 grader 节点对答案 groundedness/usefulness 评分。
- 差距：
  - 仅有离线检索指标脚本，未接入请求链路内决策。
- 建议：
  - 在生成后增加轻量 grading（可规则或 LLM）并产出分值。
- 验收标准：
  - 每次回答可输出 `grounding_score/usefulness_score`。

## 4) 图编排与状态可解释

- 状态：`PARTIAL`
- 证据：
  - 已有 LangGraph agent 图和 trace；
  - 但 agent 图内 `rag` 路径仍偏占位，非完整 RAG 节点闭环。
- 差距：
  - 缺少 graph 内完整 `rag_node` 执行与状态回流。
- 建议：
  - 将 `rag` 真正接入图节点，统一状态契约。
- 验收标准：
  - trace 中可见 `intent -> rag_node -> answer_synthesizer` 实际执行链路。

## 5) 终止条件与降级策略

- 状态：`PARTIAL`
- 证据：
  - 有默认模式回退、错误处理与 request 级错误返回。
- 差距：
  - 缺少“重试次数上限、低置信拒答、无证据降级”统一策略。
- 建议：
  - 定义全局 stop policy（max retry、min evidence、fallback response）。
- 验收标准：
  - 边界场景可稳定触发降级而非硬答。

## 6) 可观测性与评测就绪

- 状态：`PASS`（离线）
- 证据：
  - 已接入本地 JSONL tracing（request/route/retrieve/generate）；
  - `/health` 暴露 observability 状态；
  - 预留 LangSmith 兼容 tracer 接口（占位实现，不上报）。
- 差距：
  - 还未执行评测（本轮按要求不测）。
- 建议：
  - 下一步仅接评测脚本读取 JSONL traces 生成分析报表。
- 验收标准：
  - 单次请求可在 trace 文件中追溯完整链路与关键指标。

---

## 总结结论

- 当前系统结论：**部分 Agentic（路由增强 + 检索增强 + 可观测）**。
- 仍未达到“完整闭环 Agentic RAG”：主要缺少在线 grader 与显式反馈回路控制。

