"""WsHooks must stay compatible with the agent loop hooks contract.

Regression: WsHooks was a bare class missing on_thinking_done, so the loop's
``if self.hooks.on_thinking_done:`` check raised AttributeError while sending
a message over the web UI.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from lumina.agent.authorize import AgentResult
from lumina.config import Settings
from lumina.tools.registry import ToolRegistry
from lumina.tools.todo import TodoTools
from lumina.web.app import WsHooks, create_app


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

    async def run(self, content, history=None, persist=None):
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
