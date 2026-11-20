"""Forms: the answer schema of a question, the flat MCP forms, and flat responses back to
answers (spec 002, story 3; contracts/forms.md; research R7-R9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from ext_r2c.core import (
    Approval,
    NotAskableOverMcp,
    Question,
    answer_from_mcp,
    answer_schema,
    edit_offered,
    mcp_form,
    parse,
    to_json,
)
from r2c_check import MCP_KEY, example_files, load_json

MCP_EXAMPLES = example_files("mcp")


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _question(*fields: dict[str, Any]) -> Question:
    q = parse({"kind": "question", "id": "q-1", "title": "Report settings", "answer_by": {"role": "person"},
               "fields": list(fields)})
    assert isinstance(q, Question)
    return q


def _field(key: str, type_: str, **extra: Any) -> dict[str, Any]:
    f: dict[str, Any] = {"key": key, "header": key.capitalize(), "text": f"The {key}?", "type": type_}
    if type_ in ("one", "many"):
        f["options"] = [{"label": "A"}, {"label": "B"}]
    f.update(extra)
    return f


def _approval(args_schema: dict[str, Any] | None, args: dict[str, Any] | None = None,
              decisions: list[str] | None = None) -> Approval:
    subject: dict[str, Any] = {"type": "tool_call", "name": "place_order",
                               "args": args if args is not None else {"item": "A-113", "quantity": 500}}
    if args_schema is not None:
        subject["args_schema"] = args_schema
    a = parse({"kind": "approval", "id": "ap-1", "title": "Place a reorder", "answer_by": {"role": "person"},
               "subject": subject, "decisions": decisions or ["allow", "edit", "deny"]})
    assert isinstance(a, Approval)
    return a


FLAT = {"type": "object", "properties": {"item": {"type": "string"},
                                         "quantity": {"type": "number", "minimum": 1, "maximum": 1000}}}


# --- Answer schema (R2C-QUESTION-5, Q2) -------------------------------------------------------

ROWS = [
    (_field("f", "one", other=False), {"type": "string", "enum": ["A", "B"]}),
    (_field("f", "one"), {"type": "string", "minLength": 1}),
    (_field("f", "many", other=False),
     {"type": "array", "items": {"enum": ["A", "B"]}, "uniqueItems": True, "minItems": 1}),
    (_field("f", "many"),
     {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True, "minItems": 1}),
    (_field("f", "text"), {"type": "string", "minLength": 1}),
    (_field("f", "number"), {"type": "number"}),
    (_field("f", "bool"), {"type": "boolean"}),
    (_field("f", "many", other=False, required=False),
     {"type": "array", "items": {"enum": ["A", "B"]}, "uniqueItems": True}),
    (_field("f", "many", required=False),
     {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}),
    (_field("f", "text", required=False), {"type": "string"}),
    (_field("f", "one", required=False), {"type": "string", "minLength": 1}),
]


@pytest.mark.parametrize(("field", "expected"), ROWS, ids=[f"{r[0]['type']}-{i}" for i, r in enumerate(ROWS)])
def test_answer_schema_rows(field: dict[str, Any], expected: dict[str, Any]) -> None:
    s = answer_schema(_question(field))
    assert s["type"] == "object"
    assert s["properties"] == {"f": expected}
    assert s["required"] == ([] if field.get("required") is False else ["f"])
    Draft202012Validator.check_schema(s)


def test_answer_schema_required_means_not_empty() -> None:
    s = answer_schema(_question(_field("title", "text"), _field("sections", "many", other=False)))
    v = Draft202012Validator(s)
    assert v.is_valid({"title": "October", "sections": ["A"]})
    assert not v.is_valid({"title": "", "sections": ["A"]})
    assert not v.is_valid({"title": "October", "sections": []})
    assert not v.is_valid({"sections": ["A"]})


# --- Flat forms match every MCP example (R2C-MCP-2, R2C-MCP-3) --------------------------------


def _input_required(path: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(key, R2C request, elicitation params) for every input request of an MCP example."""
    out = []
    for step in load_json(path)["steps"]:
        result = step["body"].get("result")
        if not isinstance(result, dict) or "inputRequests" not in result:
            continue
        r2c = result.get("_meta", {}).get(MCP_KEY)
        if r2c is None:
            continue  # a plain elicitation: R2C is not active (not-activated.json)
        objects = r2c["input_requests"]
        for key, req in result["inputRequests"].items():
            out.append((key, objects[key], req["params"]))
    return out


FORM_EXAMPLES = [p for p in MCP_EXAMPLES if _input_required(p)]


def test_there_are_form_examples() -> None:
    assert len(FORM_EXAMPLES) >= 5


@pytest.mark.parametrize("path", FORM_EXAMPLES, ids=_id)
def test_every_mcp_form_matches_its_example(path: Path) -> None:
    for key, obj, params in _input_required(path):
        request = parse(obj)
        assert isinstance(request, (Question, Approval))
        assert mcp_form(request).requested_schema == params["requestedSchema"], f"{key}: form differs"


# Copied from each example's description ("Derived answer: ...").
DERIVED = {
    "elicitation-question.json": {
        "kind": "answer", "id": "q-2", "outcome": "answered", "answered_by": {"role": "person"},
        "value": {"warehouse": "North", "sections": ["Stock", "Returns"], "title": "October stock",
                  "threshold": 20, "charts": True},
    },
    "elicitation-question-other.json": {
        "kind": "answer", "id": "q-1", "outcome": "answered", "answered_by": {"role": "person"},
        "value": {"warehouse": "East annex"},
    },
    "elicitation-question-many-other.json": {
        "kind": "answer", "id": "q-1", "outcome": "answered", "answered_by": {"role": "person"},
        "value": {"sections": ["Stock", "Suppliers"]},
    },
    "elicitation-approval.json": {
        "kind": "answer", "id": "ap-1", "outcome": "answered", "answered_by": {"role": "person"},
        "value": {"decision": "edit", "args": {"item": "A-113", "quantity": 300, "supplier": "S-7"}},
    },
    "elicitation-approval-edit-dropped.json": {
        "kind": "answer", "id": "ap-1", "outcome": "declined", "answered_by": {"role": "person"},
    },
}


@pytest.mark.parametrize("name", sorted(DERIVED))
def test_derived_answers(name: str) -> None:
    path = next((p for p in MCP_EXAMPLES if p.name == name), None)
    assert path is not None, f"example {name} is missing"
    requests = {key: obj for key, obj, _ in _input_required(path)}
    responses = [
        (key, resp) for step in load_json(path)["steps"]
        for key, resp in (step["body"].get("params", {}).get("inputResponses") or {}).items()
    ]
    assert responses, f"{name} has no inputResponses"
    for key, resp in responses:
        request = parse(requests[key])
        assert isinstance(request, (Question, Approval))
        answer = answer_from_mcp(request, resp["action"], resp.get("content"))
        assert to_json(answer) == DERIVED[name]


# --- Approval forms (R2C-MCP-3, O3) ------------------------------------------------------------


def _decisions(form_schema: dict[str, Any]) -> list[str]:
    return [o["const"] for o in form_schema["properties"]["decision"]["oneOf"]]


def test_flat_args_keep_edit() -> None:
    form = mcp_form(_approval(FLAT))
    assert form.decisions == ["allow", "edit", "deny"]
    props = form.requested_schema["properties"]
    assert props["item"] == {"type": "string", "title": "item", "default": "A-113"}
    assert props["quantity"] == {"type": "number", "title": "quantity", "minimum": 1, "maximum": 1000, "default": 500}
    assert form.requested_schema["required"] == ["decision"]


@pytest.mark.parametrize("name", ["decision", "reason"])
def test_argument_named_like_a_form_property_drops_edit(name: str) -> None:
    schema = {"type": "object", "properties": {name: {"type": "string"}}}
    form = mcp_form(_approval(schema, args={name: "x"}))
    assert form.decisions == ["allow", "deny"]
    assert set(form.requested_schema["properties"]) == {"decision", "reason"}


def test_nested_argument_drops_edit() -> None:
    schema = {"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "object"}}}}
    form = mcp_form(_approval(schema, args={"lines": []}))
    assert _decisions(form.requested_schema) == ["allow", "deny"]


def test_external_ref_drops_edit_and_is_not_offered() -> None:
    schema = {"type": "object", "properties": {"item": {"$ref": "https://example.com/item.json"}}}
    approval = _approval(schema)
    assert edit_offered(approval) is False
    assert mcp_form(approval).decisions == ["allow", "deny"]


def test_local_ref_is_offered_but_not_flat() -> None:
    schema = {"type": "object", "$defs": {"item": {"type": "string"}},
              "properties": {"item": {"$ref": "#/$defs/item"}}}
    approval = _approval(schema, args={"item": "A-113"})
    assert edit_offered(approval) is True
    assert mcp_form(approval).decisions == ["allow", "deny"]


def test_integer_and_bool_stay_flat() -> None:
    schema = {"type": "object", "properties": {"count": {"type": "integer"}, "urgent": {"type": "boolean"}}}
    form = mcp_form(_approval(schema, args={"count": 3, "urgent": False}))
    assert "edit" in (form.decisions or [])
    assert form.requested_schema["properties"]["urgent"] == {"type": "boolean", "title": "urgent", "default": False}


def test_string_enum_without_type_becomes_titled_one_of() -> None:
    schema = {"type": "object", "properties": {"supplier": {"enum": ["S-7", "S-9"], "description": "Who supplies"}}}
    form = mcp_form(_approval(schema, args={"supplier": "S-9"}))
    assert form.requested_schema["properties"]["supplier"] == {
        "type": "string", "title": "supplier", "description": "Who supplies", "default": "S-9",
        "oneOf": [{"const": "S-7", "title": "S-7"}, {"const": "S-9", "title": "S-9"}],
    }


def test_argument_without_current_value_has_no_default() -> None:
    form = mcp_form(_approval(FLAT, args={"item": "A-113"}))
    assert "default" not in form.requested_schema["properties"]["quantity"]


def test_only_edit_with_non_flat_schema_cannot_be_asked() -> None:
    schema = {"type": "object", "properties": {"lines": {"type": "array"}}}
    with pytest.raises(NotAskableOverMcp):
        mcp_form(_approval(schema, args={"lines": []}, decisions=["edit"]))


def test_operation_approval_form() -> None:
    a = parse({"kind": "approval", "id": "ap-2", "title": "Delete the drafts", "answer_by": {"role": "person"},
               "subject": {"type": "operation", "name": "delete_drafts"}, "decisions": ["deny", "allow"]})
    assert isinstance(a, Approval)
    form = mcp_form(a)
    assert _decisions(form.requested_schema) == ["deny", "allow"]
    assert form.requested_schema["properties"]["decision"]["oneOf"][0] == {"const": "deny", "title": "Deny"}


def test_question_form_has_no_decisions() -> None:
    assert mcp_form(_question(_field("title", "text"))).decisions is None


def test_question_form_required_list() -> None:
    q = _question(_field("a", "one"), _field("b", "one", other=False), _field("c", "text", required=False),
                  _field("d", "many"), _field("e", "number"))
    s = mcp_form(q).requested_schema
    assert s["required"] == ["b", "e"]
    assert set(s["properties"]) == {"a", "a_other", "b", "c", "d", "d_other", "e"}
    assert s["properties"]["d_other"] == {"type": "string", "title": "D (other)", "description": "Another d, if not listed."}


def test_question_form_without_required_leaves_the_key_out() -> None:
    assert "required" not in mcp_form(_question(_field("a", "one"))).requested_schema


# --- Responses back to answers (R2C-MCP-4, Q1) -------------------------------------------------


def _value(request: Question | Approval, content: dict[str, Any]) -> dict[str, Any] | None:
    return answer_from_mcp(request, "accept", content).value


def test_empty_other_is_ignored() -> None:
    q = _question(_field("w", "one"))
    assert _value(q, {"w": "A", "w_other": ""}) == {"w": "A"}
    assert _value(q, {"w": "A", "w_other": "   "}) == {"w": "A"}
    assert _value(q, {"w": "A", "w_other": "C"}) == {"w": "C"}


def test_many_other_is_added_once() -> None:
    q = _question(_field("s", "many"))
    assert _value(q, {"s": ["A"], "s_other": "C"}) == {"s": ["A", "C"]}
    assert _value(q, {"s": ["A"], "s_other": "A"}) == {"s": ["A"]}
    assert _value(q, {"s_other": "C"}) == {"s": ["C"]}
    assert _value(q, {}) == {}


def test_unknown_content_keys_are_dropped() -> None:
    q = _question(_field("t", "text"))
    assert _value(q, {"t": "x", "stray": 1}) == {"t": "x"}


def test_allow_ignores_argument_values() -> None:
    assert _value(_approval(FLAT), {"decision": "allow", "quantity": 1}) == {"decision": "allow"}


def test_edit_keeps_left_out_arguments_and_drops_empty_reason() -> None:
    value = _value(_approval(FLAT), {"decision": "edit", "quantity": 300, "reason": ""})
    assert value == {"decision": "edit", "args": {"item": "A-113", "quantity": 300}}


def test_deny_keeps_reason() -> None:
    value = _value(_approval(FLAT), {"decision": "deny", "reason": "Too many"})
    assert value == {"decision": "deny", "reason": "Too many"}


@pytest.mark.parametrize("action", ["decline", "cancel"])
def test_decline_and_cancel_give_declined(action: str) -> None:
    answer = answer_from_mcp(_question(_field("t", "text")), action, None)  # type: ignore[arg-type]
    assert to_json(answer) == {"kind": "answer", "id": "q-1", "outcome": "declined", "answered_by": {"role": "person"}}
