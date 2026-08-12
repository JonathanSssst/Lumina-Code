from __future__ import annotations

import asyncio
import socket
import sys

from typer.testing import CliRunner

from lumina.agent.authorize import AgentResult
from lumina.cli import (
    CliApprover,
    CliHooks,
    _chat,
    _fetch_latest_release_tag,
    _find_free_port,
    _parse_semver,
    _print_result,
    _print_sessions,
    app,
)
from lumina.config import Settings
from lumina.store import SessionInfo

runner = CliRunner()


def _settings(api_key: str = "k") -> Settings:
    return Settings(DEEPSEEK_API_KEY=api_key)


class _FakeClient:
    async def aclose(self) -> None:
        pass


class _FakeAgent:
    def __init__(self, result: AgentResult) -> None:
        self.result = result
        self.client = _FakeClient()

    async def run(self, *args, **kwargs) -> AgentResult:
        return self.result


def _fake_build_agent(monkeypatch, result: AgentResult):
    monkeypatch.setattr("lumina.cli.build_agent", lambda *a, **k: _FakeAgent(result))


# --- pure helpers ---


def test_parse_semver_normal():
    assert _parse_semver("v1.2.3") == (1, 2, 3)


def test_parse_semver_strips_prefix_and_prerelease():
    assert _parse_semver("v2.10.4-beta.1") == (2, 10, 4)


def test_parse_semver_garbage():
    assert _parse_semver("not-a-version") == ()


def test_parse_semver_empty():
    assert _parse_semver("") == ()


def test_find_free_port_returns_candidate():
    assert _find_free_port("127.0.0.1", 0, 1) == 0


def test_find_free_port_returns_none_when_blocked():
    held = []
    try:
        for port in range(50050, 50053):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(("127.0.0.1", port))
            s.listen(1)
            held.append(s)
        assert _find_free_port("127.0.0.1", 50050, 3) is None
    finally:
        for s in held:
            s.close()


# --- _fetch_latest_release_tag ---


def test_fetch_latest_release_tag_success(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"tag_name": "v1.2.3"}

    monkeypatch.setattr("httpx.get", lambda *a, **k: Resp())
    assert _fetch_latest_release_tag() == "v1.2.3"


def test_fetch_latest_release_tag_http_error(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.HTTPStatusError("x", request=None, response=None)

    monkeypatch.setattr("httpx.get", boom)
    assert _fetch_latest_release_tag() is None


def test_fetch_latest_release_tag_missing_field(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    monkeypatch.setattr("httpx.get", lambda *a, **k: Resp())
    assert _fetch_latest_release_tag() is None


# --- CliApprover ---


def test_approver_auto_yes():
    assert asyncio.run(CliApprover(auto_yes=True).approve("run_command", {}, "test")) is True


def test_approver_asks_and_denies(monkeypatch, capsys):
    monkeypatch.setattr("lumina.cli.Confirm.ask", lambda *a, **k: False)
    assert asyncio.run(CliApprover().approve("run_command", {"cmd": "x"}, "test")) is False
    assert "Approval required" in capsys.readouterr().out


def test_approver_asks_and_allows(monkeypatch):
    monkeypatch.setattr("lumina.cli.Confirm.ask", lambda *a, **k: True)
    assert asyncio.run(CliApprover().approve("run_command", {}, "test")) is True


# --- _print_result branches ---


def test_print_result_normal(capsys):
    result = AgentResult(
        final_content="# done",
        iterations=3,
        tool_calls_made=4,
        total_tokens=100,
        stopped_reason="completed",
    )
    _print_result(result)
    out = capsys.readouterr().out
    assert "iterations=3" in out
    assert "tool_calls=4" in out
    assert "budget" not in out.lower()


def test_print_result_budget_exhausted_hint(capsys):
    result = AgentResult("x", 1, 0, 50, "budget_exhausted")
    _print_result(result)
    assert "token 预算" in capsys.readouterr().out


def test_print_result_iterations_exhausted_hint(capsys):
    result = AgentResult("x", 1, 0, 50, "iterations_exhausted")
    _print_result(result)
    out = capsys.readouterr().out
    assert "迭代" in out
    assert "LUMINA_MAX_ITERATIONS" in out


def test_print_result_auto_fix_exhausted_hint(capsys):
    result = AgentResult("x", 1, 0, 50, "auto_fix_exhausted")
    _print_result(result)
    assert "自动修复" in capsys.readouterr().out


# --- _print_sessions ---


class _FakeStore:
    def __init__(self, sessions):
        self._sessions = sessions

    def list_sessions(self):
        return self._sessions

    def close(self):
        pass


def test_print_sessions_empty(capsys):
    _print_sessions(_FakeStore([]))
    assert "No sessions yet" in capsys.readouterr().out


def test_print_sessions_table(capsys):
    store = _FakeStore(
        [SessionInfo(1, "项目调研", "C:\\proj", "2026-01-01 00:00:00", "2026-01-02 00:00:00", 3)]
    )
    _print_sessions(store)
    out = capsys.readouterr().out
    assert "项目调研" in out
    assert "Sessions" in out


# --- doctor ---


def test_doctor_shows_config(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("lumina.cli.get_settings", lambda: _settings())
    monkeypatch.setattr("lumina.cli.resolve_env_file", lambda _: None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    out = result.stdout
    assert "api_key:" in out
    assert "set" in out
    assert "base_url:" in out


def test_doctor_flags_missing_key(monkeypatch, capsys):
    monkeypatch.setattr("lumina.cli.get_settings", lambda: _settings(""))
    monkeypatch.setattr("lumina.cli.resolve_env_file", lambda _: None)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "MISSING" in result.stdout


# --- run ---


def test_run_executes_task_and_prints_result(monkeypatch, tmp_path):
    result = AgentResult("the fix", 2, 3, 200, "completed")
    _fake_build_agent(monkeypatch, result)
    out = runner.invoke(app, ["run", "fix it", "-w", str(tmp_path)])
    assert out.exit_code == 0
    assert "the fix" in out.stdout
    assert "iterations=2" in out.stdout


def test_run_with_yes_and_quiet(monkeypatch, tmp_path):
    _fake_build_agent(monkeypatch, AgentResult("ok", 1, 0, 10, "completed"))
    out = runner.invoke(app, ["run", "task", "-w", str(tmp_path), "--yes", "--quiet"])
    assert out.exit_code == 0


def test_run_missing_api_key_exits(monkeypatch, tmp_path):
    monkeypatch.setattr("lumina.cli.get_settings", lambda: _settings(""))
    out = runner.invoke(app, ["run", "task", "-w", str(tmp_path)])
    assert out.exit_code == 1
    assert "DEEPSEEK_API_KEY" in out.stdout


# --- chat ---


def test_chat_list_no_sessions(monkeypatch):
    monkeypatch.setattr("lumina.cli._load_settings", lambda: _settings())
    monkeypatch.setattr("lumina.cli._open_store", lambda _: _FakeStore([]))
    out = runner.invoke(app, ["chat", "--list"])
    assert out.exit_code == 0
    assert "No sessions yet" in out.stdout


def test_chat_list_shows_sessions(monkeypatch):
    store = _FakeStore(
        [SessionInfo(3, "重构", "C:\\proj", "2026-01-01 00:00:00", "2026-01-02 00:00:00", 5)]
    )
    monkeypatch.setattr("lumina.cli._load_settings", lambda: _settings())
    monkeypatch.setattr("lumina.cli._open_store", lambda _: store)
    out = runner.invoke(app, ["chat", "--list"])
    assert out.exit_code == 0
    assert "重构" in out.stdout


def test_chat_slash_commands(monkeypatch, capsys):
    prompts = iter(["/list", "/resume 99", "/resume", "/delete 5", "/new", "/exit"])
    monkeypatch.setattr("lumina.cli.Prompt.ask", lambda *a, **k: next(prompts))
    store = _FakeStore([])
    store.create_session = lambda _ws, *_a: 2
    store.get_session = lambda sid: None if sid == 99 else _FakeSession()
    store.delete_session = lambda sid: None
    store.get_messages = lambda sid: []
    store.append_message = lambda sid, m: None
    store.set_title = lambda sid, t: None

    asyncio.run(_chat(_settings(), "C:\\proj", False, store, 1))
    out = capsys.readouterr().out
    assert "No sessions yet" in out
    assert "Session 99 not found" in out
    assert "Usage: /resume" in out
    assert "Deleted session 5" in out
    assert "New session #2" in out


class _FakeSession:
    id = 99
    message_count = 0


def test_chat_eof_exits_loop(monkeypatch, capsys):
    def boom(*a, **k):
        raise EOFError

    monkeypatch.setattr("lumina.cli.Prompt.ask", boom)
    store = _FakeStore([])
    asyncio.run(_chat(_settings(), "C:\\proj", True, store, 1))


def test_chat_resume_existing_session(monkeypatch, capsys):
    prompts = iter(["/resume 5", "/exit"])
    monkeypatch.setattr("lumina.cli.Prompt.ask", lambda *a, **k: next(prompts))
    store = _FakeStore([])
    store.get_session = lambda sid: _FakeSession()
    asyncio.run(_chat(_settings(), "C:\\proj", True, store, 1))
    assert "Resumed session #5" in capsys.readouterr().out


def test_chat_sends_message_and_prints_result(monkeypatch, capsys):
    prompts = iter(["hello", "/exit"])
    monkeypatch.setattr("lumina.cli.Prompt.ask", lambda *a, **k: next(prompts))
    _fake_build_agent(monkeypatch, AgentResult("answer", 1, 0, 5, "completed"))
    store = _FakeStore([])
    store.get_messages = lambda sid: []
    store.append_message = lambda sid, m: None
    store.get_session = lambda sid: _FakeSession()
    store.set_title = lambda sid, t: None

    asyncio.run(_chat(_settings(), "C:\\proj", True, store, 1))
    out = capsys.readouterr().out
    assert "answer" in out
    assert "iterations=1" in out


def test_cli_hooks_second_thinking_adds_blank_line(monkeypatch):
    printed = []

    class FakeConsole:
        def print(self, *args, **kwargs):
            printed.append((args, kwargs))

    monkeypatch.setattr("lumina.cli.console", FakeConsole())
    hooks = CliHooks()
    asyncio.run(hooks.on_thinking_done(1.0))
    asyncio.run(hooks.on_thinking_done(2.0))
    assert any(len(a) == 0 for a, _ in printed)


# --- web missing deps ---
def test_web_missing_deps_exits(monkeypatch, tmp_path):
    monkeypatch.setattr("lumina.cli._load_settings", lambda: _settings())
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    out = runner.invoke(app, ["web", "-w", str(tmp_path)])
    assert out.exit_code == 1
    assert "Missing web dependencies" in out.stdout


def test_python_m_dash_m_lumina_runs():
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "lumina", "-version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0
    assert "LuminaCode version" in result.stdout


# --- end-to-end: real agent, scripted LLM ---


def test_run_once_end_to_end_with_fake_llm(monkeypatch, tmp_path, capsys):
    from lumina import cli
    from lumina.types import LLMResponse, ToolCall, Usage

    script = [
        LLMResponse(
            content="",
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "src/calc.py"})],
            usage=Usage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        ),
        LLMResponse(
            content="All good",
            tool_calls=[],
            usage=Usage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        ),
        LLMResponse(
            content="APPROVED: all requirements met",
            tool_calls=[],
            usage=Usage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        ),
    ]

    class FakeClient:
        def __init__(self, settings):
            self.script = list(script)

        async def chat(
            self,
            messages,
            tools=None,
            stream_callback=None,
            reasoning_callback=None,
            temperature=None,
            max_tokens=None,
            model=None,
        ):
            return self.script.pop(0)

        async def aclose(self):
            pass

    monkeypatch.setattr("lumina.factory.DeepSeekClient", FakeClient)
    settings = _settings()

    asyncio.run(cli._run_once(settings, tmp_path, "inspect the project", yes=True))
    out = capsys.readouterr().out
    assert "All good" in out
    assert "read_file" in out  # tool call surfaced by CliHooks
