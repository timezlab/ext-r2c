"""The checks themselves must be able to fail: each broken envelope is rejected, its fix passes."""

import copy
from typing import Any

import pytest

from r2c_check import (
    MCP_KEY,
    MCP_VERSION,
    URI,
    EnvelopeError,
    check_a2a,
    check_mcp,
    find_r2c_objects,
    parse_rules,
    unknown_kinds,
)

# --- A2A ---------------------------------------------------------------------------------------

STATUS: dict[str, Any] = {
    "statusUpdate": {
        "taskId": "task-1",
        "contextId": "ctx-1",
        "status": {
            "state": "TASK_STATE_INPUT_REQUIRED",
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_AGENT",
                "parts": [
                    {"text": "Publish the page? allow | deny"},
                    {"data": {"kind": "approval", "id": "ap-1"}, "metadata": {URI: {}}},
                ],
            },
        },
    }
}

CARD: dict[str, Any] = {
    "name": "report-service",
    "description": "Builds monthly reports",
    "version": "1.0.0",
    "supportedInterfaces": [
        {"url": "https://remote.example.com/", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ],
    "capabilities": {"streaming": True, "extensions": [{"uri": URI, "required": False}]},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "build-report", "name": "Build a report", "description": "Monthly report", "tags": ["report"]}],
}


def test_a2a_valid_status_and_card_pass() -> None:
    check_a2a("StreamResponse", STATUS)
    check_a2a("AgentCard", CARD)


@pytest.mark.parametrize(
    ("label", "mutate", "type_name", "base"),
    [
        ("misspelled field", lambda b: b["statusUpdate"]["status"].__setitem__(
            "messsage", b["statusUpdate"]["status"].pop("message")), "StreamResponse", STATUS),
        ("wrong enum", lambda b: b["statusUpdate"]["status"].__setitem__("state", "INPUT_REQUIRED"),
         "StreamResponse", STATUS),
        ("missing messageId", lambda b: b["statusUpdate"]["status"]["message"].pop("messageId"),
         "StreamResponse", STATUS),
        ("card without skills", lambda b: b.__setitem__("skills", []), "AgentCard", CARD),
    ],
)
def test_a2a_broken_envelope_is_rejected(label: str, mutate: Any, type_name: str, base: Any) -> None:
    body = copy.deepcopy(base)
    mutate(body)
    with pytest.raises(EnvelopeError):
        check_a2a(type_name, body)


def test_a2a_unknown_type_is_rejected() -> None:
    with pytest.raises(EnvelopeError):
        check_a2a("Nope", {})


# --- MCP ---------------------------------------------------------------------------------------

REQUEST_META = {
    "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {"elicitation": {"form": {}}, "extensions": {MCP_KEY: {}}},
}

INPUT_REQUIRED: dict[str, Any] = {
    "result": {
        "resultType": "input_required",
        "inputRequests": {
            "ap-1": {
                "method": "elicitation/create",
                "params": {
                    "mode": "form",
                    "message": "Publish the page?",
                    "requestedSchema": {
                        "type": "object",
                        "properties": {"decision": {"type": "string", "enum": ["allow", "deny"]}},
                        "required": ["decision"],
                    },
                },
            }
        },
        "requestState": "sealed-state",
        "_meta": {MCP_KEY: {"input_requests": {"ap-1": {"kind": "approval", "id": "ap-1"}}}},
    },
    "jsonrpc": "2.0",
    "id": 1,
}

TOOL_RESULT: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 2,
    "result": {"resultType": "complete", "content": [{"type": "text", "text": "Done"}]},
}

DISCOVER: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 0,
    "result": {
        "resultType": "complete",
        "supportedVersions": [MCP_VERSION],
        "capabilities": {"tools": {}, "extensions": {MCP_KEY: {}}},
        "cacheScope": "public",
        "ttlMs": 60000,
    },
}

CALL: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "publish_page", "arguments": {"page_id": "notes-4-2"}, "_meta": REQUEST_META},
}

PROGRESS: dict[str, Any] = {
    "jsonrpc": "2.0",
    "method": "notifications/progress",
    "params": {"progressToken": "pt-1", "progress": 1, "message": "Reading the data"},
}


def step(kind: str, body: Any, method: str | None = None) -> dict[str, Any]:
    s = {"from": "remote", "type": kind, "body": body}
    if method:
        s["method"] = method
    return s


def test_mcp_valid_envelopes_pass() -> None:
    check_mcp(step("result", INPUT_REQUIRED, "tools/call"))
    check_mcp(step("result", TOOL_RESULT, "tools/call"))
    check_mcp(step("discover", DISCOVER))
    check_mcp(step("request", CALL))
    check_mcp(step("notification", PROGRESS))


def _broken(base: Any, mutate: Any) -> Any:
    body = copy.deepcopy(base)
    mutate(body)
    return body


@pytest.mark.parametrize(
    ("label", "s"),
    [
        ("misspelled inputRequests", step("result", _broken(
            INPUT_REQUIRED, lambda b: b["result"].__setitem__("inputRequest", b["result"].pop("inputRequests"))),
            "tools/call")),
        ("tool result without resultType", step("result", _broken(
            TOOL_RESULT, lambda b: b["result"].pop("resultType")), "tools/call")),
        ("discover without cacheScope", step("discover", _broken(DISCOVER, lambda b: b["result"].pop("cacheScope")))),
        ("discover without ttlMs", step("discover", _broken(DISCOVER, lambda b: b["result"].pop("ttlMs")))),
        ("request without clientCapabilities", step("request", _broken(
            CALL, lambda b: b["params"]["_meta"].pop("io.modelcontextprotocol/clientCapabilities")))),
        ("nested requestedSchema property", step("result", _broken(
            INPUT_REQUIRED, lambda b: b["result"]["inputRequests"]["ap-1"]["params"]["requestedSchema"][
                "properties"].__setitem__("args", {"type": "object", "properties": {"x": {"type": "string"}}})),
            "tools/call")),
        ("result step without method", step("result", TOOL_RESULT)),
        ("unknown step type", step("event", TOOL_RESULT)),
    ],
)
def test_mcp_broken_envelope_is_rejected(label: str, s: Any) -> None:
    with pytest.raises(EnvelopeError):
        check_mcp(s)


# --- Finding R2C objects -----------------------------------------------------------------------


def test_find_a2a_part_and_annotation_forms() -> None:
    artifact = {"artifactId": "a-1", "parts": [{"text": "hi"}],
                "metadata": {URI: {"kind": "artifact", "presentation": "inline"}}}
    found = dict(find_r2c_objects("a2a", {"status": STATUS, "artifact": artifact}))
    kinds = sorted(o["kind"] for o in found.values())
    assert kinds == ["approval", "artifact"]


def test_find_mcp_input_requests_form_and_key_check() -> None:
    found = list(find_r2c_objects("mcp", INPUT_REQUIRED))
    assert [o["id"] for _, o in found] == ["ap-1"]
    stray = _broken(INPUT_REQUIRED, lambda b: b["result"]["_meta"][MCP_KEY]["input_requests"].__setitem__(
        "q-9", {"kind": "question"}))
    with pytest.raises(EnvelopeError):
        list(find_r2c_objects("mcp", stray))


def test_unknown_kinds_lists_only_kinds_without_a_schema() -> None:
    example = {"binding": "a2a", "steps": [{"body": {"parts": [
        {"data": {"kind": "provenance", "source": "x"}, "metadata": {URI: {}}},
        {"data": {"kind": "usage", "input_tokens": 1}, "metadata": {URI: {}}},
    ]}}]}
    assert unknown_kinds(example, {"usage"}) == [("/steps/0/body/parts/0/data", "provenance")]


# --- Rules -------------------------------------------------------------------------------------


def test_parse_rules_reads_tag_lines() -> None:
    text = "- **R2C-CORE-1** · MUST · both · wire\n  Text.\n- **R2C-APPROVAL-2** · MUST NOT · client · wire · schema\n"
    rules = parse_rules(text)
    assert rules["R2C-APPROVAL-2"].schema and rules["R2C-APPROVAL-2"].wire
    assert rules["R2C-CORE-1"].party == "both" and not rules["R2C-CORE-1"].schema


def test_parse_rules_accepts_an_area_with_a_digit() -> None:
    rules = parse_rules("- **R2C-A2A-1** · MUST · remote · wire\n")
    assert "R2C-A2A-1" in rules


@pytest.mark.parametrize(
    "text",
    [
        "- **R2C-CORE-1** · MUST · both · wire\n- **R2C-CORE-1** · MAY · remote · prose\n",  # duplicate
        "- **R2C-CORE-1** · MUSTN'T · both · wire\n",                                      # bad level
        "- **R2C-CORE-1** MUST both wire\n",                                               # no separators
    ],
)
def test_parse_rules_rejects_bad_lines(text: str) -> None:
    with pytest.raises(ValueError):
        parse_rules(text)
