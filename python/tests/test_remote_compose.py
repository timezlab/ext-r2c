"""One app from two doors: its routes, its card and the owner's middleware (spec 007, story 1; SC-008;
contracts/app-composition.md).

The agent is the checkpoint fake of the shared suite, served on A2A and as the MCP tool `agent`. What
is real: `Remote`, both doors, the SDK clients and the in-process transports.
"""

from __future__ import annotations

from typing import Any

import mcp_types as types
import pytest
from a2a.client import A2ACardResolver
from ext_r2c import URI, MCPOptions, Remote, RemoteError
from mcp.server.request_state import RequestStateSecurity
from starlette.middleware import Middleware

from a2a_harness import kinds, run, send
from fake_sources import CARD, CheckpointFake
from mcp_harness import BASE, auth, call
from remote_harness import CARD_PATH, KEYS, a2a_options, identity, quiet, serve_remote

OAUTH_PATH = "/.well-known/oauth-protected-resource/mcp"
ARGS = {"message": "Write the report", "context_id": "ctx-1"}


def _remote(**arguments: Any) -> Remote:
    return quiet(agent=CheckpointFake({}), mcp_tool=True, **arguments)


def _with_the_sdks_auth() -> MCPOptions:
    """The MCP door authenticated the SDK's own way: no `owner` callable is needed."""
    return MCPOptions(security=RequestStateSecurity(keys=KEYS), server=auth())


# --- 1. The routes (SC-008) -------------------------------------------------------------------------


def test_one_app_answers_the_card_the_json_rpc_and_the_mcp_endpoint() -> None:
    async def go() -> None:
        async with serve_remote(_remote()) as served:
            async with served.http() as http:
                card = await http.get(CARD_PATH)
                assert card.status_code == 200 and card.json()["name"] == CARD.name
                assert (await http.get("/nope")).status_code == 404
            async with served.a2a() as tc, served.mcp() as client:
                events = await send(tc, "Write the report")
                assert kinds(events)[0] == "task" and kinds(events)[-1] == "input_required", "the JSON-RPC at `/`"
                assert [t.name for t in (await client.list_tools()).tools] == ["agent"]
                first = await call(client, "agent", ARGS)
                assert isinstance(first, types.InputRequiredResult), "the MCP endpoint at `/mcp`"

    run(go())


def test_the_mcp_endpoint_answers_at_its_exact_path_with_no_redirect() -> None:
    async def go() -> None:
        async with serve_remote(_remote()) as served, served.http() as http:
            posted = await http.post("/mcp", content=b"{}")
            assert not 300 <= posted.status_code < 400 and "location" not in posted.headers, posted.status_code
            assert posted.status_code != 404, "the MCP app answered, not a missing route"

    run(go())


# --- 2. The card and its address --------------------------------------------------------------------


@pytest.mark.parametrize(("url", "says"), [
    ("https://remote.example.com", "https://remote.example.com/"),
    ("https://remote.example.com/", "https://remote.example.com/"),
    ("https://remote.example.com/agents/one", "https://remote.example.com/agents/one/"),
    ("https://remote.example.com/agents/one/", "https://remote.example.com/agents/one/"),
])
def test_the_served_card_is_the_one_agent_card_builds_at_the_base_address(url: str, says: str) -> None:
    async def go() -> None:
        async with serve_remote(_remote(url=url), url=url) as served, served.http() as http:
            card = await A2ACardResolver(http, BASE).get_agent_card()
            assert card == served.card, "the card is `agent_card(info, address)`, nothing added"
            assert [i.url for i in card.supported_interfaces] == [says]
            assert [e.uri for e in card.capabilities.extensions] == [URI]

    run(go())


def test_another_a2a_path_moves_the_json_rpc_and_the_cards_address_but_not_the_card() -> None:
    async def go() -> None:
        remote = _remote(a2a=a2a_options(path="/rpc"))
        async with serve_remote(remote, path="/rpc") as served, served.http() as http:
            card = await A2ACardResolver(http, BASE).get_agent_card()
            assert card == served.card, "the card stays at the root"
            assert [i.url for i in card.supported_interfaces] == ["https://remote.example.com/rpc"]
            async with served.a2a() as tc:  # the client posts to the address its card says
                assert kinds(await send(tc, "Write the report"))[-1] == "input_required"
            assert (await http.post("/", json={})).status_code in (404, 405), "nothing answers JSON-RPC at `/` now"

    run(go())


# --- 3. Each door keeps its own middleware; the owner's wraps both ----------------------------------


def test_with_the_sdks_auth_its_metadata_route_is_mcps_and_the_card_stays_open() -> None:
    async def go() -> None:
        remote = _remote(mcp=_with_the_sdks_auth())
        async with serve_remote(remote) as served:
            async with served.http() as http:
                metadata = await http.get(OAUTH_PATH)
                assert metadata.status_code == 200 and "authorization_servers" in metadata.json(), (
                    "a route the SDK added is found by MCP's own router"
                )
                assert (await http.delete(OAUTH_PATH)).status_code == 405, (
                    "a wrong method on a path of MCP's is MCP's to refuse, not a missing route of A2A's"
                )
                assert (await http.post("/mcp", content=b"{}")).status_code == 401, "no bearer, no MCP"
                assert (await http.get(CARD_PATH)).status_code == 200, "the SDK's authentication wraps MCP only"
            async with served.mcp() as client:
                assert [t.name for t in (await client.list_tools()).tools] == ["agent"]

    run(go())


class _Provider:
    """A stand-in for an OAuth authorization server provider: the SDK only keeps it while it builds."""


def test_a_route_the_sdk_added_that_takes_the_a2a_path_is_a_build_error() -> None:
    """With an authorization server provider the SDK adds `/authorize` and `/token` to the MCP app.
    No list of paths knows that: `app()` asks the MCP router itself (research R10)."""
    settings = {**auth(), "auth_server_provider": _Provider()}
    del settings["token_verifier"]  # the SDK takes a provider or a verifier, not both
    colliding = _remote(a2a=a2a_options(path="/token"),
                        mcp=MCPOptions(security=RequestStateSecurity(keys=KEYS), server=settings))
    with pytest.raises(RemoteError) as caught:
        colliding.app()
    (problem,) = caught.value.problems
    assert problem.startswith("a2a.path: ") and "/token" not in str(caught.value), "the option is named, not its value"

    fixed = _remote(a2a=a2a_options(path="/rpc"),
                    mcp=MCPOptions(security=RequestStateSecurity(keys=KEYS), server=settings))
    fixed.app()  # only the path changed


class Recorder:
    """A pure ASGI middleware: one line per HTTP request, with the response as it looks from outside."""

    def __init__(self, app: Any, seen: list[tuple[str, str, int, bool]]) -> None:
        self.app, self.seen = app, seen

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def watching(message: Any) -> None:
            if message["type"] == "http.response.start":
                names = {name.decode("latin-1").lower() for name, _ in message.get("headers", [])}
                self.seen.append((scope["method"], scope["path"], message["status"], "a2a-extensions" in names))
            await send(message)

        await self.app(scope, receive, watching)


def test_the_owners_middleware_runs_once_per_request_outside_both_doors() -> None:
    seen: list[tuple[str, str, int, bool]] = []

    async def go() -> None:
        remote = _remote(middleware=[Middleware(Recorder, seen=seen), *identity()], mcp=_with_the_sdks_auth())
        async with serve_remote(remote) as served, served.http(headers={"A2A-Extensions": URI}) as http:
            await http.get(CARD_PATH)
            await http.post("/mcp", content=b"{}")
            await http.get("/nope")

    run(go())
    assert seen == [
        ("GET", CARD_PATH, 200, True),  # it sees the header A2A's own middleware added: it is outside it
        ("POST", "/mcp", 401, False),  # it sees the refusal of MCP's own authentication, and no A2A echo
        ("GET", "/nope", 404, True),
    ]
