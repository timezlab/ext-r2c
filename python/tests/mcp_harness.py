"""Test bed for the MCP door (spec 004): a served `MCPServer`, a real MCP SDK client on the
streaming in-process transport, and test authentication. Test helper only: not shipped.

- `auth()` gives the `MCPServer` keyword arguments that turn `Authorization: Bearer <name>` into
  an authenticated principal through the SDK's own bearer path (`StubVerifier`). A server built
  without them has anonymous callers only.
- `serve(server, record=...)` runs the server's session manager and yields a `Served`.
- `mcp_client(served, user=..., active=..., form=...)` is an MCP SDK `Client` for one owner:
  `active` advertises the R2C key, `form` declares elicitation through a callback that raises
  (the tests drive every round by hand, through `client.session`).
- `run(coro)` runs a test coroutine with a timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx2
import mcp_types as types
from ext_r2c import MCP_KEY
from mcp.client import Client, advertise
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp_transport import Record, StreamingASGITransport

T = TypeVar("T")
TIMEOUT = 10.0  # seconds
BASE = "http://127.0.0.1:8000"
URL = f"{BASE}/mcp"
ISSUER = "https://idp.example.com"


def run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(coro, TIMEOUT))


class StubVerifier:
    """`Bearer <name>` → an access token whose subject is `<name>`; any name is accepted."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        return AccessToken(token=token, client_id="test", scopes=[], subject=token, claims={"iss": ISSUER})


def auth() -> dict[str, Any]:
    """Keyword arguments for `MCPServer` (or `mcp_server`) that authenticate bearer tokens."""
    return {
        "auth": AuthSettings(issuer_url=ISSUER, resource_server_url=URL, validate_token_resource=False),
        "token_verifier": StubVerifier(),
    }


def principal(user: str) -> str:
    """The principal string `authenticated_principal` gives for a `StubVerifier` user."""
    from mcp.server.request_state import compact_json

    return compact_json(["test", ISSUER, user])


@dataclass
class Served:
    server: Any
    app: Any
    record: Record | None = None
    clients: list[Any] = field(default_factory=list)


@contextlib.asynccontextmanager
async def serve(server: Any, *, record: Record | None = None) -> AsyncIterator[Served]:
    app = server.streamable_http_app()
    async with server.session_manager.run():
        yield Served(server, app, record)


async def _refuse(context: Any, params: types.ElicitRequestParams) -> types.ElicitResult:
    raise AssertionError("the test drives every round itself; the elicitation callback must not run")


def http_client(served: Served, *, user: str | None = None, record: Record | None = None) -> httpx2.AsyncClient:
    headers = {"Authorization": f"Bearer {user}"} if user else {}
    transport = StreamingASGITransport(served.app, record=served.record if record is None else record)
    return httpx2.AsyncClient(transport=transport, base_url=BASE, headers=headers, timeout=TIMEOUT)


def mcp_client(served: Served, *, user: str | None = None, active: bool = True, form: bool = True,
               message_handler: Any = None, record: Record | None = None) -> Client:
    """An MCP SDK client for one owner, not yet entered (`async with mcp_client(...) as c`)."""
    transport = streamable_http_client(URL, http_client=http_client(served, user=user, record=record))
    return Client(
        transport,
        extensions=[advertise(MCP_KEY, {})] if active else None,
        elicitation_callback=_refuse if form else None,
        message_handler=message_handler,
        cache=None,
    )


def dump(result: Any) -> dict[str, Any]:
    """A result model as its wire JSON."""
    return result.model_dump(mode="json", by_alias=True, exclude_none=True)  # type: ignore[no-any-return]
