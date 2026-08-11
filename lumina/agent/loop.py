from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from lumina.agent.authorize import AgentResult, AsyncApprover, Hooks
from lumina.agent.budget import TokenBudget
from lumina.config import Settings
from lumina.context.project import ProjectScanner, summarize_tool_result
from lumina.llm.client import DeepSeekClient
from lumina.tools.registry import ToolRegistry, validate_arguments
from lumina.types import Message, ToolCall, ToolResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Lumina, an autonomous coding agent working inside a git repository.

Rules:
1. Explore before you act: use list_files, glob, grep and read_file to understand the project.
2. Read a file before editing it. Use edit_file with a unique old_string; fall back to write_file for full rewrites.
3. After making changes, run the tests (run_tests). If they fail, diagnose from the traceback, fix, and rerun until green.
4. Never claim an action was taken unless a tool result confirms it.
5. Keep prose concise. When done, summarize what changed, which files were touched, and the test outcome.
6. Respond in the same language the user wrote in (Chinese by default)."""

SUMMARY_SYSTEM_PROMPT = (
    "You are the context-compressor of a coding agent. Compress the following conversation "
    "transcript into a concise summary (under 400 words, in the user's language) that preserves: "
    "the user's goals, key decisions, files touched, tool results that still matter, and the "
    "current state of the work. Do not invent anything."
)

REVIEW_SYSTEM_PROMPT = (
    "You are a strict code-reviewer for a coding agent. Given the original task and the agent's "
    "final answer, verify the answer against the task: flag unverified claims, missing steps, "
    "ignored test failures, and contradictions with what tools actually reported. If everything "
    "checks out and nothing important is missing, reply with exactly 'APPROVED'. Otherwise reply "
    "with a concise bulleted list of concrete gaps and what to do next, in the user's language."
)


class Agent:
    """The core agent loop: think -> tool-call -> observe -> repeat until done."""

    def __init__(
        self,
        settings: Settings,
        client: DeepSeekClient,
        registry: ToolRegistry,
        workspace: Path,
        approver: AsyncApprover,
        hooks: Hooks | None = None,
        scanner: ProjectScanner | None = None,
        skills=None,
        mcp_bridge=None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.registry = registry
        self.workspace = Path(workspace).resolve()
        self.approver = approver
        self.hooks = hooks or Hooks()
        self.scanner = scanner or ProjectScanner(self.workspace)
        self.skills = skills
        self.mcp_bridge = mcp_bridge
        self.persist: Callable[[Message], None] | None = None
        self.budget = TokenBudget(
            max_tokens=settings.token_budget,
            max_iterations=settings.max_iterations,
        )
        self._compressed = False
        self._reviewed = False
        self.compress_threshold = int(settings.token_budget * settings.compress_at_percent)

    async def aclose(self) -> None:
        """Release all resources owned by this agent (LLM client, web tools)."""
        await self.client.aclose()
        web = getattr(self.registry, "web_tools", None)
        if web is not None:
            await web.aclose()

    def reset_budget(self) -> None:
        """Start a fresh token/iteration budget for a new conversation."""
        self.budget = TokenBudget(
            max_tokens=self.settings.token_budget,
            max_iterations=self.settings.max_iterations,
        )
        self._compressed = False
        self._reviewed = False

    def _project_instructions(self) -> str:
        """Load AGENTS.md from the workspace to seed project-specific rules."""
        for name in ("AGENTS.md", "agents.md"):
            path = self.workspace / name
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return ""
            if not text:
                return ""
            return (
                "===== PROJECT INSTRUCTIONS (AGENTS.md) =====\n"
                + text[:4000]
                + "\n===== END PROJECT INSTRUCTIONS ====="
            )
        return ""

    async def run(
        self,
        user_input: str,
        *,
        history: Sequence[Message] | None = None,
        persist: Callable[[Message], None] | None = None,
    ) -> AgentResult:
        """Run the agent loop.

        - `history`: prior conversation messages to continue from.
        - `persist`: called synchronously with every assistant/tool message appended.
        """
        self.persist = persist
        await self._warmup()
        messages: list[Message] = [
            Message(role="system", content=SYSTEM_PROMPT),
        ]
        project_instructions = self._project_instructions()
        if project_instructions:
            messages.append(Message(role="system", content=project_instructions))
        if self.settings.enable_planner:
            t_plan = time.monotonic()
            plan = await self._generate_plan(user_input)
            if plan:
                messages.append(
                    Message(
                        role="system",
                        content="===== EXECUTOR PLAN =====\n" + plan + "\n===== END PLAN =====",
                    )
                )
                if self.hooks.on_reasoning:
                    await self.hooks.on_reasoning(
                        "### Planning\n\n" + plan.strip() + "\n"
                    )
                if self.hooks.on_thinking_done:
                    await self.hooks.on_thinking_done(time.monotonic() - t_plan)
        messages.append(self._context_message(user_input))
        if history:
            sanitized = _sanitize_history(list(history))
            messages.extend(sanitized)
        messages.append(Message(role="user", content=user_input))
        transcript: list[dict] = []
        auto_fix_rounds = self.settings.max_auto_fix_rounds
        last_test_failure: str | None = None

        while not self.budget.exhausted:
            await self._maybe_compress(messages)
            content_hook, reasoning_hook = self._make_stream_hook()
            t_start = time.monotonic()
            response = await self.client.chat(
                messages,
                tools=self.registry.specs(),
                stream_callback=content_hook,
                reasoning_callback=reasoning_hook,
                max_tokens=self.settings.max_tokens,
            )
            if self.hooks.on_thinking_done:
                await self.hooks.on_thinking_done(time.monotonic() - t_start)
            self.budget.record(response.usage, tool_calls=len(response.tool_calls))

            assistant_msg = Message(
                role="assistant",
                content=response.content or None,
                tool_calls=response.tool_calls or None,
            )
            self._append(messages, assistant_msg)
            transcript.append(self._render_message(assistant_msg))

            if not response.tool_calls:
                if last_test_failure and auto_fix_rounds > 0:
                    auto_fix_rounds -= 1
                    fix_msg = (
                        "The tests are still failing. Do not stop — diagnose and fix, then rerun.\n"
                        f"Last failure:\n{last_test_failure[:2000]}"
                    )
                    last_test_failure = None
                    self._append(messages, Message(role="user", content=fix_msg))
                    logger.info("Auto-fix round %s remaining", auto_fix_rounds)
                    continue
                if last_test_failure:
                    return self._result(
                        response.content, messages, "auto_fix_exhausted", transcript
                    )
                if not self._reviewed and self.settings.self_review:
                    review = await self._self_review(user_input, response.content)
                    self._reviewed = True
                    if review and not review.startswith("APPROVED"):
                        self._append(
                            messages,
                            Message(role="user", content="Self-review found gaps:\n" + review),
                        )
                        logger.info("Self-review requested fixes; continuing one more round")
                        continue
                    if review and self.hooks.on_assistant_message:
                        await self.hooks.on_assistant_message("\n\n> 自我审查：\n" + review + "\n")
                    return self._result(
                        response.content + (f"\n\n--- 自我审查 ---\n{review}" if review else ""),
                        messages,
                        "completed",
                        transcript,
                    )
                return self._result(
                    response.content, messages, "completed", transcript
                )

            for call in response.tool_calls:
                result = await self._execute_tool_call(call)
                last_test_failure = self._test_failure_from(result)
                tool_message = Message(
                    role="tool",
                    tool_call_id=call.id,
                    name=call.name,
                    content=summarize_tool_result(result),
                )
                self._append(messages, tool_message)
                transcript.append(
                    {
                        "type": "tool_result",
                        "name": call.name,
                        "is_error": result.is_error,
                        "content": result.content,
                    }
                )
                if self.hooks.on_tool_result:
                    await self.hooks.on_tool_result(result)

        return self._result("", messages, "budget_exhausted", transcript)

    async def _execute_tool_call(self, call: ToolCall) -> ToolResult:
        if self.hooks.on_tool_call:
            await self.hooks.on_tool_call(call)

        spec = self.registry.get_spec(call.name)
        if spec is None:
            return ToolResult(
                tool_call_id=call.id, name=call.name, content=f"Unknown tool: {call.name}", is_error=True
            )

        needs, reason = self.registry.check_approval(call.name, call.arguments)
        if needs:
            approved = await self.approver.approve(call.name, call.arguments, reason)
            if not approved:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content="User denied this tool call. Explain what happened and adapt.",
                    is_error=True,
                    denied=True,
                )

        try:
            validated = validate_arguments(spec, call.arguments)
        except ValueError as exc:
            return ToolResult(
                tool_call_id=call.id, name=call.name, content=str(exc), is_error=True
            )

        handler = self.registry.handler(call.name)
        result = await handler(**validated)
        result.tool_call_id = call.id
        result.name = call.name
        return result

    async def _maybe_compress(self, messages: list[Message]) -> None:
        """Summarize early messages once token usage nears the budget.

        Tool call/result pairs are kept intact; recent messages stay verbatim.
        """
        if not self.settings.compression_enabled or self._compressed:
            return
        if self.budget.total_tokens < self.compress_threshold:
            return
        if len(messages) < 6:
            return
        end = _find_compress_boundary(messages, self.settings.compress_keep_messages)
        if end <= 1:
            return
        source = _render_compression_source(messages[1:end])
        try:
            resp = await self.client.chat(
                [
                    Message(role="system", content=SUMMARY_SYSTEM_PROMPT),
                    Message(role="user", content=source),
                ],
                max_tokens=1000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Context compression failed: %s", exc)
            return
        self.budget.record(resp.usage)
        summary = (resp.content or "").strip()
        if not summary:
            return
        del messages[1:end]
        messages.insert(
            1,
            Message(
                role="user",
                content="===== EARLIER CONVERSATION SUMMARY =====\n" + summary,
            ),
        )
        self._compressed = True
        logger.info(
            "Compressed %s early messages into a summary (cumulative tokens: %s)",
            end - 1,
            self.budget.total_tokens,
        )

    async def _self_review(self, user_input: str, final_content: str) -> str:
        """Ask the model to verify the final answer against the original task."""
        try:
            resp = await self.client.chat(
                [
                    Message(role="system", content=REVIEW_SYSTEM_PROMPT),
                    Message(
                        role="user",
                        content=(
                            "Original task:\n" + user_input + "\n\nAgent's final answer:\n" + final_content
                        ),
                    ),
                ],
                max_tokens=500,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Self-review failed: %s", exc)
            return ""
        self.budget.record(resp.usage)
        return (resp.content or "").strip()

    def _result(
        self, final_content: str, messages: list[Message], reason: str, transcript: list[dict]
    ) -> AgentResult:
        return AgentResult(
            final_content=final_content,
            iterations=self.budget.iterations,
            tool_calls_made=self.budget.tool_calls,
            total_tokens=self.budget.total_tokens,
            stopped_reason=reason,
            transcript=transcript,
        )

    def _render_message(self, msg: Message) -> dict:
        if msg.tool_calls:
            return {
                "type": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            }
        return {"type": "assistant", "content": msg.content or ""}

    def _test_failure_from(self, result: ToolResult) -> str | None:
        if result.denied:
            return None
        if result.name == "run_tests" and result.is_error:
            return result.content
        return None

    def _make_stream_hook(self):
        content_hook = None
        reasoning_hook = None

        if self.hooks.on_assistant_message:
            async def content_hook(chunk: str) -> None:
                await self.hooks.on_assistant_message(chunk)

        if self.hooks.on_reasoning:
            async def reasoning_hook(chunk: str) -> None:
                await self.hooks.on_reasoning(chunk)

        return content_hook, reasoning_hook

    async def _warmup(self) -> None:
        """One-time async setup: connect MCP servers if configured."""
        if self.mcp_bridge is not None and self.mcp_bridge.server_count > 0:
            errors = await self.mcp_bridge.connect_all()
            for err in errors:
                logger.warning("MCP server connect failed: %s", err)

    def _append(self, messages: list[Message], msg: Message) -> None:
        messages.append(msg)
        if self.persist is not None:
            try:
                self.persist(msg)
            except Exception:
                logger.exception("Persistence callback failed")

    async def _generate_plan(self, user_input: str) -> str:
        """Ask the reasoner model to draft a plan that the flash executor will follow."""
        try:
            context = self.scanner.scan()[:6000]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project scan failed for planner: %s", exc)
            context = ""
        system = (
            "You are the planning module of a coding agent. Given a task and project context, "
            "produce a concise numbered step-by-step plan the executor will follow. "
            "No code, no claims about running anything. Respond in the user's language."
        )
        user = (
            "Task:\n"
            + user_input
            + "\n\n===== PROJECT CONTEXT =====\n"
            + context
            + "\n===== END CONTEXT ====="
        )
        resp = await self.client.chat(
            [Message(role="system", content=system), Message(role="user", content=user)],
            model=self.settings.deepseek_planner_model,
            max_tokens=self.settings.planner_max_tokens,
        )
        self.budget.record(resp.usage)
        return resp.content

    def _context_message(self, user_input: str = "") -> Message:
        try:
            context = self.scanner.scan()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Project scan failed: %s", exc)
            context = ""
        lines = [f"Working directory: {self.workspace}"]
        if context:
            lines.append("===== PROJECT CONTEXT =====\n" + context + "\n===== END CONTEXT =====")
        if self.skills is not None:
            matched = self.skills.match(user_input)
            if matched:
                blocks = []
                for skill in matched:
                    blocks.append(f"### Skill: {skill.name}\n{skill.instructions}")
                lines.append("===== RELEVANT SKILLS =====\n" + "\n\n".join(blocks) + "\n===== END SKILLS =====")
        return Message(role="user", content="\n".join(lines))


def _sanitize_history(messages: list[Message]) -> list[Message]:
    """Drop trailing tool messages so a resumed history is API-compliant.

    Tool results must immediately follow the assistant message that requested them.
    """
    while messages and messages[-1].role == "tool":
        messages.pop()
    return messages


def _find_compress_boundary(messages: list[Message], keep: int) -> int:
    """Return an index `end` such that messages[1:end] can be removed safely.

    The boundary never splits a tool call/result pair: `messages[end]` must not
    be an orphan tool result, and the last kept message must not be an assistant
    tool call whose result would be left behind.
    """
    end = max(len(messages) - keep, 2)
    while end > 1:
        if end < len(messages) and messages[end].role == "tool":
            end -= 1
            continue
        prev = messages[end - 1]
        if prev.tool_calls and end < len(messages) and messages[end].role == "tool":
            end -= 1
            continue
        return end
    return 1


def _render_compression_source(msgs: Sequence[Message]) -> str:
    lines: list[str] = []
    for m in msgs:
        if m.role == "user":
            lines.append(f"[user] {m.content}")
        elif m.role == "assistant":
            if m.content:
                lines.append(f"[assistant] {m.content}")
            if m.tool_calls:
                for tc in m.tool_calls:
                    args = json.dumps(tc.arguments, ensure_ascii=False)[:300]
                    lines.append(f"[called tool] {tc.name}({args})")
        elif m.role == "tool":
            content = (m.content or "")[:400].replace("\n", " ")
            lines.append(f"[tool result {m.name}] {content}")
    return "\n".join(lines)
