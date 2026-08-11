from __future__ import annotations

from lumina.agent.authorize import AutoApprover
from lumina.config import Settings
from lumina.factory import build_agent, build_registry


def test_build_registry_exposes_web_tools(tmp_path):
    settings = Settings(DEEPSEEK_API_KEY="k")
    registry = build_registry(tmp_path, settings)
    assert registry.web_tools is not None
    assert "web_search" in registry.names()


def test_build_agent_with_mcp_and_skills(tmp_path, monkeypatch):
    class FakeMcp:
        def __init__(self, registry, workspace):
            self.registry = registry
            self.workspace = workspace

    class FakeSkills:
        def __init__(self, workspace):
            self.workspace = workspace

    monkeypatch.setattr("lumina.mcp.MCP_AVAILABLE", True)
    monkeypatch.setattr("lumina.mcp.McpBridge", FakeMcp)
    monkeypatch.setattr("lumina.skills.SkillLoader", FakeSkills)

    agent = build_agent(tmp_path, Settings(DEEPSEEK_API_KEY="k"), AutoApprover())
    assert isinstance(agent.mcp_bridge, FakeMcp)
    assert isinstance(agent.skills, FakeSkills)
    assert agent.workspace == tmp_path.resolve()


def test_build_agent_disables_optional_integrations(tmp_path, monkeypatch):
    agent = build_agent(
        tmp_path,
        Settings(DEEPSEEK_API_KEY="k"),
        AutoApprover(),
        enable_mcp=False,
        enable_skills=False,
    )
    assert agent.mcp_bridge is None
    assert agent.skills is None
    assert "run_parallel" in agent.registry.names()


def test_build_agent_survives_import_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("lumina.mcp.MCP_AVAILABLE", False)
    agent = build_agent(tmp_path, Settings(DEEPSEEK_API_KEY="k"), AutoApprover())
    assert agent.mcp_bridge is None
