"""Test bed for `Remote` (spec 007): one `Remote`, served as one app inside its own lifespan, with an
A2A client and an MCP client over the same app. Test helper only: not shipped in the wheel.

- `quiet(**arguments)` builds a `Remote` the way a careful owner would: an explicit task store, an
  explicit request-state policy, and one authentication middleware in `middleware=` that names the
  owner on both doors (the recipe of contracts/app-composition.md). So no warning fires where it is
  not the test's subject. `a2a_options` and `mcp_options` give the same defaults with a field changed.
- `serve_remote(remote)` calls `remote.app()` once, enters the app's lifespan and yields a `Served`:
  `.a2a(user=, r2c=)` and `.mcp(user=, active=)` are the doors' own SDK clients on the in-process
  transports, `.http(user=)` a plain HTTP client. One `Authorization: Bearer <name>` header names the
  owner on both doors.
- The A2A client needs a card: `Served.card` is built by the same `agent_card(info, address)` call
  `Remote` makes, so a test can compare it with the one the app serves.

`Remote` gives no handle on its doors (FR-026): a test that must see a door stop spies on the SDK
objects (`lifecycle` in `test_remote_lifecycle.py`).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from a2a.server.tasks import InMemoryTaskStore
from a2a_transport import StreamingASGITransport
from ext_r2c import A2AOptions, MCPOptions, Remote
from ext_r2c.a2a import agent_card
from mcp.server.request_state import RequestStateSecurity
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware

from a2a_harness import TIMEOUT, BearerAuth, a2a_client
from a2a_harness import Served as A2AServed
from fake_sources import CARD
from mcp_harness import BASE, mcp_client
from mcp_harness import Served as MCPServed

URL = "https://remote.example.com"
CARD_PATH = "/.well-known/agent-card.json"
KEYS = [b"k" * 32]
OWNER = "owner-1"


def owner(ctx: Any) -> str | None:
    """The owner of an MCP call: the user the outer authentication middleware put on the request."""
    user = getattr(getattr(ctx, "request", None), "user", None)
    return user.display_name if user is not None and user.is_authenticated else None


def identity() -> list[Middleware]:
    """The one authentication middleware both doors share."""
    return [Middleware(AuthenticationMiddleware, backend=BearerAuth())]


def a2a_options(**fields: Any) -> A2AOptions:
    fields.setdefault("task_store", InMemoryTaskStore())
    return A2AOptions(**fields)


def mcp_options(**fields: Any) -> MCPOptions:
    fields.setdefault("security", RequestStateSecurity(keys=KEYS))
    fields.setdefault("owner", owner)
    return MCPOptions(**fields)


def quiet(**arguments: Any) -> Remote:
    """A `Remote` with the given arguments and, for what they leave out: both doors, the test address,
    an explicit task store, an explicit request-state policy and the shared identity."""
    doors = arguments.setdefault("expose", ["a2a", "mcp"])
    if "a2a" in doors:
        arguments.setdefault("url", URL)
        arguments.setdefault("a2a", a2a_options())
    if "mcp" in doors:
        arguments.setdefault("mcp", mcp_options())
    arguments.setdefault("middleware", identity())
    return Remote(**arguments)


def address(url: str = URL, path: str = "/") -> str:
    """The JSON-RPC address a card says: the base address and the A2A path."""
    return url.rstrip("/") + path


@dataclass
class Served:
    app: Any
    card: Any  # the `AgentCard` an A2A client is built from

    def a2a(self, *, user: str | None = OWNER, r2c: bool = True) -> Any:
        return a2a_client(A2AServed(self.app, self.card), user=user, r2c=r2c)

    def mcp(self, *, user: str | None = OWNER, active: bool = True, **options: Any) -> Any:
        return mcp_client(MCPServed(None, self.app), user=user, active=active, **options)

    def http(self, *, user: str | None = None, headers: dict[str, str] | None = None) -> httpx.AsyncClient:
        sent = dict(headers or {})
        if user:
            sent["Authorization"] = f"Bearer {user}"
        return httpx.AsyncClient(transport=StreamingASGITransport(self.app), base_url=BASE, headers=sent,
                                 timeout=TIMEOUT)


@contextlib.asynccontextmanager
async def serve_remote(remote: Remote, *, info: Any = CARD, url: str = URL, path: str = "/") -> AsyncIterator[Served]:
    """`remote.app()` inside its own lifespan, which is all a server does to start both doors."""
    app = remote.app()
    async with app.router.lifespan_context(app):
        yield Served(app, agent_card(info, address(url, path)))
