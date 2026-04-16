# Wind-Agent RAG 系统工作流（简化版）

这张图聚焦 RAG 主链路和模块协作关系，便于理解系统如何从请求到答案。

```mermaid
flowchart TD
    U[用户/前端请求] --> A[scripts/search/rag_local_api.py\nHTTP入口]
    A --> B[rag/service.py\nhandle_chat_request 调度]

    B --> C{mode 路由}
    C -->|rag| D[RAG 主流程]
    C -->|wind_agent| WA[调用 agent 流程\nrun_wind_agent_flow]
    C -->|llm_direct| LD[直接调用 LLM]

    subgraph RAG[RAG 主流程]
      D --> D1[agentic 检索控制\n_run_agentic_retrieve]
      D1 --> D2[rag/retrieval.py\nretrieve_contexts]
      D2 --> D3[Embedding + Milvus 混合检索\nDense/BGE + BM25]
      D3 --> D4[融合/去重/可选重排\n上下文编排]
      D4 --> D5[构建 contexts/citations/media\nretrieval_metrics]
      D5 --> D6[调用 LLM 生成答案]
      D6 --> D7[答案评分与引用附录\n组装 ui_blocks]
    end

    WA --> Z[统一 JSON 响应]
    LD --> Z
    D7 --> Z

    subgraph MODULES[关键模块关系]
      M1[rag_local_api.py\n负责 HTTP 收发/CORS/健康检查]
      M2[rag/service.py\n负责路由、编排、响应组装]
      M3[rag/retrieval.py\n负责检索、融合、上下文构建]
      M4[observability/tracer.py\n负责 trace/span/event]
      M5[Milvus + Embedding/Reranker\n向量检索基础设施]
      M1 --> M2 --> M3
      M2 --> M4
      M3 --> M5
    end
```

## RAG 采用的关键技术

- `Hybrid Retrieval`：向量检索 + 稀疏检索混合召回（Dense/BGE + BM25），并使用 RRF 融合候选。
- `Query Augmentation`：查询改写（启发式/LLM）与领域扩展（术语同义扩展），提升召回覆盖。
- `Agentic Retrieval Retry`：基于检索评分自动重试，动态调大 `top_k`、改写变体数并启用领域扩展。
- `Context Orchestration`：按问题意图（text/visual/formula）做上下文预算分配，提高提示词上下文质量。
- `Rerank + Dedup`：按文档去重、按候选重排，控制上下文噪声与冗余。
- `Grounded Answering`：答案后附 CTX 引用索引，支持 citations/media_refs/preview_images。
- `Answer Grading`：规则评分 + 可选 LLM 评分（grounding/usefulness/confidence）。
- `Compound Query Decomposition`：复杂问题拆分为子问题检索并汇总，降低单次检索失败风险。
- `Observability`：全链路 trace/span/event，便于回放与性能分析。

## 一句话理解

- `rag_local_api.py` 是入口。
- `rag/service.py` 决定走哪种模式，并在 `rag` 模式下调 `retrieve_contexts` 做检索增强。
- `rag/retrieval.py` 负责把“查询”变成“高质量上下文”，最后再由 LLM 生成可引用答案。
