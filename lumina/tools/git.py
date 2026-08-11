from __future__ import annotations

import asyncio
from pathlib import Path

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult


class GitTools:
    """Read-only git helpers (safe, no approval required)."""

    def __init__(self, workspace: Path, registry: ToolRegistry) -> None:
        self.workspace = Path(workspace).resolve()
        self.registry = registry
        self._setup()

    @staticmethod
    def _not_repo(out: str) -> bool:
        return "not a git repository" in out.lower()

    async def _git(self, *args: str, timeout: int = 30) -> tuple[int, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode or 0, stdout.decode("utf-8", errors="replace")
        except FileNotFoundError:
            return 1, "git executable not found on PATH"
        except Exception as exc:  # noqa: BLE001
            return 1, f"git error: {exc}"

    def _setup(self) -> None:

        @self.registry.register(
            description="Show git working-tree status (changed/new/deleted files).",
            parameters={
                "type": "object",
                "properties": {
                    "short": {"type": "boolean", "description": "Use short format"},
                },
                "required": [],
            },
        )
        async def git_status(short: bool = False) -> ToolResult:
            args = ["status", "--short"] if short else ["status"]
            code, out = await self._git(*args)
            if self._not_repo(out):
                return ToolResult(
                    tool_call_id="", name="git_status",
                    content="(workspace is not a git repository, git tracking unavailable)",
                    is_error=False,
                )
            return ToolResult(tool_call_id="", name="git_status", content=out.strip() or "(clean)", is_error=code != 0)

        @self.registry.register(
            description="Show the working-tree diff vs the last commit. Use --stat for summary.",
            parameters={
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean", "description": "Show staged diff (--cached)"},
                    "stat": {"type": "boolean", "description": "Show diffstat only"},
                    "max_lines": {"type": "integer", "description": "Max diff lines returned"},
                },
                "required": [],
            },
        )
        async def git_diff(staged: bool = False, stat: bool = False, max_lines: int = 200) -> ToolResult:
            args = ["diff", "--cached"] if staged else ["diff"]
            if stat:
                args.append("--stat")
            code, out = await self._git(*args)
            if self._not_repo(out):
                return ToolResult(
                    tool_call_id="", name="git_diff",
                    content="(workspace is not a git repository, git tracking unavailable)",
                    is_error=False,
                )
            if code != 0:
                return ToolResult(tool_call_id="", name="git_diff", content=out, is_error=True)
            lines = out.splitlines()
            truncated = max(0, len(lines) - max_lines)
            if truncated:
                out = "\n".join(lines[:max_lines]) + f"\n... ({truncated} more lines)"
            return ToolResult(tool_call_id="", name="git_diff", content=out.strip() or "(no diff)")

        @self.registry.register(
            description="Show the last N commit messages and hashes.",
            parameters={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Number of commits"},
                },
                "required": [],
            },
        )
        async def git_log(count: int = 10) -> ToolResult:
            code, out = await self._git("log", f"-{count}", "--oneline")
            if self._not_repo(out):
                return ToolResult(
                    tool_call_id="", name="git_log",
                    content="(workspace is not a git repository, git tracking unavailable)",
                    is_error=False,
                )
            return ToolResult(tool_call_id="", name="git_log", content=out.strip() or "(no commits)", is_error=code != 0)
