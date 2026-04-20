"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Layer, Map as LeafletMap } from "leaflet";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "leaflet/dist/leaflet.css";
import "katex/dist/katex.min.css";

type UiBlock = {
  type: string;
  title?: string;
  role?: string;
  content?: string;
  items?: any[] | Record<string, any>;
  data?: Record<string, any>;
};

type ChatResponse = {
  ok?: boolean;
  mode?: string;
  provider?: string;
  model?: string;
  answer?: string;
  elapsed_seconds?: number;
  request_id?: string;
  ui_blocks?: UiBlock[];
  analysis?: Record<string, any>;
  retrieval_metrics?: Record<string, any>;
  [k: string]: any;
};

type StatusKind = "ok" | "warn" | "err";
type SseEvent = { event: string; data: any };

const titleMap: Record<string, string> = {
  message: "助手回复",
  meta: "元信息",
  metrics: "检索指标",
  agentic_grades: "Agentic 评分",
  agentic_trace_timeline: "Agentic 轨迹",
  subquestions: "子问题",
  json: "结构化数据",
  gallery: "预览图片",
  actions: "操作",
  alert: "告警",
};

const DEFAULT_SYSTEM_PROMPT = "你是一个严谨的分析助手，优先使用可验证证据进行回答。";

function trimSlash(v: string) {
  return (v || "").trim().replace(/\/+$/, "");
}

function parseSseChunk(chunk: string): SseEvent | null {
  const lines = chunk.split(/\r?\n/).filter(Boolean);
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  try {
    return { event, data: JSON.parse(raw) };
  } catch {
    return { event, data: { raw } };
  }
}

function buildPayload(state: {
  sessionId: string;
  mode: string;
  provider: string;
  model: string;
  userPrompt: string;
  temperature: number;
  maxTokens: number;
  topK: number;
  ragRewrite: boolean;
  ragExpand: boolean;
  ragRerank: boolean;
  ragCoarseK: number;
  ragBm25K: number;
  ragMergeK: number;
  ragDedupDocK: number;
  ragDocTopM: number;
  ragMaxCandidates: number;
  typhoonEnabled: boolean;
  tfModelScope: string;
  tfLat: number;
  tfLon: number;
  tfRadius: number;
  tfYearStart: number;
  tfYearEnd: number;
  tfWindThreshold: number;
  tfBoundary: number;
  tfMonths: string;
}) {
  const ragEnabled = state.mode === "auto" || state.mode === "rag";
  const typhoonModeEnabled = state.mode === "wind_agent" || state.mode === "typhoon_model";

  const payload: any = {
    session_id: state.sessionId || "session-anon",
    mode: state.mode,
    provider: state.provider,
    model: state.model.trim(),
    messages: [
      { role: "system", content: DEFAULT_SYSTEM_PROMPT },
      { role: "user", content: state.userPrompt.trim() },
    ],
    generation_config: {
      temperature: Number(state.temperature || 0.2),
      max_tokens: Number(state.maxTokens || 768),
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
  };

  if (ragEnabled) {
    payload.retrieval_config = {
      top_k: Number(state.topK || 4),
      rerank: state.ragRerank,
      coarse_k: Number(state.ragCoarseK || 20),
      bm25_k: Number(state.ragBm25K || 20),
      merge_k: Number(state.ragMergeK || 20),
      dedup_doc_k: Number(state.ragDedupDocK || 20),
      doc_top_m: Number(state.ragDocTopM || 1),
      max_rerank_candidates: Number(state.ragMaxCandidates || 20),
      enable_query_rewrite: state.ragRewrite,
      enable_domain_expansion: state.ragExpand,
    };
  }

  if (!payload.model) delete payload.model;

  if (state.typhoonEnabled && typhoonModeEnabled) {
    const months = String(state.tfMonths || "")
      .split(",")
      .map((x) => Number(x.trim()))
      .filter((x) => Number.isFinite(x) && x >= 1 && x <= 12);

    payload.wind_agent_input = {
      model_scope: state.tfModelScope,
      lat: Number(state.tfLat),
      lon: Number(state.tfLon),
      radius_km: Number(state.tfRadius),
      year_start: Number(state.tfYearStart),
      year_end: Number(state.tfYearEnd),
      wind_threshold_kt: Number(state.tfWindThreshold),
      n_boundary: Number(state.tfBoundary),
      ...(months.length ? { months: Array.from(new Set(months)) } : {}),
    };
  }

  return payload;
}

function mergeBlocks(prev: UiBlock[], next: UiBlock[]) {
  if (!next.length) return prev;
  const merged = [...prev];
  for (const item of next) {
    const exists = merged.some(
      (x) =>
        x.type === item.type &&
        x.title === item.title &&
        JSON.stringify(x.items || x.data || x.content || null) ===
          JSON.stringify(item.items || item.data || item.content || null),
    );
    if (!exists) merged.push(item);
  }
  return merged;
}

function shouldHideBlockTitle(type: string) {
  return ["message", "gallery", "meta", "metrics", "json", "agentic_grades", "agentic_trace_timeline", "subquestions"].includes(type);
}

function extractFigureKey(text: string): string | null {
  const s = String(text || "");
  const m = s.match(/(?:图|fig(?:ure)?\.?)\s*([0-9]+(?:[-.][0-9]+)?)/i);
  if (!m?.[1]) return null;
  return m[1].replace(".", "-");
}

function toZhCaption(rawTitle: string): string {
  const key = extractFigureKey(rawTitle);
  if (key) return `图${key}`;
  return "图像";
}

export default function Page() {
  const [backendUrl, setBackendUrl] = useState(process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8787");
  const [mode, setMode] = useState("auto");
  const [provider, setProvider] = useState("vllm");
  const [model, setModel] = useState("");
  const [userPrompt, setUserPrompt] = useState("");
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(768);
  const [topK, setTopK] = useState(4);
  const [sessionId, setSessionId] = useState("");

  const [ragRewrite, setRagRewrite] = useState(true);
  const [ragExpand, setRagExpand] = useState(false);
  const [ragRerank, setRagRerank] = useState(true);
  const [ragCoarseK, setRagCoarseK] = useState(20);
  const [ragBm25K, setRagBm25K] = useState(20);
  const [ragMergeK, setRagMergeK] = useState(20);
  const [ragDedupDocK, setRagDedupDocK] = useState(20);
  const [ragDocTopM, setRagDocTopM] = useState(1);
  const [ragMaxCandidates, setRagMaxCandidates] = useState(20);

  const [typhoonEnabled, setTyphoonEnabled] = useState(true);
  const [tfModelScope, setTfModelScope] = useState("scs");
  const [tfLat, setTfLat] = useState(20.9339);
  const [tfLon, setTfLon] = useState(112.202);
  const [tfRadius, setTfRadius] = useState(100);
  const [tfYearStart, setTfYearStart] = useState(1976);
  const [tfYearEnd, setTfYearEnd] = useState(2025);
  const [tfWindThreshold, setTfWindThreshold] = useState(50);
  const [tfBoundary, setTfBoundary] = useState(72);
  const [tfMonths, setTfMonths] = useState("1,2,3,4,5,6,7,8,9,10,11,12");

  const [status, setStatus] = useState("就绪。");
  const [statusKind, setStatusKind] = useState<StatusKind | "">("");
  const [isLoading, setIsLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [lastQuestion, setLastQuestion] = useState("");
  const [response, setResponse] = useState<ChatResponse | null>(null);
  const [blocks, setBlocks] = useState<UiBlock[]>([]);
  const [rawText, setRawText] = useState("{}");
  const [runtimeText, setRuntimeText] = useState("{}");
  const [healthInfo, setHealthInfo] = useState<any>(null);

  const [mapSpec, setMapSpec] = useState<any>(null);
  const [mapInfo, setMapInfo] = useState("无地图数据。");
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const mapRef = useRef<LeafletMap | null>(null);
  const mapLayersRef = useRef<Layer[]>([]);
  const chatEndRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const hasResultSection = useMemo(() => !!response || !!streamedAnswer || blocks.length > 0 || !!lastQuestion, [response, streamedAnswer, blocks, lastQuestion]);

  useEffect(() => {
    const key = "wind_agent_session_id";
    let value = "";
    try {
      value = window.localStorage.getItem(key) || "";
      if (!value) {
        value = (window.crypto?.randomUUID?.() || `sid-${Date.now()}-${Math.random().toString(16).slice(2)}`).toLowerCase();
        window.localStorage.setItem(key, value);
      }
    } catch {
      value = `sid-${Date.now()}-${Math.random().toString(16).slice(2)}`.toLowerCase();
    }
    setSessionId(value);
  }, []);
  const hasMapSection = useMemo(() => !!mapSpec, [mapSpec]);
  const shouldShowTyphoonPanel = mode === "wind_agent" || mode === "typhoon_model";
  const showRagPanel = useMemo(() => mode === "rag" || mode === "auto" || !!response?.retrieval_metrics, [mode, response?.retrieval_metrics]);
  const sideBlockTypes = useMemo(() => new Set(["agentic_trace_timeline", "metrics", "meta", "agentic_grades"]), []);

  const structuralBlocks = useMemo(() => {
    const merged = [...blocks];
    if (response?.retrieval_metrics && !merged.some((b) => b.type === "metrics")) {
      merged.push({ type: "metrics", items: response.retrieval_metrics });
    }
    if (healthInfo && Object.keys(healthInfo).length && !merged.some((b) => b.type === "json" && b.title === "health")) {
      merged.push({ type: "json", title: "health", data: healthInfo });
    }
    if (runtimeText !== "{}" && !merged.some((b) => b.type === "json" && b.title === "runtime")) {
      try {
        merged.push({ type: "json", title: "runtime", data: JSON.parse(runtimeText) });
      } catch {}
    }
    return merged;
  }, [blocks, response?.retrieval_metrics, healthInfo, runtimeText]);

  const mainBlocks = useMemo(() => structuralBlocks.filter((b) => !sideBlockTypes.has(b.type)), [structuralBlocks, sideBlockTypes]);

  const displayBlocks = useMemo(() => {
    const effectiveBlocks = mainBlocks.filter((b) => {
      if (b.type !== "actions") return true;
      if (!Array.isArray(b.items) || b.items.length === 0) return false;
      return b.items.some((action: any) => {
        const id = String(action?.id || "");
        return id === "save_result" || id === "copy_request_id";
      });
    });
    const filteredBlocks = effectiveBlocks.filter((b) => b.type !== "actions");
    const galleries = filteredBlocks.filter((b) => b.type === "gallery");
    const nonGallery = filteredBlocks.filter((b) => b.type !== "gallery");
    if (!galleries.length) return nonGallery;
    const firstMsgIdx = nonGallery.findIndex((b) => b.type === "message");
    if (firstMsgIdx < 0) return [...galleries, ...nonGallery];
    return [...nonGallery.slice(0, firstMsgIdx + 1), ...galleries, ...nonGallery.slice(firstMsgIdx + 1)];
  }, [mainBlocks]);

  function setUiStatus(text: string, kind: StatusKind | "" = "") {
    setStatus(text);
    setStatusKind(kind);
  }

  function resetRuntimePanels() {
    setStreamedAnswer("");
    setResponse(null);
    setBlocks([]);
    setRawText("{}");
    setRuntimeText("{}");
    setMapSpec(null);
    setMapInfo("无地图数据。");
  }

  function onSseEvent(evt: SseEvent) {
    if (evt.event === "token") {
      const token = String(evt.data?.text || "");
      if (token) setStreamedAnswer((prev) => prev + token);
      return;
    }

    if (evt.event === "block") {
      if (evt.data && typeof evt.data === "object") setBlocks((prev) => [...prev, evt.data as UiBlock]);
      return;
    }

    if (evt.event === "error") {
      setUiStatus(String(evt.data?.payload?.error || evt.data?.error || "流式请求失败"), "err");
      return;
    }

    if (evt.event === "done") {
      const payload = evt.data as ChatResponse;
      setResponse(payload);
      setRawText(JSON.stringify(payload, null, 2));
      setRuntimeText(
        JSON.stringify(
          {
            client_time: new Date().toISOString(),
            elapsed_seconds: payload?.elapsed_seconds ?? "--",
            mode: payload?.mode ?? mode,
          },
          null,
          2,
        ),
      );
      if (Array.isArray(payload?.ui_blocks) && payload.ui_blocks.length) {
        setBlocks((prev) => mergeBlocks(prev, payload.ui_blocks!));
      }

      const analysis = payload?.analysis || {};
      const spec =
        analysis?.map_spec ||
        analysis?.result?.map_spec ||
        (Array.isArray(analysis?.batch_results)
          ? (analysis.batch_results.find((x: any) => x?.tool === "analyze_typhoon_map") || {})?.result?.map_spec
          : null);

      if (spec?.center) {
        setMapSpec(spec);
        setMapInfo(JSON.stringify(spec, null, 2));
      }
      setUiStatus("请求成功。", "ok");
    }
  }

  async function consumeSseResponse(res: Response) {
    if (!res.body) throw new Error("stream body is empty");
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let splitIndex = buffer.indexOf("\n\n");
      while (splitIndex >= 0) {
        const chunk = buffer.slice(0, splitIndex).trim();
        buffer = buffer.slice(splitIndex + 2);
        if (chunk) {
          const evt = parseSseChunk(chunk);
          if (evt) onSseEvent(evt);
        }
        splitIndex = buffer.indexOf("\n\n");
      }
    }
  }

  function normalizeResponseFromEndpoint(endpoint: string, payload: any, json: any): ChatResponse {
    if (endpoint === "/agent/chat") {
      const summary = String(json?.summary || json?.answer || "");
      return {
        ok: json?.success !== false,
        mode: "wind_agent",
        answer: summary,
        request_id: json?.request_id,
        analysis: json?.analysis,
        elapsed_seconds: json?.elapsed_seconds,
        ui_blocks: Array.isArray(json?.ui_blocks)
          ? json.ui_blocks
          : [
              { type: "message", role: "assistant", content: summary || "Agent finished." },
              { type: "json", title: "Analysis", data: json?.analysis || {} },
            ],
      };
    }

    const mapped: ChatResponse = { ...(json || {}) };
    if (!Array.isArray(mapped.ui_blocks) && mapped.answer) {
      mapped.ui_blocks = [{ type: "message", role: "assistant", content: String(mapped.answer) }];
    }
    if (!mapped.mode) mapped.mode = payload?.mode || "auto";
    return mapped;
  }

  async function tryNonStreamEndpoints(payload: any, signal?: AbortSignal): Promise<{ endpoint: string; response: ChatResponse }> {
    const base = trimSlash(backendUrl);
    const candidates: Array<{ endpoint: string; body: any }> = [
      { endpoint: "/api/chat", body: payload },
      {
        endpoint: "/agent/chat",
        body: {
          request: String(payload?.messages?.[1]?.content || ""),
          wind_agent_input: payload?.wind_agent_input || null,
        },
      },
    ];

    let lastErr = "unknown";
    for (const c of candidates) {
      try {
        const r = await fetch(base + c.endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(c.body),
          signal,
        });
        const text = await r.text();
        let json: any = {};
        try {
          json = JSON.parse(text);
        } catch {
          throw new Error(`${c.endpoint} parse failed: ${text.slice(0, 200)}`);
        }
        if (!r.ok) {
          lastErr = `${c.endpoint} HTTP ${r.status}: ${String(json?.error || text).slice(0, 200)}`;
          continue;
        }
        const normalized = normalizeResponseFromEndpoint(c.endpoint, payload, json);
        if (normalized?.ok === false) {
          lastErr = `${c.endpoint} app_error: ${String(normalized?.error || "unknown")}`;
          continue;
        }
        return { endpoint: c.endpoint, response: normalized };
      } catch (e: any) {
        lastErr = `${c.endpoint} ${String(e?.message || e)}`;
      }
    }
    throw new Error(lastErr);
  }

  async function sendMessage() {
    if (isLoading) {
      abortRef.current?.abort();
      abortRef.current = null;
      setIsLoading(false);
      return;
    }

    const payload = buildPayload({
      sessionId,
      mode,
      provider,
      model,
      userPrompt,
      temperature,
      maxTokens,
      topK,
      ragRewrite,
      ragExpand,
      ragRerank,
      ragCoarseK,
      ragBm25K,
      ragMergeK,
      ragDedupDocK,
      ragDocTopM,
      ragMaxCandidates,
      typhoonEnabled,
      tfModelScope,
      tfLat,
      tfLon,
      tfRadius,
      tfYearStart,
      tfYearEnd,
      tfWindThreshold,
      tfBoundary,
      tfMonths,
    });

    const q = String(payload?.messages?.[1]?.content || "").trim();
    if (!q) {
      setUiStatus("请先输入用户问题。", "warn");
      return;
    }

    setLastQuestion(q);
    setUserPrompt("");
    resetRuntimePanels();
    setIsLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    setUiStatus("请求中...", "warn");

    try {
      const res = await fetch(`${trimSlash(backendUrl)}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (res.ok) {
        await consumeSseResponse(res);
        return;
      }

      setUiStatus(`流式接口不可用（HTTP ${res.status}），尝试非流式接口...`, "warn");
      const fallback = await tryNonStreamEndpoints(payload, controller.signal);
      const json = fallback.response;
      setResponse(json);
      setBlocks(Array.isArray(json?.ui_blocks) ? json.ui_blocks : []);
      setRawText(JSON.stringify(json, null, 2));
      setRuntimeText(
        JSON.stringify(
          {
            client_time: new Date().toISOString(),
            elapsed_seconds: json?.elapsed_seconds ?? "--",
            mode: json?.mode ?? mode,
            transport: `fallback_non_stream:${fallback.endpoint}`,
          },
          null,
          2,
        ),
      );
      setUiStatus(`请求成功（非流式回退：${fallback.endpoint}）。`, "ok");
    } catch (err: any) {
      if (err?.name === "AbortError") return;
      setUiStatus(`请求失败: ${String(err?.message || err)}`, "err");
    } finally {
      setIsLoading(false);
    }
  }

  async function checkHealth() {
    setUiStatus("健康检查中...", "warn");
    try {
      const res = await fetch(`${trimSlash(backendUrl)}/health`);
      const text = await res.text();
      let data: any = text;
      try {
        data = JSON.parse(text);
      } catch {
        data = { raw: text };}
      setHealthInfo(data);
      if (!res.ok) {
        setUiStatus(`健康检查失败 HTTP ${res.status}`, "err");
        return;
      }
      setUiStatus("健康检查通过。", "ok");
    } catch (err: any) {
      setHealthInfo({ error: String(err?.message || err) });
      setUiStatus(`健康检查失败: ${String(err?.message || err)}`, "err");
    }
  }

  async function renderCsvMap() {
    if (!csvFile) {
      setUiStatus("请先选择 CSV 文件。", "warn");
      return;
    }
    const text = await csvFile.text();
    const lines = text.trim().split(/\r?\n/).filter(Boolean);
    if (lines.length < 2) {
      setUiStatus("CSV 至少需要两行。", "err");
      return;
    }
    const header = lines[0].split(",").map((x) => x.trim());
    const values = lines[1].split(",").map((x) => x.trim());
    const row: Record<string, string> = {};
    header.forEach((k, i) => {
      row[k] = values[i] || "";
    });
    const scope = header.includes("N_enterSCS") ? "scs" : "total";
    const spec = {
      model_scope: scope,
      center: {
        lat: Number(row.lat0 || row.lat || tfLat),
        lon: Number(row.lon0 || row.lon || tfLon),
      },
      radius_km: Number(row.R_km || row.radius_km || tfRadius),
      metrics: row,
    };
    setMapSpec(spec);
    setMapInfo(JSON.stringify(spec, null, 2));
    setUiStatus("CSV 地图参数已加载。", "ok");
  }

  function clearMap() {
    setMapSpec(null);
    setMapInfo("无地图数据。");
  }

  function saveResult() {
    if (!response) {
      setUiStatus("当前没有可下载结果。", "warn");
      return;
    }
    const blob = new Blob([JSON.stringify(response, null, 2)], { type: "application/json;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `result_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    setUiStatus("结果已下载。", "ok");
  }

  useEffect(() => {
    if (!mapSpec?.center) return;
    let cancelled = false;

    (async () => {
      const L = await import("leaflet");
      if (cancelled) return;

      if (!mapRef.current) {
        mapRef.current = L.map("map");
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          maxZoom: 12,
          attribution: "&copy; OpenStreetMap",
        }).addTo(mapRef.current);
      }

      const map = mapRef.current;
      mapLayersRef.current.forEach((layer) => {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      });
      mapLayersRef.current = [];

      const lat = Number(mapSpec.center.lat || 0);
      const lon = Number(mapSpec.center.lon || 0);
      const radiusKm = Number(mapSpec.radius_km || 0);
      const scope = String(mapSpec.model_scope || "total");

      const marker = L.marker([lat, lon]).addTo(map).bindPopup("目标点");
      mapLayersRef.current.push(marker);
      if (radiusKm > 0) {
        const circle = L.circle([lat, lon], {
          radius: radiusKm * 1000,
          color: "#1f78d1",
          weight: 2,
          fillOpacity: 0.08,
        }).addTo(map);
        mapLayersRef.current.push(circle);
      }
      if (scope === "scs") {
        const poly = L.polygon([[0, 105], [0, 121], [25, 121], [25, 105]], {
          color: "#f59e0b",
          weight: 2,
          fillOpacity: 0.08,
        }).addTo(map);
        mapLayersRef.current.push(poly);
        map.fitBounds([[0, 105], [25, 121]]);
      } else {
        map.setView([lat || 20.9, lon || 112.2], 5);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [mapSpec, tfLat, tfLon]);

  useEffect(() => {
    return () => {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      mapLayersRef.current = [];
    };
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [displayBlocks, streamedAnswer, status]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        setShowSettings((v) => !v);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <div className="chat-page">
      <main className={`chat-shell ${showSettings ? "with-sidebar" : "sidebar-collapsed"}`}>
        <div className="chat-layout">
          <button
            className={`sidebar-open-btn ${showSettings ? "hidden" : ""}`}
            onClick={() => setShowSettings(true)}
            aria-label="打开左侧栏"
            title="打开设置"
          >
            ☰
          </button>

          <aside className="settings-sidebar" aria-hidden={!showSettings}>
            <div className="settings-sidebar-inner">
              <div className="sidebar-top">
                <button
                  className="sidebar-toggle-btn"
                  onClick={() => setShowSettings(false)}
                  aria-label="收起左侧栏"
                  title="收起设置"
                >
                  ☰
                </button>
                <span className="sidebar-top-title">设置</span>
              </div>
              <section className="settings-drawer card-lite">
                <div className="settings-grid">
                  <div className="settings-block">
                    <div className="settings-title">基础</div>
                    <div className="field-grid two">
                      <div><label>模式</label><select value={mode} onChange={(e) => setMode(e.target.value)}><option value="auto">auto</option><option value="rag">rag</option><option value="wind_agent">wind_agent</option><option value="typhoon_model">typhoon_model</option><option value="llm_direct">llm_direct</option></select></div>
                      <div><label>provider</label><input value={provider} onChange={(e) => setProvider(e.target.value)} /></div>
                      <div><label>model</label><input value={model} onChange={(e) => setModel(e.target.value)} /></div>
                      <div><label>后端地址</label><input value={backendUrl} onChange={(e) => setBackendUrl(e.target.value)} /></div>
                      <div><label>temperature</label><input type="number" step="0.1" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} /></div>
                      <div><label>max_tokens</label><input type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} /></div>
                      <div><label>top_k</label><input type="number" value={topK} onChange={(e) => setTopK(Number(e.target.value))} /></div>
                    </div>
                  </div>

                  {showRagPanel ? (
                    <div className="settings-block">
                      <div className="settings-title">RAG</div>
                      <div className="check-grid">
                        <label><input type="checkbox" checked={ragRewrite} onChange={(e) => setRagRewrite(e.target.checked)} /> rewrite</label>
                        <label><input type="checkbox" checked={ragExpand} onChange={(e) => setRagExpand(e.target.checked)} /> expand</label>
                        <label><input type="checkbox" checked={ragRerank} onChange={(e) => setRagRerank(e.target.checked)} /> rerank</label>
                      </div>
                      <div className="field-grid three">
                        <div><label>coarse_k</label><input type="number" value={ragCoarseK} onChange={(e) => setRagCoarseK(Number(e.target.value))} /></div>
                        <div><label>bm25_k</label><input type="number" value={ragBm25K} onChange={(e) => setRagBm25K(Number(e.target.value))} /></div>
                        <div><label>merge_k</label><input type="number" value={ragMergeK} onChange={(e) => setRagMergeK(Number(e.target.value))} /></div>
                        <div><label>dedup_doc_k</label><input type="number" value={ragDedupDocK} onChange={(e) => setRagDedupDocK(Number(e.target.value))} /></div>
                        <div><label>doc_top_m</label><input type="number" value={ragDocTopM} onChange={(e) => setRagDocTopM(Number(e.target.value))} /></div>
                        <div><label>max_candidates</label><input type="number" value={ragMaxCandidates} onChange={(e) => setRagMaxCandidates(Number(e.target.value))} /></div>
                      </div>
                    </div>
                  ) : null}

                  {shouldShowTyphoonPanel ? (
                    <div className="settings-block">
                      <div className="settings-title">台风参数</div>
                      <label className="toggle-line"><input type="checkbox" checked={typhoonEnabled} onChange={(e) => setTyphoonEnabled(e.target.checked)} /> 启用 wind_agent_input</label>
                      <fieldset disabled={!typhoonEnabled} className="fieldset-reset">
                        <div className="field-grid two">
                          <div><label>model_scope</label><select value={tfModelScope} onChange={(e) => setTfModelScope(e.target.value)}><option value="scs">scs</option><option value="total">total</option></select></div>
                          <div><label>wind_threshold_kt</label><input type="number" value={tfWindThreshold} onChange={(e) => setTfWindThreshold(Number(e.target.value))} /></div>
                        </div>
                        <div className="field-grid three">
                          <div><label>lat</label><input type="number" value={tfLat} onChange={(e) => setTfLat(Number(e.target.value))} /></div>
                          <div><label>lon</label><input type="number" value={tfLon} onChange={(e) => setTfLon(Number(e.target.value))} /></div>
                          <div><label>radius_km</label><input type="number" value={tfRadius} onChange={(e) => setTfRadius(Number(e.target.value))} /></div>
                          <div><label>year_start</label><input type="number" value={tfYearStart} onChange={(e) => setTfYearStart(Number(e.target.value))} /></div>
                          <div><label>year_end</label><input type="number" value={tfYearEnd} onChange={(e) => setTfYearEnd(Number(e.target.value))} /></div>
                          <div><label>n_boundary</label><input type="number" value={tfBoundary} onChange={(e) => setTfBoundary(Number(e.target.value))} /></div>
                        </div>
                        <div><label>months</label><input value={tfMonths} onChange={(e) => setTfMonths(e.target.value)} /></div>
                      </fieldset>
                    </div>
                  ) : null}

                  <div className="settings-block">
                    <div className="settings-title">工具</div>
                    <div className="inline-actions">
                      <button className="ghost-btn" onClick={checkHealth}>健康检查</button>
                      <button className="ghost-btn" onClick={saveResult}>下载结果</button>
                    </div>
                    <div className={`status-chip ${statusKind}`}>{status}</div>
                  </div>
                </div>
              </section>
            </div>
          </aside>

          <section className="chat-main">
            <section className="chat-header">
              <div>
                <h1>中交智慧风电智能体</h1>
                <p className="subtle">面向风电知识问答、RAG 检索与台风分析</p>
              </div>
            </section>

            <section className="chat-body">
          {!hasResultSection ? (
            <div className="empty-state card-lite">
              <div className="empty-title">今天想分析什么？</div>
              <div className="empty-subtitle">支持 RAG 问答、wind_agent、typhoon_model 与地图结果展示</div>
            </div>
          ) : null}

          {!!lastQuestion ? (
            <article className="msg-row assistant-row">
              <div className="avatar">Q</div>
              <div className="msg-card markdown-message">
                <div className="markdown-body plain-markdown">{`${lastQuestion}`}</div>
              </div>
            </article>
          ) : null}

          {!!streamedAnswer && !response ? (
            <article className="msg-row assistant-row">
              <div className="avatar">A</div>
              <div className="msg-card markdown-message streaming">
                <div className="markdown-body plain-markdown">
                  <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                    {String(streamedAnswer || "")}
                  </ReactMarkdown>
                </div>
              </div>
            </article>
          ) : null}

          {displayBlocks.map((b, i) => {
            const isMessage = b.type === "message";
            const isGallery = b.type === "gallery";

            return (
              <article className="msg-row assistant-row" key={`${b.type}-${i}`}>
                <div className="avatar">A</div>
                <div className={`msg-card ${isMessage ? "markdown-message" : "data-card"}`}>
                  {!shouldHideBlockTitle(b.type) ? <div className="block-caption">{b.title || titleMap[b.type] || b.type}</div> : null}

                  {b.type === "message" ? (
                    <div className="markdown-body plain-markdown">
                      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                        {String(b.content || "")}
                      </ReactMarkdown>
                    </div>
                  ) : null}

                  {b.type === "meta" || b.type === "metrics" ? <pre className="mono slim">{JSON.stringify(b.items || {}, null, 2)}</pre> : null}
                  {b.type === "json" || b.type === "agentic_grades" ? <pre className="mono slim">{JSON.stringify(b.data || {}, null, 2)}</pre> : null}
                  {b.type === "agentic_trace_timeline" || b.type === "subquestions" ? <pre className="mono slim">{JSON.stringify(b.items || [], null, 2)}</pre> : null}
                  {b.type === "gallery" ? (
                    <div className="gallery gallery-chat">
                      {(Array.isArray(b.items) ? b.items : []).map((it: any, idx: number) => {
                        const src = trimSlash(backendUrl) + String(it?.asset_url || "");
                        const indices = Array.isArray(it?.indices)
                          ? it.indices.map((x: any) => String(x || "").trim()).filter(Boolean)
                          : [];
                        const indexLabel = indices.length ? `[${indices.join(", ")}] ` : it?.index ? `[${String(it.index)}] ` : "";
                        const titleText = String(it?.title || "image");
                        return (
                          <div key={`${i}-g-${idx}`} className="gallery-card">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={src} alt={titleText} />
                            <div className="gallery-title">{`${indexLabel}${titleText}`}</div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                  {b.type === "alert" ? <pre className="mono slim">{String(b.content || "")}</pre> : null}
                </div>
              </article>
            );
          })}

          {hasMapSection ? (
            <article className="msg-row assistant-row">
              <div className="avatar">A</div>
              <div className="msg-card data-card">
                <div id="map" />
                <pre className="mono slim">{mapInfo}</pre>
                <div className="inline-actions">
                  <input ref={fileInputRef} type="file" accept=".csv,text/csv" onChange={(e) => setCsvFile(e.target.files?.[0] || null)} />
                  <button className="ghost-btn" onClick={renderCsvMap}>渲染 CSV</button>
                  <button className="ghost-btn" onClick={clearMap}>清空地图</button>
                </div>
              </div>
            </article>
          ) : null}

          <div ref={chatEndRef} />
            </section>

            <section className="composer-wrap">
              <div className="composer-shell">
                <textarea
                  value={userPrompt}
                  onChange={(e) => setUserPrompt(e.target.value)}
                  disabled={isLoading}
                  placeholder="输入你的问题..."
                  className="composer-input"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void sendMessage();
                    }
                  }}
                />
                <button className="send-btn" onClick={sendMessage} aria-label={isLoading ? "停止" : "发送"}>
                  <span className="send-arrow">{isLoading ? "■" : "↑"}</span>
                </button>
              </div>
            </section>
          </section>
        </div>
      </main>
    </div>
  );
}
