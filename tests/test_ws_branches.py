from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from lumina.agent.authorize import AgentResult
from lumina.config import Settings
from lumina.web.app import create_app


class FakeAgent:
    def __init__(self) -> None:
        self.reset_calls = 0

    async def run(self, content, history=None, persist=None, plan=None, persist_plan=None):
        return AgentResult(
            final_content="fake answer",
            iterations=1,
            tool_calls_made=0,
            total_tokens=10,
            stopped_reason="completed",
        )

    def reset_budget(self) -> None:
        self.reset_calls += 1

    async def aclose(self) -> None:
        pass


class HangAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, content, history=None, persist=None, plan=None, persist_plan=None):
        self.started.set()
        await asyncio.Event().wait()

    def reset_budget(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


@pytest.fixture
def app(tmp_path):
    return create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)


def _recv_until(ws, mtype: str, skip: int = 0):
    """Receive JSON frames until one of the given type appears (skipping count matches)."""
    found = 0
    while True:
        msg = ws.receive_json()
        if msg["type"] == mtype:
            found += 1
            if found > skip:
                return msg


def _wait_started(agent) -> None:
    deadline = time.time() + 5
    while not agent.started.is_set():
        if time.time() > deadline:
            raise AssertionError("agent.run never started")
        time.sleep(0.01)


def test_ws_delete_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "new_session"})
        sid1 = _recv_until(ws, "session")["session"]["id"]
        _recv_until(ws, "sessions")
        ws.send_json({"type": "new_session"})
        sid2 = _recv_until(ws, "session")["session"]["id"]
        _recv_until(ws, "sessions")

        ws.send_json({"type": "delete_session", "session_id": sid2})
        cleared = ws.receive_json()
        assert cleared["type"] == "session_cleared"
        after = _recv_until(ws, "sessions")
        assert {s["id"] for s in after["sessions"]} == {sid1}

        ws.send_json({"type": "delete_session", "session_id": sid1})
        refresh = _recv_until(ws, "sessions")
        assert {s["id"] for s in refresh["sessions"]} == set()


def test_ws_delete_missing_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "delete_session", "session_id": 999})
        assert ws.receive_json()["type"] == "error"


def test_ws_rename_missing_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "rename_session", "session_id": 999, "title": "x"})
        assert ws.receive_json()["type"] == "error"


def test_ws_resume_missing_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "resume", "session_id": 999})
        assert ws.receive_json()["type"] == "error"


def test_ws_resume_resets_budget_only_on_switch(app, tmp_path, monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: agent)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "new_session"})
        sid1 = _recv_until(ws, "session")["session"]["id"]
        _recv_until(ws, "sessions")
        ws.send_json({"type": "new_session"})
        _recv_until(ws, "session")
        _recv_until(ws, "sessions")

        ws.send_json({"type": "resume", "session_id": sid1})
        assert _recv_until(ws, "session")["session"]["id"] == sid1
        _recv_until(ws, "history")
        assert agent.reset_calls >= 1

        before = agent.reset_calls
        ws.send_json({"type": "resume", "session_id": sid1})
        _recv_until(ws, "session")
        _recv_until(ws, "history")
        assert agent.reset_calls == before


def test_ws_truncate_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "new_session"})
        sid = _recv_until(ws, "session")["session"]["id"]
        _recv_until(ws, "sessions")

        ws.send_json({"type": "message", "content": "task 1"})
        _recv_until(ws, "done")
        _recv_until(ws, "sessions")

        ws.send_json({"type": "truncate", "before_user": 0})
        _recv_until(ws, "sessions")

        ws.send_json({"type": "resume", "session_id": sid})
        _recv_until(ws, "session")
        history = _recv_until(ws, "history")
        assert history["messages"] == []


def test_ws_truncate_bad_index(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "new_session"})
        _recv_until(ws, "session")
        _recv_until(ws, "sessions")

        ws.send_json({"type": "message", "content": "task 1"})
        _recv_until(ws, "done")
        _recv_until(ws, "sessions")

        ws.send_json({"type": "truncate", "before_user": 99})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "无法回退" in err["message"]


def test_ws_truncate_without_session_is_noop(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "truncate", "before_user": 0})
        ws.send_json({"type": "list"})
        assert ws.receive_json()["type"] == "sessions"


def test_ws_cancel_hangs_task(app, tmp_path, monkeypatch):
    agent = HangAgent()
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: agent)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "content": "long task"})
        _wait_started(agent)

        ws.send_json({"type": "cancel"})
        _recv_until(ws, "cancelled")


def test_ws_continue_replays_last_user_message(app, tmp_path, monkeypatch):
    agent = FakeAgent()
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: agent)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "content": "第一步任务"})
        _recv_until(ws, "session")
        _recv_until(ws, "done")
        _recv_until(ws, "sessions")

        reset_before = agent.reset_calls
        ws.send_json({"type": "continue"})
        _recv_until(ws, "done")
        assert agent.reset_calls > reset_before
        _recv_until(ws, "sessions")


def test_ws_continue_without_session_errors(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "continue"})
        err = ws.receive_json()
        assert err["type"] == "error"

        ws.send_json({"type": "new_session"})
        _recv_until(ws, "session")  # empty new session has no user message
        _recv_until(ws, "sessions")
        ws.send_json({"type": "continue"})
        err2 = ws.receive_json()
        assert err2["type"] == "error"
        assert "没有可继续的任务" in err2["message"]


def test_ws_new_session_rejected_while_running(app, tmp_path, monkeypatch):
    agent = HangAgent()
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: agent)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "message", "content": "long task"})
        _recv_until(ws, "session")  # auto-created session frame
        _wait_started(agent)

        ws.send_json({"type": "new_session"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert "任务运行中" in err["message"]

        ws.send_json({"type": "cancel"})
        _recv_until(ws, "cancelled")


def test_ws_approval_and_auto_toggles(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "set_auto", "value": True})
        ws.send_json({"type": "approval_response", "approved": True})
        ws.send_json({"type": "approval_response", "approved": False})
        ws.send_json({"type": "list"})
        assert ws.receive_json()["type"] == "sessions"


def test_ws_list_refreshes_sessions(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "list"})
        assert ws.receive_json()["type"] == "sessions"


def test_ws_todos_isolated_per_session(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "new_session"})
        assert ws.receive_json() == {"type": "todo", "todos": []}
        sid = _recv_until(ws, "session")["session"]["id"]
        _recv_until(ws, "sessions")

        app.state.session_todos[f"{tmp_path}|{sid}"] = [{"content": "step", "status": "pending"}]

        ws.send_json({"type": "resume", "session_id": sid})
        _recv_until(ws, "session")
        assert _recv_until(ws, "todo")["todos"] == [{"content": "step", "status": "pending"}]
        _recv_until(ws, "history")

        ws.send_json({"type": "new_session"})
        msg = ws.receive_json()
        assert msg["type"] == "todo"
        assert msg["todos"] == []


def test_ws_delete_session_clears_todos(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "new_session"})
        _recv_until(ws, "todo")
        sid = _recv_until(ws, "session")["session"]["id"]
        _recv_until(ws, "sessions")
        app.state.session_todos[f"{tmp_path}|{sid}"] = [{"content": "x", "status": "pending"}]

        ws.send_json({"type": "delete_session", "session_id": sid})
        _recv_until(ws, "session_cleared")
        _recv_until(ws, "sessions")
        assert f"{tmp_path}|{sid}" not in app.state.session_todos


class _BudgetAgent(FakeAgent):
    def __init__(self) -> None:
        from types import SimpleNamespace

        from lumina.types import Usage

        super().__init__()
        self.budget = SimpleNamespace(
            usage=Usage(prompt_tokens=6, completion_tokens=4, total_tokens=10, reasoning_tokens=1, cached_tokens=2),
            iterations=1,
            tool_calls=0,
        )


def test_ws_records_usage_and_stats_endpoint(app, tmp_path, monkeypatch):
    agent = _BudgetAgent()
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: agent)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "message", "content": "task"})
        sid = _recv_until(ws, "session")["session"]["id"]
        done = _recv_until(ws, "done")
        assert done["usage"]["total"] == 10
        assert done["usage"]["reasoning"] == 1
        _recv_until(ws, "sessions")

        r = c.get(f"/api/session/{sid}/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["usage"]["total"] == 10
        assert data["usage"]["cached"] == 2
        assert data["cost"]["value"] == round(10 * 2 / 1_000_000, 4)
        assert data["context_limit"] == app.state.settings.context_limit
        assert data["counts"]["user"] == 1


def test_stats_endpoint_missing_session_404(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c:
        assert c.get("/api/session/999/stats").status_code == 404


def test_session_payload_includes_tokens(app, tmp_path, monkeypatch):
    agent = _BudgetAgent()
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: agent)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "message", "content": "task"})
        _recv_until(ws, "session")
        _recv_until(ws, "done")
        listing = _recv_until(ws, "sessions")
        assert listing["sessions"][0]["tokens"] == 10


def test_static_and_unknown_routes_404(app, tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    with TestClient(app) as c:
        assert c.get("/static/nope.js").status_code == 404
        assert c.get("/no-such-route").status_code == 404
