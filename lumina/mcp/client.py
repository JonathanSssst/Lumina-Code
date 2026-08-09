from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from lumina.tools.registry import ToolRegistry
from lumina.types import ToolResult

logger = logging.getLogger(__name__)

try:  # optional dependency: pip install lumina[mcp]
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    MCP_AVAILABLE = False
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore

CONFIG_NAME = "lumina.mcp.json"
GLOBAL_CONFIG = Path.home() / ".config" / "lumina" / CONFIG_NAME


class McpBridge:
    """Discovers MCP servers from config and registers their tools in a ToolRegistry.

    Config format (workspace `.lumina/lumina.mcp.json` or global config):
        {"mcpServers": {"server-name": {"command": "python", "args": ["server.py"], "env": {}}}}
    """

    def __init__(self, registry: ToolRegistry, workspace: Path) -> None:
        self.registry = registry
        self.workspace = Path(workspace).resolve()
        self.config = self._load_config()
        self._servers: dict[str, tuple[Any, ClientSession]] = {}
        self._mcp_names: dict[str, str] = {}

    def _load_config(self) -> dict:
        candidates = [
            self.workspace / ".lumina" / CONFIG_NAME,
            GLOBAL_CONFIG,
        ]
        for path in candidates:
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
        return {}

    @property
    def server_count(self) -> int:
        return len(self.config.get("mcpServers", {}))

    async def connect_all(self) -> list[str]:
        if not MCP_AVAILABLE:
            return []
        errors: list[str] = []
        for name, spec in self.config.get("mcpServers", {}).items():
            try:
                await self._connect_one(name, spec)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{name}: {exc}")
        return errors

    async def _connect_one(self, name: str, spec: dict) -> None:
        params = StdioServerParameters(
            command=spec["command"],
            args=spec.get("args", []),
            env=spec.get("env"),
        )
        read_stream, write_stream = await stdio_client(params).__aenter__()
        session = await ClientSession(read_stream, write_stream).__aenter__()
        await session.initialize()
        self._servers[name] = (spec, session)
        tools = await session.list_tools()
        for tool in tools.tools:
            mcp_key = f"{name}_{tool.name}"
            self._mcp_names[mcp_key] = name
            self._register_proxy(mcp_key, tool.name, spec, tool.description, tool.inputSchema)

    def _register_proxy(
        self, mcp_key: str, tool_name: str, spec: dict, description: str, input_schema: dict
    ) -> None:
        params = input_schema or {"type": "object", "properties": {}}

        @self.registry.register(description=description, parameters=params)
        async def proxy(**arguments: Any) -> ToolResult:
            session = self._servers.get(self._mcp_names.get(mcp_key, ""))
            if session is None:
                return ToolResult(tool_call_id="", name=mcp_key, content="MCP server not connected", is_error=True)
            result = await session[1].call_tool(tool_name, arguments)
            text = "\n".join(
                getattr(block, "text", str(block)) for block in result.content
            )
            return ToolResult(
                tool_call_id="",
                name=mcp_key,
                content=text,
                is_error=result.isError if hasattr(result, "isError") else False,
            )

    async def close_all(self) -> None:
        for _spec, session in self._servers.values():
            try:
                await session.__aexit__(None, None, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error closing MCP session: %s", exc)
        self._servers.clear()
