"""A restart in the middle of a pause, on each door, and what `Remote` says when a door keeps its
pauses in memory (spec 007, story 4; SC-001 criterion 4, SC-006; D13; research R11).

A restart here is what it is in a deployment: every object of the first life is dropped (the app, the
`Remote`, the agent, the graph, the stores' connections) and a second life is built by the same code
over the same files, or with the same keys. What outlives a life is on disk, or is the list `ran` of
tool bodies that ran, which stands for the world outside.
"""

from __future__ import annotations

import contextlib
import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import mcp_types as types
import pytest
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks import DatabaseTaskStore, InMemoryTaskStore
from a2a.types.a2a_pb2 import StreamResponse
from ext_r2c import MCP_KEY, A2AOptions, MCPOptions, Remote, RemoteError
from ext_r2c.a2a._codec import read_part
from ext_r2c.core import Answer, Approval, Question, ToolSpec, parse, tool_from_function
from ext_r2c.mcp import Approve, SourceTool
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool
from mcp.server.request_state import RequestStateSecurity
from mcp.shared.exceptions import MCPError
from sqlalchemy.ext.asyncio import create_async_engine

from a2a_harness import answer, kinds, run, send
from fake_sources import CARD, CheckpointFake, LiveFake
from langgraph_graphs import PUBLISH, agent, sqlite_saver, suite_tools, wrap
from langgraph_models import Call, Say, Scripted, tool_results
from mcp_harness import accept, call, dump, texts
from remote_harness import KEYS, Served, identity, owner, quiet, serve_remote

Ran = list[tuple[str, dict[str, Any]]]


def _publish(ran: Ran) -> Any:
    def publish_page(slug: str) -> str:
        """Publish a page of the handbook."""
        ran.append((PUBLISH, {"slug": slug}))
        return f"published {slug}"

    return publish_page


def _publish_intro(messages: Any) -> Any:
    results = tool_results(messages)
    if results:
        return Say(str(results[-1].content), tokens=(8, 4))
    return Call((PUBLISH, {"slug": "intro"}), tokens=(6, 2))


def _ask_a_title(messages: Any) -> Any:
    results = tool_results(messages)
    if results:
        return Say(str(results[-1].content), tokens=(8, 4))
    return Call(("ask_question", {}), text="I will ask.", tokens=(6, 2))


# --- 1. A2A: a durable task store and a durable checkpointer (SC-001, criterion 4) --------------------


@contextlib.asynccontextmanager
async def _a2a_life(folder: Path, graph_on: Any) -> AsyncIterator[Served]:
    """One life of the remote: a checkpointer and a task store on the files of `folder`, a new graph
    (`graph_on(saver)`), a new agent and a new `Remote`, served."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{folder / 'tasks.db'}")
    try:
        async with sqlite_saver(folder / "graph.db") as saver:
            source = wrap(graph_on(saver))
            remote = Remote(
                expose=["a2a"], agent=source, url="https://remote.example.com", middleware=identity(),
                a2a=A2AOptions(task_store=DatabaseTaskStore(engine, owner_resolver=resolve_user_scope)),
            )
            async with serve_remote(remote, info=source.card) as served:
                yield served
    finally:
        await engine.dispose()


def _status_objects(events: list[StreamResponse]) -> list[Any]:
    assert kinds(events)[-1] == "input_required", kinds(events)
    return [o for o in map(read_part, events[-1].status_update.status.message.parts) if o is not None]


def _reply(*streams: list[StreamResponse]) -> str:
    updates = [e.artifact_update for stream in streams for e in stream if e.HasField("artifact_update")]
    return "".join(p.text for u in updates for p in u.artifact.parts if p.HasField("text"))


def test_an_approval_answered_after_a_restart_runs_the_tool_once_and_completes_the_task(tmp_path: Path) -> None:
    ran: Ran = []

    def graph_on(saver: Any) -> Any:
        gate = HumanInTheLoopMiddleware(interrupt_on={PUBLISH: True})  # type: ignore[arg-type]
        return agent(Scripted(script=_publish_intro), [tool(_publish(ran))], saver, middleware=[gate])

    async def go() -> None:
        async with _a2a_life(tmp_path, graph_on) as served, served.a2a() as tc:
            first = await send(tc, "Publish the intro")
            (asked,) = [o for o in _status_objects(first) if isinstance(o, Approval)]
            assert ran == []

        async with _a2a_life(tmp_path, graph_on) as served, served.a2a() as tc:  # nothing of the first life is left
            allow = Answer(id=asked.id, outcome="answered", answered_by={"role": "person"}, value={"decision": "allow"})
            second = await answer(tc, first, allow, asked)
            assert kinds(second)[-1] == "completed" and kinds(second).count("completed") == 1
            assert {e.status_update.task_id for e in second if e.HasField("status_update")} == {first[0].task.id}
            assert ran == [(PUBLISH, {"slug": "intro"})], "once, in the life that was answered"
            assert "published intro" in _reply(second)

    run(go())


def test_a_question_answered_after_a_restart_completes_the_same_task(tmp_path: Path) -> None:
    def graph_on(saver: Any) -> Any:
        return agent(Scripted(script=_ask_a_title), suite_tools(), saver)

    async def go() -> None:
        async with _a2a_life(tmp_path, graph_on) as served, served.a2a() as tc:
            first = await send(tc, "Write the report")
            (asked,) = [o for o in _status_objects(first) if isinstance(o, Question)]

        async with _a2a_life(tmp_path, graph_on) as served, served.a2a() as tc:
            title = Answer(id=asked.id, outcome="answered", answered_by={"role": "person"}, value={"title": "October"})
            second = await answer(tc, first, title, asked)
            assert kinds(second)[-1] == "completed"
            assert _reply(second).endswith("Got: October")

    run(go())


# --- 2. MCP: fixed request-state keys (SC-006) ---------------------------------------------------------

OTHER_KEYS = [b"o" * 32]
ARGS = {"slug": "home"}


def _mcp_remote(ran: Ran, security: RequestStateSecurity | None) -> Remote:
    """One life of an MCP remote whose `publish_page` waits for an approval."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)  # with `security=None`: the warning of section 3
        return Remote(expose=["mcp"], tools=[_publish(ran)], approve=[PUBLISH], card=CARD, middleware=identity(),
                      mcp=MCPOptions(security=security, owner=owner))


async def _paused_call(ran: Ran, security: RequestStateSecurity | None) -> tuple[str, str]:
    """The first life: a direct call that stops at its approval. The sealed state and the key."""
    async with serve_remote(_mcp_remote(ran, security)) as served, served.mcp() as client:
        first = await call(client, PUBLISH, ARGS)
    assert isinstance(first, types.InputRequiredResult) and first.request_state
    wire = dump(first)
    (key,) = wire["inputRequests"]
    assert isinstance(parse(wire["_meta"][MCP_KEY]["input_requests"][key]), Approval)
    assert ran == []
    return first.request_state, key


def test_a_paused_call_is_retried_after_a_rebuild_with_the_same_keys_and_runs_once() -> None:
    async def go() -> None:
        ran: Ran = []
        state, key = await _paused_call(ran, RequestStateSecurity(keys=KEYS))
        rebuilt = _mcp_remote(ran, RequestStateSecurity(keys=list(KEYS)))  # a new policy, the same keys
        async with serve_remote(rebuilt) as served, served.mcp() as client:
            done = await call(client, PUBLISH, ARGS, state=state, responses=accept(key, decision="allow"))
            assert not done.is_error and texts(done) == ["published home"]
            assert ran == [(PUBLISH, ARGS)], "once"

    run(go())


@pytest.mark.parametrize("first, second", [
    (RequestStateSecurity(keys=KEYS), RequestStateSecurity(keys=OTHER_KEYS)),
    (None, None),
], ids=["another key", "no keys: each life makes its own"])
def test_a_paused_call_is_refused_after_a_rebuild_that_does_not_have_its_key(first: Any, second: Any) -> None:
    async def go() -> None:
        ran: Ran = []
        state, key = await _paused_call(ran, first)
        async with serve_remote(_mcp_remote(ran, second)) as served, served.mcp() as client:
            with pytest.raises(MCPError) as caught:
                await call(client, PUBLISH, ARGS, state=state, responses=accept(key, decision="allow"))
            assert caught.value.error.code == -32602, "the SDK's own refusal of a state it cannot open (spec 004)"
            assert ran == [], "and the tool did not run"

    run(go())


# --- 3. A door that keeps its pauses in memory says so, once, when `Remote` is built (D13) ------------


def _plain() -> ToolSpec:
    return tool_from_function(_publish([]))


def _warned(**arguments: Any) -> tuple[Remote, list[warnings.WarningMessage]]:
    """A `Remote` and every warning its construction gave."""
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        remote = Remote(**arguments)
    return remote, list(seen)


def _a2a(**changes: Any) -> dict[str, Any]:
    return {"expose": ["a2a"], "agent": CheckpointFake({}), "url": "https://remote.example.com", **changes}


def _mcp(**changes: Any) -> dict[str, Any]:
    return {"expose": ["mcp"], "tools": [_plain()], "card": CARD, **changes}


def _says(warning: warnings.WarningMessage, setting: str) -> bool:
    text = str(warning.message)
    return (warning.category is UserWarning and text.startswith(f"{setting}: ") and "restart" in text
            and warning.filename == __file__)


def test_an_a2a_door_with_no_task_store_warns_once_and_names_the_setting() -> None:
    _, seen = _warned(**_a2a())
    assert len(seen) == 1 and _says(seen[0], "a2a.task_store"), [str(w.message) for w in seen]
    assert "A2AOptions" in str(seen[0].message), "what to do"


@pytest.mark.parametrize("store", [InMemoryTaskStore, None], ids=["a store the owner chose", "a durable one"])
def test_an_a2a_door_with_a_task_store_warns_nothing(store: Any, tmp_path: Path) -> None:
    """`Remote` does not judge the store it is given: giving one is the owner's decision."""
    engine = None if store is not None else create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tasks.db'}")
    given = store() if store is not None else DatabaseTaskStore(engine, owner_resolver=resolve_user_scope)
    _, seen = _warned(**_a2a(a2a=A2AOptions(task_store=given)))
    assert seen == []


MCP_THAT_CAN_PAUSE: list[tuple[str, dict[str, Any]]] = [
    ("approve as a name list", {"approve": [PUBLISH]}),
    ("approve with True", {"approve": {PUBLISH: True}}),
    ("approve with an Approve", {"approve": {PUBLISH: Approve(answer_by="approver")}}),
    ("a checkpoint agent as the tool", {"agent": CheckpointFake({}), "mcp_tool": True, "tools": []}),
    ("a checkpoint SourceTool in tools", {"tools": [SourceTool(CheckpointFake({}), name="writer")]}),
]
MCP_THAT_CANNOT: list[tuple[str, dict[str, Any]]] = [
    ("plain tools only", {}),
    ("approve with False only", {"approve": {PUBLISH: False}}),
    ("a live agent as the tool", {"agent": LiveFake(), "mcp_tool": True, "tools": []}),
    ("a live SourceTool in tools", {"tools": [SourceTool(LiveFake(), name="writer")]}),
]


@pytest.mark.parametrize("changes", [c[1] for c in MCP_THAT_CAN_PAUSE], ids=[c[0] for c in MCP_THAT_CAN_PAUSE])
def test_an_mcp_door_that_can_pause_with_no_keys_warns_once_and_names_the_setting(changes: dict[str, Any]) -> None:
    _, seen = _warned(**_mcp(**changes))
    assert len(seen) == 1 and _says(seen[0], "mcp.security"), [str(w.message) for w in seen]
    assert "MCPOptions" in str(seen[0].message) and "RequestStateSecurity" in str(seen[0].message), "what to do"

    _, with_keys = _warned(**_mcp(mcp=MCPOptions(security=RequestStateSecurity(keys=KEYS)), **changes))
    assert with_keys == [], "fixed keys are the whole answer"


@pytest.mark.parametrize("changes", [c[1] for c in MCP_THAT_CANNOT], ids=[c[0] for c in MCP_THAT_CANNOT])
def test_an_mcp_door_that_cannot_pause_across_a_restart_warns_nothing(changes: dict[str, Any]) -> None:
    """A plain tool answers in one round. A live source needs the same process, which no key gives back."""
    _, seen = _warned(**_mcp(**changes))
    assert seen == []


def test_both_doors_in_memory_give_two_warnings_one_each_at_construction_only() -> None:
    remote, seen = _warned(expose=["a2a", "mcp"], agent=CheckpointFake({}), mcp_tool=True,
                           url="https://remote.example.com")
    assert [str(w.message).partition(":")[0] for w in seen] == ["a2a.task_store", "mcp.security"]
    assert all(_says(w, name) for w, name in zip(seen, ["a2a.task_store", "mcp.security"], strict=True))
    with warnings.catch_warnings(record=True) as later:
        warnings.simplefilter("always")
        remote.app()
    assert later == [], "`app()` says nothing again"


def test_a_remote_that_is_refused_warns_nothing() -> None:
    """Both doors would warn; the configuration is wrong, so the owner hears only that."""
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with pytest.raises(RemoteError):
            Remote(expose=["a2a", "mcp"], agent=CheckpointFake({}), mcp_tool=True, approve=["publish_pgae"])
        with pytest.raises(TypeError):
            Remote(expose=["a2a", "mcp"], agent=object(), url="https://remote.example.com")
    assert seen == []


def test_the_quiet_remote_of_the_other_tests_is_quiet_because_it_has_a_store_and_keys() -> None:
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        quiet(agent=CheckpointFake({}), mcp_tool=True, tools=[_plain()], approve=[PUBLISH])
    assert seen == []
