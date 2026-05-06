"""Session-scoped conversation and memory persistence."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _clip_text(value: Any, limit: int = 400) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _extract_slots_from_text(text: str) -> dict[str, Any]:
    raw = str(text or "")
    slots: dict[str, Any] = {}

    def _extract_float(patterns: list[str]) -> float | None:
        for pattern in patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if not match:
                continue
            try:
                return float(match.group(1))
            except Exception:
                continue
        return None

    excel_match = re.search(r'([A-Za-z]:[\\/][^"\n\r]*?\.(?:xlsx|xls))', raw, flags=re.IGNORECASE)
    if excel_match:
        slots["excel_path"] = excel_match.group(1).strip().strip('"').strip("'")

    lat = _extract_float([r"(?:lat|latitude|纬度)\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)"])
    lon = _extract_float([r"(?:lon|lng|longitude|经度)\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)"])
    radius = _extract_float([r"(?:radius|radius_km|半径)\s*[:=]?\s*([-+]?\d+(?:\.\d+)?)"])
    year_start = _extract_float([r"(?:year_start|起始年份|开始年份)\s*[:=]?\s*(\d{4})"])
    year_end = _extract_float([r"(?:year_end|结束年份|终止年份)\s*[:=]?\s*(\d{4})"])

    if lat is not None:
        slots["lat"] = lat
    if lon is not None:
        slots["lon"] = lon
    if radius is not None:
        slots["radius_km"] = radius
    if year_start is not None:
        slots["year_start"] = int(year_start)
    if year_end is not None:
        slots["year_end"] = int(year_end)
    if re.search(r"\bscs\b|南海", raw, flags=re.IGNORECASE):
        slots["model_scope"] = "scs"
    elif re.search(r"\btotal\b|全样本", raw, flags=re.IGNORECASE):
        slots["model_scope"] = "total"
    return slots


def _extract_preferences(text: str) -> dict[str, Any]:
    raw = str(text or "")
    preferences: dict[str, Any] = {}
    if "中文" in raw:
        preferences["language"] = "zh-CN"
    if re.search(r"简洁|简短|直接给结论", raw):
        preferences["answer_style"] = "concise"
    elif re.search(r"详细|展开|具体一点", raw):
        preferences["answer_style"] = "detailed"
    if re.search(r"表格", raw):
        preferences["format"] = "table_friendly"
    return preferences


@dataclass
class SessionRecord:
    session_id: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)


class ConversationStore:
    def __init__(self, root_dir: str = "storage/conversations", max_messages: int = 40) -> None:
        self._lock = threading.Lock()
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_messages = max(6, int(max_messages))

    def get(self, session_id: str) -> SessionRecord:
        sid = str(session_id or "").strip() or "session-anon"
        with self._lock:
            return self._load_unlocked(sid)

    def get_recent_messages(self, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
        record = self.get(session_id)
        return list(record.messages[-max(1, int(limit)) :])

    def get_memory(self, session_id: str) -> dict[str, Any]:
        record = self.get(session_id)
        return dict(record.memory or {})

    def record_turn(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_message: str,
        mode: str,
        tool_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sid = str(session_id or "").strip() or "session-anon"
        user_text = str(user_message or "").strip()
        assistant_text = str(assistant_message or "").strip()
        with self._lock:
            record = self._load_unlocked(sid)
            now = _utc_now_iso()
            record.messages.extend(
                [
                    {"role": "user", "content": user_text, "ts": now, "mode": mode},
                    {"role": "assistant", "content": assistant_text, "ts": now, "mode": mode},
                ]
            )
            record.messages = record.messages[-self._max_messages :]
            record.updated_at = now
            record.memory = self._merge_memory(
                existing=record.memory,
                user_message=user_text,
                assistant_message=assistant_text,
                mode=mode,
                tool_input=tool_input,
            )
            self._persist_unlocked(record)
            return dict(record.memory)

    def _merge_memory(
        self,
        *,
        existing: dict[str, Any],
        user_message: str,
        assistant_message: str,
        mode: str,
        tool_input: dict[str, Any] | None,
    ) -> dict[str, Any]:
        memory = dict(existing or {})
        slots = dict(memory.get("slots") or {})
        slots.update(_extract_slots_from_text(user_message))
        if isinstance(tool_input, dict):
            for key, value in tool_input.items():
                if value is None:
                    continue
                if isinstance(value, (str, int, float, bool, list, dict)):
                    slots[key] = value
        preferences = dict(memory.get("preferences") or {})
        preferences.update(_extract_preferences(user_message))

        open_questions: list[str] = []
        if re.search(r"请提供|请确认|缺少|还需要|请补充", assistant_message):
            open_questions.append(_clip_text(assistant_message, 200))

        memory["last_mode"] = str(mode or "").strip().lower()
        memory["current_goal"] = _clip_text(user_message, 180)
        memory["last_user_message"] = _clip_text(user_message, 240)
        memory["last_assistant_summary"] = _clip_text(assistant_message, 300)
        memory["summary"] = self._build_summary(
            current_goal=memory.get("current_goal", ""),
            slots=slots,
            assistant_summary=memory.get("last_assistant_summary", ""),
        )
        memory["slots"] = slots
        memory["preferences"] = preferences
        memory["open_questions"] = open_questions
        return memory

    def _build_summary(self, *, current_goal: str, slots: dict[str, Any], assistant_summary: str) -> str:
        slot_items: list[str] = []
        for key in ("excel_path", "lat", "lon", "radius_km", "model_scope", "year_start", "year_end"):
            if key not in slots:
                continue
            slot_items.append(f"{key}={slots[key]}")
        parts = [
            f"当前目标: {_clip_text(current_goal, 120)}" if current_goal else "",
            f"已记住参数: {', '.join(slot_items)}" if slot_items else "",
            f"上一轮结论: {_clip_text(assistant_summary, 140)}" if assistant_summary else "",
        ]
        return "\n".join([part for part in parts if part]).strip()

    def _load_unlocked(self, session_id: str) -> SessionRecord:
        path = self._path_for(session_id)
        if not path.exists():
            now = _utc_now_iso()
            return SessionRecord(session_id=session_id, created_at=now, updated_at=now, messages=[], memory={})

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            now = _utc_now_iso()
            return SessionRecord(session_id=session_id, created_at=now, updated_at=now, messages=[], memory={})

        return SessionRecord(
            session_id=str(payload.get("session_id") or session_id),
            created_at=str(payload.get("created_at") or _utc_now_iso()),
            updated_at=str(payload.get("updated_at") or _utc_now_iso()),
            messages=list(payload.get("messages") or []),
            memory=dict(payload.get("memory") or {}),
        )

    def _persist_unlocked(self, record: SessionRecord) -> None:
        payload = {
            "session_id": record.session_id,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "messages": record.messages,
            "memory": record.memory,
        }
        self._path_for(record.session_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _path_for(self, session_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(session_id or "session-anon")).strip("._")
        return self._root / f"{safe or 'session-anon'}.json"


CHAT_SESSION_STORE = ConversationStore()
