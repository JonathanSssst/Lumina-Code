from __future__ import annotations

from lumina.tools.registry import validate_arguments


def test_registry_exposes_core_tools(registry):
    names = registry.names()
    assert "read_file" in names
    assert "write_file" in names
    assert "edit_file" in names
    assert "list_files" in names
    assert "glob" in names
    assert "grep" in names
    assert "run_command" in names
    assert "run_tests" in names
    assert "git_status" in names
    assert "list_tree" in names
    assert "replace_all" in names
    assert "web_search" in names
    assert "web_fetch" in names


async def test_git_status_degrades_outside_repo(registry):
    spec = registry.get_spec("git_status")
    result = await registry.handler("git_status")(**validate_arguments(spec, {}))
    assert not result.is_error
    assert "not a git repository" in result.content


async def test_read_file(registry, workspace):
    spec = registry.get_spec("read_file")
    assert spec is not None
    args = validate_arguments(spec, {"path": "src/calc.py"})
    result = await registry.handler("read_file")(**args)
    assert not result.is_error
    assert "def add" in result.content
    assert "1: def add" in result.content


async def test_write_and_edit_file(registry, workspace):
    spec = registry.get_spec("write_file")
    await registry.handler("write_file")(**validate_arguments(spec, {"path": "notes.txt", "content": "hello"}))
    assert (workspace / "notes.txt").read_text() == "hello"

    spec = registry.get_spec("edit_file")
    result = await registry.handler("edit_file")(
        **validate_arguments(spec, {"path": "notes.txt", "old_string": "hello", "new_string": "world"})
    )
    assert not result.is_error
    assert (workspace / "notes.txt").read_text() == "world"


async def test_edit_file_not_found_reports_error(registry):
    spec = registry.get_spec("edit_file")
    result = await registry.handler("edit_file")(
        **validate_arguments(spec, {"path": "src/calc.py", "old_string": "nonexistent", "new_string": "x"})
    )
    assert result.is_error


async def test_list_tree_renders(registry):
    result = await registry.handler("list_tree")(path=".", max_depth=2)
    assert not result.is_error
    assert "./" in result.content or "." in result.content
    assert "calc.py" in result.content


async def test_replace_all(registry, workspace):
    (workspace / "dup.txt").write_text("abc abc abc", encoding="utf-8")
    spec = registry.get_spec("replace_all")
    result = await registry.handler("replace_all")(
        **validate_arguments(spec, {"path": "dup.txt", "old": "abc", "new": "xyz"})
    )
    assert not result.is_error
    assert "3" in result.content
    assert (workspace / "dup.txt").read_text() == "xyz xyz xyz"

    result = await registry.handler("replace_all")(
        **validate_arguments(spec, {"path": "dup.txt", "old": "missing", "new": "xyz"})
    )
    assert result.is_error


async def test_web_fetch_rejects_bad_url(registry):
    result = await registry.handler("web_fetch")(url="not-a-url")
    assert result.is_error
    assert "http" in result.content


async def test_grep_and_glob(registry):
    result = await registry.handler("grep")(pattern="def add", include="*.py", limit=10)
    assert not result.is_error
    assert "src/calc.py" in result.content

    result = await registry.handler("glob")(pattern="**/*.py", limit=50)
    assert "src/calc.py" in result.content


async def test_list_files_ignores_hidden(registry):
    result = await registry.handler("list_files")(path=".")
    assert not result.is_error
    assert "src/" in result.content


async def test_validate_arguments_rejects_missing_required(registry):
    spec = registry.get_spec("read_file")
    try:
        validate_arguments(spec, {})
        assert False, "should raise"
    except ValueError:
        pass


async def test_shell_classification(registry):
    check = registry.check_approval("run_command", {"command": "pytest"})
    assert check == (False, "")
    check = registry.check_approval("run_command", {"command": "git status --short"})
    assert check == (False, "")
    check = registry.check_approval("run_command", {"command": "git log -3 --oneline"})
    assert check == (False, "")
    needs, reason = registry.check_approval("run_command", {"command": "rm -rf /tmp/x"})
    assert needs is True
    assert "danger" in reason
    needs, reason = registry.check_approval("run_command", {"command": "git push origin main"})
    assert needs is True
    assert "danger" in reason
    needs, reason = registry.check_approval("run_command", {"command": "curl http://x"})
    assert needs is True
    assert "unknown" in reason
