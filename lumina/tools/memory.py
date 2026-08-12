from __future__ import annotations

import re
from pathlib import Path

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult


def _safe_name(name: str) -> str:
    """Normalize a memory entry name to a safe <name>.md slug."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-")
    if not slug:
        raise ValueError("Memory name must contain at least one letter, digit, dot, dash or underscore.")
    if len(slug) > 64:
        slug = slug[:64].rstrip("-")
    return slug


class ProjectMemoryTools:
    """Persistent project memory: AGENTS.md conventions + a searchable knowledge base.

    - AGENTS.md holds project conventions (read/write via read_agents/write_agents).
    - The knowledge base lives in ``.lumina/memory/<name>.md`` (project) and
      ``~/.config/lumina/memory/<name>.md`` (global, shared across projects).
      Entries are written with memory_write and retrieved with memory_read,
      listed with memory_list, and searched by keyword with memory_search.
    """

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

    def _project_memory_dir(self) -> Path:
        return self.workspace / ".lumina" / "memory"

    def _global_memory_dir(self) -> Path:
        return Path.home() / ".config" / "lumina" / "memory"

    def _memory_dirs(self) -> list[Path]:
        return [self._project_memory_dir(), self._global_memory_dir()]

    def _iter_entries(self) -> list[tuple[str, Path, Path]]:
        """Return (name, file, source_dir) for every knowledge base entry."""
        out: list[tuple[str, Path, Path]] = []
        for d in self._memory_dirs():
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.md")):
                out.append((p.stem, p, d))
        return out

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

        @self.registry.register(
            description=(
                "Write or append a knowledge base entry under .lumina/memory/<name>.md "
                "(project) or, when shared=True, ~/.config/lumina/memory/<name>.md (shared "
                "across all projects). Use memory_list to see existing entries and "
                "memory_search to find relevant ones before writing, so you update instead "
                "of duplicating. Entries persist across sessions."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entry name (a-z, 0-9, dot, dash, underscore)"},
                    "content": {"type": "string", "description": "Markdown contents to write or append"},
                    "append": {"type": "boolean", "description": "If true, append instead of replace"},
                    "shared": {"type": "boolean", "description": "Write to the global shared memory dir instead of the project"},
                },
                "required": ["name", "content"],
            },
        )
        async def memory_write(name: str, content: str, append: bool = True, shared: bool = False) -> ToolResult:
            try:
                slug = _safe_name(name)
            except ValueError as exc:
                return ToolResult(tool_call_id="", name="memory_write", content=str(exc), is_error=True)
            base = self._global_memory_dir() if shared else self._project_memory_dir()
            path = base / f"{slug}.md"
            try:
                base.mkdir(parents=True, exist_ok=True)
                if append and path.is_file():
                    existing = path.read_text(encoding="utf-8", errors="replace").strip()
                    if existing:
                        content = existing + "\n\n" + content.strip() + "\n"
                path.write_text(content.strip() + "\n", encoding="utf-8")
            except OSError as exc:
                return ToolResult(tool_call_id="", name="memory_write", content=str(exc), is_error=True)
            scope = "global" if shared else "project"
            return ToolResult(
                tool_call_id="",
                name="memory_write",
                content=f"Wrote memory entry '{slug}' ({scope}, {len(content)} chars). It is now searchable via memory_search.",
            )

        @self.registry.register(
            description=(
                "Read a knowledge base entry by name. Searches project memory "
                "(.lumina/memory) first, then the global shared memory (~/.config/lumina/memory)."
            ),
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Entry name (without .md)"}},
                "required": ["name"],
            },
        )
        async def memory_read(name: str) -> ToolResult:
            try:
                slug = _safe_name(name)
            except ValueError as exc:
                return ToolResult(tool_call_id="", name="memory_read", content=str(exc), is_error=True)
            for d in self._memory_dirs():
                path = d / f"{slug}.md"
                if path.is_file():
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError as exc:
                        return ToolResult(tool_call_id="", name="memory_read", content=str(exc), is_error=True)
                    scope = "global" if d == self._global_memory_dir() else "project"
                    return ToolResult(
                        tool_call_id="",
                        name="memory_read",
                        content=f"===== MEMORY: {slug} ({scope}) =====\n{text[:8000]}",
                    )
            return ToolResult(
                tool_call_id="",
                name="memory_read",
                content=f"No memory entry named '{slug}'. Use memory_list to see what exists.",
                is_error=True,
            )

        @self.registry.register(
            description=(
                "List all knowledge base entries. Returns each entry name, its source "
                "(project/global), and char count so the agent can decide what to read."
            ),
            parameters={"type": "object", "properties": {}, "required": []},
        )
        async def memory_list() -> ToolResult:
            entries = self._iter_entries()
            if not entries:
                return ToolResult(
                    tool_call_id="",
                    name="memory_list",
                    content="No memory entries yet. Use memory_write to store project knowledge.",
                )
            lines = []
            for name, path, d in entries:
                scope = "global" if d == self._global_memory_dir() else "project"
                try:
                    size = len(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    size = 0
                lines.append(f"- {name} [{scope}] ({size} chars)")
            return ToolResult(
                tool_call_id="",
                name="memory_list",
                content="===== MEMORY ENTRIES =====\n" + "\n".join(lines),
            )

        @self.registry.register(
            description=(
                "Keyword search across the knowledge base (project + global memory). "
                "Returns the matching entry name, source, and up to 3 context lines per "
                "hit. Use before deciding what to read or update."
            ),
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Keywords to search for (case-insensitive)"}},
                "required": ["query"],
            },
        )
        async def memory_search(query: str) -> ToolResult:
            terms = [t.lower() for t in re.split(r"\s+", query.strip()) if t]
            if not terms:
                return ToolResult(
                    tool_call_id="", name="memory_search", content="Provide keywords to search for.", is_error=True
                )
            hits: list[tuple[int, str, str]] = []
            for name, path, d in self._iter_entries():
                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                scope = "global" if d == self._global_memory_dir() else "project"
                body = " ".join(lines).lower()
                if not all(t in body for t in terms):
                    continue
                score = sum(body.count(t) for t in terms)
                hits.append((score, name, scope))
            hits.sort(reverse=True)
            if not hits:
                return ToolResult(
                    tool_call_id="",
                    name="memory_search",
                    content=f"No memory entries matched '{query}'. Try broader keywords or memory_list.",
                )
            lines = [f"- {name} [{scope}] ({score} hits)" for score, name, scope in hits[:20]]
            return ToolResult(
                tool_call_id="",
                name="memory_search",
                content="===== SEARCH RESULTS =====\n" + "\n".join(lines),
            )

        self.registry.register_approval_checker("write_agents", lambda a: (False, ""))
        self.registry.register_approval_checker("read_agents", lambda a: (False, ""))
        self.registry.register_approval_checker("memory_write", lambda a: (False, ""))
        self.registry.register_approval_checker("memory_read", lambda a: (False, ""))
        self.registry.register_approval_checker("memory_list", lambda a: (False, ""))
        self.registry.register_approval_checker("memory_search", lambda a: (False, ""))
