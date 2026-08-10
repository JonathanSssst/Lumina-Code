from __future__ import annotations

import re
from pathlib import Path

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")


def read_env(path: Path) -> dict[str, str]:
    """Read a KEY=VALUE .env file into a dict (first occurrence wins)."""
    env_path = Path(path)
    if not env_path.exists():
        return {}
    result: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _ENV_LINE.match(line)
        if m:
            key = m.group(1)
            if key not in result:
                result[key] = line[len(m.group(1)) + 1 :].strip().strip('"').strip("'")
    return result


def write_env(path: Path, updates: dict[str, str]) -> None:
    """Update or append KEY=VALUE entries, preserving comments and unknown keys."""
    env_path = Path(path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines() if env_path.exists() else []
    updated: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _ENV_LINE.match(line)
        if m and m.group(1) in updates:
            out.append(f"{m.group(1)}={updates[m.group(1)]}")
            updated.add(m.group(1))
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in updated:
            out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
