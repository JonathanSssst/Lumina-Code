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


def content_text(content: str | list[Any] | None) -> str:
    """Extract the plain-text portion of a message content.

    Accepts a plain string or OpenAI-style content parts (``text`` /
    ``image_url``). Used for titles, search, export and the resume flow where
    a string is required.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                chunks.append(str(part.get("text", "")))
        return "".join(chunks)
    return ""


def content_images(content: str | list[Any] | None) -> list[str]:
    """Return the image data URLs embedded in OpenAI-style content parts."""
    if not isinstance(content, list):
        return []
    urls: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if isinstance(url, str) and url:
                urls.append(url)
    return urls


def build_user_content(text: str, images: list[str]) -> str | list[Any]:
    """Build user-message content for the LLM: plain text, or text + images.

    Images are embedded as data URLs in the OpenAI vision ``image_url`` part
    format so any vision-capable OpenAI-compatible provider can read them.
    At most 4 images are kept.
    """
    if not images:
        return text
    parts: list[Any] = [{"type": "text", "text": text}]
    added = 0
    for url in images[:4]:
        if isinstance(url, str) and url.startswith("data:image/"):
            parts.append({"type": "image_url", "image_url": {"url": url}})
            added += 1
    return parts if added else text


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
