"""A plain function as a tool (FR-027, FR-028, research R12).

The input schema comes from the signature through a pydantic model. A call is checked against
that schema with the same checker as answers, so the schema shown to the caller is the one that
judges; the model then converts the values. A sync function runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import typing
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ConfigDict, ValidationError, create_model

from ._schemas import validator
from .check import Problem, _keyed, _one_per_key

__all__ = ["InvalidArguments", "ToolSpec", "tool_from_function"]


class InvalidArguments(ValueError):
    """The arguments break the tool's input schema; the function did not run."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__("invalid arguments: " + "; ".join(f"{p.key or '(arguments)'}: {p.message}" for p in problems))


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    call: Callable[[Mapping[str, Any]], Awaitable[Any]]


def _first_paragraph(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or ""
    return " ".join(doc.split("\n\n", 1)[0].split())


def _is_async(fn: Callable[..., Any]) -> bool:
    while isinstance(fn, functools.partial):
        fn = fn.func
    return inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(getattr(fn, "__call__", None))


def tool_from_function(
    fn: Callable[..., Any], *, name: str | None = None, description: str | None = None
) -> ToolSpec:
    """A ``ToolSpec`` from a function with type hints. ``*args``, ``**kwargs`` and positional-only
    parameters are refused with ``TypeError``: a tool is called with named arguments."""
    tool_name = name or fn.__name__
    try:
        hints = typing.get_type_hints(fn)
    except Exception as exc:
        raise TypeError(f"cannot read the type hints of {tool_name}: {exc}") from exc
    fields: dict[str, Any] = {}
    for p in inspect.signature(fn).parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD, p.POSITIONAL_ONLY):
            raise TypeError(f"{tool_name}: parameter {p.name!r} cannot be passed by name")
        if p.name.startswith("_"):
            raise TypeError(f"{tool_name}: parameter {p.name!r} starts with an underscore")
        default = ... if p.default is p.empty else p.default
        fields[p.name] = (hints.get(p.name, Any), default)

    model = create_model(  # type: ignore[call-overload]
        f"{tool_name}_arguments",
        __config__=ConfigDict(extra="forbid", protected_namespaces=()),
        **fields,
    )
    schema: dict[str, Any] = model.model_json_schema()
    schema.pop("title", None)
    check = validator(schema)
    order = list(fields)
    run_async = _is_async(fn)

    async def call(args: Mapping[str, Any]) -> Any:
        problems = _one_per_key("invalid_args", _keyed(check, dict(args)), order)
        if problems:
            raise InvalidArguments(problems)
        try:
            values = model.model_validate(dict(args))
        except ValidationError as exc:  # a constraint the schema could not express
            raise InvalidArguments([
                Problem("invalid_args", str(e["loc"][0]) if e["loc"] else None, "This value is not accepted.")
                for e in exc.errors()
            ]) from None
        kwargs = {k: getattr(values, k) for k in fields}
        if run_async:
            return await fn(**kwargs)
        return await asyncio.to_thread(fn, **kwargs)

    return ToolSpec(tool_name, _first_paragraph(fn) if description is None else description, schema, call)
