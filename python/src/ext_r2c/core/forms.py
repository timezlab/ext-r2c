"""Forms generated from a request: the answer schema of a question (R2C-QUESTION-5), the flat
MCP ``requestedSchema`` of a question or an approval (R2C-MCP-2, R2C-MCP-3), and a flat MCP
response turned back into an R2C answer (R2C-MCP-4). See ``contracts/forms.md`` of spec 002.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ._schemas import external_refs
from .models import Answer, AnsweredBy, Approval, Field, Question

__all__ = ["McpForm", "NotAskableOverMcp", "answer_from_mcp", "answer_schema", "edit_offered", "mcp_form"]

_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
_FLAT_TYPES = {"string", "number", "integer", "boolean"}
_NOT_FLAT_KEYWORDS = {"$ref", "$dynamicRef", "anyOf", "oneOf", "allOf", "not"}
_FORM_NAMES = {"decision", "reason"}


class NotAskableOverMcp(ValueError):
    """An approval with no decision left once ``edit`` is dropped (only ``edit`` was offered)."""


@dataclass(frozen=True)
class McpForm:
    """A flat MCP form: the ``requestedSchema``, and for an approval the decisions it offers."""

    requested_schema: dict[str, Any]
    decisions: list[str] | None


# --- Answer schema -----------------------------------------------------------------------------


def _choice(field: Field) -> bool:
    return field.type in ("one", "many")


def _value_schema(field: Field) -> dict[str, Any]:
    labels = [o.label for o in field.options or []]
    if field.type == "one":
        return {"type": "string", "minLength": 1} if field.other else {"type": "string", "enum": labels}
    if field.type == "many":
        items: dict[str, Any] = {"type": "string", "minLength": 1} if field.other else {"enum": labels}
        many: dict[str, Any] = {"type": "array", "items": items, "uniqueItems": True}
        if field.required:
            many["minItems"] = 1
        return many
    if field.type == "text":
        return {"type": "string", "minLength": 1} if field.required else {"type": "string"}
    return {"type": "number"} if field.type == "number" else {"type": "boolean"}


def answer_schema(question: Question) -> dict[str, Any]:
    """The JSON Schema that checks the ``value`` of an answer to ``question``."""
    return {
        "$schema": _SCHEMA_URI,
        "type": "object",
        "properties": {f.key: _value_schema(f) for f in question.fields},
        "required": [f.key for f in question.fields if f.required],
    }


# --- Flat MCP forms ----------------------------------------------------------------------------


def _titled(values: list[str]) -> list[dict[str, str]]:
    return [{"const": v, "title": v} for v in values]


def _question_form(question: Question) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for f in question.fields:
        base = {"title": f.header, "description": f.text}
        labels = [o.label for o in f.options or []]
        if f.type == "one":
            props[f.key] = {"type": "string", **base, "oneOf": _titled(labels)}
        elif f.type == "many":
            props[f.key] = {"type": "array", **base, "items": {"anyOf": _titled(labels)}}
        else:
            props[f.key] = {"type": {"text": "string", "number": "number", "bool": "boolean"}[f.type], **base}
        if _choice(f) and f.other:
            props[f"{f.key}_other"] = {
                "type": "string",
                "title": f"{f.header} (other)",
                "description": f"Another {f.header.lower()}, if not listed.",
            }
    form: dict[str, Any] = {"type": "object", "properties": props}
    required = [f.key for f in question.fields if f.required and not (_choice(f) and f.other)]
    if required:
        form["required"] = required
    return form


def edit_offered(approval: Approval) -> bool:
    """``edit`` is offered and usable: a ``tool_call`` with an ``args_schema`` that stays in its
    own document (R2C-APPROVAL-3, R2C-SAFETY-7)."""
    subject = approval.subject
    return (
        "edit" in approval.decisions
        and subject.type == "tool_call"
        and isinstance(subject.args_schema, dict)
        and not external_refs(subject.args_schema)
    )


def _flat(args_schema: Mapping[str, Any]) -> bool:
    props = args_schema.get("properties")
    if args_schema.get("type") != "object" or not isinstance(props, Mapping):
        return False
    for name, prop in props.items():
        if name in _FORM_NAMES or not isinstance(prop, Mapping) or _NOT_FLAT_KEYWORDS & prop.keys():
            return False
        kind = prop.get("type")
        if "enum" in prop:
            enum = prop["enum"]
            if kind not in (None, "string") or not isinstance(enum, list) or not all(isinstance(v, str) for v in enum):
                return False
        elif kind not in _FLAT_TYPES:
            return False
    return True


def _argument_property(name: str, prop: Mapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: copy.deepcopy(v) for k, v in prop.items() if k not in ("title", "enum")}
    out["title"] = name
    if "enum" in prop:
        out.setdefault("type", "string")
        out["oneOf"] = _titled(list(prop["enum"]))
    if name in args:
        out["default"] = copy.deepcopy(args[name])
    return out


def _approval_form(approval: Approval) -> tuple[dict[str, Any], list[str]]:
    schema = approval.subject.args_schema
    editable = edit_offered(approval) and schema is not None and _flat(schema)
    offered = [d for d in approval.decisions if d != "edit" or editable]
    if not offered:
        raise NotAskableOverMcp(
            f"approval {approval.id!r} offers only 'edit', and its args_schema cannot be a flat MCP form"
        )
    props: dict[str, Any] = {
        "decision": {"type": "string", "title": "Decision",
                     "oneOf": [{"const": d, "title": d.capitalize()} for d in offered]},
        "reason": {"type": "string", "title": "Reason"},
    }
    if "edit" in offered and schema is not None:
        args = approval.subject.args or {}
        for name, prop in schema["properties"].items():
            props[name] = _argument_property(name, prop, args)
    return {"type": "object", "properties": props, "required": ["decision"]}, offered


def mcp_form(request: Question | Approval) -> McpForm:
    """The flat MCP form of a request; ``NotAskableOverMcp`` for an approval left with no decision."""
    if isinstance(request, Question):
        return McpForm(_question_form(request), None)
    schema, offered = _approval_form(request)
    return McpForm(schema, offered)


# --- Flat response → answer --------------------------------------------------------------------


def _given(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _question_value(question: Question, content: Mapping[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for f in question.fields:
        other = content.get(f"{f.key}_other") if _choice(f) and f.other else None
        if f.type == "one":
            if _given(other):
                value[f.key] = other
            elif f.key in content:
                value[f.key] = content[f.key]
        elif f.type == "many":
            chosen = content.get(f.key)
            if _given(other):
                items = list(chosen) if isinstance(chosen, list) else []
                value[f.key] = items if other in items else [*items, other]
            elif f.key in content:
                value[f.key] = chosen
        elif f.key in content:
            value[f.key] = content[f.key]
    return value


def _approval_value(approval: Approval, content: Mapping[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    if "decision" in content:
        value["decision"] = content["decision"]
    if _given(content.get("reason")):
        value["reason"] = content["reason"]
    if content.get("decision") == "edit":
        args = dict(approval.subject.args or {})
        props = (approval.subject.args_schema or {}).get("properties") or {}
        for name in props:
            if name in content and name not in _FORM_NAMES:
                args[name] = content[name]
        value["args"] = args
    return value


def answer_from_mcp(
    request: Question | Approval,
    action: Literal["accept", "decline", "cancel"],
    content: Mapping[str, Any] | None,
) -> Answer:
    """The R2C answer derived from one MCP elicitation response (R2C-MCP-4). It is not checked:
    pass it to ``check_answer`` like any other answer."""
    by = AnsweredBy(role="person")
    if action in ("decline", "cancel"):
        return Answer(id=request.id, outcome="declined", answered_by=by)
    if action != "accept":
        raise ValueError(f"unknown elicitation action {action!r}")
    content = content or {}
    if isinstance(request, Question):
        value = _question_value(request, content)
    else:
        value = _approval_value(request, content)
    return Answer(id=request.id, outcome="answered", answered_by=by, value=value)
