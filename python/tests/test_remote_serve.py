"""One `Remote` over a real graph and two plain tools, served as one app in one process (spec 007,
story 1; SC-003, SC-009).

The graph is the suite's of spec 006 (`ask_question` pauses with a hand-written R2C question), with a
sentence before the tool call so a reply streams on both sides of the pause. The model is scripted
and the rest is real: the graph, the checkpointer, the bridge, `Remote`, both doors and the SDK
clients on the in-process transports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import mcp_types as types
from a2a.types.a2a_pb2 import StreamResponse
from ext_r2c import MCP_KEY, URI, Remote
from ext_r2c.a2a._codec import read_part
from ext_r2c.core import Answer, Question, ToolSpec, thread_id
from google.protobuf import json_format

from a2a_harness import answer, ids, kinds, run, send
from langgraph_graphs import ASK_QUESTION, agent, memory_saver, suite_tools, wrap
from langgraph_models import Call, Say, Scripted, tool_results
from mcp_harness import accept, call, dump, texts
from remote_harness import OWNER, quiet, serve_remote

CONTEXT = "ctx-1"
OCTOBER = "I will ask.\n\nGot: October"
NOVEMBER = "I will ask.\n\nGot: November"


def publish_page(slug: str) -> str:
    """Publish a page of the handbook."""
    return f"published {slug}"


async def _send_notice(arguments: Any) -> str:
    return f"sent: {arguments['text']}"


SEND_NOTICE = ToolSpec(
    name="send_notice", description="Send a short notice to the team.",
    input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    call=_send_notice,
)


def _script(messages: Any) -> Any:
    results = tool_results(messages)
    if results:
        return Say(str(results[-1].content), tokens=(8, 4))
    return Call((ASK_QUESTION, {}), text="I will ask.", tokens=(6, 2))


@dataclass
class World:
    """What the owner has (a graph over a checkpointer, wrapped once) and the one `Remote` over it."""

    saver: Any
    graph: Any
    source: Any
    remote: Remote

    def threads(self) -> set[str]:
        return {found.config["configurable"]["thread_id"] for found in self.saver.list(None)}

    async def said(self, thread: str) -> list[str]:
        """What the people said in one thread, as the checkpointer holds it."""
        state = await self.graph.aget_state({"configurable": {"thread_id": thread}})
        return [str(m.content) for m in state.values["messages"] if m.type == "human"]


def _world() -> World:
    saver = memory_saver()
    graph = agent(Scripted(script=_script), suite_tools(), saver)
    source = wrap(graph)
    return World(saver, graph, source, quiet(agent=source, tools=[publish_page, SEND_NOTICE], mcp_tool=True))


def _title(value: str) -> Answer:
    return Answer(id="q-1", outcome="answered", answered_by={"role": "person"}, value={"title": value})


def _asked(event: StreamResponse) -> Question:
    (asked,) = [o for o in map(read_part, event.status_update.status.message.parts) if isinstance(o, Question)]
    return asked


def _reply(*streams: list[StreamResponse]) -> str:
    updates = [e.artifact_update for stream in streams for e in stream if e.HasField("artifact_update")]
    assert {u.artifact.artifact_id for u in updates} == {"reply"}
    return "".join(p.text for u in updates for p in u.artifact.parts if p.HasField("text"))


def _words(*streams: list[StreamResponse]) -> str:
    """Every text a stream carries: the status messages and the artifacts."""
    found = []
    for event in (e for stream in streams for e in stream):
        if event.HasField("status_update"):
            found += [p.text for p in event.status_update.status.message.parts if p.HasField("text")]
        elif event.HasField("artifact_update"):
            found += [p.text for p in event.artifact_update.artifact.parts if p.HasField("text")]
    return "\n".join(found)


# --- 1. A pause and an answer on each door (SC-003) --------------------------------------------------


def test_an_a2a_caller_gets_a_question_answers_it_and_gets_the_reply() -> None:
    async def go() -> None:
        world = _world()
        async with serve_remote(world.remote, info=world.source.card) as served, served.a2a() as tc:
            first = await send(tc, "Write the report")
            assert kinds(first)[0] == "task" and kinds(first)[-1] == "input_required"
            asked = _asked(first[-1])
            assert (asked.id, asked.title) == ("q-1", "Report title")

            second = await answer(tc, first, _title("October"), asked)
            assert kinds(second)[-1] == "completed" and kinds(second).count("completed") == 1
            assert {e.status_update.task_id for e in second if e.HasField("status_update")} == {first[0].task.id}
            assert _reply(first, second) == OCTOBER
            assert tc.echoed() == [URI, URI], "the A2A door's own middleware still echoes the activation"

    run(go())


def test_an_mcp_caller_gets_the_same_through_the_tool_agent_beside_the_plain_tools() -> None:
    async def go() -> None:
        world = _world()
        async with serve_remote(world.remote, info=world.source.card) as served, served.mcp() as client:
            assert sorted(t.name for t in (await client.list_tools()).tools) == ["agent", "publish_page", "send_notice"]
            arguments = {"message": "Write the report", "context_id": CONTEXT}
            first = await call(client, "agent", arguments)
            assert isinstance(first, types.InputRequiredResult) and first.request_state
            assert list(first.input_requests) == ["q-1"]

            done = await call(client, "agent", arguments, state=first.request_state,
                              responses=accept("q-1", title="October"))
            assert not done.is_error and texts(done) == [OCTOBER]

            assert texts(await call(client, "publish_page", {"slug": "home"})) == ["published home"]
            assert texts(await call(client, "send_notice", {"text": "ready"})) == ["sent: ready"]

    run(go())


# --- 2. One agent, one thread per door (FR-009, FR-030) ----------------------------------------------


def test_the_same_context_over_both_doors_is_two_threads_that_share_nothing() -> None:
    async def go() -> None:
        world = _world()
        a2a_thread, mcp_thread = thread_id("a2a", OWNER, CONTEXT), thread_id("mcp", OWNER, CONTEXT)
        assert a2a_thread.startswith("a2a:") and mcp_thread.startswith("mcp:")
        arguments = {"message": "Write the November report", "context_id": CONTEXT}
        async with serve_remote(world.remote, info=world.source.card) as served:
            async with served.a2a() as tc, served.mcp() as client:
                first = await send(tc, "Write the October report", context_id=CONTEXT)
                assert kinds(first)[-1] == "input_required"
                assert world.threads() == {a2a_thread}

                paused = await call(client, "agent", arguments)
                assert isinstance(paused, types.InputRequiredResult), "a new run of its own, not the A2A one"
                assert world.threads() == {a2a_thread, mcp_thread}, "one thread per door, in one checkpointer"

                # Each door's answer reaches its own pause, in the other order.
                done = await call(client, "agent", arguments, state=paused.request_state,
                                  responses=accept("q-1", title="November"))
                assert texts(done) == [NOVEMBER]
                second = await answer(tc, first, _title("October"), _asked(first[-1]))
                assert kinds(second)[-1] == "completed" and _reply(first, second) == OCTOBER

            assert await world.said(a2a_thread) == ["Write the October report"]
            assert await world.said(mcp_thread) == ["Write the November report"]
            assert world.threads() == {a2a_thread, mcp_thread}

    run(go())


# --- 3. Callers that did not activate R2C (SC-009) ----------------------------------------------------


def _r2c_anywhere(events: list[StreamResponse]) -> list[str]:
    """Every place in the events that carries R2C metadata."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == URI:
                    found.append(path)
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for n, value in enumerate(node):
                walk(value, f"{path}/{n}")

    for n, event in enumerate(events):
        walk(json_format.MessageToDict(event), f"/{n}")
    return found


def test_an_a2a_caller_without_r2c_gets_words_and_a_standard_artifact() -> None:
    async def go() -> None:
        world = _world()
        async with serve_remote(world.remote, info=world.source.card) as served:
            async with served.a2a() as active:  # the control: the same stream carries R2C when activated
                assert _r2c_anywhere(await send(active, "Write the report"))
            async with served.a2a(r2c=False) as tc:
                first = await send(tc, "Write the report")
                assert kinds(first)[-1] == "input_required"
                assert "I will ask." in _words(first) and "Report title" in _words(first)
                second = await send(tc, "October", **ids(first))
                assert kinds(second)[-1] == "completed"
                assert "Got: October" in _words(first, second)
                assert _r2c_anywhere(first + second) == [], "0 R2C parts or metadata"
                assert tc.echoed() == [None, None]

    run(go())


def test_an_mcp_caller_without_r2c_gets_a_standard_form_and_plain_text() -> None:
    async def go() -> None:
        world = _world()
        arguments = {"message": "Write the report", "context_id": CONTEXT}
        async with serve_remote(world.remote, info=world.source.card) as served:
            async with served.mcp() as active:  # the control
                assert MCP_KEY in json.dumps(dump(await call(active, "agent", {"message": "Write the report"})))
            async with served.mcp(active=False) as client:
                first = await call(client, "agent", arguments)
                assert isinstance(first, types.InputRequiredResult)
                form = dump(first)["inputRequests"]["q-1"]["params"]
                assert "title" in form["requestedSchema"]["properties"], "a standard elicitation form"
                done = await call(client, "agent", arguments, state=first.request_state,
                                  responses=accept("q-1", title="October"))
                assert not done.is_error and texts(done) == [OCTOBER]
                assert MCP_KEY not in json.dumps([dump(first), dump(done)]), "0 R2C metadata"

    run(go())


# --- 4. The owner's objects are served as they are (FR-005) -------------------------------------------


def _attributes(thing: Any) -> dict[str, int]:
    """The attributes of an object and which object each one is."""
    return {name: id(value) for name, value in vars(thing).items()}


def test_remote_sets_nothing_on_the_agent_the_graph_a_tool_or_a_function() -> None:
    def publish_page(slug: str) -> str:  # this test's own, so nothing an earlier test did is on it
        """Publish a page of the handbook."""
        return f"published {slug}"

    async def go() -> None:
        saver = memory_saver()
        tools = suite_tools()
        graph = agent(Scripted(script=_script), tools, saver)
        source = wrap(graph)
        notice = ToolSpec(name="send_notice", description=SEND_NOTICE.description,
                          input_schema=SEND_NOTICE.input_schema, call=_send_notice)
        given = {"the agent": source, "the graph": graph, "a function": publish_page, "a ToolSpec": notice,
                 **{f"the graph's tool {tool.name}": tool for tool in tools}}
        before = {name: _attributes(thing) for name, thing in given.items()}
        assert before["a function"] == {}, "the function starts with no attribute of its own"

        remote = quiet(agent=source, tools=[publish_page, notice], mcp_tool=True)
        assert {name: _attributes(thing) for name, thing in given.items()} == before, "`Remote(...)` set nothing"
        async with serve_remote(remote, info=source.card) as served:
            assert {name: _attributes(thing) for name, thing in given.items()} == before, "`app()` set nothing"
            async with served.a2a() as tc, served.mcp() as client:
                first = await send(tc, "Write the report")
                await answer(tc, first, _title("October"), _asked(first[-1]))
                arguments = {"message": "Write the report"}
                paused = await call(client, "agent", arguments)
                await call(client, "agent", arguments, state=paused.request_state,
                           responses=accept("q-1", title="October"))
                await call(client, "publish_page", {"slug": "home"})
        # After serving, by name: a run may replace a value of the framework's own. The graph's tools
        # are left out here only: LangChain caches on a tool the first time it runs it.
        handed = ("the agent", "the graph", "a function", "a ToolSpec")
        after = {name: _attributes(given[name]) for name in handed}
        assert {name: sorted(found) for name, found in after.items()} == \
            {name: sorted(before[name]) for name in handed}, "serving added or removed no attribute"
        assert after["a function"] == before["a function"] and after["a ToolSpec"] == before["a ToolSpec"]

    run(go())
