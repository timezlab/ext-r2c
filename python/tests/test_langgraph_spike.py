"""The LangChain and LangGraph facts the bridge leans on (spec 006, research R1 to R18).

Each test pins one fact with the scripted model and `create_agent`, over the installed packages. A
failing one means a library changed under the design: the phase stops, and research.md and plan.md
are updated before anything else. No test here imports the bridge.
"""

from __future__ import annotations

import asyncio
import warnings
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

import pytest
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.structured_output import ProviderStrategy, ToolStrategy
from langchain.tools import InjectedState, InjectedStore, ToolRuntime
from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.tools import InjectedToolArg, InjectedToolCallId, StructuredTool, ToolException, tool
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, Interrupt, interrupt
from pydantic import BaseModel

from langgraph_graphs import DEPLOY, NOTICE, PUBLISH, agent, counted_tools, memory_saver, restart, run, sqlite_saver
from langgraph_models import Call, Gate, Say, Scripted, Turn, dangling, humans, tool_results

PARTS: dict[str, Any] = {"stream_mode": ["messages", "updates"], "version": "v2"}
MODES = ("per_call", "batched")


def cfg(thread: str = "t-1", *handlers: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"configurable": {"thread_id": thread}}
    if handlers:
        config["callbacks"] = list(handlers)
    return config


def first(text: str = "go") -> dict[str, Any]:
    return {"messages": [HumanMessage(text)]}


async def drain(graph: Any, value: Any, config: dict[str, Any], **kwargs: Any) -> list[dict[str, Any]]:
    """Every part of one leg, in the typed shape (`type`, `ns`, `data`)."""
    options = {**PARTS, **kwargs}
    return [part async for part in graph.astream(value, config, **options)]


async def pending(graph: Any, config: dict[str, Any]) -> tuple[Interrupt, ...]:
    return tuple((await graph.aget_state(config)).interrupts)


async def history(graph: Any, config: dict[str, Any]) -> list[BaseMessage]:
    return list((await graph.aget_state(config)).values["messages"])


def resume_with(interrupt_id: str, value: Any) -> Command[Any]:
    return Command(resume={interrupt_id: value})


def gated(mode: str, *names: str, decisions: list[str] | None = None) -> HumanInTheLoopMiddleware:
    """The middleware in `mode`, gating `names` (with these decisions, or the default set)."""
    on: Any = True if decisions is None else {"allowed_decisions": decisions}
    return HumanInTheLoopMiddleware(interrupt_on={n: on for n in names}, interrupt_mode=mode)  # type: ignore[arg-type]


def two_calls(messages: list[BaseMessage]) -> Turn:
    """Turn 1: call `deploy_release` and `send_notice`; then say that it is finished."""
    if humans(messages) == 1 and not tool_results(messages):
        return Call((DEPLOY, {"version": "1.2"}), (NOTICE, {"text": "hi"}))
    return Say("finished")


def one_call(messages: list[BaseMessage]) -> Turn:
    if humans(messages) == 1 and not tool_results(messages):
        return Call((DEPLOY, {"version": "1.2"}))
    return Say("finished")


def build(
    script: Callable[[list[BaseMessage]], Turn],
    mode: str,
    *,
    gate: tuple[str, ...] = (DEPLOY,),
    decisions: list[str] | None = None,
    strict: bool = False,
    runs: Counter[str] | None = None,
    saver: Any = None,
    model_args: dict[str, Any] | None = None,
) -> tuple[Any, Counter[str]]:
    runs = Counter() if runs is None else runs
    model = Scripted(script=script, strict=strict, **(model_args or {}))
    graph = agent(
        model,
        list(counted_tools(runs).values()),
        saver or memory_saver(),
        middleware=[gated(mode, *gate, decisions=decisions)],
    )
    return graph, runs


# ---------------------------------------------------------------------------------------------
# 1. R1: the middleware takes `interrupt_mode`, and both modes pause


@pytest.mark.parametrize("mode", MODES)
def test_interrupt_mode_is_accepted_and_both_modes_pause(mode: str) -> None:
    async def go() -> None:
        graph, runs = build(one_call, mode)
        await drain(graph, first(), cfg())
        found = await pending(graph, cfg())
        assert len(found) == 1
        assert runs[DEPLOY] == 0, "a call that waits for approval must not have run"

    run(go())


# ---------------------------------------------------------------------------------------------
# 2. R3: the `tasks` stream cannot tell a paused tool from a running one (good news if it can)


def test_tasks_stream_cannot_tell_a_paused_tool_from_a_running_one() -> None:
    async def go() -> None:
        graph, _ = build(two_calls, "per_call")
        parts = await drain(graph, first(), cfg(), stream_mode=["tasks"])
        starts = [p["data"] for p in parts if "input" in p["data"] and p["data"]["name"] == "tools"]
        results = [p["data"] for p in parts if "result" in p["data"] and p["data"]["name"] == "tools"]
        called = {s["input"][0]["name"] for s in starts}
        assert called == {DEPLOY, NOTICE}, "a tools task starts for every call, the paused one too"
        assert not any("interrupts" in s for s in starts), "a start says nothing about a pause"
        paused = [r for r in results if r["interrupts"]]
        assert len(paused) == 1, "only a task's result carries the interrupt"
        by_id = {s["id"]: s["input"][0]["name"] for s in starts}
        assert by_id[paused[0]["id"]] == DEPLOY

    run(go())


# ---------------------------------------------------------------------------------------------
# 3. R3: the v2 stream parts are typed


def test_stream_parts_are_typed() -> None:
    async def go() -> None:
        graph, _ = build(two_calls, "per_call")
        parts = await drain(graph, first(), cfg())
        assert parts, "no part came"
        for part in parts:
            assert set(part) == {"type", "ns", "data"}
            assert part["type"] in {"messages", "updates"}
        messages = [p for p in parts if p["type"] == "messages"]
        updates = [p for p in parts if p["type"] == "updates"]
        assert messages and updates
        for part in messages:
            message, metadata = part["data"]
            assert isinstance(message, BaseMessage)
            assert isinstance(metadata, dict)
        for part in updates:
            assert isinstance(part["data"], dict)
        assert any("model" in p["data"] for p in updates), "an update is {node: update}"

    run(go())


# ---------------------------------------------------------------------------------------------
# 4. R8: pending interrupts are read from the state


def test_pending_interrupts_are_read_from_the_state() -> None:
    async def go() -> None:
        graph, _ = build(one_call, "per_call")
        await drain(graph, first(), cfg())
        found = await pending(graph, cfg())
        assert len(found) == 1
        item = found[0]
        assert isinstance(item, Interrupt)
        assert isinstance(item.id, str) and item.id
        assert item.value["type"] == "tool_approval"
        assert isinstance(item.response_schema, dict), "the response schema is a plain dict"
        assert (await pending(graph, cfg()))[0].id == item.id, "reading it twice gives one id"

    run(go())


# ---------------------------------------------------------------------------------------------
# 5. R3, R4: a handler sees a tool start only when the body runs


class Recorder(AsyncCallbackHandler):
    """The per-run handler of the design, reduced to a log."""

    run_inline = True

    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    async def on_tool_start(
        self, serialized: dict[str, Any], input_str: str, *, run_id: UUID, inputs: Any = None, **kwargs: Any
    ) -> None:
        self.events.append(("start", (serialized or {}).get("name"), kwargs.get("tool_call_id"), inputs))

    async def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self.events.append(("end", type(output).__name__, getattr(output, "status", None), getattr(output, "content", output)))

    async def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self.events.append(("error", type(error).__name__, isinstance(error, GraphBubbleUp)))

    def of(self, kind: str) -> list[tuple[Any, ...]]:
        return [e for e in self.events if e[0] == kind]


def test_handler_sees_a_tool_start_only_when_the_body_runs() -> None:
    async def go() -> None:
        # A paused call and a denied call fire nothing; the ungated one fires start and end.
        graph, runs = build(two_calls, "per_call")
        rec = Recorder()
        await drain(graph, first(), cfg("t-a", rec))
        assert rec.events == [("start", NOTICE, "call-0-1", {"text": "hi"}), ("end", "ToolMessage", "success", "sent: hi")]
        item = (await pending(graph, cfg("t-a")))[0]
        rec.events.clear()
        await drain(graph, resume_with(item.id, {"type": "reject", "message": "no"}), cfg("t-a", rec))
        assert rec.events == [], "a denied call never reaches its body: nothing fires"
        assert runs[DEPLOY] == 0

        # An approved one fires start (with the call id and the input) then end.
        graph, runs = build(two_calls, "per_call")
        rec = Recorder()
        await drain(graph, first(), cfg("t-b", rec))
        item = (await pending(graph, cfg("t-b")))[0]
        rec.events.clear()
        await drain(graph, resume_with(item.id, {"type": "approve"}), cfg("t-b", rec))
        assert rec.events[0] == ("start", DEPLOY, "call-0-0", {"version": "1.2"})
        assert rec.events[1] == ("end", "ToolMessage", "success", "deployed 1.2 to north")

    run(go())


def _failing_tool(handled: bool) -> Any:
    def flaky_step(item: str) -> str:
        raise ToolException("the step failed") if handled else ValueError("the step broke")

    return StructuredTool.from_function(
        flaky_step, name="flaky_step", description="A step that fails.", handle_tool_error=handled
    )


def test_handler_sees_a_handled_and_a_raised_tool_failure() -> None:
    def script(messages: list[BaseMessage]) -> Turn:
        if not tool_results(messages):
            return Call(("flaky_step", {"item": "a"}))
        return Say("finished")

    async def go() -> None:
        # A handled `ToolException`: the tool ends, with `status="error"`.
        graph = agent(Scripted(script=script), [_failing_tool(True)], memory_saver())
        rec = Recorder()
        await drain(graph, first(), cfg("t-1", rec))
        assert rec.events[0][:2] == ("start", "flaky_step")
        assert rec.events[1][:3] == ("end", "ToolMessage", "error")

        # A raising tool: `on_tool_error` fires, and the stream raises.
        graph = agent(Scripted(script=script), [_failing_tool(False)], memory_saver())
        rec = Recorder()
        with pytest.raises(ValueError, match="the step broke"):
            await drain(graph, first(), cfg("t-2", rec))
        assert rec.of("error") == [("error", "ValueError", False)]

    run(go())


# ---------------------------------------------------------------------------------------------
# 6. R3: a pause inside a tool is a `GraphBubbleUp`; the body restarts from its top


def test_a_pause_inside_a_tool_is_a_graph_bubble_up() -> None:
    body: Counter[str] = Counter()

    @tool("ask_first")
    def ask_first(q: str) -> str:
        """Ask a person first."""
        body["ran"] += 1
        return f"got {interrupt({'q': q})}"

    def script(messages: list[BaseMessage]) -> Turn:
        if not tool_results(messages):
            return Call(("ask_first", {"q": "x"}))
        return Say("finished")

    async def go() -> None:
        graph = agent(Scripted(script=script), [ask_first], memory_saver())
        rec = Recorder()
        await drain(graph, first(), cfg("t-1", rec))
        assert [e[0] for e in rec.events] == ["start", "error"]
        assert rec.events[1][2] is True, "the pause is a GraphBubbleUp, not a failure"
        item = (await pending(graph, cfg("t-1")))[0]
        rec.events.clear()
        await drain(graph, resume_with(item.id, "yes"), cfg("t-1", rec))
        assert [e[0] for e in rec.events] == ["start", "end"], "the body starts again from its top"
        assert rec.events[1][2:] == ("success", "got yes")
        assert body["ran"] == 2

    run(go())


# ---------------------------------------------------------------------------------------------
# 7 and 8. R5: `nostream` hides tokens only; a model that does not stream gives one whole message


class Hidden(AsyncCallbackHandler):
    """What the design's handler learns about a model run: its tags, and the message it ended with."""

    run_inline = True

    def __init__(self) -> None:
        self.tags: list[list[str]] = []
        self.ended: list[BaseMessage] = []

    async def on_chat_model_start(
        self, serialized: dict[str, Any], messages: Any, *, run_id: UUID, tags: list[str] | None = None, **kwargs: Any
    ) -> None:
        self.tags.append(list(tags or []))

    async def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self.ended.append(response.generations[0][0].message)


def _one_node_graph(model: Any, tags: list[str] | None) -> Any:
    bound = model.with_config(tags=tags) if tags else model

    async def call_model(state: MessagesState) -> dict[str, Any]:
        return {"messages": [await bound.ainvoke(state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("call_model", call_model)
    builder.add_edge(START, "call_model")
    builder.add_edge("call_model", END)
    return builder.compile(checkpointer=memory_saver())


def test_nostream_hides_tokens_only() -> None:
    async def go() -> None:
        model = Scripted(script=lambda m: Say("a quiet reply here"))
        graph = _one_node_graph(model, ["nostream"])
        seen = Hidden()
        parts = await drain(graph, first(), cfg("t-1", seen))
        messages = [p["data"] for p in parts if p["type"] == "messages"]
        assert not [m for m, _ in messages if isinstance(m, AIMessageChunk)], "no token came"
        whole = [m for m, _ in messages if isinstance(m, AIMessage)]
        assert len(whole) == 1 and whole[0].text == "a quiet reply here"
        assert all("nostream" not in (meta.get("tags") or []) for _, meta in messages), (
            "the part cannot tell a hidden call from a model that does not stream"
        )
        assert [t for t in seen.tags if "nostream" in t], "the handler is told the tags of the model run"
        assert [m.id for m in seen.ended] == [whole[0].id], "and gets the message, with the same id"

        visible = _one_node_graph(model, None)
        seen = Hidden()
        parts = await drain(visible, first(), cfg("t-2", seen))
        assert any(isinstance(m, AIMessageChunk) for m, _ in (p["data"] for p in parts if p["type"] == "messages"))
        assert all("nostream" not in t for t in seen.tags)

    run(go())


def test_a_model_that_does_not_stream_gives_one_whole_message() -> None:
    async def go() -> None:
        # No tools, so the graph calls the model directly.
        quiet = agent(Scripted(script=lambda m: Say("one whole reply"), streams=False), [], memory_saver())
        parts = [p["data"][0] for p in await drain(quiet, first(), cfg("t-1")) if p["type"] == "messages"]
        assert [type(m) for m in parts] == [AIMessage], "one whole message, never both it and chunks"
        assert parts[0].text == "one whole reply"

        loud = agent(Scripted(script=lambda m: Say("one whole reply")), [], memory_saver())
        chunks = [p["data"][0] for p in await drain(loud, first(), cfg("t-2")) if p["type"] == "messages"]
        assert chunks and all(isinstance(m, AIMessageChunk) for m in chunks)
        assert len({m.id for m in chunks}) == 1, "the chunks of one call share an id"
        assert "".join(m.text for m in chunks) == "one whole reply"

    run(go())


# ---------------------------------------------------------------------------------------------
# 9 and 10. R9: the two payloads


def _decision_types(schema: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            const = node.get("properties", {}).get("type", {}).get("const")
            if isinstance(const, str):
                found.append(const)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


def test_per_call_interrupt_carries_a_response_schema() -> None:
    async def go() -> None:
        graph, _ = build(one_call, "per_call", decisions=["approve", "edit", "reject"])
        await drain(graph, first(), cfg())
        item = (await pending(graph, cfg()))[0]
        assert set(item.value) == {"type", "tool_call_id", "name", "args", "description"}
        assert item.value["type"] == "tool_approval"
        assert item.value["name"] == DEPLOY and item.value["args"] == {"version": "1.2"}
        schema = item.response_schema
        assert "$defs" in schema and "oneOf" in schema, "several decisions: a oneOf over $defs"
        assert sorted(_decision_types(schema)) == ["approve", "edit", "reject"]
        edit = schema["$defs"]["EditDecision"]
        assert edit["properties"]["edited_action"]["$ref"].endswith("EditedAction")
        assert schema["$defs"]["EditedAction"]["properties"]["name"]["const"] == DEPLOY

        graph, _ = build(one_call, "per_call", decisions=["approve"])
        await drain(graph, first(), cfg("t-2"))
        only = (await pending(graph, cfg("t-2")))[0].response_schema
        assert "oneOf" not in only, "one decision: the schema is that decision's own"
        assert only["properties"]["type"]["const"] == "approve"

    run(go())


def test_batched_interrupt_payload() -> None:
    async def go() -> None:
        graph, _ = build(two_calls, "batched", gate=(DEPLOY, NOTICE), decisions=["approve", "reject"])
        await drain(graph, first(), cfg())
        found = await pending(graph, cfg())
        assert len(found) == 1, "one interrupt for the whole batch"
        value = found[0].value
        assert set(value) == {"action_requests", "review_configs"}
        assert [a["name"] for a in value["action_requests"]] == [DEPLOY, NOTICE]
        assert all("description" in a and "args" in a for a in value["action_requests"])
        assert [r["action_name"] for r in value["review_configs"]] == [DEPLOY, NOTICE]
        assert all(r["allowed_decisions"] == ["approve", "reject"] for r in value["review_configs"])
        assert found[0].response_schema is None

    run(go())


# ---------------------------------------------------------------------------------------------
# 11. R9: the shapes of a resume


def _tool_message(messages: list[BaseMessage], call_id: str) -> ToolMessage:
    found = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == call_id]
    assert len(found) == 1, f"{len(found)} tool messages for {call_id}"
    return found[0]


@dataclass(frozen=True)
class Case:
    decision: dict[str, Any]
    ran: int
    status: str
    content: str | None  # None: only check that the text is there


PER_CALL_CASES = {
    "approve": Case({"type": "approve"}, 1, "success", "deployed 1.2 to north"),
    "reject with a message": Case({"type": "reject", "message": "too risky"}, 0, "error", "too risky"),
    "reject without a message": Case({"type": "reject"}, 0, "error", None),
    "edit": Case(
        {"type": "edit", "edited_action": {"name": DEPLOY, "args": {"version": "9.9", "region": "south"}}},
        1,
        "success",
        "deployed 9.9 to south",
    ),
    "respond": Case({"type": "respond", "message": "use staging"}, 0, "success", "use staging"),
}


@pytest.mark.parametrize("case", PER_CALL_CASES.values(), ids=list(PER_CALL_CASES))
def test_resume_shapes_per_call(case: Case) -> None:
    async def go() -> None:
        graph, runs = build(one_call, "per_call")
        await drain(graph, first(), cfg())
        item = (await pending(graph, cfg()))[0]
        await drain(graph, resume_with(item.id, case.decision), cfg())
        assert not await pending(graph, cfg())
        message = _tool_message(await history(graph, cfg()), "call-0-0")
        assert runs[DEPLOY] == case.ran
        assert message.status == case.status
        if case.content is not None:
            assert case.content in message.text

    run(go())


def test_resume_shapes_batched() -> None:
    def script(messages: list[BaseMessage]) -> Turn:
        if humans(messages) == 1 and not tool_results(messages):
            return Call((DEPLOY, {"version": "1.2"}), (PUBLISH, {"slug": "intro"}), (NOTICE, {"text": "hi"}))
        return Say("finished")

    async def go() -> None:
        graph, runs = build(script, "batched", gate=(DEPLOY, PUBLISH, NOTICE))
        await drain(graph, first(), cfg())
        item = (await pending(graph, cfg()))[0]
        decisions = [
            {"type": "approve"},
            {"type": "reject", "message": "later"},
            {"type": "edit", "edited_action": {"name": NOTICE, "args": {"text": "edited"}}},
        ]
        await drain(graph, resume_with(item.id, {"decisions": decisions}), cfg())
        messages = await history(graph, cfg())
        assert _tool_message(messages, "call-0-0").text == "deployed 1.2 to north"
        assert _tool_message(messages, "call-0-1").status == "error" and "later" in _tool_message(messages, "call-0-1").text
        edited = _tool_message(messages, "call-0-2").text
        assert "sent: edited" in edited and "a human reviewer replaced this tool call" in edited, (
            "an edit puts the middleware's notice before the tool's own result"
        )
        assert (runs[DEPLOY], runs[PUBLISH], runs[NOTICE]) == (1, 0, 1)

    run(go())


# ---------------------------------------------------------------------------------------------
# 12. Spec findings 2 and 3: a refused decision, per mode


def test_a_refused_decision_per_mode() -> None:
    async def go() -> None:
        # per_call: a decision the call does not accept raises, and the thread is intact.
        graph, runs = build(one_call, "per_call", decisions=["approve"])
        await drain(graph, first(), cfg("t-p"))
        item = (await pending(graph, cfg("t-p")))[0]
        with pytest.raises(Exception):
            await drain(graph, resume_with(item.id, {"type": "reject"}), cfg("t-p"))
        again = await pending(graph, cfg("t-p"))
        assert [i.id for i in again] == [item.id], "the same pause is still pending"
        await drain(graph, resume_with(item.id, {"type": "approve"}), cfg("t-p"))
        assert runs[DEPLOY] == 1, "a retry works"

        # batched: the wrong count, or a type the call does not allow, raises ValueError ...
        graph, runs = build(two_calls, "batched", gate=(DEPLOY, NOTICE), decisions=["approve"])
        await drain(graph, first(), cfg("t-b"))
        item = (await pending(graph, cfg("t-b")))[0]
        with pytest.raises(ValueError):
            await drain(graph, resume_with(item.id, {"decisions": [{"type": "approve"}]}), cfg("t-b"))
        with pytest.raises(ValueError):
            await drain(graph, resume_with(item.id, {"decisions": [{"type": "reject"}, {"type": "approve"}]}), cfg("t-b"))
        # ... and leaves the thread unable to continue: a correct resume fails the same way.
        both = {"decisions": [{"type": "approve"}, {"type": "approve"}]}
        with pytest.raises(ValueError):
            await drain(graph, resume_with(item.id, both), cfg("t-b"))
        assert runs[DEPLOY] == 0 and runs[NOTICE] == 0

    run(go())


# ---------------------------------------------------------------------------------------------
# 13. R11: a state update settles a pending approval, in both modes


@pytest.mark.parametrize("mode", MODES)
def test_a_state_update_settles_a_pending_approval_in_both_modes(mode: str) -> None:
    async def go() -> None:
        graph, runs = build(two_calls, mode, gate=(DEPLOY,), strict=True)
        await drain(graph, first(), cfg())
        item = (await pending(graph, cfg()))[0]

        # The baseline, on a graph of its own (a failed attempt changes the state it runs on, and
        # its tools would count): a new input on a paused thread fails, as a real provider's would.
        baseline, _ = build(two_calls, mode, gate=(DEPLOY,), strict=True)
        await drain(baseline, first(), cfg())
        with pytest.raises(ValueError, match="must be answered"):
            await drain(baseline, first("again"), cfg())

        # Settle: one state update with a tool message for every call that has none.
        state = await graph.aget_state(cfg())
        answered = {m.tool_call_id for m in state.values["messages"] if isinstance(m, ToolMessage)}
        finished: list[ToolMessage] = []
        for task in state.tasks:
            result = task.result
            if isinstance(result, dict):
                finished += [m for m in result.get("messages", []) if isinstance(m, ToolMessage)]
        answered |= {m.tool_call_id for m in finished}
        last_ai = [m for m in state.values["messages"] if isinstance(m, AIMessage)][-1]
        withdrawn = [
            ToolMessage(
                content="The call was withdrawn: a new message came before it was approved.",
                name=c["name"],
                tool_call_id=c["id"],
                status="error",
            )
            for c in last_ai.tool_calls
            if c["id"] not in answered
        ]
        if mode == "per_call":
            assert [m.name for m in finished] == [NOTICE], "a finished tool's message waits in the task's result"
            assert [m.name for m in withdrawn] == [DEPLOY]
        else:
            assert finished == [] and [m.name for m in withdrawn] == [DEPLOY, NOTICE]
        await graph.aupdate_state(cfg(), {"messages": finished + withdrawn})

        await drain(graph, first("again"), cfg())
        assert not await pending(graph, cfg()), f"the old pause {item.id} is gone"
        messages = await history(graph, cfg())
        assert [m.text for m in messages if isinstance(m, AIMessage)][-1] == "finished"
        assert dangling(messages) == []
        assert runs[DEPLOY] == 0
        assert runs[NOTICE] == (1 if mode == "per_call" else 0), "only the ungated tool ran, in per_call"

    run(go())


# ---------------------------------------------------------------------------------------------
# 14. R12: the model update carries `structured_response`


class Reply(BaseModel):
    status: Literal["input_required", "completed", "error"]
    message: str


READY = {"status": "completed", "message": "all set"}


def _structured(strategy: Any, saver: Any) -> Any:
    script = (
        (lambda m: Call(("Reply", READY)))
        if isinstance(strategy, ToolStrategy)
        else (lambda m: Say('{"status": "completed", "message": "all set"}'))
    )
    return agent(Scripted(script=script), [], saver, response_format=strategy)


@pytest.mark.parametrize("strategy", [ToolStrategy(Reply), ProviderStrategy(Reply)], ids=["tool", "provider"])
def test_the_model_update_carries_structured_response(strategy: Any) -> None:
    async def go() -> None:
        graph = _structured(strategy, memory_saver())
        assert "structured_response" in graph.channels
        parts = await drain(graph, first(), cfg())
        updates = [p["data"]["model"] for p in parts if p["type"] == "updates" and "model" in p["data"]]
        assert len(updates) == 1 and "structured_response" in updates[0]
        assert updates[0]["structured_response"] == Reply(**READY)
        assert updates[0]["messages"], "the model's messages come with it"
        text = "".join(m.text for m, _ in (p["data"] for p in parts if p["type"] == "messages") if isinstance(m, AIMessageChunk))
        if isinstance(strategy, ToolStrategy):
            assert text == "", "ToolStrategy streams no text"
        else:
            assert text.startswith("{") and "all set" in text, "ProviderStrategy streams the JSON as text"

    run(go())


def test_reading_a_structured_response_back_from_sqlite_warns_in_a_known_category(tmp_path: Path) -> None:
    async def go() -> set[str]:
        async with sqlite_saver(tmp_path / "s.db") as saver:
            graph = _structured(ToolStrategy(Reply), saver)
            await drain(graph, first(), cfg())
        async with restart(tmp_path / "s.db") as saver:
            graph = _structured(ToolStrategy(Reply), saver)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                state = await graph.aget_state(cfg())
            assert state.values["structured_response"] in (Reply(**READY), READY)
            return {w.category.__name__ for w in caught}

    categories = run(go())
    print("warning categories on reading a structured_response back:", sorted(categories))
    assert categories <= {"UserWarning", "DeprecationWarning", "PendingDeprecationWarning", "LangGraphDeprecationWarning"}


# ---------------------------------------------------------------------------------------------
# 15. R14: parallel hand-written interrupts, in a stable order


class Log(TypedDict):
    log: Annotated[list[str], lambda a, b: a + b]


def _parallel(names: list[str], starts: Counter[str]) -> Any:
    builder = StateGraph(Log)
    for name in names:

        async def node(state: Log, name: str = name) -> dict[str, Any]:
            starts[name] += 1
            return {"log": [f"{name}:{interrupt({'n': name})}"]}

        builder.add_node(name, node)
        builder.add_edge(START, name)
        builder.add_edge(name, END)
    return builder.compile(checkpointer=memory_saver())


def test_parallel_interrupts_list_in_a_stable_order() -> None:
    async def go() -> None:
        for run_no in range(3):
            starts: Counter[str] = Counter()
            graph = _parallel(["a", "b", "c"], starts)
            await drain(graph, {"log": []}, cfg(f"t-{run_no}"))
            state = await graph.aget_state(cfg(f"t-{run_no}"))
            assert [i.value["n"] for i in state.interrupts] == ["a", "b", "c"]
            assert sorted(len(t.interrupts) for t in state.tasks) == [1, 1, 1], "one interrupt per task"
            # Answer one at a time, by id.
            for expected in ("a", "b", "c"):
                now = await pending(graph, cfg(f"t-{run_no}"))
                assert now[0].value["n"] == expected
                await drain(graph, resume_with(now[0].id, "ok"), cfg(f"t-{run_no}"))
            assert not await pending(graph, cfg(f"t-{run_no}"))
            assert sorted((await graph.aget_state(cfg(f"t-{run_no}"))).values["log"]) == ["a:ok", "b:ok", "c:ok"]

    run(go())


def test_two_interrupts_in_a_row_in_one_node() -> None:
    starts: Counter[str] = Counter()

    async def seq(state: Log) -> dict[str, Any]:
        starts["seq"] += 1
        one = interrupt({"n": "first"})
        two = interrupt({"n": "second"})
        return {"log": [f"{one}+{two}"]}

    builder = StateGraph(Log)
    builder.add_node("seq", seq)
    builder.add_edge(START, "seq")
    builder.add_edge("seq", END)
    graph = builder.compile(checkpointer=memory_saver())

    async def go() -> None:
        await drain(graph, {"log": []}, cfg())
        first_one = (await pending(graph, cfg()))[0]
        assert first_one.value == {"n": "first"}
        await drain(graph, resume_with(first_one.id, "x"), cfg())
        second = (await pending(graph, cfg()))[0]
        assert second.value == {"n": "second"} and second.id != first_one.id
        await drain(graph, resume_with(second.id, "y"), cfg())
        assert not await pending(graph, cfg())
        assert (await graph.aget_state(cfg())).values["log"] == ["x+y"]
        assert starts["seq"] == 3, "the node starts again from its top on every resume"

    run(go())


# ---------------------------------------------------------------------------------------------
# 16. R8: a SQLite restart keeps the interrupt ids


def test_a_sqlite_restart_keeps_interrupt_ids(tmp_path: Path) -> None:
    async def go() -> None:
        path = tmp_path / "a.db"
        async with sqlite_saver(path) as saver:
            graph, runs_before = build(one_call, "per_call", saver=saver)
            await drain(graph, first(), cfg())
            before = await pending(graph, cfg())
        assert runs_before[DEPLOY] == 0

        async with restart(path) as saver:
            graph, runs_after = build(one_call, "per_call", saver=saver)  # a new graph, a new model
            after = await pending(graph, cfg())
            assert [i.id for i in after] == [i.id for i in before]
            assert [i.response_schema for i in after] == [i.response_schema for i in before]
            await drain(graph, resume_with(after[0].id, {"type": "approve"}), cfg())
            assert not await pending(graph, cfg())
        assert runs_before[DEPLOY] + runs_after[DEPLOY] == 1, "the body ran once, after the restart"

        async with sqlite_saver(tmp_path / "b.db") as saver:
            graph, _ = build(one_call, "per_call", saver=saver)
            await drain(graph, first(), cfg())
            other = await pending(graph, cfg())
        assert other[0].id != before[0].id, "ids differ between graphs on different files"

    run(go())


# ---------------------------------------------------------------------------------------------
# 17 and 18. R6, R7, R18: content blocks, usage, and standard blocks as input

PNG = "aGk="


def test_content_blocks_and_usage() -> None:
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "hello"},
        {"type": "reasoning", "reasoning": "thinking it over"},
        {"type": "image", "base64": PNG, "mime_type": "image/png"},
        {"type": "audio", "url": "https://example.invalid/a.mp3", "mime_type": "audio/mpeg"},
        {"type": "video", "base64": PNG, "mime_type": "video/mp4"},
        {"type": "file", "base64": PNG, "mime_type": "application/pdf"},
        {"type": "non_standard", "value": {"x": 1}},
    ]
    message = AIMessage(content=blocks, response_metadata={"output_version": "v1"})  # type: ignore[arg-type]
    got = message.content_blocks
    assert [b["type"] for b in got] == [b["type"] for b in blocks]
    assert got[2].get("base64") == PNG and got[2].get("mime_type") == "image/png"
    assert got[3].get("url") == "https://example.invalid/a.mp3"

    # A streaming chunk's reasoning is in its `reasoning` field, and its `text` is empty.
    chunk = AIMessageChunk(content=[{"type": "reasoning", "reasoning": "thinking", "index": 0}])  # type: ignore[list-item]
    assert chunk.text == ""
    assert chunk.content_blocks[0]["type"] == "reasoning"
    assert chunk.content_blocks[0].get("reasoning") == "thinking"

    # An image hosted by the provider has an id and no data.
    hosted = AIMessage(content=[{"type": "image", "id": "file-1"}], response_metadata={"output_version": "v1"})  # type: ignore[list-item]
    only = hosted.content_blocks[0]
    assert only["type"] == "image" and "base64" not in only and "url" not in only

    async def go() -> None:
        image = {"type": "image", "base64": PNG, "mime_type": "image/png"}
        graph = agent(
            Scripted(script=lambda m: Turn(text="see this", blocks=(image,), tokens=(11, 7), model="m-1")),
            [],
            memory_saver(),
        )
        await drain(graph, first(), cfg())
        final = (await history(graph, cfg()))[-1]
        assert isinstance(final, AIMessage)
        assert final.usage_metadata is not None
        assert final.usage_metadata["input_tokens"] == 11 and final.usage_metadata["output_tokens"] == 7
        assert final.response_metadata["model_name"] == "m-1"
        kinds = [b["type"] for b in final.content_blocks]
        assert "text" in kinds and "image" in kinds

    run(go())


def test_a_human_message_takes_standard_blocks() -> None:
    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": "look at these"},
        {"type": "image", "base64": PNG, "mime_type": "image/png"},
        {"type": "audio", "url": "https://example.invalid/a.mp3", "mime_type": "audio/mpeg"},
        {"type": "video", "base64": PNG, "mime_type": "video/mp4"},
        {"type": "file", "url": "https://example.invalid/r.pdf", "mime_type": "application/pdf"},
    ]
    seen: list[list[Any]] = []

    def script(messages: list[BaseMessage]) -> Turn:
        seen.append(list(messages[-1].content_blocks))
        return Say("seen")

    async def go() -> None:
        graph = agent(Scripted(script=script), [], memory_saver())
        await drain(graph, {"messages": [HumanMessage(content_blocks=blocks)]}, cfg())  # type: ignore[arg-type]

    run(go())
    assert seen == [blocks], "the model gets the blocks as given"


# ---------------------------------------------------------------------------------------------
# 19. R16: facts about LangChain tools


def test_langchain_tool_facts() -> None:
    @tool
    def lookup(
        item: str,
        state: Annotated[dict[str, Any], InjectedState],
        store: Annotated[Any, InjectedStore()],
        runtime: ToolRuntime,
        call_id: Annotated[str, InjectedToolCallId],
        extra: Annotated[int, InjectedToolArg],
    ) -> str:
        """Look an item up."""
        return item

    visible = lookup.tool_call_schema
    shape = visible.model_json_schema() if hasattr(visible, "model_json_schema") else visible
    assert list(shape["properties"]) == ["item"], "the model-visible schema holds only what the model fills in"
    assert set(lookup.args) == {"item"}
    injected = set(lookup.get_input_schema().model_fields) - set(lookup.args)
    assert injected == {"state", "store", "runtime", "call_id", "extra"}

    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    ticks = {"n": 0}

    def slow(**kwargs: Any) -> str:
        import time

        time.sleep(0.3)
        return "slept"

    plain = StructuredTool.from_function(slow, name="slow_step", description="Sleeps.", args_schema=schema)
    carried = dict(plain.tool_call_schema)  # type: ignore[arg-type]
    assert carried.pop("description") == "Sleeps.", "a dict schema comes back with the tool's description added"
    assert carried == schema, "and is otherwise the model-visible schema itself"
    wrapper = plain.get_input_schema().model_json_schema()
    assert wrapper.get("properties") != schema["properties"], "get_input_schema wraps a tool call: not the schema"

    async def go() -> None:
        async def tick() -> None:
            while True:
                ticks["n"] += 1
                await asyncio.sleep(0.05)

        ticker = asyncio.create_task(tick())
        try:
            assert await plain.ainvoke({"a": "x"}) == "slept"
        finally:
            ticker.cancel()
        assert ticks["n"] >= 3, "a sync tool runs off the loop: the loop kept ticking"

        def strict_body(a: str) -> str:
            return a

        unchecked = StructuredTool.from_function(strict_body, name="echo_step", description="Echoes.", args_schema=schema)
        with pytest.raises(TypeError):
            await unchecked.ainvoke({"wrong": 1})  # LangChain does not validate a dict schema

    run(go())


# ---------------------------------------------------------------------------------------------
# 20. R17: the scripted model


def test_the_scripted_model() -> None:
    call = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c-1", "type": "tool_call"}])

    async def go() -> None:
        # The stock fake cannot stream a turn that has a tool call and no text.
        stock = GenericFakeChatModel(messages=iter([call]))
        with pytest.raises(ValueError, match="No generation chunks were returned"):
            _ = [c async for c in stock.astream([HumanMessage("x")])]

        # The scripted one can, and gives the call on a last chunk.
        scripted = Scripted(script=lambda m: Call(("t", {})))
        got = [c async for c in scripted.astream([HumanMessage("x")])]
        assert got and got[-1].tool_calls[0]["name"] == "t"

        # Pure: the same history gives the same answer from a second object.
        def script(messages: list[BaseMessage]) -> Turn:
            return Say(f"seen {humans(messages)}") if humans(messages) < 2 else Say("later")

        one, two = Scripted(script=script), Scripted(script=script)
        history_ = [HumanMessage("a")]
        assert (await one.ainvoke(history_)).text == (await two.ainvoke(history_)).text == "seen 1"
        assert (await one.ainvoke(history_)).text == "seen 1", "asking twice gives the same answer"

        # strict: a tool call that nothing answers is refused.
        strict = Scripted(script=lambda m: Say("x"), strict=True)
        with pytest.raises(ValueError, match="must be answered"):
            await strict.ainvoke([HumanMessage("a"), call])
        await strict.ainvoke([HumanMessage("a"), call, ToolMessage(content="r", tool_call_id="c-1")])

        # The gate holds the stream after k pieces, and the flag says when it was closed early.
        gate = Gate(after=2)
        gated_model = Scripted(script=lambda m: Say("one two three four"), gate=gate)
        received: list[str] = []

        async def consume() -> None:
            async for piece in gated_model.astream([HumanMessage("x")]):
                received.append(piece.text)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(gate.reached.wait(), 5)
        assert received == ["one ", "two "], "exactly `after` pieces came before the gate"
        gate.event.set()
        await asyncio.wait_for(task, 5)
        assert "".join(received) == "one two three four" and gate.closed is False

        held = Gate(after=1)
        again = Scripted(script=lambda m: Say("one two three"), gate=held)

        async def consume_held() -> None:
            async for _ in again.astream([HumanMessage("x")]):
                pass

        task = asyncio.create_task(consume_held())
        await asyncio.wait_for(held.reached.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert held.closed is True, "closing the stream early is visible"

    run(go())
