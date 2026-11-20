"""Refuse or re-ask, never pass a bad answer on (spec 004, story 3, research R10).

Each bad retry goes to a paused call; the source's received answers and the tool's call count
stay empty.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import mcp_types as types
import pytest
from ext_r2c import MCP_KEY
from ext_r2c.core import Ask, Limits, ReplyChunk, parse
from ext_r2c.mcp import Approve, R2CExtension, SourceTool, mcp_server
from ext_r2c.mcp._state import TOO_LATE
from mcp.server.request_state import RequestStateSecurity
from mcp.shared.exceptions import MCPError

from fake_sources import QUESTION
from mcp_harness import Scripted, accept, auth, call, dump, mcp_client, run, serve, texts
from test_mcp_approve import ARGS, Counted

STYLES = ["checkpoint", "live"]
SOURCE_ARGS = {"message": "Write the report", "context_id": "ctx-1"}
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _server(*tools: Any, approve: Any = None, security: Any = None, **kwargs: Any) -> Any:
    return mcp_server("test", R2CExtension(tools=list(tools), approve=approve or {}, **kwargs), security=security)


def _source(style: str, request: Any = QUESTION) -> Scripted:
    return Scripted(style, ReplyChunk("Before. "), Ask(request), ReplyChunk("After.", last=True))


def _r2c(result: Any, key: str) -> Any:
    return parse(dump(result)["_meta"][MCP_KEY]["input_requests"][key])


def _message(result: Any, key: str) -> str:
    return str(dump(result)["inputRequests"][key]["params"]["message"])


@pytest.mark.parametrize("style", STYLES)
def test_reask(style: str) -> None:
    source = _source(style)

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", SOURCE_ARGS)
            bad = await call(client, "agent", SOURCE_ARGS, state=first.request_state, responses=accept("q-1", title=""))
            assert isinstance(bad, types.InputRequiredResult) and list(bad.input_requests) == ["q-1"]
            again = _r2c(bad, "q-1")
            assert again.id == "q-1" and [e.key for e in again.errors or []] == ["title"]
            assert _message(bad, "q-1").splitlines()[1:] == [e.message for e in again.errors or []]
            assert source.answers == []
            done = await call(client, "agent", SOURCE_ARGS, state=bad.request_state,
                              responses=accept("q-1", title="October"))
        assert [a.value for a in source.answers] == [{"title": "October"}]
        assert texts(done) == ["Before. After."]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_missing_response(style: str) -> None:
    source = _source(style)
    refusal = 'No response was received for "Report title".'

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", SOURCE_ARGS)
            none = await call(client, "agent", SOURCE_ARGS, state=first.request_state)
            assert list(none.input_requests) == ["q-1"]
            assert _message(none, "q-1").splitlines()[0] == refusal
            other = await call(client, "agent", SOURCE_ARGS, state=none.request_state,
                               responses=accept("q-9", title="Not this one"))
            assert list(other.input_requests) == ["q-1"]
            assert _message(other, "q-1").splitlines()[0] == refusal
            assert source.answers == []
            await call(client, "agent", SOURCE_ARGS, state=other.request_state, responses=accept("q-1", title="T"))
        assert [a.value for a in source.answers] == [{"title": "T"}]

    run(main())


@pytest.mark.parametrize("style", STYLES)
def test_expired_question_counts_as_declined(style: str) -> None:
    now = [NOW]
    question = parse({**QUESTION.model_dump(mode="json", exclude_none=True),
                      "expires_at": (NOW + timedelta(minutes=1)).isoformat().replace("+00:00", "Z")})
    source = _source(style, question)

    async def main() -> None:
        async with serve(_server(SourceTool(source), clock=lambda: now[0])) as served, mcp_client(served) as client:
            first = await call(client, "agent", SOURCE_ARGS)
            now[0] = NOW + timedelta(minutes=2)
            done = await call(client, "agent", SOURCE_ARGS, state=first.request_state, responses=accept("q-1", title="T"))
        assert [a.outcome for a in source.answers] == ["declined"]
        assert texts(done)[0] == TOO_LATE

    run(main())


def test_expired_approval_counts_as_deny() -> None:
    now = [NOW]
    tool = Counted()

    async def main() -> None:
        server = _server(tool.spec, approve={"place_order": Approve(expires_in=timedelta(minutes=1))},
                         clock=lambda: now[0])
        async with serve(server) as served, mcp_client(served) as client:
            first = await call(client, "place_order", ARGS)
            (key,) = first.input_requests
            now[0] = NOW + timedelta(minutes=2)
            done = await call(client, "place_order", ARGS, state=first.request_state,
                              responses=accept(key, decision="allow"))
        assert done.is_error and texts(done) == ["Not run: the approval expired."]
        assert tool.calls == []

    run(main())


def test_state_refused_by_the_boundary() -> None:
    first_source, other_source = _source("live"), _source("live")
    security = RequestStateSecurity(keys=[b"k" * 32], ttl=0.5)
    ok = accept("q-1", title="T")

    async def refused(client: Any, name: str, args: dict[str, Any], state: str) -> None:
        with pytest.raises(MCPError) as caught:
            await call(client, name, args, state=state, responses=ok)
        assert caught.value.error.code == -32602

    async def main() -> None:
        tools = [SourceTool(first_source), SourceTool(other_source, name="other")]
        server = mcp_server("test", R2CExtension(tools=tools), security=security, **auth())
        async with serve(server) as served:
            async with mcp_client(served, user="alice") as alice, mcp_client(served, user="bob") as bob:
                first = await call(alice, "agent", SOURCE_ARGS)
                state = first.request_state
                middle = len(state) // 2
                altered = state[:middle] + ("A" if state[middle] != "A" else "B") + state[middle + 1:]
                await refused(alice, "agent", SOURCE_ARGS, altered)
                await refused(alice, "other", SOURCE_ARGS, state)
                await refused(alice, "agent", {**SOURCE_ARGS, "message": "Something else"}, state)
                await refused(bob, "agent", SOURCE_ARGS, state)
                await asyncio.sleep(0.7)
                await refused(alice, "agent", SOURCE_ARGS, state)
        assert first_source.answers == [] and other_source.answers == []

    run(main())


def test_response_too_large() -> None:
    source = _source("live")

    async def main() -> None:
        server = _server(SourceTool(source), limits=Limits(message_bytes=1000))
        async with serve(server) as served, mcp_client(served) as client:
            first = await call(client, "agent", SOURCE_ARGS)
            big = await call(client, "agent", SOURCE_ARGS, state=first.request_state,
                             responses=accept("q-1", title="x" * 2000))
        again = _r2c(big, "q-1")
        assert [e.message for e in again.errors or []] == ["The content is larger than 1000 bytes."]
        assert source.answers == []

    run(main())


def test_roles_not_checked_on_the_door() -> None:
    approval = parse({
        "kind": "approval", "id": "ap-1", "title": "Publish the page",
        "answer_by": {"role": "approver", "approver_role": "editor"},
        "subject": {"type": "tool_call", "name": "publish_page", "args": {"page": "team/reports"}},
        "decisions": ["allow", "deny"],
    })
    source = _source("live", approval)

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            first = await call(client, "agent", SOURCE_ARGS)
            done = await call(client, "agent", SOURCE_ARGS, state=first.request_state,
                              responses=accept("ap-1", decision="allow"))
        assert [(a.answered_by.role, a.value) for a in source.answers] == [("person", {"decision": "allow"})]
        assert not done.is_error

    run(main())


def test_gathered_reply_too_large() -> None:
    chunk = "x" * (2 * 2**20)
    source = Scripted("live", ReplyChunk(chunk), ReplyChunk(chunk), ReplyChunk(chunk, last=True))

    async def main() -> None:
        async with serve(_server(SourceTool(source))) as served, mcp_client(served) as client:
            done = await call(client, "agent", SOURCE_ARGS)
        assert done.is_error and texts(done) == ["The content is larger than 5 MiB."]

    run(main())
