"""Test bed for the A2A door (spec 003): a served app, a real a2a-sdk client on the streaming
in-process transport, and test authentication. Test helper only: not shipped in the wheel.

- `serve(executor, card)` builds the app with `a2a_app` and yields it; the request handler is
  closed on exit.
- `a2a_client(served, user=..., r2c=...)` gives an a2a-sdk client whose requests carry
  `Authorization: Bearer <user>` and, with `r2c`, the `A2A-Extensions` header. `BearerAuth`
  turns the bearer into the owner (research R11).
- `run(coro)` runs a test coroutine with a timeout, so a stream that never ends fails the test.
- `send`, `answer` and `wire` drive a task and give back what came over the wire.
- `WireExecutor(*events)` is a remote whose wire the test chooses (`example_events` reads it
  from an example file, `status` builds one status update).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Coroutine, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

import httpx
from a2a.client import Client, ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskStore
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    TaskArtifactUpdateEvent,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a_transport import StreamingASGITransport
from ext_r2c import URI
from ext_r2c.a2a import a2a_app
from ext_r2c.a2a._codec import answer_text, r2c_part
from ext_r2c.core import Answer, Approval, Question
from google.protobuf import json_format
from starlette.applications import Starlette
from starlette.authentication import AuthCredentials, AuthenticationBackend, SimpleUser
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection

T = TypeVar("T")
TIMEOUT = 10.0  # seconds
URL = "https://remote.example.com/"


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(coro, TIMEOUT))


class BearerAuth(AuthenticationBackend):
    """`Authorization: Bearer <name>` → a user named `<name>`; no header → anonymous."""

    async def authenticate(self, conn: HTTPConnection) -> tuple[AuthCredentials, SimpleUser] | None:
        value = conn.headers.get("authorization", "")
        if not value.startswith("Bearer "):
            return None
        return AuthCredentials(["authenticated"]), SimpleUser(value[len("Bearer "):])


def plain_card(url: str = URL) -> AgentCard:
    """A card with no R2C declaration, for an executor that is not about R2C."""
    return AgentCard(
        name="test-remote", description="A remote for tests", version="0.0.1",
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        skills=[AgentSkill(id="echo", name="Echo", description="Answers for tests", tags=["test"])],
    )


@dataclass
class Served:
    app: Starlette
    card: AgentCard


@contextlib.asynccontextmanager
async def serve(executor: AgentExecutor, card: AgentCard, *, store: TaskStore | None = None,
                rpc_url: str = "/") -> AsyncIterator[Served]:
    app = a2a_app(executor, card, task_store=store, rpc_url=rpc_url,
                  middleware=[Middleware(AuthenticationMiddleware, backend=BearerAuth())])
    try:
        yield Served(app, card)
    finally:
        await app.state.request_handler.aclose()


@dataclass
class Caller:
    client: Client
    http: httpx.AsyncClient
    response_headers: list[httpx.Headers] = field(default_factory=list)

    def echoed(self) -> list[str | None]:
        """The `A2A-Extensions` header of each response so far (`None` when absent)."""
        return [h.get("a2a-extensions") for h in self.response_headers]

    async def aclose(self) -> None:
        await self.client.close()
        await self.http.aclose()


@contextlib.asynccontextmanager
async def a2a_client(served: Served, *, user: str | None = None, r2c: bool = True) -> AsyncIterator[Caller]:
    headers = {"Authorization": f"Bearer {user}"} if user else {}
    if r2c:
        headers["A2A-Extensions"] = URI
    seen: list[httpx.Headers] = []

    async def record(response: httpx.Response) -> None:
        seen.append(response.headers)

    http = httpx.AsyncClient(transport=StreamingASGITransport(served.app), headers=headers,
                             event_hooks={"response": [record]}, timeout=TIMEOUT)
    client = ClientFactory(ClientConfig(httpx_client=http, streaming=True)).create(served.card)
    caller = Caller(client, http, seen)
    try:
        yield caller
    finally:
        await caller.aclose()


# --- Driving a task -------------------------------------------------------------------------------


def message(*parts: Part, task_id: str = "", context_id: str = "") -> SendMessageRequest:
    return SendMessageRequest(message=Message(
        message_id=f"m-{uuid4().hex[:8]}", role=Role.ROLE_USER, parts=list(parts),
        task_id=task_id, context_id=context_id,
    ))


async def stream(tc: Caller, request: SendMessageRequest) -> list[StreamResponse]:
    return [event async for event in tc.client.send_message(request)]


async def send(tc: Caller, text: str, **ids: str) -> list[StreamResponse]:
    return await stream(tc, message(Part(text=text), **ids))


def ids(events: Iterable[StreamResponse]) -> dict[str, str]:
    """`task_id` and `context_id` of the task in a stream."""
    for event in events:
        if event.HasField("task"):
            return {"task_id": event.task.id, "context_id": event.task.context_id}
        for name in ("status_update", "artifact_update"):
            if event.HasField(name):
                inner = getattr(event, name)
                return {"task_id": inner.task_id, "context_id": inner.context_id}
    raise AssertionError("no task in the stream")


async def answer(tc: Caller, events: list[StreamResponse], reply: Answer,
                 request: Question | Approval) -> list[StreamResponse]:
    """Answer the request of a paused task the way an R2C client does (R2C-A2A-2)."""
    return await stream(tc, message(Part(text=answer_text(reply, request)), r2c_part(reply), **ids(events)))


def kinds(events: Iterable[StreamResponse]) -> list[str]:
    """One word per event: `task`, a status state (`working`, `input_required`, ...) or
    `artifact:<id>`."""
    out = []
    for event in events:
        if event.HasField("task"):
            out.append("task")
        elif event.HasField("status_update"):
            name = event.status_update.status.state
            out.append(_STATE_NAMES[name])
        elif event.HasField("artifact_update"):
            out.append(f"artifact:{event.artifact_update.artifact.artifact_id}")
        else:
            out.append(event.WhichOneof("payload") or "?")
    return out


def wire(events: Iterable[StreamResponse]) -> list[dict[str, Any]]:
    """The events as JSON, without the ids and timestamps that differ from run to run."""
    drop = {"taskId", "contextId", "messageId", "timestamp", "id"}

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: clean(v) for k, v in node.items() if k not in drop}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return [clean(json_format.MessageToDict(e)) for e in events]


class WireExecutor(AgentExecutor):
    """Sends the given status and artifact updates as they are, after the `Task`, with this
    task's ids: a remote whose wire a test chooses, for the client's tests."""

    def __init__(self, *events: TaskStatusUpdateEvent | TaskArtifactUpdateEvent) -> None:
        self.events = events

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task is None and context.message is not None:
            await event_queue.enqueue_event(new_task_from_user_message(context.message))
        for event in self.events:
            copy = type(event)()
            copy.CopyFrom(event)
            copy.task_id, copy.context_id = context.task_id or "", context.context_id or ""
            await event_queue.enqueue_event(copy)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def example_events(path: Path) -> list[TaskStatusUpdateEvent | TaskArtifactUpdateEvent]:
    """The status and artifact updates among an example's remote steps."""
    out: list[TaskStatusUpdateEvent | TaskArtifactUpdateEvent] = []
    for step in json.loads(path.read_text("utf-8"))["steps"]:
        if step["from"] != "remote" or step["type"] != "StreamResponse":
            continue
        event = json_format.ParseDict(step["body"], StreamResponse())
        if event.HasField("status_update"):
            out.append(event.status_update)
        elif event.HasField("artifact_update"):
            out.append(event.artifact_update)
    return out


def status(state: int, text: str = "") -> TaskStatusUpdateEvent:
    """A status update with a text Part, for a `WireExecutor`."""
    parts = [Part(text=text)] if text else []
    message = Message(message_id=f"m-{uuid4().hex[:8]}", role=Role.ROLE_AGENT, parts=parts)
    return TaskStatusUpdateEvent(status=TaskStatus(state=state, message=message))  # type: ignore[arg-type]


def _state_names() -> dict[int, str]:
    from a2a.types.a2a_pb2 import TaskState

    return {v: k.removeprefix("TASK_STATE_").lower() for k, v in TaskState.items()}


_STATE_NAMES = _state_names()
