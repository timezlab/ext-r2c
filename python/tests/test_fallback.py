"""Fallback text (R2C-CORE-4, FR-019): exact strings for hand-built requests and activities, and a
readable, non-empty text for every request and activity in the examples (contracts/forms.md
"Fallback text"; research R13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ext_r2c.core import Activity, Approval, Question, edit_offered, fallback_text, parse
from r2c_check import example_files, find_r2c_objects, load_json

QUESTION: dict[str, Any] = {
    "kind": "question", "id": "q-1", "title": "Report settings", "description": "For October only.",
    "answer_by": {"role": "person"},
    "fields": [
        {"key": "warehouse", "header": "Warehouse", "text": "Which warehouse?", "type": "one",
         "options": [{"label": "North"}, {"label": "South"}]},
        {"key": "region", "header": "Region", "text": "Which region?", "type": "one", "other": False,
         "options": [{"label": "East"}, {"label": "West"}]},
        {"key": "sections", "header": "Sections", "text": "Which sections?", "type": "many",
         "options": [{"label": "Stock"}, {"label": "Orders"}]},
        {"key": "kinds", "header": "Kinds", "text": "Which kinds?", "type": "many", "other": False,
         "options": [{"label": "A"}, {"label": "B"}]},
        {"key": "title", "header": "Title", "text": "What title?", "type": "text"},
        {"key": "threshold", "header": "Threshold", "text": "Below which level?", "type": "number"},
        {"key": "charts", "header": "Charts", "text": "Include charts?", "type": "bool"},
        {"key": "note", "header": "Note", "text": "Any note?", "type": "text", "required": False},
        {"key": "limit", "header": "Limit", "text": "Any limit?", "type": "number", "required": False},
    ],
}


def test_a_question_with_every_field_type() -> None:
    assert fallback_text(Question.parse(QUESTION)) == "\n".join([
        "Report settings",
        "For October only.",
        "- Warehouse: Which warehouse? (one of: North, South, or another)",
        "- Region: Which region? (one of: East, West)",
        "- Sections: Which sections? (one or more of: Stock, Orders, or others)",
        "- Kinds: Which kinds? (one or more of: A, B)",
        "- Title: What title?",
        "- Threshold: Below which level? (a number)",
        "- Charts: Include charts? (yes/no)",
        "- Note: Any note? (optional)",
        "- Limit: Any limit? (a number; optional)",
    ])


def test_a_forwarded_reask() -> None:
    question = {
        "kind": "question", "id": "q-1", "title": "Reorder threshold", "answer_by": {"role": "person"},
        "origin": {"name": "inventory-service", "url": "https://inventory.example.com/a2a"},
        "errors": [{"key": "threshold", "message": "Must be a number, for example 20."},
                   {"message": "Please answer again."}],
        "fields": [{"key": "threshold", "header": "Threshold", "text": "Below which stock level?", "type": "number"}],
    }
    assert fallback_text(Question.parse(question)) == "\n".join([
        "Must be a number, for example 20.",
        "Please answer again.",
        "inventory-service asks: Reorder threshold",
        "- Threshold: Below which stock level? (a number)",
    ])


APPROVAL: dict[str, Any] = {
    "kind": "approval", "id": "ap-1", "title": "Place the order for A-113", "description": "500 units from S-7.",
    "answer_by": {"role": "approver", "approver_role": "purchasing lead"},
    "subject": {"type": "tool_call", "name": "place_order", "args": {"item": "A-113", "quantity": 500},
                "args_schema": {"type": "object", "properties": {"item": {"type": "string"},
                                                                 "quantity": {"type": "integer"}}}},
    "decisions": ["allow", "edit", "deny"],
    "expires_at": "2026-11-20T11:00:00Z",
}


def test_an_approval_with_role_expiry_and_edit() -> None:
    assert fallback_text(Approval.parse(APPROVAL)) == "\n".join([
        "Approval needed (purchasing lead): Place the order for A-113",
        "500 units from S-7.",
        "Reply with one of: allow | edit | deny (expires 2026-11-20T11:00:00Z)",
    ])


def test_an_approval_lists_only_the_offered_decisions() -> None:
    plain = {
        "kind": "approval", "id": "ap-2", "title": "Publish the page", "answer_by": {"role": "person"},
        "subject": {"type": "operation", "name": "publish"}, "decisions": ["deny", "allow"],
    }
    assert fallback_text(Approval.parse(plain)) == "Approval needed: Publish the page\nReply with one of: deny | allow"
    external = {**APPROVAL, "subject": {**APPROVAL["subject"], "args_schema": {"$ref": "https://example.invalid/a.json"}}}
    assert fallback_text(Approval.parse(external)).endswith("Reply with one of: allow | deny (expires 2026-11-20T11:00:00Z)")


def test_an_activity() -> None:
    running = {"kind": "activity", "id": "call-1", "type": "tool", "state": "running", "name": "read_inventory",
               "label": "Reading the inventory"}
    done = {**running, "state": "done", "label": "Read the inventory", "detail": "412 items"}
    assert fallback_text(Activity.parse(running)) == "Reading the inventory"
    assert fallback_text(Activity.parse(done)) == "Read the inventory: 412 items"


# --- Every request and activity in the examples ------------------------------------------------


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _objects() -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for path in example_files("a2a") + example_files("mcp"):
        example = load_json(path)
        for n, step in enumerate(example["steps"]):
            for where, obj in find_r2c_objects(example["binding"], step["body"], f"/steps/{n}/body"):
                if obj.get("kind") in ("question", "approval", "activity"):
                    out.append((f"{_id(path)}{where}", obj))
    return out


OBJECTS = _objects()


def test_the_examples_have_requests_and_activities() -> None:
    kinds = {obj["kind"] for _, obj in OBJECTS}
    assert kinds == {"question", "approval", "activity"}


@pytest.mark.parametrize(("where", "obj"), OBJECTS, ids=[w for w, _ in OBJECTS])
def test_every_example_object_has_a_readable_text(where: str, obj: dict[str, Any]) -> None:
    model = parse(obj)
    text = fallback_text(model)  # type: ignore[arg-type]
    assert text.strip()
    if isinstance(model, Activity):
        assert model.label in text
        return
    assert model.title in text
    if isinstance(model, Question):
        for field in model.fields:
            assert field.text in text
            for option in field.options or []:
                assert option.label in text
    else:
        assert isinstance(model, Approval)
        for d in model.decisions:
            assert (d in text) or (d == "edit" and not edit_offered(model))
