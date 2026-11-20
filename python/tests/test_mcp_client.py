"""The caller's MCP client: typed items, checked answers, fetch from the connection's origin only
(spec 004, story 6, research R13, R14, SC-009).

Every round trip runs against a real `MCPServer` on the streaming in-process transport, driven
only through `R2CClient`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx2
import mcp_types as types
import pytest
from ext_r2c import MCP_KEY
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Answer,
    AnsweredBy,
    ArtifactEvent,
    ArtifactMeta,
    Ask,
    BytesContent,
    Limits,
    ReplyChunk,
    UrlContent,
    Usage,
    UsageEvent,
    parse,
)
from ext_r2c.mcp import (
    ActivityItem,
    AnswerRejected,
    Approve,
    ArtifactItem,
    Link,
    ProgressItem,
    R2CClient,
    R2CExtension,
    ReplyItem,
    RequestItem,
    ResultItem,
    SourceTool,
    TooLarge,
    UsageItem,
    mcp_server,
)
from mcp.server.extension import Extension, ToolBinding
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.request_state import RequestStateSecurity
from mcp_transport import Record, StreamingASGITransport
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from fake_sources import APPROVAL, QUESTION
from mcp_harness import BASE, TIMEOUT, URL, Hang, Scripted, run, serve

ARGS = {"message": "Write the report", "context_id": "ctx-1"}
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
PERSON = AnsweredBy(role="person")


def _step(id: str, state: str = "running") -> ActivityEvent:
    return ActivityEvent(Activity.parse({"kind": "activity", "id": id, "type": "step", "label": f"Label {id}",
                                         "state": state}))


def _server(*tools: Any, **kwargs: Any) -> Any:
    return mcp_server("test", R2CExtension(tools=list(tools), **kwargs.pop("extension", {})), **kwargs)


class Counting(httpx2.AsyncBaseTransport):
    """Passes every request to the in-process app, and keeps the url of each."""

    def __init__(self, inner: httpx2.AsyncBaseTransport) -> None:
        self.inner = inner
        self.urls: list[str] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.urls.append(str(request.url))
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


@contextlib.asynccontextmanager
async def connected(server: Any, *, record: Record | None = None, limits: Limits = Limits(),
                    clock: Any = None) -> AsyncIterator[tuple[R2CClient, Counting]]:
    async with serve(server) as served:
        counting = Counting(StreamingASGITransport(served.app, record=record))
        http = httpx2.AsyncClient(transport=counting, base_url=BASE, timeout=TIMEOUT)
        client = await R2CClient.connect(URL, http_client=http, limits=limits, clock=clock)
        try:
            yield client, counting
        finally:
            await client.aclose()
            await http.aclose()


async def items(stream: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in stream]


def _answer(request: Any, value: dict[str, Any] | None, *, outcome: str = "answered",
            by: AnsweredBy = PERSON) -> Answer:
    given = {"value": value} if value is not None else {}
    return Answer(id=request.id, outcome=outcome, answered_by=by, **given)  # type: ignore[arg-type]


# --- Items (scenarios 1, 2, 5) -------------------------------------------------------------------


def test_activities_in_order() -> None:
    source = Scripted("live", _step("a-1"), _step("a-1", "done"), _step("a-2"), ReplyChunk("Hi.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            assert client.active
            got = await items(client.call("agent", ARGS))
        assert [(i.activity.id, i.activity.state) for i in got if isinstance(i, ActivityItem)] == [
            ("a-1", "running"), ("a-1", "done"), ("a-2", "running")]
        assert isinstance(got[0], ActivityItem) and isinstance(got[-1], ResultItem)

    run(main())


def test_call_without_progress_has_no_activity() -> None:
    source = Scripted("live", _step("a-1"), ReplyChunk("Hi.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            got = await items(client.call("agent", ARGS, progress=False))
        assert not any(isinstance(i, (ActivityItem, ProgressItem)) for i in got)

    run(main())


def _plain_server(progress: list[dict[str, Any]], *, declare: bool = False) -> MCPServer:
    """A hand-built server whose tool `chatty` sends ``progress`` as given, then ``Done.``; it
    declares the R2C key only with ``declare``."""
    server = MCPServer("plain", extensions=[_Declare()] if declare else None)

    @server.tool(name="chatty", structured_output=False)
    async def chatty(ctx: Context) -> str:
        rc = ctx.request_context
        token = (rc.meta or {}).get("progress_token")
        for n, extra in enumerate(progress, start=1):
            params = types.ProgressNotificationParams(progress_token=token, progress=n, **extra)
            await rc.session.send_notification(types.ProgressNotification(params=params),
                                               related_request_id=rc.request_id)
        return "Done."

    return server


def test_plain_progress() -> None:
    async def main() -> None:
        async with connected(_plain_server([{"message": "Half way"}])) as (client, _):
            assert not client.active
            got = await items(client.call("chatty"))
        assert got[0] == ProgressItem("Half way", 1.0)
        assert got[1] == ReplyItem("Done.")
        assert isinstance(got[2], ResultItem) and not got[2].is_error

    run(main())


def test_unknown_objects_skipped_and_counted() -> None:
    known = {"kind": "activity", "id": "a-1", "type": "step", "label": "Known", "state": "running", "colour": "red"}
    wire = [
        {"message": "Odd kind", "_meta": {MCP_KEY: {"kind": "mystery", "id": "m-1"}}},
        {"message": "Odd type", "_meta": {MCP_KEY: {**known, "type": "dream"}}},
        {"message": "Known", "_meta": {MCP_KEY: known}},
    ]

    async def main() -> None:
        async with connected(_plain_server(wire, declare=True)) as (client, _):
            assert client.active
            got = await items(client.call("chatty"))
            assert client.skipped == 2
        assert got[0] == ProgressItem("Odd kind", 1.0)
        assert got[1] == ProgressItem("Odd type", 2.0)
        assert isinstance(got[2], ActivityItem) and got[2].activity.label == "Known"  # unknown field ignored

    run(main())


class _Declare(Extension):
    """Declares the R2C key and nothing else, so a hand-built server is active."""

    identifier = MCP_KEY

    def settings(self) -> dict[str, Any]:
        return {"revision": 1}


def test_request_items() -> None:
    usage = Usage(input_tokens=7)
    source = Scripted("live", UsageEvent(usage), Ask(QUESTION), ReplyChunk("Done.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            got = await items(client.call("agent", ARGS))
            assert list(client.pending) == ["q-1"]
        assert got[0] == UsageItem(usage)
        request = got[1]
        assert isinstance(request, RequestItem) and request.key == "q-1" and request.request == QUESTION
        assert request.message == "Report title"
        assert request.requested_schema is not None and "title" in request.requested_schema["properties"]
        assert request.url is None
        assert len(got) == 2

    run(main())


def test_plain_request_item() -> None:
    async def main() -> None:
        async with connected(_pair_server()) as (client, _):
            got = await items(client.call("pair"))
        assert [i.key for i in got] == ["one", "two"]
        assert all(isinstance(i, RequestItem) and i.request is None for i in got)
        assert got[0].message == "First?" and got[0].requested_schema == _SCHEMA

    run(main())


def test_result_items() -> None:
    csv = ArtifactEvent("f-1", ArtifactMeta(presentation="file"),
                        (UrlContent("https://files.example.com/r/a.csv", "text/csv"),))
    usage = Usage(input_tokens=9, output_tokens=3)
    source = Scripted("live", ReplyChunk("The report. "), csv, UsageEvent(usage), ReplyChunk("Done.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            got = await items(client.call("agent", {"message": "Write the report"}))
            chosen = client.context_id
        assert got[0] == ReplyItem("The report. Done.")
        artifact = got[1]
        assert isinstance(artifact, ArtifactItem) and artifact.presentation == "file"
        assert artifact.uri == "https://files.example.com/r/a.csv" and artifact.media_type == "text/csv"
        assert artifact.meta == ArtifactMeta(presentation="file")
        assert got[2] == UsageItem(usage)
        assert isinstance(chosen, str) and len(chosen) == 32
        assert got[3] == ResultItem(False, {"context_id": chosen}, chosen)
        assert len(got) == 4

    run(main())


def test_error_result() -> None:
    source = Scripted("live", ReplyChunk("Never.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            got = await items(client.call("agent", {"message": 5}))
        assert isinstance(got[0], ReplyItem) and got[0].text.startswith("invalid arguments")
        assert isinstance(got[-1], ResultItem) and got[-1].is_error

    run(main())


# --- Answers (scenarios 3, 4) --------------------------------------------------------------------


def test_bad_answer_sends_nothing() -> None:
    source = Scripted("live", Ask(QUESTION), ReplyChunk("Done.", last=True))
    record: Record = []

    async def main() -> None:
        async with connected(_server(SourceTool(source)), record=record) as (client, _):
            await items(client.call("agent", ARGS))
            sent = len(record)
            with pytest.raises(AnswerRejected) as caught:
                await items(client.answer(_answer(QUESTION, {"title": 5})))
            assert caught.value.problems and caught.value.problems[0].code == "invalid_value"
            with pytest.raises(AnswerRejected) as wrong:
                await items(client.answer(Answer(id="q-9", outcome="answered", value={"title": "T"},
                                                 answered_by=PERSON)))
            assert wrong.value.problems[0].code == "wrong_id"
            assert len(record) == sent
            assert list(client.pending) == ["q-1"]

    run(main())


def test_good_answer_sends_the_same_call_and_state() -> None:
    source = Scripted("live", Ask(QUESTION), ReplyChunk("Done.", last=True))
    record: Record = []

    async def main() -> None:
        async with connected(_server(SourceTool(source)), record=record) as (client, _):
            await items(client.call("agent", ARGS))
            state = next(m["result"]["requestState"] for side, m in record
                         if side == "remote" and "requestState" in m.get("result", {}))
            got = await items(client.answer(_answer(QUESTION, {"title": "October"})))
            assert client.pending == {}
        calls = [m["params"] for side, m in record if side == "client" and m.get("method") == "tools/call"]
        assert [c["name"] for c in calls] == ["agent", "agent"]
        assert calls[1]["arguments"] == ARGS
        assert calls[1]["requestState"] == state
        assert calls[1]["inputResponses"] == {"q-1": {"action": "accept", "content": {"title": "October"}}}
        assert got[0] == ReplyItem("Done.")
        assert [a.value for a in source.answers] == [{"title": "October"}]

    run(main())


def test_declined_answer() -> None:
    source = Scripted("live", Ask(QUESTION), ReplyChunk("Done.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            await items(client.call("agent", ARGS))
            await items(client.answer(_answer(QUESTION, None, outcome="declined")))
        assert [a.outcome for a in source.answers] == ["declined"]

    run(main())


def test_caller_on_approval_refused() -> None:
    source = Scripted("live", Ask(APPROVAL), ReplyChunk("Done.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            await items(client.call("agent", ARGS))
            with pytest.raises(AnswerRejected) as caught:
                await items(client.answer(_answer(APPROVAL, {"decision": "allow"}, by=AnsweredBy(role="caller"))))
            assert [p.code for p in caught.value.problems] == ["caller_on_approval"]
            await items(client.answer(_answer(APPROVAL, {"decision": "allow"})))
        assert [a.value for a in source.answers] == [{"decision": "allow"}]

    run(main())


def test_policy_refused_anywhere() -> None:
    source = Scripted("live", Ask(QUESTION), ReplyChunk("Done.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            await items(client.call("agent", ARGS))
            with pytest.raises(AnswerRejected) as caught:
                await items(client.answer(_answer(QUESTION, {"title": "T"}, by=AnsweredBy(role="policy"))))
            assert "policy" in caught.value.problems[0].message

    run(main())


def test_expired_answer_refused() -> None:
    async def main() -> None:
        extension = {"approve": {"publish_page": Approve(expires_in=timedelta(minutes=5))}, "clock": lambda: NOW}
        server = _server(_publish(), extension=extension)
        async with connected(server, clock=lambda: NOW + timedelta(minutes=6)) as (client, _):
            got = await items(client.call("publish_page", {"page": "team/reports"}))
            request = got[-1].request
            with pytest.raises(AnswerRejected) as caught:
                await items(client.answer(_answer(request, {"decision": "allow"})))
            assert [p.code for p in caught.value.problems] == ["expired"]

    run(main())


def _publish() -> Any:
    from ext_r2c.core import tool_from_function

    def publish_page(page: str) -> str:
        """Publish a page."""
        return f"Published {page}."

    return tool_from_function(publish_page)


def test_edit_answer() -> None:
    async def main() -> None:
        server = _server(_publish(), extension={"approve": {"publish_page": True}})
        async with connected(server) as (client, _):
            got = await items(client.call("publish_page", {"page": "team/reports"}))
            request = got[-1].request
            done = await items(client.answer(_answer(request, {"decision": "edit", "args": {"page": "team/drafts"}})))
        assert done[0] == ReplyItem("Published team/drafts.")

    run(main())


def test_respond_checks_content() -> None:
    async def main() -> None:
        async with connected(_pair_server()) as (client, _):
            await items(client.call("pair"))
            with pytest.raises(AnswerRejected):
                await items(client.respond("one", "accept", {"name": 5}))
            with pytest.raises(AnswerRejected):
                await items(client.respond("nine", "accept", {"name": "A"}))
            assert await items(client.respond("one", "accept", {"name": "A"})) == []
            got = await items(client.respond("two", "decline"))
        assert got[0] == ReplyItem("Got one=accept, two=decline.")

    run(main())


# --- Several requests in one round ---------------------------------------------------------------

_SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}


class _Pair(Extension):
    """A tool `pair` that asks two things in one round, then names what it got."""

    identifier = MCP_KEY

    def settings(self) -> dict[str, Any]:
        return {"revision": 1}

    def tools(self) -> list[ToolBinding]:
        def pair() -> str:
            raise RuntimeError("served by intercept_tool_call")

        return [ToolBinding(pair, kwargs={"name": "pair", "structured_output": False})]

    async def intercept_tool_call(self, params: types.CallToolRequestParams, ctx: Any, call_next: Any) -> Any:
        if params.name != "pair":
            return await call_next(ctx)
        responses = params.input_responses or {}
        if responses:
            got = ", ".join(f"{k}={v.action}" for k, v in sorted(responses.items()))
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"Got {got}.")])
        asks = {
            "one": types.ElicitRequest(params=types.ElicitRequestFormParams(message="First?", requested_schema=_SCHEMA)),
            "two": types.ElicitRequest(params=types.ElicitRequestFormParams(message="Second?", requested_schema=_SCHEMA)),
        }
        return types.InputRequiredResult(input_requests=asks, request_state="pair-state")


def _pair_server() -> MCPServer:
    return MCPServer("pair", extensions=[_Pair()],
                     request_state_security=RequestStateSecurity(keys=[b"k" * 32]))


def test_several_requests() -> None:
    async def main() -> None:
        server = _pair_server()
        record: Record = []
        async with connected(server, record=record) as (client, _):
            await items(client.call("pair"))
            first = await items(client.respond("two", "accept", {"name": "B"}))
            calls = [m for side, m in record if side == "client" and m.get("method") == "tools/call"]
            assert first == [] and len(calls) == 1
            got = await items(client.respond("one", "cancel"))
            calls = [m for side, m in record if side == "client" and m.get("method") == "tools/call"]
        assert len(calls) == 2
        assert calls[1]["params"]["inputResponses"] == {"two": {"action": "accept", "content": {"name": "B"}},
                                                        "one": {"action": "cancel"}}
        assert got[0] == ReplyItem("Got one=cancel, two=accept.")

    run(main())


# --- Fetch (scenario 6, SC-009) ------------------------------------------------------------------

LIMITS = Limits(file_bytes=1000)


def _file(id: str, content: Any, presentation: str = "file") -> ArtifactEvent:
    return ArtifactEvent(id, ArtifactMeta(presentation=presentation), (content,))  # type: ignore[arg-type]


def _fetch_server() -> Any:
    steps = [
        _file("f-1", UrlContent("r2c://files/notes.txt", "text/plain", "notes.txt")),
        _file("f-2", UrlContent(f"{BASE}/files/a.csv", "text/csv", "a.csv")),
        _file("f-3", UrlContent("https://files.example.com/b.csv", "text/csv", "b.csv")),
        _file("f-4", UrlContent(f"{BASE}/files/page.html", "text/html", "page"), "live"),
        _file("f-5", BytesContent(b"x" * 20, "application/octet-stream", "small.bin")),
        _file("f-6", BytesContent(b"x" * 2000, "application/octet-stream", "big.bin")),
        _file("f-7", UrlContent(f"{BASE}/files/big.csv", "text/csv", "big.csv")),
        _file("f-8", UrlContent(f"{BASE}/files/moved.csv", "text/csv", "moved.csv")),
        ReplyChunk("Files.", last=True),
    ]
    server = _server(SourceTool(Scripted("live", *steps)))

    @server.resource("r2c://files/notes.txt", mime_type="text/plain")
    def notes() -> str:
        return "Some notes."

    @server.custom_route("/files/a.csv", methods=["GET"])
    async def a_csv(request: Request) -> Response:
        return PlainTextResponse("a,b\n1,2\n")

    @server.custom_route("/files/big.csv", methods=["GET"])
    async def big_csv(request: Request) -> Response:
        return PlainTextResponse("x" * 2000)

    @server.custom_route("/files/moved.csv", methods=["GET"])
    async def moved(request: Request) -> Response:
        return RedirectResponse(f"{BASE}/files/a.csv", status_code=302)

    return server


def test_fetch() -> None:
    async def main() -> None:
        async with connected(_fetch_server(), limits=LIMITS) as (client, counting):
            got = [i for i in await items(client.call("agent", ARGS)) if isinstance(i, ArtifactItem)]
            assert len(got) == 8
            assert await client.fetch(got[0]) == "Some notes."
            assert await client.fetch(got[1]) == b"a,b\n1,2\n"
            assert await client.fetch(got[2]) == Link("https://files.example.com/b.csv", "text/csv", "b.csv")
            assert await client.fetch(got[3]) == Link(f"{BASE}/files/page.html", "text/html", "page")
            assert await client.fetch(got[4]) == b"x" * 20
            assert await client.fetch(got[5]) == TooLarge(2000)
            assert await client.fetch(got[6]) == TooLarge(2000)
            with pytest.raises(httpx2.HTTPStatusError):
                await client.fetch(got[7])
        hosts = {httpx2.URL(u).host for u in counting.urls}
        assert hosts == {"127.0.0.1"}
        assert not any(u.endswith("/files/page.html") for u in counting.urls)
        assert sum(u.endswith("/files/a.csv") for u in counting.urls) == 1  # the redirect was not followed

    run(main())


# --- Version, cancel, a call while paused --------------------------------------------------------


def test_version_checked() -> None:
    server = _server(SourceTool(Scripted("live", ReplyChunk("Hi.", last=True))))
    server._lowlevel_server._request_handlers.pop("server/discover")  # the legacy handshake only

    async def main() -> None:
        async with serve(server) as served:
            http = httpx2.AsyncClient(transport=StreamingASGITransport(served.app), base_url=BASE, timeout=TIMEOUT)
            with pytest.raises(ConnectionError, match="2026-07-28"):
                await R2CClient.connect(URL, http_client=http)
            await http.aclose()

    run(main())


def test_cancel() -> None:
    source = Scripted("live", _step("a-1"), Hang(), ReplyChunk("Never.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            seen: list[Any] = []

            async def read() -> None:
                async for item in client.call("agent", ARGS):
                    seen.append(item)

            reading = asyncio.create_task(read())
            await asyncio.wait_for(source.hanging.wait(), TIMEOUT)
            for _ in range(250):  # the activity can still be on its way when the source hangs
                if seen:
                    break
                await asyncio.sleep(0.02)
            await client.cancel()
            await asyncio.wait_for(reading, TIMEOUT)
            for _ in range(50):
                if source.saw_cancelled is not None:
                    break
                await asyncio.sleep(0.02)
            assert isinstance(seen[0], ActivityItem) and not any(isinstance(i, ResultItem) for i in seen)
            assert client.pending == {}
            again = await items(client.call("agent", {"message": 5}))  # the client is free: refused at once
            assert isinstance(again[-1], ResultItem) and again[-1].is_error
        assert source.saw_cancelled is True

    run(main())


def test_call_while_paused_raises() -> None:
    source = Scripted("live", Ask(QUESTION), ReplyChunk("Done.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            await items(client.call("agent", ARGS))
            with pytest.raises(RuntimeError):
                await items(client.call("agent", ARGS))
            done = await items(client.answer(_answer(QUESTION, {"title": "T"})))
            assert isinstance(done[-1], ResultItem)
            again = await items(client.call("agent", ARGS))  # free again once answered
        assert isinstance(again[-1], RequestItem)

    run(main())


def test_answer_without_pending_raises() -> None:
    async def main() -> None:
        async with connected(_server(SourceTool(Scripted("live", ReplyChunk("Hi.", last=True))))) as (client, _):
            with pytest.raises(AnswerRejected):
                await items(client.answer(_answer(QUESTION, {"title": "T"})))

    run(main())


def test_mcp_response_parse_round_trip() -> None:
    from ext_r2c.mcp import mcp_response

    question = parse({"kind": "question", "id": "q-2", "title": "Pick", "answer_by": {"role": "person"},
                      "fields": [{"key": "color", "header": "Color", "text": "Which?", "type": "one",
                                  "options": [{"label": "Red"}], "other": True}]})
    assert mcp_response(question, _answer(question, {"color": "Teal"})).content == {"color_other": "Teal"}
