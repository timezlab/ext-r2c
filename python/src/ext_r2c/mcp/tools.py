"""Serving ``ToolSpec``s, and approval before a direct tool call (``approve=``) (spec 004,
research R2, R10).

A tool named in ``approve=`` never runs before an ``allow`` or ``edit``: its first round is an
input-required approval, and the retry runs it at most once, the round claimed through the
ledger first. ``edit`` is offered for a tool of the door whose input schema is flat (R2C-MCP-3);
a tool registered elsewhere on the server gets ``allow`` and ``deny`` only.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import mcp_types as types
from jsonschema import Draft202012Validator

from ..core import (
    Approval,
    ArtifactEvent,
    InvalidArguments,
    ToolSpec,
    Usage,
    decision,
    mcp_form,
    parse,
    to_json,
)
from ._codec import content_blocks, final_result, input_required, output_too_large
from ._state import CLAIMED, StoppingPoint, dump, outcome
from .activation import Round
from .source_tool import tool_error

__all__ = ["Approve", "ToolOutput", "approval_for", "approve_first_round", "approve_retry", "serve_tool"]

_SHOWN = 512  # characters of the description that shows the arguments
NO_FORMS = "Not run: approval could not be asked (the client does not support forms)."
EXPIRED = "Not run: the approval expired."


@dataclass(frozen=True)
class Approve:
    """How a tool named in ``approve=`` is approved. ``expires_in`` sets ``expires_at`` from the
    door's clock; ``title`` defaults to ``Run <tool>``."""

    answer_by: Literal["person", "approver"] = "person"
    expires_in: timedelta | None = None
    title: str | None = None


@dataclass(frozen=True)
class ToolOutput:
    """What a ``ToolSpec`` call may return besides a ``str`` or a JSON value: the reply text,
    structured content, artifacts and usage."""

    text: str | None = None
    data: Any = None
    artifacts: tuple[ArtifactEvent, ...] = ()
    usage: Usage | None = None


# --- Serving a ToolSpec ----------------------------------------------------------------------------


def _result(value: Any, r: Round) -> types.CallToolResult:
    if isinstance(value, ToolOutput):
        blocks = [b for a in value.artifacts for b in content_blocks(a, active=True)]
        reply, usage, structured = value.text or "", value.usage, value.data
    else:
        blocks, usage = [], None
        if isinstance(value, str):
            reply, structured = value, None
        else:
            reply = json.dumps(value, ensure_ascii=False, default=str)
            structured = value if isinstance(value, dict) else None
    problem = output_too_large(reply, blocks, r.limits)
    if problem is not None:
        return tool_error(problem.message, usage=usage, active=r.active)
    return final_result(reply=reply, blocks=blocks, usage=usage, active=r.active, structured=structured)


async def serve_tool(spec: ToolSpec, r: Round, arguments: Mapping[str, Any]) -> types.CallToolResult:
    """Check the arguments, call the tool once, and map its return value."""
    try:
        value = await spec.call(arguments)
    except InvalidArguments as exc:
        return tool_error(str(exc), active=r.active)
    except Exception as exc:  # the tool failed: the model reads why, as an error
        return tool_error(str(exc) or type(exc).__name__, active=r.active)
    return _result(value, r)


# --- Approval ------------------------------------------------------------------------------------


def _stamp(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def _shown(arguments: Mapping[str, Any]) -> str:
    """The arguments a person approves, as one line: the elicitation message shows them even when
    the form cannot (no ``edit``, or a client that does not read R2C)."""
    line = "Arguments: " + json.dumps(dict(arguments), ensure_ascii=False, default=str)
    return line if len(line) <= _SHOWN else line[: _SHOWN - 1] + "…"


def approval_for(name: str, arguments: Mapping[str, Any], schema: dict[str, Any] | None, settings: Approve, *,
                 editable: bool, now: datetime) -> Approval:
    """The approval of one call: ``subject`` is the tool, its arguments and its listed schema, and
    ``description`` shows the arguments. ``edit`` is offered only when ``editable`` and the
    schema makes a flat form."""
    subject: dict[str, Any] = {"type": "tool_call", "name": name, "args": dict(arguments)}
    if schema is not None:
        subject["args_schema"] = schema
    data: dict[str, Any] = {
        "kind": "approval", "id": f"ap-{uuid.uuid4().hex[:8]}", "title": settings.title or f"Run {name}",
        "description": _shown(arguments),
        "answer_by": {"role": settings.answer_by}, "subject": subject,
        "decisions": ["allow", "edit", "deny"] if editable else ["allow", "deny"],
    }
    if settings.expires_in is not None:
        data["expires_at"] = _stamp(now + settings.expires_in)
    approval = parse(data)
    assert isinstance(approval, Approval)
    if editable and "edit" not in (mcp_form(approval).decisions or []):
        data["decisions"] = ["allow", "deny"]
        approval = parse(data)
        assert isinstance(approval, Approval)
    return approval


def _ask(r: Round, approval: Approval, *, call: str, refusal: str | None = None) -> types.InputRequiredResult:
    point = StoppingPoint(call=call, round=uuid.uuid4().hex, kind="approve", request=to_json(approval),
                          owner=r.owner)
    return input_required(approval, dump(point), active=r.active, usage=None, refusal=refusal)


def approve_first_round(r: Round, name: str, arguments: Mapping[str, Any], settings: Approve, *,
                        schema: dict[str, Any] | None, editable: bool) -> types.CallToolResult | types.InputRequiredResult:
    if schema is not None:  # a person never approves a call that cannot run
        problems = sorted(Draft202012Validator(schema).iter_errors(dict(arguments)), key=lambda e: list(e.path))
        if problems:
            return tool_error("invalid arguments: " + "; ".join(p.message for p in problems), active=r.active)
    if not r.form:
        return tool_error(NO_FORMS, active=r.active)
    approval = approval_for(name, arguments, schema, settings, editable=editable, now=r.clock())
    return _ask(r, approval, call=uuid.uuid4().hex)


RunTool = Callable[[Mapping[str, Any]], Awaitable[Any]]


async def approve_retry(r: Round, point: StoppingPoint, responses: Mapping[str, types.ElicitResult],
                        run_tool: RunTool) -> Any:
    """The retry of an approval round: re-ask, refuse, or run the tool once with the call's (or
    the edited) arguments."""
    found = await outcome(point, responses, ledger=r.ledger, ttl=r.ttl, now=r.clock(), limits=r.limits)
    approval = found.request
    assert isinstance(approval, Approval)
    if found.kind == "claimed":
        return tool_error(CLAIMED, active=r.active)
    if found.kind in ("missing", "reask"):
        return _ask(r, approval, call=point.call, refusal=found.refusal)
    if found.kind == "expired":
        return tool_error(EXPIRED, active=r.active)
    assert found.answer is not None
    chosen = decision(found.answer, approval, now=r.clock())
    if chosen == "deny":
        reason = (found.answer.value or {}).get("reason")
        return tool_error("Not run: denied." + (f" Reason: {reason}" if reason else ""), active=r.active)
    arguments = (found.answer.value or {}).get("args") if chosen == "edit" else approval.subject.args
    return await run_tool(dict(arguments or {}))
