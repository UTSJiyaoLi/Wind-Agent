from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
import streamlit as st

st.set_page_config(page_title="Wind Agent UI", layout="wide")
st.title("Wind Resource Agent")

default_api_base = os.getenv("WIND_AGENT_API_BASE", "http://127.0.0.1:8005")
api_base = st.sidebar.text_input("API Base URL", value=default_api_base)
auto_refresh = st.sidebar.checkbox("Auto Refresh (2s)", value=True)

if "task_id" not in st.session_state:
    st.session_state.task_id = ""

with st.form("create_task"):
    excel_path = st.text_input("Excel Path", value=r"C:\wind-agent\wind_data\wind condition @Akida.xlsx")
    submitted = st.form_submit_button("Run Analysis")

if submitted:
    try:
        resp = requests.post(f"{api_base}/tasks", json={"excel_path": excel_path}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        st.session_state.task_id = payload["task_id"]
        st.success(f"Task created: {st.session_state.task_id}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to create task: {exc}")

task_id = st.text_input("Task ID", value=st.session_state.task_id)

if st.button("Refresh Task Status") or (auto_refresh and task_id):
    if task_id:
        try:
            resp = requests.get(f"{api_base}/tasks/{task_id}", timeout=10)
            resp.raise_for_status()
            task = resp.json()

            st.write(f"Status: **{task['status']}**")
            st.write(task.get("message", ""))

            if task.get("error"):
                st.error(task["error"])

            result = task.get("result") or {}
            if result:
                st.subheader("Flow Summary")
                st.write(result.get("summary", ""))

                analysis = result.get("analysis") or {}
                st.subheader("Structured JSON")
                st.json(analysis)

                charts = analysis.get("charts") or {}
                if charts:
                    st.subheader("Charts")
                    cols = st.columns(2)
                    for i, (_, chart_path) in enumerate(charts.items()):
                        p = Path(chart_path)
                        if p.exists():
                            with cols[i % 2]:
                                st.image(str(p), caption=p.name, use_container_width=True)

            if auto_refresh and task.get("status") in {"pending", "running"}:
                time.sleep(2)
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to query task: {exc}")
