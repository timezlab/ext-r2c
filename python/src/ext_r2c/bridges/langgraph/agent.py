"""`LangGraphAgent`: a compiled LangGraph graph as an `AgentSource` of the checkpoint style
(spec 006; contracts/langgraph-api.md).

The graph is never changed (FR-001): the bridge reads its schema and checkpointer when wrapping,
and for each run passes the thread and a per-run callback handler in the `config` of the call.
"""

from __future__ import annotations

import warnings
from collections.abc import AsyncIterator, Iterable
from contextlib import aclosing
from functools import partial
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from langgraph.pregel import Pregel
from langgraph.types import Command

from ext_r2c.core import (
    Answer,
    Approval,
    Ask,
    CardInfo,
    PauseLost,
    Question,
    RunContext,
    RunEvent,
    RunInput,
    check_answer,
)

from ._batch import Batches
from ._blocks import to_message
from ._decisions import check, to_graph
from ._leg import run_leg, seeded_reply, sent_before
from ._pauses import read_pauses, resume_value
from ._reply import Reply
from .tools import tools_by_name

__all__ = ["LangGraphAgent"]

_DEFAULT_DESCRIPTION = "A LangGraph agent served through R2C."


def _accepts_messages(graph: Pregel) -> bool:
    """Whether the graph's input has a `messages` key (D1): the caller's text goes in as a human message."""
    schema: Any = graph.get_input_jsonschema()
    ref = schema.get("$ref") if isinstance(schema, dict) else None
    if isinstance(ref, str) and ref.startswith("#/"):  # a state class that is described by reference
        node: Any = schema
        for key in ref[2:].split("/"):
            node = node.get(key) if isinstance(node, dict) else None
        schema = node
    properties = schema.get("properties") if isinstance(schema, dict) else None
    return isinstance(properties, dict) and "messages" in properties


class LangGraphAgent:
    """A compiled LangGraph graph (a LangChain agent) served over R2C, with its checkpointer as the
    place a paused run waits. Wrap it, then give it to a door: `LangGraphAgent(graph)`.

    Refused at construction, each with a message that names the missing piece: an object that is not
    a compiled graph (`TypeError`), a graph with no checkpointer (`ValueError`), a graph whose input
    has no `messages` (`ValueError`), and an `expose_tools` that holds a non-string (`TypeError`).
    An in-memory checkpointer works and warns once: a pause will not survive a restart.
    """

    pause: Literal["checkpoint"] = "checkpoint"

    def __init__(
        self,
        graph: Pregel,
        *,
        card: CardInfo | None = None,
        reasoning: bool = False,
        expose_tools: Iterable[str] = (),
    ) -> None:
        if isinstance(graph, StateGraph):
            raise TypeError(
                "LangGraphAgent needs a compiled graph, not a StateGraph: call "
                ".compile(checkpointer=...) first and pass what it returns."
            )
        if not isinstance(graph, Pregel):
            raise TypeError(f"LangGraphAgent needs a compiled LangGraph graph, not {type(graph).__name__}.")
        checkpointer = graph.checkpointer
        if not isinstance(checkpointer, BaseCheckpointSaver):
            raise ValueError(
                "The graph has no checkpointer of its own: a paused run waits in the checkpointer. "
                "Compile it with .compile(checkpointer=...)."
            )
        if not _accepts_messages(graph):
            raise ValueError(
                "The graph's input has no `messages`: the bridge sends the caller's text as a human "
                "message under `messages`, so give the graph a state with a `messages` key."
            )
        names = tuple(expose_tools)
        if not all(isinstance(name, str) for name in names):
            raise TypeError("expose_tools must hold tool names (strings).")
        if isinstance(checkpointer, InMemorySaver):
            warnings.warn(
                "The graph's checkpointer keeps its state in memory: a paused run will not survive a "
                "restart of this process. Compile the graph with a durable checkpointer, one with "
                "async support, so a pause can be answered later.",
                UserWarning,
                stacklevel=2,
            )
        self._graph = graph
        self._reasoning = reasoning
        self._expose_tools = frozenset(names)
        self._tools = tools_by_name(graph)  # only to find the schema of an edit
        self._batches = Batches()  # the decisions of the batches in progress: the agent's only state
        self.card = card if card is not None else CardInfo(graph.name or "LangGraph", _DEFAULT_DESCRIPTION, "0.0.0")

    def _next_ask(self, thread_id: str, state: Any) -> Question | Approval:
        """The one request to ask now: the first pending one, leaving out the calls of a batch that
        already have a decision."""
        pauses = read_pauses(state, self._tools)

        def open_(pause: Any) -> bool:
            batch = self._batches.get(thread_id, pause.interrupt_id) if pause.kind == "batch_call" else None
            return batch is None or pause.position not in batch.decisions

        return next((p for p in pauses if open_(p)), pauses[0]).request

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        """One turn on the context's thread: the input as one human message."""
        pick = partial(self._next_ask, ctx.thread_id)
        leg = run_leg(
            self._graph, {"messages": [to_message(input)]}, ctx.thread_id, Reply(), pick,
            reasoning=self._reasoning, expose_tools=self._expose_tools,
        )
        async with aclosing(leg) as events:
            async for event in events:
                yield event

    async def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        """Go on from the pause the answer is for: found again in the checkpointer, never trusted.

        The checks come in this order, and each refusal leaves the graph untouched and the pause
        pending: the request is still pending, the core accepts the answer, the graph accepts the
        decision.
        """
        thread = ctx.thread_id
        state = await self._graph.aget_state({"configurable": {"thread_id": thread}})
        pauses = read_pauses(state, self._tools)
        self._batches.prune(thread, (p.interrupt_id for p in pauses))  # what the graph no longer holds
        pause = next((p for p in pauses if p.request.id == answer.id), None)
        if pause is None:
            raise PauseLost(f"The paused run was lost: nothing waits for request {answer.id!r}. Ask again.")
        problems = check_answer(answer, pause.request)
        if problems:
            raise ValueError("The answer is not acceptable: " + "; ".join(p.message for p in problems))
        check(answer, pause)

        value: Any
        if pause.kind == "batch_call":
            assert pause.position is not None and pause.batch_size is not None
            batch = self._batches.record(
                thread, pause.interrupt_id, size=pause.batch_size, position=pause.position,
                decision=to_graph(answer, pause),
            )
            if not batch.complete():  # the graph needs them all at once: ask the next call, call nothing
                yield Ask(self._next_ask(thread, state))
                return
            value = {"decisions": batch.ordered()}
            self._batches.drop(thread, pause.interrupt_id)
        elif pause.kind == "tool_call":
            value = to_graph(answer, pause)
        else:
            value = resume_value(answer)

        values = state.values
        earlier = values.get("messages") or () if isinstance(values, dict) else ()
        leg = run_leg(
            self._graph, Command(resume={pause.interrupt_id: value}), thread, seeded_reply(earlier),
            partial(self._next_ask, thread),
            reasoning=self._reasoning, expose_tools=self._expose_tools, known=sent_before(earlier),
        )
        async with aclosing(leg) as events:
            async for event in events:
                yield event
