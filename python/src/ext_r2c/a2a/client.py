"""The caller's side of R2C over A2A, on a2a-sdk's client (spec 003 story 5, contracts/a2a-api.md).

``R2CClient`` sends messages with R2C activated and turns what comes back into typed items, in
wire order (data-model.md "Items a client reads"). It checks an answer before sending it, never
sends an approval answer as ``caller``, reattaches to a task after a cut, and fetches artifact
files from its connection's own origin only.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeAlias
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, Client, ClientCallContext, ClientConfig, ClientFactory
from a2a.client.service_parameters import ServiceParametersFactory, with_a2a_extensions
from a2a.extensions.common import HTTP_EXTENSION_HEADER, get_requested_extensions
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
)
from google.protobuf import json_format

from .. import URI
from ..core import (
    Activity,
    Answer,
    Approval,
    ArtifactMeta,
    BytesContent,
    Content,
    Limits,
    Problem,
    Question,
    TextContent,
    UrlContent,
    Usage,
    check_answer,
)
from ._codec import _ints, answer_text, pending_request, r2c_part, read_artifact, read_part

__all__ = [
    "ActivityItem",
    "AnswerRejected",
    "ArtifactItem",
    "Item",
    "Link",
    "R2CClient",
    "ReplyItem",
    "RequestItem",
    "StatusItem",
    "TaskItem",
    "TooLarge",
    "UsageItem",
]

_ACTIVITY_TYPES = frozenset({"tool", "step", "reasoning"})  # v1; others are skipped (R2C-CORE-6)
_PAUSED = "input_required"
_TERMINAL = frozenset({"completed", "failed", "canceled", "rejected"})
_DEFAULT_PORTS = {"https": 443, "http": 80}


# --- Items --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TaskItem:
    """A ``Task``: the first event of a stream, a reattach snapshot, or ``get_task``."""

    task_id: str
    context_id: str
    state: str
    text: str


@dataclass(frozen=True, slots=True)
class StatusItem:
    """A status update: its state (``working``, ``input_required``, ``completed``, ...) and the
    joined text of its message. The R2C Parts of that message follow as their own items."""

    state: str
    text: str


@dataclass(frozen=True, slots=True)
class ActivityItem:
    activity: Activity


@dataclass(frozen=True, slots=True)
class RequestItem:
    """A question or an approval waiting for an answer; with ``errors`` when it is re-asked."""

    request: Question | Approval


@dataclass(frozen=True, slots=True)
class UsageItem:
    usage: Usage


@dataclass(frozen=True, slots=True)
class ReplyItem:
    """A piece of the reply: a chunk of the artifact marked ``response: true``."""

    text: str
    last: bool


@dataclass(frozen=True, slots=True)
class ArtifactItem:
    """Any other artifact update. ``meta`` is ``None`` without R2C; ``presentation`` is then the
    client's guess (R2C-ARTIFACT-7): ``file``, ``inline``, or ``link`` for a page that is only
    opened in a new tab. ``data`` holds the JSON of its ``data`` Parts."""

    artifact_id: str
    meta: ArtifactMeta | None
    parts: tuple[Content, ...]
    name: str | None = None
    append: bool = False
    last: bool = False
    presentation: str = "file"
    data: tuple[Any, ...] = ()


Item: TypeAlias = TaskItem | StatusItem | ActivityItem | RequestItem | UsageItem | ReplyItem | ArtifactItem


@dataclass(frozen=True, slots=True)
class Link:
    """A file ``url`` on another origin: given back, never requested (R2C-SAFETY-1)."""

    url: str
    media_type: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class TooLarge:
    """A file over ``Limits.file_bytes``; ``size`` when it is known (R2C-SAFETY-5)."""

    size: int | None


class AnswerRejected(ValueError):
    """The answer was not sent: ``problems`` says why (FR-022)."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("; ".join(p.message for p in problems))
        self.problems = problems


# --- Reading the wire ---------------------------------------------------------------------------


def _state(state: int) -> str:
    return TaskState.Name(state).removeprefix("TASK_STATE_").lower()  # type: ignore[arg-type]


def _text(parts: Iterable[Part]) -> str:
    return "".join(p.text for p in parts if p.HasField("text"))


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = httpx.URL(url)
    return parsed.scheme, parsed.host, parsed.port or _DEFAULT_PORTS.get(parsed.scheme)


def _rpc_url(card: AgentCard) -> str:
    interfaces = list(card.supported_interfaces)
    if not interfaces:
        raise ValueError("the agent card lists no interface")
    return next((i.url for i in interfaces if i.protocol_binding == "JSONRPC"), interfaces[0].url)


class R2CClient:
    """One connection to an A2A remote, with R2C asked for on every call."""

    def __init__(self, client: Client, http: httpx.AsyncClient, url: str, *, limits: Limits = Limits(),
                 clock: Callable[[], datetime] | None = None, owns_http: bool = False) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.client = client
        self.http = http
        self.url = url
        self.limits = limits
        self._owns_http = owns_http
        self.active = False
        self.task_id: str | None = None
        self.context_id: str | None = None
        self.pending: Question | Approval | None = None
        self.skipped = 0
        self._context = ClientCallContext(service_parameters=ServiceParametersFactory.create(
            [with_a2a_extensions([URI])]))
        hooks = http.event_hooks
        hooks.setdefault("response", []).append(self._record_echo)
        http.event_hooks = hooks

    @classmethod
    async def connect(cls, url: str, *, httpx_client: httpx.AsyncClient | None = None,
                      limits: Limits = Limits(), clock: Callable[[], datetime] | None = None) -> R2CClient:
        """Read the agent card at ``url`` and connect to its JSON-RPC interface. ``clock`` is
        the time an answer is checked against ``expires_at`` at (now, by default)."""
        http = httpx_client if httpx_client is not None else httpx.AsyncClient()
        card = await A2ACardResolver(http, url).get_agent_card()
        return cls._build(card, http, limits, clock, owns_http=httpx_client is None)

    @classmethod
    def from_card(cls, card: AgentCard, *, httpx_client: httpx.AsyncClient, limits: Limits = Limits(),
                  clock: Callable[[], datetime] | None = None) -> R2CClient:
        return cls._build(card, httpx_client, limits, clock, owns_http=False)

    @classmethod
    def _build(cls, card: AgentCard, http: httpx.AsyncClient, limits: Limits,
               clock: Callable[[], datetime] | None, *, owns_http: bool) -> R2CClient:
        client = ClientFactory(ClientConfig(httpx_client=http, streaming=True)).create(card)
        return cls(client, http, _rpc_url(card), limits=limits, clock=clock, owns_http=owns_http)

    async def _record_echo(self, response: httpx.Response) -> None:
        """``active``: whether the last JSON-RPC response echoed the R2C URI (R2C-ACT-2)."""
        if response.request.method != "POST" or _origin(str(response.request.url)) != _origin(self.url):
            return
        echoed = response.headers.get(HTTP_EXTENSION_HEADER, "")
        self.active = URI in get_requested_extensions([echoed])

    async def aclose(self) -> None:
        hooks = self.http.event_hooks
        hooks["response"] = [h for h in hooks.get("response", []) if h != self._record_echo]
        self.http.event_hooks = hooks
        await self.client.close()
        if self._owns_http:
            await self.http.aclose()

    # --- Calls ----------------------------------------------------------------------------------

    async def send(self, text: str, *, context_id: str | None = None,
                   task_id: str | None = None) -> AsyncIterator[Item]:
        """Send ``text``; a new task, or a follow-up in ``context_id`` (R2C-A2A-7)."""
        async for item in self._stream(Message(
            message_id=uuid4().hex, role=Role.ROLE_USER, parts=[Part(text=text)],
            context_id=context_id or "", task_id=task_id or "",
        )):
            yield item

    async def answer(self, answer: Answer) -> AsyncIterator[Item]:
        """Answer the pending request, after checking it; ``AnswerRejected`` sends nothing."""
        request = self.pending
        if request is None or self.task_id is None:
            raise AnswerRejected([Problem("wrong_id", None, "No request is waiting for an answer.")])
        problems = check_answer(answer, request, now=self.clock(), limits=self.limits)
        if problems:
            raise AnswerRejected(problems)
        message = Message(
            message_id=uuid4().hex, role=Role.ROLE_USER, task_id=self.task_id, context_id=self.context_id or "",
            parts=[Part(text=answer_text(answer, request)), r2c_part(answer)],
        )
        async for item in self._stream(message):
            yield item

    async def reattach(self, task_id: str | None = None) -> AsyncIterator[Item]:
        """Subscribe to a task again after a cut (R2C-A2A-6). The first item is the snapshot; the
        stream ends at input-required or a terminal state."""
        events = self.client.subscribe(SubscribeToTaskRequest(id=self._task(task_id)), context=self._context)
        async with contextlib.aclosing(events):
            async for event in events:
                for item in self._read(event):
                    yield item
                if self._paused_or_over(event):
                    return

    async def get_task(self, task_id: str | None = None) -> list[Item]:
        """The task as stored: its state, last status and artifacts (R2C-A2A-6). Reading another
        task than this conversation's leaves ``task_id``, ``context_id`` and ``pending`` alone."""
        task = await self.client.get_task(GetTaskRequest(id=self._task(task_id)), context=self._context)
        if task_id is None or task_id == self.task_id:
            return list(self._task_items(task))
        kept = (self.task_id, self.context_id, self.pending)
        try:
            return list(self._task_items(task))
        finally:
            self.task_id, self.context_id, self.pending = kept

    async def cancel(self, task_id: str | None = None) -> StatusItem:
        task = await self.client.cancel_task(CancelTaskRequest(id=self._task(task_id)), context=self._context)
        self.pending = None
        return StatusItem(_state(task.status.state), _text(task.status.message.parts))

    async def fetch(self, item: ArtifactItem) -> bytes | Link | TooLarge:
        """The file of an artifact. A ``url`` is fetched only on this connection's origin, with no
        redirect followed and no compression asked for; reading stops at ``Limits.file_bytes``.
        A page (a ``live`` artifact, or a ``link`` guessed for an html ``url``) is never fetched:
        it comes back as a ``Link`` for the user to open (R2C-ARTIFACT-7)."""
        content = next((c for c in item.parts if not isinstance(c, TextContent)), None)
        limit = self.limits.file_bytes
        if isinstance(content, BytesContent):
            return content.data if len(content.data) <= limit else TooLarge(len(content.data))
        if not isinstance(content, UrlContent):
            raise ValueError(f"artifact {item.artifact_id} has no file")
        if item.presentation in ("live", "link") or _origin(content.url) != _origin(self.url):
            return Link(content.url, content.media_type, content.name)
        async with self.http.stream("GET", content.url, follow_redirects=False,
                                    headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            size = int(declared) if declared and declared.isdigit() else None
            if size is not None and size > limit:
                return TooLarge(size)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > limit:
                    return TooLarge(size)
            return bytes(body)

    # --- Items ----------------------------------------------------------------------------------

    def _task(self, task_id: str | None) -> str:
        found = task_id or self.task_id
        if not found:
            raise ValueError("no task yet: give a task id")
        return found

    async def _stream(self, message: Message) -> AsyncIterator[Item]:
        events = self.client.send_message(SendMessageRequest(message=message), context=self._context)
        async with contextlib.aclosing(events):
            async for event in events:
                for item in self._read(event):
                    yield item

    @staticmethod
    def _paused_or_over(event: StreamResponse) -> bool:
        if event.HasField("task"):
            state = event.task.status.state
        elif event.HasField("status_update"):
            state = event.status_update.status.state
        else:
            return False
        name = _state(state)
        return name == _PAUSED or name in _TERMINAL

    def _read(self, event: StreamResponse) -> Iterator[Item]:
        if event.HasField("task"):
            yield from self._task_items(event.task)
        elif event.HasField("status_update"):
            self.task_id, self.context_id = event.status_update.task_id, event.status_update.context_id
            yield from self._status(event.status_update.status)
        elif event.HasField("artifact_update"):
            yield self._artifact(event.artifact_update)
        elif event.HasField("message"):  # a reply without a task
            yield ReplyItem(_text(event.message.parts), last=True)
            yield from self._objects(event.message.parts)

    def _task_items(self, task: Task) -> Iterator[Item]:
        self.task_id, self.context_id = task.id, task.context_id
        state = _state(task.status.state)
        yield TaskItem(task.id, task.context_id, state, _text(task.status.message.parts))
        before = self.pending
        self.pending = None
        yield from self._objects(task.status.message.parts)
        if state == _PAUSED and self.pending is None and self.active:
            self.pending = pending_request(task) or before  # asked earlier, then refused in text
        over = state in _TERMINAL
        for artifact in task.artifacts:
            yield self._artifact(TaskArtifactUpdateEvent(task_id=task.id, context_id=task.context_id,
                                                         artifact=artifact, last_chunk=over))

    def _status(self, status: TaskStatus) -> Iterator[Item]:
        state = _state(status.state)
        if state != _PAUSED:
            self.pending = None
        yield StatusItem(state, _text(status.message.parts))
        yield from self._objects(status.message.parts)

    def _objects(self, parts: Iterable[Part]) -> Iterator[Item]:
        """One item per R2C Part, in order; anything else marked R2C is skipped and counted."""
        for part in parts:
            obj = read_part(part)
            if obj is None:
                continue
            if not self.active:
                self.skipped += 1  # R2C was not echoed: text and standard artifacts only
            elif isinstance(obj, Activity) and obj.type in _ACTIVITY_TYPES:
                yield ActivityItem(obj)
            elif isinstance(obj, (Question, Approval)):
                self.pending = obj
                yield RequestItem(obj)
            elif isinstance(obj, Usage):
                yield UsageItem(obj)
            else:  # an unknown kind or activity type, a broken object, or a kind out of place
                self.skipped += 1

    def _artifact(self, update: TaskArtifactUpdateEvent) -> Item:
        meta, contents = read_artifact(update.artifact)
        if not self.active:
            meta = None
        if meta is not None and meta.response:
            return ReplyItem("".join(c.text for c in contents if isinstance(c, TextContent)), last=update.last_chunk)
        artifact = update.artifact
        data = tuple(_ints(json_format.MessageToDict(p.data)) for p in artifact.parts if p.HasField("data"))
        return ArtifactItem(artifact.artifact_id, meta, contents, artifact.name or None,
                            update.append, update.last_chunk,
                            meta.presentation if meta is not None else _guess(artifact.parts), data)


def _guess(parts: Iterable[Part]) -> str:
    """The presentation of an artifact without R2C metadata (R2C-ARTIFACT-7). ``live`` is never
    guessed."""
    for part in parts:
        which = part.WhichOneof("content")
        if which == "url" and part.media_type == "text/html":
            return "link"
        if which == "raw" or (which == "url" and part.filename):
            return "file"
    return "inline" if any(p.WhichOneof("content") in ("text", "data") for p in parts) else "link"
