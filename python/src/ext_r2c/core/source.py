"""Agent sources and the one driver that runs both pause styles (FR-021 to FR-025, research R10,
R11).

A **checkpoint** source yields an ``Ask`` and ends its iterator; the driver later calls
``resume(answer, ctx)``. A **live** source awaits ``ctx.ask(request)`` inside ``run``. The driver
runs the source in one task that feeds one queue, so a door reads one ordered stream either way.
It emits ``AnswerEvent`` and the single terminal event itself, and ends a run that breaks the
sequence rules with ``Error("protocol")``. It checks no answer: the door does, then delivers.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, Protocol

from .events import AnswerEvent, Ask, Content, Done, Error, RunEvent
from .models import Answer, AnsweredBy, Approval, Question

__all__ = ["AgentSource", "CardInfo", "CardSkill", "Driver", "Run", "RunContext", "RunInput", "thread_id"]

_CANCEL_GRACE = 5.0  # seconds a live source has to see its declined answer after a cancel
_END = object()


def thread_id(door: Literal["a2a", "mcp"], owner: str, context_id: str) -> str:
    """The thread of one owner's context over one door (R2C-ID-1, R11). The owner stays out of it."""
    if door not in ("a2a", "mcp"):
        raise ValueError(f"unknown door {door!r}")
    digest = hashlib.sha256(json.dumps([door, owner, context_id]).encode("utf-8")).hexdigest()
    return f"{door}:{digest[:32]}"


@dataclass(frozen=True, slots=True)
class CardSkill:
    id: str
    name: str
    description: str
    tags: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CardInfo:
    name: str
    description: str
    version: str
    skills: tuple[CardSkill, ...] = ()


@dataclass(frozen=True, slots=True)
class RunInput:
    text: str
    parts: tuple[Content, ...] = ()


class RunContext:
    """What a source gets for one run: its thread, a cancel signal, and (live only) ``ask``."""

    def __init__(self, thread_id: str, ask: Callable[[Question | Approval], Any]) -> None:
        self.thread_id = thread_id
        self.cancelled = asyncio.Event()
        self._ask = ask

    async def ask(self, request: Question | Approval) -> Answer:
        """Live sources only: emit the ``Ask`` and wait for the answer. A cancelled run answers
        ``declined``. A checkpoint source calling it ends the run with ``Error("protocol")``."""
        answer: Answer = await self._ask(request)
        return answer


class AgentSource(Protocol):
    card: CardInfo
    pause: Literal["checkpoint", "live"]

    def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]: ...

    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]: ...  # checkpoint only


class _Broken(Exception):
    """The source broke the sequence rules; the run has already ended with ``Error("protocol")``."""


def _declined(request: Question | Approval) -> Answer:
    return Answer(id=request.id, outcome="declined", answered_by=AnsweredBy(role="policy"),
                  note="The run was cancelled.")


Factory = Callable[[RunContext], AsyncIterator[RunEvent]]


class Run:
    """One run of a source: an async iterator of run events, answered with ``deliver``."""

    def __init__(self, driver: Driver, thread_id: str, factory: Factory | None) -> None:
        self._driver = driver
        self._source = driver.source
        self._live = driver.source.pause == "live"
        self.thread_id = thread_id
        self.pending: Question | Approval | None = None
        self._ctx = RunContext(thread_id, self._ask)
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._factory = factory
        self._task: asyncio.Task[None] | None = None
        self._future: asyncio.Future[Answer] | None = None
        self._asked = False  # the current checkpoint iterator has yielded its Ask
        self._finished = False
        self._closed = False

    # --- the door's side --------------------------------------------------------------------

    def __aiter__(self) -> Run:
        return self

    async def __anext__(self) -> RunEvent:
        if self._closed:
            raise StopAsyncIteration
        if self._factory is not None and not self._finished:
            factory, self._factory = self._factory, None
            self._spawn(factory)
        event = await self._queue.get()
        if event is _END:
            self._closed = True
            raise StopAsyncIteration
        return event  # type: ignore[no-any-return]

    async def deliver(self, answer: Answer) -> None:
        """Answer the pending ``Ask``; ``ValueError`` when nothing is pending."""
        if self._finished or self.pending is None:
            raise ValueError("this run has no pending ask")
        self.pending = None
        self._put(AnswerEvent(answer))
        if self._live:
            future, self._future = self._future, None
            assert future is not None
            future.set_result(answer)
        else:
            self._spawn(lambda ctx: self._source.resume(answer, ctx))

    async def cancel(self) -> None:
        """End the run with ``Error("cancelled")``. A paused live source sees a declined answer; a
        paused checkpoint source is never resumed."""
        if self._finished:
            return
        self._ctx.cancelled.set()
        handed = False
        if self._future is not None and not self._future.done() and self.pending is not None:
            self._future.set_result(_declined(self.pending))
            handed = True
        self._finish(Error("cancelled", "The run was cancelled."))
        task = self._task
        if task is None or task.done():
            return
        if handed:
            await asyncio.wait({task}, timeout=_CANCEL_GRACE)
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # --- the source's side ------------------------------------------------------------------

    def _spawn(self, factory: Factory) -> None:
        self._asked = False
        self._task = asyncio.get_running_loop().create_task(self._pump(factory))

    async def _pump(self, factory: Factory) -> None:
        events: AsyncIterator[RunEvent] | None = None
        try:
            events = factory(self._ctx)
            async for event in events:
                if self._finished:
                    break
                self._accept(event)
        except _Broken:
            return
        except Exception as exc:  # the source failed: the run ends, the door reads why
            self._finish(Error("failed", str(exc) or type(exc).__name__))
            return
        finally:
            aclose = getattr(events, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()
        if not self._finished and self.pending is None:
            self._finish(Done())

    def _accept(self, event: RunEvent) -> None:
        if isinstance(event, (AnswerEvent, Done, Error)):
            self._break(f"a source does not yield {type(event).__name__}; the driver does")
        if isinstance(event, Ask):
            if self.pending is not None:
                self._break("a second Ask came before the first was answered")
            if self._live:
                self._break("a live source asks through ctx.ask, not by yielding Ask")
            self.pending = event.request
            self._asked = True
        elif self._asked:
            self._break("a checkpoint source yields nothing after its Ask")
        self._put(event)

    async def _ask(self, request: Question | Approval) -> Answer:
        if self._finished:
            raise _Broken("the run has ended")
        if not self._live:
            self._break("a checkpoint source asks by yielding Ask, not through ctx.ask")
        if self.pending is not None:
            self._break("a second Ask came before the first was answered")
        self.pending = request
        self._future = asyncio.get_running_loop().create_future()
        self._put(Ask(request))
        return await self._future

    def _break(self, reason: str) -> NoReturn:
        self._finish(Error("protocol", reason))
        raise _Broken(reason)

    def _put(self, event: RunEvent) -> None:
        if not self._finished:
            self._queue.put_nowait(event)

    def _finish(self, event: Done | Error) -> None:
        if self._finished:
            return
        self._finished = True
        self.pending = None
        self._queue.put_nowait(event)
        self._queue.put_nowait(_END)
        if self._future is not None and not self._future.done():
            self._future.cancel()
        self._driver._release(self)


class Driver:
    """Runs one source, of either pause style, the same way for every door."""

    def __init__(self, source: AgentSource) -> None:
        pause = getattr(source, "pause", None)
        if pause not in ("checkpoint", "live"):
            raise TypeError(f"a source declares pause = 'checkpoint' or 'live', not {pause!r}")
        if not callable(getattr(source, "run", None)):
            raise TypeError("a source has a run(input, ctx) method")
        if pause == "checkpoint" and not callable(getattr(source, "resume", None)):
            raise TypeError("a checkpoint source has a resume(answer, ctx) method")
        self.source = source
        self._runs: dict[str, Run] = {}

    def start(self, thread_id: str, input: RunInput) -> Run:
        """Start a run on a thread that has none."""
        run = Run(self, self._free(thread_id), lambda ctx: self.source.run(input, ctx))
        self._runs[thread_id] = run
        return run

    def resume(self, thread_id: str, request: Question | Approval, answer: Answer) -> Run:
        """Answer a paused run this driver does not hold, as after a restart: ``request`` is the
        pending request the door kept. A live source's run is gone, so this gives ``Error("lost")``.
        While the driver holds the run, ``Run.deliver`` is the way to answer it."""
        self._free(thread_id)
        run = Run(self, thread_id, None)
        if self.source.pause == "live":
            run._finish(Error("lost", f"The paused run for {request.id} was lost on a restart; ask again."))
            return run
        self._runs[thread_id] = run
        run._put(AnswerEvent(answer))
        run._factory = lambda ctx: self.source.resume(answer, ctx)
        return run

    def _free(self, thread_id: str) -> str:
        if thread_id in self._runs:
            raise ValueError(f"thread {thread_id} already has a run; answer it with Run.deliver")
        return thread_id

    def _release(self, run: Run) -> None:
        if self._runs.get(run.thread_id) is run:
            del self._runs[run.thread_id]
