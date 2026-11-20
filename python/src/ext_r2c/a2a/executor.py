"""An a2a-sdk executor that serves an ``ext_r2c.core.AgentSource`` (spec 003 research R1).

a2a-sdk calls ``execute`` once per client message, and the call returns when the task reaches
input-required. The executor holds one core ``Run`` per task id: each call reads the run's
events until an ``Ask`` or the end. The next call checks the answer and delivers it to the same
run. When no run is held for a paused task (after a restart), the driver resumes the source:
a checkpoint source goes on, and a live source's run ends lost.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.owner_resolver import OwnerResolver
from a2a.server.tasks import TaskStore

from ..core import (
    ActivityEvent,
    AgentSource,
    ArtifactEvent,
    Ask,
    Done,
    Driver,
    Error,
    Limits,
    ReplyChunk,
    Run,
    RunInput,
    UsageEvent,
    thread_id,
)
from ._codec import part_to_content, read_part
from .task import ContentTooLarge, PendingMemory, R2CTask

__all__ = ["SourceExecutor"]


class SourceExecutor(AgentExecutor):
    """Serves one source, of either pause style, with R2C."""

    def __init__(self, source: AgentSource, *, clock: Callable[[], datetime] | None = None,
                 limits: Limits = Limits()) -> None:
        self.driver = Driver(source)
        self.clock = clock
        self.limits = limits
        self.memory = PendingMemory()
        self._runs: dict[str, Run] = {}
        self._threads: dict[str, str] = {}  # task id → thread of the run in `_runs`
        self._store: TaskStore | None = None
        self._owner: OwnerResolver | None = None

    def bind(self, task_store: TaskStore, owner_resolver: OwnerResolver) -> None:
        """Use the handler's store and owner resolver; ``a2a_app`` calls it."""
        self._store = task_store
        self._owner = owner_resolver

    def _task(self, context: RequestContext, queue: EventQueue) -> R2CTask:
        return R2CTask(context, queue, memory=self.memory, clock=self.clock, limits=self.limits)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if self._owner is None:
            raise RuntimeError("SourceExecutor.bind was never called; serve it with a2a_app")
        task = self._task(context, event_queue)
        thread = thread_id("a2a", self._owner(context.call_context), task.context_id)
        if context.current_task is None:
            if not await task.open(store=self._store, owner_resolver=self._owner):
                return
            await self._drop_stale(thread)
            run = self.driver.start(thread, _input(context))
            self._hold(task.task_id, thread, run)
        else:
            request = task.pending
            answer = await task.take_answer()
            if answer is None or request is None:
                return
            held = self._runs.get(task.task_id)
            if held is not None:
                run = held
                await run.deliver(answer)
            else:
                run = self.driver.resume(thread, request, answer)
                self._hold(task.task_id, thread, run)
        await self._pump(task, run)

    def _hold(self, task_id: str, thread: str, run: Run) -> None:
        self._runs[task_id] = run
        self._threads[task_id] = thread

    def _forget(self, task_id: str) -> Run | None:
        self._threads.pop(task_id, None)
        return self._runs.pop(task_id, None)

    async def _drop_stale(self, thread: str) -> None:
        """Cancel a run still held for ``thread``. ``open`` found no unfinished task of this owner
        in this context, so such a run belongs to a task a2a-sdk ended without asking us, as on
        a failed write."""
        for task_id in [t for t, held in self._threads.items() if held == thread]:
            run = self._forget(task_id)
            if run is not None:
                await run.cancel()

    async def _pump(self, task: R2CTask, run: Run) -> None:
        try:
            async for event in run:
                if isinstance(event, ActivityEvent):
                    await task.activity(event.activity)
                elif isinstance(event, ReplyChunk):
                    await task.reply(event.text, last=event.last)
                elif isinstance(event, ArtifactEvent):
                    await task.artifact(event)
                elif isinstance(event, UsageEvent):
                    await task.usage(event.usage)
                elif isinstance(event, Ask):
                    await task.ask(event.request)
                    return
                elif isinstance(event, Done):
                    await task.complete()
                elif isinstance(event, Error) and event.code != "cancelled":
                    await task.fail(event.reason)
                # AnswerEvent: already on the wire as the client's message. Error("cancelled"):
                # only `cancel` cancels a run, and it writes the canceled status itself.
        except ContentTooLarge:
            await run.cancel()  # the task has already ended failed
        except Exception:
            await run.cancel()  # a2a-sdk ends the task failed; the thread is free again
            self._forget(task.task_id)
            raise
        self._forget(task.task_id)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel the run through the driver and end the task canceled (FR-005)."""
        task = self._task(context, event_queue)
        run = self._forget(task.task_id)
        if run is not None:
            await run.cancel()
        await task.cancelled()


def _input(context: RequestContext) -> RunInput:
    """The client's first message as the run's input: its text, and its other content."""
    message = context.message
    parts = list(message.parts) if message is not None else []
    text = "\n".join(p.text for p in parts if p.HasField("text"))
    contents = tuple(
        c for p in parts
        if not p.HasField("text") and read_part(p) is None and (c := part_to_content(p)) is not None
    )
    return RunInput(text, contents)
