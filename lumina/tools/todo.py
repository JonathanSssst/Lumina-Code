"""Agent-managed todo list tool for large, multi-step tasks.

The model can create / replace a checklist with `update_todo` and re-read the
current progress with `todo_list`. The whole list is rewritten on every update
(no fragile ids to keep track of), mirroring the todowrite UX used by coding
agents.
"""

from __future__ import annotations

import logging
from typing import Any

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult

logger = logging.getLogger(__name__)

_TODO_SCHEMA = {
    "type": "object",
    "properties": {
        "todos": {
            "type": "array",
            "description": (
                "The full todo list. Replaces the previous list entirely. "
                "Each item is {content: str, status: pending|in_progress|completed|cancelled}. "
                "Use this for large tasks: break the work into concrete steps and keep this "
                "list up to date as you make progress."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled"],
                    },
                },
                "required": ["content"],
            },
        }
    },
    "required": ["todos"],
}

_VALID_STATUS = ("pending", "in_progress", "completed", "cancelled")

_ICON = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
    "cancelled": "[~]",
}


class TodoTools:
    """Registers `update_todo` and `todo_list` tools bound to one agent run."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self._todos: list[dict[str, str]] = []
        self._setup()

    def _render(self) -> str:
        counts = {s: 0 for s in _VALID_STATUS}
        lines = []
        for i, item in enumerate(self._todos, start=1):
            status = item.get("status", "pending")
            counts[status] += 1
            lines.append(f"{_ICON.get(status, '[ ]')} {i}. {item['content']}")
        header = f"## 待办列表（{len(self._todos)} 项，已完成 {counts['completed']}）\n"
        body = "\n".join(lines) if lines else "_（空）_"
        return header + body

    def _setup(self) -> None:

        @self.registry.register(
            description=(
                "Create or replace the agent's todo list for the current task. "
                "Pass the COMPLETE new list (existing items keep their status if you resend them). "
                "For large tasks, plan the steps up front and update statuses as you finish each one."
            ),
            parameters=_TODO_SCHEMA,
        )
        async def update_todo(todos: list[dict[str, Any]]) -> ToolResult:
            try:
                cleaned: list[dict[str, str]] = []
                for raw in todos:
                    if not isinstance(raw, dict) or not str(raw.get("content") or "").strip():
                        raise ValueError("each todo item needs a non-empty 'content'")
                    status = str(raw.get("status") or "pending")
                    if status not in _VALID_STATUS:
                        raise ValueError(f"invalid todo status {status!r} (use {', '.join(_VALID_STATUS)})")
                    cleaned.append({"content": str(raw["content"]).strip(), "status": status})
                self._todos = cleaned
                return ToolResult(tool_call_id="", name="update_todo", content=self._render())
            except ValueError as exc:
                return ToolResult(
                    tool_call_id="", name="update_todo", content=f"update_todo failed: {exc}", is_error=True
                )

        @self.registry.register(
            description="Show the agent's current todo list and progress.",
        )
        async def todo_list() -> ToolResult:
            return ToolResult(tool_call_id="", name="todo_list", content=self._render())
