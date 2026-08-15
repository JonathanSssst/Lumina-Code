from __future__ import annotations

import json

from lumina.config_edit import read_env, write_env
from lumina.store import SessionStore, default_db_path
from lumina.types import Message


def test_write_env_updates_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n# keep this comment\nB=old\n", encoding="utf-8")
    write_env(env, {"A": "2", "C": "new"})
    text = env.read_text(encoding="utf-8")
    assert "A=2" in text
    assert "C=new" in text
    assert "# keep this comment" in text
    assert "B=old" in text
    assert read_env(env) == {"A": "2", "B": "old", "C": "new"}


def test_write_env_creates_missing_file(tmp_path):
    env = tmp_path / "nested" / ".env"
    write_env(env, {"DEEPSEEK_API_KEY": "sk-x"})
    assert env.read_text(encoding="utf-8").strip() == "DEEPSEEK_API_KEY=sk-x"


def test_read_env_tolerates_utf8_bom(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"\xef\xbb\xbfDEEPSEEK_API_KEY=sk-bom\nOTHER=1\n")
    parsed = read_env(env)
    assert parsed["DEEPSEEK_API_KEY"] == "sk-bom"
    assert parsed["OTHER"] == "1"


def test_settings_tolerates_utf8_bom(tmp_path, monkeypatch):
    from lumina.config import Settings

    (tmp_path / ".env").write_bytes(b"\xef\xbb\xbfDEEPSEEK_API_KEY=sk-bom-settings\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = Settings()
    assert s.api_key == "sk-bom-settings"


async def test_config_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    s = Settings(DEEPSEEK_API_KEY="sk-test", LUMINA_TOKEN_BUDGET=999)
    app = create_app(settings=s, workspace=tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/config")
        assert r.status_code == 200
        data = r.json()
        assert data["DEEPSEEK_API_KEY"] == "sk-test"
        assert data["LUMINA_TOKEN_BUDGET"] == 999
        assert data["LUMINA_TDD"] is False
        assert data["LUMINA_PROJECT_MEMORY"] is True

        r2 = c.post(
            "/api/config",
            json={
                "LUMINA_TOKEN_BUDGET": "50000",
                "DEEPSEEK_MODEL": "deepseek-v4-flash",
                "LUMINA_LLM_PROVIDER": "openai",
                "OPENAI_API_KEY": "sk-openai",
                "OPENAI_BASE_URL": "http://localhost:11434/v1",
            },
        )
        assert r2.status_code == 200
        assert r2.json()["ok"]
        env_text = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "LUMINA_TOKEN_BUDGET=50000" in env_text
        assert "LUMINA_LLM_PROVIDER=openai" in env_text
        assert "OPENAI_API_KEY=sk-openai" in env_text
        assert "OPENAI_BASE_URL=http://localhost:11434/v1" in env_text

        r3 = c.get("/api/config")
        data3 = r3.json()
        assert "LUMINA_LLM_PROVIDER" in data3
        assert "OPENAI_MODEL" in data3
        assert "OPENAI_BASE_URL" in data3


def test_workspaces_and_session_export(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    ws1 = tmp_path / "w1"
    ws2 = tmp_path / "w2"
    ws1.mkdir()
    ws2.mkdir()
    app = create_app(settings=Settings(DEEPSEEK_API_KEY="k"), workspace=ws1, workspaces=[ws1, ws2])
    with TestClient(app) as c:
        data = c.get("/api/workspaces").json()
        assert data["default"] == str(ws1.resolve())
        assert {w["name"] for w in data["workspaces"]} == {"w1", "w2"}

        st = SessionStore(default_db_path(ws2))
        sid = st.create_session(ws2, "demo")
        st.append_message(sid, Message(role="user", content="hello"))
        st.append_message(sid, Message(role="assistant", content="world"))
        st.close()

        md = c.get(f"/api/session/{sid}/export?format=markdown&workspace={ws2.name}")
        assert md.status_code == 200
        assert "hello" in md.text and "world" in md.text

        js = c.get(f"/api/session/{sid}/export?format=json&workspace={ws2.name}")
        assert js.status_code == 200
        assert js.json()["messages"][0]["role"] == "user"

        missing = c.get(f"/api/session/{sid}/export?workspace={ws1.name}")
        assert missing.status_code == 404


def test_workspace_manager_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    ws1 = tmp_path / "w1"
    ws2 = tmp_path / "w2"
    ws1.mkdir()
    ws2.mkdir()
    env = tmp_path / "app.env"
    state = tmp_path / "state.json"
    app = create_app(
        settings=Settings(DEEPSEEK_API_KEY="k"),
        workspace=ws1,
        workspaces=[ws1, ws2],
        config_env=env,
        state_file=state,
    )
    with TestClient(app) as c:
        ws3 = tmp_path / "w3"
        ws3.mkdir()

        r = c.post("/api/workspaces", json={"action": "add", "path": str(ws3)})
        assert r.json()["ok"]
        assert {w["name"] for w in r.json()["workspaces"]} == {"w1", "w2", "w3"}
        assert "LUMINA_WORKSPACES" in env.read_text(encoding="utf-8")

        r = c.post("/api/workspaces", json={"action": "add", "path": str(ws3)})
        assert r.json()["ok"] and len(r.json()["workspaces"]) == 3

        r = c.post("/api/workspaces", json={"action": "add", "path": str(tmp_path / "nope")})
        assert not r.json()["ok"]

        r = c.post("/api/workspaces", json={"action": "remove", "path": str(ws1)})
        assert not r.json()["ok"]  # cannot remove the active workspace

        r = c.post("/api/workspaces", json={"action": "remove", "path": str(ws2)})
        assert r.json()["ok"]
        assert {w["name"] for w in r.json()["workspaces"]} == {"w1", "w3"}

        r = c.post("/api/workspaces", json={"action": "set_default", "path": str(ws3)})
        assert r.json()["ok"]
        assert json.loads(state.read_text(encoding="utf-8"))["last_workspace"] == str(ws3.resolve())

        r = c.post("/api/workspaces", json={"action": "set_default", "path": str(ws2)})
        assert not r.json()["ok"]

        r = c.post("/api/config", json={"LUMINA_TOKEN_BUDGET": "12345"})
        assert r.json()["ok"]
        assert "LUMINA_TOKEN_BUDGET=12345" in env.read_text(encoding="utf-8")


def test_theme_prefs_roundtrip(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    state = tmp_path / "state.json"
    app = create_app(
        settings=Settings(DEEPSEEK_API_KEY="k"),
        workspace=tmp_path,
        state_file=state,
    )
    with TestClient(app) as c:
        assert c.get("/api/prefs").json() == {"theme": "dark"}

        r = c.post("/api/prefs", json={"theme": "light"})
        assert r.json() == {"ok": True, "theme": "light"}
        assert json.loads(state.read_text(encoding="utf-8"))["theme"] == "light"
        assert c.get("/api/prefs").json() == {"theme": "light"}

        bad = c.post("/api/prefs", json={"theme": "neon"})
        assert not bad.json()["ok"]

        fresh = create_app(
            settings=Settings(DEEPSEEK_API_KEY="k"),
            workspace=tmp_path,
            state_file=state,
        )
        with TestClient(fresh) as f:
            assert f.get("/api/prefs").json() == {"theme": "light"}


def test_settings_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    state = tmp_path / "state.json"
    app = create_app(
        settings=Settings(DEEPSEEK_API_KEY="k"),
        workspace=tmp_path,
        state_file=state,
    )
    with TestClient(app) as c:
        d = c.get("/api/settings").json()
        assert d["language"] == "zh-CN"
        assert d["auto_approve"] is False
        assert d["color_scheme"] == "system"
        assert d["theme"] == "system"
        assert d["term_font"] == "JetBrainsMono Nerd Font Mono"

        r = c.post("/api/settings", json={"auto_approve": True, "theme": "matrix", "ui_font": "Segoe UI"})
        assert r.json()["ok"]
        saved = c.get("/api/settings").json()
        assert saved["auto_approve"] is True
        assert saved["theme"] == "matrix"
        assert saved["ui_font"] == "Segoe UI"
        assert saved["language"] == "zh-CN"  # untouched defaults preserved

        bad = c.post("/api/settings", json={"nonsense": 1})
        assert bad.json()["ok"]  # unknown keys ignored, no crash


def test_servers_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    state = tmp_path / "state.json"
    app = create_app(
        settings=Settings(DEEPSEEK_API_KEY="k"),
        workspace=tmp_path,
        state_file=state,
    )
    with TestClient(app) as c:
        assert c.get("/api/servers").json() == {"servers": []}

        r = c.post(
            "/api/servers",
            json={"action": "add", "url": "http://localhost:1200", "name": "Localhost", "user": "lumina-code"},
        )
        assert r.json()["ok"]
        servers = r.json()["servers"]
        assert len(servers) == 1
        assert servers[0]["url"] == "http://localhost:1200"

        r = c.post("/api/servers", json={"action": "add", "url": ""})
        assert not r.json()["ok"]  # empty url rejected

        r = c.post("/api/servers", json={"action": "update", "index": 0, "name": "Rename"})
        assert r.json()["ok"]
        assert r.json()["servers"][0]["name"] == "Rename"

        r = c.post("/api/servers", json={"action": "remove", "index": 0})
        assert r.json()["ok"]
        assert r.json()["servers"] == []

        assert json.loads(state.read_text(encoding="utf-8"))["servers"] == []


def test_index_serves_static_ui(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    app = create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "<!doctype html>" in r.text[:200].lower()
        assert "/static/app.js" in r.text

        for path, ctype in (("/static/style.css", "css"), ("/static/app.js", "javascript")):
            rs = c.get(path)
            assert rs.status_code == 200, path
            assert ctype in rs.headers["content-type"], path
            assert len(rs.text) > 1000, path


def test_session_export_formats(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.store import SessionStore, default_db_path
    from lumina.types import Message
    from lumina.web.app import create_app

    store = SessionStore(default_db_path(tmp_path))
    sid = store.create_session(tmp_path, "测试会话")
    store.append_message(sid, Message(role="user", content="你好"))
    store.append_message(sid, Message(role="assistant", content="你好！有什么可以帮你？"))
    store.close()

    app = create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)
    with TestClient(app) as c:
        md = c.get(f"/api/session/{sid}/export")
        assert md.status_code == 200
        assert md.headers["content-type"].startswith("text/markdown")
        assert "## User" in md.text and "你好" in md.text
        assert "## Assistant" in md.text

        js = c.get(f"/api/session/{sid}/export", params={"format": "json"})
        assert js.status_code == 200
        data = js.json()
        assert data["session"]["title"] == "测试会话"
        assert data["messages"][0] == {"role": "user", "content": "你好", "tool": ""}

        miss = c.get("/api/session/9999/export")
        assert miss.status_code == 404


def test_websocket_chat_roundtrip(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lumina.agent.authorize import AgentResult
    from lumina.config import Settings
    from lumina.web.app import create_app

    class FakeAgent:
        async def run(self, content, history=None, persist=None, plan=None, persist_plan=None, user_content=None):
            return AgentResult(
                final_content="fake answer",
                iterations=1,
                tool_calls_made=0,
                total_tokens=10,
                stopped_reason="completed",
            )

        def reset_budget(self) -> None:
            pass

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())

    app = create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "sessions"

        ws.send_json({"type": "message", "content": "你好"})
        done = None
        while done is None:
            msg = ws.receive_json()
            if msg["type"] == "done":
                done = msg
        assert done["final_content"] == "fake answer"
        assert done["stopped_reason"] == "completed"


def test_websocket_new_and_rename_session(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    class FakeAgent:
        def reset_budget(self) -> None:
            pass

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr("lumina.web.app.build_agent", lambda *a, **k: FakeAgent())

    app = create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)
    with TestClient(app) as c, c.websocket_connect("/ws") as ws:
        ws.receive_json()  # sessions
        ws.send_json({"type": "new_session"})
        assert ws.receive_json()["type"] == "todo"  # empty per-session todo push
        payload = ws.receive_json()
        assert payload["type"] == "session"
        sid = payload["session"]["id"]
        ws.receive_json()  # sessions refresh

        ws.send_json({"type": "rename_session", "session_id": sid, "title": "项目调研"})
        ws.receive_json()  # sessions refresh

        ws.send_json({"type": "resume", "session_id": sid})
        got = ws.receive_json()
        assert got["type"] == "session"
        assert got["session"]["title"] == "项目调研"
