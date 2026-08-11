from __future__ import annotations

from lumina.agent.authorize import AutoApprover, DeniedToolError, Hooks


async def test_auto_approver_approves_everything():
    approver = AutoApprover()
    assert await approver.approve("rm -rf", {}, "dangerous") is True
    assert await approver.approve("read_file", {"path": "x"}, "") is True


def test_hooks_defaults_to_none():
    hooks = Hooks()
    assert hooks.on_tool_call is None
    assert hooks.on_tool_result is None
    assert hooks.on_assistant_message is None
    assert hooks.on_reasoning is None
    assert hooks.on_finish is None


def test_hooks_with_callbacks():
    calls = []

    async def cb(x):
        calls.append(x)

    hooks = Hooks(on_tool_call=cb)
    assert hooks.on_tool_call is cb


def test_denied_tool_error_fields():
    err = DeniedToolError(tool_call_id="t1", name="run_command", reason="user said no")
    assert err.tool_call_id == "t1"
    assert err.name == "run_command"
    assert err.reason == "user said no"
    assert "run_command" in str(err)
    assert "denied" in str(err)
