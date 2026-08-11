from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import create_model

from lumina.types import ToolResult, ToolSpec

ToolHandler = Callable[..., Awaitable[ToolResult]]


class ToolRegistry:
    """Registers async tool handlers and exposes their JSON-Schema specs."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._specs: dict[str, ToolSpec] = {}
        self._approval: dict[str, Callable[[dict[str, Any]], tuple[bool, str]]] = {}

    def register(
        self,
        *,
        description: str,
        requires_approval: bool = False,
        parameters: dict[str, Any] | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        def decorator(fn: ToolHandler) -> ToolHandler:
            name = fn.__name__
            sig = inspect.signature(fn)
            schema = parameters or _schema_from_signature(sig)
            self._specs[name] = ToolSpec(
                name=name,
                description=description,
                parameters=schema,
                requires_approval=requires_approval,
            )
            self._handlers[name] = fn
            return fn

        return decorator

    def handler(self, name: str) -> ToolHandler:
        return self._handlers[name]

    def set_handler(self, name: str, fn: ToolHandler) -> None:
        self._handlers[name] = fn

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def requires_approval(self, name: str) -> bool:
        return self._specs[name].requires_approval

    def register_approval_checker(
        self, name: str, checker: Callable[[dict[str, Any]], tuple[bool, str]]
    ) -> None:
        self._approval[name] = checker

    def check_approval(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Return (needs_approval, reason). Static flag OR dynamic checker decides."""
        checker = self._approval.get(name)
        if checker:
            dynamic, reason = checker(arguments)
            return dynamic, reason
        static = self._specs[name].requires_approval
        if static:
            return True, f"tool '{name}' requires approval"
        return False, ""


def _schema_from_signature(sig: inspect.Signature) -> dict[str, Any]:
    """Build a JSON-Schema object from a function signature (best-effort)."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        annotation = param.annotation
        type_name = _type_name(annotation)
        properties[name] = {"type": type_name}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def _type_name(annotation: Any) -> str:
    """Best-effort JSON-Schema type for a Python annotation.

    Works with real types and with string annotations produced by
    ``from __future__ import annotations``.
    """
    from typing import get_args, get_origin

    if isinstance(annotation, str):
        return _type_name(_string_annotation(annotation))
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is not None:
        inner = _type_name(args[0]) if args else "string"
        if origin is list:
            return "array"
        if origin is dict:
            return "object"
        if inner == "null":
            return "string"
        return "string"
    if annotation is str:
        return "string"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if annotation is bool:
        return "boolean"
    if annotation is list:
        return "array"
    if annotation is dict:
        return "object"
    return "string"


def _string_annotation(text: str) -> Any:
    """Resolve a string annotation back to a type when possible."""
    text = text.strip()
    if text in ("None", "NoneType"):
        return type(None)
    if "|" in text:
        left, _, right = text.partition("|")
        left = _string_annotation(left)
        right = _string_annotation(right)
        try:
            return left | right
        except TypeError:
            return str
    if text.endswith("]"):
        head, _, tail = text.partition("[")
        head = head.strip()
        tail = tail.strip().rstrip("]")
        origin = {
            "list": list,
            "dict": dict,
            "typing.List": list,
            "typing.Dict": dict,
            "typing.Optional": "optional",
            "Optional": "optional",
        }.get(head)
        if origin == "optional":
            return _string_annotation(tail) | None
        if origin is not None:
            inner = _string_annotation(tail)
            if origin is list:
                return list[inner]
            return dict
    return {
        "str": str,
        "string": str,
        "int": int,
        "integer": int,
        "float": float,
        "number": float,
        "bool": bool,
        "boolean": bool,
        "list": list,
        "dict": dict,
        "object": dict,
        "Any": str,
    }.get(text, str)


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
    """Coerce/validate tool arguments against the spec; raises ValueError on bad input."""
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    fields = {}
    for pname, pinfo in spec.parameters.get("properties", {}).items():
        pytype = _TYPE_MAP.get(pinfo.get("type", "string"), str)
        if pname in spec.parameters.get("required", []):
            fields[pname] = (pytype, ...)
        else:
            fields[pname] = (pytype | None, None)
    model = create_model(spec.name, **fields)
    try:
        data = model(**arguments).model_dump()
    except Exception as exc:
        raise ValueError(f"Invalid arguments for {spec.name}: {exc}") from exc
    # Drop optional params left as None so handler defaults apply.
    required = set(spec.parameters.get("required", []))
    return {k: v for k, v in data.items() if k in required or v is not None}
