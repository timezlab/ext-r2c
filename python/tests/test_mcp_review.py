"""Findings of the outside review of spec 004 (T092), each pinned by a test that failed first.

The security findings on approvals and the state's TTL are in `test_mcp_approve.py`.
"""

from __future__ import annotations

import asyncio
import gzip
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import httpx2
import mcp_types as types
import pytest
from ext_r2c.core import Ask, Limits, ReplyChunk, tool_from_function
from ext_r2c.mcp import Approve, ArtifactItem, R2CClient, R2CExtension, SourceTool, mcp_server
from ext_r2c.mcp._state import MemoryLedger
from ext_r2c.mcp.activation import Round
from ext_r2c.mcp.source_tool import BUSY
from ext_r2c.mcp.tools import EXPIRED
from mcp.server.request_state import RequestStateSecurity

from fake_sources import QUESTION
from mcp_harness import Hang, Scripted, accept, call, dump, mcp_client, run, serve, texts
from test_mcp_client import ARGS, _server, _step, connected

KEYS = [b"k" * 32]


# --- A round that fails frees its context (code review 1) -----------------------------------------


class _ClosedSession:
    client_capabilities = None

    async def send_notification(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError("the stream is closed")


def _round(token: str | None) -> Round:
    return Round(ctx=SimpleNamespace(session=_ClosedSession(), request_id=1), active=True, form=True,
                 owner="anonymous", token=token, clock=lambda: datetime.now(timezone.utc), limits=Limits(),
                 ledger=MemoryLedger(), ttl=600.0)


def test_a_failed_round_frees_its_context() -> None:
    async def main() -> None:
        source = Scripted("live", _step("a-1"), ReplyChunk("Hi.", last=True))
        tool = SourceTool(source)
        with pytest.raises(ConnectionError):
            await tool.first_round(_round("pt-1"), ARGS)
        assert tool._open == {} and tool._runs == {}
        again = await tool.first_round(_round(None), ARGS)
        assert BUSY not in texts(again)

    run(main())


# --- A resume after a restart on a busy context (code review 2) -----------------------------------


def test_a_resume_on_a_busy_context_waits_and_keeps_its_round() -> None:
    store: dict[str, Any] = {}

    def server(source: Scripted) -> Any:
        return mcp_server("test", R2CExtension(tools=[SourceTool(source)]),
                          security=RequestStateSecurity(keys=KEYS))

    async def main() -> None:
        first = Scripted("checkpoint", Ask(QUESTION), ReplyChunk("Done.", last=True), store=store)
        async with serve(server(first)) as served, mcp_client(served) as client:
            paused = await call(client, "agent", ARGS)
        rebuilt = Scripted("checkpoint", Ask(QUESTION), ReplyChunk("Done.", last=True), store=store)
        async with serve(server(rebuilt)) as served, mcp_client(served) as client:
            other = await call(client, "agent", ARGS)  # a new call on the same context, after the restart
            assert isinstance(other, types.InputRequiredResult)
            for _ in range(2):  # the old state does not burn its round while the context is busy
                old = await call(client, "agent", ARGS, state=paused.request_state,
                                 responses=accept("q-1", title="October"))
                assert old.is_error and texts(old) == [BUSY]
        assert rebuilt.answers == []

    run(main())


# --- Another owner holding the state (code review 5) ----------------------------------------------


def test_another_owner_cannot_answer_a_paused_call() -> None:
    who = {"owner": "alice"}
    source = Scripted("live", Ask(QUESTION), ReplyChunk("Done.", last=True))
    server = mcp_server("test", R2CExtension(tools=[SourceTool(source)], owner=lambda ctx: who["owner"]))

    async def main() -> None:
        async with serve(server) as served, mcp_client(served) as client:
            paused = await call(client, "agent", ARGS)
            who["owner"] = "bob"
            stolen = await call(client, "agent", ARGS, state=paused.request_state,
                                responses=accept("q-1", title="Bob's"))
            assert stolen.is_error
            who["owner"] = "alice"  # the round was not claimed by bob's retry
            done = await call(client, "agent", ARGS, state=paused.request_state,
                              responses=accept("q-1", title="October"))
            assert not done.is_error
        assert [a.value for a in source.answers] == [{"title": "October"}]

    run(main())


def test_another_owner_cannot_answer_an_approval() -> None:
    who = {"owner": "alice"}
    calls: list[int] = []

    def pay(amount: int) -> str:
        """Pay."""
        calls.append(amount)
        return "Paid."

    server = mcp_server("test", R2CExtension(tools=[tool_from_function(pay)], approve={"pay": True},
                                             owner=lambda ctx: who["owner"]))

    async def main() -> None:
        async with serve(server) as served, mcp_client(served) as client:
            asked = await call(client, "pay", {"amount": 5})
            (key,) = dump(asked)["inputRequests"]
            who["owner"] = "bob"
            stolen = await call(client, "pay", {"amount": 5}, state=asked.request_state,
                                responses=accept(key, decision="allow"))
            assert stolen.is_error and calls == []

    run(main())


# --- Expired with no response (code review 7) -----------------------------------------------------


def test_an_expired_approval_without_a_response_ends() -> None:
    now = {"at": datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)}
    calls: list[int] = []

    def pay(amount: int) -> str:
        """Pay."""
        calls.append(amount)
        return "Paid."

    server = mcp_server("test", R2CExtension(tools=[tool_from_function(pay)], clock=lambda: now["at"],
                                             approve={"pay": Approve(expires_in=timedelta(minutes=5))}))

    async def main() -> None:
        async with serve(server) as served, mcp_client(served) as client:
            asked = await call(client, "pay", {"amount": 5})
            now["at"] += timedelta(minutes=6)
            late = await call(client, "pay", {"amount": 5}, state=asked.request_state)  # no response at all
        assert isinstance(late, types.CallToolResult) and late.is_error
        assert texts(late) == [EXPIRED] and calls == []

    run(main())


# --- Arguments checked before an approval is asked (code review 8) ---------------------------------


def test_arguments_are_checked_before_the_approval() -> None:
    def pay(amount: int) -> str:
        """Pay."""
        return "Paid."

    server = mcp_server("test", R2CExtension(tools=[tool_from_function(pay)], approve={"pay": True}))

    async def main() -> None:
        async with serve(server) as served, mcp_client(served) as client:
            bad = await call(client, "pay", {"amount": "five"})
        assert isinstance(bad, types.CallToolResult) and bad.is_error

    run(main())


# --- The client (code review 3, 9; security review 6) ---------------------------------------------


def test_cancel_then_break_frees_the_client() -> None:
    source = Scripted("live", _step("a-1"), Hang(), ReplyChunk("Never.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            async for _item in client.call("agent", ARGS):
                await client.cancel()
                break
            again = [i async for i in client.call("agent", {"message": 5})]  # refused at once
            assert again and again[-1].is_error

    run(main())


def test_aclose_waits_for_the_running_round() -> None:
    source = Scripted("live", _step("a-1"), Hang(), ReplyChunk("Never.", last=True))

    async def main() -> None:
        async with connected(_server(SourceTool(source))) as (client, _):
            reading = asyncio.ensure_future(anext(aiter(client.call("agent", ARGS))))
            await asyncio.wait_for(reading, 5)
            running = client._running
            assert running is not None
            await client.aclose()
            assert running.done()

    run(main())


def _inline(block: dict[str, Any]) -> ArtifactItem:
    return ArtifactItem(meta=None, presentation="inline", block=block)


def test_fetch_refuses_bad_base64() -> None:
    async def main() -> None:
        http = httpx2.AsyncClient()
        client = R2CClient("http://127.0.0.1:8000/mcp", http)
        with pytest.raises(ValueError, match="base64"):
            await client.fetch(_inline({"type": "image", "data": "not base64!", "mimeType": "image/png"}))
        await http.aclose()

    run(main())


def test_fetch_refuses_a_compressed_body() -> None:
    """The client asks for `identity`; a body sent compressed anyway would be inflated before the
    size check, so it is refused (security review 6)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=gzip.compress(b"x" * 10_000), headers={"Content-Encoding": "gzip"})

    async def main() -> None:
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        client = R2CClient("http://127.0.0.1:8000/mcp", http)
        item = ArtifactItem(meta=None, presentation="file", block={"type": "resource_link", "uri": "x", "name": "a"},
                            uri="http://127.0.0.1:8000/files/a.csv", media_type="text/csv")
        with pytest.raises(ValueError, match="encoding"):
            await client.fetch(item)
        await http.aclose()

    run(main())
