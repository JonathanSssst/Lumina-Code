from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

from lumina.types import ToolResult


class ProjectScanner:
    """Collects structural context about the workspace to seed the agent."""

    _ignored: ClassVar[frozenset[str]] = frozenset({
        ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode",
    })
    _dep_files: ClassVar[tuple[str, ...]] = (
        "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
        "package.json", "Cargo.toml", "go.mod", "Pipfile", "poetry.lock",
        "Gemfile", "CMakeLists.txt",
    )
    _readme_files: ClassVar[tuple[str, ...]] = ("README.md", "README.rst", "README.txt", "Readme.md")

    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()

    def is_git_repo(self) -> bool:
        return (self.workspace / ".git").exists()

    def scan(self, max_files: int = 200) -> str:
        """Build a compact text summary of the project structure."""
        parts: list[str] = []
        lang_hint = self._detect_language()
        if lang_hint:
            parts.append(f"Detected language: {lang_hint}")

        git_branch = self._git_branch()
        if git_branch:
            parts.append(f"Git branch: {git_branch}")

        readme = self._read_first(self._readme_files)
        if readme:
            parts.append("README preview (first 60 lines):")
            body = readme.splitlines()[:60]
            parts.append("\n".join("  " + line for line in body))

        parts.append("Project tree (relative paths):")
        tree = self._build_tree(max_files)
        parts.append(tree or "  (empty)")

        deps = self._read_dependency_files()
        if deps:
            parts.append("Dependency files:")
            parts.append(deps)

        return "\n".join(parts)

    def _detect_language(self) -> str | None:
        counts: dict[str, int] = {}
        for p in self._iter_files():
            suffix = p.suffix.lower()
            if suffix in {".py"}:
                counts["Python"] = counts.get("Python", 0) + 1
            elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
                counts["JavaScript/TypeScript"] = counts.get("JavaScript/TypeScript", 0) + 1
            elif suffix in {".go"}:
                counts["Go"] = counts.get("Go", 0) + 1
            elif suffix in {".rs"}:
                counts["Rust"] = counts.get("Rust", 0) + 1
            elif suffix in {".java"}:
                counts["Java"] = counts.get("Java", 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)

    def _build_tree(self, max_files: int) -> str:
        lines: list[str] = []
        count = 0
        for dirpath, dirnames, filenames in os.walk(self.workspace):
            dirnames[:] = sorted(d for d in dirnames if d not in self._ignored)
            for fn in sorted(filenames):
                p = Path(dirpath) / fn
                if p.suffix.lower() in {".pyc", ".pyo"}:
                    continue
                rel = p.relative_to(self.workspace)
                depth = len(rel.parts)
                indent = "  " * max(0, depth - 1)
                lines.append(f"{indent}{rel.as_posix()}")
                count += 1
                if count >= max_files:
                    lines.append("  ... (truncated)")
                    return "\n".join(lines)
        return "\n".join(lines)

    def _read_dependency_files(self) -> str:
        blocks: list[str] = []
        for name in self._dep_files:
            for p in self.workspace.glob(name):
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                blocks.append(f"--- {p.relative_to(self.workspace).as_posix()} ---")
                blocks.append(text[:2000])
        return "\n".join(blocks)

    def _read_first(self, names: list[str]) -> str | None:
        for name in names:
            p = self.workspace / name
            if p.is_file():
                try:
                    return p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return None
        return None

    def _git_branch(self) -> str | None:
        head = self.workspace / ".git" / "HEAD"
        try:
            if not head.is_file():
                return None
            raw = head.read_text(encoding="utf-8").strip()
            return raw.split("refs/heads/")[-1] if "refs/heads/" in raw else None
        except OSError:
            return None

    def _iter_files(self) -> list[Path]:
        files: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.workspace):
            dirnames[:] = [d for d in dirnames if d not in self._ignored]
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    if p.is_file():
                        files.append(p)
                except OSError:
                    continue
        return files


def summarize_tool_result(result: ToolResult) -> str:
    """Compact, JSON-safe rendering of a tool result for LLM context."""
    if result.is_error:
        return f"[error] {result.content[:2000]}"
    return result.content[:4000]
