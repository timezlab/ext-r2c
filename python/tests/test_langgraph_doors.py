"""One wrapped real graph served through the two doors (spec 006, story 1; SC-002; D2, R13, R15).

The graph is the suite's (`ask_question` pauses with a hand-written R2C question) with one more reply
before the tool call, so a reply streams on both sides of the pause. The model is scripted and the
rest is real: the graph, the checkpointer, the bridge, the door and the SDK client on the in-process
transport (`a2a_harness`, `mcp_harness`).

Phase 3 made the agent a real source, so most of these pass on their first run (T041); the mutation
check of T043 is what shows they are not vacuous.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import mcp_types as types
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks import DatabaseTaskStore
from a2a.types.a2a_pb2 import StreamResponse
from ext_r2c.a2a import SourceExecutor, agent_card
from ext_r2c.a2a._codec import read_part
from ext_r2c.core import Answer, Limits, Question, Usage
from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt
from mcp.server.request_state import RequestStateSecurity
from sqlalchemy.ext.asyncio import create_async_engine

from a2a_harness import Served, a2a_client, answer, kinds, run, send, serve
from langgraph_graphs import ASK_QUESTION, SUITE_QUESTION, agent, memory_saver, suite_tools, wrap
from langgraph_models import Call, Calls, Say, Scripted
from mcp_harness import accept, call, mcp_client, texts
from mcp_harness import serve as mcp_serve

URL = "https://remote.example.com/"
ARGS = {"message": "Write the report", "context_id": "ctx-1"}
KEYS = [b"k" * 32]
# Two messages with text, so the bridge's paragraph break (R5) is in the one reply the doors build.
FULL = "I will ask.\n\nGot: October"
USAGE = Usage(input_tokens=14, output_tokens=6)  # 6 + 8 in, 2 + 4 out: the two model calls of the turn


def _script(messages: Any) -> Any:
    from langgraph_models import tool_results

    results = tool_results(messages)
    if results:
        return Say(str(results[-1].content), tokens=(8, 4))
    return Call((ASK_QUESTION, {}), text="I will ask.", tokens=(6, 2))


def _agent(saver: Any = None, calls: Calls | None = None) -> Any:
    """A wrapped graph over `saver`; a second one over another saver is the remote after a restart
    that lost its checkpointer."""
    model = Scripted(script=_script, calls=calls)
    return wrap(agent(model, suite_tools(), memory_saver() if saver is None else saver))


def _title(value: str) -> Answer:
    return Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={"title": value})


# --- 1. A2A: a real round trip with a pause and an answer ---------------------------------------


def _status_text(event: StreamResponse) -> str:
    return "".join(p.text for p in event.status_update.status.message.parts if p.HasField("text"))


def _status_objects(event: StreamResponse) -> list[Any]:
    parts = event.status_update.status.message.parts
    return [o for o in map(read_part, parts) if o is not None]


def _reply_updates(*streams: list[StreamResponse]) -> list[Any]:
    return [e.artifact_update for stream in streams for e in stream if e.HasField("artifact_update")]


def _artifact_text(update: Any) -> str:
    return "".join(p.text for p in update.artifact.parts if p.HasField("text"))


def test_a2a_a_pause_and_an_answer_complete_the_same_task() -> None:
    async def go() -> None:
        source = _agent()
        async with serve(SourceExecutor(source), agent_card(source.card, URL)) as served:
            async with a2a_client(served, user="alice") as tc:
                first = await send(tc, "Write the report")
                assert kinds(first)[0] == "task" and kinds(first)[-1] == "input_required"
                (asked,) = [o for o in _status_objects(first[-1]) if isinstance(o, Question)]
                assert (asked.id, asked.title) == ("q-1", "Report title")
                assert "".join(_artifact_text(u) for u in _reply_updates(first)) == "I will ask.", (
                    "the reply so far is in the reply artifact when the question comes"
                )
                task_id = first[0].task.id

                second = await answer(tc, first, _title("October"), asked)
                assert kinds(second)[-1] == "completed"
                assert kinds(second).count("completed") == 1, "nothing follows the terminal event"
                assert {e.status_update.task_id for e in second if e.HasField("status_update")} == {task_id}

                updates = _reply_updates(first, second)
                assert {u.artifact.artifact_id for u in updates} == {"reply"}, "one artifact across the pause"
                assert "".join(_artifact_text(u) for u in updates) == FULL
                assert [u.last_chunk for u in updates][-1] is True, "the reply ends on `last`"
                assert not any(u.last_chunk for u in updates[:-1]), "the pause did not end the reply"
                (reported,) = [o for o in _status_objects(second[-1]) if isinstance(o, Usage)]
                assert reported == USAGE

    run(go())


def test_a2a_a_client_that_did_not_activate_r2c_reads_the_reply_and_the_question_in_words() -> None:
    async def go() -> None:
        source = _agent()
        async with serve(SourceExecutor(source), agent_card(source.card, URL)) as served:
            async with a2a_client(served, user="alice", r2c=False) as tc:
                first = await send(tc, "Write the report")
                assert kinds(first)[-1] == "input_required"
                text = _status_text(first[-1])
                assert "I will ask." in text and "Report title" in text, text

    run(go())


# --- 2. MCP: a real round trip with a pause and an answer ----------------------------------------


def _server(source: Any, **options: Any) -> Any:
    return mcp_server("test", R2CExtension(tools=[SourceTool(source)], **options),
                      security=RequestStateSecurity(keys=KEYS))


def test_mcp_a_pause_and_an_answer_return_the_final_result() -> None:
    async def go() -> None:
        async with mcp_serve(_server(_agent())) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            assert isinstance(first, types.InputRequiredResult) and first.request_state
            assert list(first.input_requests) == ["q-1"]

            done = await call(client, "agent", ARGS, state=first.request_state, responses=accept("q-1", title="October"))
            assert not done.is_error
            assert texts(done) == [FULL], "the door gathers the reply across the pause"

    run(go())


# --- 2b. A node pauses right after the model spoke: the held piece is not lost --------------------


def _talk_then_gate() -> Any:
    """The model says one sentence, then a plain node (not a tool) pauses with the suite's question.

    No tool-call update comes between the last token and the pause, so what the bridge held back
    (the newest piece) can only leave at the pause itself.
    """
    model = Scripted(script=lambda messages: Say("I will ask."))

    async def talk(state: MessagesState, config: RunnableConfig) -> dict[str, Any]:
        return {"messages": [await model.ainvoke(state["messages"], config)]}

    def gate(state: MessagesState) -> dict[str, Any]:
        interrupt(SUITE_QUESTION)
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("talk", talk)
    builder.add_node("gate", gate)
    builder.add_edge(START, "talk")
    builder.add_edge("talk", "gate")
    builder.add_edge("gate", END)
    return wrap(builder.compile(checkpointer=memory_saver()))


def test_a2a_the_last_piece_before_a_pause_is_sent_with_the_question() -> None:
    async def go() -> None:
        source = _talk_then_gate()
        async with serve(SourceExecutor(source), agent_card(source.card, URL)) as served:
            async with a2a_client(served, user="alice") as tc:
                first = await send(tc, "Write the report")
                assert kinds(first)[-1] == "input_required"
                assert "".join(_artifact_text(u) for u in _reply_updates(first)) == "I will ask."
                (asked,) = [o for o in _status_objects(first[-1]) if isinstance(o, Question)]
                second = await answer(tc, first, _title("October"), asked)
                assert kinds(second)[-1] == "completed"
                updates = _reply_updates(first, second)
                assert "".join(_artifact_text(u) for u in updates) == "I will ask."
                assert [u.last_chunk for u in updates][-1] is True and not any(u.last_chunk for u in updates[:-1])

    run(go())


def test_mcp_the_last_piece_before_a_pause_is_in_the_final_result() -> None:
    async def go() -> None:
        async with mcp_serve(_server(_talk_then_gate())) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            assert isinstance(first, types.InputRequiredResult) and first.request_state
            done = await call(client, "agent", ARGS, state=first.request_state, responses=accept("q-1", title="October"))
            assert not done.is_error and texts(done) == ["I will ask."]

    run(go())


# --- 3. A pause nothing waits for any more is `lost` on both doors (D2, R13) ----------------------


@contextlib.asynccontextmanager
async def _remote(source: Any, db: Path) -> AsyncIterator[Served]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    store = DatabaseTaskStore(engine, owner_resolver=resolve_user_scope)
    try:
        async with serve(SourceExecutor(source), agent_card(source.card, URL), store=store) as served:
            yield served
    finally:
        await engine.dispose()


def test_a2a_a_pause_the_new_checkpointer_does_not_hold_ends_the_task_lost(tmp_path: Path) -> None:
    async def go() -> None:
        db = tmp_path / "tasks.db"
        async with _remote(_agent(), db) as served, a2a_client(served, user="alice") as tc:
            first = await send(tc, "Write the report")
            assert kinds(first)[-1] == "input_required"
            (asked,) = [o for o in _status_objects(first[-1]) if isinstance(o, Question)]

        calls = Calls()  # the remote restarts with an empty in-memory checkpointer
        async with _remote(_agent(calls=calls), db) as served, a2a_client(served, user="alice") as tc:
            second = await answer(tc, first, _title("October"), asked)
            assert kinds(second)[-1] == "failed"
            assert "lost" in _status_text(second[-1])
            assert calls.n == 0, "the graph was not started"

    run(go())


def test_mcp_a_pause_the_new_checkpointer_does_not_hold_is_an_error_that_says_lost() -> None:
    async def go() -> None:
        async with mcp_serve(_server(_agent())) as served, mcp_client(served) as client:
            first = await call(client, "agent", ARGS)
            assert isinstance(first, types.InputRequiredResult)
            state = first.request_state

        calls = Calls()
        async with mcp_serve(_server(_agent(calls=calls))) as served, mcp_client(served) as client:
            done = await call(client, "agent", ARGS, state=state, responses=accept("q-1", title="October"))
            assert done.is_error
            assert "lost" in " ".join(texts(done))
            assert calls.n == 0, "the graph was not started"

    run(go())


# --- 4. The size limits are the doors' (R15): the bridge checks none -----------------------------


def test_a2a_a_reply_over_the_message_limit_fails_the_task_cleanly() -> None:
    async def go() -> None:
        source = wrap(agent(Scripted(script=lambda m: Say("x" * 200)), [], memory_saver()))
        executor = SourceExecutor(source, limits=Limits(message_bytes=32))
        async with serve(executor, agent_card(source.card, URL)) as served, a2a_client(served, user="alice") as tc:
            events = await send(tc, "go")
            assert kinds(events)[-1] == "failed"
            assert "larger than" in _status_text(events[-1])

    run(go())


def test_mcp_a_reply_over_the_message_limit_is_an_output_too_large_error() -> None:
    async def go() -> None:
        source = wrap(agent(Scripted(script=lambda m: Say("x" * 200)), [], memory_saver()))
        server = _server(source, limits=Limits(message_bytes=32))
        async with mcp_serve(server) as served, mcp_client(served) as client:
            done = await call(client, "agent", ARGS)
            assert done.is_error
            assert "larger than" in " ".join(texts(done))

    run(go())
