from __future__ import annotations

import asyncio

import pytest

from lumina.config import Settings
from lumina.llm.client import DeepSeekClient

_PROVIDER_ENV = (
    "LUMINA_LLM_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_PLANNER_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "OPENAI_PLANNER_MODEL",
)


def _clean(monkeypatch) -> None:
    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)


def test_auto_defaults_to_deepseek(monkeypatch):
    _clean(monkeypatch)
    s = Settings(_env_file=None, DEEPSEEK_API_KEY="sk-d", LUMINA_LLM_PROVIDER="auto")
    assert s.provider == "deepseek"
    assert s.api_key == "sk-d"
    assert s.base_url == "https://api.deepseek.com"
    assert s.model == "deepseek-chat"
    assert s.planner_model == "deepseek-reasoner"
    assert s.key_env_var == "DEEPSEEK_API_KEY"


def test_auto_switches_to_openai_when_key_set(monkeypatch):
    _clean(monkeypatch)
    s = Settings(_env_file=None, OPENAI_API_KEY="sk-o", LUMINA_LLM_PROVIDER="auto")
    assert s.provider == "openai"
    assert s.api_key == "sk-o"
    assert s.base_url == "https://api.openai.com/v1"
    assert s.model == "gpt-4o-mini"
    assert s.planner_model == "gpt-4o"
    assert s.key_env_var == "OPENAI_API_KEY"


def test_forced_provider_wins_over_key(monkeypatch):
    _clean(monkeypatch)
    s = Settings(_env_file=None, 
        LUMINA_LLM_PROVIDER="deepseek",
        DEEPSEEK_API_KEY="sk-d",
        OPENAI_API_KEY="sk-o",
    )
    assert s.provider == "deepseek"
    assert s.api_key == "sk-d"

    s2 = Settings(_env_file=None, 
        LUMINA_LLM_PROVIDER="openai",
        DEEPSEEK_API_KEY="sk-d",
        OPENAI_API_KEY="sk-o",
    )
    assert s2.provider == "openai"
    assert s2.api_key == "sk-o"


def test_custom_openai_compatible_vendor(monkeypatch):
    _clean(monkeypatch)
    s = Settings(_env_file=None, 
        LUMINA_LLM_PROVIDER="openai",
        OPENAI_API_KEY="sk-ollama",
        OPENAI_BASE_URL="http://localhost:11434/v1",
        OPENAI_MODEL="qwen2.5-coder",
        OPENAI_PLANNER_MODEL="qwen2.5-coder:72b",
    )
    assert s.provider == "openai"
    assert s.base_url == "http://localhost:11434/v1"
    assert s.model == "qwen2.5-coder"
    assert s.planner_model == "qwen2.5-coder:72b"


def test_client_uses_active_provider(monkeypatch):
    _clean(monkeypatch)
    s = Settings(_env_file=None, 
        LUMINA_LLM_PROVIDER="openai",
        OPENAI_API_KEY="sk-o",
        OPENAI_BASE_URL="http://localhost:11434/v1/",
        OPENAI_MODEL="qwen2.5-coder",
    )
    client = DeepSeekClient(s)
    try:
        assert client.base_url == "http://localhost:11434/v1"
        assert client.model == "qwen2.5-coder"
        assert client.api_key == "sk-o"
    finally:
        asyncio.run(client.aclose())


def test_validate_for_run_reports_active_provider(monkeypatch):
    _clean(monkeypatch)
    s = Settings(_env_file=None, LUMINA_LLM_PROVIDER="openai")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        s.validate_for_run()

    s2 = Settings(_env_file=None, LUMINA_LLM_PROVIDER="deepseek")
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        s2.validate_for_run()

    s3 = Settings(_env_file=None, LUMINA_LLM_PROVIDER="deepseek", DEEPSEEK_API_KEY="sk-d")
    s3.validate_for_run()

