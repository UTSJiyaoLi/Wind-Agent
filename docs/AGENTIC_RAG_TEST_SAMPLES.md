# Agentic RAG 测试样例（可直接复制）

用于 `docs/langchain_generative_ui_v1.html` 的快速回归测试。

## 建议前置配置

- `Backend URL`: `http://127.0.0.1:8787`
- `Mode`: `auto`
- 其余参数保持默认（如需压测可提高 `max_tokens`）

## 1) 反思 + 动态检索触发

**输入：**

```text
请解释一下风电中的尾流损失，并给出常见降低尾流损失的方法
```

**预期：**

- `ui_blocks` 出现 `agentic_trace_timeline`
- 可见 `grade_retrieval -> retry_retrieve`（最多 2 轮）
- 响应中包含 `agentic_grades`

## 2) 问题拆分触发（子问题）

**输入：**

```text
请分别说明风速分布建模方法以及尾流效应评估方法，并给出场址选型建议
```

**预期：**

- 出现 `subquestions` block
- 响应中 `decomposition.triggered = true`
- 最终答案为子问题汇总

## 3) 专业 RAG（可能不重试）

**输入：**

```text
IEC 标准里风资源评估常见指标有哪些？
```

**预期：**

- 走 `rag` 路由
- 出现 `agentic_grades`
- 可能 0~2 次重检索（取决于召回质量）

## 4) 通用问题走直答（不走 RAG）

**输入：**

```text
帮我写一段周报开头，语气专业一点
```

**预期：**

- 路由倾向 `llm_direct`
- 无 RAG 上下文相关块

## 5) 风况工具（wind_agent）

**输入：**

```text
请分析这个文件: /share/home/lijiyao/CCCC/Wind-Agent/wind_data/wind speed(1).xlsx
```

**预期：**

- 路由到 `wind_agent`
- 返回分析结果与图表预览

## 6) 复合追问（再次验证拆分+汇总）

**输入：**

```text
对比 Weibull 拟合和实测分箱统计在年发电量估算上的差异，并说明各自适用场景
```

**预期：**

- 常触发 `subquestions`
- 输出汇总答案，带证据引用
