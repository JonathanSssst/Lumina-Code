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
        self._contexts: dict[str, tuple[Any, Any]] = {}
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
        # Keep the context managers alive for the whole lifetime of the server:
        # dropping the temporary returned by __aenter__() lets GC close the
        # async generator, which shuts the pipes down mid-handshake.
        stdio_cm = stdio_client(params)
        session_cm: Any = None
        try:
            read_stream, write_stream = await stdio_cm.__aenter__()
            session_cm = ClientSession(read_stream, write_stream)
            session = await session_cm.__aenter__()
            await session.initialize()
            self._servers[name] = (spec, session)
            self._contexts[name] = (stdio_cm, session_cm)
            tools = await session.list_tools()
            for tool in tools.tools:
                mcp_key = f"{name}_{tool.name}"
                self._mcp_names[mcp_key] = name
                # mcp 2.x renamed Tool.inputSchema -> Tool.input_schema
                input_schema = getattr(tool, "input_schema", None) or getattr(
                    tool, "inputSchema", {}
                )
                self._register_proxy(mcp_key, tool.name, spec, tool.description, input_schema)
        except BaseException:
            for cm in (session_cm, stdio_cm):
                if cm is not None:
                    try:
                        await cm.__aexit__(None, None, None)
                    except Exception:  # noqa: BLE001, S110
                        pass
            raise

    def _register_proxy(
        self, mcp_key: str, tool_name: str, spec: dict, description: str, input_schema: dict
    ) -> None:
        params = input_schema or {"type": "object", "properties": {}}

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

        proxy.__name__ = mcp_key
        self.registry.register(description=description, parameters=params)(proxy)

    async def close_all(self) -> None:
        for name in list(self._servers):
            session = self._servers[name][1]
            if name in self._contexts:
                for cm in self._contexts.pop(name):
                    try:
                        await cm.__aexit__(None, None, None)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Error closing MCP session: %s", exc)
            else:
                try:
                    await session.__aexit__(None, None, None)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Error closing MCP session: %s", exc)
        self._servers.clear()
