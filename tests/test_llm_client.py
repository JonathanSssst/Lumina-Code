from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from lumina.config import Settings
from lumina.llm.client import DeepSeekClient
from lumina.types import Message


def _make_client(api_key: str = "test-key") -> DeepSeekClient:
    settings = Settings(DEEPSEEK_API_KEY=api_key)
    return DeepSeekClient(settings)


class FakeStream:
    """Mimics httpx.Response streaming: raise_for_status() + aiter_lines()."""

    def __init__(self, lines: list[str], status: int = 200) -> None:
        self._lines = lines
        self._status = status
        self._req = httpx.Request("POST", "http://x")

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self._status}", request=self._req, response=httpx.Response(self._status, request=self._req)
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _sse(payload: dict | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}"
    return "data: " + json.dumps(payload)


def _complete_payload(content: str = "hi") -> str:
    return _sse(
        {
            "choices": [{"delta": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
    )


def _fake_post(stream):
    async def fake_post(*args, **kwargs):
        return stream

    return fake_post


async def test_chat_parses_content_and_usage(monkeypatch):
    client = _make_client()
    stream = FakeStream(
        [
            _sse({"choices": [{"delta": {"content": "he"}}]}),
            _sse({"choices": [{"delta": {"content": "llo"}}]}),
            _sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            _complete_payload(""),
            "data: [DONE]",
        ]
    )
    monkeypatch.setattr(client._client, "post", _fake_post(stream))

    streamed: list[str] = []
    resp = await client.chat([Message(role="user", content="hi")], stream_callback=streamed.append)
    assert resp.content == "hello"
    assert resp.finish_reason == "stop"
    assert resp.usage.total_tokens == 8
    assert streamed == ["he", "llo"]
    await client.aclose()


async def test_chat_reasoning_callback_and_raw_args(monkeypatch):
    client = _make_client()
    stream = FakeStream(
        [
            _sse({"choices": [{"delta": {"reasoning_content": "think"}}]}),
            _sse(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {"index": 0, "id": "t1", "function": {"name": "read_file", "arguments": "{\"path\":"}}
                                ]
                            }
                        }
                    ]
                }
            ),
            _sse(
                {
                    "choices": [
                        {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"a.py\"}"}}]}}
                    ]
                }
            ),
            _sse(
                {
                    "choices": [
                        {"delta": {"tool_calls": [{"index": 1, "function": {"name": "grep", "arguments": "[not json"}}]}}
                    ]
                }
            ),
            "data: [DONE]",
        ]
    )
    monkeypatch.setattr(client._client, "post", _fake_post(stream))

    thoughts: list[str] = []
    resp = await client.chat(
        [Message(role="user", content="hi")], reasoning_callback=thoughts.append
    )
    assert thoughts == ["think"]
    assert len(resp.tool_calls) == 2
    assert resp.tool_calls[0].name == "read_file"
    assert resp.tool_calls[0].arguments == {"path": "a.py"}
    assert resp.tool_calls[1].name == "grep"
    assert resp.tool_calls[1].arguments == {"_raw": "[not json"}
    assert resp.tool_calls[0].id == "t1"
    assert resp.tool_calls[1].id == "call_1"
    await client.aclose()


async def test_chat_ignores_garbage_and_usage_late(monkeypatch):
    client = _make_client()
    stream = FakeStream(
        [
            "not a data line",
            "data: {bad json",
            _complete_payload("ok"),
            "data: [DONE]",
        ]
    )
    monkeypatch.setattr(client._client, "post", _fake_post(stream))
    resp = await client.chat([Message(role="user", content="hi")])
    assert resp.content == "ok"
    assert resp.usage.total_tokens == 8
    await client.aclose()


async def test_chat_retries_transient_http_error(monkeypatch):
    client = _make_client()
    req = httpx.Request("POST", "http://x")
    calls = {"n": 0}

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.HTTPStatusError(
                "boom", request=req, response=httpx.Response(500, request=req)
            )
        return FakeStream([_complete_payload("ok"), "data: [DONE]"])

    monkeypatch.setattr(client._client, "post", flaky)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda s: real_sleep(0))

    resp = await client.chat([Message(role="user", content="hi")])
    assert resp.content == "ok"
    assert calls["n"] == 3
    await client.aclose()


async def test_chat_does_not_retry_client_errors(monkeypatch):
    client = _make_client()
    req = httpx.Request("POST", "http://x")

    async def bad(*a, **k):
        raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(400, request=req))

    monkeypatch.setattr(client._client, "post", bad)
    with pytest.raises(httpx.HTTPStatusError):
        await client.chat([Message(role="user", content="hi")])
    await client.aclose()


async def test_chat_retries_transport_error_then_fails(monkeypatch):
    client = _make_client()

    async def always_transport(*a, **k):
        raise httpx.TransportError("network down")

    monkeypatch.setattr(client._client, "post", always_transport)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda s: real_sleep(0))
    with pytest.raises(RuntimeError, match="LLM request failed after retries"):
        await client.chat([Message(role="user", content="hi")])
    await client.aclose()


def test_chat_requires_api_key():
    client = _make_client(api_key="")
    with pytest.raises(RuntimeError, match="API Key"):
        asyncio.run(client.chat([Message(role="user", content="hi")]))
    asyncio.run(client.aclose())


async def test_chat_uses_model_override_and_clamps_tokens(monkeypatch):
    client = _make_client()
    sent: dict = {}

    async def capture(url, json=None, headers=None):
        sent.update(json)
        return FakeStream([_complete_payload("ok"), "data: [DONE]"])

    monkeypatch.setattr(client._client, "post", capture)
    await client.chat(
        [Message(role="user", content="hi")],
        model="other-model",
        max_tokens=999999,
        temperature=0.2,
    )
    assert sent["model"] == "other-model"
    assert sent["max_tokens"] == client.MAX_REQUEST_TOKENS
    assert sent["temperature"] == 0.2
    await client.aclose()
