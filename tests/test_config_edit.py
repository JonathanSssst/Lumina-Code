from __future__ import annotations

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

        r2 = c.post(
            "/api/config",
            json={"LUMINA_TOKEN_BUDGET": "50000", "DEEPSEEK_MODEL": "deepseek-v4-flash"},
        )
        assert r2.status_code == 200
        assert r2.json()["ok"]
        assert "LUMINA_TOKEN_BUDGET=50000" in (tmp_path / ".env").read_text(encoding="utf-8")


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
