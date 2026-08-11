from __future__ import annotations

from lumina.agent.authorize import AsyncApprover
from lumina.agent.loop import Agent
from lumina.factory import build_registry
from lumina.tools.registry import ToolRegistry, validate_arguments
from lumina.tools.todo import TodoTools
from lumina.types import LLMResponse, ToolCall, Usage


async def _update(registry, todos):
    return await registry.handler("update_todo")(todos=todos)


def test_update_todo_creates_list():
    registry = ToolRegistry()
    TodoTools(registry)
    result = asyncio_run(_update(registry, [{"content": "探索代码"}]))
    assert not result.is_error
    assert "待办列表" in result.content
    assert "1. 探索代码" in result.content
    assert "[ ]" in result.content


def test_update_todo_counts_completed():
    registry = ToolRegistry()
    TodoTools(registry)
    result = asyncio_run(
        _update(
            registry,
            [
                {"content": "a", "status": "completed"},
                {"content": "b", "status": "in_progress"},
                {"content": "c", "status": "cancelled"},
                {"content": "d"},
            ],
        )
    )
    assert "已完成 1" in result.content
    assert "[x] 1. a" in result.content
    assert "[>] 2. b" in result.content
    assert "[~] 3. c" in result.content
    assert "[ ] 4. d" in result.content


def test_update_todo_replaces_whole_list():
    registry = ToolRegistry()
    TodoTools(registry)
    asyncio_run(_update(registry, [{"content": "a"}, {"content": "b"}, {"content": "c"}]))
    result = asyncio_run(_update(registry, [{"content": "z", "status": "completed"}]))
    assert "1. z" in result.content
    assert "a" not in result.content
    assert "3 项" not in result.content


def test_update_todo_rejects_invalid_status():
    registry = ToolRegistry()
    TodoTools(registry)
    result = asyncio_run(_update(registry, [{"content": "a", "status": "banana"}]))
    assert result.is_error
    assert "invalid todo status" in result.content


def test_update_todo_rejects_missing_content():
    registry = ToolRegistry()
    TodoTools(registry)
    result = asyncio_run(_update(registry, [{"content": "  "}]))
    assert result.is_error
    assert "non-empty" in result.content


def test_update_todo_accepts_empty_list():
    registry = ToolRegistry()
    TodoTools(registry)
    result = asyncio_run(_update(registry, []))
    assert not result.is_error
    assert "（空）" in result.content


def test_todo_list_reflects_updates():
    registry = ToolRegistry()
    TodoTools(registry)
    asyncio_run(_update(registry, [{"content": "x", "status": "completed"}]))
    result = asyncio_run(registry.handler("todo_list")())
    assert "1. x" in result.content
    assert "[x]" in result.content


def test_registry_integration(workspace, settings):
    registry = build_registry(workspace, settings)
    spec = registry.get_spec("update_todo")
    assert spec is not None
    assert "todos" in spec.parameters["required"]
    assert registry.get_spec("todo_list") is not None
    assert registry.todo_tools is not None
    args = validate_arguments(spec, {"todos": [{"content": "step", "status": "pending"}]})
    assert args["todos"][0]["content"] == "step"


async def _collector(collected):
    async def cb(todos):
        collected.append(todos)

    return cb


def test_update_todo_emits_on_change():
    registry = ToolRegistry()
    TodoTools(registry)
    collected = []
    registry.todo_tools.on_change = asyncio_run(_collector(collected))
    asyncio_run(_update(registry, [{"content": "a", "status": "in_progress"}, {"content": "b"}]))
    assert collected == [
        [
            {"content": "a", "status": "in_progress"},
            {"content": "b", "status": "pending"},
        ]
    ]
    asyncio_run(_update(registry, [{"content": "c"}]))
    assert collected[-1] == [{"content": "c", "status": "pending"}]


def test_update_todo_does_not_emit_on_error():
    registry = ToolRegistry()
    TodoTools(registry)
    collected = []
    registry.todo_tools.on_change = asyncio_run(_collector(collected))
    asyncio_run(_update(registry, [{"content": "bad", "status": "nope"}]))
    assert collected == []


def test_set_status_toggles_and_emits():
    registry = ToolRegistry()
    TodoTools(registry)
    asyncio_run(_update(registry, [{"content": "a"}, {"content": "b"}]))
    collected = []
    registry.todo_tools.on_change = asyncio_run(_collector(collected))
    result = asyncio_run(registry.todo_tools.set_status(0, "completed"))
    assert not result.is_error
    assert "[x] 1. a" in result.content
    assert collected == [[{"content": "a", "status": "completed"}, {"content": "b", "status": "pending"}]]
    render = asyncio_run(registry.handler("todo_list")())
    assert "[x] 1. a" in render.content


def test_set_status_rejects_bad_index_or_status():
    registry = ToolRegistry()
    TodoTools(registry)
    asyncio_run(_update(registry, [{"content": "a"}]))
    result = asyncio_run(registry.todo_tools.set_status(5, "completed"))
    assert result.is_error
    assert "index out of range" in result.content
    result = asyncio_run(registry.todo_tools.set_status(0, "banana"))
    assert result.is_error
    assert "invalid status" in result.content


class _Deny(AsyncApprover):
    async def approve(self, name, arguments, reason) -> bool:
        return False


def _resp(tool_calls=None, content="", usage_tokens=10):
    return LLMResponse(
        content=content,
        tool_calls=tool_calls or [],
        usage=Usage(prompt_tokens=5, completion_tokens=usage_tokens, total_tokens=5 + usage_tokens),
    )


async def test_agent_uses_todo_tools_end_to_end(workspace, settings):
    class FakeClient:
        def __init__(self, script):
            self.script = list(script)

        async def chat(self, messages, tools=None, stream_callback=None, reasoning_callback=None, temperature=None, max_tokens=None, model=None):
            return self.script.pop(0)

        async def aclose(self):
            pass

    client = FakeClient(
        [
            _resp(
                [ToolCall(id="1", name="update_todo", arguments={"todos": [{"content": "调研"}, {"content": "实现", "status": "in_progress"}]})],
                content="Planning...",
            ),
            _resp([ToolCall(id="2", name="todo_list", arguments={})], content="Checking progress..."),
            _resp(content="APPROVED: task complete."),
        ]
    )
    registry = build_registry(workspace, settings)
    agent = Agent(settings=settings, client=client, registry=registry, workspace=workspace, approver=_Deny())
    result = await agent.run("build a feature")
    assert result.tool_calls_made == 2
    tool_names = [
        tc["name"]
        for t in result.transcript
        if "tool_calls" in t
        for tc in t["tool_calls"]
    ]
    assert "update_todo" in tool_names
    assert "todo_list" in tool_names


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
