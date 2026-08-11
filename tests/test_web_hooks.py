"""WsHooks must stay compatible with the agent loop hooks contract.

Regression: WsHooks was a bare class missing on_thinking_done, so the loop's
``if self.hooks.on_thinking_done:`` check raised AttributeError while sending
a message over the web UI.
"""

from lumina.web.app import WsHooks


def test_ws_hooks_has_all_loop_hook_attributes():
    hooks = WsHooks(ws=None)
    assert hooks.on_thinking_done is None
    assert hooks.on_assistant_message is not None
    assert hooks.on_reasoning is not None
    assert hooks.on_tool_call is not None
    assert hooks.on_tool_result is not None
    assert hooks.on_finish is None


def test_ws_hooks_missing_hook_defaults_are_none_not_attribute_error():
    hooks = WsHooks(ws=None)
    assert getattr(hooks, "on_thinking_done", None) is None
    assert not hooks.on_thinking_done
