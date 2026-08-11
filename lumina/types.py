from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A function-call request produced by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The outcome of executing a tool call."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    requires_approval: bool = False
    denied: bool = False
    stats: dict[str, Any] | None = None


class Message(BaseModel):
    """A single chat message in OpenAI-compatible format."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[Any] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls is not None:
            payload["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": _json_dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            payload["name"] = self.name
        return payload


class ToolSpec(BaseModel):
    """JSON-Schema description of a tool exposed to the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]
    requires_approval: bool = False


class Usage(BaseModel):
    """Token accounting for a single LLM round-trip.

    ``reasoning_tokens`` / ``cached_tokens`` are optional; providers expose
    them under different keys (or not at all), so they default to 0 and the
    client normalizes them before constructing this object.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
        )


class LLMResponse(BaseModel):
    """Parsed result of an LLM invocation."""

    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str = "stop"


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
