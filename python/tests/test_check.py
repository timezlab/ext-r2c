"""Answer checking: every FR-015 rule fails with its code and key, problems read as sentences,
the decision fails closed, sizes are counted without decoding, and no `$ref` reaches the network
(spec 002, story 2; research R6; contracts/core-api.md "Answer checking")."""

from __future__ import annotations

import base64
import binascii
import copy
import re
import socket
from datetime import datetime, timezone
from typing import Any

import pytest

from ext_r2c.core import (
    Answer,
    Approval,
    Limits,
    Problem,
    Question,
    check_answer,
    check_size,
    decision,
)

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
LATE = datetime(2026, 11, 20, 11, 0, 1, tzinfo=timezone.utc)

QUESTION_OBJ: dict[str, Any] = {
    "kind": "question", "id": "q-2", "title": "Report settings", "answer_by": {"role": "person"},
    "fields": [
        {"key": "sections", "header": "Sections", "text": "Which sections should the report have?", "type": "many",
         "other": False, "options": [{"label": "Stock"}, {"label": "Orders"}, {"label": "Returns"}]},
        {"key": "title", "header": "Title", "text": "What is the report's title?", "type": "text"},
        {"key": "threshold", "header": "Threshold", "text": "Below which stock level is an item flagged?",
         "type": "number"},
        {"key": "charts", "header": "Charts", "text": "Include charts?", "type": "bool"},
        {"key": "note", "header": "Note", "text": "A note for the reader, if any.", "type": "text", "required": False},
    ],
}
QUESTION = Question.parse(QUESTION_OBJ)
GOOD_VALUE = {"sections": ["Stock"], "title": "October stock", "threshold": 20, "charts": True}

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "item": {"type": "string"},
        "quantity": {"type": "integer", "minimum": 1, "maximum": 1000},
        "supplier": {"type": "string", "enum": ["S-7", "S-9"]},
    },
    "required": ["item", "quantity", "supplier"],
}
APPROVAL_OBJ: dict[str, Any] = {
    "kind": "approval", "id": "ap-1", "title": "Place the order for A-113",
    "answer_by": {"role": "approver", "approver_role": "purchasing lead"},
    "subject": {"type": "tool_call", "name": "place_order",
                "args": {"item": "A-113", "quantity": 500, "supplier": "S-7"}, "args_schema": ARGS_SCHEMA},
    "decisions": ["allow", "edit", "deny"],
    "expires_at": "2026-11-20T11:00:00Z",
}
APPROVAL = Approval.parse(APPROVAL_OBJ)
EDITED = {"item": "A-113", "quantity": 300, "supplier": "S-9"}


def _approval(**changes: Any) -> Approval:
    obj = copy.deepcopy(APPROVAL_OBJ)
    subject = changes.pop("subject", None)
    if subject is not None:
        obj["subject"].update(subject)
    obj.update(changes)
    return Approval.parse(obj)


def _answer(id: str = "q-2", outcome: str = "answered", role: str = "person", value: Any = None) -> Answer:
    """An answer built without the schema check, so a malformed one can reach `check_answer`."""
    obj: dict[str, Any] = {"kind": "answer", "id": id, "outcome": outcome, "answered_by": {"role": role}}
    if value is not None:
        obj["value"] = value
    return Answer.model_validate(obj)


def _approve(value: Any, role: str = "approver") -> Answer:
    return _answer("ap-1", role=role, value=value)


def _codes(problems: list[Problem]) -> list[tuple[str, str | None]]:
    return [(p.code, p.key) for p in problems]


# --- Answers that fit --------------------------------------------------------------------------


def test_good_answers_have_no_problem() -> None:
    assert check_answer(_answer(value=GOOD_VALUE), QUESTION, now=NOW) == []
    assert check_answer(_answer(value={**GOOD_VALUE, "note": ""}), QUESTION, now=NOW) == []  # optional text
    assert check_answer(_answer(outcome="declined"), QUESTION, now=NOW) == []
    assert check_answer(_approve({"decision": "allow"}), APPROVAL, now=NOW) == []
    assert check_answer(_approve({"decision": "deny", "reason": "Too many."}), APPROVAL, now=NOW) == []
    assert check_answer(_approve({"decision": "edit", "args": EDITED}), APPROVAL, now=NOW) == []
    assert check_answer(_answer("ap-1", outcome="declined", role="approver"), APPROVAL, now=NOW) == []


def test_now_defaults_to_the_clock() -> None:
    old = _approval(expires_at="2000-01-01T00:00:00Z")
    assert _codes(check_answer(_approve({"decision": "allow"}), old)) == [("expired", None)]


# --- One bad answer per FR-015 rule ------------------------------------------------------------

BAD: list[tuple[str, Answer, Question | Approval, dict[str, Any], tuple[str, str | None]]] = [
    ("too_large", _answer(value={**GOOD_VALUE, "title": "x" * 200}), QUESTION,
     {"limits": Limits(message_bytes=100)}, ("too_large", None)),
    ("invalid_answer: declined with a value", _answer(outcome="declined", value=GOOD_VALUE), QUESTION, {},
     ("invalid_answer", None)),
    ("invalid_answer: answered without a value", _answer(), QUESTION, {}, ("invalid_answer", None)),
    ("wrong_id", _answer(id="q-9", value=GOOD_VALUE), QUESTION, {}, ("wrong_id", None)),
    ("caller_on_approval", _approve({"decision": "allow"}, role="caller"), APPROVAL, {},
     ("caller_on_approval", None)),
    ("expired", _approve({"decision": "allow"}), APPROVAL, {"now": LATE}, ("expired", None)),
    ("invalid_value on a question", _answer(value={**GOOD_VALUE, "threshold": "twenty"}), QUESTION, {},
     ("invalid_value", "threshold")),
    ("invalid_value on an approval", _approve({"decision": "maybe"}), APPROVAL, {}, ("invalid_value", "decision")),
    ("invalid_value: edit without args", _approve({"decision": "edit"}), APPROVAL, {}, ("invalid_value", "args")),
    ("not_offered: edit not in decisions", _approve({"decision": "edit", "args": EDITED}),
     _approval(decisions=["allow", "deny"]), {}, ("not_offered", "decision")),
    ("not_offered: edit with an external $ref", _approve({"decision": "edit", "args": EDITED}),
     _approval(subject={"args_schema": {"$ref": "https://example.invalid/args.json"}}), {},
     ("not_offered", "decision")),
    ("invalid_args", _approve({"decision": "edit", "args": {**EDITED, "quantity": 5000}}), APPROVAL, {},
     ("invalid_args", "quantity")),
]


@pytest.mark.parametrize(("name", "answer", "request_", "options", "expected"), BAD, ids=[b[0] for b in BAD])
def test_each_rule_fails_with_its_code_and_key(
    name: str, answer: Answer, request_: Question | Approval, options: dict[str, Any],
    expected: tuple[str, str | None],
) -> None:
    options = {"now": NOW, **options}
    assert _codes(check_answer(answer, request_, **options)) == [expected]


def test_too_large_stops_before_any_other_check() -> None:
    big = _answer(id="q-9", value={"title": "x" * 200})
    assert _codes(check_answer(big, QUESTION, now=NOW, limits=Limits(message_bytes=100))) == [("too_large", None)]


def test_every_problem_is_returned_in_order() -> None:
    answer = _approve({"decision": "allow"}, role="caller")
    assert _codes(check_answer(answer, APPROVAL, now=LATE)) == [("expired", None), ("caller_on_approval", None)]


def test_a_required_error_gives_one_problem_per_missing_key() -> None:
    problems = check_answer(_answer(value={"sections": ["Stock"]}), QUESTION, now=NOW)
    assert _codes(problems) == [("invalid_value", "title"), ("invalid_value", "threshold"), ("invalid_value", "charts")]


def test_one_problem_per_field() -> None:
    value = {**GOOD_VALUE, "sections": ["Nope", "Nope"]}  # not an option, twice
    assert _codes(check_answer(_answer(value=value), QUESTION, now=NOW)) == [("invalid_value", "sections")]


def test_empty_required_values_fail() -> None:
    value = {**GOOD_VALUE, "title": "", "sections": []}
    problems = check_answer(_answer(value=value), QUESTION, now=NOW)
    assert _codes(problems) == [("invalid_value", "sections"), ("invalid_value", "title")]


def test_missing_arguments_give_one_problem_each() -> None:
    problems = check_answer(_approve({"decision": "edit", "args": {"quantity": 300}}), APPROVAL, now=NOW)
    assert _codes(problems) == [("invalid_args", "item"), ("invalid_args", "supplier")]


def test_a_local_ref_in_args_schema_is_followed() -> None:
    local = {"$defs": {"qty": {"type": "integer", "maximum": 1000}}, "type": "object",
             "properties": {"quantity": {"$ref": "#/$defs/qty"}}}
    approval = _approval(subject={"args_schema": local, "args": {"quantity": 500}})
    assert check_answer(_approve({"decision": "edit", "args": {"quantity": 300}}), approval, now=NOW) == []
    problems = check_answer(_approve({"decision": "edit", "args": {"quantity": 5000}}), approval, now=NOW)
    assert _codes(problems) == [("invalid_args", "quantity")]


# --- Messages ----------------------------------------------------------------------------------

KEYWORDS = re.compile(
    r"\b(type|enum|const|minLength|maxLength|minItems|maxItems|required|minimum|maximum|uniqueItems|"
    r"additionalProperties|pattern|anyOf|oneOf|allOf)\b"
)


def _all_problems() -> list[Problem]:
    out: list[Problem] = []
    for _, answer, request_, options, _ in BAD:
        out += check_answer(answer, request_, **{"now": NOW, **options})
    out += check_answer(_answer(value={"sections": ["Nope", "Nope"], "title": "", "charts": "yes"}), QUESTION, now=NOW)
    out += check_answer(_approve({"decision": "edit", "args": {"quantity": 0, "supplier": "S-1"}}), APPROVAL, now=NOW)
    return out


def test_messages_are_short_sentences_without_schema_words() -> None:
    problems = _all_problems()
    assert len(problems) >= 15
    for p in problems:
        assert p.message[:1].isupper() and p.message.endswith("."), p
        assert len(p.message) <= 120, p
        assert not KEYWORDS.search(p.message), p
        assert "'" not in p.message and "{" not in p.message, p


def test_as_error_item_is_a_valid_errors_item() -> None:
    items = [p.as_error_item() for p in _all_problems()]
    assert any(i.key is None for i in items) and any(i.key for i in items)
    reask = {**QUESTION_OBJ, "errors": [i.model_dump(exclude_none=True) for i in items]}
    assert Question.parse(reask).errors is not None


# --- decision (FR-018) -------------------------------------------------------------------------


def test_decision_of_an_answered_approval() -> None:
    assert decision(_approve({"decision": "allow"}), APPROVAL, now=NOW) == "allow"
    assert decision(_approve({"decision": "edit", "args": EDITED}), APPROVAL, now=NOW) == "edit"
    assert decision(_approve({"decision": "deny"}), APPROVAL, now=NOW) == "deny"


def test_declined_and_expired_mean_deny() -> None:
    assert decision(_answer("ap-1", outcome="declined", role="approver"), APPROVAL, now=NOW) == "deny"
    assert decision(_approve({"decision": "allow"}), APPROVAL, now=LATE) == "deny"


def test_decision_fails_closed() -> None:
    assert decision(_approve({"decision": "allow"}, role="caller"), APPROVAL, now=NOW) == "deny"
    assert decision(_approve({"decision": "edit", "args": EDITED}), _approval(decisions=["allow", "deny"]),
                    now=NOW) == "deny"
    assert decision(_approve({"decision": "maybe"}), APPROVAL, now=NOW) == "deny"
    assert decision(_approve({"decision": "allow"}), _approval(id="ap-2"), now=NOW) == "deny"


def test_decision_of_a_question_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        decision(_answer(value=GOOD_VALUE), QUESTION, now=NOW)  # type: ignore[arg-type]


# --- check_size (FR-017) -----------------------------------------------------------------------


def test_default_limits_are_the_standards() -> None:
    assert Limits().message_bytes == 5 * 2**20
    assert Limits().file_bytes == 50 * 2**20
    assert check_size(text="x") is None


def test_text_is_counted_in_utf8_bytes() -> None:
    small = Limits(message_bytes=100)
    assert check_size(text="e" * 60, limits=small) is None
    problem = check_size(text="é" * 60, limits=small)  # 120 bytes
    assert problem is not None and problem.code == "too_large" and problem.key is None


def test_raw_base64_is_counted_by_its_decoded_size_without_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> bytes:
        raise AssertionError("check_size decoded the content")

    exact, over = base64.b64encode(b"x" * 100).decode(), base64.b64encode(b"x" * 101).decode()
    monkeypatch.setattr(base64, "b64decode", refuse)
    monkeypatch.setattr(binascii, "a2b_base64", refuse)
    small = Limits(message_bytes=100)
    assert len(exact) > 100
    assert check_size(raw_base64=exact, limits=small) is None
    assert check_size(raw_base64=over, limits=small) is not None


def test_a_custom_threshold_applies() -> None:
    assert check_size(text="x" * 11, limits=Limits(message_bytes=10)) is not None
    assert check_size(text="x" * 10, limits=Limits(message_bytes=10)) is None


# --- No $ref leaves the document (FR-016, R2C-SAFETY-7) ----------------------------------------


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("a socket was opened")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.mark.usefixtures("no_network")
def test_an_external_ref_opens_no_socket() -> None:
    nested = {"type": "object", "properties": {"quantity": {"$ref": "https://example.invalid/args.json"}}}
    for args_schema in ({"$ref": "https://example.invalid/args.json"}, nested):
        approval = _approval(subject={"args_schema": args_schema})
        problems = check_answer(_approve({"decision": "edit", "args": EDITED}), approval, now=NOW)
        assert _codes(problems) == [("not_offered", "decision")]
        assert check_answer(_approve({"decision": "allow"}), approval, now=NOW) == []
