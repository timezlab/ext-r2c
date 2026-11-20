"""The codec between R2C objects and the MCP wire (spec 004, phase 2).

Every R2C object in `standard/v1/examples/mcp/` reads to its core model and encodes back to the
same JSON; input-required results, progress notifications and content blocks built by the codec
equal the examples' (research R7–R9, contracts/wire-mapping.md). Numbers are compared after
`_ints`: the SDK's models hold `progress` as a float, so `1` and `1.0` are the same value.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest
from ext_r2c import MCP_KEY
from ext_r2c.core import (
    Activity,
    Answer,
    Approval,
    ArtifactEvent,
    ArtifactMeta,
    BytesContent,
    Field,
    Option,
    Origin,
    Question,
    TextContent,
    UrlContent,
    Usage,
    answer_from_mcp,
    parse,
    to_json,
)
from ext_r2c.mcp._codec import (
    content_blocks,
    final_result,
    input_required,
    mcp_response,
    message,
    progress_params,
    read_block,
    read_input_required,
    read_progress,
    read_result,
)
from r2c_check import example_files, load_json
from test_forms import DERIVED

EXAMPLES = example_files("mcp")
CORRECTED = {"elicitation-approval.json", "elicitation-approval-edit-dropped.json"}  # O5, until T083


def _ints(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _ints(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ints(v) for v in value]
    return value


def _wire(model: Any) -> dict[str, Any]:
    data = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return _ints(data)  # type: ignore[no-any-return]


def _remote(path: Path) -> list[dict[str, Any]]:
    return [s["body"] for s in load_json(path)["steps"] if s["from"] == "remote"]


def _results(path: Path, kind: str) -> list[dict[str, Any]]:
    return [b["result"] for b in _remote(path) if b.get("result", {}).get("resultType") == kind]


def _progress(path: Path) -> list[dict[str, Any]]:
    return [b["params"] for b in _remote(path) if b.get("method") == "notifications/progress"]


def _id(path: Path) -> str:
    return path.name


# --- Decoding ------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", EXAMPLES, ids=_id)
def test_every_r2c_object_reads_and_writes_back(path: Path) -> None:
    for result in _results(path, "input_required"):
        asked = read_input_required(result)
        wanted = (result.get("_meta") or {}).get(MCP_KEY, {}).get("input_requests", {})
        assert [p.key for p in asked.requests] == list(result["inputRequests"])
        for pending in asked.requests:
            if pending.key in wanted:
                assert pending.request is not None and to_json(pending.request) == wanted[pending.key]
            else:
                assert pending.request is None
            params = result["inputRequests"][pending.key]["params"]
            assert pending.message == params["message"]
            assert pending.requested_schema == params["requestedSchema"]
    for params in _progress(path):
        activity, text, _progress_value, skipped = read_progress(params)
        meta = (params.get("_meta") or {}).get(MCP_KEY)
        assert skipped == 0
        assert (to_json(activity) if activity else None) == meta
        assert text == params.get("message")
    for result in _results(path, "complete"):
        read = read_result(result)
        assert read.skipped == 0
        meta = (result.get("_meta") or {}).get(MCP_KEY)
        assert (to_json(read.usage) if read.usage else None) == meta
        for item in read.artifacts:
            block_meta = (item.block.get("_meta") or {}).get(MCP_KEY)
            assert (to_json(item.meta) if item.meta else None) == block_meta


def test_input_required_reads_the_request_and_usage() -> None:
    path = next(p for p in EXAMPLES if p.name == "elicitation-question.json")
    asked = read_input_required(_results(path, "input_required")[0])
    (pending,) = asked.requests
    assert pending.key == "q-2" and isinstance(pending.request, Question) and pending.url is None
    assert asked.usage is None and asked.skipped == 0


def test_not_activated_input_required_has_no_request() -> None:
    path = next(p for p in EXAMPLES if p.name == "not-activated.json")
    (pending,) = read_input_required(_results(path, "input_required")[0]).requests
    assert pending.request is None and pending.message == "Which warehouse should the report cover?"


def test_tool_result_reads_reply_artifacts_and_usage() -> None:
    path = next(p for p in EXAMPLES if p.name == "tool-result.json")
    read = read_result(_results(path, "complete")[0])
    assert read.reply == "The October report is ready: 412 items, 3 below their reorder level."
    assert [(a.presentation, a.uri, a.media_type, a.name) for a in read.artifacts] == [
        ("file", "https://files.example.com/r/inventory-2026-10.csv", "text/csv", "inventory-2026-10.csv"),
        ("file", "https://files.example.com/r/below-threshold.txt", "text/plain", None),
        ("live", "https://remote.example.com/live/report-2026-10", "text/html", "Stock dashboard"),
    ]
    assert read.usage is not None and read.usage.input_tokens == 5200
    assert read.is_error is False and read.structured is None


def test_reply_is_guessed_without_r2c_meta() -> None:
    read = read_result({"resultType": "complete", "content": [
        {"type": "text", "text": "Done."}, {"type": "text", "text": "More."},
        {"type": "resource_link", "uri": "https://x.example.com/a.html", "name": "a", "mimeType": "text/html"},
        {"type": "resource_link", "uri": "https://x.example.com/a.csv", "name": "a", "mimeType": "text/csv"},
        {"type": "image", "data": "AA==", "mimeType": "image/png"},
    ]})
    assert read.reply == "Done."
    assert [(a.meta, a.presentation) for a in read.artifacts] == [
        (None, "inline"), (None, "link"), (None, "file"), (None, "inline")]


def test_unknown_and_invalid_objects_are_skipped() -> None:
    read = read_result({"resultType": "complete", "content": [
        {"type": "text", "text": "x", "_meta": {MCP_KEY: {"kind": "future-kind"}}},
        {"type": "text", "text": "y", "_meta": {MCP_KEY: {"kind": "artifact", "presentation": "nowhere"}}},
    ], "_meta": {MCP_KEY: {"kind": "usage", "input_tokens": "many"}}})
    assert read.skipped == 3 and read.usage is None
    activity, _, _, skipped = read_progress({"progressToken": 1, "progress": 1, "message": "m",
                                             "_meta": {MCP_KEY: {"kind": "activity", "id": "a", "label": "l"}}})
    assert activity is None and skipped == 1


# --- Encoding ------------------------------------------------------------------------------------


def _asked(path: Path) -> list[tuple[dict[str, Any], Question | Approval]]:
    out = []
    for result in _results(path, "input_required"):
        meta = (result.get("_meta") or {}).get(MCP_KEY)
        if meta is None:
            continue
        for obj in meta["input_requests"].values():
            request = parse(obj)
            assert isinstance(request, (Question, Approval))
            out.append((result, request))
    return out


ASKING = [p for p in EXAMPLES if _asked(p)]


@pytest.mark.parametrize("path", ASKING, ids=_id)
def test_input_required_equals_the_example(path: Path) -> None:
    if path.name in CORRECTED:
        pytest.xfail("the approval messages are corrected to the message rule in phase 8 (O5)")
    for result, request in _asked(path):
        built = _wire(input_required(request, result["requestState"], active=True, usage=None))
        assert built == _ints(result)


def test_input_required_without_activation_has_no_meta() -> None:
    _, request = _asked(next(p for p in EXAMPLES if p.name == "elicitation-question-other.json"))[0]
    built = _wire(input_required(request, "s", active=False, usage=None))
    assert "_meta" not in built and built["inputRequests"]["q-1"]["params"]["message"] == request.title


def test_usage_sits_beside_input_requests() -> None:
    _, request = _asked(next(p for p in EXAMPLES if p.name == "elicitation-question-other.json"))[0]
    usage = Usage(input_tokens=10, output_tokens=2)
    built = _wire(input_required(request, "s", active=True, usage=usage))
    assert built["_meta"][MCP_KEY] == {"input_requests": {"q-1": to_json(request)}, "usage": to_json(usage)}
    asked = read_input_required(built)
    assert asked.usage == usage


def _question(**extra: Any) -> Question:
    field = Field(key="w", header="Warehouse", text="Which warehouse?", type="one",
                  options=[Option(label="North"), Option(label="South")])
    return Question(id="q-1", title="Report settings", answer_by={"role": "person"}, fields=[field], **extra)


def test_message_rule() -> None:
    assert message(_question()) == "Report settings"
    assert message(_question(description="For October.")) == "Report settings\nFor October."
    origin = Origin(name="Inventory agent", url="https://inventory.example.com/")
    assert message(_question(origin=origin)) == "Inventory agent asks: Report settings"
    again = _question(errors=[{"key": "w", "message": "This is needed."}, {"message": "Try again."}])
    assert message(again) == "Report settings\nThis is needed.\nTry again."
    assert message(_question(), refusal="The response came too late; the request had expired.") == (
        "The response came too late; the request had expired.\nReport settings")


def test_progress_notification() -> None:
    path = next(p for p in EXAMPLES if p.name == "progress-activity.json")
    for n, params in enumerate(_progress(path), start=1):
        activity = parse(params["_meta"][MCP_KEY])
        assert isinstance(activity, Activity)
        assert _wire(progress_params(activity, "pt-1", n, active=True)) == params
        plain = _wire(progress_params(activity, "pt-1", n, active=False))
        assert "_meta" not in plain and plain["message"] == activity.label


# --- Content blocks ------------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n-invented-"


def _event(presentation: str, content: Any, **kw: Any) -> ArtifactEvent:
    return ArtifactEvent("a-1", ArtifactMeta(presentation=presentation), (content,), **kw)  # type: ignore[arg-type]


BLOCKS = [
    ("file-url", _event("file", UrlContent("https://files.example.com/r/x.csv", "text/csv", "x.csv")),
     {"type": "resource_link", "uri": "https://files.example.com/r/x.csv", "name": "x.csv", "mimeType": "text/csv"}),
    ("file-bytes", _event("file", BytesContent(b"abc", "application/pdf", "x.pdf")),
     {"type": "resource", "resource": {"uri": "urn:r2c:artifact:a-1", "mimeType": "application/pdf",
                                       "blob": base64.b64encode(b"abc").decode()}}),
    ("file-text", _event("file", TextContent("A 1\n", "text/plain")),
     {"type": "resource", "resource": {"uri": "urn:r2c:artifact:a-1", "mimeType": "text/plain", "text": "A 1\n"}}),
    ("inline-text", _event("inline", TextContent("Twelve items.")), {"type": "text", "text": "Twelve items."}),
    ("inline-image", _event("inline", BytesContent(PNG, "image/png")),
     {"type": "image", "data": base64.b64encode(PNG).decode(), "mimeType": "image/png"}),
    ("inline-audio", _event("inline", BytesContent(b"ID3", "audio/mpeg")),
     {"type": "audio", "data": base64.b64encode(b"ID3").decode(), "mimeType": "audio/mpeg"}),
    ("inline-bytes", _event("inline", BytesContent(b"{}", "application/json")),
     {"type": "resource", "resource": {"uri": "urn:r2c:artifact:a-1", "mimeType": "application/json",
                                       "blob": base64.b64encode(b"{}").decode()}}),
    ("live", _event("live", UrlContent("https://remote.example.com/live/1", "text/html"), name="Stock dashboard"),
     {"type": "resource_link", "uri": "https://remote.example.com/live/1", "name": "Stock dashboard",
      "mimeType": "text/html"}),
]


@pytest.mark.parametrize(("event", "block"), [(e, b) for _, e, b in BLOCKS], ids=[n for n, _, _ in BLOCKS])
def test_content_blocks(event: ArtifactEvent, block: dict[str, Any]) -> None:
    (plain,) = content_blocks(event, active=False)
    assert _wire(plain) == block
    (marked,) = content_blocks(event, active=True)
    assert _wire(marked) == {**block, "_meta": {MCP_KEY: to_json(event.meta)}}
    read = read_block(_wire(marked))
    assert read.meta == event.meta and read.presentation == event.meta.presentation


def test_final_result_of_tool_result_json() -> None:
    path = next(p for p in EXAMPLES if p.name == "tool-result.json")
    wanted = _results(path, "complete")[0]
    events = [
        _event("file", UrlContent("https://files.example.com/r/inventory-2026-10.csv", "text/csv",
                                  "inventory-2026-10.csv")),
        ArtifactEvent("below", ArtifactMeta(presentation="file"), (TextContent("A-113 12\nB-201 8\nC-047 19\n"),)),
        _event("live", UrlContent("https://remote.example.com/live/report-2026-10", "text/html"),
               name="Stock dashboard"),
    ]
    usage = parse(wanted["_meta"][MCP_KEY])
    assert isinstance(usage, Usage)
    blocks = [b for e in events for b in content_blocks(e, active=True)]
    built = _wire(final_result(reply=wanted["content"][0]["text"], blocks=blocks, usage=usage, active=True))
    assert built["content"][0] == wanted["content"][0]
    assert built["content"][1] == wanted["content"][1] and built["content"][3] == wanted["content"][3]
    assert built["_meta"] == wanted["_meta"] and built["isError"] is False
    plain = _wire(final_result(reply="Done.", blocks=blocks, usage=usage, active=False))
    assert "_meta" not in plain and all("_meta" not in b for b in plain["content"])


def test_final_result_refusal_error_and_structured() -> None:
    built = _wire(final_result(refusal="The response came too late; the request had expired.", reply="Done.",
                               blocks=[], usage=None, active=True, is_error=True, structured={"context_id": "c"}))
    assert [b["text"] for b in built["content"]] == ["The response came too late; the request had expired.", "Done."]
    assert "_meta" not in built["content"][0] and built["isError"] is True
    assert built["structuredContent"] == {"context_id": "c"}


# --- Answer → elicitation response ---------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(DERIVED))
def test_mcp_response_inverts_answer_from_mcp(name: str) -> None:
    path = next(p for p in EXAMPLES if p.name == name)
    _, request = _asked(path)[0]
    answer = parse(DERIVED[name])
    assert isinstance(answer, Answer)
    response = mcp_response(request, answer)
    assert answer_from_mcp(request, response.action, response.content) == answer


def test_mcp_response_cases() -> None:
    q = _question()
    other = Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={"w": "East annex"})
    assert mcp_response(q, other).content == {"w_other": "East annex"}
    listed = Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={"w": "North"})
    assert mcp_response(q, listed).content == {"w": "North"}
    declined = Answer(id="q-1", outcome="declined", answered_by={"role": "person"})
    assert mcp_response(q, declined).action == "decline" and mcp_response(q, declined).content is None
