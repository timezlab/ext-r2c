"""One leg of a run: one call of `astream` read as run events (spec 006, research R3, R5).

A leg is three parts. A **producer task** iterates `astream` and puts each part on a queue; the
per-run **handler** puts what it sees on the same queue; and the generator below is the only
consumer, so the events leave in the order they happened. Its `finally` cancels the producer and
awaits it, which also closes the graph's stream when the door cancels the run.

The leg never touches the graph: the thread and the handler travel in the `config` of this call.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from ext_r2c.core import Approval, Ask, Question, RunEvent, UsageEvent

from ._handler import Handler, Hidden
from ._reply import Reply
from ._usage import turn_of, usage_of

__all__ = ["run_leg", "seeded_reply"]

_END = object()


@dataclass(frozen=True, slots=True)
class _Failure:
    """On the queue: the exception that ended the producer."""

    error: BaseException


def _messages(values: Any) -> list[Any]:
    found = values.get("messages") if isinstance(values, dict) else None
    return list(found) if isinstance(found, (list, tuple)) else []


def seeded_reply(messages: Sequence[Any]) -> Reply:
    """The reply of a leg that goes on after a pause: it knows which message spoke last, so the
    next message gets its blank line, and the closing chunk can tell the turn had reply text."""
    for message in reversed(turn_of(messages)):
        if isinstance(message, AIMessage) and message.text:
            return Reply(previous=message.id)
    return Reply()


def _holds_tool_calls(update: Any) -> bool:
    """A node's update that holds a completed AI message asking for tools."""
    found = update.get("messages") if isinstance(update, dict) else None
    items = [found] if isinstance(found, BaseMessage) else found
    return isinstance(items, (list, tuple)) and any(isinstance(m, AIMessage) and m.tool_calls for m in items)


def _events(part: Any, reply: Reply) -> Sequence[RunEvent]:
    """The run events of one stream part."""
    if not isinstance(part, dict):
        return ()
    data = part.get("data")
    if part.get("type") == "messages":
        message = data[0]
        return reply.feed(str(message.text), message.id) if isinstance(message, AIMessage) else ()
    if part.get("type") == "updates" and isinstance(data, dict):
        # The model asked for tools: the reply may or may not go on, so what is ready leaves now.
        return reply.flush() if any(_holds_tool_calls(update) for update in data.values()) else ()
    return ()


async def _produce(graph: Any, graph_input: Any, config: dict[str, Any], queue: asyncio.Queue[Any]) -> None:
    try:
        async for part in graph.astream(graph_input, config, stream_mode=["messages", "updates"], version="v2"):
            queue.put_nowait(part)
    except asyncio.CancelledError:
        raise
    except BaseException as error:  # noqa: BLE001 - whatever ended the stream is the consumer's to raise
        queue.put_nowait(_Failure(error))
    else:
        queue.put_nowait(_END)


async def run_leg(
    graph: Any,
    graph_input: Any,
    thread_id: str,
    reply: Reply,
    pick: Callable[[Any], Question | Approval],
) -> AsyncIterator[RunEvent]:
    """The events of one call of `astream`; ends right after an `Ask`, or at the end of the turn.

    When the graph is left with pending interrupts, `pick` chooses from the thread's state the one
    request to ask (it may raise, and then the run ends `failed`: nothing is asked).
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    thread = {"configurable": {"thread_id": thread_id}}
    producer = asyncio.create_task(_produce(graph, graph_input, {**thread, "callbacks": [Handler(queue)]}, queue))
    try:
        while (item := await queue.get()) is not _END:
            if isinstance(item, _Failure):
                for chunk in reply.flush():
                    yield chunk
                raise item.error
            if isinstance(item, Hidden):
                reply.hide(item.id)
                continue
            for event in _events(item, reply):
                yield event

        state = await graph.aget_state(thread)
        if state.interrupts:  # read from the checkpointer, never from the stream
            for chunk in reply.flush():
                yield chunk
            yield Ask(pick(state))
            return
        messages = _messages(state.values)
        had_text = any(
            isinstance(m, AIMessage) and m.text and not reply.hidden(m.id) for m in turn_of(messages)
        )
        for closing in reply.end_turn(had_text):
            yield closing
        usage = usage_of(messages)
        if usage is not None:
            yield UsageEvent(usage)
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
