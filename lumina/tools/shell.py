from __future__ import annotations

import asyncio
from pathlib import Path

from lumina.config import Settings
from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult


class ShellTools:
    """Command execution tools with danger/safety classification."""

    def __init__(self, workspace: Path, registry: ToolRegistry, settings: Settings) -> None:
        self.workspace = Path(workspace).resolve()
        self.registry = registry
        self.settings = settings
        self._setup()

    def _classify(self, command: str) -> tuple[bool, str]:
        """Return (requires_approval, reason) for a shell command."""
        normalized = " ".join(command.strip().split()).lower()
        first = normalized.split(" ", 1)[0].strip(";|&")

        if any(danger in normalized for danger in self.settings.danger_command_list):
            matched = next(d for d in self.settings.danger_command_list if d in normalized)
            return True, f"matches danger pattern '{matched}'"
        if first in self.settings.safe_command_list:
            return False, ""
        if any(normalized == s or normalized.startswith(s + " ") for s in self.settings.safe_command_list):
            return False, ""
        return True, f"unknown command '{first}'"

    async def _run(self, command: str, timeout: int) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")
            tail = output[-8000:]
            prefix = "" if len(output) <= 8000 else f"[truncated, {len(output)} chars total]\n"
            return ToolResult(
                tool_call_id="",
                name="run_command",
                content=f"exit={proc.returncode}\n{prefix}{tail}",
                is_error=proc.returncode != 0,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_call_id="",
                name="run_command",
                content=f"Command timed out after {timeout}s",
                is_error=True,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_call_id="", name="run_command", content=f"run failed: {exc}", is_error=True)

    def _setup(self) -> None:

        @self.registry.register(
            description="Execute a shell command in the workspace directory. Unknown or dangerous "
            "commands require user approval. Output is truncated to the last 8000 chars.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                },
                "required": ["command"],
            },
        )
        async def run_command(command: str, timeout: int = 120) -> ToolResult:
            return await self._run(command, timeout)

        @self.registry.register(
            description="Run the project test suite (pytest). Returns the report tail.",
            parameters={
                "type": "object",
                "properties": {
                    "args": {"type": "string", "description": "Extra pytest arguments"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                },
                "required": [],
            },
        )
        async def run_tests(args: str = "", timeout: int = 300) -> ToolResult:
            result = await self._run(f"python -m pytest {args} -q", timeout)
            result.name = "run_tests"
            return result

        self.registry.register_approval_checker("run_command", lambda a: self._classify(a.get("command", "")))
        self.registry.register_approval_checker("run_tests", lambda a: (False, ""))
