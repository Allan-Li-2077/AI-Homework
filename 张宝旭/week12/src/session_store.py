"""Local JSONL-backed session store for short-term conversation memory."""

from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _short_title(text: str, limit: int = 24) -> str:
    text = (text or "").strip().replace("\n", " ")
    if not text:
        return "新会话"
    return text[:limit] + ("…" if len(text) > limit else "")


@dataclass
class SessionRecord:
    session_id: str
    title: str
    mode: str
    created_at: str
    updated_at: str
    messages: list[dict[str, Any]]
    turns: list[dict[str, Any]]

    @classmethod
    def new(
        cls,
        title: str | None = None,
        mode: str = "manual",
    ) -> "SessionRecord":
        now = _utc_now()
        return cls(
            session_id=f"sess_{uuid.uuid4().hex[:12]}",
            title=_short_title(title or "新会话"),
            mode=mode,
            created_at=now,
            updated_at=now,
            messages=[],
            turns=[],
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionRecord":
        return cls(
            session_id=str(data.get("session_id", "")),
            title=str(data.get("title", "新会话")),
            mode=str(data.get("mode", "manual")),
            created_at=str(data.get("created_at", _utc_now())),
            updated_at=str(data.get("updated_at", _utc_now())),
            messages=list(data.get("messages", [])),
            turns=list(data.get("turns", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
            "turns": self.turns,
        }


class JsonlSessionStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionRecord] = {}
        self.load()

    def load(self) -> None:
        with self._lock:
            self._sessions = {}
            if not self.path.exists():
                return

            for raw_line in self.path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record = SessionRecord.from_dict(data)
                if record.session_id:
                    self._sessions[record.session_id] = record

    def _write_all_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        lines = [
            json.dumps(rec.to_dict(), ensure_ascii=False)
            for rec in self.list_records()
        ]
        tmp_path.write_text(
            "\n".join(lines) + ("\n" if lines else ""),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def list_records(self) -> list[SessionRecord]:
        with self._lock:
            return sorted(
                self._sessions.values(),
                key=lambda rec: rec.updated_at,
                reverse=True,
            )

    def list_sessions(self) -> list[dict[str, Any]]:
        return [self._summary(rec) for rec in self.list_records()]

    def _summary(self, rec: SessionRecord) -> dict[str, Any]:
        user_turns = [t for t in rec.turns if t.get("role") == "user"]
        last_question = user_turns[-1]["content"] if user_turns else ""
        return {
            "session_id": rec.session_id,
            "title": rec.title,
            "mode": rec.mode,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
            "turn_count": len(rec.turns),
            "message_count": len(rec.messages),
            "last_question": last_question,
        }

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            record = self._sessions.get(session_id)
            return deepcopy(record) if record else None

    def create(self, title: str | None = None, mode: str = "manual") -> SessionRecord:
        with self._lock:
            record = SessionRecord.new(title=title, mode=mode)
            self._sessions[record.session_id] = record
            self._write_all_locked()
            return deepcopy(record)

    def ensure(
        self,
        session_id: str | None,
        title: str | None = None,
        mode: str = "manual",
    ) -> SessionRecord:
        if session_id:
            existing = self.get(session_id)
            if existing is not None:
                return existing
        with self._lock:
            record = SessionRecord.new(title=title, mode=mode)
            if session_id:
                record.session_id = session_id
            self._sessions[record.session_id] = record
            self._write_all_locked()
            return deepcopy(record)

    def save(self, record: SessionRecord) -> SessionRecord:
        with self._lock:
            self._sessions[record.session_id] = deepcopy(record)
            self._write_all_locked()
            return deepcopy(record)

    def append_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        mode: str,
        messages: list[dict[str, Any]],
    ) -> SessionRecord:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                record = SessionRecord.new(title=question, mode=mode)
                record.session_id = session_id
                self._sessions[session_id] = record

            record.mode = mode or record.mode
            if record.title == "新会话":
                record.title = _short_title(question)
            record.updated_at = _utc_now()
            record.messages = deepcopy(messages)
            record.turns.extend(
                [
                    {
                        "role": "user",
                        "content": question,
                        "at": record.updated_at,
                    },
                    {
                        "role": "assistant",
                        "content": answer,
                        "at": record.updated_at,
                    },
                ]
            )
            self._write_all_locked()
            return deepcopy(record)

    def update_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        mode: str | None = None,
    ) -> SessionRecord:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                record = SessionRecord.new(mode=mode or "manual")
                record.session_id = session_id
                self._sessions[session_id] = record
            if mode:
                record.mode = mode
            record.updated_at = _utc_now()
            record.messages = deepcopy(messages)
            self._write_all_locked()
            return deepcopy(record)

    def reset(self) -> None:
        with self._lock:
            self._sessions = {}
            self._write_all_locked()
