from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lumina.types import Message, ToolCall, Usage

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
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL UNIQUE REFERENCES sessions(id) ON DELETE CASCADE,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,
    iterations INTEGER NOT NULL DEFAULT 0,
    tool_calls INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
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
            self._conn.execute("DELETE FROM usage WHERE session_id = ?", (session_id,))
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

    def truncate_after_user(self, session_id: int, user_index: int) -> bool:
        """Delete the user_index-th user message (0-based) and everything after it."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq FROM messages WHERE session_id = ? AND role = 'user' ORDER BY seq",
                (session_id,),
            ).fetchall()
        if user_index < 0 or user_index >= len(rows):
            return False
        seq = int(rows[user_index]["seq"])
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE session_id = ? AND seq >= ?", (session_id, seq)
            )
            self._conn.commit()
        return True

    # --- usage / stats ---

    def record_usage(
        self,
        session_id: int,
        usage: Usage,
        *,
        iterations: int = 0,
        tool_calls: int = 0,
    ) -> None:
        """Accumulate one agent run's token usage onto the session (upsert)."""
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE usage SET "
                "prompt_tokens = prompt_tokens + ?, completion_tokens = completion_tokens + ?, "
                "total_tokens = total_tokens + ?, reasoning_tokens = reasoning_tokens + ?, "
                "cached_tokens = cached_tokens + ?, iterations = iterations + ?, "
                "tool_calls = tool_calls + ?, updated_at = ? WHERE session_id = ?",
                (
                    usage.prompt_tokens,
                    usage.completion_tokens,
                    usage.total_tokens,
                    usage.reasoning_tokens,
                    usage.cached_tokens,
                    iterations,
                    tool_calls,
                    now,
                    session_id,
                ),
            )
            if cur.rowcount == 0:
                self._conn.execute(
                    "INSERT INTO usage("
                    "session_id, prompt_tokens, completion_tokens, total_tokens, "
                    "reasoning_tokens, cached_tokens, iterations, tool_calls, updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        session_id,
                        usage.prompt_tokens,
                        usage.completion_tokens,
                        usage.total_tokens,
                        usage.reasoning_tokens,
                        usage.cached_tokens,
                        iterations,
                        tool_calls,
                        now,
                    ),
                )
            self._conn.commit()

    def get_session_usage(self, session_id: int) -> Usage | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT prompt_tokens, completion_tokens, total_tokens, "
                "reasoning_tokens, cached_tokens FROM usage WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return Usage(
            prompt_tokens=int(row["prompt_tokens"]),
            completion_tokens=int(row["completion_tokens"]),
            total_tokens=int(row["total_tokens"]),
            reasoning_tokens=int(row["reasoning_tokens"]),
            cached_tokens=int(row["cached_tokens"]),
        )

    def get_session_stats(self, session_id: int) -> dict:
        """Aggregate stats for one session (usage + message counts + meta)."""
        session = self.get_session(session_id)
        usage = self.get_session_usage(session_id)
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(iterations), 0) AS iterations, "
                "COALESCE(MAX(tool_calls), 0) AS tool_calls FROM usage WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            counts = {
                r["role"]: int(r["n"])
                for r in self._conn.execute(
                    "SELECT role, COUNT(*) AS n FROM messages WHERE session_id = ? GROUP BY role",
                    (session_id,),
                ).fetchall()
            }
        return {
            "id": session_id,
            "title": session.title if session else "新会话",
            "created_at": session.created_at if session else "",
            "updated_at": session.updated_at if session else "",
            "messages": session.message_count if session else 0,
            "counts": {
                "user": counts.get("user", 0),
                "assistant": counts.get("assistant", 0),
                "tool": counts.get("tool", 0),
                "system": counts.get("system", 0),
            },
            "usage": {
                "prompt": usage.prompt_tokens if usage else 0,
                "completion": usage.completion_tokens if usage else 0,
                "total": usage.total_tokens if usage else 0,
                "reasoning": usage.reasoning_tokens if usage else 0,
                "cached": usage.cached_tokens if usage else 0,
            },
            "iterations": int(row["iterations"]),
            "tool_calls": int(row["tool_calls"]),
        }

    # --- search / trend ---

    def search_messages(self, workspace: Path, query: str, limit: int = 30) -> list[dict]:
        """Find user/assistant messages containing ``query`` across sessions."""
        like = f"%{query}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.session_id AS sid, m.role AS role, m.content AS content, s.title AS title "
                "FROM messages m JOIN sessions s ON s.id = m.session_id "
                "WHERE m.role IN ('user', 'assistant') AND m.content IS NOT NULL "
                "  AND m.content LIKE ? AND s.workspace = ? "
                "ORDER BY m.id DESC LIMIT ?",
                (like, str(Path(workspace).resolve()), int(limit)),
            ).fetchall()
        return [
            {
                "session_id": int(r["sid"]),
                "role": r["role"],
                "title": r["title"] or "新会话",
                "snippet": _snippet(r["content"] or "", query),
            }
            for r in rows
        ]

    def usage_trend(self, workspace: Path, limit: int = 60) -> list[dict]:
        """Recent sessions with non-zero token usage, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id AS sid, s.title AS title, s.updated_at AS updated_at, "
                "       u.total_tokens AS total, u.prompt_tokens AS prompt, "
                "       u.completion_tokens AS completion "
                "FROM usage u JOIN sessions s ON s.id = u.session_id "
                "WHERE s.workspace = ? AND u.total_tokens > 0 "
                "ORDER BY s.updated_at DESC LIMIT ?",
                (str(Path(workspace).resolve()), int(limit)),
            ).fetchall()
        return [
            {
                "session_id": int(r["sid"]),
                "title": r["title"] or "新会话",
                "updated_at": r["updated_at"],
                "total_tokens": int(r["total"]),
                "prompt_tokens": int(r["prompt"]),
                "completion_tokens": int(r["completion"]),
            }
            for r in rows
        ]

    def _next_seq(self, session_id: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS n FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return int(row["n"])


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _snippet(text: str, query: str, radius: int = 70) -> str:
    """Compact single-line excerpt around the first query match."""
    flat = text.replace("\n", " ").strip()
    idx = flat.lower().find(query.lower())
    idx = max(idx, 0)
    start = max(0, idx - radius)
    end = min(len(flat), idx + len(query) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return prefix + flat[start:end].strip() + suffix
