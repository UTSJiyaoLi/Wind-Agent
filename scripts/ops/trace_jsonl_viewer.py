#!/usr/bin/env python
"""Offline JSONL trace viewer for Wind-Agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import streamlit as st


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        t = line.strip()
        if not t:
            continue
        try:
            row = json.loads(t)
            row["_line"] = i
            rows.append(row)
        except Exception:
            continue
    return rows


def to_ts(ms: Any) -> str:
    try:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(int(ms) / 1000.0).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "-"


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--trace-dir", default="storage/traces")
    cli_args, _ = parser.parse_known_args()

    st.set_page_config(page_title="Wind-Agent Trace Viewer", layout="wide")
    st.title("Wind-Agent Offline Trace Viewer")

    default_dir = Path(cli_args.trace_dir)
    trace_dir_str = st.sidebar.text_input("Trace dir", value=str(default_dir))
    trace_dir = Path(trace_dir_str)
    files = sorted(trace_dir.glob("*.jsonl")) if trace_dir.exists() else []
    if not files:
        st.warning(f"No *.jsonl file found in: {trace_dir}")
        return

    file_map = {f.name: f for f in files}
    selected_file = st.sidebar.selectbox("Trace file", options=list(file_map.keys()), index=len(file_map) - 1)
    rows = load_jsonl(file_map[selected_file])
    if not rows:
        st.warning("Selected file has no valid JSON rows.")
        return

    by_trace: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        tid = str(r.get("trace_id") or "").strip()
        if not tid:
            continue
        by_trace.setdefault(tid, []).append(r)
    if not by_trace:
        st.warning("No trace_id found in selected file.")
        return

    st.sidebar.write(f"Traces: {len(by_trace)}")
    trace_ids = sorted(by_trace.keys())
    selected_trace = st.sidebar.selectbox("trace_id", options=trace_ids, index=len(trace_ids) - 1)
    trace_rows = by_trace[selected_trace]

    spans: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for r in trace_rows:
        if r.get("record_type") == "span":
            spans.append(
                {
                    "span": r.get("span"),
                    "status": r.get("status"),
                    "start": to_ts(r.get("started_at_ms")),
                    "end": to_ts(r.get("ended_at_ms")),
                    "duration_ms": r.get("duration_ms"),
                    "error": r.get("error", ""),
                }
            )
        elif r.get("record_type") == "event":
            events.append(
                {
                    "event": r.get("event"),
                    "time": to_ts(r.get("ts_ms")),
                    "metadata": json.dumps(r.get("metadata") or {}, ensure_ascii=False),
                }
            )

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", len(trace_rows))
    c2.metric("Spans", len(spans))
    c3.metric("Events", len(events))

    st.subheader("Spans")
    st.dataframe(spans, use_container_width=True)

    st.subheader("Events")
    st.dataframe(events, use_container_width=True)

    st.subheader("Raw JSON")
    st.json(trace_rows)


if __name__ == "__main__":
    main()
