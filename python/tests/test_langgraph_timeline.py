"""What the caller sees while a run goes on: tool activity, reasoning, usage and files (spec 006, story 4;
R3, R4, R6, R7; FR-009 to FR-012, FR-013; SC-008).

Real `create_agent` graphs and real checkpointers, through the real `Driver`; the model is scripted and
its tools are small real tools. Four parts: tool activity, reasoning (with the pure buffer of `_reasoning`
tested apart), usage, and files. A few tests drive `run_leg` with a stub of the graph, where a real graph
cannot make the event happen on cue (a stream that ends with no node update, a failure that comes with no
callback of the tool's end).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, ToolException, tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from ext_r2c.bridges.langgraph._leg import run_leg
from ext_r2c.bridges.langgraph._reasoning import Reasoning, thoughts
from ext_r2c.bridges.langgraph._reply import Reply
from ext_r2c.bridges.langgraph._usage import usage_of
from ext_r2c.a2a import SourceExecutor, agent_card
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Answer,
    ArtifactEvent,
    Ask,
    BytesContent,
    Done,
    Driver,
    Error,
    Limits,
    Question,
    ReplyChunk,
    RunEvent,
    RunInput,
    UrlContent,
    Usage,
    UsageEvent,
    to_json,
)

from a2a_harness import a2a_client, kinds, send, serve
from agent_source_suite import reply_text, rest, until_pause
from langgraph_graphs import DEPLOY, NOTICE, SUITE_QUESTION, memory_saver, restart, run, sqlite_saver, suite_graph, wrap
from langgraph_models import (
    ENCRYPTED,
    SIGNATURE,
    Call,
    Say,
    Scripted,
    Turn,
    broken,
    hosted,
    linked,
    media,
    vendor,
)
from test_langgraph_approvals import MODES, THREAD, allow, deny, notice_then_deploy, one_deploy, world
from test_langgraph_run import _two_models, events_of, graph_of, sequence

CONFIG = {"configurable": {"thread_id": THREAD}}
LINT = "lint_file"
EXPLODE = "explode"
BIG = "big_report"
LONG = "long_failure"


# --- the tools and the helpers of the tests -------------------------------------------------------


def tools_for(*, wait: asyncio.Event | None = None, entered: asyncio.Event | None = None) -> list[BaseTool]:
    """Small async tools. `deploy_release` waits for `wait` when it is given (and says it is inside by
    setting `entered`), so a test decides when the tool's body goes on; `explode` waits for `entered`."""

    @tool(DEPLOY)
    async def deploy_release(version: str, region: str = "north") -> str:
        """Roll a release out to a region."""
        if entered is not None:
            entered.set()
        if wait is not None:
            await asyncio.wait_for(wait.wait(), 5)
        return f"deployed {version} to {region}"

    @tool(NOTICE)
    async def send_notice(text: str) -> str:
        """Send a short notice to the team."""
        return f"sent: {text}"

    @tool(BIG)
    async def big_report(n: int) -> str:
        """Write a report of `n` characters."""
        return "x" * n

    async def lint(path: str) -> str:
        raise ToolException(f"lint found 3 problems in {path}")

    async def long_failure() -> str:
        raise ToolException("e" * 3000)

    async def explode() -> str:
        if entered is not None:
            await asyncio.wait_for(entered.wait(), 5)
        raise RuntimeError("the tool broke")

    handled = {"handle_tool_error": True}
    return [
        deploy_release,
        send_notice,
        big_report,
        StructuredTool.from_function(coroutine=lint, name=LINT, description="Lint a file.", **handled),
        StructuredTool.from_function(coroutine=long_failure, name=LONG, description="Always fails.", **handled),
        StructuredTool.from_function(coroutine=explode, name=EXPLODE, description="Raises.", args_schema=None),
    ]


def tool_activities(events: list[RunEvent]) -> list[Activity]:
    return [e.activity for e in events if isinstance(e, ActivityEvent) and e.activity.type == "tool"]


def thinking(events: list[RunEvent]) -> list[Activity]:
    return [e.activity for e in events if isinstance(e, ActivityEvent) and e.activity.type == "reasoning"]


def states(events: list[RunEvent], call_id: str) -> list[str | None]:
    """The states one tool call went through, in order."""
    return [a.state for a in tool_activities(events) if a.id == call_id]


def positions(events: list[RunEvent], kind: type) -> list[int]:
    return [i for i, e in enumerate(events) if isinstance(e, kind)]


def chunks_of(events: list[RunEvent]) -> list[ReplyChunk]:
    return [e for e in events if isinstance(e, ReplyChunk)]


def usage_events(events: list[RunEvent]) -> list[Usage]:
    return [e.usage for e in events if isinstance(e, UsageEvent)]


def artifacts(events: list[RunEvent]) -> list[ArtifactEvent]:
    return [e for e in events if isinstance(e, ArtifactEvent)]


async def ai_ids(graph: Any) -> list[str]:
    """The ids of the AI messages the thread holds, in order."""
    state = await graph.aget_state(CONFIG)
    return [m.id for m in state.values["messages"] if isinstance(m, AIMessage)]


def answer_for(request: Any, value: dict[str, Any]) -> Answer:
    return Answer.parse(
        {"kind": "answer", "id": request.id, "answered_by": {"role": "person"}, "outcome": "answered", "value": value}
    )


def valid(activities: list[Activity]) -> None:
    for activity in activities:
        to_json(activity)  # each one breaks no rule of the schema


# --- 1. tool activity -------------------------------------------------------------------------------


def test_a_tool_call_is_one_activity_running_then_done_with_its_duration() -> None:
    script = sequence(Call((NOTICE, {"text": "a"})), Say("All sent."))
    events = run(events_of(wrap(graph_of(script, tools=tools_for()))))
    seen = tool_activities(events)
    assert [a.state for a in seen] == ["running", "done"]
    started, ended = seen
    assert started.id == ended.id == "call-0-0", "the id is the tool call's id"
    for a in seen:
        assert (a.type, a.name, a.label) == ("tool", NOTICE, NOTICE)
        assert (a.args, a.detail) == (None, None), "nothing is exposed by default"
    assert started.duration_ms is None and isinstance(ended.duration_ms, int) and ended.duration_ms >= 0
    valid(seen)
    first_reply = positions(events, ReplyChunk)[0]
    assert max(positions(events, ActivityEvent)) < first_reply, "the tool is over before the model says its words"


def test_running_is_seen_while_the_tool_runs() -> None:
    wait = asyncio.Event()
    script = sequence(Call((DEPLOY, {"version": "1.2"})), Say("Rolled out."))
    source = wrap(graph_of(script, tools=tools_for(wait=wait)))

    async def go() -> None:
        seen: list[RunEvent] = []
        async for event in Driver(source).start(THREAD, RunInput("go")):
            seen.append(event)
            if isinstance(event, ActivityEvent) and event.activity.state == "running":
                assert not wait.is_set()
                wait.set()  # the body goes on only after the caller was told it runs
        assert [a.state for a in tool_activities(seen)] == ["running", "done"], seen
        assert isinstance(seen[-1], Done)

    run(go())


def test_a_tool_that_reports_an_error_ends_failed_and_the_run_goes_on() -> None:
    script = sequence(Call((LINT, {"path": "a.py"})), Say("Noted."))
    events = run(events_of(wrap(graph_of(script, tools=tools_for()))))
    seen = tool_activities(events)
    assert [a.state for a in seen] == ["running", "failed"]
    assert seen[-1].detail is None, "the message is not shown unless the tool is exposed"
    assert isinstance(events[-1], Done) and reply_text(events) == "Noted."


@pytest.mark.parametrize("exposed", [False, True])
def test_a_tool_that_raises_ends_failed_and_then_the_run_ends_failed(exposed: bool) -> None:
    script = sequence(Call((EXPLODE, {})))
    options = {"expose_tools": {EXPLODE}} if exposed else {}
    events = run(events_of(wrap(graph_of(script, tools=tools_for()), **options)))
    seen = tool_activities(events)
    assert [a.state for a in seen] == ["running", "failed"]
    assert isinstance(seen[-1].duration_ms, int)
    assert seen[-1].detail == ("the tool broke" if exposed else None)
    assert isinstance(events[-1], Error) and events[-1].code == "failed" and "the tool broke" in events[-1].reason
    assert max(positions(events, ActivityEvent)) < len(events) - 1, "the activity is closed before the run ends"
    valid(seen)


@pytest.mark.parametrize("mode", MODES)
def test_a_call_waiting_for_approval_has_no_activity_and_a_denied_one_never_has(mode: str) -> None:
    async def go() -> None:
        w = world(one_deploy, mode)
        live = Driver(w.source).start(THREAD, RunInput("go"))
        before = await until_pause(live)
        assert isinstance(before[-1], Ask) and live.pending is not None
        assert not tool_activities(before), "waiting for approval is not running"
        await live.deliver(deny(live.pending, "not now"))
        after = await rest(live)
        assert not tool_activities(after), "a denied call never ran, so it shows nothing"
        assert not w.runs

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_an_approved_call_shows_running_then_done_after_the_answer(mode: str) -> None:
    async def go() -> None:
        w = world(one_deploy, mode)
        live = Driver(w.source).start(THREAD, RunInput("go"))
        before = await until_pause(live)
        assert live.pending is not None and not tool_activities(before)
        await live.deliver(allow(live.pending))
        after = await rest(live)
        assert states(after, "call-0-0") == ["running", "done"]
        assert w.runs == Counter({DEPLOY: 1})

    run(go())


def test_per_call_an_ungated_call_shows_its_activity_while_the_gated_one_shows_none() -> None:
    async def go() -> None:
        w = world(notice_then_deploy, "per_call", gate={DEPLOY: True})
        live = Driver(w.source).start(THREAD, RunInput("go"))
        before = await until_pause(live)
        assert states(before, "call-0-0") == ["running", "done"], "send_notice is not gated: it ran"
        assert states(before, "call-0-1") == [], "deploy_release waits for approval: no activity"

    run(go())


def test_a_tool_that_pauses_inside_its_body_stays_running_and_reports_running_again_when_resumed() -> None:
    source = wrap(suite_graph(memory_saver()))

    async def go() -> None:
        live = Driver(source).start(THREAD, RunInput("a report"))
        before = await until_pause(live)
        assert isinstance(before[-1], Ask) and isinstance(live.pending, Question)
        assert states(before, "call-0-0") == ["running"], "a pause is not a failure: the call goes on"
        await live.deliver(answer_for(live.pending, {"title": "October"}))
        after = await rest(live)
        assert states(after, "call-0-0") == ["running", "done"], "the body started again from its top"

    run(go())


# --- 1b. what an owner exposes ---------------------------------------------------------------------


def test_an_exposed_tool_shows_its_args_and_its_result_and_another_tool_does_not() -> None:
    script = sequence(Call((NOTICE, {"text": "a"}), (DEPLOY, {"version": "1.2"})), Say("Done."))
    graph = graph_of(script, tools=tools_for())
    events = run(events_of(wrap(graph, expose_tools={DEPLOY})))
    deploy = [a for a in tool_activities(events) if a.name == DEPLOY]
    notice = [a for a in tool_activities(events) if a.name == NOTICE]
    assert [a.state for a in deploy] == ["running", "done"] and [a.state for a in notice] == ["running", "done"]
    assert [a.args for a in deploy] == [{"version": "1.2"}] * 2, "the call's own input, on every update"
    assert [a.detail for a in deploy] == [None, "deployed 1.2 to north"], "the result comes with the end"
    assert all(a.args is None and a.detail is None for a in notice), "R2C-ACTIVITY-6: only what the owner exposed"
    valid(deploy + notice)


@pytest.mark.parametrize(
    ("name", "args", "char"),
    [(BIG, {"n": 5000}, "x"), (LONG, {}, "e")],
    ids=["a long result", "a long failure message"],
)
def test_detail_is_cut_at_2000_characters(name: str, args: dict[str, Any], char: str) -> None:
    script = sequence(Call((name, args)), Say("ok"))
    events = run(events_of(wrap(graph_of(script, tools=tools_for()), expose_tools={name})))
    assert tool_activities(events)[-1].detail == char * 2000


def test_a_result_that_fits_is_not_cut() -> None:
    script = sequence(Call((BIG, {"n": 2000})), Say("ok"))
    events = run(events_of(wrap(graph_of(script, tools=tools_for()), expose_tools={BIG})))
    assert tool_activities(events)[-1].detail == "x" * 2000


# --- 1c. when the graph raises, and a cancel -------------------------------------------------------


def test_when_the_graph_raises_each_activity_still_running_ends_failed_once_before_the_error() -> None:
    wait, entered = asyncio.Event(), asyncio.Event()  # `wait` is never set: deploy waits until it is cancelled
    script = sequence(Call((DEPLOY, {"version": "1.2"}), (EXPLODE, {})))
    events = run(events_of(wrap(graph_of(script, tools=tools_for(wait=wait, entered=entered)))))
    for call_id in ("call-0-0", "call-0-1"):
        assert states(events, call_id) == ["running", "failed"], f"{call_id}: one running, then one failed"
    assert isinstance(events[-1], Error) and events[-1].code == "failed"
    assert max(positions(events, ActivityEvent)) < len(events) - 1


class _Stub:
    """A graph that gives `run_leg` a stream the real graph cannot be made to give on cue."""

    def __init__(self, *, start: Callable[[Any], Any] | None = None, parts: tuple[Any, ...] = (), error: Exception | None = None):
        self._start, self._parts, self._error = start, parts, error

    async def astream(self, graph_input: Any, config: dict[str, Any], **kwargs: Any) -> Any:
        if self._start is not None:
            await self._start(config["callbacks"][0])
        for part in self._parts:
            yield part
        if self._error is not None:
            raise self._error

    async def aget_state(self, config: Any) -> Any:
        return SimpleNamespace(interrupts=(), values={"messages": []})


def _no_pick(state: Any) -> Any:
    raise AssertionError("nothing is pending, so nothing is asked")


async def _leg(stub: Any, **options: Any) -> tuple[list[RunEvent], BaseException | None]:
    out: list[RunEvent] = []
    try:
        async for event in run_leg(stub, {}, "t-1", Reply(), _no_pick, **options):
            out.append(event)
    except Exception as error:  # noqa: BLE001 - what the leg raises is what the test looks at
        return out, error
    return out, None


def test_the_leg_closes_a_running_activity_when_the_stream_raises_with_no_callback_of_its_end() -> None:
    async def start(handler: Any) -> None:
        await handler.on_tool_start({"name": DEPLOY}, "", run_id=uuid4(), inputs={"version": "1.2"}, tool_call_id="tc-1")

    async def go() -> None:
        events, error = await _leg(_Stub(start=start, error=RuntimeError("the graph broke")))
        assert isinstance(error, RuntimeError) and "the graph broke" in str(error), "the failure goes on"
        seen = tool_activities(events)
        assert [(a.id, a.state) for a in seen] == [("tc-1", "running"), ("tc-1", "failed")]
        assert seen[-1].name == DEPLOY and isinstance(seen[-1].duration_ms, int)
        assert (seen[0].args, seen[-1].detail) == (None, None), "nothing is exposed here either"

    run(go())


def test_an_input_that_is_not_json_is_not_an_arg() -> None:
    """A tool that asked for injected state has more than JSON in its input: nothing of it is sent."""
    from ext_r2c.bridges.langgraph._handler import Handler, ToolStarted

    async def go() -> None:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        handler = Handler(queue)
        await handler.on_tool_start({"name": DEPLOY}, "", run_id=uuid4(), inputs={"version": "1.2"}, tool_call_id="a")
        await handler.on_tool_start({"name": DEPLOY}, "", run_id=uuid4(), inputs={"state": object()}, tool_call_id="b")
        await handler.on_tool_start({"name": DEPLOY}, "", run_id=uuid4(), tool_call_id="c")
        started = [queue.get_nowait() for _ in range(3)]
        assert all(isinstance(s, ToolStarted) for s in started)
        assert [s.args for s in started] == [{"version": "1.2"}, None, None]

    run(go())


def test_a_cancel_emits_nothing_more_and_leaves_no_task_running() -> None:
    wait, entered = asyncio.Event(), asyncio.Event()
    script = sequence(Call((DEPLOY, {"version": "1.2"})), Say("Rolled out."))
    source = wrap(graph_of(script, tools=tools_for(wait=wait, entered=entered)))

    async def go() -> None:
        before = set(asyncio.all_tasks())
        live = Driver(source).start(THREAD, RunInput("go"))
        async for event in live:
            if isinstance(event, ActivityEvent) and event.activity.state == "running":
                break
        await live.cancel()
        tail = await rest(live)
        assert [type(e) for e in tail] == [Error] and tail[0].code == "cancelled", "no `failed` activity follows"
        for _ in range(100):
            if not {t for t in asyncio.all_tasks() - before if not t.done()}:
                break
            await asyncio.sleep(0.01)
        assert not {t for t in asyncio.all_tasks() - before if not t.done()}, "a task of the bridge still runs"

    run(go())


# --- 1d. a tool a node calls itself ----------------------------------------------------------------


def _node_graph(body: Callable[[BaseTool], Any]) -> Any:
    """A graph with one node that calls the notice tool its own way."""
    notice = next(t for t in tools_for() if t.name == NOTICE)

    async def act(state: MessagesState) -> dict[str, Any]:
        await body(notice)
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("act", act)
    builder.add_edge(START, "act")
    builder.add_edge("act", END)
    return builder.compile(checkpointer=memory_saver())


def test_a_tool_a_node_calls_without_a_tool_call_is_shown_under_its_run_id() -> None:
    async def body(t: BaseTool) -> None:
        await t.ainvoke({"text": "b"})  # no config passed: it still travels with the run

    events = run(events_of(wrap(_node_graph(body))))
    seen = tool_activities(events)
    assert [a.state for a in seen] == ["running", "done"]
    assert seen[0].id == seen[1].id and isinstance(UUID(seen[0].id), UUID), "no call id: the run id stands for it"
    assert seen[0].name == NOTICE


def test_a_tool_called_with_callbacks_of_its_own_shows_nothing() -> None:
    """The limit that is left: a caller that replaces the run's callbacks hides what it calls."""

    async def body(t: BaseTool) -> None:
        await t.ainvoke({"text": "b"}, {"callbacks": []})

    assert not tool_activities(run(events_of(wrap(_node_graph(body))))), "nothing reached the handler"


# --- 2. reasoning: the buffer, apart from any graph ---------------------------------------------------

THOUGHTS = ("Let me look at the numbers first. ", "Then I will write the report for the team. ", "Last, check it once.")
FIRST = THOUGHTS[0] + THOUGHTS[1]  # 77 characters, ends at a sentence end followed by a space


def _fed(*deltas: str, end: bool = True) -> list[str]:
    buffer, out = Reasoning(), []
    for delta in deltas:
        out += buffer.feed("m1", delta)
    return out + (buffer.end("m1") if end else [])


def test_a_short_thought_waits_for_the_end_of_its_message() -> None:
    buffer = Reasoning()
    assert buffer.feed("m1", "Let me think.") == []
    assert buffer.end("m1") == ["Let me think."]
    assert buffer.end("m1") == [], "once sent, it is not sent again"


def test_a_sentence_end_lets_the_buffer_leave_once_it_holds_40_characters() -> None:
    forty = "a" * 39 + "."
    assert _fed(forty + " next", end=False) == [forty + " "], "40 characters up to the full stop, and the space goes with it"
    short = "a" * 38 + "."
    assert _fed(short + " next", end=False) == [], "39 characters are not enough: it waits for more"
    assert _fed(short + " next one over here.", end=False) == [], "and the later full stop has no space after it yet"
    assert _fed(short + " next one over here. ", end=False) == [short + " next one over here. "]


def test_a_newline_ends_a_piece_as_a_sentence_end_does() -> None:
    assert _fed("a" * 39 + "\nrest", end=False) == ["a" * 39 + "\n"]
    assert _fed("a" * 38 + "\nrest", end=False) == []


def test_a_full_stop_with_no_space_after_it_is_not_a_sentence_end() -> None:
    assert _fed("The value is about 3.14159 and we keep it as it is", end=False) == []


def test_a_sentence_end_alone_at_the_end_of_the_buffer_waits_for_the_next_character() -> None:
    forty = "a" * 39 + "."
    buffer = Reasoning()
    assert buffer.feed("m1", forty) == [], "it could be a decimal point: the next character decides"
    assert buffer.feed("m1", " and on") == [forty + " "]
    assert buffer.end("m1") == ["and on"]


def test_the_pieces_follow_the_deltas_the_model_sent() -> None:
    assert _fed(*THOUGHTS) == [FIRST, THOUGHTS[2]]
    assert _fed(FIRST + THOUGHTS[2]) == [FIRST, THOUGHTS[2]], "the same text in one delta: the same pieces"
    assert "".join(_fed(*list(FIRST + THOUGHTS[2]))) == FIRST + THOUGHTS[2], "a character at a time loses none"


def test_a_long_run_with_no_sentence_end_is_cut_at_a_space_near_400_characters() -> None:
    words = "word " * 90  # 450 characters
    assert _fed(words) == [words[:400], words[400:]]
    assert _fed(*(["word "] * 90)) == [words[:400], words[400:]], "a word at a time cuts at the same place"
    assert _fed("word " * 79 + "word") == ["word " * 79 + "word"], "399 characters: nothing yet"


def test_a_long_run_with_no_space_is_cut_at_400_characters() -> None:
    assert _fed("z" * 450) == ["z" * 400, "z" * 50]


def test_the_buffers_of_two_messages_are_apart_and_drain_gives_what_is_left() -> None:
    buffer = Reasoning()
    buffer.feed("m1", "first thought")
    buffer.feed("m2", "second thought")
    assert buffer.end("m1") == ["first thought"]
    assert buffer.drain() == [("m2", "second thought")]
    assert buffer.drain() == []


def test_an_empty_delta_adds_nothing() -> None:
    buffer = Reasoning()
    assert buffer.feed("m1", "") == [] and buffer.end("m1") == []


def test_only_the_standard_reasoning_text_is_read_from_a_message() -> None:
    message = AIMessage(
        content=[
            {"type": "reasoning", "reasoning": "First idea.", "extras": {"signature": SIGNATURE}},
            {"type": "text", "text": "visible"},
            vendor({"type": "redacted_thinking", "data": ENCRYPTED}),
            {"type": "reasoning", "reasoning": "Second idea."},
        ]
    )
    assert thoughts(message) == "First idea.\n\nSecond idea.", "blocks are parts: a blank line between them"
    assert thoughts(AIMessage(content="plain")) == ""
    assert thoughts(AIMessage(content=[{"type": "reasoning", "reasoning": "", "extras": {"signature": SIGNATURE}}])) == ""


# --- 2b. reasoning through a graph ------------------------------------------------------------------


def test_reasoning_is_off_by_default_though_the_model_reasons() -> None:
    events = run(events_of(wrap(graph_of(sequence(Say("Done.", reasoning=THOUGHTS))))))
    assert not thinking(events)
    assert reply_text(events) == "Done."


@pytest.mark.parametrize("streams", [True, False], ids=["streamed", "whole message"])
def test_with_the_option_on_reasoning_is_one_activity_per_message_in_readable_pieces(streams: bool) -> None:
    graph = graph_of(sequence(Say("Done.", reasoning=THOUGHTS)), streams=streams)
    events = run(events_of(wrap(graph, reasoning=True)))
    seen = thinking(events)
    (message_id,) = run(ai_ids(graph))
    assert {a.id for a in seen} == {f"reasoning-{message_id}"}, "one activity, whatever the number of pieces"
    for a in seen:
        assert (a.type, a.label, a.state, a.name) == ("reasoning", "Thinking", None, None)
        assert a.args is None and a.detail is None and a.duration_ms is None
    assert [a.delta for a in seen] == [FIRST, THOUGHTS[2]]
    assert max(positions(events, ActivityEvent)) < positions(events, ReplyChunk)[0], "the thoughts come before the words"
    valid(seen)
    assert reply_text(events) == "Done."


def test_the_last_thought_leaves_before_the_first_word_of_a_reply_of_many_words() -> None:
    """A reply of one word is held to the end of the turn and hides the order: with many words the first
    chunk leaves while the model is still talking, so the thoughts must already be out."""
    graph = graph_of(sequence(Say("The report is ready for review today", reasoning=THOUGHTS)))
    events = run(events_of(wrap(graph, reasoning=True)))
    assert len(chunks_of(events)) > 2, "the reply has several chunks"
    assert [a.delta for a in thinking(events)] == [FIRST, THOUGHTS[2]]
    assert max(positions(events, ActivityEvent)) < positions(events, ReplyChunk)[0]


@pytest.mark.parametrize("streams", [True, False], ids=["streamed", "whole message"])
def test_the_thoughts_of_a_message_that_only_calls_a_tool_leave_before_the_tool_runs(streams: bool) -> None:
    script = sequence(Call((NOTICE, {"text": "a"}), reasoning=("A short thought.",)), Say("All sent."))
    graph = graph_of(script, tools=tools_for(), streams=streams)
    events = run(events_of(wrap(graph, reasoning=True)))
    assert [a.delta for a in thinking(events)] == ["A short thought."]
    first = next(e for e in events if isinstance(e, ActivityEvent))
    assert first.activity.type == "reasoning", "the thought is out before the tool is reported"


@pytest.mark.parametrize("streams", [True, False], ids=["streamed", "whole message"])
def test_a_long_thought_with_no_sentence_end_leaves_in_pieces_of_about_400_characters(streams: bool) -> None:
    pieces = tuple("word " for _ in range(100))
    graph = graph_of(sequence(Say("Done.", reasoning=pieces)), streams=streams)
    seen = thinking(run(events_of(wrap(graph, reasoning=True))))
    assert [a.delta for a in seen] == ["word " * 80, "word " * 20]


def test_reasoning_still_in_the_buffer_at_a_pause_leaves_with_the_ask() -> None:
    model = Scripted(script=lambda messages: Say("", reasoning=("A short thought.",)))  # no words: nothing ends it

    async def talk_then_ask(state: MessagesState, config: RunnableConfig) -> dict[str, Any]:
        await model.ainvoke(state["messages"], config)  # it reasons, then the node waits: no message is written
        interrupt(SUITE_QUESTION)
        return {}

    builder = StateGraph(MessagesState)
    builder.add_node("talk", talk_then_ask)
    builder.add_edge(START, "talk")
    builder.add_edge("talk", END)
    source = wrap(builder.compile(checkpointer=memory_saver()), reasoning=True)

    async def go() -> None:
        events = await until_pause(Driver(source).start(THREAD, RunInput("go")))
        assert isinstance(events[-1], Ask)
        assert [a.delta for a in thinking(events)] == ["A short thought."], "it left before the question was asked"

    run(go())


def test_reasoning_still_in_the_buffer_when_the_turn_ends_leaves_before_the_end() -> None:
    chunk = AIMessageChunk(content=[{"type": "reasoning", "reasoning": "No node update follows.", "index": 0}], id="m-9")  # type: ignore[list-item]
    stub = _Stub(parts=({"type": "messages", "ns": (), "data": (chunk, {})},))

    async def go() -> None:
        events, error = await _leg(stub, reasoning=True)
        assert error is None
        assert [(a.id, a.delta) for a in thinking(events)] == [("reasoning-m-9", "No node update follows.")]
        events, error = await _leg(stub)
        assert error is None and not thinking(events), "and with the option off, nothing"

    run(go())


@pytest.mark.parametrize("on", [True, False], ids=["option on", "option off"])
@pytest.mark.parametrize("streams", [True, False], ids=["streamed", "whole message"])
def test_a_signature_an_encrypted_block_and_a_vendor_block_never_leave(streams: bool, on: bool) -> None:
    turn = Say("Done.", reasoning=("Thinking it over now. ",), sealed=True)
    events = run(events_of(wrap(graph_of(sequence(turn), streams=streams), reasoning=on)))
    text = repr(events)
    assert SIGNATURE not in text and ENCRYPTED not in text, "R2C-ACTIVITY-5"
    assert not artifacts(events), "an encrypted block is not a file"
    assert "".join(a.delta or "" for a in thinking(events)) == ("Thinking it over now. " if on else "")


def test_a_signature_with_no_reasoning_text_makes_no_activity() -> None:
    events = run(events_of(wrap(graph_of(sequence(Say("Done.", sealed=True))), reasoning=True)))
    assert not thinking(events) and reply_text(events) == "Done."


def test_the_reasoning_of_a_hidden_model_call_is_not_sent() -> None:
    hidden = Scripted(script=lambda m: Say("private notes", reasoning=("Private thoughts of the helper. ",)))
    visible = Scripted(script=lambda m: Say("public answer", reasoning=("Public thoughts for the reader. ",)))
    events = run(events_of(wrap(_two_models(hidden, visible), reasoning=True)))
    assert "".join(a.delta or "" for a in thinking(events)) == "Public thoughts for the reader. "


# --- 3. usage ------------------------------------------------------------------------------------------


def test_several_model_calls_send_one_cumulative_usage_with_the_model_name_after_the_reply() -> None:
    script = sequence(
        Call((NOTICE, {"text": "a"}), tokens=(5, 2), model="model-a"), Say("All sent.", tokens=(7, 3), model="model-b")
    )
    events = run(events_of(wrap(graph_of(script, tools=tools_for()))))
    (usage,) = usage_events(events)
    assert (usage.input_tokens, usage.output_tokens, usage.model) == (12, 5, "model-b"), "the sum, the last name"
    assert usage.cost is None and usage.duration_ms is None, "nothing the model did not report"
    to_json(usage)
    assert positions(events, UsageEvent)[0] > positions(events, ReplyChunk)[-1], "after the last reply chunk"
    assert isinstance(events[-1], Done) and positions(events, UsageEvent)[0] == len(events) - 2, "just before done"


def test_the_model_name_is_the_last_one_that_was_not_empty() -> None:
    script = sequence(Call((NOTICE, {"text": "a"}), tokens=(5, 2), model="model-a"), Say("All sent.", tokens=(7, 3)))
    (usage,) = usage_events(run(events_of(wrap(graph_of(script, tools=tools_for())))))
    assert usage.model == "model-a"


def test_a_turn_with_no_model_name_has_none() -> None:
    (usage,) = usage_events(run(events_of(wrap(graph_of(sequence(Say("Hi", tokens=(1, 1))))))))
    assert usage.model is None
    assert to_json(usage) == {"kind": "usage", "input_tokens": 1, "output_tokens": 1}, "no `model: null` on the wire"


def test_a_field_the_model_did_not_report_is_absent_not_zero() -> None:
    only_input = AIMessage.model_construct(content="x", usage_metadata={"input_tokens": 5}, response_metadata={})
    usage = usage_of([only_input])
    assert usage is not None and (usage.input_tokens, usage.output_tokens) == (5, None)
    assert to_json(usage) == {"kind": "usage", "input_tokens": 5}, "absent on the wire, not zero and not null"
    assert usage_of([AIMessage(content="nothing reported")]) is None, "no tokens at all: no usage at all"
    assert usage_of([AIMessage.model_construct(content="x", usage_metadata={"input_tokens": True}, response_metadata={})]) is None


@pytest.mark.parametrize("mode", MODES)
def test_usage_is_not_sent_at_a_pause_but_once_at_the_end(mode: str) -> None:
    async def go() -> None:
        w = world(one_deploy, mode)
        live = Driver(w.source).start(THREAD, RunInput("go"))
        before = await until_pause(live)
        assert not usage_events(before), "the turn is not over"
        assert live.pending is not None
        await live.deliver(allow(live.pending))
        after = await rest(live)
        (usage,) = usage_events(after)
        assert (usage.input_tokens, usage.output_tokens) == (14, 6), "both model calls of the turn: (6, 2) and (8, 4)"

    run(go())


def test_the_tokens_of_a_hidden_message_count_because_they_were_spent() -> None:
    hidden = Scripted(script=lambda m: Say("private notes here", tokens=(3, 3)))
    visible = Scripted(script=lambda m: Say("public answer", tokens=(4, 2)))
    (usage,) = usage_events(run(events_of(wrap(_two_models(hidden, visible)))))
    assert (usage.input_tokens, usage.output_tokens) == (7, 5)


def test_the_tokens_of_a_structured_reply_count() -> None:
    from langchain.agents.structured_output import ToolStrategy

    class Result(BaseModel):
        status: str
        message: str

    model = Scripted(script=sequence(Call(("Result", {"status": "completed", "message": "ok"}), tokens=(9, 3))))
    from langgraph_graphs import agent

    graph = agent(model, [], memory_saver(), response_format=ToolStrategy(Result))
    (usage,) = usage_events(run(events_of(wrap(graph))))
    assert (usage.input_tokens, usage.output_tokens) == (9, 3)


def test_a_new_turn_counts_from_zero() -> None:
    async def go() -> None:
        source = wrap(graph_of(sequence(Say("one", tokens=(4, 1)), Say("two", tokens=(10, 5)))))
        first = await events_of(source, "first")
        second = await events_of(source, "second")
        assert [(u.input_tokens, u.output_tokens) for u in usage_events(first)] == [(4, 1)]
        assert [(u.input_tokens, u.output_tokens) for u in usage_events(second)] == [(10, 5)], "not (14, 6)"

    run(go())


@pytest.mark.parametrize("mode", MODES)
def test_the_total_is_the_same_after_a_restart_in_the_middle_of_the_turn(mode: str, tmp_path: Path) -> None:
    """SC-008, scenario 6: the first model call ran in one process, the second in another."""
    path = tmp_path / "usage.db"

    async def go() -> None:
        async with sqlite_saver(path) as saver_a:
            a = world(one_deploy, mode, saver=saver_a)
            live = Driver(a.source).start(THREAD, RunInput("go"))
            await until_pause(live)
            assert live.pending is not None
            asked = live.pending
        async with restart(path) as saver_b:
            b = world(one_deploy, mode, saver=saver_b, runs=a.runs, calls=a.calls)
            events = [e async for e in Driver(b.source).resume(THREAD, asked, allow(asked))]
            (usage,) = usage_events(events)
            assert (usage.input_tokens, usage.output_tokens) == (14, 6), "the model call of the other process counts"

    run(go())


# --- 4. files ----------------------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n-pixels"
PDF = b"%PDF-1.7 report"
WAV = b"RIFF....WAVE"
MP4 = b"\x00\x00\x00\x18ftypmp42"


@pytest.mark.parametrize("streams", [True, False], ids=["streamed", "whole message"])
@pytest.mark.parametrize(
    ("kind", "data", "mime"),
    [("image", PNG, "image/png"), ("file", PDF, "application/pdf"), ("audio", WAV, "audio/wav"), ("video", MP4, "video/mp4")],
)
def test_a_file_block_with_bytes_becomes_a_file_artifact(kind: str, data: bytes, mime: str, streams: bool) -> None:
    graph = graph_of(sequence(Say("Here it is.", blocks=(media(kind, data, mime),))), streams=streams)
    events = run(events_of(wrap(graph)))
    (message_id,) = run(ai_ids(graph))
    (artifact,) = artifacts(events)
    assert artifact.id == f"{message_id}-1", "the block's position in the message: the text is block 0"
    assert artifact.meta.presentation == "file" and artifact.meta.state is None
    assert artifact.parts == (BytesContent(data, mime),) and artifact.name is None
    assert reply_text(events) == "Here it is." and isinstance(events[-1], Done)


def test_a_file_block_with_a_url_becomes_a_url_part_and_the_name_is_read_from_its_extras() -> None:
    block = linked("file", "https://files.example.com/a.pdf", "application/pdf", filename="a.pdf")
    (artifact,) = artifacts(run(events_of(wrap(graph_of(sequence(Say("See it.", blocks=(block,))))))))
    assert artifact.parts == (UrlContent("https://files.example.com/a.pdf", "application/pdf", "a.pdf"),)
    assert artifact.name == "a.pdf"


def test_the_name_is_read_from_name_too_and_only_when_it_is_a_string() -> None:
    said = Say("Files.", blocks=(media("image", PNG, "image/png", name="chart.png"), media("image", PNG, "image/png", filename=5)))
    first, second = artifacts(run(events_of(wrap(graph_of(sequence(said))))))
    assert (first.name, second.name) == ("chart.png", None)
    assert first.parts[0].name == "chart.png" and second.parts[0].name is None


def test_a_file_with_no_media_type_goes_as_octet_stream() -> None:
    block = {"type": "file", "base64": "QUJD"}
    (artifact,) = artifacts(run(events_of(wrap(graph_of(sequence(Say("Bytes.", blocks=(block,))))))))
    assert artifact.parts == (BytesContent(b"ABC", "application/octet-stream"),)


@pytest.mark.parametrize("streams", [True, False], ids=["streamed", "whole message"])
def test_a_block_with_no_data_bad_base64_or_a_vendor_kind_is_skipped_and_the_run_goes_on(streams: bool) -> None:
    blocks = (
        hosted("image", "file-1", "image/png"),
        broken("audio", "audio/wav"),
        vendor({"type": "code_interpreter_call", "id": "ci-1"}),
        media("file", PDF, "application/pdf"),
    )
    graph = graph_of(sequence(Say("Some files.", blocks=blocks)), streams=streams)
    events = run(events_of(wrap(graph)))
    (message_id,) = run(ai_ids(graph))
    (artifact,) = artifacts(events)
    assert artifact.id == f"{message_id}-4", "the position counts the blocks that were skipped"
    assert reply_text(events) == "Some files." and isinstance(events[-1], Done)


@pytest.mark.parametrize("streams", [True, False], ids=["streamed", "whole message"])
def test_each_file_is_sent_once_whether_or_not_the_model_streams(streams: bool) -> None:
    said = Say("Two files.", blocks=(media("image", PNG, "image/png"), media("file", PDF, "application/pdf")))
    events = run(events_of(wrap(graph_of(sequence(said), streams=streams))))
    assert [a.id.rsplit("-", 1)[1] for a in artifacts(events)] == ["1", "2"], "never from a chunk, never twice"


@pytest.mark.parametrize("mode", MODES)
def test_a_file_of_a_message_that_asks_for_approval_is_sent_once_across_the_pause(mode: str) -> None:
    """The middleware gives the same message again after the answer: its file is not sent twice."""
    chart = media("image", PNG, "image/png")

    def script(messages: list[Any]) -> Any:
        if not any(m.type == "tool" for m in messages):
            return Turn(text="Here is the chart.", calls=((DEPLOY, {"version": "1.2"}),), blocks=(chart,))
        return Say("Rolled out.")

    async def go() -> None:
        w = world(script, mode)
        live = Driver(w.source).start(THREAD, RunInput("go"))
        before = await until_pause(live)
        assert live.pending is not None and len(artifacts(before)) == 1, "sent before the ask"
        await live.deliver(allow(live.pending))
        after = await rest(live)
        assert not artifacts(after), "not again once the graph goes on"
        assert w.runs == Counter({DEPLOY: 1})

    run(go())


def test_the_files_of_a_hidden_model_call_are_not_sent() -> None:
    hidden = Scripted(script=lambda m: Say("private", blocks=(media("file", PDF, "application/pdf"),)))
    visible = Scripted(script=lambda m: Say("public"))
    assert not artifacts(run(events_of(wrap(_two_models(hidden, visible)))))


# --- 4b. the doors carry a file, and refuse one that is too large (R15) -------------------------------------


def _file_source(size: int) -> Any:
    block = media("file", b"x" * size, "application/pdf", filename="report.pdf")
    return wrap(graph_of(sequence(Say("Here it is.", blocks=(block,)))))


def _status_text(event: Any) -> str:
    return "".join(p.text for p in event.status_update.status.message.parts if p.HasField("text"))


def test_a2a_a_file_artifact_reaches_the_caller() -> None:
    async def go() -> None:
        source = _file_source(200)
        async with serve(SourceExecutor(source), agent_card(source.card, "https://remote.example.com/")) as served:
            async with a2a_client(served, user="alice") as tc:
                events = await send(tc, "go")
                assert kinds(events)[-1] == "completed"
                (update,) = [e.artifact_update for e in events if e.HasField("artifact_update") and e.artifact_update.artifact.artifact_id != "reply"]
                (part,) = update.artifact.parts
                assert part.raw == b"x" * 200 and part.media_type == "application/pdf" and part.filename == "report.pdf"

    run(go())


def test_a2a_a_door_with_a_small_file_limit_fails_the_task_cleanly() -> None:
    async def go() -> None:
        source = _file_source(200)
        executor = SourceExecutor(source, limits=Limits(message_bytes=64))  # what a door sends out is checked by this one
        async with serve(executor, agent_card(source.card, "https://remote.example.com/")) as served:
            async with a2a_client(served, user="alice") as tc:
                events = await send(tc, "go")
                assert kinds(events)[-1] == "failed"
                assert "larger than" in _status_text(events[-1])

    run(go())
