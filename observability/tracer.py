"""Local/offline tracing with JSONL backend and LangSmith-compatible placeholder."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from langsmith import Client as _LangSmithClient
    from langsmith.run_trees import RunTree as _LangSmithRunTree
except Exception:
    _LangSmithClient = None
    _LangSmithRunTree = None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _bool_env(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


class _NullSpan:
    def add(self, _data: dict[str, Any]) -> None:
        return

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _tb: Any) -> bool:
        return False


class _Span:
    def __init__(self, tracer: "BaseTracer", trace_id: str, name: str, metadata: dict[str, Any] | None = None):
        self.tracer = tracer
        self.trace_id = trace_id
        self.name = name
        self.started_ms = _now_ms()
        self.metadata: dict[str, Any] = dict(metadata or {})

    def add(self, data: dict[str, Any]) -> None:
        self.metadata.update(data or {})

    def __enter__(self) -> "_Span":
        return self

    def __exit__(self, exc_type: Any, exc: Any, _tb: Any) -> bool:
        ended_ms = _now_ms()
        payload = {
            "record_type": "span",
            "trace_id": self.trace_id,
            "span": self.name,
            "started_at_ms": self.started_ms,
            "ended_at_ms": ended_ms,
            "duration_ms": max(0, ended_ms - self.started_ms),
            "status": "error" if exc is not None else "ok",
            "metadata": self.metadata,
        }
        if exc is not None:
            payload["error"] = str(exc)
        self.tracer._write(payload)
        return False


class BaseTracer:
    backend = "none"
    enabled = False

    def new_trace_id(self) -> str:
        return uuid4().hex

    def summarize_text(self, text: str, max_len: int = 120) -> str:
        t = " ".join(str(text or "").split())
        if len(t) <= max_len:
            return t
        return t[: max(0, max_len - 3)] + "..."

    def redact_contexts(self, contexts: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in contexts[: max(0, limit)]:
            rows.append(
                {
                    "rank": item.get("rank"),
                    "doc_id": item.get("doc_id"),
                    "chunk_id": item.get("chunk_id"),
                    "score": item.get("score"),
                    "file_name": item.get("file_name"),
                    "page_no": item.get("page_no"),
                }
            )
        return rows

    def span(self, _trace_id: str, _name: str, metadata: dict[str, Any] | None = None) -> _NullSpan:
        return _NullSpan()

    def event(self, _trace_id: str, _name: str, metadata: dict[str, Any] | None = None) -> None:
        return

    def info(self) -> dict[str, Any]:
        return {"backend": self.backend, "enabled": bool(self.enabled)}

    def _write(self, _payload: dict[str, Any]) -> None:
        return


class JsonlTracer(BaseTracer):
    backend = "jsonl"

    def __init__(self, *, enabled: bool, trace_dir: str, redaction_mode: str = "summary_id"):
        self.enabled = bool(enabled)
        self.trace_dir = Path(trace_dir)
        self.redaction_mode = str(redaction_mode or "summary_id")
        self._lock = threading.Lock()
        if self.enabled:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            self._file_path = self.trace_dir / f"trace_{time.strftime('%Y%m%d')}.jsonl"
        else:
            self._file_path = self.trace_dir / "trace_disabled.jsonl"

    def span(self, trace_id: str, name: str, metadata: dict[str, Any] | None = None) -> _NullSpan | _Span:
        if not self.enabled:
            return _NullSpan()
        return _Span(self, trace_id=trace_id, name=name, metadata=metadata)

    def event(self, trace_id: str, name: str, metadata: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self._write(
            {
                "record_type": "event",
                "trace_id": trace_id,
                "event": name,
                "ts_ms": _now_ms(),
                "metadata": metadata or {},
            }
        )

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "enabled": bool(self.enabled),
            "trace_dir": str(self.trace_dir),
            "redaction_mode": self.redaction_mode,
        }

    def _write(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with self._file_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")


class LangSmithTracer(BaseTracer):
    backend = "langsmith"

    def __init__(self, *, enabled: bool, endpoint: str = "", project: str = "", api_key: str = ""):
        self.enabled = bool(enabled)
        self.endpoint = str(endpoint or "")
        self.project = str(project or "wind-agent-rag-eval")
        self.api_key = str(api_key or "")
        self._lock = threading.Lock()
        self._roots: dict[str, Any] = {}
        self._client = None
        self._note = "ready"

        if not self.enabled:
            self._note = "disabled_by_config"
            return

        if _LangSmithClient is None or _LangSmithRunTree is None:
            self.enabled = False
            self._note = "langsmith_package_unavailable"
            return
        if not self.api_key:
            self.enabled = False
            self._note = "missing_api_key"
            return

        try:
            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.endpoint:
                kwargs["api_url"] = self.endpoint
            self._client = _LangSmithClient(**kwargs)
        except Exception as exc:
            self.enabled = False
            self._note = f"client_init_failed:{exc}"

    def _ensure_root(self, trace_id: str) -> Any | None:
        if not self.enabled or self._client is None or _LangSmithRunTree is None:
            return None
        key = str(trace_id or "")
        with self._lock:
            root = self._roots.get(key)
            if root is not None:
                return root
            root = _LangSmithRunTree(
                name="wind_agent_request",
                run_type="chain",
                project_name=self.project,
                client=self._client,
                inputs={"trace_id": key},
                extra={"metadata": {"trace_id": key}},
            )
            root.post()
            self._roots[key] = root
            return root

    def _finalize_root(self, trace_id: str, status: str) -> None:
        key = str(trace_id or "")
        with self._lock:
            root = self._roots.pop(key, None)
        if root is None:
            return
        try:
            root.end(outputs={"status": status, "trace_id": key})
            root.patch()
        except Exception:
            return

    def _create_span_run(self, trace_id: str, name: str, metadata: dict[str, Any]) -> Any | None:
        root = self._ensure_root(trace_id)
        if root is None:
            return None
        try:
            run = root.create_child(
                name=name,
                run_type="chain",
                inputs={"trace_id": trace_id},
                extra={"metadata": metadata},
            )
            run.post()
            return run
        except Exception:
            return None

    def span(self, trace_id: str, name: str, metadata: dict[str, Any] | None = None) -> _NullSpan | "_LangSmithSpan":
        if not self.enabled:
            return _NullSpan()
        return _LangSmithSpan(self, trace_id=trace_id, name=name, metadata=metadata or {})

    def event(self, trace_id: str, name: str, metadata: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        run = self._create_span_run(trace_id, f"event:{name}", metadata or {})
        if run is None:
            return
        try:
            run.end(outputs={"event": name, "metadata": metadata or {}, "status": "ok"})
            run.patch()
        except Exception:
            return

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "enabled": bool(self.enabled),
            "endpoint": self.endpoint,
            "project": self.project,
            "note": self._note,
        }


class _LangSmithSpan:
    def __init__(self, tracer: LangSmithTracer, trace_id: str, name: str, metadata: dict[str, Any] | None = None):
        self.tracer = tracer
        self.trace_id = str(trace_id or "")
        self.name = str(name or "span")
        self.metadata: dict[str, Any] = dict(metadata or {})
        self.run = None

    def add(self, data: dict[str, Any]) -> None:
        self.metadata.update(data or {})

    def __enter__(self) -> "_LangSmithSpan":
        self.run = self.tracer._create_span_run(self.trace_id, self.name, self.metadata)
        return self

    def __exit__(self, exc_type: Any, exc: Any, _tb: Any) -> bool:
        status = "error" if exc is not None else "ok"
        if self.run is not None:
            try:
                out: dict[str, Any] = {"status": status, "metadata": self.metadata}
                if exc is not None:
                    out["error"] = str(exc)
                self.run.end(outputs=out)
                self.run.patch()
            except Exception:
                pass
        if self.name == "request":
            self.tracer._finalize_root(self.trace_id, status)
        return False


def build_tracer_from_args(args: Any) -> BaseTracer:
    backend = str(getattr(args, "obs_backend", "jsonl") or "jsonl").strip().lower()
    enabled = _bool_env(getattr(args, "obs_enabled", True), default=True)
    if backend == "none":
        return BaseTracer()
    if backend == "langsmith":
        return LangSmithTracer(
            enabled=enabled,
            endpoint=str(getattr(args, "langsmith_endpoint", "") or ""),
            project=str(getattr(args, "langsmith_project", "") or ""),
            api_key=str(getattr(args, "langsmith_api_key", "") or ""),
        )
    return JsonlTracer(
        enabled=enabled,
        trace_dir=str(getattr(args, "obs_trace_dir", "storage/traces") or "storage/traces"),
        redaction_mode=str(getattr(args, "obs_redaction_mode", "summary_id") or "summary_id"),
    )
