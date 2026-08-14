from __future__ import annotations

import asyncio
import json
import sys

import pytest

from lumina.config import Settings, workspace_data_dir
from lumina.factory import build_registry
from lumina.mcp.client import CONFIG_NAME, MCP_AVAILABLE, McpBridge
from lumina.tools.registry import validate_arguments

_SERVER_SOURCE = '''\
import asyncio, sys

try:
    from mcp.server.mcpserver import MCPServer as Server
    MODE = "mcpserver"
except ImportError:
    from mcp.server.fastmcp import FastMCP as Server
    MODE = "fastmcp"

server = Server(name="demo")


@server.tool()
async def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
async def echo(text: str) -> str:
    """Echo the input text."""
    return text


if __name__ == "__main__":
    if MODE == "mcpserver":
        asyncio.run(server.run_stdio_async())
    else:
        server.run()
'''

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp SDK not installed")


def _write_server(tmp_path) -> str:
    script = tmp_path / "mcp_server.py"
    script.write_text(_SERVER_SOURCE, encoding="utf-8")
    return str(script)


def _config(workspace, script: str, server_name: str = "demo") -> None:
    cfg = workspace_data_dir(workspace)
    cfg.mkdir(exist_ok=True)
    (cfg / CONFIG_NAME).write_text(
        json.dumps(
            {"mcpServers": {server_name: {"command": sys.executable, "args": [script]}}}
        ),
        encoding="utf-8",
    )


def _bridge(workspace) -> McpBridge:
    registry = build_registry(workspace, Settings(DEEPSEEK_API_KEY="k"))
    return McpBridge(registry, workspace)


def test_connect_all_registers_and_calls_tools(tmp_path):
    script = _write_server(tmp_path)
    _config(tmp_path, script)
    bridge = _bridge(tmp_path)
    assert bridge.server_count == 1

    async def run():
        errors = await bridge.connect_all()
        assert errors == []

        spec = bridge.registry.get_spec("demo_add")
        assert spec is not None
        result = await bridge.registry.handler("demo_add")(
            **validate_arguments(spec, {"a": 2, "b": 40})
        )
        assert not result.is_error
        assert result.content.strip() == "42"

        spec2 = bridge.registry.get_spec("demo_echo")
        result2 = await bridge.registry.handler("demo_echo")(
            **validate_arguments(spec2, {"text": "hi there"})
        )
        assert not result2.is_error
        assert "hi there" in result2.content

        await bridge.close_all()

    asyncio.run(run())
    assert bridge._servers == {}


def test_connect_all_collects_errors(tmp_path):
    cfg = workspace_data_dir(tmp_path)
    cfg.mkdir()
    (cfg / CONFIG_NAME).write_text(
        json.dumps({"mcpServers": {"broken": {"command": "definitely-not-a-real-cmd-xyz", "args": []}}}),
        encoding="utf-8",
    )
    bridge = _bridge(tmp_path)
    errors = asyncio.run(bridge.connect_all())
    assert len(errors) == 1
    assert errors[0].startswith("broken:")


def test_connect_all_cleans_up_after_failed_handshake(tmp_path, monkeypatch):
    class _BadCm:
        async def __aenter__(self):
            raise RuntimeError("handshake boom")

        async def __aexit__(self, *a):
            raise RuntimeError("close boom")

    monkeypatch.setattr("lumina.mcp.client.stdio_client", lambda *a, **k: _BadCm())
    cfg = workspace_data_dir(tmp_path)
    cfg.mkdir()
    (cfg / CONFIG_NAME).write_text(
        json.dumps({"mcpServers": {"s": {"command": sys.executable, "args": ["x.py"]}}}),
        encoding="utf-8",
    )
    bridge = _bridge(tmp_path)
    assert bridge.server_count == 1
    errors = asyncio.run(bridge.connect_all())
    assert len(errors) == 1
    assert "handshake boom" in errors[0]


def test_close_all_tolerates_aexit_errors(tmp_path):
    class _BadSession:
        async def __aexit__(self, *a):
            raise RuntimeError("boom")

    bridge = _bridge(tmp_path)
    bridge._servers["x"] = (None, _BadSession())
    asyncio.run(bridge.close_all())
    assert bridge._servers == {}
