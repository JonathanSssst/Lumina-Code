from __future__ import annotations

from lumina.agent.authorize import AsyncApprover, Hooks
from lumina.agent.loop import (
    Agent,
    _find_compress_boundary,
    _render_compression_source,
    _sanitize_history,
)
from lumina.config import Settings
from lumina.factory import build_registry
from lumina.types import LLMResponse, Message, ToolCall, ToolResult, Usage


class ScriptedLLM:
    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = list(script)
        self.calls = 0

    async def chat(self, messages, **kwargs):
        assert self.calls < len(self.script), f"unexpected call {self.calls}"
        resp = self.script[self.calls]
        self.calls += 1
        return resp

    async def aclose(self) -> None:
        pass


class AlwaysApprover(AsyncApprover):
    async def approve(self, name, arguments, reason) -> bool:
        return True


class DenyApprover(AsyncApprover):
    async def approve(self, name, arguments, reason) -> bool:
        return False


def _agent(workspace, settings, client, approver=None) -> Agent:
    registry = build_registry(workspace, settings)
    return Agent(
        settings=settings,
        client=client,
        registry=registry,
        workspace=workspace,
        approver=approver or AlwaysApprover(),
        hooks=Hooks(),
    )


def _settings(**kw) -> Settings:
    base = {"DEEPSEEK_API_KEY": "k", "LUMINA_MAX_ITERATIONS": 10, "LUMINA_TOKEN_BUDGET": 30000}
    base.update(kw)
    return Settings(**base)


# ---------- helpers ----------

def test_sanitize_history_drops_trailing_tool_messages():
    msgs = [
        Message(role="user", content="q"),
        Message(role="assistant", content=None, tool_calls=[ToolCall(id="t", name="x", arguments={})]),
        Message(role="tool", tool_call_id="t", name="x", content="r"),
    ]
    cleaned = _sanitize_history(msgs)
    assert cleaned[-1].role == "assistant"
    assert cleaned[-1].tool_calls is not None


def test_compress_boundary_never_splits_tool_pairs():
    msgs = [
        Message(role="system", content="s"),
        Message(role="user", content="a"),
        Message(role="assistant", content=None, tool_calls=[ToolCall(id="t", name="x", arguments={})]),
        Message(role="tool", tool_call_id="t", name="x", content="r"),
        Message(role="user", content="b"),
    ]
    end = _find_compress_boundary(msgs, keep=2)
    assert end <= len(msgs) - 2
    assert not (end < len(msgs) and msgs[end].role == "tool")


def test_render_compression_source_covers_roles():
    msgs = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="let me check", tool_calls=[ToolCall(id="t", name="grep", arguments={"p": "x"})]),
        Message(role="tool", tool_call_id="t", name="grep", content="hit line"),
    ]
    src = _render_compression_source(msgs)
    assert "[user] hello" in src
    assert "[assistant] let me check" in src
    assert "[called tool] grep" in src
    assert "[tool result grep] hit line" in src


# ---------- _execute_tool_call paths ----------

async def test_execute_unknown_tool(workspace):
    agent = _agent(workspace, _settings(), ScriptedLLM([]))
    result = await agent._execute_tool_call(ToolCall(id="x", name="nope", arguments={}))
    assert result.is_error
    assert "Unknown tool" in result.content


async def test_execute_denied_tool(workspace):
    agent = _agent(workspace, _settings(), ScriptedLLM([]), approver=DenyApprover())
    result = await agent._execute_tool_call(
        ToolCall(id="x", name="run_command", arguments={"command": "rm -rf /tmp/x"})
    )
    assert result.is_error
    assert result.denied


async def test_execute_bad_arguments(workspace):
    agent = _agent(workspace, _settings(), ScriptedLLM([]))
    result = await agent._execute_tool_call(ToolCall(id="x", name="read_file", arguments={}))
    assert result.is_error
    assert result.tool_call_id == "x"
    assert result.name == "read_file"


# ---------- auto-fix loop ----------

async def test_auto_fix_round_then_completes(workspace):
    async def failing_run_tests(**args):
        return ToolResult(tool_call_id="", name="run_tests", content="FAILED test_x", is_error=True)

    agent = _agent(workspace, _settings(LUMINA_SELF_REVIEW=False), ScriptedLLM([]))
    agent.registry.set_handler("run_tests", failing_run_tests)
    client = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="t1", name="run_tests", arguments={})]),
            LLMResponse(content="checking the failure"),
            LLMResponse(content="fixed the bug"),
        ]
    )
    agent.client = client
    result = await agent.run("fix the bug")
    assert result.stopped_reason == "completed"
    assert result.final_content == "fixed the bug"
    assert client.calls == 3


async def test_auto_fix_exhausted(workspace):
    async def failing_run_tests(**args):
        return ToolResult(tool_call_id="", name="run_tests", content="FAILED still", is_error=True)

    agent = _agent(workspace, _settings(LUMINA_SELF_REVIEW=False, LUMINA_MAX_AUTO_FIX_ROUNDS=0), ScriptedLLM([]))
    agent.registry.set_handler("run_tests", failing_run_tests)
    agent.client = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="t1", name="run_tests", arguments={})]),
            LLMResponse(content="i give up"),
        ]
    )
    result = await agent.run("fix it")
    assert result.stopped_reason == "auto_fix_exhausted"
    assert agent.client.calls == 2


# ---------- self-review ----------

async def test_self_review_approved(workspace):
    agent = _agent(workspace, _settings(), ScriptedLLM([]))
    agent.client = ScriptedLLM(
        [
            LLMResponse(content="the final answer"),
            LLMResponse(content="APPROVED"),
        ]
    )
    result = await agent.run("do the thing")
    assert result.stopped_reason == "completed"
    assert "the final answer" in result.final_content
    assert "APPROVED" in result.final_content
    assert agent.client.calls == 2


async def test_self_review_requests_fixes_then_completes(workspace):
    agent = _agent(workspace, _settings(), ScriptedLLM([]))
    agent.client = ScriptedLLM(
        [
            LLMResponse(content="answer v1"),
            LLMResponse(content="- missing test coverage"),
            LLMResponse(content="answer v2"),
        ]
    )
    result = await agent.run("do the thing")
    assert result.stopped_reason == "completed"
    assert "answer v2" in result.final_content
    assert agent.client.calls == 3


# ---------- context compression ----------

async def test_maybe_compress(workspace):
    agent = _agent(workspace, _settings(), ScriptedLLM([]))
    agent.budget.record(Usage(prompt_tokens=50000, completion_tokens=0, total_tokens=50000))
    messages = [
        Message(role="system", content="s"),
        Message(role="user", content="m1"),
        Message(role="assistant", content="a1"),
        Message(role="user", content="m2"),
        Message(role="assistant", content="a2"),
        Message(role="user", content="m3"),
        Message(role="assistant", content="a3"),
    ]
    agent.client = ScriptedLLM([LLMResponse(content="SUMMARY TEXT")])
    await agent._maybe_compress(messages)
    assert agent._compressed
    assert messages[1].content == "===== EARLIER CONVERSATION SUMMARY =====\nSUMMARY TEXT"
    assert messages[1].content != "m1"


async def test_maybe_compress_skips_when_budget_low(workspace):
    agent = _agent(workspace, _settings(), ScriptedLLM([]))
    messages = [Message(role="system", content="s"), Message(role="user", content="m1")]
    await agent._maybe_compress(messages)
    assert not agent._compressed


async def test_maybe_compress_noop_when_disabled(workspace):
    agent = _agent(workspace, _settings(LUMINA_COMPRESSION=False), ScriptedLLM([]))
    agent.budget.record(Usage(prompt_tokens=50000, completion_tokens=0, total_tokens=50000))
    messages = [Message(role="system", content="s") for _ in range(10)]
    await agent._maybe_compress(messages)
    assert not agent._compressed
