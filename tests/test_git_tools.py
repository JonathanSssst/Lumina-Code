from __future__ import annotations

import subprocess

from lumina.tools.registry import validate_arguments


def _git(workspace, *args):
    return subprocess.run(
        ["git", *args], cwd=str(workspace), capture_output=True, text=True, check=False
    )


def _init_repo(workspace):
    _git(workspace, "init", "-b", "main")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    (workspace / "tracked.txt").write_text("hello\n", encoding="utf-8")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "init")


async def test_git_status_reports_clean(registry, workspace):
    _init_repo(workspace)
    spec = registry.get_spec("git_status")
    result = await registry.handler("git_status")(**validate_arguments(spec, {}))
    assert not result.is_error
    assert "(clean)" in result.content or "nothing to commit" in result.content


async def test_git_status_short_shows_changes(registry, workspace):
    _init_repo(workspace)
    (workspace / "tracked.txt").write_text("hello\nchanged\n", encoding="utf-8")
    spec = registry.get_spec("git_status")
    result = await registry.handler("git_status")(**validate_arguments(spec, {"short": True}))
    assert not result.is_error
    assert "tracked.txt" in result.content


async def test_git_diff_shows_changes(registry, workspace):
    _init_repo(workspace)
    (workspace / "tracked.txt").write_text("hello\nworld\n", encoding="utf-8")
    spec = registry.get_spec("git_diff")
    result = await registry.handler("git_diff")(**validate_arguments(spec, {}))
    assert not result.is_error
    assert "+world" in result.content


async def test_git_diff_empty_is_reported(registry, workspace):
    _init_repo(workspace)
    spec = registry.get_spec("git_diff")
    result = await registry.handler("git_diff")(**validate_arguments(spec, {}))
    assert not result.is_error
    assert "(no diff)" in result.content


async def test_git_diff_stat_and_max_lines(registry, workspace):
    _init_repo(workspace)
    lines = "\n".join(f"line {i}" for i in range(50))
    (workspace / "tracked.txt").write_text("hello\n" + lines + "\n", encoding="utf-8")
    spec = registry.get_spec("git_diff")
    result = await registry.handler("git_diff")(
        **validate_arguments(spec, {"stat": True, "max_lines": 10})
    )
    assert not result.is_error
    assert "tracked.txt" in result.content


async def test_git_log_lists_commits(registry, workspace):
    _init_repo(workspace)
    (workspace / "tracked.txt").write_text("hello\nsecond\n", encoding="utf-8")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-m", "second commit")
    spec = registry.get_spec("git_log")
    result = await registry.handler("git_log")(**validate_arguments(spec, {"count": 5}))
    assert not result.is_error
    assert "second commit" in result.content
    assert "init" in result.content


async def test_git_tools_degrade_outside_repo(registry):
    for name in ("git_status", "git_diff", "git_log"):
        spec = registry.get_spec(name)
        result = await registry.handler(name)(**validate_arguments(spec, {}))
        assert not result.is_error
        assert "not a git repository" in result.content
