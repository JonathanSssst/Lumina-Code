from __future__ import annotations

import pytest


@pytest.fixture
def app(tmp_path):
    from lumina.config import Settings
    from lumina.web.app import create_app

    return create_app(settings=Settings(DEEPSEEK_API_KEY="sk-test"), workspace=tmp_path)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from lumina.web import cli_setup

    monkeypatch.setattr(cli_setup, "bin_dir", lambda: tmp_path / "bin")
    monkeypatch.setattr(cli_setup, "_broadcast_env_change", lambda: None)
    return cli_setup


def test_path_entries():
    from lumina.web.cli_setup import _path_entries

    assert _path_entries("a;b; c ") == ["a", "b", "c"]
    assert _path_entries("") == []
    assert _path_entries('"C:\\x y";D:\\z') == ["C:\\x y", "D:\\z"]


def test_cli_available_uses_which(monkeypatch):
    from lumina.web import cli_setup

    monkeypatch.setattr(cli_setup.shutil, "which", lambda name: name == "lumina" and "C:\\x\\lumina.exe")
    assert cli_setup.cli_available() is True

    monkeypatch.setattr(cli_setup.shutil, "which", lambda name: None)
    assert cli_setup.cli_available() is False


def test_install_writes_shim_and_path(setup, monkeypatch):
    store = {"value": "C:\\existing", "typ": 2}

    def read():
        return store["value"], store["typ"]

    def write(value, typ):
        store["value"] = value
        store["typ"] = typ

    monkeypatch.setattr(setup, "_user_path_value", read)
    monkeypatch.setattr(setup, "_set_user_path_value", write)

    ok, _ = setup.install_cli(r"C:\Apps\LuminaCode.exe")
    assert ok is True
    shim = setup.bin_dir() / "lumina.cmd"
    assert shim.is_file()
    content = shim.read_text(encoding="ascii")
    assert r"C:\Apps\LuminaCode.exe" in content
    assert "@echo off" in content
    assert str(setup.bin_dir()) in store["value"]
    assert setup.cli_managed() is True


def test_install_preserves_existing_path_and_skips_duplicate(setup, monkeypatch):
    store = {"value": "C:\\one;%USERPROFILE%\\two", "typ": 2}

    def read():
        return store["value"], store["typ"]

    def write(value, typ):
        store["value"] = value
        store["typ"] = typ

    monkeypatch.setattr(setup, "_user_path_value", read)
    monkeypatch.setattr(setup, "_set_user_path_value", write)

    ok, _ = setup.install_cli(r"C:\x\LuminaCode.exe")
    assert ok is True
    entries = [e.strip() for e in store["value"].split(";") if e.strip()]
    assert "C:\\one" in entries
    assert "%USERPROFILE%\\two" in entries
    assert store["value"].count(str(setup.bin_dir())) == 1

    ok, _ = setup.install_cli(r"C:\x\LuminaCode.exe")
    assert ok is True
    assert store["value"].count(str(setup.bin_dir())) == 1


def test_uninstall_removes_shim_and_path(setup, monkeypatch):
    setup.bin_dir().mkdir(parents=True, exist_ok=True)
    (setup.bin_dir() / "lumina.cmd").write_text("@echo off\r\n", encoding="ascii")
    store = {"value": f"{setup.bin_dir()};C:\\other", "typ": 2}

    def read():
        return store["value"], store["typ"]

    def write(value, typ):
        store["value"] = value
        store["typ"] = typ

    monkeypatch.setattr(setup, "_user_path_value", read)
    monkeypatch.setattr(setup, "_set_user_path_value", write)

    ok, _ = setup.uninstall_cli()
    assert ok is True
    assert not (setup.bin_dir() / "lumina.cmd").exists()
    assert "C:\\other" in store["value"]
    assert str(setup.bin_dir()) not in store["value"]
    assert setup.cli_managed() is False


def test_install_requires_frozen_or_explicit_path(setup):
    ok, _ = setup.install_cli(None)
    assert ok is False  # source mode has no sys.executable exe to point at


def test_cli_api_status(app, monkeypatch):
    from fastapi.testclient import TestClient

    from lumina.web import cli_setup

    monkeypatch.setattr(cli_setup, "cli_available", lambda: True)
    monkeypatch.setattr(cli_setup, "cli_managed", lambda: False)
    with TestClient(app) as c:
        r = c.get("/api/cli").json()
    assert r["available"] is True
    assert r["managed"] is False
    assert r["enabled"] is True
    assert r["prompted"] is False


def test_cli_api_install_and_remove(app, monkeypatch):
    from fastapi.testclient import TestClient

    from lumina.web import cli_setup

    monkeypatch.setattr(cli_setup, "install_cli", lambda: (True, "ok"))
    monkeypatch.setattr(cli_setup, "uninstall_cli", lambda: (True, "removed"))
    monkeypatch.setattr(cli_setup, "cli_available", lambda: True)
    monkeypatch.setattr(cli_setup, "cli_managed", lambda: True)
    with TestClient(app) as c:
        assert c.post("/api/cli", json={"action": "install"}).json()["ok"] is True
        assert c.post("/api/cli", json={"action": "remove"}).json()["ok"] is True
        assert c.post("/api/cli", json={"action": "nope"}).json()["ok"] is False


def test_cli_api_dismiss_prompt(tmp_path):
    from fastapi.testclient import TestClient

    from lumina.config import Settings
    from lumina.web.app import create_app

    state_file = tmp_path / "state.json"
    app2 = create_app(
        settings=Settings(DEEPSEEK_API_KEY="sk-test"),
        workspace=tmp_path,
        state_file=state_file,
    )
    with TestClient(app2) as c:
        assert c.get("/api/cli").json()["prompted"] is False
        assert c.post("/api/cli", json={"action": "dismiss_prompt"}).json()["ok"] is True
        assert c.get("/api/cli").json()["prompted"] is True
