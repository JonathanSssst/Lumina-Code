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
from lumina.config import Settings, workspace_data_dir
from lumina.store import SessionStore, default_db_path
from lumina.tools.registry import ToolRegistry
from lumina.tools.todo import TodoTools
from lumina.types import Message, Usage, build_user_content, content_images, content_text
from lumina.web.app import WsApprover, WsHooks, _message_view, create_app


@pytest.fixture
def app(tmp_path):
    return create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)


def test_config_payload_includes_vision_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(
        settings=Settings(DEEPSEEK_API_KEY="sk-test"),
        workspace=tmp_path,
        config_env=tmp_path / ".env",
    )
    with TestClient(app) as c:
        data = c.get("/api/config").json()
        assert data["LUMINA_VISION"] is False
        c.post("/api/config", json={"LUMINA_VISION": "true"})
        data2 = c.get("/api/config").json()
        assert data2["LUMINA_VISION"] is True


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

    async def run(self, content, history=None, persist=None, plan=None, persist_plan=None, user_content=None):
        return AgentResult(
            final_content="ok", iterations=1, tool_calls_made=0, total_tokens=5, stopped_reason="completed"
        )

    def reset_budget(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


class _FakeAgent:
    async def run(self, content, history=None, persist=None, plan=None, persist_plan=None, user_content=None):
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
        config = json.loads((workspace_data_dir(tmp_path) / "lumina.mcp.json").read_text(encoding="utf-8"))
        assert "demo" in config["mcpServers"]
        remove = c.post("/api/mcp", json={"action": "remove", "name": "demo"}).json()
        assert remove["ok"] is True
        assert "demo" not in c.get("/api/mcp").json()["servers"]


def test_api_mcp_add_requires_name_and_command(app, tmp_path):
    with TestClient(app) as c:
        bad = c.post("/api/mcp", json={"action": "add", "name": "", "command": ""}).json()
        assert bad["ok"] is False


def test_api_skills_lists_project_skills(app, tmp_path):
    skill_dir = workspace_data_dir(tmp_path) / "skills" / "bug-fix"
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


def test_api_health_reports_ok_version_and_local(app):
    with TestClient(app) as c:
        data = c.get("/api/health").json()
        assert data["ok"] is True
        assert data["local"] is True
        assert isinstance(data["version"], str) and data["version"]


def test_api_agents_lists_default_agent(app):
    with TestClient(app) as c:
        data = c.get("/api/agents").json()
        agents = data["agents"]
        assert agents[0]["id"] == "default"
        assert agents[0]["name"]


# --- multimodal content helpers ---


def test_content_text_extracts_from_string_and_parts():
    assert content_text("plain") == "plain"
    assert content_text(None) == ""
    assert content_text("") == ""
    parts = [
        {"type": "text", "text": "描述一下 "},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "text", "text": "这张截图"},
    ]
    assert content_text(parts) == "描述一下 这张截图"


def test_content_images_extracts_data_urls():
    parts = [
        {"type": "text", "text": "hi"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBBB"}},
    ]
    assert content_images(parts) == ["data:image/png;base64,AAAA", "data:image/jpeg;base64,BBBB"]
    assert content_images("plain") == []
    assert content_images(None) == []


def test_build_user_content_plain_vs_images():
    assert build_user_content("hi", []) == "hi"
    built = build_user_content("hi", ["data:image/png;base64,AAAA"])
    assert isinstance(built, list)
    assert built[0] == {"type": "text", "text": "hi"}
    assert built[1]["type"] == "image_url"
    assert built[1]["image_url"]["url"] == "data:image/png;base64,AAAA"
    assert len(built) == 2


def test_build_user_content_caps_at_four_images():
    imgs = [f"data:image/png;base64,{i}" for i in range(6)]
    built = build_user_content("hi", imgs)
    assert len(built) == 5  # 1 text + 4 images
    assert all(p["image_url"]["url"].startswith("data:image/") for p in built[1:])


def test_build_user_content_ignores_non_image_urls():
    built = build_user_content("hi", ["http://x/y.png"])
    assert built == "hi"


def test_message_view_flattens_parts_for_frontend():
    m = Message(
        role="user",
        content=[
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    )
    view = _message_view(m)
    assert view["role"] == "user"
    assert view["content"] == "看图"
    assert view["images"] == ["data:image/png;base64,AAAA"]


def test_ws_multimodal_message_roundtrip(tmp_path, monkeypatch):
    """A message with images is stored as parts and resumes as text + images."""
    from lumina.config import Settings

    app = create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test", LUMINA_VISION=True), workspace=tmp_path)
    calls = []

    class FakeAgent:
        async def run(self, content, history=None, persist=None, plan=None, persist_plan=None, user_content=None):
            calls.append({"content": content, "user_content": user_content})
            return AgentResult(
                final_content="看到图片了", iterations=1, tool_calls_made=0, total_tokens=10,
                stopped_reason="completed",
            )

        def reset_budget(self):
            pass

        async def aclose(self):
            pass

    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({
            "type": "message",
            "content": "看看这张图",
            "images": ["data:image/png;base64,AAAA"],
        })
        while True:
            msg = ws.receive_json()
            if msg["type"] == "done":
                assert msg["final_content"] == "看到图片了"
                break

    assert len(calls) == 1
    assert calls[0]["content"] == "看看这张图"
    assert calls[0]["user_content"][0]["type"] == "text"
    assert calls[0]["user_content"][1]["image_url"]["url"] == "data:image/png;base64,AAAA"

    store = SessionStore(default_db_path(tmp_path))
    sid = store.list_sessions(tmp_path)[0].id
    user_msgs = [m for m in store.get_messages(sid) if m.role == "user"]
    assert content_images(user_msgs[0].content) == ["data:image/png;base64,AAAA"]
    assert content_text(user_msgs[0].content) == "看看这张图"
    store.close()


def test_ws_image_message_rejected_when_vision_disabled(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: _FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({
            "type": "message",
            "content": "看看这张图",
            "images": ["data:image/png;base64,AAAA"],
        })
        err = None
        while True:
            m = ws.receive_json()
            if m["type"] == "error":
                err = m
                break
        assert "LUMINA_VISION" in err["message"]

        store = SessionStore(default_db_path(tmp_path))
        sessions = store.list_sessions(tmp_path)
        assert len(sessions) == 1 and sessions[0].message_count == 0  # empty session, no image stored
        store.close()


def test_ws_continue_image_session_rejected_when_vision_disabled(tmp_path, monkeypatch):
    """A session that already holds images must not continue without vision."""
    from lumina.config import Settings

    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: _FakeAgent())

    store = SessionStore(default_db_path(tmp_path))
    sid = store.create_session(tmp_path)
    store.append_message(sid, Message(role="user", content="看图"))
    store.append_message(
        sid,
        Message(
            role="user",
            content=[
                {"type": "text", "text": "看图"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        ),
    )
    store.close()

    app2 = create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test", LUMINA_VISION=False), workspace=tmp_path)
    with TestClient(app2) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "resume", "session_id": sid})
        while True:
            msg = ws.receive_json()
            if msg["type"] == "history":
                break
        ws.send_json({"type": "continue"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "LUMINA_VISION" in err["message"]
