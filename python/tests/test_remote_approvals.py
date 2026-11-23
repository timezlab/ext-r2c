"""Approvals sit where each caller path is (spec 007, story 3; SC-001 criteria 1 to 3, SC-004).

Two lists, on purpose. The agent's own (here LangChain's `HumanInTheLoopMiddleware`) gates a tool the
agent calls; `approve=` on `Remote` gates a tool an MCP client calls directly. Each governs its own
path, `Remote` reads neither from the other, and nothing here answers an approval but the test's
caller, as a person.

Real: the graph, the middleware, the checkpointer, the bridge, `Remote`, both doors and the SDK
clients. The model is scripted. Every tool body records its call, so a test sees whether it ran.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, cast

import mcp_types as types
import pytest
from a2a.types.a2a_pb2 import StreamResponse
from ext_r2c import MCP_KEY, A2AOptions, MCPOptions, Remote, RemoteError
from ext_r2c.a2a._codec import read_part
from ext_r2c.core import Answer, Approval, parse, thread_id
from ext_r2c.mcp import Approve
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool

from a2a_harness import answer, kinds, run, send
from langgraph_graphs import DEPLOY, PUBLISH, agent, memory_saver, wrap
from langgraph_models import Call, Say, Scripted, tool_results
from mcp_harness import accept, call, dump, texts
from remote_harness import OWNER, quiet, serve_remote

CONTEXT = "ctx-1"
REASON = "Not before Monday."


@dataclass
class World:
    """One graph whose tools `gate` names wait for the agent's own approval, and the `Remote` over it.
    `ran` lists every tool body that ran, whoever called it: `(tool, arguments)`."""

    ran: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    graph: Any = None
    source: Any = None
    remote: Any = None

    async def tool_messages(self) -> list[str]:
        """What the tools (or the gate, for a call it refused) told the model, in the A2A thread."""
        config = {"configurable": {"thread_id": thread_id("a2a", OWNER, CONTEXT)}}
        state = await self.graph.aget_state(config)
        return [str(m.content) for m in state.values["messages"] if m.type == "tool"]


def _world(script: Any, gate: dict[str, Any], *, mcp_tools: tuple[str, ...] = (), **arguments: Any) -> World:
    """`mcp_tools` names the functions that are also plain tools of the MCP door: the same functions
    the graph's tools are made of, so both paths run one body."""
    world = World()

    def publish_page(slug: str) -> str:
        """Publish a page of the handbook."""
        world.ran.append((PUBLISH, {"slug": slug}))
        return f"published {slug}"

    def deploy_release(version: str, region: str = "north") -> str:
        """Roll a release out to a region."""
        world.ran.append((DEPLOY, {"version": version, "region": region}))
        return f"deployed {version} to {region}"

    functions = {PUBLISH: publish_page, DEPLOY: deploy_release}
    middleware = HumanInTheLoopMiddleware(interrupt_on=gate)  # type: ignore[arg-type]
    world.graph = agent(Scripted(script=script), [tool(function) for function in functions.values()], memory_saver(),
                        middleware=[middleware])
    world.source = wrap(world.graph)
    world.remote = quiet(agent=world.source, tools=[functions[name] for name in mcp_tools], mcp_tool=True, **arguments)
    return world


def _summary(messages: Any) -> str:
    return " | ".join(str(m.content) for m in tool_results(messages))


def publish_intro(messages: Any) -> Any:
    """The agent publishes one page, then says what the tool said."""
    if tool_results(messages):
        return Say(_summary(messages), tokens=(8, 4))
    return Call((PUBLISH, {"slug": "intro"}), tokens=(6, 2))


def publish_then_deploy(messages: Any) -> Any:
    """Two calls, one after the other: `publish_page`, then `deploy_release`."""
    done = len(tool_results(messages))
    if done == 0:
        return Call((PUBLISH, {"slug": "intro"}), tokens=(6, 2))
    if done == 1:
        return Call((DEPLOY, {"version": "1.2"}), tokens=(6, 2))
    return Say(_summary(messages), tokens=(8, 4))


def _decided(asked: Approval, role: str = "person", **value: Any) -> Answer:
    return Answer(id=asked.id, outcome="answered", answered_by={"role": role}, value=value)


def _a2a_approval(events: list[StreamResponse]) -> Approval:
    """The one approval of a stream that ends `input_required`."""
    assert kinds(events)[-1] == "input_required", kinds(events)
    (asked,) = [o for o in map(read_part, events[-1].status_update.status.message.parts) if isinstance(o, Approval)]
    return asked


def _mcp_approval(result: Any) -> tuple[str, Approval]:
    """The key and the R2C approval of an input-required result."""
    assert isinstance(result, types.InputRequiredResult), result
    wire = dump(result)
    (key,) = wire["inputRequests"]
    asked = parse(wire["_meta"][MCP_KEY]["input_requests"][key])
    assert isinstance(asked, Approval)
    return key, asked


def _reply(*streams: list[StreamResponse]) -> str:
    updates = [e.artifact_update for stream in streams for e in stream if e.HasField("artifact_update")]
    return "".join(p.text for u in updates for p in u.artifact.parts if p.HasField("text"))


# --- 1. A2A: the agent's own gate (SC-001, criteria 1 to 3) -------------------------------------------


def test_the_agents_gated_call_is_an_approval_that_describes_the_call() -> None:
    async def go() -> None:
        world = _world(publish_intro, {PUBLISH: True})
        async with serve_remote(world.remote, info=world.source.card) as served, served.a2a() as tc:
            first = await send(tc, "Publish the intro", context_id=CONTEXT)
            asked = _a2a_approval(first)
            assert asked.title == f"Approve {PUBLISH}?"
            assert (asked.subject.type, asked.subject.name, asked.subject.args) == ("tool_call", PUBLISH,
                                                                                    {"slug": "intro"})
            assert asked.answer_by.role == "person" and asked.decisions == ["allow", "edit", "deny"]
            assert world.ran == [], "the body waits for the answer"

    run(go())


def test_allow_runs_the_body_once_and_the_task_completes() -> None:
    async def go() -> None:
        world = _world(publish_intro, {PUBLISH: True})
        async with serve_remote(world.remote, info=world.source.card) as served, served.a2a() as tc:
            first = await send(tc, "Publish the intro", context_id=CONTEXT)
            asked = _a2a_approval(first)
            second = await answer(tc, first, _decided(asked, decision="allow"), asked)
            assert kinds(second)[-1] == "completed" and kinds(second).count("completed") == 1
            assert world.ran == [(PUBLISH, {"slug": "intro"})], "exactly once"
            assert _reply(first, second) == "published intro"

    run(go())


def test_deny_with_a_reason_does_not_run_the_body_and_the_model_gets_the_reason() -> None:
    async def go() -> None:
        world = _world(publish_intro, {PUBLISH: True})
        async with serve_remote(world.remote, info=world.source.card) as served, served.a2a() as tc:
            first = await send(tc, "Publish the intro", context_id=CONTEXT)
            asked = _a2a_approval(first)
            second = await answer(tc, first, _decided(asked, decision="deny", reason=REASON), asked)
            assert kinds(second)[-1] == "completed", "a refusal is an answer, not a failure"
            assert world.ran == []
            (told,) = await world.tool_messages()
            assert REASON in told, "what the model reads in place of the tool's result"
            assert REASON in _reply(first, second)

    run(go())


def test_an_answer_that_fails_the_schema_is_asked_again_and_the_run_lives() -> None:
    async def go() -> None:
        world = _world(publish_intro, {PUBLISH: True})
        async with serve_remote(world.remote, info=world.source.card) as served, served.a2a() as tc:
            first = await send(tc, "Publish the intro", context_id=CONTEXT)
            asked = _a2a_approval(first)
            wrong = _decided(asked, decision="edit", args={"slug": 42})  # the tool's `slug` is text
            again_events = await answer(tc, first, wrong, asked)
            assert kinds(again_events) == ["input_required"]
            again = _a2a_approval(again_events)
            assert again.id == asked.id and again.errors, "the same request, with what was wrong"
            assert again.model_copy(update={"errors": None}) == asked
            assert world.ran == []

            done = await answer(tc, first, _decided(asked, decision="allow"), asked)
            assert kinds(done)[-1] == "completed" and world.ran == [(PUBLISH, {"slug": "intro"})]

    run(go())


# --- 2. MCP: `approve=` on `Remote` gates a direct call ------------------------------------------------


def _mcp_world(approve: Any) -> World:
    return _world(publish_intro, {DEPLOY: True}, mcp_tools=(PUBLISH,), approve=approve)


def test_a_direct_call_to_a_named_tool_first_asks_an_approval_and_runs_once_after_allow() -> None:
    async def go() -> None:
        world = _mcp_world([PUBLISH])
        async with serve_remote(world.remote, info=world.source.card) as served, served.mcp() as client:
            first = await call(client, PUBLISH, {"slug": "home"})
            key, asked = _mcp_approval(first)
            assert (asked.subject.name, asked.subject.args) == (PUBLISH, {"slug": "home"})
            assert asked.answer_by.role == "person"
            assert world.ran == [], "0 times before `allow`"

            done = await call(client, PUBLISH, {"slug": "home"}, state=first.request_state,
                              responses=accept(key, decision="allow"))
            assert not done.is_error and texts(done) == ["published home"]
            assert world.ran == [(PUBLISH, {"slug": "home"})], "once after"

    run(go())


def test_deny_on_a_direct_call_does_not_run_the_body() -> None:
    async def go() -> None:
        world = _mcp_world([PUBLISH])
        async with serve_remote(world.remote, info=world.source.card) as served, served.mcp() as client:
            first = await call(client, PUBLISH, {"slug": "home"})
            key, _ = _mcp_approval(first)
            denied = await call(client, PUBLISH, {"slug": "home"}, state=first.request_state,
                                responses=accept(key, decision="deny", reason=REASON))
            assert denied.is_error and REASON in texts(denied)[0]
            assert world.ran == []

    run(go())


@pytest.mark.parametrize(("approve", "role"), [
    ([PUBLISH], "person"),
    ({PUBLISH: True}, "person"),
    ({PUBLISH: Approve()}, "person"),
    ({PUBLISH: Approve(answer_by="approver")}, "approver"),
], ids=["a name list", "True", "Approve()", "an approver"])
def test_the_approval_is_addressed_as_approve_says(approve: Any, role: str) -> None:
    async def go() -> None:
        world = _mcp_world(approve)
        async with serve_remote(world.remote, info=world.source.card) as served, served.mcp() as client:
            _, asked = _mcp_approval(await call(client, PUBLISH, {"slug": "home"}))
            assert asked.answer_by.role == role

    run(go())


def test_a_tool_approve_names_with_false_runs_at_once() -> None:
    async def go() -> None:
        world = _mcp_world({PUBLISH: False})
        async with serve_remote(world.remote, info=world.source.card) as served, served.mcp() as client:
            done = await call(client, PUBLISH, {"slug": "home"})
            assert isinstance(done, types.CallToolResult) and texts(done) == ["published home"]

    run(go())


def test_each_list_governs_only_its_own_path() -> None:
    """The agent's list gates `deploy_release`; `approve=` gates `publish_page`. The agent publishes
    with no approval and is asked before it deploys; an MCP caller deploys with no approval and is
    asked before it publishes. The two lists differ, and `Remote` derived neither from the other."""

    async def go() -> None:
        world = _world(publish_then_deploy, {DEPLOY: True}, mcp_tools=(PUBLISH, DEPLOY), approve=[PUBLISH])
        async with serve_remote(world.remote, info=world.source.card) as served:
            async with served.a2a() as tc:
                first = await send(tc, "Publish and deploy", context_id=CONTEXT)
                asked = _a2a_approval(first)
                assert world.ran == [(PUBLISH, {"slug": "intro"})], "the agent's publish asked nobody"
                assert asked.subject.name == DEPLOY, "the agent's own gate"
                second = await answer(tc, first, _decided(asked, decision="allow"), asked)
                assert kinds(second)[-1] == "completed"
                assert world.ran[1:] == [(DEPLOY, {"version": "1.2", "region": "north"})]

            world.ran.clear()
            async with served.mcp() as client:
                deployed = await call(client, DEPLOY, {"version": "2.0"})
                assert isinstance(deployed, types.CallToolResult), "a direct deploy asked nobody"
                assert world.ran == [(DEPLOY, {"version": "2.0", "region": "north"})]
                key, direct = _mcp_approval(await call(client, PUBLISH, {"slug": "home"}))
                assert direct.subject.name == PUBLISH and len(world.ran) == 1, "`approve=`'s gate"

    run(go())


# --- 3. No approval is for the caller, and `Remote` has no way to answer one (SC-004) ------------------


def test_every_approval_remote_serves_is_for_a_person_or_an_approver() -> None:
    """Every path through `Remote` that makes an approval: the agent's gate on A2A, the same gate
    through the MCP tool `agent`, and `approve=` in each of its forms."""

    async def go() -> None:
        found: dict[str, Approval] = {}
        wires: list[Any] = []
        world = _world(publish_intro, {PUBLISH: True}, mcp_tools=(DEPLOY,), approve=[DEPLOY])
        async with serve_remote(world.remote, info=world.source.card) as served:
            async with served.a2a() as tc:
                found["the agent's gate, on A2A"] = _a2a_approval(await send(tc, "Publish the intro"))
            async with served.mcp() as client:
                through_tool = await call(client, "agent", {"message": "Publish the intro"})
                direct = await call(client, DEPLOY, {"version": "2.0"})
                wires += [dump(through_tool), dump(direct)]
                found["the agent's gate, through the MCP tool"] = _mcp_approval(through_tool)[1]
                found["approve= as a name list"] = _mcp_approval(direct)[1]
        for name, approve in (("Approve()", {DEPLOY: Approve()}), ("an approver", {DEPLOY: Approve(answer_by="approver")})):
            other = _world(publish_intro, {PUBLISH: True}, mcp_tools=(DEPLOY,), approve=approve)
            async with serve_remote(other.remote, info=other.source.card) as served, served.mcp() as client:
                direct = await call(client, DEPLOY, {"version": "2.0"})
                wires.append(dump(direct))
                found[f"approve= as {name}"] = _mcp_approval(direct)[1]

        assert len(found) == 5
        assert {name: asked.answer_by.role for name, asked in found.items()} == {
            "the agent's gate, on A2A": "person", "the agent's gate, through the MCP tool": "person",
            "approve= as a name list": "person", "approve= as Approve()": "person", "approve= as an approver": "approver",
        }
        assert '"caller"' not in json.dumps(wires), "no wire object names the caller as the one who answers"
        assert world.ran == [], "and nothing ran: nobody answered"

    run(go())


@pytest.mark.parametrize("answer_by", ["caller", "model", "agent"])
def test_an_approval_addressed_to_anything_else_is_refused_when_remote_is_built(answer_by: str) -> None:
    with pytest.raises(RemoteError) as caught:
        _mcp_world({PUBLISH: Approve(answer_by=cast(Any, answer_by))})
    (problem,) = caught.value.problems
    assert problem.startswith("approve: ") and PUBLISH in problem


@pytest.mark.parametrize("approve", [[PUBLISH + "_page"], {PUBLISH + "_page": True}, {PUBLISH + "_page": False}])
def test_a_name_in_approve_that_is_no_tool_is_refused_so_a_typo_cannot_leave_a_tool_ungated(approve: Any) -> None:
    with pytest.raises(RemoteError) as caught:
        _mcp_world(approve)
    (problem,) = caught.value.problems
    assert problem.startswith("approve: ") and PUBLISH + "_page" in problem


def test_approve_cannot_name_the_agents_own_tool() -> None:
    with pytest.raises(RemoteError) as caught:
        _world(publish_intro, {PUBLISH: True}, approve=["agent"])
    (problem,) = caught.value.problems
    assert problem.startswith("approve: ") and "its own approvals" in problem


def test_remote_has_no_knob_that_answers_an_approval() -> None:
    """The whole surface, pinned: a new argument, field or method is a decision, not a patch. None of
    them takes an answer, a policy or a model."""
    parameters = [name for name in inspect.signature(Remote.__init__).parameters if name != "self"]
    assert parameters == ["expose", "agent", "card", "url", "tools", "approve", "skills", "resources", "prompts",
                          "mcp_tool", "middleware", "a2a", "mcp", "limits", "clock"]
    assert [name for name in vars(Remote) if not name.startswith("_")] == ["app"]
    assert [f.name for f in dataclasses.fields(A2AOptions)] == ["task_store", "owner_resolver", "path"]
    assert [f.name for f in dataclasses.fields(MCPOptions)] == ["path", "security", "owner", "transport_security",
                                                                "server", "http"]
    assert [f.name for f in dataclasses.fields(Approve)] == ["answer_by", "expires_in", "title"]
