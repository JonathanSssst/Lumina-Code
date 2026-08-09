from __future__ import annotations

import os
import re
from pathlib import Path

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult


class SearchTools:
    """Glob + grep over the workspace using pure Python (no ripgrep dependency)."""

    def __init__(self, workspace: Path, registry: ToolRegistry) -> None:
        self.workspace = Path(workspace).resolve()
        self.registry = registry
        self._ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache"}
        self._setup()

    def _iter_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self._ignored]
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    if p.is_file():
                        files.append(p)
                except OSError:
                    continue
        return files

    def _setup(self) -> None:

        @self.registry.register(
            description="Find files by glob pattern (e.g. '**/*.py').",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern relative to workspace"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["pattern"],
            },
        )
        async def glob(pattern: str, limit: int = 100) -> ToolResult:
            try:
                matches = sorted(p.as_posix() for p in self.workspace.glob(pattern))
                matches = [m for m in matches if not any(part in self._ignored for part in Path(m).parts)]
                truncated = len(matches) - limit if len(matches) > limit else 0
                body = "\n".join(matches[:limit])
                if truncated > 0:
                    body += f"\n... ({truncated} more)"
                return ToolResult(tool_call_id="", name="glob", content=body or "(no matches)")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="glob", content=f"glob failed: {exc}", is_error=True)

        @self.registry.register(
            description="Regex search across workspace files. Returns file:line matches.",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression"},
                    "include": {"type": "string", "description": "File glob filter e.g. '*.py'"},
                    "limit": {"type": "integer", "description": "Max results"},
                },
                "required": ["pattern"],
            },
        )
        async def grep(pattern: str, include: str = "*", limit: int = 100) -> ToolResult:
            try:
                regex = re.compile(pattern)
            except re.error as exc:
                return ToolResult(tool_call_id="", name="grep", content=f"Invalid regex: {exc}", is_error=True)
            try:
                out: list[str] = []
                for p in self._iter_files(self.workspace):
                    if include != "*" and not p.match(include):
                        continue
                    try:
                        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                            if regex.search(line):
                                rel = p.relative_to(self.workspace).as_posix()
                                out.append(f"{rel}:{i}: {line.strip()[:160]}")
                                if len(out) >= limit:
                                    return ToolResult(
                                        tool_call_id="",
                                        name="grep",
                                        content="\n".join(out) + f"\n... (truncated at {limit})",
                                    )
                    except OSError:
                        continue
                return ToolResult(tool_call_id="", name="grep", content="\n".join(out) or "(no matches)")
            except Exception as exc:  # noqa: BLE001
                return ToolResult(tool_call_id="", name="grep", content=f"grep failed: {exc}", is_error=True)
