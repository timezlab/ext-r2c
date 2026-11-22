"""Running a real graph: the reply, `last`, the paragraph break, `nostream`, threads, the input, a
failure, a cancel and a lost pause (spec 006: R3, R5, R18; FR-005, FR-006, FR-008, FR-013, FR-023).

Real `create_agent` graphs and a real checkpointer, through the real `Driver`; the model is scripted.
The last section tests the pure reply state machine (`_reply`) with no graph at all.
"""

from __future__ import annotations

import asyncio
import base64
from collections import Counter
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph

from ext_r2c.bridges.langgraph._reply import Reply
from ext_r2c.core import (
    Answer,
    AnswerEvent,
    Ask,
    BytesContent,
    Done,
    Driver,
    Error,
    PauseLost,
    ReplyChunk,
    RunContext,
    RunEvent,
    RunInput,
    TextContent,
    UrlContent,
    UsageEvent,
    parse,
    thread_id,
)

from agent_source_suite import TITLE, check_last, reply_text, rest, until_pause
from langgraph_graphs import ASK_QUESTION, NOTICE, agent, counted_tools, memory_saver, run, suite_tools, wrap
from langgraph_models import Call, Calls, Gate, Say, Script, Scripted, Turn, humans

THREAD = thread_id("a2a", "owner-1", "ctx-1")
OTHER = thread_id("a2a", "owner-2", "ctx-1")


def sequence(*turns: Turn) -> Script:
    """The nth model call says the nth turn (the last one for ever): a pure function of the history."""

    def script(messages: list[BaseMessage]) -> Turn:
        spoken = sum(isinstance(m, AIMessage) for m in messages)
        return turns[min(spoken, len(turns) - 1)]

    return script


def graph_of(script: Script, *, tools: Any = None, saver: Any = None, **model: Any) -> Any:
    return agent(Scripted(script=script, **model), list(tools or []), saver or memory_saver())


def notice_tools() -> list[Any]:
    return list(counted_tools(Counter()).values())


async def events_of(source: Any, input: RunInput | str = "go", thread: str = THREAD) -> list[RunEvent]:
    value = RunInput(input) if isinstance(input, str) else input
    return [event async for event in Driver(source).start(thread, value)]


def chunks(events: list[RunEvent]) -> list[ReplyChunk]:
    return [e for e in events if isinstance(e, ReplyChunk)]


# --- 1. the reply ------------------------------------------------------------------------------


def test_the_reply_is_the_models_text_in_chunks_and_only_the_last_one_is_last() -> None:
    text = "The report is ready for review today"
    events = run(events_of(wrap(graph_of(sequence(Say(text))))))
    assert isinstance(events[-1], Done)
    assert reply_text(events) == text
    assert len(chunks(events)) >= 3, "the reply arrives as the model streams it, not in one piece"
    check_last(events)


def test_a_one_token_reply_is_one_chunk_marked_last() -> None:
    events = run(events_of(wrap(graph_of(sequence(Say("Done"))))))
    assert chunks(events) == [ReplyChunk("Done", last=True)]


def test_a_turn_of_tool_calls_only_has_no_reply_and_ends_done() -> None:
    script = sequence(Call((NOTICE, {"text": "hi"})), Say(""))
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    assert not chunks(events), "no text, so no reply chunk, not even an empty one"
    assert not [e for e in events if isinstance(e, Error)]
    assert isinstance(events[-1], Done)


def test_a_tool_message_is_never_reply_text() -> None:
    script = sequence(Call((NOTICE, {"text": "hi"})), Say("All sent."))
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    assert reply_text(events) == "All sent."
    assert "sent: hi" not in reply_text(events), "the tool's result is not the model's reply"


# --- 2. SC-007: the first chunk before the model's last token ----------------------------------


def test_the_first_chunk_is_read_before_the_models_last_token() -> None:
    gate = Gate(after=3)
    text = "The report is ready for review today"
    source = wrap(graph_of(sequence(Say(text)), gate=gate))

    async def go() -> None:
        live = Driver(source).start(THREAD, RunInput("go"))
        first = await asyncio.wait_for(live.__anext__(), 5)
        assert isinstance(first, ReplyChunk) and first.text, "a piece of the reply, read while the model waits"
        assert not gate.event.is_set(), "the model has not produced its last token"
        await asyncio.wait_for(gate.reached.wait(), 5)
        gate.event.set()
        events = [first] + [e async for e in live]
        assert reply_text(events) == text
        check_last(events)

    run(go())


# --- 3. hold one, and `last` -------------------------------------------------------------------


def test_text_then_a_tool_then_text_has_one_last_chunk_at_the_end() -> None:
    script = sequence(Call((NOTICE, {"text": "hi"}), text="Sending the notice now."), Say("The notice went out."))
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    assert reply_text(events) == "Sending the notice now.\n\nThe notice went out."
    check_last(events)


def test_a_reply_that_ends_before_the_tools_is_closed_with_an_empty_last_chunk() -> None:
    # The held piece leaves with last=False when the model asks for tools, so when no more text
    # comes, the reply is closed by one empty chunk marked last (R5).
    script = sequence(Call((NOTICE, {"text": "hi"}), text="Looking it up."), Say(""))
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    assert chunks(events) == [
        ReplyChunk("Looking "), ReplyChunk("it "), ReplyChunk("up."), ReplyChunk("", last=True),
    ]


def test_a_leg_that_ends_in_an_ask_leaves_its_held_piece_unmarked_and_the_reply_goes_on() -> None:
    script = sequence(Call((ASK_QUESTION, {}), text="One moment please."), Say("Got: October stock"))
    source = wrap(graph_of(script, tools=suite_tools()))

    async def go() -> None:
        live = Driver(source).start(THREAD, RunInput("go"))
        events = await until_pause(live)
        assert isinstance(events[-1], Ask)
        assert reply_text(events) == "One moment please."
        assert not any(c.last for c in chunks(events)), "a pause is not the end of the reply"
        await live.deliver(TITLE)
        events += await rest(live)
        assert reply_text(events) == "One moment please.\n\nGot: October stock"
        check_last(events)

    run(go())


def test_a_graph_that_raises_leaves_its_held_piece_unmarked_before_the_error() -> None:
    model = Scripted(script=sequence(Say("Almost there.")))

    async def call_model(state: MessagesState) -> dict[str, Any]:
        return {"messages": [await model.ainvoke(state["messages"])]}

    def boom(state: MessagesState) -> dict[str, Any]:
        raise ValueError("the node broke")

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("boom", boom)
    builder.add_edge(START, "model")
    builder.add_edge("model", "boom")
    builder.add_edge("boom", END)
    events = run(events_of(wrap(builder.compile(checkpointer=memory_saver()))))
    assert chunks(events) == [ReplyChunk("Almost "), ReplyChunk("there.")]
    assert isinstance(events[-1], Error) and events[-1].code == "failed" and "the node broke" in events[-1].reason


# --- 4. the paragraph break --------------------------------------------------------------------


def test_two_messages_with_text_are_separated_by_a_blank_line() -> None:
    script = sequence(Call((NOTICE, {"text": "a"}), text="First."), Say("Second."))
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    assert reply_text(events) == "First.\n\nSecond."


def test_a_message_with_no_text_between_two_that_have_text_adds_nothing() -> None:
    script = sequence(
        Call((NOTICE, {"text": "a"}), text="First."),
        Call((NOTICE, {"text": "b"})),
        Say("Second."),
    )
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    assert reply_text(events) == "First.\n\nSecond."


def test_a_reply_that_starts_after_the_tools_has_no_leading_break() -> None:
    script = sequence(Call((NOTICE, {"text": "a"})), Say("Only this."))
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    assert reply_text(events) == "Only this."


# --- 5. `nostream` -----------------------------------------------------------------------------


def _two_models(hidden: Scripted, visible: Scripted) -> Any:
    quiet = hidden.with_config(tags=["nostream"])

    async def think(state: MessagesState) -> dict[str, Any]:
        return {"messages": [await quiet.ainvoke(state["messages"])]}

    async def answer(state: MessagesState) -> dict[str, Any]:
        return {"messages": [await visible.ainvoke(state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("think", think)
    builder.add_node("answer", answer)
    builder.add_edge(START, "think")
    builder.add_edge("think", "answer")
    builder.add_edge("answer", END)
    return builder.compile(checkpointer=memory_saver())


@pytest.mark.parametrize("hidden_streams", [True, False])
def test_a_hidden_model_call_never_reaches_the_reply(hidden_streams: bool) -> None:
    hidden = Scripted(script=lambda m: Say("private notes here", tokens=(3, 3)), streams=hidden_streams)
    visible = Scripted(script=lambda m: Say("public answer", tokens=(4, 2)))
    events = run(events_of(wrap(_two_models(hidden, visible))))
    assert reply_text(events) == "public answer"
    assert "private" not in reply_text(events)
    check_last(events)
    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert len(usage) == 1 and (usage[0].usage.input_tokens, usage[0].usage.output_tokens) == (7, 5), (
        "the hidden call spent tokens, so it counts"
    )


def test_a_model_that_does_not_stream_gives_its_whole_message_as_one_chunk() -> None:
    hidden = Scripted(script=lambda m: Say("private notes here"))
    visible = Scripted(script=lambda m: Say("public answer"), streams=False)
    events = run(events_of(wrap(_two_models(hidden, visible))))
    assert chunks(events) == [ReplyChunk("public answer", last=True)]


# --- 6. threads (FR-005) -----------------------------------------------------------------------


def test_the_same_thread_continues_and_another_thread_shares_nothing() -> None:
    graph = graph_of(lambda messages: Say(f"seen {humans(messages)}"))
    source = wrap(graph)

    async def go() -> None:
        assert reply_text(await events_of(source, "one", THREAD)) == "seen 1"
        assert reply_text(await events_of(source, "two", THREAD)) == "seen 2", "the thread's history is kept"
        assert reply_text(await events_of(source, "one", OTHER)) == "seen 1", "another thread starts empty"
        mine = await graph.aget_state({"configurable": {"thread_id": THREAD}})
        theirs = await graph.aget_state({"configurable": {"thread_id": OTHER}})
        assert humans(mine.values["messages"]) == 2 and humans(theirs.values["messages"]) == 1

    run(go())


# --- 7. the input (FR-006, R18) ----------------------------------------------------------------


def _seen_by_the_model(input: RunInput) -> BaseMessage:
    seen: list[BaseMessage] = []

    def script(messages: list[BaseMessage]) -> Turn:
        seen.append(messages[-1])
        return Say("ok")

    run(events_of(wrap(graph_of(script)), input))
    return seen[0]


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_a_text_only_input_is_one_human_message_with_that_text() -> None:
    message = _seen_by_the_model(RunInput("Write the report"))
    assert isinstance(message, HumanMessage) and message.content == "Write the report"


def test_parts_become_standard_content_blocks_and_nothing_is_dropped() -> None:
    png, pdf = b"\x89PNG\r\n", b"%PDF-1.7"
    parts = (
        BytesContent(png, "image/png", "chart.png"),
        UrlContent("https://example.com/clip.mp3", "audio/mpeg"),
        UrlContent("https://example.com/clip.mp4", "video/mp4"),
        BytesContent(pdf, "application/pdf", "report.pdf"),
        UrlContent("https://example.com/data.csv", "text/csv"),
        TextContent("a note"),
    )
    message = _seen_by_the_model(RunInput("Look at these", parts))
    assert isinstance(message, HumanMessage)
    assert message.content == [
        {"type": "text", "text": "Look at these"},
        {"type": "image", "base64": _b64(png), "mime_type": "image/png"},
        {"type": "audio", "url": "https://example.com/clip.mp3", "mime_type": "audio/mpeg"},
        {"type": "video", "url": "https://example.com/clip.mp4", "mime_type": "video/mp4"},
        {"type": "file", "base64": _b64(pdf), "mime_type": "application/pdf"},
        {"type": "file", "url": "https://example.com/data.csv", "mime_type": "text/csv"},
        {"type": "text", "text": "a note"},
    ]


def test_a_file_with_no_text_is_one_block_and_no_empty_text_block() -> None:
    message = _seen_by_the_model(RunInput("", (BytesContent(b"%PDF-1.7", "application/pdf"),)))
    assert message.content == [{"type": "file", "base64": _b64(b"%PDF-1.7"), "mime_type": "application/pdf"}]


def test_the_media_type_is_read_by_its_top_level_whatever_its_case_or_parameters() -> None:
    message = _seen_by_the_model(RunInput("x", (UrlContent("https://example.com/a", "Image/PNG; q=1"),)))
    assert message.content[1] == {"type": "image", "url": "https://example.com/a", "mime_type": "Image/PNG; q=1"}


# --- 8. a failure ------------------------------------------------------------------------------


def test_an_exception_in_a_tool_ends_the_run_failed_with_its_message() -> None:
    @tool("explode")
    def explode() -> str:
        """A tool that always fails."""
        raise RuntimeError("the tool broke")

    events = run(events_of(wrap(graph_of(sequence(Call(("explode", {}))), tools=[explode]))))
    assert isinstance(events[-1], Error)
    assert events[-1].code == "failed" and "the tool broke" in events[-1].reason
    assert [type(e) for e in events if isinstance(e, (Done, Error))] == [Error]


# --- 9. a cancel -------------------------------------------------------------------------------


def test_a_cancel_closes_the_models_stream_and_leaves_no_task_running() -> None:
    gate = Gate(after=2)
    source = wrap(graph_of(sequence(Say("The report is ready for review today")), gate=gate))

    async def go() -> None:
        before = set(asyncio.all_tasks())
        live = Driver(source).start(THREAD, RunInput("go"))
        assert isinstance(await asyncio.wait_for(live.__anext__(), 5), ReplyChunk)
        await asyncio.wait_for(gate.reached.wait(), 5)
        await live.cancel()
        for _ in range(100):  # one second at most
            if gate.closed and not {t for t in asyncio.all_tasks() - before if not t.done()}:
                break
            await asyncio.sleep(0.01)
        assert gate.closed, "the model's stream was closed, not left to finish"
        assert not {t for t in asyncio.all_tasks() - before if not t.done()}, "a task of the bridge still runs"

    run(go())


# --- 10. an answer nothing waits for (FR-023) --------------------------------------------------


def _unwanted() -> tuple[Any, Answer]:
    request = parse({
        "kind": "question", "id": "q-404", "title": "Report title", "answer_by": {"role": "person"},
        "fields": [{"key": "title", "header": "Title", "text": "Title?", "type": "text"}],
    })
    answer = Answer.parse({
        "kind": "answer", "id": "q-404", "outcome": "answered", "answered_by": {"role": "person"},
        "value": {"title": "October stock"},
    })
    return request, answer


def test_an_answer_for_a_pause_the_graph_does_not_hold_is_lost_and_the_graph_is_not_started() -> None:
    calls = Calls()
    graph = graph_of(sequence(Say("never said")), calls=calls)
    request, answer = _unwanted()

    async def go() -> None:
        events = [e async for e in Driver(wrap(graph)).resume(THREAD, request, answer)]
        assert [type(e) for e in events] == [AnswerEvent, Error]
        assert isinstance(events[1], Error) and events[1].code == "lost" and "q-404" in events[1].reason
        assert calls.n == 0, "the model was not called"
        assert not (await graph.aget_state({"configurable": {"thread_id": THREAD}})).values, "nothing was written"

    run(go())


def test_resume_raises_pause_lost_naming_the_id() -> None:
    source = wrap(graph_of(sequence(Say("never said"))))
    _, answer = _unwanted()

    async def go() -> None:
        ctx = RunContext(THREAD, lambda request: None)
        with pytest.raises(PauseLost, match="q-404"):
            async for _ in source.resume(answer, ctx):
                pass

    run(go())


def test_an_answer_for_another_request_than_the_pending_one_is_lost_and_the_pause_stays_pending() -> None:
    calls = Calls()
    graph = graph_of(sequence(Call((ASK_QUESTION, {})), Say("All done.")), tools=suite_tools(), calls=calls)
    source = wrap(graph)
    _, stray = _unwanted()  # an answer for "q-404", while the graph waits on "q-1"

    async def go() -> None:
        live = Driver(source).start(THREAD, RunInput("go"))
        await until_pause(live)
        assert live.pending is not None and live.pending.id == "q-1"
        asked = calls.n
        with pytest.raises(PauseLost, match="q-404"):
            async for _ in source.resume(stray, RunContext(THREAD, lambda request: None)):
                pass
        assert calls.n == asked, "the graph was not resumed by an answer that is not for its pause"
        held = await graph.aget_state({"configurable": {"thread_id": THREAD}})
        assert [i.value["id"] for i in held.interrupts] == ["q-1"], "the pause is still pending"
        await live.deliver(TITLE)
        assert reply_text(await rest(live)) == "All done."  # the right answer still resumes it

    run(go())


def test_an_answer_the_request_refuses_is_refused_before_the_graph_and_the_pause_stays_pending() -> None:
    calls = Calls()
    graph = graph_of(sequence(Call((ASK_QUESTION, {})), Say("All done.")), tools=suite_tools(), calls=calls)
    source = wrap(graph)
    empty = Answer.parse({
        "kind": "answer", "id": "q-1", "outcome": "answered", "answered_by": {"role": "person"}, "value": {},
    })  # the question's one field is required

    async def go() -> None:
        live = Driver(source).start(THREAD, RunInput("go"))
        await until_pause(live)
        asked = calls.n
        with pytest.raises(ValueError, match="not acceptable"):
            async for _ in source.resume(empty, RunContext(THREAD, lambda request: None)):
                pass
        assert calls.n == asked, "the graph was not resumed by an answer its request refuses"
        held = await graph.aget_state({"configurable": {"thread_id": THREAD}})
        assert [i.value["id"] for i in held.interrupts] == ["q-1"], "the pause is still pending"
        await live.deliver(TITLE)
        assert reply_text(await rest(live)) == "All done."

    run(go())


# --- 11. usage ---------------------------------------------------------------------------------


def test_usage_is_summed_over_the_turn_and_sent_once_before_the_end() -> None:
    script = sequence(Call((NOTICE, {"text": "a"}), tokens=(5, 2)), Say("All sent.", tokens=(7, 3)))
    events = run(events_of(wrap(graph_of(script, tools=notice_tools()))))
    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert len(usage) == 1
    assert (usage[0].usage.input_tokens, usage[0].usage.output_tokens) == (12, 5)
    assert events.index(usage[0]) > max(i for i, e in enumerate(events) if isinstance(e, ReplyChunk))
    assert isinstance(events[-1], Done)


def test_no_usage_event_when_no_message_reported_tokens() -> None:
    events = run(events_of(wrap(graph_of(sequence(Say("No counts here"))))))
    assert not [e for e in events if isinstance(e, UsageEvent)], "an empty usage is not allowed (R2C-USAGE-1)"


# --- 12. the reply state machine, with no graph ------------------------------------------------


def test_a_piece_is_held_until_the_next_one_arrives() -> None:
    reply = Reply()
    assert reply.feed("Hello ", "m1") == []
    assert reply.feed("world", "m1") == [ReplyChunk("Hello ")]
    assert reply.end_turn(True) == [ReplyChunk("world", last=True)]


def test_a_flush_sends_the_held_piece_unmarked_and_the_turn_is_then_closed_by_an_empty_chunk() -> None:
    reply = Reply()
    reply.feed("Hello ", "m1")
    reply.feed("world", "m1")
    assert reply.flush() == [ReplyChunk("world")]
    assert reply.flush() == [], "nothing is held any more"
    assert reply.end_turn(True) == [ReplyChunk("", last=True)]


def test_a_turn_with_no_reply_text_sends_nothing() -> None:
    reply = Reply()
    assert reply.feed("", "m1") == []
    assert reply.end_turn(False) == []


def test_a_turn_that_had_text_in_an_earlier_leg_is_closed_by_an_empty_chunk() -> None:
    assert Reply().end_turn(True) == [ReplyChunk("", last=True)]


def test_a_blank_line_goes_before_the_first_piece_of_a_different_message() -> None:
    reply = Reply()
    assert reply.feed("One.", "m1") == []
    assert reply.feed("Two.", "m2") == [ReplyChunk("One.")]
    assert reply.end_turn(True) == [ReplyChunk("\n\nTwo.", last=True)]


def test_pieces_of_one_message_have_no_break_between_them() -> None:
    reply = Reply()
    reply.feed("a ", "m1")
    assert reply.feed("b ", "m1") == [ReplyChunk("a ")]
    assert reply.feed("c", "m1") == [ReplyChunk("b ")]
    assert reply.end_turn(True) == [ReplyChunk("c", last=True)]


def test_a_message_with_no_text_changes_nothing() -> None:
    reply = Reply()
    reply.feed("A", "m1")
    assert reply.feed("", "m2") == []
    assert reply.feed("B", "m3") == [ReplyChunk("A")]
    assert reply.end_turn(True) == [ReplyChunk("\n\nB", last=True)]


def test_chunks_with_no_id_are_one_message_while_they_follow_each_other() -> None:
    reply = Reply()
    reply.feed("a", None)
    assert reply.feed("b", None) == [ReplyChunk("a")]
    assert reply.feed("c", "m1") == [ReplyChunk("b")]
    assert reply.end_turn(True) == [ReplyChunk("\n\nc", last=True)]


def test_a_hidden_message_is_skipped_and_does_not_start_a_paragraph() -> None:
    reply = Reply()
    reply.hide("h1")
    assert reply.feed("secret", "h1") == []
    assert reply.feed("Visible", "m1") == []
    assert reply.end_turn(True) == [ReplyChunk("Visible", last=True)], "no break before the first visible text"


def test_a_reply_seeded_from_an_earlier_leg_breaks_before_a_new_message_only() -> None:
    reply = Reply(previous="m0")
    assert reply.feed("Next", "m1") == []
    assert reply.end_turn(True) == [ReplyChunk("\n\nNext", last=True)]
    same = Reply(previous="m0")
    same.feed("More", "m0")
    assert same.end_turn(True) == [ReplyChunk("More", last=True)]
