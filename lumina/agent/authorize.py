from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from lumina.types import ToolCall, ToolResult


class AsyncApprover(Protocol):
    """Decides whether a tool call may execute."""

    async def approve(self, name: str, arguments: dict[str, Any], reason: str) -> bool: ...


class AutoApprover:
    """Approves everything — use only for fully headless runs."""

    async def approve(self, name: str, arguments: dict[str, Any], reason: str) -> bool:
        return True


@dataclass
class Hooks:
    """Async callbacks for UI / observability integration."""

    on_tool_call: Callable[[ToolCall], Awaitable[None]] | None = None
    on_tool_result: Callable[[ToolResult], Awaitable[None]] | None = None
    on_assistant_message: Callable[[str], Awaitable[None]] | None = None
    on_reasoning: Callable[[str], Awaitable[None]] | None = None
    on_finish: Callable[[dict[str, Any]], Awaitable[None]] | None = None


@dataclass
class AgentResult:
    final_content: str
    iterations: int
    tool_calls_made: int
    total_tokens: int
    stopped_reason: str
    transcript: list[dict[str, Any]] = field(default_factory=list)


class DeniedToolError(Exception):
    """Raised when a user denies a tool call; handled by the loop."""

    def __init__(self, tool_call_id: str, name: str, reason: str) -> None:
        self.tool_call_id = tool_call_id
        self.name = name
        self.reason = reason
        super().__init__(f"tool '{name}' denied: {reason}")
