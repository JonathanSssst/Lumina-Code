from __future__ import annotations

from pathlib import Path

from lumina.agent.authorize import AsyncApprover, Hooks
from lumina.agent.loop import Agent
from lumina.config import Settings
from lumina.context.project import ProjectScanner
from lumina.llm.client import DeepSeekClient
from lumina.tools.files import FileTools
from lumina.tools.git import GitTools
from lumina.tools.registry import ToolRegistry
from lumina.tools.search import SearchTools
from lumina.tools.shell import ShellTools
from lumina.tools.web import WebTools


def build_registry(workspace: Path, settings: Settings) -> ToolRegistry:
    registry = ToolRegistry()
    FileTools(workspace, registry)
    SearchTools(workspace, registry)
    ShellTools(workspace, registry, settings)
    GitTools(workspace, registry)
    web = WebTools(registry)
    registry.web_tools = web  # closed together with the agent
    return registry


def build_agent(
    workspace: Path,
    settings: Settings,
    approver: AsyncApprover,
    hooks: Hooks | None = None,
    *,
    enable_mcp: bool = True,
    enable_skills: bool = True,
) -> Agent:
    client = DeepSeekClient(settings)
    registry = build_registry(workspace, settings)
    scanner = ProjectScanner(workspace)
    mcp_bridge = None
    if enable_mcp:
        try:
            from lumina.mcp import MCP_AVAILABLE, McpBridge

            if MCP_AVAILABLE:
                mcp_bridge = McpBridge(registry, workspace)
        except ImportError:  # pragma: no cover
            mcp_bridge = None
    skills = None
    if enable_skills:
        try:
            from lumina.skills import SkillLoader

            skills = SkillLoader(workspace)
        except ImportError:  # pragma: no cover
            skills = None
    return Agent(
        settings=settings,
        client=client,
        registry=registry,
        workspace=workspace,
        approver=approver,
        hooks=hooks,
        scanner=scanner,
        skills=skills,
        mcp_bridge=mcp_bridge,
    )
