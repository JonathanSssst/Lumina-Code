from __future__ import annotations

from lumina.config import workspace_data_dir
from lumina.tools.registry import validate_arguments


async def test_escape_attempts_rejected(registry):
    cases = [
        ("read_file", {"path": "../secret"}),
        ("write_file", {"path": "../x.txt", "content": "x"}),
        ("edit_file", {"path": "../x.txt", "old_string": "a", "new_string": "b"}),
        ("list_files", {"path": "../"}),
        ("list_tree", {"path": "../"}),
        ("replace_all", {"path": "../x.txt", "old": "a", "new": "b"}),
        ("undo_file", {"path": "../x.txt"}),
    ]
    for name, args in cases:
        spec = registry.get_spec(name)
        result = await registry.handler(name)(**validate_arguments(spec, args))
        assert result.is_error, name
        assert "escapes" in result.content.lower(), name


async def test_read_file_not_a_file(registry):
    spec = registry.get_spec("read_file")
    result = await registry.handler("read_file")(**validate_arguments(spec, {"path": "nope.txt"}))
    assert result.is_error
    assert "Not a file" in result.content


async def test_read_file_clamps_negative_offset(registry):
    spec = registry.get_spec("read_file")
    result = await registry.handler("read_file")(
        **validate_arguments(spec, {"path": "src/calc.py", "offset": -5, "limit": 2})
    )
    assert not result.is_error
    assert "1: def add" in result.content


async def test_list_files_not_a_directory(registry):
    spec = registry.get_spec("list_files")
    result = await registry.handler("list_files")(**validate_arguments(spec, {"path": "src/calc.py"}))
    assert result.is_error
    assert "Not a directory" in result.content


async def test_list_tree_not_a_directory(registry):
    spec = registry.get_spec("list_tree")
    result = await registry.handler("list_tree")(**validate_arguments(spec, {"path": "src/calc.py"}))
    assert result.is_error
    assert "Not a directory" in result.content


async def test_edit_file_multiple_matches_rejected(registry, workspace):
    (workspace / "multi.txt").write_text("a a a", encoding="utf-8")
    spec = registry.get_spec("edit_file")
    result = await registry.handler("edit_file")(
        **validate_arguments(spec, {"path": "multi.txt", "old_string": "a", "new_string": "b"})
    )
    assert result.is_error
    assert "matches 3 times" in result.content


async def test_edit_file_not_a_file(registry):
    spec = registry.get_spec("edit_file")
    result = await registry.handler("edit_file")(
        **validate_arguments(spec, {"path": "nope.txt", "old_string": "a", "new_string": "b"})
    )
    assert result.is_error
    assert "Not a file" in result.content


async def test_replace_all_not_a_file(registry):
    spec = registry.get_spec("replace_all")
    result = await registry.handler("replace_all")(
        **validate_arguments(spec, {"path": "nope.txt", "old": "a", "new": "b"})
    )
    assert result.is_error
    assert "Not a file" in result.content


async def test_undo_without_snapshot(registry, workspace):
    (workspace / "untouched.txt").write_text("v1", encoding="utf-8")
    spec = registry.get_spec("undo_file")
    result = await registry.handler("undo_file")(
        **validate_arguments(spec, {"path": "untouched.txt"})
    )
    assert result.is_error
    assert "No undo snapshot" in result.content


async def test_undo_tolerates_bad_snapshots(registry, workspace):
    undo_dir = workspace_data_dir(workspace) / "undo"
    undo_dir.mkdir(parents=True)
    (undo_dir / "not_a_number_5.json").write_text("not json", encoding="utf-8")
    (workspace / "t.txt").write_text("v1", encoding="utf-8")
    spec = registry.get_spec("undo_file")
    result = await registry.handler("undo_file")(**validate_arguments(spec, {"path": "t.txt"}))
    assert result.is_error
    assert "No undo snapshot" in result.content


async def test_list_tree_depth_limit_and_ignored_files(registry, workspace):
    nested = workspace / "deep" / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "x.py").write_text("x", encoding="utf-8")
    (workspace / "deep" / "cache.pyc").write_text("x", encoding="utf-8")
    (workspace / "deep" / "a" / "__pycache__").mkdir()
    (workspace / "deep" / "a" / "__pycache__" / "y.pyc").write_text("x", encoding="utf-8")

    spec = registry.get_spec("list_tree")
    shallow = await registry.handler("list_tree")(
        **validate_arguments(spec, {"path": "deep", "max_depth": 1})
    )
    assert not shallow.is_error
    assert "cache.pyc" not in shallow.content
    assert "x.py" not in shallow.content


async def test_list_tree_truncates_at_300(registry, workspace):
    (workspace / "big").mkdir()
    for i in range(305):
        (workspace / "big" / f"f{i}.txt").write_text("x", encoding="utf-8")
    spec = registry.get_spec("list_tree")
    result = await registry.handler("list_tree")(
        **validate_arguments(spec, {"path": "big", "max_depth": 5})
    )
    assert not result.is_error
    assert "tree truncated at 300" in result.content
