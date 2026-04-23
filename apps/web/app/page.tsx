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

function extractPrimaryAnswer(payload: any): string {
  const text = [
    payload?.answer,
    payload?.summary,
    payload?.final_answer,
    payload?.output_text,
    payload?.response,
    payload?.data?.answer,
    payload?.data?.summary,
  ].find((v) => typeof v === "string" && String(v).trim());
  return String(text || "").trim();
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
  const typhoonModeEnabled = state.mode === "typhoon_model";

  const payload: any = {
    session_id: state.sessionId || "session-anon",
    mode: state.mode,
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

function resolveScopedSessionId(baseSessionId: string, mode: string): string {
  const base = String(baseSessionId || "session-anon").trim() || "session-anon";
  const m = String(mode || "").trim().toLowerCase();
  if (m === "wind_analysis") return `${base}:wind-analysis`;
  if (m === "typhoon_model") return `${base}:typhoon-model`;
  return `${base}:chat`;
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

function resolveGallerySrc(backendUrl: string, asset: string): string {
  const raw = String(asset || "").trim();
  if (!raw) return "";
  if (/^(?:data:|https?:\/\/|file:\/\/)/i.test(raw)) return raw;
  if (/^[A-Za-z]:[\\/]/.test(raw)) return `file:///${raw.replace(/\\/g, "/")}`;
  if (raw.startsWith("/")) return `${trimSlash(backendUrl)}${raw}`;
  return raw;
}

function extractMapSpec(payload: any): any | null {
  const analysis = payload?.analysis || payload || {};
  const direct =
    analysis?.map_spec ||
    analysis?.result?.map_spec ||
    payload?.map_spec ||
    payload?.result?.map_spec ||
    payload?.data?.result?.map_spec;
  if (direct?.center) return direct;

  const batches: any[] = [];
  if (Array.isArray(analysis?.batch_results)) batches.push(...analysis.batch_results);
  if (Array.isArray(payload?.batch_results)) batches.push(...payload.batch_results);
  if (Array.isArray(payload?.workflow_results)) {
    for (const item of payload.workflow_results) {
      if (item && typeof item === "object") batches.push(item);
    }
  }

  for (const item of batches) {
    if (!item || typeof item !== "object") continue;
    const tool = String(item?.tool || item?.data?.tool || "");
    const spec = item?.result?.map_spec || item?.data?.result?.map_spec;
    if (tool === "analyze_typhoon_map" && spec?.center) return spec;
  }
  return null;
}

function isVerboseBatchJsonBlock(block: UiBlock): boolean {
  if (block.type !== "json") return false;
  const data = block.data || {};
  if (Array.isArray((data as any).batch_results)) return true;
  const asText = JSON.stringify(data || {});
  return asText.includes("\"batch_results\"");
}

function extractTyphoonProbabilityResult(payload: any): any | null {
  const analysis = payload?.analysis || payload || {};
  if (analysis?.metrics && (analysis?.model_scope || analysis?.input?.model_scope)) {
    return analysis;
  }
  const batches: any[] = [];
  if (Array.isArray(analysis?.batch_results)) batches.push(...analysis.batch_results);
  if (Array.isArray(payload?.batch_results)) batches.push(...payload.batch_results);
  for (const item of batches) {
    if (!item || typeof item !== "object") continue;
    if (String(item?.tool || item?.data?.tool || "") !== "analyze_typhoon_probability") continue;
    const res = item?.result || item?.data?.result;
    if (res && typeof res === "object" && res?.metrics) return res;
  }
  return null;
}

function formatPct(value: any): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return `${(n * 100).toFixed(2)}%`;
}

function classifyRisk(value: any): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return "未识别";
  if (n >= 0.2) return "高";
  if (n >= 0.1) return "中等";
  return "偏低";
}

function extractWindAnalysisGalleryItems(payload: any): any[] {
  const charts = Array.isArray(payload?.analysis?.data?.charts) ? payload.analysis.data.charts : [];
  return charts
    .map((item: any) => ({
      title: String(item?.title || "analysis-chart"),
      asset_url: String(item?.data_url || item?.path || ""),
    }))
    .filter((item: any) => !!item.asset_url);
}

function buildTyphoonMarkdownSummary(payload: any): string {
  const prob = extractTyphoonProbabilityResult(payload);
  if (!prob || typeof prob !== "object") return "台风分析已完成。";
  const scope = String(prob?.model_scope || prob?.input?.model_scope || "total").toLowerCase();
  const m = prob?.metrics || {};
  const input = prob?.input || {};
  const lat = input?.lat ?? "--";
  const lon = input?.lon ?? "--";
  const radius = input?.radius_km ?? "--";

  if (scope === "scs") {
    const cond = Number(m?.p_cond_impact_given_SCS);
    const abs = Number(m?.p_abs_impact_and_SCS);
    const pYear = Number(m?.p_year);
    const risk = classifyRisk(cond);
    return [
      "### 台风预测结论（SCS）",
      `目标点位于 lat=${lat}、lon=${lon}，统计半径 ${radius}km。基于南海样本回溯，这个点位的台风影响风险为**${risk}**。`,
      `从已进入南海的历史台风看，命中该点位的条件概率约为 **${formatPct(cond)}**；若按全部样本计，绝对命中概率约为 **${formatPct(abs)}**；折算成年尺度，年内至少受一次影响的概率约为 **${formatPct(pYear)}**。`,
      "这是一种历史统计意义上的概率结论，不表示单个台风过程的确定性落点，但可以作为站址风险筛查和方案比选的先验参考。",
      "",
      "### 关键指标",
      `- 目标点：lat=${lat}，lon=${lon}，R=${radius}km`,
      `- 样本总数（N_all）：${m?.N_all ?? "--"}`,
      `- 入南海样本（N_enterSCS）：${m?.N_enterSCS ?? "--"}`,
      `- 命中样本（N_hit）：${m?.N_hit ?? "--"}`,
      `- 条件概率 P(impact|SCS)：${formatPct(cond)}`,
      `- 绝对概率 P(impact∩SCS)：${formatPct(abs)}`,
      `- 年命中概率 P_year：${formatPct(pYear)}`,
    ].join("\n");
  }

  const pStorm = Number(m?.p_storm);
  const pYear = Number(m?.p_year);
  const risk = classifyRisk(pStorm);
  return [
    "### 台风预测结论（Total）",
    `目标点位于 lat=${lat}、lon=${lon}，统计半径 ${radius}km。基于全样本回溯，这个点位的历史台风影响风险为**${risk}**。`,
    `按风暴事件计，单个台风命中该点位的概率约为 **${formatPct(pStorm)}**；折算到年尺度，年内至少受一次影响的概率约为 **${formatPct(pYear)}**。`,
    "该结论反映的是历史统计风险，不替代具体台风过程的路径和强度预报。",
    "",
    "### 关键指标",
    `- 目标点：lat=${lat}，lon=${lon}，R=${radius}km`,
    `- 台风总数（N_storm）：${m?.N_storm ?? "--"}`,
    `- 命中样本（N_hit）：${m?.N_hit ?? "--"}`,
    `- 风暴命中概率 P_storm：${formatPct(pStorm)}`,
    `- 年命中概率 P_year：${formatPct(pYear)}`,
  ].join("\n");
}

function applyTyphoonNarrative(payload: ChatResponse): ChatResponse {
  if (!extractTyphoonProbabilityResult(payload)) return payload;
  const summary = buildTyphoonMarkdownSummary(payload);
  const existingBlocks = Array.isArray(payload?.ui_blocks) ? payload.ui_blocks.filter((b) => b.type !== "message") : [];
  return {
    ...payload,
    answer: summary,
    ui_blocks: [{ type: "message", role: "assistant", content: summary }, ...existingBlocks],
  };
}

export default function Page() {
  const [backendUrl, setBackendUrl] = useState(process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8787");
  const [mode, setMode] = useState("auto");
  const [userPrompt, setUserPrompt] = useState("");
  const [windAnalysisFilePath, setWindAnalysisFilePath] = useState("/share/home/lijiyao/CCCC/Wind-Agent/wind_data/wind condition @Akida.xlsx");
  const [sidebarWidth, setSidebarWidth] = useState(340);
  const [imagePreview, setImagePreview] = useState<{ src: string; title: string } | null>(null);
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
  const [showHealthDetails, setShowHealthDetails] = useState(false);

  const [mapSpec, setMapSpec] = useState<any>(null);
  const [mapInfo, setMapInfo] = useState("无地图数据。");
  const [csvFile, setCsvFile] = useState<File | null>(null);

  const mapRef = useRef<LeafletMap | null>(null);
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
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
  const sideBlockTypes = useMemo(() => new Set(["agentic_trace_timeline", "metrics", "meta", "agentic_grades"]), []);

  const structuralBlocks = useMemo(() => {
    const merged = [...blocks];
    if (response?.retrieval_metrics && !merged.some((b) => b.type === "metrics")) {
      merged.push({ type: "metrics", items: response.retrieval_metrics });
    }
    return merged;
  }, [blocks, response?.retrieval_metrics]);

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
    const filteredBlocks = effectiveBlocks.filter((b) => b.type !== "actions" && b.type !== "json" && !isVerboseBatchJsonBlock(b));
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
    const typhoonUiOnlyMap = mode === "typhoon_model";

    if (evt.event === "token") {
      if (typhoonUiOnlyMap) return;
      const token = String(evt.data?.text || "");
      if (token) setStreamedAnswer((prev) => prev + token);
      return;
    }

    if (evt.event === "block") {
      if (typhoonUiOnlyMap) return;
      if (evt.data && typeof evt.data === "object") setBlocks((prev) => [...prev, evt.data as UiBlock]);
      return;
    }

    if (evt.event === "workflow") {
      if (typhoonUiOnlyMap) {
        const spec = extractMapSpec(evt.data);
        if (spec?.center) {
          setMapSpec(spec);
          setMapInfo(JSON.stringify(spec, null, 2));
        }
        return;
      }
      const spec = extractMapSpec(evt.data);
      if (spec?.center) {
        setMapSpec(spec);
        setMapInfo(JSON.stringify(spec, null, 2));
      }
      return;
    }

    if (evt.event === "error") {
      setUiStatus(String(evt.data?.payload?.error || evt.data?.error || "流式请求失败"), "err");
      return;
    }

    if (evt.event === "done") {
      const payload = evt.data as ChatResponse;
      if (typhoonUiOnlyMap) {
        const summary = buildTyphoonMarkdownSummary(payload);
        const spec = extractMapSpec(payload);
        const patched: ChatResponse = {
          ...payload,
          answer: summary,
          ui_blocks: [{ type: "message", role: "assistant", content: summary }],
        };
        if (spec?.center) {
          setMapSpec(spec);
          setMapInfo(JSON.stringify(spec, null, 2));
        }
        setStreamedAnswer("");
        setResponse(patched);
        setBlocks([{ type: "message", role: "assistant", content: summary }]);
        setRawText(JSON.stringify(patched, null, 2));
        setRuntimeText(
          JSON.stringify(
            {
              client_time: new Date().toISOString(),
              elapsed_seconds: patched?.elapsed_seconds ?? "--",
              mode: patched?.mode ?? mode,
            },
            null,
            2,
          ),
        );
        setUiStatus("请求成功。", "ok");
        return;
      }
      const normalizedPayload: ChatResponse = { ...(payload || {}) };
      const primaryAnswer = extractPrimaryAnswer(normalizedPayload);
      if (!normalizedPayload.answer && primaryAnswer) {
        normalizedPayload.answer = primaryAnswer;
      }
      if (!Array.isArray(normalizedPayload.ui_blocks) && primaryAnswer) {
        normalizedPayload.ui_blocks = [{ type: "message", role: "assistant", content: primaryAnswer }];
      }
      const finalPayload = applyTyphoonNarrative(normalizedPayload);

      setResponse(finalPayload);
      setRawText(JSON.stringify(finalPayload, null, 2));
      setRuntimeText(
        JSON.stringify(
          {
            client_time: new Date().toISOString(),
            elapsed_seconds: finalPayload?.elapsed_seconds ?? "--",
            mode: finalPayload?.mode ?? mode,
          },
          null,
          2,
        ),
      );
      if (Array.isArray(finalPayload?.ui_blocks) && finalPayload.ui_blocks.length) {
        setBlocks((prev) => mergeBlocks(prev, finalPayload.ui_blocks!));
      }
      const galleryItems = extractWindAnalysisGalleryItems(finalPayload);
      if (galleryItems.length) {
        setBlocks((prev) => mergeBlocks(prev, [{ type: "gallery", title: "分析图", items: galleryItems }]));
      }

      const spec = extractMapSpec(finalPayload);
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
      const summary = extractPrimaryAnswer(json);
      const charts = Array.isArray(json?.analysis?.data?.charts) ? json.analysis.data.charts : [];
      const galleryItems = charts
        .map((item: any) => ({
          title: String(item?.title || "analysis-chart"),
          asset_url: String(item?.data_url || item?.path || ""),
        }))
        .filter((item: any) => !!item.asset_url);
      return {
        ok: json?.success !== false,
        mode: "wind_analysis",
        answer: summary,
        request_id: json?.request_id,
        analysis: json?.analysis,
        elapsed_seconds: json?.elapsed_seconds,
        ui_blocks: Array.isArray(json?.ui_blocks)
          ? json.ui_blocks
          : [
              { type: "message", role: "assistant", content: summary || "Agent finished." },
              ...(galleryItems.length ? [{ type: "gallery", title: "分析图", items: galleryItems }] : []),
              { type: "json", title: "Analysis", data: json?.analysis || {} },
            ],
      };
    }

    const mapped: ChatResponse = { ...(json || {}) };
    const primaryAnswer = extractPrimaryAnswer(mapped);
    if (!mapped.answer && primaryAnswer) {
      mapped.answer = primaryAnswer;
    }
    if (!Array.isArray(mapped.ui_blocks) && primaryAnswer) {
      mapped.ui_blocks = [{ type: "message", role: "assistant", content: primaryAnswer }];
    }
    if (!mapped.mode) mapped.mode = payload?.mode || "auto";
    return applyTyphoonNarrative(mapped);
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

    let effectivePrompt = userPrompt;
    if (mode === "wind_analysis" && windAnalysisFilePath.trim()) {
      const p = windAnalysisFilePath.trim();
      if (!effectivePrompt.includes(p)) {
        effectivePrompt = `${effectivePrompt.trim()}\n\n风况分析输入文件：${p}`.trim();
      }
    }

    const scopedSessionId = resolveScopedSessionId(sessionId, mode);
    const payload = buildPayload({
      sessionId: scopedSessionId,
      mode,
      userPrompt: effectivePrompt,
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
      const json = applyTyphoonNarrative(fallback.response);
      const typhoonUiOnlyMap = mode === "typhoon_model";
      if (typhoonUiOnlyMap) {
        const summary = buildTyphoonMarkdownSummary(json);
        const spec = extractMapSpec(json);
        const patched: ChatResponse = {
          ...json,
          answer: summary,
          ui_blocks: [{ type: "message", role: "assistant", content: summary }],
        };
        setResponse(patched);
        setBlocks([{ type: "message", role: "assistant", content: summary }]);
        if (spec?.center) {
          setMapSpec(spec);
          setMapInfo(JSON.stringify(spec, null, 2));
        }
      } else {
        setResponse(json);
        const baseBlocks = Array.isArray(json?.ui_blocks) ? json.ui_blocks : [];
        const galleryItems = extractWindAnalysisGalleryItems(json);
        const appended = galleryItems.length ? mergeBlocks(baseBlocks, [{ type: "gallery", title: "分析图", items: galleryItems }]) : baseBlocks;
        setBlocks(appended);
      }
      const spec = extractMapSpec(json);
      if (spec?.center) {
        setMapSpec(spec);
        setMapInfo(JSON.stringify(spec, null, 2));
      }
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
    setShowHealthDetails(false);
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

  async function downloadImage(src: string, title: string) {
    const safeName = (title || "image").replace(/[\\/:*?"<>|]+/g, "_");
    if (!src) return;
    if (/^data:/i.test(src)) {
      const a = document.createElement("a");
      a.href = src;
      a.download = `${safeName}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return;
    }
    try {
      const resp = await fetch(src);
      if (!resp.ok) throw new Error(`download failed: ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${safeName}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      window.open(src, "_blank", "noopener,noreferrer");
    }
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
    if (!mapSpec?.center) {
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      mapLayersRef.current = [];
      return;
    }
    let cancelled = false;

    (async () => {
      const L = await import("leaflet");
      if (cancelled) return;
      const container = mapContainerRef.current;
      if (!container) return;

      if (!mapRef.current) {
        mapRef.current = L.map(container);
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
      <main
        className={`chat-shell ${showSettings ? "with-sidebar" : "sidebar-collapsed"}`}
        style={{ ["--sidebar-width" as any]: `${sidebarWidth}px` }}
      >
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
                      <div><label>模式</label><select value={mode} onChange={(e) => setMode(e.target.value)}><option value="auto">自动路由</option><option value="wind_analysis">风况分析</option><option value="typhoon_model">台风预测</option><option value="llm_direct">大模型问答</option><option value="rag">RAG</option></select></div>
                      <div><label>后端地址</label><input value={backendUrl} onChange={(e) => setBackendUrl(e.target.value)} /></div>
                      <div><label>temperature</label><input type="number" step="0.1" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} /></div>
                      <div><label>max_tokens</label><input type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} /></div>
                      <div><label>top_k</label><input type="number" value={topK} onChange={(e) => setTopK(Number(e.target.value))} /></div>
                    </div>
                  </div>

                  <div className="settings-block">
                    <div className="settings-title">布局</div>
                    <div>
                      <label>设置栏宽度（{sidebarWidth}px）</label>
                      <input
                        type="range"
                        min={280}
                        max={520}
                        step={10}
                        value={sidebarWidth}
                        onChange={(e) => setSidebarWidth(Number(e.target.value))}
                      />
                    </div>
                  </div>

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

                  <div className="settings-block">
                    <div className="settings-title">工具</div>
                    <div className="inline-actions">
                      <button className="ghost-btn" onClick={checkHealth}>健康检查</button>
                      <button className="ghost-btn" onClick={saveResult}>下载结果</button>
                      {healthInfo ? (
                        <button className="ghost-btn" onClick={() => setShowHealthDetails((v) => !v)}>
                          {showHealthDetails ? "隐藏详细信息" : "详细信息"}
                        </button>
                      ) : null}
                    </div>
                    <div>
                      <label>风况分析输入文件</label>
                      <div className="inline-actions">
                        <button
                          className="ghost-btn"
                          onClick={() => {
                            if (!windAnalysisFilePath.trim()) return;
                            setUserPrompt((prev) => {
                              const text = (prev || "").trim();
                              const line = `风况分析输入文件：${windAnalysisFilePath.trim()}`;
                              if (text.includes(windAnalysisFilePath.trim())) return text;
                              return `${text}\n${line}`.trim();
                            });
                          }}
                        >
                          插入到输入框
                        </button>
                        <input
                          value={windAnalysisFilePath}
                          onChange={(e) => setWindAnalysisFilePath(e.target.value)}
                          placeholder="输入风况分析 Excel 路径"
                        />
                      </div>
                    </div>
                    <div className={`status-chip ${statusKind}`}>{status}</div>
                    <pre className="mono slim">{runtimeText === "{}" ? '{\n  "client_time": "--",\n  "elapsed_seconds": "--",\n  "mode": "--"\n}' : runtimeText}</pre>
                    {healthInfo && showHealthDetails ? (
                      <pre className="mono slim health-details">{JSON.stringify(healthInfo, null, 2)}</pre>
                    ) : null}
                  </div>
                </div>
              </section>
            </div>
          </aside>

          <section className="chat-main">
            <section className="chat-header">
              <div>
                <h1>中交智慧风电智能体平台</h1>
                <p className="subtle">面向风电知识问答、RAG 检索与台风分析</p>
              </div>
            </section>

            <section className="chat-body">
          {!hasResultSection ? (
            <div className="empty-state card-lite">
              <div className="empty-title">今天想分析什么？</div>
              <div className="empty-subtitle">支持风况分析、台风预测、大模型问答、RAG 与地图结果展示</div>
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
                        const src = resolveGallerySrc(backendUrl, String(it?.asset_url || it?.src || ""));
                        const indices = Array.isArray(it?.indices)
                          ? it.indices.map((x: any) => String(x || "").trim()).filter(Boolean)
                          : [];
                        const indexLabel = indices.length ? `[${indices.join(", ")}] ` : it?.index ? `[${String(it.index)}] ` : "";
                        const titleText = String(it?.title || "image");
                        return (
                          <div key={`${i}-g-${idx}`} className="gallery-card">
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={src} alt={titleText} onClick={() => setImagePreview({ src, title: titleText })} />
                            <div className="gallery-title">{`${indexLabel}${titleText}`}</div>
                            <div className="gallery-actions">
                              <button className="ghost-btn" onClick={() => setImagePreview({ src, title: titleText })}>放大</button>
                              <button className="ghost-btn" onClick={() => void downloadImage(src, titleText)}>下载</button>
                            </div>
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
                <div id="map" ref={mapContainerRef} />
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
      {imagePreview ? (
        <div className="image-modal" onClick={() => setImagePreview(null)}>
          <div className="image-modal-inner" onClick={(e) => e.stopPropagation()}>
            <div className="image-modal-top">
              <div className="image-modal-title">{imagePreview.title}</div>
              <div className="inline-actions">
                <button className="ghost-btn" onClick={() => void downloadImage(imagePreview.src, imagePreview.title)}>下载</button>
                <button className="ghost-btn" onClick={() => setImagePreview(null)}>关闭</button>
              </div>
            </div>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={imagePreview.src} alt={imagePreview.title} className="image-modal-img" />
          </div>
        </div>
      ) : null}
    </div>
  );
}
