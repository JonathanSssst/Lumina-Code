from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from lumina.config import Settings, get_settings
from lumina.config_edit import write_env
from lumina.factory import build_agent
from lumina.store import SessionStore, default_db_path
from lumina.types import Message

_EDITABLE_KEYS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_PLANNER_MODEL",
    "LUMINA_MAX_TOKENS",
    "LUMINA_TOKEN_BUDGET",
    "LUMINA_MAX_ITERATIONS",
    "LUMINA_TEMPERATURE",
    "LUMINA_ENABLE_PLANNER",
    "LUMINA_COMPRESSION",
    "LUMINA_SELF_REVIEW",
)


def _config_payload(s: Settings) -> dict:
    payload: dict = {}
    for field_name, field in Settings.model_fields.items():
        alias = field.alias
        if alias in _EDITABLE_KEYS:
            payload[alias] = getattr(s, field_name)
    return payload



def _static_dir() -> Path:
    """Resolve the bundled web static directory (source tree or PyInstaller bundle)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "lumina" / "web" / "static"
    return Path(__file__).resolve().parent / "static"


class WsApprover:
    """Approval via WebSocket: ask over WS, wait for the client response."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.queue: asyncio.Queue[bool] = asyncio.Queue()
        self.auto = False
        self._counter = 0

    async def approve(self, name: str, arguments: dict[str, Any], reason: str) -> bool:
        if self.auto:
            return True
        self._counter += 1
        await self.ws.send_json(
            {"type": "approval_request", "request_id": self._counter, "name": name, "reason": reason}
        )
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=300)
        except asyncio.TimeoutError:
            return False

    def submit(self, approved: bool) -> None:
        self.queue.put_nowait(approved)


class WsHooks:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def on_assistant_message(self, chunk: str) -> None:
        await self.ws.send_json({"type": "stream", "chunk": chunk})

    async def on_reasoning(self, chunk: str) -> None:
        await self.ws.send_json({"type": "reasoning", "chunk": chunk})

    async def on_tool_call(self, call) -> None:
        await self.ws.send_json(
            {"type": "tool_call", "name": call.name, "arguments": call.arguments}
        )

    async def on_tool_result(self, result) -> None:
        await self.ws.send_json(
            {
                "type": "tool_result",
                "name": result.name,
                "is_error": result.is_error,
                "content": result.content[:2000],
                "stats": result.stats,
            }
        )


def create_app(
    settings: Settings,
    workspace: Path,
    workspaces: list[Path] | None = None,
    *,
    config_env: Path | None = None,
    state_file: Path | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        yield
        for s in _app.state.stores.values():
            s.close()

    app = FastAPI(title="LuminaCode", lifespan=_lifespan)
    workspace = Path(workspace).resolve()
    configured = [str(Path(p).resolve()) for p in (workspaces or [])]
    if str(workspace) not in configured:
        configured.insert(0, str(workspace))
    ws_paths: list[Path] = [Path(p) for p in dict.fromkeys(configured)]
    app.state.workspaces = ws_paths
    app.state.settings = settings
    app.state.stores: dict[str, SessionStore] = {}
    app.state.config_env = Path(config_env).resolve() if config_env else None
    app.state.state_file = Path(state_file).resolve() if state_file else None

    def env_target() -> Path:
        return app.state.config_env or (app.state.workspaces[0] / ".env")

    def _load_state() -> dict:
        try:
            return json.loads(app.state.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(data: dict) -> None:
        try:
            app.state.state_file.parent.mkdir(parents=True, exist_ok=True)
            app.state.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _workspaces_payload() -> dict:
        return {
            "workspaces": [{"path": str(p), "name": p.name or str(p)} for p in ws_paths],
            "default": str(workspace),
        }

    def _persist_workspaces() -> None:
        try:
            write_env(env_target(), {"LUMINA_WORKSPACES": ",".join(str(p) for p in ws_paths)})
        except OSError:
            pass

    def get_store(path: Path) -> SessionStore:
        key = str(path)
        if key not in app.state.stores:
            app.state.stores[key] = SessionStore(default_db_path(path))
        return app.state.stores[key]

    def resolve_workspace(requested: str) -> Path:
        if not requested:
            return workspace
        for p in ws_paths:
            if requested in (str(p), p.name):
                return p
        return workspace

    def session_payload(store: SessionStore, sid: int) -> dict:
        s = store.get_session(sid)
        return {"id": sid, "title": s.title if s else "", "messages": s.message_count if s else 0}

    async def push_sessions(ws: WebSocket, store: SessionStore, path: Path) -> None:
        await ws.send_json(
            {"type": "sessions", "sessions": [session_payload(store, s.id) for s in store.list_sessions(path)]}
        )

    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")

    @app.get("/")
    async def index() -> Response:
        return FileResponse(_static_dir() / "index.html")

    @app.get("/api/workspaces")
    async def list_workspaces() -> dict:
        return _workspaces_payload()

    @app.post("/api/workspaces")
    async def mutate_workspaces(payload: dict[str, Any]) -> dict:
        action = str(payload.get("action", ""))
        raw = str(payload.get("path", "")).strip()
        if not raw:
            return {"ok": False, "message": "缺少路径参数 path"}
        p = Path(raw).expanduser().resolve()
        known = [str(w) for w in ws_paths]

        if action == "add":
            if not p.is_dir():
                return {"ok": False, "message": f"不是有效目录: {p}"}
            if str(p) not in known:
                ws_paths.append(p)
                _persist_workspaces()
            return {"ok": True, **_workspaces_payload()}

        if action == "remove":
            if str(p) == str(workspace):
                return {"ok": False, "message": "不能移除当前正在使用的工作区，请先切换到其他工作区"}
            before = len(ws_paths)
            ws_paths[:] = [w for w in ws_paths if str(w) != str(p)]
            if len(ws_paths) == before:
                return {"ok": False, "message": "工作区不在列表中"}
            _persist_workspaces()
            if app.state.state_file is not None:
                state = _load_state()
                if state.get("last_workspace") == str(p):
                    state["last_workspace"] = str(workspace)
                    _save_state(state)
            return {"ok": True, **_workspaces_payload()}

        if action == "set_default":
            if str(p) not in known:
                return {"ok": False, "message": "工作区不在列表中"}
            if app.state.state_file is not None:
                state = _load_state()
                state["last_workspace"] = str(p)
                _save_state(state)
            return {"ok": True}

        return {"ok": False, "message": f"未知操作: {action}"}

    @app.get("/api/prefs")
    async def get_prefs() -> dict:
        state = _load_state() if app.state.state_file is not None else {}
        return {"theme": state.get("theme") or "dark"}

    @app.post("/api/prefs")
    async def set_prefs(payload: dict[str, Any]) -> dict:
        theme = str(payload.get("theme", "")).lower()
        if theme not in ("dark", "light"):
            return {"ok": False, "message": "theme 必须是 dark 或 light"}
        if app.state.state_file is not None:
            state = _load_state()
            state["theme"] = theme
            _save_state(state)
        return {"ok": True, "theme": theme}

    def _default_settings() -> dict:
        return {
            "language": "zh-CN",
            "auto_approve": False,
            "shell": "auto",
            "show_reasoning": False,
            "expand_shell": False,
            "expand_edit": False,
            "color_scheme": "system",
            "theme": "system",
            "ui_font": "",
            "code_font": "",
            "term_font": "JetBrainsMono Nerd Font Mono",
            "notif_agent": True,
            "notif_permission": True,
            "notif_error": False,
            "sound_agent": "none",
            "sound_permission": "none",
            "sound_error": "none",
            "release_notes": True,
            "file_tree": False,
            "command_palette": False,
            "server_status": False,
            "custom_agents": False,
        }

    def _load_settings() -> dict:
        defaults = _default_settings()
        if app.state.state_file is None:
            return defaults
        stored = _load_state().get("settings") or {}
        return {**defaults, **stored}

    def _save_settings(data: dict) -> None:
        if app.state.state_file is None:
            return
        state = _load_state()
        state["settings"] = data
        _save_state(state)

    @app.get("/api/settings")
    async def get_settings_data() -> dict:
        return _load_settings()

    @app.post("/api/settings")
    async def set_settings_data(payload: dict[str, Any]) -> dict:
        current = _load_settings()
        merged = {**current}
        for key, value in (payload or {}).items():
            if key in current:
                merged[key] = value
        _save_settings(merged)
        return {"ok": True, "settings": merged}

    @app.get("/api/servers")
    async def list_servers() -> dict:
        servers = _load_state().get("servers", []) if app.state.state_file is not None else []
        if not isinstance(servers, list):
            servers = []
        return {"servers": servers}

    @app.post("/api/servers")
    async def mutate_servers(payload: dict[str, Any]) -> dict:
        if app.state.state_file is None:
            return {"ok": False, "message": "无状态文件，无法保存服务器"}
        state = _load_state()
        servers = state.get("servers", [])
        if not isinstance(servers, list):
            servers = []
        action = str(payload.get("action", ""))
        idx = int(payload.get("index", -1))
        if action == "add":
            url = str(payload.get("url", "")).strip()
            if not url:
                return {"ok": False, "message": "服务器 URL 不能为空"}
            entry = {
                "url": url,
                "name": str(payload.get("name", "")).strip() or url,
                "user": str(payload.get("user", "")).strip(),
                "password": str(payload.get("password", "")).strip(),
            }
            servers.append(entry)
        elif action == "update":
            if not (0 <= idx < len(servers)):
                return {"ok": False, "message": "服务器不存在"}
            for key in ("url", "name", "user", "password"):
                if key in payload:
                    servers[idx][key] = str(payload.get(key, "")).strip()
        elif action == "remove":
            if not (0 <= idx < len(servers)):
                return {"ok": False, "message": "服务器不存在"}
            servers.pop(idx)
        else:
            return {"ok": False, "message": f"未知操作: {action}"}
        state["servers"] = servers
        _save_state(state)
        return {"ok": True, "servers": servers}

    @app.get("/api/session/{sid}/export")
    async def export_session(sid: int, format: str = "markdown", workspace: str = "") -> Any:
        store = get_store(resolve_workspace(workspace))
        session = store.get_session(sid)
        if session is None:
            return JSONResponse({"error": f"会话 {sid} 不存在"}, status_code=404)
        msgs = store.get_messages(sid)
        if format == "json":
            return JSONResponse(
                {
                    "session": {"id": sid, "title": session.title, "messages": session.message_count},
                    "messages": [
                        {"role": m.role, "content": m.content or "", "tool": m.name or ""} for m in msgs
                    ],
                }
            )
        parts: list[str] = []
        for m in msgs:
            if m.role == "user" and m.content:
                parts.append(f"## User\n\n{m.content}")
            elif m.role == "assistant" and m.content:
                parts.append(f"## Assistant\n\n{m.content}")
        body = "\n\n---\n\n".join(parts) or "(empty session)"
        filename = f"session-{sid}.md"
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/config")
    async def get_config() -> dict:
        return _config_payload(app.state.settings)

    @app.post("/api/config")
    async def post_config(payload: dict[str, Any]) -> dict:
        updates: dict[str, str] = {}
        for key in _EDITABLE_KEYS:
            if key in payload:
                value = payload[key]
                if isinstance(value, bool):
                    value = "true" if value else "false"
                updates[key] = str(value)
        if not updates:
            return {"ok": False, "message": "no valid configuration fields"}
        try:
            write_env(env_target(), updates)
        except OSError as exc:
            return {"ok": False, "message": str(exc)}
        get_settings.cache_clear()
        app.state.settings = get_settings()
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, w: str = "") -> None:
        await ws.accept()
        ws_path = resolve_workspace(w)
        store = get_store(ws_path)
        approver = WsApprover(ws)
        agent = build_agent(ws_path, app.state.settings, approver, WsHooks(ws))
        current_session: int | None = None
        running: asyncio.Task | None = None

        async def run_in_background(content: str, sid: int, history: list[Message]) -> None:
            """Runs the agent in a background task so approvals stay responsive."""
            try:
                result = await agent.run(
                    content,
                    history=history,
                    persist=lambda m, sid_=sid: store.append_message(sid_, m),
                )
                await ws.send_json(
                    {
                        "type": "done",
                        "iterations": result.iterations,
                        "tool_calls": result.tool_calls_made,
                        "total_tokens": result.total_tokens,
                        "stopped_reason": result.stopped_reason,
                        "final_content": result.final_content,
                    }
                )
            except asyncio.CancelledError:
                try:
                    await ws.send_json({"type": "cancelled"})
                except Exception:  # noqa: BLE001, S110
                    pass
                raise
            except Exception as exc:  # noqa: BLE001
                await ws.send_json({"type": "error", "message": str(exc)})
            finally:
                try:
                    await push_sessions(ws, store, ws_path)
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001, S110
                    pass

        try:
            await push_sessions(ws, store, ws_path)
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "list":
                    await push_sessions(ws, store, ws_path)

                elif mtype == "new_session":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    current_session = store.create_session(ws_path, "新会话")
                    agent.reset_budget()
                    await ws.send_json({"type": "session", "session": session_payload(store, current_session)})
                    await push_sessions(ws, store, ws_path)

                elif mtype == "delete_session":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    sid = int(msg.get("session_id", 0))
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    store.delete_session(sid)
                    if current_session == sid:
                        current_session = None
                        await ws.send_json({"type": "session_cleared"})
                    await push_sessions(ws, store, ws_path)

                elif mtype == "rename_session":
                    sid = int(msg.get("session_id", 0))
                    title = str(msg.get("title", "")).strip()[:60]
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    store.set_title(sid, title or "新会话")
                    await push_sessions(ws, store, ws_path)

                elif mtype == "resume":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    sid = int(msg.get("session_id", 0))
                    if store.get_session(sid) is None:
                        await ws.send_json({"type": "error", "message": f"会话 {sid} 不存在"})
                        continue
                    if current_session != sid:
                        agent.reset_budget()
                    current_session = sid
                    await ws.send_json({"type": "session", "session": session_payload(store, sid)})
                    msgs = [
                        {"role": m.role, "content": m.content or ""}
                        for m in store.get_messages(sid)
                        if m.role in ("user", "assistant") and m.content
                    ]
                    await ws.send_json({"type": "history", "messages": msgs})

                elif mtype == "message":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    if current_session is None:
                        current_session = store.create_session(ws_path, "新会话")
                        agent.reset_budget()
                        await ws.send_json({"type": "session", "session": session_payload(store, current_session)})
                    content = msg.get("content", "")
                    history = store.get_messages(current_session)
                    store.append_message(current_session, Message(role="user", content=content))
                    s = store.get_session(current_session)
                    if s and s.message_count <= 1:
                        store.set_title(current_session, content[:40])
                    running = asyncio.create_task(
                        run_in_background(content, current_session, history)
                    )

                elif mtype == "truncate":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    if current_session is None:
                        continue
                    if not store.truncate_after_user(current_session, int(msg.get("before_user", -1))):
                        await ws.send_json({"type": "error", "message": "无法回退：找不到该消息"})
                        continue
                    await push_sessions(ws, store, ws_path)

                elif mtype == "approval_response":
                    approver.submit(bool(msg.get("approved")))

                elif mtype == "cancel":
                    if running and not running.done():
                        await ws.send_json({"type": "cancelled"})
                        running.cancel()

                elif mtype == "set_auto":
                    approver.auto = bool(msg.get("value"))
        except WebSocketDisconnect:
            pass
        finally:
            if running is not None:
                running.cancel()
            await agent.aclose()

    return app
