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
