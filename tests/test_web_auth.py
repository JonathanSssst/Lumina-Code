"""HTTP access authentication for the web UI.

Covers the ``--password`` / ``LUMINA_WEB_PASSWORD`` gate: HTTP middleware,
the /api/auth login endpoint, and the WebSocket token check.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from lumina.config import Settings
from lumina.web.app import _secure_eq, _web_token, create_app


def _app(tmp_path, password=None):
    return create_app(
        settings=Settings(DEEPSEEK_API_KEY="sk-test"),
        workspace=tmp_path,
        auth_password=password,
    )


# --- helpers ---


def test_web_token_is_deterministic_and_salted():
    a = _web_token("hunter2")
    b = _web_token("hunter2")
    assert a == b
    assert _web_token("hunter3") != a
    assert len(a) == 64


def test_secure_eq_compares_constant_time():
    assert _secure_eq("abc", "abc")
    assert not _secure_eq("abc", "abd")
    assert not _secure_eq("abc", "")


# --- auth disabled (default) ---


def test_auth_disabled_by_default(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        data = c.get("/api/settings").json()
        assert data["show_reasoning"] is True
        auth = c.post("/api/auth", json={"password": "x"}).json()
        assert auth == {"ok": True, "enabled": False, "token": ""}


# --- auth enabled: HTTP ---


def test_http_requests_rejected_without_token(tmp_path):
    with TestClient(_app(tmp_path, password="secret")) as c:
        for path in ("/api/settings", "/api/workspaces", "/api/config", "/"):
            resp = c.get(path)
            assert resp.status_code == 401, path


def test_auth_login_wrong_password(tmp_path):
    with TestClient(_app(tmp_path, password="secret")) as c:
        resp = c.post("/api/auth", json={"password": "nope"})
        assert resp.status_code == 401
        assert resp.json()["error"] == "unauthorized"


def test_auth_login_correct_password_returns_token(tmp_path):
    with TestClient(_app(tmp_path, password="secret")) as c:
        resp = c.post("/api/auth", json={"password": "secret"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["enabled"] is True
        assert body["token"] == _web_token("secret")


def test_authorized_requests_with_bearer_token(tmp_path):
    app = _app(tmp_path, password="secret")
    token = _web_token("secret")
    with TestClient(app) as c:
        ok = c.get("/api/workspaces", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
        ok2 = c.get("/api/settings", headers={"Authorization": f"Bearer {token}"})
        assert ok2.status_code == 200


def test_authorized_requests_with_x_auth_token_header(tmp_path):
    app = _app(tmp_path, password="secret")
    token = _web_token("secret")
    with TestClient(app) as c:
        ok = c.get("/api/workspaces", headers={"X-Auth-Token": token})
        assert ok.status_code == 200


def test_static_assets_exempt_from_auth(tmp_path):
    app = _app(tmp_path, password="secret")
    with TestClient(app) as c:
        page = c.get("/static/app.js")
        assert page.status_code == 200
        assert str(page.url).endswith("/static/app.js")


def test_post_config_requires_auth(tmp_path):
    app = _app(tmp_path, password="secret")
    with TestClient(app) as c:
        resp = c.post("/api/config", json={"LUMINA_TDD": "true"})
        assert resp.status_code == 401


# --- auth enabled: WebSocket ---


def test_websocket_rejected_without_token(tmp_path):
    app = _app(tmp_path, password="secret")
    with TestClient(app) as c, pytest.raises(WebSocketDisconnect) as ei, c.websocket_connect("/ws") as ws:
        ws.receive_json()
    assert ei.value.code == 4401


def test_websocket_rejected_with_wrong_token(tmp_path):
    app = _app(tmp_path, password="secret")
    with TestClient(app) as c, pytest.raises(WebSocketDisconnect) as ei, c.websocket_connect("/ws?token=wrong") as ws:
        ws.receive_json()
    assert ei.value.code == 4401


def test_websocket_accepted_with_valid_token(tmp_path, monkeypatch):
    from lumina.agent.authorize import AgentResult

    class FakeAgent:
        async def run(self, content, history=None, persist=None, plan=None, persist_plan=None, user_content=None):
            return AgentResult(
                final_content="ok", iterations=1, tool_calls_made=0, total_tokens=5, stopped_reason="completed"
            )

        def reset_budget(self):
            pass

        async def aclose(self):
            pass

    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())
    app = _app(tmp_path, password="secret")
    token = _web_token("secret")
    with TestClient(app) as c, c.websocket_connect(f"/ws?token={token}") as ws:
        first = ws.receive_json()
        assert first["type"] == "sessions"
        ws.send_json({"type": "message", "content": "hi"})
        while True:
            msg = ws.receive_json()
            if msg["type"] == "done":
                assert msg["final_content"] == "ok"
                break
