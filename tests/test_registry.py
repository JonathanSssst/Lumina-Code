from __future__ import annotations

import pytest

from lumina.tools.registry import (
    ToolRegistry,
    _schema_from_signature,
    _type_name,
    validate_arguments,
)
from lumina.types import ToolResult


def test_type_name_mapping():
    assert _type_name(str) == "string"
    assert _type_name(int) == "integer"
    assert _type_name(float) == "number"
    assert _type_name(bool) == "boolean"
    assert _type_name(list) == "array"
    assert _type_name(dict) == "object"
    assert _type_name(type(None)) == "string"
    assert _type_name(list[str]) == "array"
    assert _type_name(dict[str, int]) == "object"
    assert _type_name(int | None) == "string"


def test_schema_from_signature_required_and_optional():
    def handler(path: str, content: str, *, limit: int = 5) -> None: ...

    schema = _schema_from_signature(__import__("inspect").signature(handler))
    assert schema["type"] == "object"
    assert "path" in schema["properties"]
    assert schema["required"] == ["path", "content"]
    assert schema["properties"]["path"] == {"type": "string"}
    assert schema["properties"]["limit"] == {"type": "integer"}


def test_schema_skips_varargs():
    def handler(*args, **kwargs) -> None: ...

    schema = _schema_from_signature(__import__("inspect").signature(handler))
    assert schema["properties"] == {}
    assert schema["required"] == []


def test_validate_arguments_coerces_types():
    spec = type(
        "Spec",
        (),
        {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, "flag": {"type": "boolean"}, "opt": {"type": "string"}},
                "required": ["n"],
            },
        },
    )()
    args = validate_arguments(spec, {"n": "42", "flag": 1})
    assert args == {"n": 42, "flag": True}


def test_validate_arguments_drops_unset_optionals():
    spec = type(
        "Spec",
        (),
        {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a"],
            },
        },
    )()
    assert validate_arguments(spec, {"a": "v"}) == {"a": "v"}


def test_validate_arguments_raises_on_bad_type():
    spec = type(
        "Spec",
        (),
        {
            "name": "x",
            "parameters": {
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
            },
        },
    )()
    with pytest.raises(ValueError):
        validate_arguments(spec, {"n": "not-a-number"})


def test_register_approval_checker_overrides_static():
    reg = ToolRegistry()

    @reg.register(description="tool", requires_approval=False)
    async def safe(a: str) -> ToolResult:
        return ToolResult(tool_call_id="", name="safe", content="ok")

    assert reg.check_approval("safe", {}) == (False, "")

    def dynamic(args):
        return (args.get("a") == "danger", "flagged by checker")

    reg.register_approval_checker("safe", dynamic)
    assert reg.check_approval("safe", {"a": "danger"})[0] is True
    needs, reason = reg.check_approval("safe", {"a": "fine"})
    assert needs is False
    assert "flagged" in reason


def test_static_requires_approval_flag():
    reg = ToolRegistry()

    @reg.register(description="t", requires_approval=True)
    async def risky(a: str) -> ToolResult:
        return ToolResult(tool_call_id="", name="risky", content="ok")

    needs, reason = reg.check_approval("risky", {})
    assert needs is True
    assert "requires approval" in reason


def test_registry_handler_and_spec_access():
    reg = ToolRegistry()

    @reg.register(description="hi", parameters={"type": "object", "properties": {}})
    async def hello() -> ToolResult:
        return ToolResult(tool_call_id="", name="hello", content="hi")

    assert reg.get_spec("hello").description == "hi"
    assert reg.handler("hello") is hello
    assert "hello" in reg.names()
    assert reg.requires_approval("hello") is False


def test_set_handler_overrides():
    reg = ToolRegistry()

    @reg.register(description="t")
    async def a() -> ToolResult:
        return ToolResult(tool_call_id="", name="a", content="orig")

    async def b() -> ToolResult:
        return ToolResult(tool_call_id="", name="a", content="new")

    reg.set_handler("a", b)
    assert reg.handler("a") is b
