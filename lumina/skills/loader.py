from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lumina.config import workspace_data_dir

SKILL_DIR_NAMES = ("skills",)

_LOCAL_SKILLS = Path.home() / ".config" / "lumina" / "skills"


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    instructions: str = ""


class SkillLoader:
    """Loads skills from the per-workspace user data dir and `~/.config/lumina/skills/`.

    A skill is a `<name>/skill.md` (or `<name>.md`) file whose front-matter block
    declares metadata, followed by the instruction body injected into the agent context.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.project_dir = workspace_data_dir(workspace) / "skills"
        self._skills: list[Skill] = []
        self._loaded = False

    def load(self) -> list[Skill]:
        if self._loaded:
            return self._skills
        for root in (self.project_dir, _LOCAL_SKILLS):
            self._load_dir(root)
        self._loaded = True
        return self._skills

    def _load_dir(self, root: Path) -> None:
        if not root.is_dir():
            return
        for md in sorted(root.rglob("*.md")):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            skill = self._parse(text, md.stem)
            if skill:
                self._skills.append(skill)

    def _parse(self, text: str, fallback_name: str) -> Skill | None:
        front = _parse_frontmatter(text)
        if front is None:
            return None
        name = front.get("name", fallback_name)
        description = front.get("description", "")
        triggers = [t.strip().lower() for t in front.get("trigger", "").split(",") if t.strip()]
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                body = parts[2].strip()
        return Skill(name=name, description=description, triggers=triggers, instructions=body)

    def match(self, user_input: str) -> list[Skill]:
        """Return skills whose triggers appear in the user input."""
        needle = user_input.lower()
        return [s for s in self.load() if any(t in needle for t in s.triggers)]

    def all(self) -> list[Skill]:
        return self.load()


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta
