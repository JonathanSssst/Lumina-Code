from __future__ import annotations

from pathlib import Path

import pytest

from lumina.config import Settings
from lumina.factory import build_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef buggy(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        "from src.calc import add, buggy\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def settings() -> Settings:
    return Settings(
        DEEPSEEK_API_KEY="test-key",
        LUMINA_MAX_ITERATIONS=10,
        LUMINA_MAX_TOKENS=100000,
    )


@pytest.fixture
def registry(workspace: Path, settings: Settings) -> object:
    return build_registry(workspace, settings)
