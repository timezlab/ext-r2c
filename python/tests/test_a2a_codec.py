"""The codec between R2C objects and A2A Parts and Artifacts (spec 003, phase 2).

Every R2C Part and every artifact update in `standard/v1/examples/a2a/` reads to its core
object and encodes back to the same protobuf message. Equality is checked on the protobuf
messages: both sides hold numbers as doubles, so `20` and `20.0` compare equal there, and a
field left at its default (`append: false`) is the same as one not written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from a2a.types import Artifact, Message, Part, Role, Task, TaskArtifactUpdateEvent, TaskState, TaskStatus
from ext_r2c import URI
from ext_r2c.a2a._codec import (
    Invalid,
    _ints,
    answer_text,
    artifact_update,
    last_usage,
    pending_request,
    r2c_part,
    read_artifact,
    read_part,
    read_parts,
    text_answer,
)
from ext_r2c.core import (
    Answer,
    Approval,
    ArtifactMeta,
    BytesContent,
    Question,
    TextContent,
    Unknown,
    UrlContent,
    Usage,
    parse,
)
from google.protobuf import json_format

from r2c_check import example_files, load_json

EXAMPLES = example_files("a2a")


def _parts_in(node: Any) -> list[dict[str, Any]]:
    """Every Part of a body, in document order."""
    out: list[dict[str, Any]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "parts" and isinstance(value, list):
                out.extend(p for p in value if isinstance(p, dict))
            else:
                out.extend(_parts_in(value))
    elif isinstance(node, list):
        for item in node:
            out.extend(_parts_in(item))
    return out


def _is_r2c(part: dict[str, Any]) -> bool:
    meta = part.get("metadata")
    return isinstance(meta, dict) and meta.get(URI) == {} and isinstance(part.get("data"), dict)


def _r2c_parts() -> list[Any]:
    cases = []
    for path in EXAMPLES:
        for n, step in enumerate(load_json(path)["steps"]):
            r2c = [p for p in _parts_in(step["body"]) if _is_r2c(p)]
            for i, part in enumerate(r2c):
                cases.append(pytest.param(part, id=f"{path.name}#{n}.{i}"))
    return cases


def _artifact_updates() -> list[Any]:
    cases = []
    for path in EXAMPLES:
        for n, step in enumerate(load_json(path)["steps"]):
            update = step["body"].get("artifactUpdate") if isinstance(step["body"], dict) else None
            if update is not None:
                cases.append(pytest.param(update, id=f"{path.name}#{n}"))
    return cases


def _example(name: str) -> dict[str, Any]:
    return load_json(next(p for p in EXAMPLES if p.name == name))


def _objects(name: str) -> list[dict[str, Any]]:
    """The R2C objects of an example, in step and Part order."""
    out = []
    for step in _example(name)["steps"]:
        out.extend(p["data"] for p in _parts_in(step["body"]) if _is_r2c(p))
    return out


def _part(obj: dict[str, Any]) -> Part:
    return json_format.ParseDict({"data": obj, "metadata": {URI: {}}}, Part())


# --- Parts from the examples --------------------------------------------------------------------


def test_examples_have_r2c_parts_and_artifacts() -> None:
    assert len(_r2c_parts()) >= 30
    assert len(_artifact_updates()) >= 10


@pytest.mark.parametrize("part_json", _r2c_parts())
def test_r2c_part_reads_and_encodes_back(part_json: dict[str, Any]) -> None:
    part = json_format.ParseDict(part_json, Part())
    obj = read_part(part)
    if part_json["data"]["kind"] == "provenance":
        assert obj == Unknown("provenance", part_json["data"])
        return
    assert obj is not None and not isinstance(obj, (Unknown, Invalid))
    assert obj == parse(part_json["data"])
    assert r2c_part(obj) == part


def test_numbers_come_back_as_json_numbers() -> None:
    part = _part({"kind": "usage", "input_tokens": 5200, "cost": {"amount": 0.031, "currency": "EUR"}})
    usage = read_part(part)
    assert isinstance(usage, Usage)
    assert usage.input_tokens == 5200 and isinstance(usage.input_tokens, int)
    assert usage.cost is not None and usage.cost.amount == 0.031
    assert _ints({"a": [1.0, 2.5, True, {"b": 3.0}], "c": "4.0"}) == {"a": [1, 2.5, True, {"b": 3}], "c": "4.0"}


def test_a_plain_part_is_not_r2c() -> None:
    assert read_part(Part(text="Hello.")) is None
    assert read_part(json_format.ParseDict({"data": {"kind": "usage"}}, Part())) is None
    marked_text = json_format.ParseDict({"text": "x", "metadata": {URI: {}}}, Part())
    assert read_part(marked_text) is None


# --- Unknown and invalid ------------------------------------------------------------------------


def test_unknown_kind_reads_as_unknown() -> None:
    (provenance,) = [o for o in _objects("unknown-kind-ignored.json") if o["kind"] == "provenance"]
    assert read_part(_part(provenance)) == Unknown("provenance", provenance)


def test_invalid_r2c_part_is_a_skip_marker() -> None:
    bad = read_part(_part({"kind": "question", "id": "q-1"}))
    assert isinstance(bad, Invalid)
    assert bad.kind == "question"
    no_kind = read_part(_part({"id": "q-1"}))
    assert isinstance(no_kind, Invalid) and no_kind.kind is None


def test_read_parts_keeps_order_and_leaves_out_plain_parts() -> None:
    usage = {"kind": "usage", "input_tokens": 1}
    parts = [Part(text="Working."), _part(usage), _part({"kind": "provenance"}), _part({"kind": "answer"})]
    got = list(read_parts(parts))
    assert [type(x) for x in got] == [Usage, Unknown, Invalid]


# --- Artifacts ----------------------------------------------------------------------------------


@pytest.mark.parametrize("update_json", _artifact_updates())
def test_artifact_reads_and_encodes_back(update_json: dict[str, Any]) -> None:
    update = json_format.ParseDict(update_json, TaskArtifactUpdateEvent())
    meta, contents = read_artifact(update.artifact)
    marked = (update_json["artifact"].get("metadata") or {}).get(URI)
    assert meta == (parse(marked) if marked else None)
    kinds = [next(k for k in ("text", "raw", "url", "data") if k in p) for p in update_json["artifact"]["parts"]]
    assert len(contents) == len([k for k in kinds if k != "data"])
    if "data" in kinds:
        return  # a `data` Part is not core content; read_artifact leaves it out
    again = artifact_update(
        update.task_id, update.context_id, update.artifact.artifact_id, contents, meta=meta,
        name=update.artifact.name or None, description=update.artifact.description or None,
        append=update.append, last_chunk=update.last_chunk,
    )
    assert again == update


def test_content_kinds() -> None:
    meta = ArtifactMeta(presentation="file")
    contents = (
        TextContent("Three items."),
        TextContent("a,b", media_type="text/csv"),
        BytesContent(b"A-113 12\n", "text/plain", "low.txt"),
        UrlContent("https://files.example.com/r/x.csv", "text/csv", "x.csv"),
        UrlContent("https://remote.example.com/view", "text/html"),
    )
    update = artifact_update("t", "c", "a", contents, meta=meta)
    assert [json_format.MessageToDict(p) for p in update.artifact.parts] == [
        {"text": "Three items."},
        {"text": "a,b", "mediaType": "text/csv"},
        {"raw": "QS0xMTMgMTIK", "mediaType": "text/plain", "filename": "low.txt"},
        {"url": "https://files.example.com/r/x.csv", "mediaType": "text/csv", "filename": "x.csv"},
        {"url": "https://remote.example.com/view", "mediaType": "text/html"},
    ]
    assert read_artifact(update.artifact) == (meta, contents)


def test_artifact_without_meta_has_no_r2c_metadata() -> None:
    update = artifact_update("t", "c", "a", (TextContent("x"),), meta=None)
    assert URI not in update.artifact.metadata
    assert read_artifact(update.artifact) == (None, (TextContent("x"),))


def test_artifact_meta_of_another_kind_is_no_meta() -> None:
    artifact = json_format.ParseDict(
        {"artifactId": "a", "parts": [{"text": "x"}], "metadata": {URI: {"kind": "usage"}}}, Artifact()
    )
    assert read_artifact(artifact) == (None, (TextContent("x"),))
    broken = json_format.ParseDict(
        {"artifactId": "a", "parts": [{"text": "x"}], "metadata": {URI: {"kind": "artifact"}}}, Artifact()
    )
    assert read_artifact(broken) == (None, (TextContent("x"),))


def test_raw_without_media_type_is_octet_stream() -> None:
    artifact = Artifact(artifact_id="a", parts=[Part(raw=b"\x00\x01")])
    assert read_artifact(artifact) == (None, (BytesContent(b"\x00\x01", "application/octet-stream"),))


# --- Pending request and last usage -------------------------------------------------------------

QUESTION = Question.parse(_objects("question-one.json")[0])
QUESTION_2 = Question.parse(_objects("refuse-wrong-id.json")[0])
USAGE_1 = Usage(input_tokens=1800, output_tokens=120)
USAGE_2 = Usage(input_tokens=5200, output_tokens=940)


def _agent(*parts: Part, n: int = 0) -> Message:
    return Message(message_id=f"r-{n}", role=Role.ROLE_AGENT, parts=list(parts))


def _user(*parts: Part, n: int = 0) -> Message:
    return Message(message_id=f"c-{n}", role=Role.ROLE_USER, parts=list(parts))


def _task(state: TaskState.ValueType, message: Message | None, history: list[Message]) -> Task:
    status = TaskStatus(state=state, message=message) if message is not None else TaskStatus(state=state)
    return Task(id="task-1", context_id="ctx-1", status=status, history=history)


ASKED = _agent(Part(text="Which warehouse?"), r2c_part(QUESTION), r2c_part(USAGE_1), n=1)
INPUT_REQUIRED = TaskState.TASK_STATE_INPUT_REQUIRED


def test_pending_request_in_status_message() -> None:
    task = _task(INPUT_REQUIRED, ASKED, [_user(Part(text="Go."))])
    assert pending_request(task) == QUESTION


def test_pending_request_after_a_text_only_refusal() -> None:
    refusal = _agent(Part(text="No pending request has the id q-9."), n=2)
    wrong = _user(Part(text="x"), r2c_part(Answer(id="q-9", outcome="declined", answered_by={"role": "person"})), n=1)
    task = _task(INPUT_REQUIRED, refusal, [_user(Part(text="Go.")), ASKED, wrong])
    assert pending_request(task) == QUESTION


def test_no_pending_request_while_working() -> None:
    task = _task(TaskState.TASK_STATE_WORKING, _agent(Part(text="Reading.")), [ASKED])
    assert pending_request(task) is None
    assert pending_request(_task(INPUT_REQUIRED, None, [])) is None


def test_pending_request_is_the_newest() -> None:
    answer = Answer(id=QUESTION.id, outcome="answered", answered_by={"role": "person"}, value={"warehouse": "South"})
    asked_again = _agent(Part(text="Which month?"), r2c_part(QUESTION_2), r2c_part(USAGE_2), n=3)
    history = [_user(Part(text="Go.")), ASKED, _user(r2c_part(answer), n=1), _agent(Part(text="Reading."), n=2)]
    task = _task(INPUT_REQUIRED, asked_again, history)
    assert pending_request(task) == QUESTION_2
    assert last_usage(task) == USAGE_2


def test_a_request_from_the_user_is_never_pending() -> None:
    task = _task(INPUT_REQUIRED, _agent(Part(text="Waiting.")), [_user(r2c_part(QUESTION))])
    assert pending_request(task) is None


def test_last_usage() -> None:
    refusal = _agent(Part(text="Refused."), n=2)
    assert last_usage(_task(INPUT_REQUIRED, refusal, [ASKED])) == USAGE_1
    done = _agent(Part(text="Done."), r2c_part(USAGE_2), n=4)
    assert last_usage(_task(TaskState.TASK_STATE_COMPLETED, done, [ASKED])) == USAGE_2
    assert last_usage(_task(TaskState.TASK_STATE_WORKING, None, [])) is None


# --- answer_text ---------------------------------------------------------------------------------


def _pair(name: str) -> tuple[Any, Answer]:
    request, answer = (parse(o) for o in _objects(name)[:2])
    assert isinstance(answer, Answer)
    return request, answer


def test_answer_text_question_fields() -> None:
    request, answer = _pair("question-fields.json")
    assert answer_text(answer, request) == "Sections: Stock, Returns; Title: October stock; Threshold: 20; Charts: yes"


def test_answer_text_one() -> None:
    request, answer = _pair("question-one.json")
    assert answer_text(answer, request) == "Warehouse: East annex"


def test_answer_text_approvals() -> None:
    deny_request, deny = _pair("approval-operation-deny.json")
    assert answer_text(deny, deny_request) == "Deny: Keep them until the audit is done."
    plain_deny = Answer(id="ap-1", outcome="answered", answered_by={"role": "person"}, value={"decision": "deny"})
    assert answer_text(plain_deny, deny_request) == "Deny"
    allow = Answer(id="ap-1", outcome="answered", answered_by={"role": "person"}, value={"decision": "allow"})
    assert answer_text(allow, deny_request) == "Allow"
    edit_request, edit = _pair("approval-four-eyes-edit.json")
    assert answer_text(edit, edit_request) == 'Edited: {"item": "A-113", "quantity": 300, "supplier": "S-7"}'


def test_answer_text_declined() -> None:
    request, answer = _pair("answer-declined.json")
    assert answer_text(answer, request) == "Declined"


# --- text_answer (R9) ---------------------------------------------------------------------------


def _question(field: dict[str, Any], *more: dict[str, Any]) -> Question:
    return Question.parse({
        "kind": "question", "id": "q-1", "title": "T", "answer_by": {"role": "person"},
        "fields": [field, *more],
    })


ONE_CLOSED = {"key": "w", "header": "W", "text": "Which?", "type": "one", "other": False,
              "options": [{"label": "North"}, {"label": "South"}]}
ONE_OPEN = {**ONE_CLOSED, "other": True}
TEXT = {"key": "m", "header": "M", "text": "Which month?", "type": "text"}
BOOL = {"key": "c", "header": "C", "text": "Charts?", "type": "bool"}


def _value(request: Question, text: str) -> Any:
    answer = text_answer(request, text)
    assert answer is not None
    assert answer.id == "q-1" and answer.outcome == "answered" and answer.answered_by.role == "person"
    assert answer.value is not None
    return answer.value


def test_text_answer_accepted() -> None:
    assert _value(_question(ONE_CLOSED), "South") == {"w": "South"}
    assert _value(_question(ONE_CLOSED), "  south ") == {"w": "South"}
    assert _value(_question(ONE_OPEN), "East annex") == {"w": "East annex"}
    assert _value(_question(TEXT), " 2026-10 ") == {"m": "2026-10"}


def test_text_answer_refused() -> None:
    assert text_answer(_question(ONE_CLOSED), "East annex") is None
    assert text_answer(_question(BOOL), "yes") is None
    assert text_answer(_question(TEXT, BOOL), "2026-10") is None
    assert text_answer(_question(TEXT), "   ") is None
    approval, _ = _pair("approval-operation-deny.json")
    assert isinstance(approval, Approval)
    assert text_answer(approval, "allow") is None


def test_the_test_file_is_found(standard_dir: Path) -> None:
    assert (standard_dir / "examples" / "a2a" / "question-one.json").is_file()
