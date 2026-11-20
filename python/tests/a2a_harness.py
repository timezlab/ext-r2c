"""Test bed for the A2A door (spec 003): a served app, a real a2a-sdk client on the streaming
in-process transport, and test authentication. Test helper only: not shipped in the wheel.

- `serve(executor, card)` runs an app and yields it; the request handler is closed on exit.
- `a2a_client(app, card, user=...)` gives an a2a-sdk client whose requests carry
  `Authorization: Bearer <user>`; `BearerAuth` turns that into the owner (research R11).
- `run(coro)` runs a test coroutine with a timeout, so a stream that never ends fails the test.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from a2a.client import Client, ClientConfig, ClientFactory
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a_transport import StreamingASGITransport
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
    """A card with no R2C declaration, for tests that run before `agent_card` exists."""
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
    handler: DefaultRequestHandlerV2
    card: AgentCard
    store: TaskStore


@contextlib.asynccontextmanager
async def serve(executor: AgentExecutor, card: AgentCard, *, store: TaskStore | None = None) -> AsyncIterator[Served]:
    store = store or InMemoryTaskStore()
    handler = DefaultRequestHandlerV2(agent_executor=executor, task_store=store, agent_card=card)
    app = Starlette(
        routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")],
        middleware=[Middleware(AuthenticationMiddleware, backend=BearerAuth())],
    )
    try:
        yield Served(app, handler, card, store)
    finally:
        await handler.aclose()


@dataclass
class TestClient:
    client: Client
    http: httpx.AsyncClient
    response_headers: list[httpx.Headers] = field(default_factory=list)

    async def aclose(self) -> None:
        await self.client.close()
        await self.http.aclose()


@contextlib.asynccontextmanager
async def a2a_client(served: Served, *, user: str | None = None) -> AsyncIterator[TestClient]:
    headers = {"Authorization": f"Bearer {user}"} if user else {}
    seen: list[httpx.Headers] = []

    async def record(response: httpx.Response) -> None:
        seen.append(response.headers)

    http = httpx.AsyncClient(transport=StreamingASGITransport(served.app), headers=headers,
                             event_hooks={"response": [record]}, timeout=TIMEOUT)
    client = ClientFactory(ClientConfig(httpx_client=http, streaming=True)).create(served.card)
    test_client = TestClient(client, http, seen)
    try:
        yield test_client
    finally:
        await test_client.aclose()
