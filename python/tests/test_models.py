"""Models of the six kinds: every example object round-trips, every invalid object is rejected
where its file says, unknown kinds are skipped (spec 002, story 1; research R1-R3)."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from ext_r2c.core import (
    Activity,
    Answer,
    AnswerBy,
    Approval,
    Field,
    InvalidObject,
    Option,
    Question,
    Subject,
    Unknown,
    parse,
    schema,
    schema_kinds,
    to_json,
)
from ext_r2c.core._schemas import format_checker, is_date_time
from r2c_check import example_files, find_r2c_objects, load_json

KINDS = {"question", "approval", "answer", "artifact", "activity", "usage"}
VALID = example_files("a2a") + example_files("mcp")
INVALID = example_files("invalid")


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def _objects(path: Path) -> list[tuple[str, dict[str, Any]]]:
    example = load_json(path)
    found: list[tuple[str, dict[str, Any]]] = []
    for n, step in enumerate(example["steps"]):
        found += find_r2c_objects(example["binding"], step["body"], f"/steps/{n}/body")
    return found


def _question(**extra: Any) -> dict[str, Any]:
    return {
        "kind": "question", "id": "q-1", "title": "Which warehouse?", "answer_by": {"role": "person"},
        "fields": [{"key": "warehouse", "header": "Warehouse", "text": "Which warehouse?", "type": "one",
                    "options": [{"label": "North"}, {"label": "South"}]}],
        **extra,
    }


# --- Round trip (SC-001) -----------------------------------------------------------------------


@pytest.mark.parametrize("path", VALID, ids=_id)
def test_every_example_object_round_trips(path: Path) -> None:
    for where, obj in _objects(path):
        if obj["kind"] not in KINDS:
            continue
        original = copy.deepcopy(obj)
        assert to_json(parse(obj)) == original, f"{where}: {obj['kind']} changed on the way back"
        assert obj == original, f"{where}: parse changed its input"


def test_unknown_kind_is_skipped() -> None:
    path = next(p for p in VALID if p.name == "unknown-kind-ignored.json")
    unknown = [parse(o) for _, o in _objects(path) if o["kind"] not in KINDS]
    assert unknown and all(isinstance(u, Unknown) for u in unknown)
    assert {u.kind for u in unknown} == {"provenance"}


# --- Rejection (SC-002) ------------------------------------------------------------------------


@pytest.mark.parametrize("path", INVALID, ids=_id)
def test_invalid_example_is_rejected_at_its_place(path: Path) -> None:
    example = load_json(path)
    with pytest.raises(InvalidObject) as caught:
        parse(example["object"])
    pointers = [p for p, _ in caught.value.errors]
    assert example["fails_at"] in pointers, f"rejected at {pointers}, not at {example['fails_at']!r}"
    assert all(message for _, message in caught.value.errors)


def test_missing_kind_is_invalid() -> None:
    obj = _question()
    del obj["kind"]
    with pytest.raises(InvalidObject):
        parse(obj)


def test_model_parse_refuses_another_kind() -> None:
    with pytest.raises(InvalidObject) as caught:
        Approval.parse(_question())
    assert "/kind" in [p for p, _ in caught.value.errors]


def test_duplicate_field_keys() -> None:
    obj = _question()
    obj["fields"].append(dict(obj["fields"][0]))
    with pytest.raises(InvalidObject) as caught:
        parse(obj)
    assert "/fields/1/key" in [p for p, _ in caught.value.errors]


def test_duplicate_option_labels() -> None:
    obj = _question()
    obj["fields"][0]["options"].append({"label": "North"})
    with pytest.raises(InvalidObject) as caught:
        parse(obj)
    assert "/fields/0/options/2/label" in [p for p, _ in caught.value.errors]


def test_unknown_enum_value_is_rejected() -> None:  # R2C-VERSION-3
    obj = _question()
    obj["fields"][0]["type"] = "date"
    with pytest.raises(InvalidObject):
        parse(obj)


# --- Open objects, defaults, numbers, dates ---------------------------------------------------


def test_unknown_activity_type_and_field_kept() -> None:
    obj = {"kind": "activity", "id": "a-1", "type": "plan", "label": "Planning", "tone": {"calm": True}}
    activity = parse(obj)
    assert isinstance(activity, Activity) and activity.type == "plan"
    assert to_json(activity) == obj


def test_defaults_read_not_written() -> None:
    question = parse(_question())
    assert isinstance(question, Question)
    field = question.fields[0]
    assert field.other is True and field.required is True
    dumped = to_json(question)["fields"][0]
    assert "other" not in dumped and "required" not in dumped


def test_code_built_object_dumps_kind() -> None:
    question = Question(
        id="q-1", title="Which warehouse?", answer_by=AnswerBy(role="person"),
        fields=[Field(key="warehouse", header="Warehouse", text="Which warehouse?", type="one",
                      options=[Option(label="North")])],
    )
    assert to_json(question) == {
        "kind": "question", "id": "q-1", "title": "Which warehouse?", "answer_by": {"role": "person"},
        "fields": [{"key": "warehouse", "header": "Warehouse", "text": "Which warehouse?", "type": "one",
                    "options": [{"label": "North"}]}],
    }


def test_to_json_rejects_what_the_schema_rejects() -> None:
    approval = Approval(
        id="ap-1", title="Delete the drafts", answer_by={"role": "person"},
        subject=Subject(type="operation", name="delete_drafts"), decisions=["edit"],
    )
    with pytest.raises(InvalidObject):
        to_json(approval)


def test_number_stays_int() -> None:
    obj = {"kind": "answer", "id": "q-1", "outcome": "answered", "answered_by": {"role": "person"},
           "value": {"quantity": 300}}
    assert to_json(parse(obj)) == obj
    usage = {"kind": "usage", "cost": {"amount": 300, "currency": "EUR"}}
    dumped = to_json(parse(usage))
    assert dumped == usage and isinstance(dumped["cost"]["amount"], int)


def test_expires_at_kept_as_written() -> None:
    question = parse(_question(expires_at="2026-11-20T10:15:00Z"))
    assert isinstance(question, Question)
    assert to_json(question)["expires_at"] == "2026-11-20T10:15:00Z"
    assert question.expires() == datetime(2026, 11, 20, 10, 15, tzinfo=timezone.utc)
    assert parse(_question()).expires() is None


def test_answer_model() -> None:
    answer = parse({"kind": "answer", "id": "ap-1", "outcome": "declined", "answered_by": {"role": "approver"}})
    assert isinstance(answer, Answer) and answer.value is None and answer.answered_by.role == "approver"


# --- Schemas and the date-time check (R3) ------------------------------------------------------


def test_own_date_time_check() -> None:
    checker = format_checker()
    assert checker.checkers["date-time"][0] is is_date_time
    for bad in ("nope", "2026-11-20", "2026-13-01T00:00:00Z", "2026-11-20T25:00:00Z", "2026-11-20T10:15:00"):
        assert not checker.conforms(bad, "date-time"), bad
    for good in ("2026-11-20T10:15:00Z", "2026-11-20T10:15:00.123456+07:00", "2026-11-20t10:15:00z"):
        assert checker.conforms(good, "date-time"), good


def test_schema_kinds_and_copies() -> None:
    assert set(schema_kinds()) == KINDS
    schema("question")["title"] = "changed"
    assert schema("question")["title"] == "R2C question"
