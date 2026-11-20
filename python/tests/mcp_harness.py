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


# --- Driving rounds -------------------------------------------------------------------------------


async def call(client: Client, name: str, arguments: dict[str, Any] | None = None, *, state: str | None = None,
               responses: dict[str, types.ElicitResult] | None = None, token: str | None = None) -> Any:
    """One `tools/call` round, raw: an `InputRequiredResult` or a `CallToolResult`."""
    return await client.session.call_tool(
        name, arguments or {}, meta={"progressToken": token} if token else None,
        input_responses=responses, request_state=state, allow_input_required=True,
    )


def accept(key: str, **content: Any) -> dict[str, types.ElicitResult]:
    return {key: types.ElicitResult(action="accept", content=content)}


def refuse(key: str, action: str = "decline") -> dict[str, types.ElicitResult]:
    return {key: types.ElicitResult(action=action)}  # type: ignore[arg-type]


def texts(result: Any) -> list[str]:
    return [b.text for b in result.content if b.type == "text"]


class Progress:
    """A `message_handler` that keeps every progress notification's params, as wire JSON."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        self.arrived = asyncio.Event()

    async def __call__(self, message: object) -> None:
        if isinstance(message, types.ProgressNotification):
            self.seen.append(dump(message.params))
            self.arrived.set()


# --- A scripted source ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Raise:
    """A step: the source raises `RuntimeError(reason)`."""

    reason: str


@dataclass(frozen=True)
class Hang:
    """A step: the source waits until it is cancelled, and notes whether `ctx.cancelled` was set."""


class Scripted:
    """A source that yields its steps in order, in either pause style. An `Ask` step pauses: a
    checkpoint source yields it and ends, keeping its place in `store` (a second instance on the
    same `store` is the same remote after a restart); a live source awaits `ctx.ask`. Every answer
    that reached it is in `answers`, and every run's input and thread in `inputs` and `threads`."""

    def __init__(self, pause: str, *steps: Any, store: dict[str, Any] | None = None,
                 card: Any = None) -> None:
        from fake_sources import CARD

        self.pause = pause
        self.card = card or CARD
        self.steps = steps
        self.store: dict[str, Any] = {} if store is None else store
        self.answers: list[Any] = []
        self.inputs: list[Any] = []
        self.threads: list[str] = []
        self.saw_cancelled: bool | None = None
        self.hanging = asyncio.Event()

    async def run(self, input: Any, ctx: Any) -> AsyncIterator[Any]:
        self.inputs.append(input)
        self.threads.append(ctx.thread_id)
        async for event in self._from(0, ctx):
            yield event

    async def resume(self, answer: Any, ctx: Any) -> AsyncIterator[Any]:
        self.answers.append(answer)
        self.threads.append(ctx.thread_id)
        async for event in self._from(self.store.pop(ctx.thread_id), ctx):
            yield event

    async def _from(self, start: int, ctx: Any) -> AsyncIterator[Any]:
        from ext_r2c.core import Ask

        for i in range(start, len(self.steps)):
            step = self.steps[i]
            if isinstance(step, Raise):
                raise RuntimeError(step.reason)
            if isinstance(step, Hang):
                self.hanging.set()
                try:
                    await asyncio.sleep(3600)
                finally:
                    self.saw_cancelled = ctx.cancelled.is_set()
            elif isinstance(step, Ask) and self.pause == "checkpoint":
                self.store[ctx.thread_id] = i + 1
                yield step
                return
            elif isinstance(step, Ask):
                self.answers.append(await ctx.ask(step.request))
            else:
                yield step


# --- Comparing wires ------------------------------------------------------------------------------


def normalise(record: Record) -> list[tuple[str, Any]]:
    """A recorded wire with what differs from run to run mapped to stable names: JSON-RPC ids,
    `requestState`, progress tokens; the SDK's own `_meta` keys dropped."""
    names: dict[str, dict[Any, str]] = {"id": {}, "state": {}, "token": {}}

    def name(kind: str, value: Any) -> str:
        found = names[kind]
        if value not in found:
            found[value] = f"<{kind}-{len(found) + 1}>"
        return found[value]

    def clean(node: Any, key: str | None = None) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "_meta" and isinstance(v, dict):
                    v = {mk: mv for mk, mv in v.items() if not mk.startswith("io.modelcontextprotocol/")}
                    if not v:
                        continue
                    out[k] = {mk: clean(mv) for mk, mv in v.items()}
                elif k == "requestState" and isinstance(v, str):
                    out[k] = name("state", v)
                elif k == "progressToken":
                    out[k] = name("token", v)
                else:
                    out[k] = clean(v, k)
            return out
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    out: list[tuple[str, Any]] = []
    for side, message in record:
        message = dict(message)
        if "id" in message:
            message["id"] = name("id", message["id"])
        out.append((side, clean(message)))
    return out
