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

from lumina.agent.authorize import Hooks
from lumina.config import Settings, get_settings
from lumina.config_edit import write_env
from lumina.factory import build_agent
from lumina.mcp import MCP_AVAILABLE
from lumina.skills import SkillLoader
from lumina.store import SessionStore, default_db_path
from lumina.types import Message

_EDITABLE_KEYS = (
    "LUMINA_LLM_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_PLANNER_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_PLANNER_MODEL",
    "LUMINA_MAX_TOKENS",
    "LUMINA_TOKEN_BUDGET",
    "LUMINA_CONTEXT_LIMIT",
    "LUMINA_MAX_ITERATIONS",
    "LUMINA_TEMPERATURE",
    "LUMINA_ENABLE_PLANNER",
    "LUMINA_COMPRESSION",
    "LUMINA_SELF_REVIEW",
    "LUMINA_TDD",
    "LUMINA_PROJECT_MEMORY",
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


_FILE_TREE_IGNORED = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".pytest_cache", ".mypy_cache", ".lumina",
}
_FILE_TREE_LIMIT = 600


def _build_file_tree(root: Path, path: str = "") -> tuple[list[dict], int]:
    """Nested file/dir tree for the sidebar panel. Returns (nodes, count)."""
    target = (root / path).resolve()
    nodes: list[dict] = []
    if not target.is_dir() or not target.is_relative_to(root):
        return nodes, 0
    count = 0
    for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if count >= _FILE_TREE_LIMIT:
            break
        if entry.name in _FILE_TREE_IGNORED:
            continue
        rel = entry.relative_to(root).as_posix()
        if entry.is_dir():
            children, sub = _build_file_tree(root, rel)
            count += sub + 1
            nodes.append({"name": entry.name, "path": rel, "type": "dir", "children": children})
        else:
            if entry.name.endswith((".pyc", ".pyo")):
                continue
            count += 1
            nodes.append({"name": entry.name, "path": rel, "type": "file"})
        if count >= _FILE_TREE_LIMIT:
            break
    return nodes, count


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
            {
                "type": "approval_request",
                "request_id": self._counter,
                "name": name,
                "reason": reason,
                "arguments": arguments or {},
            }
        )
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=300)
        except asyncio.TimeoutError:
            return False

    def submit(self, approved: bool) -> None:
        self.queue.put_nowait(approved)


class WsHooks(Hooks):
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws

    async def on_todo(self, todos: list[dict[str, str]]) -> None:
        await self.ws.send_json({"type": "todo", "todos": todos})

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
    # Per-session todo lists, keyed by "<workspace>|<session_id>", so that
    # switching sessions (or workspaces) never leaks the previous task's list.
    app.state.session_todos: dict[str, list[dict[str, str]]] = {}

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
        usage = store.get_session_usage(sid) if s else None
        return {
            "id": sid,
            "title": s.title if s else "",
            "messages": s.message_count if s else 0,
            "tokens": usage.total_tokens if usage else 0,
            "updated_at": s.updated_at if s else "",
        }

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
            "show_reasoning": True,
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

    @app.get("/api/shell-menu")
    async def get_shell_menu() -> dict:
        from lumina.web.shell_menu import context_menu_enabled

        return {"enabled": context_menu_enabled()}

    @app.post("/api/shell-menu")
    async def set_shell_menu(payload: dict[str, Any]) -> dict:
        from lumina.web.shell_menu import set_context_menu

        enabled = bool(payload.get("enabled"))
        ok, message = set_context_menu(enabled)
        return {"ok": ok, "message": message, "enabled": enabled if ok else None}

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

    MCP_CONFIG_NAME = "lumina.mcp.json"

    def _mcp_config_paths() -> list[Path]:
        return [workspace / ".lumina" / MCP_CONFIG_NAME, Path.home() / ".config" / "lumina" / MCP_CONFIG_NAME]

    def _load_mcp_config() -> dict:
        for p in _mcp_config_paths():
            if p.is_file():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
        return {}

    @app.get("/api/mcp")
    async def list_mcp() -> dict:
        config = _load_mcp_config()
        servers = config.get("mcpServers", {})
        if not isinstance(servers, dict):
            servers = {}
        return {
            "servers": servers,
            "available": bool(MCP_AVAILABLE),
            "config_path": str(workspace / ".lumina" / MCP_CONFIG_NAME),
        }

    @app.post("/api/mcp")
    async def mutate_mcp(payload: dict[str, Any]) -> dict:
        path = workspace / ".lumina" / MCP_CONFIG_NAME
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            config = _load_mcp_config()
            servers = config.get("mcpServers", {})
            if not isinstance(servers, dict):
                servers = {}
            action = str(payload.get("action", ""))
            name = str(payload.get("name", "")).strip()
            if action == "add":
                if not name or not str(payload.get("command", "")).strip():
                    return {"ok": False, "message": "名称和命令不能为空"}
                servers[name] = {
                    "command": str(payload.get("command", "")).strip(),
                    "args": [str(a) for a in payload.get("args", []) if str(a).strip()] or [],
                    "env": {str(k): str(v) for k, v in (payload.get("env") or {}).items()} or {},
                }
            elif action == "remove":
                servers.pop(name, None)
            elif action == "enable":
                if name not in servers:
                    return {"ok": False, "message": f"MCP 服务器不存在: {name}"}
            else:
                return {"ok": False, "message": f"未知操作: {action}"}
            config["mcpServers"] = servers
            path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"ok": True, "servers": servers, "config_path": str(path)}
        except OSError as exc:
            return {"ok": False, "message": str(exc)}

    @app.get("/api/skills")
    async def list_skills(workspace: str = "") -> dict:
        root = resolve_workspace(workspace)
        try:
            skills = SkillLoader(root).all()
            return {
                "skills": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "triggers": s.triggers,
                        "instructions": s.instructions,
                    }
                    for s in skills
                ]
            }
        except Exception as exc:  # noqa: BLE001
            return {"skills": [], "error": str(exc)}

    @app.get("/api/files")
    async def file_tree(workspace: str = "") -> dict:
        root = resolve_workspace(workspace)
        nodes, count = _build_file_tree(root)
        return {"root": root.name or str(root), "tree": nodes, "count": count}

    @app.get("/api/file")
    async def read_file(path: str = "", workspace: str = "") -> Any:
        root = resolve_workspace(workspace)
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            return JSONResponse({"error": "路径超出工作区范围"}, status_code=403)
        if target.is_dir():
            return JSONResponse({"error": "这是目录"}, status_code=400)
        if not target.is_file():
            return JSONResponse({"error": f"文件不存在: {path}"}, status_code=404)
        try:
            raw = target.read_bytes()
        except OSError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        truncated = len(raw) > 200_000
        content = raw[:200_000].decode("utf-8", errors="replace")
        return {"path": path, "content": content, "truncated": truncated, "size": len(raw)}

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

    @app.get("/api/session/{sid}/stats")
    async def session_stats(sid: int, workspace: str = "") -> Any:
        """Per-session usage/cost breakdown for the ring indicator popup."""
        store = get_store(resolve_workspace(workspace))
        session = store.get_session(sid)
        if session is None:
            return JSONResponse({"error": f"会话 {sid} 不存在"}, status_code=404)
        stats = store.get_session_stats(sid)
        total = int(stats["usage"]["total"])
        stats["context_limit"] = int(app.state.settings.context_limit)
        stats["cost"] = {
            "rate_per_m": 2,
            "value": round(total * 2 / 1_000_000, 4),
        }
        return stats

    @app.get("/api/search")
    async def search_sessions(q: str = "", workspace: str = "") -> dict:
        """Search user/assistant message content across sessions."""
        root = resolve_workspace(workspace)
        query = q.strip()
        if not query:
            return {"query": "", "results": []}
        store = get_store(root)
        return {"query": query, "results": store.search_messages(root, query)}

    @app.get("/api/usage/trend")
    async def usage_trend(workspace: str = "") -> dict:
        """Recent per-session token usage for the trend chart."""
        root = resolve_workspace(workspace)
        store = get_store(root)
        return {"points": store.usage_trend(root)}

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
        hooks = WsHooks(ws)
        agent = build_agent(ws_path, app.state.settings, approver, hooks)
        todo_tools = getattr(getattr(agent, "registry", None), "todo_tools", None)
        current_session: int | None = None
        running: asyncio.Task | None = None

        def _todo_key(sid: int | None) -> str | None:
            return f"{ws_path}|{sid}" if sid is not None else None

        async def _on_todo_change(todos: list[dict[str, str]]) -> None:
            """Snapshot the list onto the current session, then push it to the UI."""
            key = _todo_key(current_session)
            if key is not None:
                app.state.session_todos[key] = [dict(t) for t in todos]
            await hooks.on_todo(todos)

        if todo_tools is not None:
            todo_tools.on_change = _on_todo_change

        async def _push_session_todos(sid: int) -> None:
            key = _todo_key(sid)
            await ws.send_json(
                {"type": "todo", "todos": list(app.state.session_todos.get(key, []))}
            )

        async def run_in_background(content: str, sid: int, history: list[Message]) -> None:
            """Runs the agent in a background task so approvals stay responsive."""
            budget = getattr(agent, "budget", None)
            try:
                result = await agent.run(
                    content,
                    history=history,
                    plan=store.get_plan(sid) or None,
                    persist=lambda m, sid_=sid: store.append_message(sid_, m),
                    persist_plan=lambda p, sid_=sid: store.set_plan(sid_, p),
                )
                usage = budget.usage if budget is not None else None
                await ws.send_json(
                    {
                        "type": "done",
                        "iterations": result.iterations,
                        "tool_calls": result.tool_calls_made,
                        "total_tokens": result.total_tokens,
                        "stopped_reason": result.stopped_reason,
                        "final_content": result.final_content,
                        "usage": {
                            "prompt": usage.prompt_tokens if usage else 0,
                            "completion": usage.completion_tokens if usage else 0,
                            "reasoning": usage.reasoning_tokens if usage else 0,
                            "cached": usage.cached_tokens if usage else 0,
                            "total": result.total_tokens,
                        },
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
                    if budget is not None:
                        store.record_usage(
                            sid,
                            budget.usage,
                            iterations=budget.iterations,
                            tool_calls=budget.tool_calls,
                        )
                except Exception:  # noqa: BLE001, S110
                    pass
                try:
                    await push_sessions(ws, store, ws_path)
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001, S110
                    pass

        async def run_terminal(command: str) -> dict:
            """Run a shell command in the workspace and stream its output back."""
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=ws_path,
                )
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    return {"command": command, "exit_code": -1, "output": "命令超时（120s），已终止。"}
                output = out.decode("utf-8", errors="replace")
                if len(output) > 8000:
                    output = output[-8000:] + "\n... (输出过长，已截断)"
                return {"command": command, "exit_code": proc.returncode, "output": output or ""}
            except Exception as exc:  # noqa: BLE001
                return {"command": command, "exit_code": -1, "output": str(exc)}

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
                    await _push_session_todos(current_session)
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
                    app.state.session_todos.pop(_todo_key(sid), None)
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
                    await _push_session_todos(sid)
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
                        await _push_session_todos(current_session)
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

                elif mtype == "continue":
                    if running and not running.done():
                        await ws.send_json({"type": "error", "message": "任务运行中，请先等待完成"})
                        continue
                    if current_session is None:
                        await ws.send_json({"type": "error", "message": "没有可继续的会话"})
                        continue
                    msgs = store.get_messages(current_session)
                    last_user: Message | None = None
                    last_user_index = -1
                    user_index = -1
                    for m in msgs:
                        if m.role == "user":
                            user_index += 1
                            last_user = m
                            last_user_index = user_index
                    if last_user is None or not (last_user.content or "").strip():
                        await ws.send_json({"type": "error", "message": "没有可继续的任务"})
                        continue
                    content = str(last_user.content)
                    store.truncate_after_user(current_session, last_user_index)
                    store.append_message(current_session, Message(role="user", content=content))
                    s = store.get_session(current_session)
                    if s and s.message_count <= 1:
                        store.set_title(current_session, content[:40])
                    agent.reset_budget()
                    history = store.get_messages(current_session)
                    running = asyncio.create_task(
                        run_in_background(content, current_session, history)
                    )

                elif mtype == "approval_response":
                    approver.submit(bool(msg.get("approved")))

                elif mtype == "todo_toggle":
                    if todo_tools is not None:
                        index = int(msg.get("index", -1))
                        status = str(msg.get("status", ""))
                        res = await todo_tools.set_status(index, status)
                        if res.is_error:
                            await ws.send_json({"type": "error", "message": res.content})
                    else:
                        await ws.send_json({"type": "error", "message": "待办列表不可用"})

                elif mtype == "cancel":
                    if running and not running.done():
                        await ws.send_json({"type": "cancelled"})
                        running.cancel()

                elif mtype == "set_auto":
                    approver.auto = bool(msg.get("value"))

                elif mtype == "terminal":
                    command = str(msg.get("command", ""))[:2000]
                    if command.strip():
                        result = await run_terminal(command)
                        await ws.send_json({"type": "terminal_output", **result})
        except WebSocketDisconnect:
            pass
        finally:
            if running is not None:
                running.cancel()
            await agent.aclose()

    return app
