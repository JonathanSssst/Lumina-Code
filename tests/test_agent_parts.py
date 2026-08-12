from __future__ import annotations

from lumina.agent.budget import TokenBudget
from lumina.context.project import ProjectScanner
from lumina.factory import build_registry
from lumina.skills.loader import SkillLoader
from lumina.tools.registry import validate_arguments
from lumina.types import Usage


def test_budget_exhaustion():
    budget = TokenBudget(max_tokens=100, max_iterations=3)
    assert not budget.exhausted
    budget.record(Usage(prompt_tokens=60, completion_tokens=60, total_tokens=120))
    assert budget.exhausted
    assert budget.reason == "budget_exhausted"
    assert budget.total_tokens == 120


def test_budget_zero_limits_are_unlimited():
    budget = TokenBudget(max_tokens=0, max_iterations=0)
    for _ in range(100):
        budget.record(Usage(prompt_tokens=50, completion_tokens=50, total_tokens=100))
    assert not budget.exhausted


def test_budget_reason_distinguishes_limits():
    iters = TokenBudget(max_tokens=0, max_iterations=3)
    iters.record(Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20))
    iters.record(Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20))
    iters.record(Usage(prompt_tokens=10, completion_tokens=10, total_tokens=20))
    assert iters.exhausted
    assert iters.reason == "iterations_exhausted"
    assert iters.snapshot().reason == "iterations_exhausted"

    toks = TokenBudget(max_tokens=100, max_iterations=0)
    toks.record(Usage(prompt_tokens=80, completion_tokens=80, total_tokens=160))
    assert toks.exhausted
    assert toks.reason == "budget_exhausted"


def test_project_scanner_detects_structure(workspace):
    scanner = ProjectScanner(workspace)
    ctx = scanner.scan()
    assert "src/calc.py" in ctx
    assert "tests/test_calc.py" in ctx
    assert "pyproject.toml" in ctx
    assert "Python" in ctx


def test_skill_loader_matches_triggers(tmp_path):
    skill_dir = tmp_path / ".lumina" / "skills" / "bug-fix"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "---\nname: bug-fix\ndescription: bug fixing workflow\ntrigger: 修复, fix\n---\n"
        "Reproduce first, then minimal fix.\n",
        encoding="utf-8",
    )
    loader = SkillLoader(tmp_path)
    skills = loader.load()
    assert len(skills) == 1
    assert skills[0].name == "bug-fix"
    assert len(loader.match("帮我修复这个 bug")) == 1
    assert loader.match("无关话题") == []


def test_project_memory_tools_read_write_agents(tmp_path):
    from lumina.types import ToolResult

    async def go():
        registry = build_registry(tmp_path, None)
        read = registry.handler("read_agents")
        write = registry.handler("write_agents")
        first = await read()
        assert isinstance(first, ToolResult)
        assert "No AGENTS.md exists" in first.content
        await write(content="# Project\n- run tests with pytest\n")
        second = await read()
        assert "pytest" in second.content
        await write(content="## Extra\n- keep files ASCII\n", append=True)
        third = await read()
        assert "pytest" in third.content
        assert "ASCII" in third.content

    import asyncio

    asyncio.run(go())


def test_project_memory_write_agents_spec_and_approval(tmp_path):
    registry = build_registry(tmp_path, None)
    spec = registry.get_spec("write_agents")
    assert spec is not None
    args = validate_arguments(spec, {"content": "x"})
    assert args["content"] == "x"
    needs, _ = registry.check_approval("write_agents", {"content": "x"})
    assert needs is False
