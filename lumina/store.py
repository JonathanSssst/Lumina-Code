from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lumina.types import Message, ToolCall

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace TEXT NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    name TEXT,
    seq INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);
"""


@dataclass
class SessionInfo:
    id: int
    title: str
    workspace: str
    created_at: str
    updated_at: str
    message_count: int


def default_db_path(workspace: Path) -> Path:
    """Session DB lives in the project's .lumina dir so it follows the repo."""
    return Path(workspace).resolve() / ".lumina" / "sessions.db"


class SessionStore:
    """SQLite-backed conversation store. Thread-safe for CLI/Web use."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- sessions ---

    def create_session(self, workspace: Path, title: str = "新会话") -> int:
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions(workspace, title, created_at, updated_at) VALUES(?,?,?,?)",
                (str(Path(workspace).resolve()), title, now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_sessions(self, workspace: Path | None = None) -> list[SessionInfo]:
        q = (
            "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS cnt "
            "FROM sessions s"
        )
        params: tuple = ()
        if workspace is not None:
            q += " WHERE s.workspace = ?"
            params = (str(Path(workspace).resolve()),)
        q += " ORDER BY s.updated_at DESC"
        with self._lock:
            rows = self._conn.execute(q, params).fetchall()
        return [
            SessionInfo(
                id=int(r["id"]),
                title=r["title"] or "新会话",
                workspace=r["workspace"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                message_count=int(r["cnt"]),
            )
            for r in rows
        ]

    def get_session(self, session_id: int) -> SessionInfo | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS cnt "
                "FROM sessions s WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SessionInfo(
            id=int(row["id"]),
            title=row["title"] or "新会话",
            workspace=row["workspace"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            message_count=int(row["cnt"]),
        )

    def delete_session(self, session_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.commit()

    def touch(self, session_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?", (_now(), session_id)
            )
            self._conn.commit()

    def set_title(self, session_id: int, title: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now(), session_id),
            )
            self._conn.commit()

    # --- messages ---

    def append_message(self, session_id: int, message: Message) -> None:
        seq = self._next_seq(session_id)
        tool_calls = (
            json.dumps([tc.model_dump() for tc in message.tool_calls], ensure_ascii=False)
            if message.tool_calls
            else None
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages(session_id, role, content, tool_calls, tool_call_id, name, seq) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    session_id,
                    message.role,
                    message.content,
                    tool_calls,
                    message.tool_call_id,
                    message.name,
                    seq,
                ),
            )
            self._conn.commit()

    def get_messages(self, session_id: int) -> list[Message]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY seq",
                (session_id,),
            ).fetchall()
        messages: list[Message] = []
        for r in rows:
            tool_calls = (
                [ToolCall(**tc) for tc in json.loads(r["tool_calls"])] if r["tool_calls"] else None
            )
            messages.append(
                Message(
                    role=r["role"],
                    content=r["content"],
                    tool_calls=tool_calls,
                    tool_call_id=r["tool_call_id"],
                    name=r["name"],
                )
            )
        return messages

    def _next_seq(self, session_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS n FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return int(row["n"])


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
