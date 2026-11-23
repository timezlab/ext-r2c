"""The app starts and stops both doors by itself, and one `Remote` builds one app (spec 007, story 1;
SC-007; D4; research R2 and R12).

`Remote` gives no handle on its doors (FR-026), so the tests watch the two SDK objects that hold what
a door keeps open: the MCP session manager (`run`) and the A2A request handler (`aclose`).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import mcp_types as types
import pytest
from ext_r2c import Remote
from ext_r2c.a2a import R2CRequestHandler, agent_card
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from a2a_harness import kinds, run, send
from fake_sources import CARD, CheckpointFake
from mcp_harness import call
from remote_harness import Served, address, mcp_options, quiet, serve_remote

ARGS = {"message": "Write the report", "context_id": "ctx-1"}


@dataclass
class Doors:
    """What the two real objects did, in order; `fail_mcp` makes the MCP door fail when it starts."""

    seen: list[str] = field(default_factory=list)
    fail_mcp: bool = False


@pytest.fixture
def doors(monkeypatch: pytest.MonkeyPatch) -> Doors:
    watched = Doors()
    real_run, real_aclose = StreamableHTTPSessionManager.run, R2CRequestHandler.aclose

    @contextlib.asynccontextmanager
    async def spied_run(self: Any) -> AsyncIterator[None]:
        if watched.fail_mcp:
            raise RuntimeError("the MCP door did not start")
        async with real_run(self):
            watched.seen.append("mcp up")
            try:
                yield
            finally:
                watched.seen.append("mcp down")

    async def spied_aclose(self: Any) -> None:
        watched.seen.append("a2a closed")
        await real_aclose(self)

    monkeypatch.setattr(StreamableHTTPSessionManager, "run", spied_run)
    monkeypatch.setattr(R2CRequestHandler, "aclose", spied_aclose)
    return watched


def _remote(**arguments: Any) -> Remote:
    return quiet(agent=CheckpointFake({}), mcp_tool=True, **arguments)


async def _both_doors_answer(served: Served) -> None:
    async with served.a2a() as tc, served.mcp() as client:
        assert kinds(await send(tc, "Write the report"))[-1] == "input_required"
        assert isinstance(await call(client, "agent", ARGS), types.InputRequiredResult)


# --- 1. Start and stop (SC-007) ---------------------------------------------------------------------


def test_app_starts_nothing_and_its_lifespan_starts_and_stops_both_doors(doors: Doors) -> None:
    async def go() -> None:
        remote = _remote()
        assert doors.seen == [], "`Remote(...)` starts nothing"
        async with serve_remote(remote) as served:
            assert doors.seen == ["mcp up"]
            await _both_doors_answer(served)
        assert doors.seen == ["mcp up", "mcp down", "a2a closed"], "MCP stops first, then A2A, each once"

    run(go())


def test_app_alone_starts_no_door(doors: Doors) -> None:
    _remote().app()
    assert doors.seen == []


def test_a_server_that_speaks_the_asgi_lifespan_protocol_starts_and_stops_both_doors(doors: Doors) -> None:
    """What `uvicorn` does with the app: no step of `Remote`'s own is needed (story 1, scenario 1)."""

    async def go() -> None:
        app = _remote().app()
        to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}, "state": {}}
        serving = asyncio.create_task(app(scope, to_app.get, from_app.put))

        await to_app.put({"type": "lifespan.startup"})
        assert (await from_app.get())["type"] == "lifespan.startup.complete"
        assert doors.seen == ["mcp up"]
        await _both_doors_answer(Served(app, agent_card(CARD, address())))
        await to_app.put({"type": "lifespan.shutdown"})
        assert (await from_app.get())["type"] == "lifespan.shutdown.complete"
        await serving
        assert doors.seen == ["mcp up", "mcp down", "a2a closed"]

    run(go())


# --- 2. Failures unwind both doors ------------------------------------------------------------------


def test_an_mcp_door_that_fails_to_start_leaves_the_a2a_door_closed(doors: Doors) -> None:
    async def go() -> None:
        doors.fail_mcp = True
        app = _remote().app()
        with pytest.raises(RuntimeError, match="the MCP door did not start"):
            async with app.router.lifespan_context(app):
                pytest.fail("the app must not serve with one door down")
        assert doors.seen == ["a2a closed"], "the A2A door, already started, is closed (this needs A1)"

    run(go())


def _leaves(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in _leaves(inner)]
    return [error]


def test_an_exception_while_serving_unwinds_both_doors(doors: Doors) -> None:
    async def go() -> None:
        with pytest.raises(BaseException) as caught:
            async with serve_remote(_remote()):
                raise RuntimeError("broke while serving")
        # The MCP SDK's session manager runs inside a task group, which hands an error on in a group.
        assert [(type(leaf), str(leaf)) for leaf in _leaves(caught.value)] == [(RuntimeError, "broke while serving")]
        assert doors.seen == ["mcp up", "mcp down", "a2a closed"]

    run(go())


# --- 3. One `Remote`, one app (D4) ------------------------------------------------------------------


def test_one_remote_builds_one_app() -> None:
    remote = _remote()
    remote.app()
    with pytest.raises(RuntimeError, match="build a new `Remote`"):
        remote.app()


def test_a_build_that_fails_uses_the_remote_up_too() -> None:
    """The SDK refuses a keyword it does not know, in `app()`. What it was given may be half used, so
    the one way on is a new `Remote` (R12)."""
    remote = _remote(mcp=mcp_options(server={"no_such_keyword": True}))
    with pytest.raises(TypeError, match="no_such_keyword"):
        remote.app()
    with pytest.raises(RuntimeError, match="build a new `Remote`"):
        remote.app()
