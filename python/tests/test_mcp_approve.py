"""Approval before a direct tool call over MCP (spec 004, story 2, research R2, R3).

A counting tool behind `approve=`: it never runs before an `allow` or `edit`, runs exactly once
after one, and a replayed round never runs it again.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import mcp_types as types
from ext_r2c import MCP_KEY
from ext_r2c.core import (
    ArtifactEvent,
    ArtifactMeta,
    UrlContent,
    Usage,
    parse,
    to_json,
    tool_from_function,
)
from ext_r2c.mcp import Approve, R2CExtension, SourceTool, ToolOutput, mcp_server
from ext_r2c.mcp.source_tool import DEFAULT_SCHEMA

from fake_sources import LiveFake
from mcp_harness import accept, call, dump, mcp_client, refuse, run, serve, texts

ARGS = {"item": "A-113", "quantity": 500, "supplier": "S-7"}
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


class Counted:
    """`place_order` as a ToolSpec, with every call it received in `calls`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

        def place_order(item: str, quantity: int, supplier: Literal["S-7", "S-9"] = "S-7") -> str:
            """Place an order with a supplier."""
            self.calls.append({"item": item, "quantity": quantity, "supplier": supplier})
            return f"Ordered {quantity} of {item}."

        self.spec = tool_from_function(place_order)


def _server(*tools: Any, approve: Any = None, **kwargs: Any) -> Any:
    return mcp_server("test", R2CExtension(tools=list(tools), approve=approve or {}, **kwargs))


def _asked(result: Any) -> tuple[str, Any, dict[str, Any]]:
    """(key, the R2C approval, the requested schema) of an input-required result."""
    assert isinstance(result, types.InputRequiredResult)
    wire = dump(result)
    (key,) = wire["inputRequests"]
    return key, parse(wire["_meta"][MCP_KEY]["input_requests"][key]), wire["inputRequests"][key]["params"]["requestedSchema"]


def test_ask() -> None:
    tool = Counted()

    async def main() -> None:
        async with serve(_server(tool.spec, approve={"place_order": True})) as served, mcp_client(served) as client:
            first = await call(client, "place_order", ARGS)
        key, approval, schema = _asked(first)
        assert key == approval.id and approval.id.startswith("ap-")
        assert approval.title == "Run place_order"
        assert approval.answer_by.role == "person"
        assert approval.subject.name == "place_order" and approval.subject.args == ARGS
        assert approval.subject.args_schema == tool.spec.input_schema
        assert approval.decisions == ["allow", "edit", "deny"]
        assert list(schema["properties"]) == ["decision", "reason", "item", "quantity", "supplier"]
        assert {k: schema["properties"][k]["default"] for k in ARGS} == ARGS
        assert tool.calls == []

    run(main())


def test_allow_runs_once() -> None:
    tool = Counted()

    async def main() -> None:
        async with serve(_server(tool.spec, approve={"place_order": True})) as served, mcp_client(served) as client:
            first = await call(client, "place_order", ARGS)
            key, _, _ = _asked(first)
            done = await call(client, "place_order", ARGS, state=first.request_state,
                              responses=accept(key, decision="allow"))
        assert isinstance(done, types.CallToolResult) and not done.is_error
        assert tool.calls == [ARGS]
        assert texts(done) == ["Ordered 500 of A-113."]

    run(main())


def test_edit_runs_with_the_edited_arguments() -> None:
    tool = Counted()

    async def main() -> None:
        async with serve(_server(tool.spec, approve={"place_order": True})) as served, mcp_client(served) as client:
            first = await call(client, "place_order", ARGS)
            key, _, _ = _asked(first)
            bad = await call(client, "place_order", ARGS, state=first.request_state,
                             responses=accept(key, decision="edit", item="A-113", quantity="lots", supplier="S-7"))
            again_key, again, _ = _asked(bad)
            assert again_key == key and again.id == key
            assert [e.key for e in again.errors or []] == ["quantity"]
            assert tool.calls == []
            done = await call(client, "place_order", ARGS, state=bad.request_state,
                              responses=accept(key, decision="edit", item="A-113", quantity=300, supplier="S-7"))
        assert not done.is_error
        assert tool.calls == [{"item": "A-113", "quantity": 300, "supplier": "S-7"}]

    run(main())


def test_deny_and_decline_do_not_run() -> None:
    tool = Counted()

    async def main() -> None:
        async with serve(_server(tool.spec, approve={"place_order": True})) as served, mcp_client(served) as client:
            first = await call(client, "place_order", ARGS)
            key, _, _ = _asked(first)
            denied = await call(client, "place_order", ARGS, state=first.request_state,
                                responses=accept(key, decision="deny", reason="Too many."))
            second = await call(client, "place_order", ARGS)
            key2, _, _ = _asked(second)
            declined = await call(client, "place_order", ARGS, state=second.request_state, responses=refuse(key2))
        assert denied.is_error and texts(denied) == ["Not run: denied. Reason: Too many."]
        assert declined.is_error and texts(declined) == ["Not run: denied."]
        assert tool.calls == []

    run(main())


def test_edit_dropped_for_nested_args() -> None:
    def place_lines(supplier: str, lines: list[dict[str, int]]) -> str:
        """Place an order of several lines."""
        return "Ordered."

    async def main() -> None:
        spec = tool_from_function(place_lines)
        async with serve(_server(spec, approve={"place_lines": True})) as served, mcp_client(served) as client:
            first = await call(client, "place_lines", {"supplier": "S-7", "lines": [{"A-113": 300}]})
        _, approval, schema = _asked(first)
        assert approval.decisions == ["allow", "deny"]
        assert list(schema["properties"]) == ["decision", "reason"]

    run(main())


def test_approver_and_expiry_from_settings() -> None:
    tool = Counted()
    settings = Approve(answer_by="approver", expires_in=timedelta(minutes=5), title="Place the order")

    async def main() -> None:
        server = _server(tool.spec, approve={"place_order": settings}, clock=lambda: NOW)
        async with serve(server) as served, mcp_client(served) as client:
            first = await call(client, "place_order", ARGS)
            key, approval, _ = _asked(first)
            done = await call(client, "place_order", ARGS, state=first.request_state,
                              responses=accept(key, decision="allow"))
        assert approval.answer_by.role == "approver" and approval.title == "Place the order"
        assert approval.expires() == NOW + timedelta(minutes=5)
        assert not done.is_error and tool.calls == [ARGS]

    run(main())


def test_tool_without_approval_runs_at_once() -> None:
    usage = Usage(input_tokens=12, output_tokens=3)

    def report(month: str) -> ToolOutput:
        """The monthly report."""
        csv = ArtifactEvent("f-1", ArtifactMeta(presentation="file"),
                            (UrlContent(f"https://files.example.com/r/{month}.csv", "text/csv"),))
        return ToolOutput(text="Report ready.", artifacts=(csv,), usage=usage)

    async def main() -> None:
        async with serve(_server(tool_from_function(report))) as served, mcp_client(served) as client:
            done = await call(client, "report", {"month": "2026-10"})
        wire = dump(done)
        assert wire["content"] == [
            {"type": "text", "text": "Report ready.",
             "_meta": {MCP_KEY: {"kind": "artifact", "presentation": "inline", "response": True}}},
            {"type": "resource_link", "uri": "https://files.example.com/r/2026-10.csv", "name": "2026-10.csv",
             "mimeType": "text/csv", "_meta": {MCP_KEY: {"kind": "artifact", "presentation": "file"}}},
        ]
        assert wire["_meta"][MCP_KEY] == to_json(usage)

    run(main())


def test_tool_registered_elsewhere() -> None:
    notes: list[str] = []

    async def main() -> None:
        server = _server(approve={"ping": True})

        @server.tool()
        def ping(note: str) -> str:
            """Ping with a note."""
            notes.append(note)
            return f"pong {note}"

        async with serve(server) as served, mcp_client(served) as client:
            first = await call(client, "ping", {"note": "hi"})
            key, approval, schema = _asked(first)
            assert approval.decisions == ["allow", "deny"] and approval.subject.args == {"note": "hi"}
            assert list(schema["properties"]) == ["decision", "reason"]
            assert notes == []
            done = await call(client, "ping", {"note": "hi"}, state=first.request_state,
                              responses=accept(key, decision="allow"))
        assert notes == ["hi"]
        assert texts(done) == ["pong hi"]

    run(main())


def test_replayed_round_does_not_run_again() -> None:
    tool = Counted()

    async def main() -> None:
        async with serve(_server(tool.spec, approve={"place_order": True})) as served, mcp_client(served) as client:
            first = await call(client, "place_order", ARGS)
            key, _, _ = _asked(first)
            allow = accept(key, decision="allow")
            done = await call(client, "place_order", ARGS, state=first.request_state, responses=allow)
            again = await call(client, "place_order", ARGS, state=first.request_state, responses=allow)
        assert not done.is_error
        assert again.is_error and texts(again) == ["This request was already answered."]
        assert len(tool.calls) == 1

    run(main())


def test_replayed_source_round_is_refused() -> None:
    source = LiveFake()
    args = {"message": "Write the report", "context_id": "ctx-1"}

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", args)
            answer = accept("q-1", title="T")
            await call(client, "agent", args, state=first.request_state, responses=answer)
            again = await call(client, "agent", args, state=first.request_state, responses=answer)
        assert again.is_error and texts(again) == ["This request was already answered."]
        assert len(source.answers) == 1

    run(main())


def test_listed_schema() -> None:
    tool = Counted()

    async def main() -> None:
        async with serve(_server(tool.spec, SourceTool(LiveFake()))) as served, mcp_client(served) as client:
            listed = await client.session.list_tools()
        schemas = {t.name: t.input_schema for t in listed.tools}
        assert schemas == {"place_order": tool.spec.input_schema, "agent": DEFAULT_SCHEMA}

    run(main())


def test_return_values() -> None:
    def as_text() -> str:
        """Text."""
        return "plain"

    def as_json() -> dict[str, Any]:
        """JSON."""
        return {"count": 3}

    def as_output() -> ToolOutput:
        """Output."""
        return ToolOutput(text="With data.", data={"rows": 2})

    def needs(n: int) -> str:
        """Needs a number."""
        return str(n)

    def breaks() -> str:
        """Breaks."""
        raise RuntimeError("the tool broke")

    async def main() -> None:
        specs = [tool_from_function(f) for f in (as_text, as_json, as_output, needs, breaks)]
        async with serve(_server(*specs)) as served, mcp_client(served) as client:
            text = await call(client, "as_text")
            data = await call(client, "as_json")
            output = await call(client, "as_output")
            invalid = await call(client, "needs", {"n": "x"})
            broken = await call(client, "breaks")
        assert texts(text) == ["plain"] and text.structured_content is None
        assert data.structured_content == {"count": 3} and json.loads(texts(data)[0]) == {"count": 3}
        assert texts(output) == ["With data."] and output.structured_content == {"rows": 2}
        assert invalid.is_error and "invalid arguments" in texts(invalid)[0]
        assert broken.is_error and texts(broken) == ["the tool broke"]

    run(main())
