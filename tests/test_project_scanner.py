from __future__ import annotations

from pathlib import Path

from lumina.context.project import ProjectScanner


def test_scanner_git_branch_and_readme(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/feature-x\n", encoding="utf-8")
    readme_lines = ["# My Project"] + ["body line"] * 30
    (tmp_path / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")
    (tmp_path / "app.js").write_text("x", encoding="utf-8")
    (tmp_path / "main.go").write_text("x", encoding="utf-8")
    (tmp_path / "lib.rs").write_text("x", encoding="utf-8")
    (tmp_path / "Main.java").write_text("x", encoding="utf-8")
    (tmp_path / "bin.pyc").write_text("x", encoding="utf-8")

    scanner = ProjectScanner(tmp_path)
    text = scanner.scan()
    assert "Git branch: feature-x" in text
    assert "README preview" in text
    assert "Detected language: JavaScript/TypeScript" in text
    assert "bin.pyc" not in text


def test_scanner_not_git_repo(tmp_path):
    assert ProjectScanner(tmp_path).is_git_repo() is False


def test_scanner_no_files_no_language(tmp_path):
    assert ProjectScanner(tmp_path).scan() == "Project tree (relative paths):\n  (empty)"


def test_scanner_tree_truncates(tmp_path):
    for i in range(201):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    scanner = ProjectScanner(tmp_path)
    text = scanner.scan(max_files=200)
    assert "... (truncated)" in text


def test_scanner_reads_dependency_file(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
    text = ProjectScanner(tmp_path).scan()
    assert "pyproject.toml" in text
    assert "[tool.pytest]" in text


def test_git_branch_detached_head(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("abcdef1234", encoding="utf-8")
    assert ProjectScanner(tmp_path)._git_branch() is None


def test_git_branch_read_error(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    head = tmp_path / ".git" / "HEAD"
    head.write_text("ref: refs/heads/main", encoding="utf-8")
    real_read_text = Path.read_text

    def boom(self, *a, **k):
        if self == head:
            raise OSError
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", boom)
    assert ProjectScanner(tmp_path)._git_branch() is None


def test_readme_read_error(monkeypatch, tmp_path):
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    real_read_text = Path.read_text

    def boom(self, *a, **k):
        if self.name == "README.md":
            raise OSError
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", boom)
    scanner = ProjectScanner(tmp_path)
    assert scanner._read_first(list(scanner._readme_files)) is None
