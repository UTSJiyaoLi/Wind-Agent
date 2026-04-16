"use client";

import { useMemo, useState } from "react";

type UiBlock = {
  type: string;
  title?: string;
  content?: string;
  items?: any;
  data?: any;
};

type ChatResponse = {
  ok?: boolean;
  mode?: string;
  answer?: string;
  elapsed_seconds?: number;
  request_id?: string;
  ui_blocks?: UiBlock[];
  [k: string]: any;
};

const titleMap: Record<string, string> = {
  message: "Assistant Reply",
  meta: "Session Meta",
  metrics: "Retrieval Metrics",
  agentic_grades: "Agentic Grades",
  agentic_trace_timeline: "Agentic Trace",
  subquestions: "Subquestions",
  json: "Structured Data",
  gallery: "Preview Images",
  actions: "Actions",
  alert: "Alert",
};

function trimSlash(v: string) {
  return (v || "").trim().replace(/\/+$/, "");
}

function renderText(v: any) {
  if (typeof v === "string") return v;
  return JSON.stringify(v ?? {}, null, 2);
}

export default function V1Page() {
  const [backendUrl, setBackendUrl] = useState(process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8787");
  const [mode, setMode] = useState("auto");
  const [model, setModel] = useState("");
  const [topK, setTopK] = useState(4);
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(768);
  const [systemPrompt, setSystemPrompt] = useState("You are a rigorous assistant. Use evidence when available.");
  const [userPrompt, setUserPrompt] = useState("");
  const [status, setStatus] = useState("Ready.");
  const [raw, setRaw] = useState("{}");
  const [runtime, setRuntime] = useState("{}");
  const [blocks, setBlocks] = useState<UiBlock[]>([]);
  const [busy, setBusy] = useState(false);

  const payload = useMemo(
    () => ({
      mode,
      provider: "vllm",
      ...(model.trim() ? { model: model.trim() } : {}),
      messages: [
        { role: "system", content: systemPrompt.trim() },
        { role: "user", content: userPrompt.trim() },
      ],
      generation_config: {
        temperature: Number(temperature || 0.2),
        max_tokens: Number(maxTokens || 768),
      },
      retrieval_config: {
        top_k: Number(topK || 4),
      },
      agentic: {
        enabled: true,
        max_retries: 2,
        min_top_score: 0.58,
        min_coverage: 0.55,
        retry_topk_step: 2,
        max_topk: 10,
        decompose_enabled: true,
        max_subquestions: 3,
      },
    }),
    [mode, model, systemPrompt, userPrompt, temperature, maxTokens, topK],
  );

  async function send() {
    if (!userPrompt.trim()) {
      setStatus("Please input user prompt.");
      return;
    }
    setBusy(true);
    setStatus("Sending request...");
    setBlocks([]);
    setRaw("{}");
    setRuntime("{}");

    try {
      const r = await fetch(`${trimSlash(backendUrl)}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const text = await r.text();
      let json: ChatResponse = {};
      try {
        json = JSON.parse(text);
      } catch {
        setStatus(`Request failed: HTTP ${r.status}`);
        setRaw(text || "");
        return;
      }
      if (!r.ok) {
        setStatus(`Request failed: HTTP ${r.status}`);
        setRaw(text || "");
        return;
      }
      const uiBlocks =
        Array.isArray(json.ui_blocks) && json.ui_blocks.length
          ? json.ui_blocks
          : [{ type: "message", content: String(json.answer || "") }];
      setBlocks(uiBlocks);
      setRaw(JSON.stringify(json, null, 2));
      setRuntime(
        JSON.stringify(
          {
            client_time: new Date().toISOString(),
            elapsed_seconds: json?.elapsed_seconds ?? "--",
            mode: json?.mode ?? mode,
          },
          null,
          2,
        ),
      );
      setStatus("Request success.");
    } catch (e: any) {
      setStatus(`Request error: ${String(e?.message || e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function health() {
    setBusy(true);
    setStatus("Checking health...");
    try {
      const r = await fetch(`${trimSlash(backendUrl)}/health`);
      const text = await r.text();
      setRaw(text || "{}");
      if (!r.ok) {
        setStatus(`Health failed: HTTP ${r.status}`);
      } else {
        setStatus("Health OK.");
      }
    } catch (e: any) {
      setStatus(`Health error: ${String(e?.message || e)}`);
    } finally {
      setBusy(false);
    }
  }

  function resetView() {
    setBlocks([]);
    setRaw("{}");
    setRuntime("{}");
    setStatus("Cleared.");
  }

  return (
    <main className="v1-wrap">
      <h1>Wind Agent v1 (Next.js)</h1>
      <p className="v1-sub">React implementation aligned with langchain_generative_ui_v1 style.</p>

      <section className="v1-card">
        <div className="v1-row3">
          <div>
            <label>Backend URL</label>
            <input value={backendUrl} onChange={(e) => setBackendUrl(e.target.value)} />
          </div>
          <div>
            <label>Mode</label>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="auto">auto</option>
              <option value="rag">rag</option>
              <option value="wind_agent">wind_agent</option>
              <option value="llm_direct">llm_direct</option>
            </select>
          </div>
          <div>
            <label>Model (optional)</label>
            <input value={model} onChange={(e) => setModel(e.target.value)} />
          </div>
        </div>

        <div className="v1-row">
          <div>
            <label>System Prompt</label>
            <textarea value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} />
          </div>
          <div>
            <label>User Prompt</label>
            <textarea value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} />
          </div>
        </div>

        <div className="v1-row3">
          <div>
            <label>top_k</label>
            <input type="number" value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
          </div>
          <div>
            <label>temperature</label>
            <input type="number" step="0.1" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
          </div>
          <div>
            <label>max_tokens</label>
            <input type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} />
          </div>
        </div>

        <div className="v1-btns">
          <button className="primary" disabled={busy} onClick={() => void send()}>
            Send
          </button>
          <button disabled={busy} onClick={() => void health()}>
            Health
          </button>
          <button disabled={busy} onClick={resetView}>
            Clear
          </button>
        </div>
      </section>

      <section className="v1-card">
        <h2>Status</h2>
        <div className="v1-status">{status}</div>
      </section>

      <section className="v1-card">
        <h2>UI Blocks</h2>
        <div className="v1-blocks">
          {blocks.length === 0 ? <div className="v1-muted">No blocks yet.</div> : null}
          {blocks.map((b, i) => (
            <div key={`${b.type}-${i}`} className={`v1-block ${b.type === "alert" ? "alert" : ""}`}>
              <h3>{b.title || titleMap[b.type] || b.type}</h3>
              {b.type === "message" ? <pre className="v1-mono">{renderText(b.content)}</pre> : null}
              {b.type === "meta" || b.type === "metrics" ? <pre className="v1-mono">{renderText(b.items)}</pre> : null}
              {b.type === "json" || b.type === "agentic_grades" ? <pre className="v1-mono">{renderText(b.data)}</pre> : null}
              {b.type === "agentic_trace_timeline" || b.type === "subquestions" ? <pre className="v1-mono">{renderText(b.items)}</pre> : null}
              {b.type !== "message" && b.type !== "meta" && b.type !== "metrics" && b.type !== "json" && b.type !== "agentic_grades" && b.type !== "agentic_trace_timeline" && b.type !== "subquestions" ? (
                <pre className="v1-mono">{renderText(b)}</pre>
              ) : null}
            </div>
          ))}
        </div>
      </section>

      <section className="v1-card">
        <h2>Raw Response</h2>
        <pre className="v1-mono">{raw}</pre>
      </section>

      <section className="v1-card">
        <h2>Runtime</h2>
        <pre className="v1-mono">{runtime}</pre>
      </section>
    </main>
  );
}
