from __future__ import annotations

import asyncio
import json

from lumina.config import Settings, workspace_data_dir
from lumina.factory import build_registry
from lumina.mcp.client import CONFIG_NAME, McpBridge
from lumina.tools.registry import validate_arguments


def _bridge(workspace) -> McpBridge:
    registry = build_registry(workspace, Settings(DEEPSEEK_API_KEY="k"))
    return McpBridge(registry, workspace)


def test_load_config_workspace_preferred(tmp_path, monkeypatch):
    cfg = workspace_data_dir(tmp_path)
    cfg.mkdir()
    (cfg / CONFIG_NAME).write_text(
        json.dumps({"mcpServers": {"local": {"command": "python", "args": ["s.py"]}}}), encoding="utf-8"
    )
    global_cfg = tmp_path / "global"
    global_cfg.mkdir()
    monkeypatch.setattr("lumina.mcp.client.GLOBAL_CONFIG", global_cfg / CONFIG_NAME)
    (global_cfg / CONFIG_NAME).write_text(
        json.dumps({"mcpServers": {"global": {"command": "python"}}}), encoding="utf-8"
    )

    bridge = _bridge(tmp_path)
    assert set(bridge.config.get("mcpServers", {})) == {"local"}
    assert bridge.server_count == 1


def test_load_config_falls_back_to_global(tmp_path, monkeypatch):
    global_cfg = tmp_path / "global"
    global_cfg.mkdir()
    monkeypatch.setattr("lumina.mcp.client.GLOBAL_CONFIG", global_cfg / CONFIG_NAME)
    (global_cfg / CONFIG_NAME).write_text(
        json.dumps({"mcpServers": {"g": {"command": "x"}}}), encoding="utf-8"
    )

    bridge = _bridge(tmp_path)
    assert bridge.server_count == 1


def test_load_config_skips_invalid_json(tmp_path, monkeypatch):
    global_cfg = tmp_path / "global"
    global_cfg.mkdir()
    monkeypatch.setattr("lumina.mcp.client.GLOBAL_CONFIG", global_cfg / CONFIG_NAME)
    (global_cfg / CONFIG_NAME).write_text("{not json", encoding="utf-8")

    bridge = _bridge(tmp_path)
    assert bridge.config == {}
    assert bridge.server_count == 0


def test_connect_all_noop_when_mcp_unavailable(tmp_path, monkeypatch):
    cfg = workspace_data_dir(tmp_path)
    cfg.mkdir()
    (cfg / CONFIG_NAME).write_text(
        json.dumps({"mcpServers": {"s": {"command": "python"}}}), encoding="utf-8"
    )
    monkeypatch.setattr("lumina.mcp.client.MCP_AVAILABLE", False)
    bridge = _bridge(tmp_path)
    assert bridge.server_count == 1
    assert asyncio.run(bridge.connect_all()) == []


class _Block:
    def __init__(self, text: str) -> None:
        self.text = text


class _CallResult:
    def __init__(self, content: list, is_error: bool = False) -> None:
        self.content = content
        self.isError = is_error


class _FakeSession:
    def __init__(self, result: _CallResult) -> None:
        self.result = result

    async def call_tool(self, name, args):
        return self.result


async def test_proxy_calls_session_and_joins_blocks(tmp_path):
    session = _FakeSession(_CallResult([_Block("one"), _Block("two")]))
    bridge = _bridge(tmp_path)
    bridge._servers["srv"] = (None, session)
    bridge._mcp_names["srv_check"] = "srv"
    bridge._register_proxy(
        "srv_check", "check", {"command": "x"}, "check something", {"type": "object", "properties": {}}
    )

    spec = bridge.registry.get_spec("srv_check")
    result = await bridge.registry.handler("srv_check")(**validate_arguments(spec, {}))
    assert not result.is_error
    assert result.content == "one\ntwo"


async def test_proxy_reports_mcp_error_flag(tmp_path):
    session = _FakeSession(_CallResult([_Block("bad")], is_error=True))
    bridge = _bridge(tmp_path)
    bridge._servers["srv"] = (None, session)
    bridge._mcp_names["srv_fail"] = "srv"
    bridge._register_proxy(
        "srv_fail", "fail", {"command": "x"}, "", {"type": "object", "properties": {}}
    )

    spec = bridge.registry.get_spec("srv_fail")
    result = await bridge.registry.handler("srv_fail")(**validate_arguments(spec, {}))
    assert result.is_error


async def test_proxy_not_connected_returns_error(tmp_path):
    bridge = _bridge(tmp_path)
    bridge._register_proxy(
        "ghost", "g", {"command": "x"}, "", {"type": "object", "properties": {}}
    )
    spec = bridge.registry.get_spec("ghost")
    result = await bridge.registry.handler("ghost")(**validate_arguments(spec, {}))
    assert result.is_error
    assert "not connected" in result.content


async def test_close_all_aexit_sessions(tmp_path):
    class _Sess:
        def __init__(self):
            self.closed = False

        async def __aexit__(self, *a):
            self.closed = True

    s1, s2 = _Sess(), _Sess()
    bridge = _bridge(tmp_path)
    bridge._servers["a"] = (None, s1)
    bridge._servers["b"] = (None, s2)
    await bridge.close_all()
    assert s1.closed and s2.closed
    assert bridge._servers == {}
