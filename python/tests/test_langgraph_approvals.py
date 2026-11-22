"""Approvals from `HumanInTheLoopMiddleware`, `per_call` and `batched` (spec 006, story 2; R8, R9;
FR-014 to FR-018, FR-020; SC-004, SC-005, SC-006).

Real `create_agent` graphs with LangChain's own middleware and a real checkpointer, through the real
`Driver`; the model is scripted. Every test that can run in both modes runs in both: the caller must
not be able to tell them apart (the batch is the bridge's business, not the caller's).

A refusal test delivers the wrong answer through `Driver.resume`, checks that nothing reached the
graph, then delivers a right answer through a new `Driver.resume` on the same pending request: the
thread must still be able to go on (SC-005).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from ext_r2c.bridges.langgraph._decisions import schema_decisions
from ext_r2c.bridges.langgraph._pauses import read_pauses
from ext_r2c.bridges.langgraph.tools import schema_of, tools_by_name
from ext_r2c.core import (
    Answer,
    AnswerBy,
    AnswerEvent,
    Approval,
    Ask,
    Done,
    Driver,
    Error,
    Field,
    Question,
    Run,
    RunInput,
    thread_id,
)

from agent_source_suite import reply_text, rest, until_pause
from langgraph_graphs import DEPLOY, NOTICE, PUBLISH, agent, counted_tools, memory_saver, run, wrap
from langgraph_models import Call, Calls, Say, Script, Scripted, Turn, tool_results

THREAD = thread_id("a2a", "owner-1", "ctx-1")
CONFIG = {"configurable": {"thread_id": THREAD}}
MODES = ("per_call", "batched")
EVERYTHING: Any = True  # the middleware's default: approve, edit, reject and respond


# --- the graphs and the scripts ------------------------------------------------------------------


def _summary(messages: list[BaseMessage]) -> str:
    """What the tools said this turn: the model's last words, so a test reads it in the reply."""
    return " | ".join(str(m.content) for m in tool_results(messages))


def notice_then_deploy(messages: list[BaseMessage]) -> Turn:
    """Two gated calls, in an order that is not alphabetical: `send_notice`, then `deploy_release`."""
    if not tool_results(messages):
        return Call((NOTICE, {"text": "hi"}), (DEPLOY, {"version": "1.2"}), tokens=(6, 2))
    return Say(_summary(messages), tokens=(8, 4))


def one_deploy(messages: list[BaseMessage]) -> Turn:
    if not tool_results(messages):
        return Call((DEPLOY, {"version": "1.2"}), tokens=(6, 2))
    return Say(_summary(messages), tokens=(8, 4))


def three_calls(messages: list[BaseMessage]) -> Turn:
    if not tool_results(messages):
        return Call((DEPLOY, {"version": "1"}), (PUBLISH, {"slug": "intro"}), (NOTICE, {"text": "hi"}))
    return Say(_summary(messages))


@dataclass
class World:
    """One wrapped graph with what a test looks at: the tool counters and the model's call count."""

    source: Any
    graph: Any
    runs: Counter[str]
    calls: Calls
    saver: Any

    async def state(self) -> Any:
        return await self.graph.aget_state(CONFIG)

    async def messages(self) -> list[BaseMessage]:
        return list((await self.state()).values["messages"])


def world(script: Script, mode: str, gate: dict[str, Any] | None = None, *, saver: Any = None) -> World:
    """A graph whose tools `gate` (name → `True` or an `InterruptOnConfig`) wait for approval."""
    runs: Counter[str] = Counter()
    calls = Calls()
    saver = memory_saver() if saver is None else saver
    middleware = HumanInTheLoopMiddleware(interrupt_on=gate or {DEPLOY: True, NOTICE: True}, interrupt_mode=mode)  # type: ignore[arg-type]
    graph = agent(Scripted(script=script, calls=calls), list(counted_tools(runs).values()), saver, middleware=[middleware])
    return World(wrap(graph), graph, runs, calls, saver)


def hidden(script: Script, mode: str, gate: dict[str, Any]) -> World:
    """The same agent as a node of another graph: its tool node is not the wrapped graph's, so the
    bridge cannot read the tool's arguments schema (a hand-built graph that hides its tools)."""
    runs: Counter[str] = Counter()
    calls = Calls()
    saver = memory_saver()
    middleware = HumanInTheLoopMiddleware(interrupt_on=gate, interrupt_mode=mode)  # type: ignore[arg-type]
    inner = agent(Scripted(script=script, calls=calls), list(counted_tools(runs).values()), None, middleware=[middleware])
    builder = StateGraph(MessagesState)
    builder.add_node("agent", inner)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    graph = builder.compile(checkpointer=saver)
    return World(wrap(graph), graph, runs, calls, saver)


# --- the answers ---------------------------------------------------------------------------------


def _answer(request: Approval | Question, value: dict[str, Any] | None, note: str | None = None) -> Answer:
    obj: dict[str, Any] = {"kind": "answer", "id": request.id, "answered_by": {"role": "person"}}
    obj.update({"outcome": "answered", "value": value} if value is not None else {"outcome": "declined"})
    if note is not None:
        obj["note"] = note
    return Answer.parse(obj)


def allow(request: Approval) -> Answer:
    return _answer(request, {"decision": "allow"})


def deny(request: Approval, reason: str | None = None) -> Answer:
    return _answer(request, {"decision": "deny", **({"reason": reason} if reason else {})})


def edit(request: Approval, args: dict[str, Any], **more: Any) -> Answer:
    return _answer(request, {"decision": "edit", "args": args, **more})


def declined(request: Approval | Question, note: str | None = None) -> Answer:
    return _answer(request, None, note)


def reply(request: Question, text: str) -> Answer:
    return _answer(request, {"reply": text})


async def pause_at(w: World, text: str = "go") -> tuple[Run, Approval | Question]:
    """Start a run and read it up to its first ask."""
    live = Driver(w.source).start(THREAD, RunInput(text))
    await until_pause(live)
    assert live.pending is not None, "the run was expected to ask"
    return live, live.pending


async def approval_at(w: World) -> Approval:
    _, request = await pause_at(w)
    assert isinstance(request, Approval)
    return request


async def refused(w: World, request: Approval | Question, wrong: Answer, right: Answer) -> tuple[Error, list[Any]]:
    """`wrong` ends the run `failed` with no call into the graph and no change to its saved state;
    `right`, delivered later on the same request, goes through. Returns the error and the right
    answer's events."""
    before, asked = await w.state(), w.calls.n
    events = [e async for e in Driver(w.source).resume(THREAD, request, wrong)]
    assert [type(e) for e in events] == [AnswerEvent, Error], events
    error = events[-1]
    assert isinstance(error, Error) and error.code == "failed", error
    after = await w.state()
    assert w.calls.n == asked, "the model was not called"
    assert after.config == before.config, "nothing was written to the checkpoint"
    assert [i.id for i in after.interrupts] == [i.id for i in before.interrupts], "the pause is still pending"
    tail = [e async for e in Driver(w.source).resume(THREAD, request, right)]
    assert isinstance(tail[-1], Done), tail
    return error, tail


def tool_message(messages: list[BaseMessage], call_id: str) -> ToolMessage:
    (found,) = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == call_id]
    return found


# --- 1. SC-004: one at a time, in the model's order -----------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_two_gated_calls_are_asked_one_at_a_time_in_the_models_order(mode: str) -> None:
    w = world(notice_then_deploy, mode)

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval) and first.subject.name == NOTICE, (
            "the model's first call is asked first (an alphabetical order would ask deploy_release)"
        )
        held = await w.state()
        assert len(held.interrupts) == (2 if mode == "per_call" else 1), "per call: one interrupt each; batched: one"
        assert not w.runs, "nothing ran before an answer"

        await live.deliver(allow(first))
        await until_pause(live)
        second = live.pending
        assert isinstance(second, Approval) and second.subject.name == DEPLOY
        assert w.runs[NOTICE] == (1 if mode == "per_call" else 0), "per call each answer goes at once; a batch waits"
        assert not w.runs[DEPLOY]

        await live.deliver(deny(second, "Not before Monday."))
        tail = await rest(live)
        assert isinstance(tail[-1], Done) and not [e for e in tail if isinstance(e, Ask)], "two asks, no third"
        assert "Not before Monday." in reply_text(tail), "the model was told why"
        assert w.runs == Counter({NOTICE: 1}), "the allowed call ran once, the denied one never"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_three_calls_are_asked_in_order_and_each_decision_reaches_its_own_call(mode: str) -> None:
    w = world(three_calls, mode, {DEPLOY: True, PUBLISH: True, NOTICE: True})

    async def go() -> None:
        live, request = await pause_at(w)
        names: list[str] = []
        for step in (allow, lambda r: deny(r, "no"), allow):
            assert isinstance(request, Approval)
            names.append(request.subject.name)
            await live.deliver(step(request))
            await until_pause(live)
            request = live.pending  # type: ignore[assignment]
        assert names == [DEPLOY, PUBLISH, NOTICE]
        assert request is None and w.runs == Counter({DEPLOY: 1, NOTICE: 1})
        messages = await w.messages()
        rejected = tool_message(messages, "call-0-1")
        assert rejected.status == "error" and "no" in rejected.text, "the middle call is the denied one"
        assert tool_message(messages, "call-0-0").status != "error" and tool_message(messages, "call-0-2").status != "error"

    run(go())


# --- 2. the approval's shape ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_the_approval_describes_the_call(mode: str) -> None:
    gate = {DEPLOY: {"allowed_decisions": ["reject", "edit", "approve"], "description": "Rolls the release out"}}
    w = world(one_deploy, mode, gate)

    async def go() -> None:
        asked = await approval_at(w)
        (pending,) = (await w.state()).interrupts
        assert asked.id == (f"lg-{pending.id}" if mode == "per_call" else f"lg-{pending.id}-0")
        assert asked.title == f"Approve {DEPLOY}?"
        assert asked.description == "Rolls the release out"
        assert asked.answer_by.role == "person"
        assert asked.decisions == ["allow", "edit", "deny"], "in the standard's order, whatever order the graph lists"
        assert (asked.subject.type, asked.subject.name, asked.subject.args) == ("tool_call", DEPLOY, {"version": "1.2"})
        schema = asked.subject.args_schema
        assert schema is not None and set(schema["properties"]) == {"version", "region"}
        assert "title" not in schema

    run(go())


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("allowed", "offered"),
    [
        (["approve", "reject"], ["allow", "deny"]),
        (["approve"], ["allow"]),
        (["reject"], ["deny"]),
        (["approve", "edit"], ["allow", "edit"]),
        (["approve", "reject", "respond"], ["allow", "deny"]),
        (EVERYTHING, ["allow", "edit", "deny"]),
    ],
    ids=["approve+reject", "approve", "reject", "approve+edit", "respond is dropped", "default"],
)
def test_only_what_the_call_allows_is_offered(mode: str, allowed: Any, offered: list[str]) -> None:
    gate = {DEPLOY: True if allowed is EVERYTHING else {"allowed_decisions": allowed}}
    w = world(one_deploy, mode, gate)

    async def go() -> None:
        asked = await approval_at(w)
        assert asked.decisions == offered
        assert (asked.subject.args_schema is not None) == ("edit" in offered), "a schema only where edit is offered"

    run(go())


# --- 3. edit ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_an_edit_runs_the_tool_with_the_new_arguments(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: True})

    async def go() -> None:
        live, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        await live.deliver(edit(asked, {"version": "2.0", "region": "south"}))
        tail = await rest(live)
        assert isinstance(tail[-1], Done)
        assert w.runs == Counter({DEPLOY: 1})
        assert "deployed 2.0 to south" in reply_text(tail)

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_an_edit_cannot_rename_the_tool(mode: str) -> None:
    """An R2C answer has no tool name; a stray one is ignored and the call's own tool runs."""
    w = world(one_deploy, mode, {DEPLOY: True, NOTICE: True})

    async def go() -> None:
        live, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        await live.deliver(edit(asked, {"version": "2.0"}, name=NOTICE))
        tail = await rest(live)
        assert isinstance(tail[-1], Done)
        assert w.runs == Counter({DEPLOY: 1}), "send_notice did not run in the place of deploy_release"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_arguments_that_break_the_tools_schema_are_refused_before_the_graph(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: True})

    async def go() -> None:
        _, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        error, tail = await refused(w, asked, edit(asked, {"version": 5}), allow(asked))
        assert "not acceptable" in error.reason and "text" in error.reason, error.reason
        assert w.runs == Counter({DEPLOY: 1}), "the later right answer ran the call"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_decision_the_call_does_not_allow_is_refused_before_the_graph(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: {"allowed_decisions": ["approve", "reject"]}})

    async def go() -> None:
        _, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        error, _ = await refused(w, asked, edit(asked, {"version": "2.0"}), allow(asked))
        assert "not acceptable" in error.reason and "Edit is not offered" in error.reason, error.reason

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_tool_the_graph_hides_cannot_be_edited(mode: str) -> None:
    w = hidden(one_deploy, mode, {DEPLOY: True})

    async def go() -> None:
        live, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        assert asked.decisions == ["allow", "deny"], "no schema to check an edit against: no edit"
        assert asked.subject.args_schema is None
        await live.deliver(allow(asked))
        tail = await rest(live)
        assert isinstance(tail[-1], Done) and w.runs == Counter({DEPLOY: 1})

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_call_that_allows_only_an_edit_nobody_can_check_ends_failed_before_any_ask(mode: str) -> None:
    w = hidden(one_deploy, mode, {DEPLOY: {"allowed_decisions": ["edit"]}})

    async def go() -> None:
        events = [e async for e in Driver(w.source).start(THREAD, RunInput("go"))]
        assert not [e for e in events if isinstance(e, Ask)], "nothing is asked"
        error = events[-1]
        assert isinstance(error, Error) and error.code == "failed"
        assert DEPLOY in error.reason and "edit" in error.reason, error.reason
        assert (await w.state()).interrupts, "the graph still waits: the run is over, the pause is not"

    run(go())


# --- 4. respond-only: a question ---------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_a_call_that_allows_only_a_reply_is_asked_as_a_question(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: {"allowed_decisions": ["respond"], "description": "Say what to return"}})

    async def go() -> None:
        live, asked = await pause_at(w)
        (pending,) = (await w.state()).interrupts
        assert isinstance(asked, Question) and asked.answer_by.role == "person"
        assert asked.id == (f"lg-{pending.id}" if mode == "per_call" else f"lg-{pending.id}-0")
        assert DEPLOY in asked.title and asked.description == "Say what to return"
        assert [(f.key, f.type, f.required) for f in asked.fields] == [("reply", "text", True)]
        await live.deliver(reply(asked, "use staging"))
        tail = await rest(live)
        assert isinstance(tail[-1], Done)
        assert not w.runs, "the call did not run: the reply took its place"
        assert "use staging" in reply_text(tail)

    run(go())


# --- 5. declined ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_a_declined_approval_is_a_reject_with_the_note_as_the_message(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: True})

    async def go() -> None:
        live, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        await live.deliver(declined(asked, "later"))
        tail = await rest(live)
        assert isinstance(tail[-1], Done) and not w.runs
        assert "with reason: later" in reply_text(tail)

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_declined_approval_with_no_note_is_a_reject_with_no_message(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: True})

    async def go() -> None:
        live, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        await live.deliver(declined(asked))
        tail = await rest(live)
        assert isinstance(tail[-1], Done) and not w.runs
        assert "was not executed" in reply_text(tail) and "with reason" not in reply_text(tail)

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_a_deny_carries_its_reason_to_the_model(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: True})

    async def go() -> None:
        live, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        await live.deliver(deny(asked, "Not before Monday."))
        tail = await rest(live)
        assert "with reason: Not before Monday." in reply_text(tail)
        no_reason = world(one_deploy, mode, {DEPLOY: True})
        live, asked = await pause_at(no_reason)
        assert isinstance(asked, Approval)
        await live.deliver(deny(asked))
        assert "with reason" not in reply_text(await rest(live))

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_declining_a_call_that_cannot_be_rejected_ends_failed_and_the_pause_stays(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: {"allowed_decisions": ["approve", "edit"]}})

    async def go() -> None:
        _, asked = await pause_at(w)
        assert isinstance(asked, Approval)
        error, tail = await refused(w, asked, declined(asked, "no"), allow(asked))
        assert "cannot be rejected" in error.reason and DEPLOY in error.reason, error.reason
        assert w.runs == Counter({DEPLOY: 1}), "the call ran only when it was allowed"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_declining_a_question_that_only_takes_a_reply_ends_failed_and_the_pause_stays(mode: str) -> None:
    w = world(one_deploy, mode, {DEPLOY: {"allowed_decisions": ["respond"]}})

    async def go() -> None:
        _, asked = await pause_at(w)
        assert isinstance(asked, Question)
        error, tail = await refused(w, asked, declined(asked), reply(asked, "use staging"))
        assert "cannot be rejected" in error.reason, error.reason
        assert "use staging" in reply_text(tail)

    run(go())


def test_a_batch_is_never_sent_with_a_decision_the_graph_would_refuse() -> None:
    """The graph would raise on this batch and could then not continue at all (spec finding 2)."""
    gate = {NOTICE: True, DEPLOY: {"allowed_decisions": ["approve"]}}
    w = world(notice_then_deploy, "batched", gate)

    async def go() -> None:
        live, first = await pause_at(w)
        assert isinstance(first, Approval)
        await live.deliver(allow(first))
        await until_pause(live)
        second = live.pending
        assert isinstance(second, Approval) and second.decisions == ["allow"]

        before, asked = await w.state(), w.calls.n
        await live.deliver(declined(second))  # the bridge refuses: DEPLOY cannot be rejected
        events = await rest(live)
        assert isinstance(events[-1], Error) and events[-1].code == "failed" and "cannot be rejected" in events[-1].reason
        assert w.calls.n == asked and (await w.state()).config == before.config, "the graph was never called"

        tail = [e async for e in Driver(w.source).resume(THREAD, second, allow(second))]
        assert isinstance(tail[-1], Done), "the thread can still go on"
        assert w.runs == Counter({NOTICE: 1, DEPLOY: 1})

    run(go())


# --- 6. a payload that cannot be read (settled point 5) ---------------------------------------------------


def _by_hand(response_schema: Any) -> World:
    """A node that interrupts with the middleware's four keys but gives no usable decisions."""

    def gate(state: MessagesState) -> dict[str, Any]:
        interrupt(
            {"type": "tool_approval", "tool_call_id": "c-1", "name": DEPLOY, "args": {"version": "1.2"}, "description": "Roll"},
            response_schema=response_schema,
        )
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("gate", gate)
    builder.add_edge(START, "gate")
    builder.add_edge("gate", END)
    graph = builder.compile(checkpointer=memory_saver())
    return World(wrap(graph), graph, Counter(), Calls(), None)


@pytest.mark.parametrize("response_schema", [None, dict], ids=["no response schema", "a schema with no decision"])
def test_a_per_call_payload_with_no_readable_decisions_ends_failed_before_any_ask(response_schema: Any) -> None:
    w = _by_hand(response_schema)

    async def go() -> None:
        events = [e async for e in Driver(w.source).start(THREAD, RunInput("go"))]
        assert not [e for e in events if isinstance(e, Ask)], "a call nobody can decide on is not asked"
        error = events[-1]
        assert isinstance(error, Error) and error.code == "failed"
        assert "decisions" in error.reason and DEPLOY in error.reason, error.reason
        assert len((await w.state()).interrupts) == 1, "the graph was left as it was"

    run(go())


# --- 7. SC-006: an approval is never for the caller ----------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_the_middleware_never_yields_an_approval_for_the_caller(mode: str) -> None:
    w = world(notice_then_deploy, mode)

    async def go() -> None:
        live, request = await pause_at(w)
        roles: list[str] = []
        while request is not None:
            assert isinstance(request, Approval)
            roles.append(request.answer_by.role)
            await live.deliver(allow(request))
            await until_pause(live)
            request = live.pending  # type: ignore[assignment]
        assert roles == ["person", "person"]

    run(go())


@pytest.mark.parametrize("approver", [{"role": "person"}, {"role": "approver", "approver_role": "release-manager"}])
def test_a_hand_written_approval_is_asked_as_it_is_for_a_person_or_an_approver(approver: dict[str, str]) -> None:
    written = {
        "kind": "approval", "id": "ap-9", "title": "Publish the page", "answer_by": approver,
        "subject": {"type": "tool_call", "name": PUBLISH, "args": {"slug": "intro"}}, "decisions": ["allow", "deny"],
    }

    @tool("ask_the_approver")
    def ask_the_approver() -> str:
        """Ask for an approval the graph wrote by hand."""
        answer = interrupt(written)
        return f"decided: {answer['decision']}"

    def script(messages: list[BaseMessage]) -> Turn:
        return Say(_summary(messages)) if tool_results(messages) else Call(("ask_the_approver", {}))

    graph = agent(Scripted(script=script), [ask_the_approver], memory_saver())
    source = wrap(graph)

    async def go() -> None:
        live = Driver(source).start(THREAD, RunInput("go"))
        await until_pause(live)
        asked = live.pending
        assert isinstance(asked, Approval) and asked.id == "ap-9" and asked.answer_by.role == approver["role"]
        await live.deliver(_answer(asked, {"decision": "allow"}))
        assert "decided: allow" in reply_text(await rest(live))

    run(go())


# --- 8. the pieces: what the decisions walk reads, and the tools of a graph -----------------------------------


def test_the_allowed_decisions_are_every_type_a_response_schema_names() -> None:
    one = {"type": "object", "properties": {"type": {"const": "approve"}}}
    several = {
        "oneOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}],
        "$defs": {
            "A": {"type": "object", "properties": {"type": {"const": "approve"}}},
            "B": {"type": "object", "properties": {"type": {"const": "edit"}, "edited_action": {"type": "object"}}},
            "C": {"type": "object", "properties": {"type": {"const": "reject"}}},
        },
    }
    assert schema_decisions(one) == frozenset({"approve"})
    assert schema_decisions(several) == frozenset({"approve", "edit", "reject"}), "$defs are walked, wherever they are used"
    for nothing in (None, {}, {"type": "object"}, "approve", ["approve"]):
        assert schema_decisions(nothing) == frozenset(), nothing


def test_the_tools_of_a_create_agent_graph_are_found_by_name_and_a_wrapper_has_none() -> None:
    w = world(one_deploy, "per_call")
    found = tools_by_name(w.graph)
    assert found is not None and set(found) == {DEPLOY, NOTICE, PUBLISH}
    assert tools_by_name(hidden(one_deploy, "per_call", {DEPLOY: True}).graph) is None
    assert tools_by_name(agent(Scripted(script=one_deploy), [], memory_saver())) is None, "no tools, no tool node"


def test_a_tools_schema_is_a_copy_without_its_title_and_without_the_description_a_dict_schema_gets() -> None:
    found = tools_by_name(world(one_deploy, "per_call").graph)
    assert found is not None
    schema = schema_of(found[DEPLOY])
    assert "title" not in schema and set(schema["properties"]) == {"version", "region"} and schema["required"] == ["version"]
    schema["properties"].clear()
    assert set(schema_of(found[DEPLOY])["properties"]) == {"version", "region"}, "a copy: the tool's own is untouched"

    ping = StructuredTool.from_function(
        func=lambda host: host,
        name="ping",
        description="Ping a host",
        args_schema={"type": "object", "properties": {"host": {"type": "string"}}, "required": ["host"]},
    )
    assert schema_of(ping) == {"type": "object", "properties": {"host": {"type": "string"}}, "required": ["host"]}


# --- 9. read_pauses on a state of its own: the order does not depend on how LangGraph lists them -------------


_APPROVE_OR_REJECT: dict[str, Any] = {
    "oneOf": [
        {"type": "object", "properties": {"type": {"const": "approve"}}},
        {"type": "object", "properties": {"type": {"const": "reject"}}},
    ]
}


def _per_call_interrupt(interrupt_id: str, call_id: str, name: str, description: Any = "Needs approval") -> Any:
    return SimpleNamespace(
        id=interrupt_id,
        value={"tool_call_id": call_id, "name": name, "args": {}, "description": description},
        response_schema=_APPROVE_OR_REJECT,
    )


def _state_of(interrupts: list[Any], calls: list[tuple[str, str]]) -> Any:
    """A thread's state: the pending interrupts and the model's last message with its tool calls."""
    message = AIMessage(content="", tool_calls=[{"id": i, "name": n, "args": {}} for i, n in calls])
    return SimpleNamespace(interrupts=interrupts, values={"messages": [message]})


def test_tool_approvals_come_in_the_models_order_whatever_order_the_graph_lists_them_in() -> None:
    state = _state_of(
        [
            _per_call_interrupt("i-late", "c2", "deploy_release"),
            SimpleNamespace(id="own", value=Question(
                id="q-own", title="Which region?", answer_by=AnswerBy(role="person"),
                fields=[Field(key="region", header="Region", text="The region to use", type="text")],
            ).model_dump(exclude_none=True), response_schema=None),
            _per_call_interrupt("i-early", "c1", "send_notice"),
        ],
        [("c1", "send_notice"), ("c2", "deploy_release")],
    )
    pauses = read_pauses(state)
    assert [p.request.id for p in pauses] == ["lg-i-early", "lg-i-late", "q-own"], (
        "the model's order for the calls, then what the graph wrote itself"
    )


@pytest.mark.parametrize("description", ["", None, 7])
def test_a_description_the_middleware_did_not_give_is_left_out_not_shown_as_text(description: Any) -> None:
    state = _state_of([_per_call_interrupt("i", "c1", "send_notice", description)], [("c1", "send_notice")])
    (pause,) = read_pauses(state)
    assert pause.request.description is None
