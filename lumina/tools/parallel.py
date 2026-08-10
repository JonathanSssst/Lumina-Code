from __future__ import annotations

import asyncio

from lumina.tools.registry import ToolRegistry, validate_arguments
from lumina.types import Message, ToolResult

_READ_ONLY_TOOLS = frozenset(
    {
        "read_file",
        "glob",
        "grep",
        "list_files",
        "list_tree",
        "web_search",
        "web_fetch",
        "git_status",
        "git_diff",
        "git_log",
    }
)

_SUB_AGENT_PROMPT = (
    "You are a research subagent of a coding agent. Use the available read-only tools to investigate "
    "your assignment. Call tools as needed, then reply with a concise factual report of your findings. "
    "Never modify files. Answer in the user's language."
)

_MAX_SUBAGENT_ITERATIONS = 8
_MAX_CONCURRENCY = 3


class ParallelRunner:
    """Registers a run_parallel tool that fans out read-only research subagents."""

    def __init__(self, registry: ToolRegistry, client, settings) -> None:
        self.registry = registry
        self.client = client
        self.settings = settings

    def install(self) -> None:
        @self.registry.register(
            description=(
                "Run several independent research sub-tasks in parallel and return each report. "
                "Use when the task splits into independent investigations (e.g. explore different "
                "modules, compare options). Sub-tasks are limited to read-only tools and do not "
                "modify the workspace."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "Independent research goals",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Short label"},
                                "goal": {"type": "string", "description": "What to investigate"},
                            },
                            "required": ["id", "goal"],
                        },
                    }
                },
                "required": ["tasks"],
            },
        )
        async def run_parallel(tasks: list[dict]) -> ToolResult:
            content = await self._run(tasks or [])
            return ToolResult(tool_call_id="", name="run_parallel", content=content)

    async def _run(self, tasks: list[dict]) -> str:
        semaphore = asyncio.Semaphore(min(_MAX_CONCURRENCY, max(1, len(tasks))))

        async def one(task: dict) -> str:
            async with semaphore:
                return await self._sub_agent(task)

        outputs = await asyncio.gather(*(one(t) for t in tasks), return_exceptions=True)
        blocks: list[str] = []
        for index, (task, output) in enumerate(zip(tasks, outputs)):
            label = str(task.get("id") or f"task-{index + 1}")
            if isinstance(output, BaseException):
                blocks.append(f"[{label}]\nERROR: {output}")
            else:
                blocks.append(f"[{label}]\n{output.strip()}")
        return "\n\n".join(blocks)

    async def _sub_agent(self, task: dict) -> str:
        goal = str(task.get("goal", "")).strip()
        if not goal:
            return "(empty goal)"
        tools = [s for n in _READ_ONLY_TOOLS if (s := self.registry.get_spec(n))]
        messages = [
            Message(role="system", content=_SUB_AGENT_PROMPT),
            Message(role="user", content=goal),
        ]
        for _ in range(_MAX_SUBAGENT_ITERATIONS):
            response = await self.client.chat(
                messages,
                tools=tools,
                max_tokens=self.settings.max_tokens,
            )
            if not response.tool_calls:
                return response.content or "(no output)"
            messages.append(
                Message(role="assistant", content=response.content or None, tool_calls=response.tool_calls)
            )
            for call in response.tool_calls:
                messages.append(await self._exec_tool(call, tools))
        last = messages[-1]
        return str(last.content or "(subtask did not finish)")

    async def _exec_tool(self, call, tools: list) -> Message:
        spec = next((s for s in tools if s.name == call.name), None)
        if spec is None:
            return Message(
                role="tool",
                tool_call_id=call.id,
                name=call.name,
                content=f"[error] tool '{call.name}' is not allowed in sub-tasks",
            )
        try:
            args = validate_arguments(spec, call.arguments)
            result = await self.registry.handler(call.name)(**args)
            content, status = result.content, "ok" if not result.is_error else "error"
        except Exception as exc:  # noqa: BLE001
            content, status = str(exc), "error"
        return Message(
            role="tool",
            tool_call_id=call.id,
            name=call.name,
            content=f"[{status}] {content[:3000]}",
        )
