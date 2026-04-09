# Wind-Agent Structure

更新时间：2026-04-09

## 1) 一句话说明

Wind-Agent 用一个 `POST /agent/chat` 入口，自动在 `RAG / Tool / Workflow` 三种模式中选择，并返回可追踪结果。

## 2) 核心模块

- API：`api/app.py`
- 编排：`graph/builder.py`
- 节点：`graph/nodes/agent.py`
- 状态：`graph/state.py`
- 工具：`tools/wind_analysis_tool.py`
- RAG 后端：`http://127.0.0.1:8787/api/chat`

## 3) LangGraph 流程图（当前实现）

```mermaid
flowchart TB

  %% -----------------------------
  %% Layer 1: Entry
  %% -----------------------------
  subgraph L1[Entry Layer]
    U[User / UI Request]
    H1[excel_path hint optional]
    API[FastAPI POST /agent/chat]
  end

  U --> API
  H1 --> API

  %% -----------------------------
  %% Layer 2: LangGraph Core
  %% -----------------------------
  subgraph L2[LangGraph Core]
    S0[[START]]
    N1[input_preprocess]
    N2[intent_router]
    N3[workflow_planner]
    N4[rag_executor]
    N5[tool_executor]
    N6[answer_synthesizer]
    S1[[END]]
  end

  API --> S0 --> N1 --> N2 --> N3 --> N4 --> N5 --> N6 --> S1

  %% -----------------------------
  %% Layer 3: State
  %% -----------------------------
  subgraph L3[State (AgentFlowState)]
    ST1[(user_query / session_id)]
    ST2[(file_path / file_paths / data_folder)]
    ST3[(intent / intent_confidence)]
    ST4[(workflow_plan / workflow_results)]
    ST5[(rag_result / tool_result)]
    ST6[(warnings / trace / error)]
    ST7[(final_answer)]
  end

  N1 --> ST1
  N1 --> ST2
  N2 --> ST3
  N3 --> ST4
  N4 --> ST5
  N5 --> ST5
  N5 --> ST4
  N2 --> ST6
  N3 --> ST6
  N4 --> ST6
  N5 --> ST6
  N6 --> ST7

  %% -----------------------------
  %% Layer 4: Capability Calls
  %% -----------------------------
  subgraph L4[Capability Layer]
    RAG[RAG API :8787 /api/chat]
    TOOL[wind_resource_analysis tool]
    OLLM[Orchestrator LLM]
  end

  N2 -. intent classify .-> OLLM
  N3 -. workflow plan .-> OLLM
  N4 -. query .-> RAG
  N5 -. tool step invoke .-> TOOL
  N5 -. llm step summarize .-> OLLM
  N6 -. final synthesis .-> OLLM

  %% -----------------------------
  %% Intent semantics
  %% -----------------------------
  I1{{intent = rag}}
  I2{{intent = tool}}
  I3{{intent = workflow}}

  N2 --> I1
  N2 --> I2
  N2 --> I3

  I1 -. rag path .-> N3
  I2 -. tool path .-> N3
  I3 -. workflow path .-> N3

  %% -----------------------------
  %% Tool executor inner loop
  %% -----------------------------
  subgraph L5[tool_executor internal]
    W0[for each step in workflow_plan]
    W1{step.type}
    W2[rag step: call RAG API]
    W3[tool step: for each excel file]
    W4[llm step: summarize intermediate]
    W5[append workflow_results]
  end

  N5 --> W0 --> W1
  W1 -->|rag| W2 --> W5
  W1 -->|tool| W3 --> W5
  W1 -->|llm| W4 --> W5

  %% -----------------------------
  %% Output
  %% -----------------------------
  OUT[Response JSON\nsuccess, summary, analysis,\nresolved_excel_path(s), rag_result,\nworkflow_results, trace, error]
  S1 --> OUT

  %% -----------------------------
  %% Styles
  %% -----------------------------
  classDef layer fill:#EEF2FF,stroke:#4F46E5,stroke-width:1.2px,color:#1E1B4B;
  classDef node fill:#F8FAFC,stroke:#334155,stroke-width:1.2px,color:#0F172A;
  classDef state fill:#ECFEFF,stroke:#0E7490,stroke-width:1.1px,color:#083344;
  classDef cap fill:#F0FDF4,stroke:#16A34A,stroke-width:1.1px,color:#14532D;
  classDef warn fill:#FFF7ED,stroke:#EA580C,stroke-width:1.1px,color:#7C2D12;

  class L1,L2,L3,L4,L5 layer;
  class U,H1,API,S0,N1,N2,N3,N4,N5,N6,S1,I1,I2,I3,W0,W1,W2,W3,W4,W5,OUT node;
  class ST1,ST2,ST3,ST4,ST5,ST6,ST7 state;
  class RAG,TOOL,OLLM cap;

```

## 4) 当前能力边界

- 支持单文件分析
- 支持文件夹匹配与多文件批量分析（`.xlsx/.xls`）
- 支持真实 RAG 路径，不再是占位回复
- 支持 workflow 按步骤执行（`rag/tool/llm`）
- 所有回退会写入 `warnings + trace`
