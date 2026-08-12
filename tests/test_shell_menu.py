from __future__ import annotations

import pytest


@pytest.fixture
def app(tmp_path):
    from lumina.config import Settings
    from lumina.web.app import create_app

    return create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)


@pytest.fixture
def shell_menu():
    """Real winreg round-trip is only meaningful on Windows; skip elsewhere."""
    import sys

    if sys.platform != "win32":
        pytest.skip("registry tests require Windows")
    from lumina.web import shell_menu

    # Ensure a known baseline: remove any existing entries first.
    shell_menu.set_context_menu(False)
    yield shell_menu
    shell_menu.set_context_menu(True)  # restore the user's menu


def test_shell_menu_toggle_roundtrip(shell_menu):
    assert shell_menu.context_menu_enabled() is False
    ok, _ = shell_menu.set_context_menu(True)
    assert ok is True
    assert shell_menu.context_menu_enabled() is True
    ok2, _ = shell_menu.set_context_menu(False)
    assert ok2 is True
    assert shell_menu.context_menu_enabled() is False


def test_shell_menu_api(app, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr("lumina.web.shell_menu.context_menu_enabled", lambda: True)
    with TestClient(app) as c:
        assert c.get("/api/shell-menu").json() == {"enabled": True}


def test_shell_menu_api_toggle(app, monkeypatch):
    from fastapi.testclient import TestClient

    calls: list[bool] = []

    def fake_set(enabled: bool):
        calls.append(enabled)
        return True, "ok"

    monkeypatch.setattr("lumina.web.shell_menu.set_context_menu", fake_set)
    with TestClient(app) as c:
        r = c.post("/api/shell-menu", json={"enabled": False})
        assert r.json()["ok"] is True
        assert calls == [False]
