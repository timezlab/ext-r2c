"""One leg of a run: one call of `astream` read as run events (spec 006, research R3, R5).

A leg is three parts. A **producer task** iterates `astream` and puts each part on a queue; the
per-run **handler** puts what it sees on the same queue; and the generator below is the only
consumer, so the events leave in the order they happened. Its `finally` cancels the producer and
awaits it, which also closes the graph's stream when the door cancels the run.

The leg never touches the graph: the thread and the handler travel in the `config` of this call.

What the caller sees while the leg goes on (reply chunks, tool activity, reasoning, files) is kept by
a `_Timeline`; the leg only moves what is on the queue through it, so the order is the order it happened.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from ext_r2c.core import Activity, ActivityEvent, Approval, Ask, Question, RunEvent, UsageEvent

from ._blocks import files_of
from ._handler import Handler, Hidden, ToolEnded, ToolStarted
from ._reasoning import Reasoning, thoughts
from ._reply import Reply
from ._usage import turn_of, usage_of

__all__ = ["run_leg", "seeded_reply"]

_END = object()
_DETAIL = 2000  # a tool's result or failure message is cut to this many characters (research R4)


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


def sent_before(messages: Sequence[Any]) -> list[str]:
    """The ids of the turn's AI messages an earlier leg already read: their files already left. The
    middleware gives the same message again once an approval is answered, and it must not send them again."""
    return [m.id for m in turn_of(messages) if isinstance(m, AIMessage) and m.id]


def _ai_messages(update: Any) -> list[AIMessage]:
    """The completed AI messages a node's update holds."""
    found = update.get("messages") if isinstance(update, dict) else None
    items = [found] if isinstance(found, BaseMessage) else found
    return [m for m in items if isinstance(m, AIMessage)] if isinstance(items, (list, tuple)) else []


@dataclass(slots=True)
class _Running:
    """A tool in its body: what its terminal activity repeats, and when it started."""

    name: str
    args: dict[str, Any] | None
    at: float


class _Timeline:
    """What one leg has told the caller, and what is still open: the reply's held piece, the reasoning
    still gathering in its buffer and the tools in their body.

    Every method returns the events to send now, in order. `reasoning` and `expose` are the owner's
    options: reasoning is off unless asked for (FR-010), and only an exposed tool shows its input and
    its result (R2C-ACTIVITY-6).
    """

    def __init__(self, reply: Reply, *, reasoning: bool, expose: Collection[str], known: Collection[str]) -> None:
        self.reply = reply
        self._thoughts = Reasoning() if reasoning else None
        self._expose = frozenset(expose)
        self._running: dict[str, _Running] = {}
        self._sent = set(known)  # the messages whose files already left, so a message seen twice sends them once

    # -- what the handler saw ---------------------------------------------------------------------

    def item(self, item: Hidden | ToolStarted | ToolEnded) -> list[RunEvent]:
        if isinstance(item, Hidden):
            self.reply.hide(item.id)
            return []
        if isinstance(item, ToolStarted):
            args = item.args if item.name in self._expose else None
            self._running[item.id] = _Running(item.name, args, item.at)
            return [self._tool(item.id, "running", self._running[item.id])]
        call = self._running.pop(item.id, None)
        if call is None:
            return []
        shown = item.text[:_DETAIL] or None if call.name in self._expose else None
        return [self._tool(item.id, "failed" if item.failed else "done", call, shown, item.at)]

    @staticmethod
    def _tool(id: str, state: str, call: _Running, detail: str | None = None, at: float | None = None) -> RunEvent:
        # Only what has a value is set: a field given as `None` counts as set, and is then checked
        # (and sent) as `null`, which the schema does not allow.
        fields: dict[str, Any] = {"args": call.args, "detail": detail}
        if at is not None:
            fields["duration_ms"] = max(0, round((at - call.at) * 1000))
        shown = {key: value for key, value in fields.items() if value is not None}
        return ActivityEvent(
            Activity(id=id, type="tool", label=call.name, name=call.name, state=state, **shown)  # type: ignore[arg-type]
        )

    # -- what the stream said ---------------------------------------------------------------------

    def part(self, part: Any) -> list[RunEvent]:
        """The events of one stream part."""
        if not isinstance(part, dict):
            return []
        data = part.get("data")
        if part.get("type") == "messages":
            message = data[0]
            if not isinstance(message, AIMessage):
                return []
            out = self._think(message)
            text = str(message.text)
            if text:  # the words start: the thoughts before them are over
                out += self._stop(message.id)
            return out + self.reply.feed(text, message.id)
        if part.get("type") == "updates" and isinstance(data, dict):
            done = [m for update in data.values() for m in _ai_messages(update)]
            out = []
            for message in done:  # the message is complete: its thoughts are over
                out += self._stop(message.id)
            if any(m.tool_calls for m in done):
                # The model asked for tools: the reply may or may not go on, so what is ready leaves now.
                out += self.reply.flush()
            for message in done:
                out += self._send_files(message)
            return out
        return []

    def _think(self, message: AIMessage) -> list[RunEvent]:
        if self._thoughts is None or self.reply.hidden(message.id):
            return []
        return [self._thought(message.id, piece) for piece in self._thoughts.feed(message.id, thoughts(message))]

    def _stop(self, message_id: str | None) -> list[RunEvent]:
        if self._thoughts is None:
            return []
        return [self._thought(message_id, piece) for piece in self._thoughts.end(message_id)]

    @staticmethod
    def _thought(message_id: str | None, piece: str) -> RunEvent:
        return ActivityEvent(Activity(id=f"reasoning-{message_id}", type="reasoning", label="Thinking", delta=piece))

    def _send_files(self, message: AIMessage) -> list[RunEvent]:
        if self.reply.hidden(message.id) or (message.id is not None and message.id in self._sent):
            return []
        if message.id is not None:
            self._sent.add(message.id)
        return list(files_of(message))

    # -- when the leg stops -----------------------------------------------------------------------

    def settle(self) -> list[RunEvent]:
        """What is ready leaves before an ask or before the end of the turn: the thoughts still in the
        buffer, then the reply's held piece (the end of the turn closes the reply itself)."""
        if self._thoughts is None:
            return []
        return [self._thought(message_id, text) for message_id, text in self._thoughts.drain()]

    def pause(self) -> list[RunEvent]:
        return self.settle() + list(self.reply.flush())

    def fail(self) -> list[RunEvent]:
        """The graph raised: what is ready leaves, and each tool still in its body ends `failed` (no
        callback of its end will come), before the exception goes on (FR-013)."""
        out = self.pause()
        now = time.monotonic()
        out += [self._tool(id, "failed", call, None, now) for id, call in self._running.items()]
        self._running.clear()
        return out


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
    *,
    reasoning: bool = False,
    expose_tools: Collection[str] = (),
    known: Collection[str] = (),
) -> AsyncIterator[RunEvent]:
    """The events of one call of `astream`; ends right after an `Ask`, or at the end of the turn.

    When the graph is left with pending interrupts, `pick` chooses from the thread's state the one
    request to ask (it may raise, and then the run ends `failed`: nothing is asked). `reasoning` and
    `expose_tools` are the owner's options (see `_Timeline`); `known` are the ids of the turn's
    messages an earlier leg already read (`sent_before`).
    """
    queue: asyncio.Queue[Any] = asyncio.Queue()
    thread = {"configurable": {"thread_id": thread_id}}
    timeline = _Timeline(reply, reasoning=reasoning, expose=expose_tools, known=known)
    producer = asyncio.create_task(_produce(graph, graph_input, {**thread, "callbacks": [Handler(queue)]}, queue))
    try:
        while (item := await queue.get()) is not _END:
            if isinstance(item, _Failure):
                for event in timeline.fail():
                    yield event
                raise item.error
            for event in timeline.item(item) if isinstance(item, (Hidden, ToolStarted, ToolEnded)) else timeline.part(item):
                yield event

        state = await graph.aget_state(thread)
        if state.interrupts:  # read from the checkpointer, never from the stream
            for event in timeline.pause():
                yield event
            yield Ask(pick(state))
            return
        messages = _messages(state.values)
        had_text = any(
            isinstance(m, AIMessage) and m.text and not reply.hidden(m.id) for m in turn_of(messages)
        )
        for event in timeline.settle():
            yield event
        for closing in reply.end_turn(had_text):
            yield closing
        usage = usage_of(messages)
        if usage is not None:
            yield UsageEvent(usage)
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
