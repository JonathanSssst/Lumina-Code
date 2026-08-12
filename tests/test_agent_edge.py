from __future__ import annotations

from lumina.agent.loop import (
    Agent,
    _render_compression_source,
    _sanitize_history,
)
from lumina.factory import build_registry
from lumina.types import LLMResponse, Message, ToolCall, Usage


class ScriptedClient:
    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = list(script)
        self.calls: list[list[Message]] = []
        self.closed = False

    async def chat(
        self, messages, tools=None, stream_callback=None, reasoning_callback=None,
        temperature=None, max_tokens=None, model=None,
    ):
        self.calls.append(list(messages))
        return self.script.pop(0)

    async def aclose(self) -> None:
        self.closed = True


class ApproveAll:
    async def approve(self, name, arguments, reason) -> bool:
        return True


class DenyAll:
    async def approve(self, name, arguments, reason) -> bool:
        return False


def _resp(tool_calls=None, content="", usage_tokens=10):
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=Usage(prompt_tokens=5, completion_tokens=usage_tokens, total_tokens=5 + usage_tokens),
    )


def _agent(workspace, settings, client, approver=None):
    registry = build_registry(workspace, settings)
    return Agent(
        settings=settings, client=client, registry=registry,
        workspace=workspace, approver=approver or ApproveAll(),
    )


async def test_unknown_tool_reports_error(workspace, settings):
    client = ScriptedClient(
        [
            _resp([ToolCall(id="1", name="no_such_tool", arguments={})]),
            _resp(content="ok"),
        ]
    )
    agent = _agent(workspace, settings, client)
    result = await agent.run("go")
    tool_result = next(t for t in result.transcript if t["type"] == "tool_result")
    assert tool_result["is_error"] is True
    assert "Unknown tool" in tool_result["content"]


async def test_invalid_arguments_reported(workspace, settings):
    client = ScriptedClient(
        [
            _resp([ToolCall(id="1", name="read_file", arguments={"path": 123})]),
            _resp(content="ok"),
        ]
    )
    agent = _agent(workspace, settings, client)
    result = await agent.run("go")
    tool_result = next(t for t in result.transcript if t["type"] == "tool_result")
    assert tool_result["is_error"] is True


async def test_denied_run_tests_does_not_trigger_autofix(workspace, settings):

    registry = build_registry(workspace, settings)
    registry.register_approval_checker("run_tests", lambda args: (True, "denied for test"))
    client = ScriptedClient(
        [
            _resp([ToolCall(id="1", name="run_tests", arguments={})]),
            _resp(content="user denied"),
        ]
    )
    agent = Agent(
        settings=settings, client=client, registry=registry,
        workspace=workspace, approver=DenyAll(),
    )
    result = await agent.run("run tests")
    assert result.stopped_reason == "completed"
    tool_result = next(t for t in result.transcript if t["type"] == "tool_result")
    assert tool_result["is_error"] is True
    assert "denied" in tool_result["content"].lower()
    # no autofix continuation was injected
    assert not any(
        m.role == "user" and "still failing" in (m.content or "").lower()
        for c in client.calls for m in c
    )


async def test_compression_disabled_skips(workspace, settings):
    settings.compression_enabled = False
    settings.token_budget = 200
    settings.compress_at_percent = 0.5
    client = ScriptedClient(
        [
            _resp([ToolCall(id="1", name="list_files", arguments={"path": "."})], usage_tokens=80),
            _resp(content="done"),
        ]
    )
    agent = _agent(workspace, settings, client)
    await agent.run("go")
    assert not agent._compressed
    assert not any("SUMMARY" in (m.content or "") for c in client.calls for m in c)


async def test_compression_empty_summary_aborts(workspace, settings):
    settings.token_budget = 300
    settings.compress_at_percent = 0.5
    settings.compress_keep_messages = 3
    settings.self_review = False
    client = ScriptedClient(
        [
            _resp([ToolCall(id="1", name="list_files", arguments={"path": "."})], usage_tokens=80),
            _resp([ToolCall(id="2", name="list_files", arguments={"path": "."})], usage_tokens=80),
            _resp(content="   ", usage_tokens=10),  # compressor returns blank
            _resp(content="done"),
        ]
    )
    agent = _agent(workspace, settings, client)
    result = await agent.run("go")
    assert result.stopped_reason == "completed"
    assert not agent._compressed


async def test_aclose_releases_client(workspace, settings):
    client = ScriptedClient([_resp(content="done")])
    agent = _agent(workspace, settings, client)
    await agent.run("hi")
    await agent.aclose()
    assert client.closed


def test_sanitize_history_keeps_complete_tool_round():
    msgs = [
        Message(role="assistant", tool_calls=[ToolCall(id="t1", name="x", arguments={})]),
        Message(role="tool", tool_call_id="t1", name="x", content="r"),
    ]
    _sanitize_history(msgs)
    assert [m.role for m in msgs] == ["assistant", "tool"]


def test_sanitize_history_drops_dangling_assistant_tool_call():
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", tool_calls=[ToolCall(id="t1", name="x", arguments={})]),
    ]
    _sanitize_history(msgs)
    assert [m.role for m in msgs] == ["user"]


def test_sanitize_history_drops_partial_tool_round():
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", tool_calls=[ToolCall(id="t1", name="x", arguments={})]),
        Message(role="tool", tool_call_id="t1", name="x", content="r1"),
        Message(role="assistant", tool_calls=[ToolCall(id="t2", name="y", arguments={})]),
    ]
    _sanitize_history(msgs)
    assert [m.role for m in msgs] == ["user", "assistant", "tool"]


def test_render_compression_source_covers_roles():
    msgs = [
        Message(role="user", content="hello"),
        Message(
            role="assistant", content="reading",
            tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "a.py"})],
        ),
        Message(role="tool", tool_call_id="t1", name="read_file", content="def foo():\n    pass"),
    ]
    text = _render_compression_source(msgs)
    assert "[user] hello" in text
    assert "read_file" in text
    assert "def foo():" in text


def test_sanitize_history_keeps_valid_pairs():
    msgs = [
        Message(role="user", content="hi"),
        Message(role="assistant", tool_calls=[ToolCall(id="t1", name="x", arguments={})]),
        Message(role="tool", tool_call_id="t1", name="x", content="r"),
    ]
    _sanitize_history(msgs)
    assert [m.role for m in msgs] == ["user", "assistant", "tool"]
