"""LLM client (OpenAI-compatible chat/completions protocol, streaming).

LuminaCode talks to any OpenAI-compatible vendor (DeepSeek, OpenAI, Ollama,
vLLM, ...); the active provider is selected by `Settings.provider`.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable, Sequence

import httpx

from lumina.config import Settings
from lumina.types import LLMResponse, Message, ToolCall, ToolSpec, Usage

logger = logging.getLogger(__name__)

StreamCallback = Callable[[str], object]


def _parse_usage(data: dict) -> Usage:
    """Build a Usage from a provider `usage` payload, tolerating vendor quirks.

    Providers report reasoning/cache tokens under different keys (e.g. DeepSeek
    ``prompt_cache_hit_tokens``, OpenAI ``completion_tokens_details``), so they
    are normalized defensively; unknown keys are simply ignored.
    """
    details = data.get("completion_tokens_details") or {}
    return Usage(
        prompt_tokens=int(data.get("prompt_tokens") or 0),
        completion_tokens=int(data.get("completion_tokens") or 0),
        total_tokens=int(data.get("total_tokens") or 0),
        reasoning_tokens=int(details.get("reasoning_tokens") or data.get("reasoning_tokens") or 0),
        cached_tokens=int(
            data.get("prompt_cache_hit_tokens")
            or data.get("cached_tokens")
            or details.get("cached_tokens")
            or 0
        ),
    )


class DeepSeekClient:
    """Async client for any OpenAI-compatible chat/completions API.

    The class name is kept for backward compatibility; the provider is driven
    entirely by `Settings` (base_url / model / api_key).
    """

    MAX_REQUEST_TOKENS = 8192  # safe per-request output cap; larger values are rejected by the API

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.base_url.rstrip("/")
        self.model = settings.model
        self.api_key = settings.api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers={"Content-Type": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] | None = None,
        *,
        stream_callback: StreamCallback | None = None,
        reasoning_callback: StreamCallback | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> LLMResponse:
        """Send a chat request with optional tool definitions and streaming.

        `model` overrides the configured model for this call (e.g. planner).
        """
        payload = {
            "model": model or self.model,
            "messages": [m.to_openai() for m in messages],
            "stream": True,
            "temperature": temperature if temperature is not None else self.settings.temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = min(max_tokens, self.MAX_REQUEST_TOKENS)
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            payload["tool_choice"] = "auto"

        if not self.api_key:
            raise RuntimeError(
                f"未配置 API Key（当前提供商 {self.settings.provider}）。"
                f"请在 设置 > 模型 填写 {self.settings.key_env_var} 后重试。"
            )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return await self._stream_once(payload, stream_callback, reasoning_callback)
            except httpx.HTTPStatusError as exc:
                status_code = getattr(exc.response, "status_code", 0)
                if status_code in (400, 401, 402, 404, 422):
                    raise  # non-retryable (bad request / auth / billing / not found)
                wait = 2 ** attempt
                logger.warning("LLM request failed (%s), retrying in %ss", exc, wait)
                await asyncio.sleep(wait)
            except httpx.TransportError as exc:
                last_error = exc
                wait = 2 ** attempt
                logger.warning("LLM transport error (%s), retrying in %ss", exc, wait)
                await asyncio.sleep(wait)
        raise RuntimeError(f"LLM request failed after retries: {last_error}")

    async def _stream_once(
        self,
        payload: dict,
        stream_callback: StreamCallback | None,
        reasoning_callback: StreamCallback | None = None,
    ) -> LLMResponse:
        response = await self._client.post(
            "/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_deltas: dict[int, dict] = {}
        usage = Usage()
        finish_reason = "stop"

        async def _emit(callback: StreamCallback | None, text: str) -> None:
            if not callback or not text:
                return
            emitted = callback(text)
            if inspect.isawaitable(emitted):
                await emitted

        async def _finish_message(data: dict) -> None:
            nonlocal usage, finish_reason
            choice = (data.get("choices") or [{}])[0]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
                await _emit(stream_callback, delta["content"])
            if delta.get("reasoning_content"):
                reasoning_parts.append(delta["reasoning_content"])
                await _emit(reasoning_callback, delta["reasoning_content"])
            if delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    slot = tool_call_deltas.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
            if data.get("usage"):
                usage = _parse_usage(data["usage"])

        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            await _finish_message(chunk)

        tool_calls: list[ToolCall] = []
        for idx in sorted(tool_call_deltas):
            slot = tool_call_deltas[idx]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["arguments"]}
            tool_calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=args,
                )
            )

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
        )
