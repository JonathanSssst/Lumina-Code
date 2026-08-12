"""WsHooks must stay compatible with the agent loop hooks contract.

Regression: WsHooks was a bare class missing on_thinking_done, so the loop's
``if self.hooks.on_thinking_done:`` check raised AttributeError while sending
a message over the web UI.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from lumina.agent.authorize import AgentResult
from lumina.config import Settings
from lumina.store import SessionStore, default_db_path
from lumina.tools.registry import ToolRegistry
from lumina.tools.todo import TodoTools
from lumina.types import Message, Usage
from lumina.web.app import WsApprover, WsHooks, create_app


@pytest.fixture
def app(tmp_path):
    return create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)


def test_ws_hooks_has_all_loop_hook_attributes():
    hooks = WsHooks(ws=None)
    assert hooks.on_thinking_done is None
    assert hooks.on_assistant_message is not None
    assert hooks.on_reasoning is not None
    assert hooks.on_tool_call is not None
    assert hooks.on_tool_result is not None
    assert hooks.on_todo is not None
    assert hooks.on_finish is None


def test_ws_hooks_missing_hook_defaults_are_none_not_attribute_error():
    hooks = WsHooks(ws=None)
    assert getattr(hooks, "on_thinking_done", None) is None
    assert not hooks.on_thinking_done


class _FakeWs:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, obj: dict) -> None:
        self.sent.append(obj)


def test_ws_hooks_on_todo_pushes_todo_message():
    hooks = WsHooks(ws=_FakeWs())
    asyncio.run(hooks.on_todo([{"content": "a", "status": "pending"}]))
    assert hooks.ws.sent == [{"type": "todo", "todos": [{"content": "a", "status": "pending"}]}]


def test_todo_tools_on_change_wired_to_ws_hooks():
    ws = _FakeWs()
    hooks = WsHooks(ws=ws)
    registry = ToolRegistry()
    TodoTools(registry)
    registry.todo_tools.on_change = hooks.on_todo

    async def run():
        await registry.handler("update_todo")(todos=[{"content": "step 1", "status": "in_progress"}])
        await registry.todo_tools.set_status(0, "completed")

    asyncio.run(run())
    assert ws.sent == [
        {"type": "todo", "todos": [{"content": "step 1", "status": "in_progress"}]},
        {"type": "todo", "todos": [{"content": "step 1", "status": "completed"}]},
    ]


class _SharedTodoAgent:
    def __init__(self) -> None:
        registry = ToolRegistry()
        TodoTools(registry)
        self.registry = registry

    async def run(self, content, history=None, persist=None, plan=None, persist_plan=None):
        return AgentResult(
            final_content="ok", iterations=1, tool_calls_made=0, total_tokens=5, stopped_reason="completed"
        )

    def reset_budget(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


def test_ws_todo_toggle_updates_and_pushes_todo(app, tmp_path, monkeypatch):
    agent = _SharedTodoAgent()

    async def seed():
        await agent.registry.handler("update_todo")(todos=[{"content": "a"}, {"content": "b"}])

    asyncio.run(seed())
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: agent)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "todo_toggle", "index": 0, "status": "completed"})
        msg = ws.receive_json()
        assert msg["type"] == "todo"
        assert msg["todos"][0] == {"content": "a", "status": "completed"}
        ws.send_json({"type": "todo_toggle", "index": 9, "status": "completed"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "index out of range" in err["message"]


class _NoRegistryAgent(_SharedTodoAgent):
    def __init__(self) -> None:
        pass


def test_ws_todo_toggle_without_todo_tools_errors(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: _NoRegistryAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "todo_toggle", "index": 0, "status": "completed"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "待办列表不可用" in err["message"]


def test_ws_approver_sends_arguments_in_request():
    ws = _FakeWs()
    approver = WsApprover(ws)

    async def go():
        task = asyncio.create_task(
            approver.approve("run_command", {"command": "git push origin main"}, "危险命令")
        )
        while not ws.sent:
            await asyncio.sleep(0.001)
        approver.submit(True)
        await task

    asyncio.run(go())
    msg = ws.sent[0]
    assert msg["type"] == "approval_request"
    assert msg["name"] == "run_command"
    assert msg["arguments"] == {"command": "git push origin main"}
    assert msg["reason"] == "危险命令"


def test_default_settings_show_reasoning_enabled(app):
    with TestClient(app) as c:
        settings = c.get("/api/settings").json()
        assert settings["show_reasoning"] is True


def test_config_exposes_context_limit_and_zero_budget(app):
    with TestClient(app) as c:
        cfg = c.get("/api/config").json()
        assert "LUMINA_CONTEXT_LIMIT" in cfg
        assert isinstance(cfg["LUMINA_TOKEN_BUDGET"], int)


def test_settings_default_budget_disabled_and_context_limit():
    s = Settings(_env_file=None)
    assert s.token_budget == 0
    assert s.context_limit == 131072


def test_api_files_tree_and_read(app, tmp_path):
    (tmp_path / "readme.md").write_text("# hello", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    with TestClient(app) as c:
        tree = c.get("/api/files").json()
        names = {n["name"] for n in tree["tree"]}
        assert "readme.md" in names
        assert any(n["name"] == "src" and n["type"] == "dir" for n in tree["tree"])
        assert ".git" not in names
        content = c.get("/api/file", params={"path": "readme.md"}).json()
        assert content["content"] == "# hello"
        assert content["truncated"] is False


def test_api_file_rejects_path_escape(app, tmp_path):
    with TestClient(app) as c:
        resp = c.get("/api/file", params={"path": "../outside.txt"})
        assert resp.status_code == 403


def test_api_mcp_add_list_remove(app, tmp_path):
    with TestClient(app) as c:
        add = c.post("/api/mcp", json={"action": "add", "name": "demo", "command": "python", "args": ["srv.py"]}).json()
        assert add["ok"] is True
        listed = c.get("/api/mcp").json()
        assert "demo" in listed["servers"]
        assert listed["servers"]["demo"]["command"] == "python"
        assert listed["servers"]["demo"]["args"] == ["srv.py"]
        config = json.loads((tmp_path / ".lumina" / "lumina.mcp.json").read_text(encoding="utf-8"))
        assert "demo" in config["mcpServers"]
        remove = c.post("/api/mcp", json={"action": "remove", "name": "demo"}).json()
        assert remove["ok"] is True
        assert "demo" not in c.get("/api/mcp").json()["servers"]


def test_api_mcp_add_requires_name_and_command(app, tmp_path):
    with TestClient(app) as c:
        bad = c.post("/api/mcp", json={"action": "add", "name": "", "command": ""}).json()
        assert bad["ok"] is False


def test_api_skills_lists_project_skills(app, tmp_path):
    skill_dir = tmp_path / ".lumina" / "skills" / "bug-fix"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "---\nname: bug-fix\ndescription: 修复失败的测试\ntrigger: 修复测试, 测试失败\n---\nAlways run pytest first.",
        encoding="utf-8",
    )
    with TestClient(app) as c:
        data = c.get("/api/skills").json()
        assert any(s["name"] == "bug-fix" for s in data["skills"])
        bug = next(s for s in data["skills"] if s["name"] == "bug-fix")
        assert "pytest" in bug["instructions"]
        assert "测试失败" in bug["triggers"]


def test_ws_terminal_runs_command(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: _NoRegistryAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "terminal", "command": "echo lumina-terminal-ok"})
        msg = ws.receive_json()
        assert msg["type"] == "terminal_output"
        assert msg["exit_code"] == 0
        assert "lumina-terminal-ok" in msg["output"]


def _seed_searchable_session(path):
    store = SessionStore(default_db_path(path))
    sid = store.create_session(path, title="搜索测试")
    store.append_message(sid, Message(role="user", content="我需要修复 fibonacci 的 bug"))
    store.append_message(sid, Message(role="assistant", content="已修复 fibonacci，测试全部通过"))
    store.record_usage(
        sid,
        Usage(prompt_tokens=120, completion_tokens=80, total_tokens=200, reasoning_tokens=20, cached_tokens=0),
        iterations=1,
        tool_calls=2,
    )
    store.close()
    return sid


def test_api_search_finds_messages_across_sessions(app, tmp_path):
    _seed_searchable_session(tmp_path)
    with TestClient(app) as c:
        data = c.get("/api/search", params={"q": "fibonacci"}).json()
        assert data["query"] == "fibonacci"
        assert len(data["results"]) == 2
        assert all("fibonacci" in r["snippet"] for r in data["results"])
        assert data["results"][0]["session_id"] > 0
        assert "搜索测试" in data["results"][0]["title"]
        empty = c.get("/api/search", params={"q": "不存在的关键词"}).json()
        assert empty["results"] == []


def test_api_search_requires_nonempty_query(app, tmp_path):
    with TestClient(app) as c:
        data = c.get("/api/search", params={"q": "   "}).json()
        assert data["query"] == ""
        assert data["results"] == []


def test_api_usage_trend_lists_recent_sessions_with_usage(app, tmp_path):
    _seed_searchable_session(tmp_path)
    with TestClient(app) as c:
        data = c.get("/api/usage/trend").json()
        points = data["points"]
        assert len(points) == 1
        p = points[0]
        assert p["total_tokens"] == 200
        assert p["prompt_tokens"] == 120
        assert p["completion_tokens"] == 80
        assert p["title"] == "搜索测试"
        assert p["updated_at"]
