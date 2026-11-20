"""A paused run across a restart of the remote, on a durable task store (spec 003, story 4).

The whole app is rebuilt on the same SQLite file (research R16): a new request handler, a new
executor and driver, a new source. The checkpoint fake's dict outlives the app, as a real
checkpointer would. A checkpoint run goes on (SC-006); a live run is lost (FR-020).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks import DatabaseTaskStore
from a2a.types.a2a_pb2 import StreamResponse
from ext_r2c.a2a import SourceExecutor, agent_card
from ext_r2c.a2a._codec import read_part
from ext_r2c.core import Answer, Question
from sqlalchemy.ext.asyncio import create_async_engine

from a2a_harness import Served, a2a_client, answer, kinds, run, send, serve
from fake_sources import CARD, QUESTION, CheckpointFake, LiveFake


@contextlib.asynccontextmanager
async def _remote(source: Any, db: Path) -> AsyncIterator[Served]:
    """One life of the remote: a store on the SQLite file, and the app around `source`."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    store = DatabaseTaskStore(engine, owner_resolver=resolve_user_scope)
    try:
        async with serve(SourceExecutor(source), agent_card(CARD, "https://remote.example.com/"),
                         store=store) as served:
            yield served
    finally:
        await engine.dispose()


def _text(event: StreamResponse) -> str:
    return "".join(p.text for p in event.status_update.status.message.parts if p.HasField("text"))


def _title(value: str) -> Answer:
    return Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={"title": value})


async def _paused(source: Any, db: Path) -> list[StreamResponse]:
    async with _remote(source, db) as served, a2a_client(served, user="alice") as tc:
        first = await send(tc, "Write the report")
        assert kinds(first) == ["task", "working", "input_required"]
        return first


def test_a_checkpoint_run_goes_on_after_a_restart(tmp_path: Path) -> None:
    async def go() -> None:
        db, store = tmp_path / "tasks.db", {}
        first = await _paused(CheckpointFake(store), db)

        again = CheckpointFake(store)  # the same remote, restarted
        async with _remote(again, db) as served, a2a_client(served, user="alice") as tc:
            reply = _title("October")
            second = await answer(tc, first, reply, QUESTION)
            assert kinds(second)[-1] == "completed"  # SC-006
            assert again.answers == [reply]

    run(go())


def test_a_live_run_is_lost_on_a_restart(tmp_path: Path) -> None:
    async def go() -> None:
        db = tmp_path / "tasks.db"
        first = await _paused(LiveFake(), db)

        async with _remote(LiveFake(), db) as served, a2a_client(served, user="alice") as tc:
            second = await answer(tc, first, _title("October"), QUESTION)
            assert kinds(second)[-1] == "failed"  # FR-020
            assert "lost" in _text(second[-1])

    run(go())


@pytest.mark.parametrize("style", ["checkpoint", "live"])
def test_a_bad_answer_after_a_restart_is_re_asked_from_the_stored_request(tmp_path: Path, style: str) -> None:
    async def go() -> None:
        db, store = tmp_path / "tasks.db", {}
        make = (lambda: CheckpointFake(store)) if style == "checkpoint" else LiveFake
        first = await _paused(make(), db)

        async with _remote(make(), db) as served, a2a_client(served, user="alice") as tc:
            empty = Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={})
            second = await answer(tc, first, empty, QUESTION)
            assert kinds(second) == ["input_required"]  # R2: read back from the stored task
            asked = [o for o in map(read_part, second[-1].status_update.status.message.parts) if o is not None]
            (again,) = asked
            assert isinstance(again, Question) and again.id == "q-1"
            assert [e.key for e in again.errors or ()] == ["title"]

    run(go())
