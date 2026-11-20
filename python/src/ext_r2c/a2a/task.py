"""R2C on one A2A task, for any a2a-sdk executor (spec 003 research R18, contracts/wire-mapping.md).

An ``R2CTask`` is built per ``execute`` call. It writes run events as A2A with R2C when the
request activated it, and as plain text and standard artifacts when not (R2C-ACT-3). It reads
what the task waits for back from the stored task (research R2). Without activation that is in
a ``PendingMemory`` the executor keeps (spec FR-006).
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, Part, TaskState
from google.protobuf import json_format

from .. import URI
from ..core import (
    Activity,
    Answer,
    AnsweredBy,
    Approval,
    ArtifactEvent,
    ArtifactMeta,
    BytesContent,
    Limits,
    Problem,
    Question,
    R2CObject,
    TextContent,
    Usage,
    check_answer,
    check_size,
    fallback_text,
    parse,
    to_json,
)
from ._codec import Invalid, artifact_update, last_usage, pending_request, r2c_part, read_parts, text_answer
from .activation import is_active

__all__ = ["ContentTooLarge", "PendingMemory", "R2CTask"]

REPLY_ID = "reply"
_REPLY_META = ArtifactMeta(presentation="inline", response=True)
_LOST = "The request this task waited for was lost when the remote restarted; please start again."


class PendingMemory:
    """Task id → the request it waits for, for tasks whose caller did not activate R2C: the
    wire then carries no R2C request to read back. In memory only; a restart loses it."""

    def __init__(self) -> None:
        self._requests: dict[str, Question | Approval] = {}

    def get(self, task_id: str) -> Question | Approval | None:
        return self._requests.get(task_id)

    def put(self, task_id: str, request: Question | Approval) -> None:
        self._requests[task_id] = request

    def drop(self, task_id: str) -> None:
        self._requests.pop(task_id, None)


class ContentTooLarge(Exception):
    """Outgoing content above ``Limits.message_bytes`` (R2C-SAFETY-4). The task has already
    ended failed when this is raised."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.message)
        self.problem = problem


def _join(*pieces: str | None) -> str:
    return "\n\n".join(p for p in pieces if p)


def _text_of(parts: Iterable[Part]) -> str:
    return "\n".join(p.text for p in parts if p.HasField("text"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expired(request: Question | Approval, now: datetime) -> bool:
    expires = request.expires()
    return expires is not None and now >= expires


class R2CTask:
    def __init__(
        self,
        context: RequestContext,
        queue: EventQueue,
        *,
        memory: PendingMemory | None = None,
        clock: Callable[[], datetime] | None = None,
        limits: Limits = Limits(),
    ) -> None:
        if context.task_id is None or context.context_id is None:
            raise ValueError("the request context has no task id or context id")
        self.context = context
        self.queue = queue
        self.memory = memory
        self.limits = limits
        self._clock = clock or _now
        self.active = is_active(context)
        self.task_id: str = context.task_id
        self.context_id: str = context.context_id
        self._updater = TaskUpdater(queue, self.task_id, self.context_id)
        current = context.current_task
        self.pending: Question | Approval | None = None
        self._usage: Usage | None = None
        self._reply_started = False
        if current is not None:
            if current.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                self.pending = pending_request(current) or (memory.get(self.task_id) if memory else None)
            self._usage = last_usage(current)
            self._reply_started = any(a.artifact_id == REPLY_ID for a in current.artifacts)
        self._gathered: list[str] = []  # the reply, without activation
        self._note: str | None = None  # a refusal due in the next status (phase 4)

    # --- opening ----------------------------------------------------------------------------

    async def open(self) -> bool:
        """Emit the ``Task`` when the task is new. ``False`` when the task was refused."""
        if self.context.current_task is None:
            if self.context.message is None:
                raise ValueError("a new task needs the client's message")
            await self.queue.enqueue_event(new_task_from_user_message(self.context.message))
        return True

    # --- while working ----------------------------------------------------------------------

    def _message(self, text: str, *objects: R2CObject | None) -> Message:
        parts = [Part(text=text)]
        if self.active:
            parts.extend(r2c_part(o) for o in objects if o is not None)
        return self._updater.new_agent_message(parts)

    async def activity(self, activity: Activity) -> None:
        """A working status with the activity (one per status, R2C-A2A-3). Without activation,
        the text only, and a ``reasoning`` activity is dropped."""
        if not self.active and activity.type == "reasoning":
            return
        await self._updater.update_status(TaskState.TASK_STATE_WORKING, self._message(fallback_text(activity), activity))

    async def reply(self, text: str, *, last: bool = False) -> None:
        """The next piece of the reply: a chunk of the ``reply`` artifact, or, without activation,
        text kept for the next status."""
        await self._check(check_size(text=text, limits=self.limits))
        if not self.active:
            self._gathered.append(text)
            return
        update = artifact_update(self.task_id, self.context_id, REPLY_ID, (TextContent(text),), meta=_REPLY_META,
                                 append=self._reply_started, last_chunk=last)
        self._reply_started = True
        await self.queue.enqueue_event(update)

    async def artifact(self, event: ArtifactEvent) -> None:
        """An artifact update; its R2C metadata only when active (R2C-A2A-5)."""
        for content in event.parts:
            if isinstance(content, TextContent):
                await self._check(check_size(text=content.text, limits=self.limits))
            elif isinstance(content, BytesContent):
                encoded = base64.b64encode(content.data).decode("ascii")
                await self._check(check_size(raw_base64=encoded, limits=self.limits))
        update = artifact_update(self.task_id, self.context_id, event.id, event.parts,
                                 meta=event.meta if self.active else None, name=event.name,
                                 description=event.description, last_chunk=True)
        await self.queue.enqueue_event(update)

    async def usage(self, usage: Usage) -> None:
        """Hold the usage for the next input-required or terminal status (R2C-USAGE-2, O10)."""
        self._usage = usage

    async def _check(self, problem: Problem | None) -> None:
        if problem is not None:
            await self.fail(problem.message)
            raise ContentTooLarge(problem)

    # --- pausing ----------------------------------------------------------------------------

    async def ask(self, request: Question | Approval) -> None:
        """An input-required status with the request (R2C-A2A-1), or its text only."""
        text = _join(self._note, "".join(self._gathered), fallback_text(request))
        self._note, self._gathered = None, []
        if not self.active and self.memory is not None:
            self.memory.put(self.task_id, request)
        self.pending = request
        await self._updater.requires_input(self._message(text, request, self._usage))

    async def take_answer(self) -> Answer | None:
        """The answer in the client's message, to deliver to the agent (research R7 to R9).

        It gives an acceptable answer, or the expiry outcome (a declined answer by ``policy``,
        whose refusal note goes into the next status). It gives ``None`` once it has already
        written the next status itself: the same request again with ``errors`` (R2C-ASK-6), a
        refusal in text (R2C-ASK-5), or the failed end of a task whose request was lost."""
        request = self.pending
        if request is None:
            await self.fail(_LOST)
            return None
        if _expired(request, self._clock()):
            return self._expiry(request)
        parts = list(self.context.message.parts) if self.context.message is not None else []

        too_large = next((p for p in map(self._size, parts) if p is not None), None)
        if too_large is not None:
            await self._reask(request, [too_large])
            return None
        objects = list(read_parts(parts))
        answers = [o for o in objects if isinstance(o, Answer)]
        broken = any(isinstance(o, Invalid) and o.kind in ("answer", None) for o in objects)
        if not answers and broken:
            await self._reask(request, [Problem("invalid_answer", None, "The answer is not well formed.")])
            return None
        if not answers:
            if self.active:
                await self._refuse(f"This message has no answer for request {request.id}, which is still waiting.")
                return None
            built = text_answer(request, _text_of(parts))
            if built is None:
                await self.ask(request)  # asked again in text (R2C-ASK-8)
                return None
            answers = [built]

        found = [a for a in answers if a.id == request.id]
        if len(found) > 1:
            await self._refuse(f"This message has {len(found)} answers for request {request.id}; send one.")
            return None
        if not found:
            other = ", ".join(sorted({a.id for a in answers}))
            await self._refuse(f"No pending request has the id {other}. "
                               f"Request {request.id} is still waiting for an answer.")
            return None
        answer = found[0]
        problems = self._problems(answer, request)
        if problems:
            await self._reask(request, problems)
            return None
        return answer

    def _problems(self, answer: Answer, request: Question | Approval) -> list[Problem]:
        # The remote takes the role claim as given (O8, FR-012).
        found = check_answer(answer, request, now=self._clock(), limits=self.limits)
        return [p for p in found if p.code != "caller_on_approval"]

    def _size(self, part: Part) -> Problem | None:
        """``too_large`` for an R2C Part above the message limit (R2C-SAFETY-4)."""
        if not part.HasField("data") or URI not in part.metadata:
            return None
        return check_size(text=json_format.MessageToJson(part.data, indent=None), limits=self.limits)

    def _expiry(self, request: Question | Approval) -> Answer:
        """The outcome of a request past ``expires_at`` (R2C-ASK-4, research R8)."""
        counted = "deny" if isinstance(request, Approval) else "declined"
        kind = "Approval" if isinstance(request, Approval) else "Question"
        self._note = (f"{kind} {request.id} expired at {request.expires_at} and counted as {counted}; "
                      "this answer came too late.")
        return Answer(id=request.id, outcome="declined", answered_by=AnsweredBy(role="policy"),
                      note="The request expired.")

    async def _reask(self, request: Question | Approval, problems: list[Problem]) -> None:
        """The same request, the same id, with the problems as ``errors`` (R2C-ASK-6)."""
        data = to_json(request)
        data["errors"] = [p.as_error_item().model_dump(mode="json", exclude_none=True) for p in problems]
        again = parse(data)
        assert isinstance(again, (Question, Approval))
        await self.ask(again)

    async def _refuse(self, text: str) -> None:
        """A text-only input-required status; the request stays pending (R2C-ASK-5)."""
        await self._updater.requires_input(self._updater.new_agent_message([Part(text=text)]))

    # --- ending -----------------------------------------------------------------------------

    def _end(self) -> None:
        if self.memory is not None:
            self.memory.drop(self.task_id)
        self.pending = None

    async def complete(self) -> None:
        reply = "".join(self._gathered)
        text = _join(self._note, reply if reply and not self.active else "Done.")
        self._end()
        await self._updater.complete(self._message(text, self._usage))

    async def fail(self, reason: str) -> None:
        text = _join(self._note, "" if self.active else "".join(self._gathered), reason)
        self._end()
        await self._updater.failed(self._message(text, self._usage))

    async def cancelled(self) -> None:
        text = _join(self._note, "The run was cancelled.")
        self._end()
        await self._updater.cancel(self._message(text, self._usage))

    async def reject(self, text: str) -> None:
        self._end()
        await self._updater.reject(self._updater.new_agent_message([Part(text=text)]))
