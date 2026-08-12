from __future__ import annotations

from lumina.agent.authorize import AsyncApprover, Hooks
from lumina.agent.loop import Agent, _find_compress_boundary
from lumina.factory import build_registry
from lumina.types import LLMResponse, Message, ToolCall, ToolResult, Usage


class FakeClient:
    """Scripted LLM client: returns responses in order from a queue."""

    def __init__(self, script: list[LLMResponse]) -> None:
        self.script = list(script)
        self.calls: list[list[Message]] = []
        self.models: list[str | None] = []

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
        self.calls.append(list(messages))
        self.models.append(model)
        return self.script.pop(0)

    async def aclose(self) -> None:
        pass


class DenyApprover(AsyncApprover):
    async def approve(self, name, arguments, reason) -> bool:
        return False


def _resp(tool_calls=None, content="", usage_tokens=10):
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=Usage(prompt_tokens=5, completion_tokens=usage_tokens, total_tokens=5 + usage_tokens),
    )


def _build_agent(workspace, settings, client, approver):
    registry = build_registry(workspace, settings)
    return Agent(settings=settings, client=client, registry=registry, workspace=workspace, approver=approver)


async def test_agent_executes_tool_and_finishes(workspace, settings):
    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="read_file", arguments={"path": "src/calc.py"})], content="Reading..."),
            _resp(content="The file defines add and buggy."),
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("what's in calc.py?")

    assert result.tool_calls_made == 1
    assert result.iterations == 2
    assert result.stopped_reason == "completed"
    assert "buggy" in result.final_content
    assert any(m.role == "tool" for m in client.calls[1])


async def test_agent_denied_tool_feeds_back(workspace, settings):
    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="run_command", arguments={"command": "rm -rf /tmp"})], content=""),
            _resp(content="The user denied the command."),
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("run rm -rf")
    tool_result = next(t for t in result.transcript if t["type"] == "tool_result")
    assert tool_result["is_error"] is True
    assert "denied" in tool_result["content"].lower()


async def test_agent_auto_fix_loop(workspace, settings):
    async def failing_run_tests(*args, **kwargs) -> ToolResult:
        return ToolResult(
            tool_call_id="", name="run_tests",
            content="FAILED tests/test_calc.py::test_add - AssertionError: 3 != 4",
            is_error=True,
        )

    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="run_tests", arguments={})]),
            _resp(content="Looks fine."),  # final, but last_test_failure set -> autofix triggers
            _resp(content="Fixed and verified."),  # final, no failure -> done
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    agent.registry.set_handler("run_tests", failing_run_tests)
    result = await agent.run("make sure tests pass")
    assert result.stopped_reason == "completed"
    # an extra autofix user message was appended between call 2 and call 3
    assert any(
        m.role == "user" and "still failing" in (m.content or "").lower() for m in client.calls[2]
    )


async def test_agent_exhausts_budget(workspace, settings):
    settings.max_iterations = 2
    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="read_file", arguments={"path": "src/calc.py"})]),
            _resp([ToolCall(id="2", name="read_file", arguments={"path": "src/calc.py"})]),
            _resp([ToolCall(id="3", name="read_file", arguments={"path": "src/calc.py"})]),
            _resp(content="never reached"),
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("loop forever")
    assert result.stopped_reason == "iterations_exhausted"


async def test_max_iterations_zero_is_unlimited(workspace, settings):
    settings.max_iterations = 0
    settings.self_review = False
    client = FakeClient([_resp(content="done in one step")])
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("simple task")
    assert result.stopped_reason == "completed"
    assert not agent.budget.exhausted


async def test_reset_budget_starts_fresh_conversation(workspace, settings):
    settings.token_budget = 1000
    settings.self_review = False
    client = FakeClient([_resp(content="ok")])
    agent = _build_agent(workspace, settings, client, DenyApprover())
    agent.budget.record(Usage(prompt_tokens=700, completion_tokens=700, total_tokens=1400))
    assert agent.budget.exhausted

    agent.reset_budget()
    assert not agent.budget.exhausted
    assert agent.budget.total_tokens == 0
    assert agent.budget.iterations == 0
    result = await agent.run("task")
    assert result.stopped_reason == "completed"


async def test_hooks_fire(workspace, settings):
    seen: list[str] = []

    async def on_tool_call(call):
        seen.append("call:" + call.name)

    async def on_tool_result(res):
        seen.append("result")

    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="list_files", arguments={"path": "."})]),
            _resp(content="done"),
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    agent.hooks = Hooks(on_tool_call=on_tool_call, on_tool_result=on_tool_result)
    await agent.run("list files")
    assert seen == ["call:list_files", "result"]


async def test_agent_continues_from_history(workspace, settings):
    history = [
        Message(role="user", content="之前的对话"),
        Message(role="assistant", content="之前的回答"),
    ]
    client = FakeClient([_resp(content="续谈回答")])
    agent = _build_agent(workspace, settings, client, DenyApprover())
    await agent.run("继续", history=history)
    executor_call = client.calls[0]
    roles = [m.role for m in executor_call]
    assert roles[:2] == ["system", "user"]  # system + fresh context
    assert roles[-3:] == ["user", "assistant", "user"]  # history + new input
    assert executor_call[-1].content == "继续"
    assert any(m.content == "之前的对话" for m in executor_call)


async def test_agent_sanitizes_trailing_tool_in_history(workspace, settings):
    history = [
        Message(role="assistant", tool_calls=[ToolCall(id="t1", name="read_file", arguments={"path": "x"})]),
        Message(role="tool", tool_call_id="t1", name="read_file", content="result"),
    ]
    client = FakeClient([_resp(content="ok")])
    agent = _build_agent(workspace, settings, client, DenyApprover())
    await agent.run("继续", history=history)
    roles = [m.role for m in client.calls[0]]
    assert roles[-1] == "user"
    assert "tool" not in roles


async def test_agent_planner_injects_plan(workspace, settings):
    settings.enable_planner = True
    client = FakeClient(
        [
            _resp(content="1. 阅读代码 2. 修复"),  # planner call
            _resp(content="已完成修复"),  # executor call
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("修复 bug")
    assert client.models[0] == settings.planner_model
    executor_call = client.calls[1]
    assert any(
        m.role == "system" and "EXECUTOR PLAN" in (m.content or "") for m in executor_call
    )
    assert result.stopped_reason == "completed"


async def test_agent_persist_callback(workspace, settings):
    persisted: list[Message] = []
    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="list_files", arguments={"path": "."})]),
            _resp(content="done"),
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    await agent.run("list files", persist=persisted.append)
    roles = [m.role for m in persisted]
    assert "assistant" in roles and "tool" in roles


async def test_agent_compresses_early_history(workspace, settings):
    settings.token_budget = 200
    settings.compress_at_percent = 0.5  # threshold = 100 cumulative tokens
    settings.compress_keep_messages = 3
    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="list_files", arguments={"path": "."})], usage_tokens=80),
            _resp([ToolCall(id="2", name="list_files", arguments={"path": "."})], usage_tokens=80),
            _resp(content="EARLIER WORK SUMMARIZED", usage_tokens=10),  # compressor call
            _resp(content="done"),
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("do the work")
    assert result.stopped_reason == "completed"
    assert agent._compressed
    # the summary replaced the early context in the final request
    assert any(
        "EARLIER CONVERSATION SUMMARY" in (m.content or "") for m in client.calls[3]
    )
    # system prompt stays first; summary sits right after it
    final = client.calls[3]
    assert final[0].role == "system"
    assert final[1].role == "user"
    assert final[1].content.startswith("===== EARLIER CONVERSATION SUMMARY =====")


def test_compress_boundary_keeps_tool_pairs():
    msgs = [
        Message(role="system", content="s"),
        Message(role="user", content="u1"),
        Message(
            role="assistant", content="a",
            tool_calls=[ToolCall(id="1", name="x", arguments={})],
        ),
        Message(role="tool", tool_call_id="1", name="x", content="r"),
        Message(role="user", content="u2"),
        Message(role="assistant", content="final"),
    ]
    # keep=2: boundary lands at 4 so the tool call/result pair is removed together
    assert _find_compress_boundary(msgs, 2) == 4
    # keep=1: the tool call/result pair is still removed as a unit (never split)
    assert _find_compress_boundary(msgs, 1) == 5


async def test_self_review_approves_and_passes_through(workspace, settings):
    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="read_file", arguments={"path": "src/calc.py"})], content="Reading..."),
            _resp(content="Initial answer."),
            _resp(content="APPROVED", usage_tokens=3),  # self-review says all good
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("do the task")
    assert result.stopped_reason == "completed"
    assert agent._reviewed
    assert "自我审查" in result.final_content


async def test_self_review_finds_gaps_and_continues(workspace, settings):
    client = FakeClient(
        [
            _resp([ToolCall(id="1", name="read_file", arguments={"path": "src/calc.py"})], content="Reading..."),
            _resp(content="Initial answer."),
            _resp(content="- Tests were not run\n- Verify the fix", usage_tokens=3),  # review finds gaps
            _resp(content="Now tests are run and pass."),
        ]
    )
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("do the task")
    assert result.stopped_reason == "completed"
    # the synthetic review user message is in-memory only (not persisted to history)
    assert any(
        m.role == "tool" for m in client.calls[3]
    )
    assert any(
        m.role == "user" and "Self-review found gaps" in (m.content or "") for m in client.calls[3]
    )


async def test_no_tools_skips_self_review(workspace, settings):
    client = FakeClient([_resp(content="这是模拟代码，不涉及真实改动。")])
    agent = _build_agent(workspace, settings, client, DenyApprover())
    result = await agent.run("帮我模拟一个函数实现的思路")
    assert result.stopped_reason == "completed"
    assert not agent._reviewed
    assert "自我审查" not in result.final_content
    assert len(client.calls) == 1  # no extra reviewer round-trip


async def test_agent_seeds_agents_md(workspace, settings):
    (workspace / "AGENTS.md").write_text("Never use tabs. Keep files ASCII-only.\n", encoding="utf-8")
    client = FakeClient([_resp(content="done")])
    agent = _build_agent(workspace, settings, client, DenyApprover())
    await agent.run("hello")
    first_call = client.calls[0]
    assert any(
        m.role == "system" and "Never use tabs" in (m.content or "") for m in first_call
    )


async def test_run_parallel_subagents(workspace, settings):
    from lumina.tools.parallel import ParallelRunner
    from lumina.tools.registry import validate_arguments

    registry = build_registry(workspace, settings)
    client = FakeClient([_resp(content="Report A"), _resp(content="Report B")])
    ParallelRunner(registry, client, settings).install()
    spec = registry.get_spec("run_parallel")
    assert spec is not None
    args = validate_arguments(
        spec,
        {"tasks": [{"id": "a", "goal": "explore x"}, {"id": "b", "goal": "explore y"}]},
    )
    result = await registry.handler("run_parallel")(**args)
    assert not result.is_error
    assert "Report A" in result.content
    assert "Report B" in result.content
    assert len(client.calls) == 2
