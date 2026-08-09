from __future__ import annotations

import os
from pathlib import Path

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult


class FileTools:
    """File read/write/edit tools bound to a workspace root."""

    def __init__(self, workspace: Path, registry: ToolRegistry) -> None:
        self.workspace = Path(workspace).resolve()
        self.registry = registry
        self._setup()

    def _resolve(self, path: str) -> Path:
        resolved = (self.workspace / path).resolve()
        if not resolved.is_relative_to(self.workspace):
            raise PermissionError(f"Path escapes workspace: {path}")
        return resolved

    def _setup(self) -> None:

        @self.registry.register(
            description="Read a text file from the workspace. Returns content with line numbers.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside workspace"},
                    "offset": {"type": "integer", "description": "Start line (1-based)"},
                    "limit": {"type": "integer", "description": "Max lines to return"},
                },
                "required": ["path"],
            },
        )
        async def read_file(path: str, offset: int = 1, limit: int = 2000) -> ToolResult:
            try:
                target = self._resolve(path)
                if not target.is_file():
                    return ToolResult(tool_call_id="", name="read_file", content=f"Not a file: {path}", is_error=True)
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(1, offset)
                selected = lines[start - 1 : start - 1 + limit]
                body = "\n".join(f"{start + i}: {line}" for i, line in enumerate(selected))
                meta = f"File: {path} ({len(lines)} lines total)\n"
                return ToolResult(tool_call_id="", name="read_file", content=meta + body)
            except PermissionError as exc:
                return ToolResult(tool_call_id="", name="read_file", content=str(exc), is_error=True)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="read_file", content=f"read_file failed: {exc}", is_error=True)

        @self.registry.register(
            description="Write content to a file, creating parent directories if needed.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside workspace"},
                    "content": {"type": "string", "description": "Full content to write"},
                },
                "required": ["path", "content"],
            },
        )
        async def write_file(path: str, content: str) -> ToolResult:
            try:
                target = self._resolve(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return ToolResult(
                    tool_call_id="",
                    name="write_file",
                    content=f"Wrote {len(content)} chars to {path}",
                )
            except PermissionError as exc:
                return ToolResult(tool_call_id="", name="write_file", content=str(exc), is_error=True)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="write_file", content=f"write_file failed: {exc}", is_error=True)

        @self.registry.register(
            description="Replace an exact string occurrence in a file. Returns the diff.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside workspace"},
                    "old_string": {"type": "string", "description": "Exact text to find"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        )
        async def edit_file(path: str, old_string: str, new_string: str) -> ToolResult:
            try:
                target = self._resolve(path)
                if not target.is_file():
                    return ToolResult(tool_call_id="", name="edit_file", content=f"Not a file: {path}", is_error=True)
                text = target.read_text(encoding="utf-8")
                count = text.count(old_string)
                if count == 0:
                    return ToolResult(
                        tool_call_id="",
                        name="edit_file",
                        content=f"old_string not found in {path}",
                        is_error=True,
                    )
                if count > 1:
                    return ToolResult(
                        tool_call_id="",
                        name="edit_file",
                        content=f"old_string matches {count} times in {path}; provide more context",
                        is_error=True,
                    )
                target.write_text(text.replace(old_string, new_string), encoding="utf-8")
                diff = _simple_diff(old_string, new_string)
                return ToolResult(
                    tool_call_id="",
                    name="edit_file",
                    content=f"Edited {path}\n{diff}",
                )
            except PermissionError as exc:
                return ToolResult(tool_call_id="", name="edit_file", content=str(exc), is_error=True)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="edit_file", content=f"edit_file failed: {exc}", is_error=True)

        @self.registry.register(
            description="List files/directories in a workspace directory.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory; '.' for root"},
                },
                "required": ["path"],
            },
        )
        async def list_files(path: str = ".") -> ToolResult:
            try:
                target = (self.workspace / path).resolve()
                if not target.is_relative_to(self.workspace):
                    return ToolResult(tool_call_id="", name="list_files", content="Path escapes workspace", is_error=True)
                if not target.is_dir():
                    return ToolResult(tool_call_id="", name="list_files", content=f"Not a directory: {path}", is_error=True)
                entries = sorted(
                    os.listdir(target),
                    key=lambda e: (not (target / e).is_dir(), e.lower()),
                )
                lines = [
                    (f"{e}/" if (target / e).is_dir() else e)
                    for e in entries
                    if not e.startswith(".git") and e not in {"__pycache__", "node_modules", ".venv", "venv"}
                ]
                return ToolResult(tool_call_id="", name="list_files", content="\n".join(lines) or "(empty)")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="list_files", content=f"list_files failed: {exc}", is_error=True)

        @self.registry.register(
            description="Render a directory tree of the workspace (ignores .git, caches, venvs).",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory; '.' for root"},
                    "max_depth": {"type": "integer", "description": "Max directory depth"},
                },
                "required": [],
            },
        )
        async def list_tree(path: str = ".", max_depth: int = 3) -> ToolResult:
            _IGNORED = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache"}
            try:
                target = (self.workspace / path).resolve()
                if not target.is_relative_to(self.workspace):
                    return ToolResult(tool_call_id="", name="list_tree", content="Path escapes workspace", is_error=True)
                if not target.is_dir():
                    return ToolResult(tool_call_id="", name="list_tree", content=f"Not a directory: {path}", is_error=True)
                root_name = target.relative_to(self.workspace).as_posix() or "."
                lines = [f"{root_name}/"]
                for dirpath, dirnames, filenames in os.walk(target):
                    rel = Path(dirpath).relative_to(target)
                    depth = len(rel.parts)
                    if depth >= max_depth:
                        dirnames[:] = []
                    dirnames[:] = [d for d in dirnames if d not in _IGNORED]
                    indent = "  " * depth
                    name = "." if depth == 0 else rel.name
                    lines.append(f"{indent}{name}/")
                    for fn in sorted(filenames):
                        if fn in _IGNORED or fn.endswith((".pyc", ".pyo")):
                            continue
                        lines.append(f"{indent}  {fn}")
                    if len(lines) > 300:
                        lines.append("... (tree truncated at 300 entries)")
                        break
                return ToolResult(tool_call_id="", name="list_tree", content="\n".join(lines))
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="list_tree", content=f"list_tree failed: {exc}", is_error=True)

        @self.registry.register(
            description="Replace every occurrence of an exact string in a file. Returns the count.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path inside workspace"},
                    "old": {"type": "string", "description": "Exact text to find"},
                    "new": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old", "new"],
            },
        )
        async def replace_all(path: str, old: str, new: str) -> ToolResult:
            try:
                target = self._resolve(path)
                if not target.is_file():
                    return ToolResult(tool_call_id="", name="replace_all", content=f"Not a file: {path}", is_error=True)
                text = target.read_text(encoding="utf-8")
                count = text.count(old)
                if count == 0:
                    return ToolResult(
                        tool_call_id="", name="replace_all", content=f"'{old}' not found in {path}", is_error=True
                    )
                target.write_text(text.replace(old, new), encoding="utf-8")
                return ToolResult(
                    tool_call_id="",
                    name="replace_all",
                    content=f"Replaced {count} occurrence(s) of '{old}' in {path}",
                )
            except PermissionError as exc:
                return ToolResult(tool_call_id="", name="replace_all", content=str(exc), is_error=True)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="replace_all", content=f"replace_all failed: {exc}", is_error=True)


def _simple_diff(old_string: str, new_string: str) -> str:
    old_lines = old_string.splitlines()
    new_lines = new_string.splitlines()
    width = max(1, max((len(l) for l in old_lines + new_lines), default=0))
    out: list[str] = []
    for line in old_lines:
        out.append(f"- {line:<{width}}")
    for line in new_lines:
        out.append(f"+ {line:<{width}}")
    return "\n".join(out)
