from __future__ import annotations

from typer.testing import CliRunner

from lumina import __version__
from lumina.cli import app

runner = CliRunner()


def test_version_flag_single_dash():
    result = runner.invoke(app, ["-version"])
    assert result.exit_code == 0
    assert f"LuminaCode version {__version__}" in result.stdout


def test_version_flag_double_dash():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"LuminaCode version {__version__}" in result.stdout


def test_version_matches_package_version():
    # `-version` 杈撳嚭搴斾笌妯″潡 __version__ 涓€鑷?
    result = runner.invoke(app, ["-version"])
    assert __version__ in result.stdout


def test_help_still_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("run", "chat", "doctor", "web"):
        assert cmd in result.stdout
    assert "-version" in result.stdout
    assert "-latest" in result.stdout


def test_version_latest_up_to_date(monkeypatch):
    monkeypatch.setattr("lumina.cli._fetch_latest_release_tag", lambda: f"v{__version__}")
    result = runner.invoke(app, ["-version", "-latest"])
    assert result.exit_code == 0
    assert f"LuminaCode version {__version__}" in result.stdout
    assert "You are up to date" in result.stdout


def test_version_latest_newer_available(monkeypatch):
    major = __version__.split(".")[0]
    monkeypatch.setattr("lumina.cli._fetch_latest_release_tag", lambda: f"v{major}.999.0")
    result = runner.invoke(app, ["-version", "-latest"])
    assert result.exit_code == 0
    assert "upgrade recommended" in result.stdout


def test_version_latest_fetch_failure(monkeypatch):
    monkeypatch.setattr("lumina.cli._fetch_latest_release_tag", lambda: None)
    result = runner.invoke(app, ["-version", "-latest"])
    assert result.exit_code == 0
    assert "Could not check the latest release" in result.stdout


def test_version_latest_ignores_non_version_tag(monkeypatch):
    monkeypatch.setattr("lumina.cli._fetch_latest_release_tag", lambda: "dev")
    result = runner.invoke(app, ["-version", "-latest"])
    assert result.exit_code == 0
    assert "You are up to date" in result.stdout
