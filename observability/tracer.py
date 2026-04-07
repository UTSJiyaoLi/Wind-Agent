"""Local/offline tracing with JSONL backend and LangSmith-compatible placeholder."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


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
    """Placeholder for future self-hosted/cloud LangSmith integration."""

    backend = "langsmith_placeholder"

    def __init__(self, *, enabled: bool, endpoint: str = "", project: str = ""):
        # Placeholder keeps tracing disabled by default until real client integration.
        self.enabled = bool(enabled and False)
        self.endpoint = str(endpoint or "")
        self.project = str(project or "")

    def info(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "enabled": bool(self.enabled),
            "endpoint": self.endpoint,
            "project": self.project,
            "note": "placeholder_only",
        }


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
        )
    return JsonlTracer(
        enabled=enabled,
        trace_dir=str(getattr(args, "obs_trace_dir", "storage/traces") or "storage/traces"),
        redaction_mode=str(getattr(args, "obs_redaction_mode", "summary_id") or "summary_id"),
    )
