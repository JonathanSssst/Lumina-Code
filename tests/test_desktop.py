from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import app as desktop


def test_app_data_dir_is_project_root_in_source_mode():
    assert desktop.app_data_dir() == desktop._PROJECT_ROOT


def test_user_data_dir_defaults_to_appdata(monkeypatch):
    from lumina.config import user_data_dir

    monkeypatch.delenv("LUMINA_HOME", raising=False)
    monkeypatch.setenv("APPDATA", "C:/appdata")
    assert user_data_dir() == Path("C:/appdata") / "LuminaCode"


def test_user_data_dir_honors_lumina_home(monkeypatch):
    from lumina.config import user_data_dir

    monkeypatch.setenv("LUMINA_HOME", "C:/custom")
    monkeypatch.delenv("APPDATA", raising=False)
    assert user_data_dir() == Path("C:/custom")


def test_default_workspace_prefers_last_used(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(desktop, "_PROJECT_ROOT", project)

    other = tmp_path / "other"
    other.mkdir()
    assert desktop._default_workspace({"last_workspace": str(other)}, frozen=False) == other.resolve()
    assert (
        desktop._default_workspace({"last_workspace": str(tmp_path / "missing")}, frozen=False)
        == project
    )


def test_default_workspace_falls_back_to_home_without_env(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(desktop, "_PROJECT_ROOT", project)

    result = desktop._default_workspace({}, frozen=False)
    assert result == Path.home().resolve()


def test_find_free_port():
    port = desktop.find_free_port(12990, 5)
    assert isinstance(port, int) and 12990 <= port < 12995


def test_state_roundtrip(tmp_path):
    f = tmp_path / "state.json"
    desktop.save_state(f, {"last_workspace": "C:\\x"})
    assert desktop.load_state(f)["last_workspace"] == "C:\\x"
    assert desktop.load_state(tmp_path / "missing.json") == {}


def test_resolve_workspaces_skips_meipass_when_frozen(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(desktop, "_PROJECT_ROOT", project)

    # frozen: _PROJECT_ROOT is the PyInstaller extraction dir, never a workspace
    result = desktop._resolve_workspaces(other, frozen=True, extra="")
    assert project not in result
    assert result == []

    # frozen: configured extras still respected
    result = desktop._resolve_workspaces(other, frozen=True, extra=str(project))
    assert result == [project]

    # source mode: project root auto-added when workspace differs
    result = desktop._resolve_workspaces(other, frozen=False, extra="")
    assert result == [project]

    # source mode: not duplicated when already configured
    result = desktop._resolve_workspaces(project, frozen=False, extra="")
    assert result == []


def test_wait_for_server_returns_true_when_started():
    server = SimpleNamespace(started=True, should_exit=False)
    assert desktop._wait_for_server(server, timeout=0.1) is True


def test_wait_for_server_times_out():
    server = SimpleNamespace(started=False, should_exit=False)
    assert desktop._wait_for_server(server, timeout=0.1) is False


def test_wait_for_server_detects_shutdown():
    server = SimpleNamespace(started=False, should_exit=True)
    assert desktop._wait_for_server(server, timeout=1.0) is False


def test_is_cli_invocation():
    assert desktop._is_cli_invocation(["LuminaCode.exe", "chat"]) is True
    assert desktop._is_cli_invocation(["LuminaCode.exe", "run", "fix it"]) is True
    assert desktop._is_cli_invocation(["LuminaCode.exe", "doctor"]) is True
    assert desktop._is_cli_invocation(["LuminaCode.exe", "--version"]) is True
    assert desktop._is_cli_invocation(["LuminaCode.exe", "--help"]) is True
    assert desktop._is_cli_invocation(["LuminaCode.exe"]) is False
    assert desktop._is_cli_invocation(["app.py", "--port", "1300"]) is False
    assert desktop._is_cli_invocation(["app.py", "--no-webview"]) is False


def test_run_cli_mode_handles_version(monkeypatch, capsys):
    monkeypatch.setattr(desktop.sys, "argv", ["app.py", "--version"])
    code = desktop._run_cli_mode()
    assert code == 0
    assert "LuminaCode version" in capsys.readouterr().out
