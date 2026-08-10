from __future__ import annotations

from lumina.config_edit import read_env, write_env


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
