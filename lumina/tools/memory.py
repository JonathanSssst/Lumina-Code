from __future__ import annotations

from pathlib import Path

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult


class ProjectMemoryTools:
    """Persistent project memory: read/write AGENTS.md conventions."""

    def __init__(self, workspace: Path, registry: ToolRegistry) -> None:
        self.workspace = Path(workspace).resolve()
        self.registry = registry
        self._setup()

    def _agents_path(self) -> Path:
        for name in ("AGENTS.md", "agents.md"):
            p = self.workspace / name
            if p.exists():
                return p
        return self.workspace / "AGENTS.md"

    def _setup(self) -> None:

        @self.registry.register(
            description=(
                "Read the project's AGENTS.md file (project memory: build/test commands, "
                "code style, structure, conventions the agent should follow). Returns the "
                "full contents or a note that no AGENTS.md exists."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
        )
        async def read_agents() -> ToolResult:
            path = self._agents_path()
            if not path.is_file():
                return ToolResult(
                    tool_call_id="",
                    name="read_agents",
                    content="No AGENTS.md exists yet. Use write_agents to create one with project conventions.",
                )
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return ToolResult(
                    tool_call_id="", name="read_agents", content=str(exc), is_error=True
                )
            return ToolResult(tool_call_id="", name="read_agents", content=text[:8000])

        @self.registry.register(
            description=(
                "Write or update AGENTS.md (project memory). Pass full new contents to "
                "replace the file, or append=True to add a section without losing existing "
                "content. Use for build/test/lint commands, code style, and project "
                "conventions the agent should follow in future sessions."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Markdown contents to write or append"},
                    "append": {"type": "boolean", "description": "If true, append instead of replace"},
                },
                "required": ["content"],
            },
        )
        async def write_agents(content: str, append: bool = True) -> ToolResult:
            path = self._agents_path()
            try:
                if append and path.is_file():
                    existing = path.read_text(encoding="utf-8", errors="replace").strip()
                    if existing:
                        content = existing + "\n\n" + content.strip() + "\n"
                path.write_text(content.strip() + "\n", encoding="utf-8")
            except OSError as exc:
                return ToolResult(
                    tool_call_id="", name="write_agents", content=str(exc), is_error=True
                )
            return ToolResult(
                tool_call_id="",
                name="write_agents",
                content=f"Wrote AGENTS.md ({len(content)} chars). Project conventions now persist across sessions.",
            )

        self.registry.register_approval_checker("write_agents", lambda a: (False, ""))
        self.registry.register_approval_checker("read_agents", lambda a: (False, ""))
