"""The facts about the installed SDKs that `Remote` leans on (spec 007, phase 1; research R1 to R5, R8,
R9 and R14). No production code of `ext_r2c.remote` is used here: each test pins one fact, so a change
in `a2a-sdk`, `mcp` or `starlette` shows up as a failing test that names it.

`Dispatch` and `both` below are the test's own copies of the design (contracts/app-composition.md).
"""

from __future__ import annotations

import contextlib
import functools
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import mcp_types as types
import pytest
from a2a.server.agent_execution import AgentExecutor
from a2a_transport import StreamingASGITransport
from ext_r2c import MCP_KEY
from ext_r2c.a2a import R2CRequestHandler, SourceExecutor, a2a_app, agent_card
from ext_r2c.core import AgentSource, thread_id, tool_from_function
from ext_r2c.mcp import Approve, R2CExtension, SkillsExtension, SourceTool, mcp_server
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts import Prompt
from mcp.server.mcpserver.resources import TextResource
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.routing import Match, Mount

from a2a_harness import BearerAuth, a2a_client, kinds, run, send
from a2a_harness import Served as A2AServed
from fake_sources import CARD, CheckpointFake
from mcp_harness import BASE, auth, call, mcp_client
from mcp_harness import Served as MCPServed

URL = "https://remote.example.com/"
CARD_PATH = "/.well-known/agent-card.json"
OAUTH_PATH = "/.well-known/oauth-protected-resource/mcp"


class Dispatch:
    """A request the MCP app's own router matches goes to MCP; everything else goes to A2A."""

    def __init__(self, a2a: Any, mcp: Any) -> None:
        self.a2a, self.mcp = a2a, mcp

    def is_mcp(self, scope: Any) -> bool:
        return any(route.matches(scope)[0] != Match.NONE for route in self.mcp.router.routes)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await (self.mcp if scope["type"] == "http" and self.is_mcp(scope) else self.a2a)(scope, receive, send)


def _parent(a2a: Any, mcp: Any, *, middleware: list[Middleware] | None = None) -> Starlette:
    @contextlib.asynccontextmanager
    async def both(app: Starlette) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(a2a.router.lifespan_context(a2a))
            await stack.enter_async_context(mcp.router.lifespan_context(mcp))
            yield

    return Starlette(routes=[Mount("/", app=Dispatch(a2a, mcp))], middleware=middleware or [], lifespan=both)


def _doors(*, with_auth: bool = False, owner: Any = None, store: dict[str, Any] | None = None) -> tuple[Any, ...]:
    """The real A2A app and the real MCP app over one fake source: (a2a, mcp, card, server)."""
    source = CheckpointFake({} if store is None else store)
    card = agent_card(source.card, URL)
    a2a = a2a_app(SourceExecutor(source), card)
    server = mcp_server("spike", R2CExtension(tools=[SourceTool(source)], owner=owner), **(auth() if with_auth else {}))
    return a2a, server.streamable_http_app(), card, server


def _scope(path: str, method: str = "POST") -> dict[str, Any]:
    return {"type": "http", "path": path, "method": method, "headers": [], "root_path": ""}


def _http(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE)


@pytest.fixture
def lifecycle(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """What the two real objects did, in order: the MCP session manager's `run` and the A2A request
    handler's `aclose` (research R14: the tests spy on these, `Remote` offers no handle)."""
    seen: list[str] = []
    real_run, real_aclose = StreamableHTTPSessionManager.run, R2CRequestHandler.aclose

    @contextlib.asynccontextmanager
    async def spied_run(self: Any) -> AsyncIterator[None]:
        async with real_run(self):
            seen.append("mcp up")
            try:
                yield
            finally:
                seen.append("mcp down")

    async def spied_aclose(self: Any) -> None:
        seen.append("a2a closed")
        await real_aclose(self)

    monkeypatch.setattr(StreamableHTTPSessionManager, "run", spied_run)
    monkeypatch.setattr(R2CRequestHandler, "aclose", spied_aclose)
    return seen


# --- 1. One app from two door apps (R1) -----------------------------------------------------------


def test_the_mcp_router_decides_what_is_mcps() -> None:
    a2a, mcp, _, _ = _doors()
    dispatch = Dispatch(a2a, mcp)
    assert [(type(r).__name__, r.path) for r in mcp.router.routes] == [("Route", "/mcp")]
    assert {r.path for r in a2a.router.routes} == {CARD_PATH, "/"}
    for method in ("POST", "GET", "DELETE"):
        assert dispatch.is_mcp(_scope("/mcp", method)), f"{method} /mcp is MCP's: its own app answers the method"
    for path in ("/mcp/", "/", CARD_PATH, "/nope", OAUTH_PATH):
        assert not dispatch.is_mcp(_scope(path)), f"{path} is not MCP's"


def test_the_sdks_auth_adds_routes_the_router_knows_and_middleware_of_its_own() -> None:
    a2a, mcp, _, _ = _doors(with_auth=True)
    dispatch = Dispatch(a2a, mcp)
    assert dispatch.is_mcp(_scope(OAUTH_PATH, "GET")), "the protected-resource metadata is MCP's"
    assert not dispatch.is_mcp(_scope("/.well-known/oauth-protected-resource", "GET"))
    assert not dispatch.is_mcp(_scope(CARD_PATH, "GET")), "the card stays A2A's"
    # Each app carries middleware of its own: lifting the routes into one app would drop it.
    assert "AuthenticationMiddleware" in [m.cls.__name__ for m in mcp.user_middleware]
    assert [m.cls.__name__ for m in a2a.user_middleware] == ["EchoExtensions"]
    plain = _doors()[1]
    assert plain.user_middleware == []


def test_one_parent_answers_both_doors_and_mcp_without_a_redirect() -> None:
    async def go() -> None:
        a2a, mcp, _, _ = _doors()
        parent = _parent(a2a, mcp)
        async with parent.router.lifespan_context(parent), _http(parent) as http:
            card = await http.get(CARD_PATH)
            assert card.status_code == 200 and card.json()["name"] == CARD.name
            posted = await http.post("/mcp", content=b"{}")
            assert not 300 <= posted.status_code < 400 and "location" not in posted.headers, posted.status_code
            assert posted.status_code != 404, "the MCP app answered, not a missing route"
            assert (await http.post("/mcp/", content=b"{}")).status_code == 404, "`/mcp/` is not promised"
            assert (await http.get("/nope")).status_code == 404

    run(go())


def test_a_mount_is_not_the_design_it_redirects_and_never_starts_the_door(lifecycle: list[str]) -> None:
    async def go() -> None:
        _, mcp, _, _ = _doors()
        parent = Starlette(routes=[Mount("/mcp", app=mcp)])
        async with parent.router.lifespan_context(parent), _http(parent) as http:
            posted = await http.post("/mcp", content=b"{}")
            assert posted.status_code == 307 and posted.headers["location"].endswith("/mcp/")
            assert (await http.post("/mcp/", content=b"{}")).status_code == 404
        assert lifecycle == [], "a mounted sub-app's lifespan is never run"

    run(go())


# --- 2. Start, stop and failure (R2) --------------------------------------------------------------


def test_a_stack_of_the_two_lifespans_starts_and_stops_both_in_order(lifecycle: list[str]) -> None:
    async def go() -> None:
        a2a, mcp, _, _ = _doors()
        parent = _parent(a2a, mcp)
        async with parent.router.lifespan_context(parent):
            assert lifecycle == ["mcp up"]
        assert lifecycle == ["mcp up", "mcp down", "a2a closed"], "MCP stops first, then A2A"

    run(go())


def test_the_session_manager_runs_once_and_the_handler_closes_twice() -> None:
    async def go() -> None:
        a2a, _, _, server = _doors()
        async with server.session_manager.run():
            pass
        with pytest.raises(RuntimeError, match="once per instance"):
            async with server.session_manager.run():
                pass
        await a2a.state.request_handler.aclose()
        await a2a.state.request_handler.aclose()

    run(go())


# --- 3. Identity under one outer middleware (R3) ---------------------------------------------------


def test_one_outer_authentication_middleware_names_the_owner_on_both_doors() -> None:
    seen: list[str | None] = []

    def owner(ctx: Any) -> str | None:
        user = getattr(getattr(ctx, "request", None), "user", None)
        name = user.display_name if user is not None and user.is_authenticated else None
        seen.append(name)
        return name

    async def go() -> None:
        store: dict[str, Any] = {}
        a2a, mcp, card, _ = _doors(owner=owner, store=store)
        parent = _parent(a2a, mcp, middleware=[Middleware(AuthenticationMiddleware, backend=BearerAuth())])
        async with parent.router.lifespan_context(parent):
            async with a2a_client(A2AServed(parent, card), user="owner-1") as tc:
                events = await send(tc, "Write the report", context_id="ctx-1")
                assert kinds(events)[-1] == "input_required"
            assert thread_id("a2a", "owner-1", "ctx-1") in store, "A2A's default resolver read the middleware's user"
            async with mcp_client(MCPServed(None, parent), user="owner-1") as client:
                first = await call(client, "agent", {"message": "Write the report", "context_id": "ctx-1"})
                assert isinstance(first, types.InputRequiredResult)
            assert seen and set(seen) == {"owner-1"}, "the MCP extension's owner callable read the same user"
            assert thread_id("mcp", "owner-1", "ctx-1") in store
            assert len(store) == 2, "one thread per door for the same owner and context"

    run(go())


# --- 4. Shapes: the agent and the tools (R4, R5) ----------------------------------------------------


class _Executor(AgentExecutor):
    async def execute(self, context: Any, event_queue: Any) -> None: ...

    async def cancel(self, context: Any, event_queue: Any) -> None: ...


class _Invokable:
    """A stand-in for a framework's tool object: it has `invoke` and is not a function."""

    name = "publish_page"

    def invoke(self, arguments: dict[str, Any]) -> str:
        return "published"


class _CallableInstance:
    def __call__(self, page: str) -> str:
        return page


def publish_page(page: str) -> str:
    """Publish a page."""
    return page


def test_agent_source_is_not_runtime_checkable_and_an_executor_has_its_own_shape() -> None:
    with pytest.raises(TypeError):
        isinstance(object(), AgentSource)
    executor = _Executor()
    assert callable(executor.execute) and callable(executor.cancel)
    assert not any(hasattr(executor, name) for name in ("card", "pause", "run", "resume"))
    source = CheckpointFake({})
    assert all(hasattr(source, name) for name in ("card", "pause", "run", "resume"))
    assert not hasattr(source, "execute")


def test_a_routine_is_a_function_or_a_method_and_nothing_else() -> None:
    from langchain_core.tools import tool as langchain_tool

    assert inspect.isroutine(publish_page) and inspect.isroutine(_Invokable().invoke) and inspect.isroutine(len)
    for other in (functools.partial(publish_page, "home"), _CallableInstance(), _Invokable(),
                  langchain_tool(publish_page)):
        assert not inspect.isroutine(other), type(other).__name__
    assert not callable(langchain_tool(publish_page)), "a LangChain tool is not even callable"


def test_the_core_gives_no_help_for_an_object_that_is_not_a_function() -> None:
    """The reason `Remote` classifies a tool before it converts one."""
    with pytest.raises(AttributeError):
        tool_from_function(_Invokable())  # type: ignore[arg-type]
    assert tool_from_function(publish_page).name == "publish_page"


# --- 5. What the MCP side is built from (R8, R9) ----------------------------------------------------

SERVER_KEYWORDS = {
    "name", "title", "description", "instructions", "website_url", "icons", "version", "auth_server_provider",
    "token_verifier", "tools", "resources", "extensions", "debug", "log_level", "warn_on_duplicate_resources",
    "warn_on_duplicate_tools", "warn_on_duplicate_prompts", "dependencies", "lifespan", "auth", "resource_security",
    "request_state_security", "cache_hints", "subscriptions", "middleware",
}
HTTP_KEYWORDS = {
    "streamable_http_path", "json_response", "stateless_http", "event_store", "retry_interval",
    "max_request_body_size", "session_idle_timeout", "max_sessions", "transport_security", "host",
}


def _keywords(function: Any) -> set[str]:
    return {name for name in inspect.signature(function).parameters if name != "self"}


def test_the_keywords_of_the_mcp_server_and_its_http_app() -> None:
    assert _keywords(MCPServer.__init__) == SERVER_KEYWORDS
    assert _keywords(MCPServer.streamable_http_app) == HTTP_KEYWORDS
    assert "prompts" not in SERVER_KEYWORDS, "prompts have no keyword: `add_prompt` is the one way"


def _skill_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "skills" / "greet"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: greet\ndescription: Say hello.\n---\nSay hello.\n", encoding="utf-8")
    return tmp_path / "skills"


def a_prompt() -> str:
    """A prompt for tests."""
    return "Say hello"


def test_a_server_with_skills_a_resource_and_a_prompt_but_no_tools_serves(tmp_path: Path) -> None:
    async def go() -> None:
        server = mcp_server("spike", R2CExtension(tools=()), extensions=[SkillsExtension(_skill_folder(tmp_path))],
                            version="1.2.3", description="A remote for tests")
        server.add_resource(TextResource(uri="file:///note.txt", name="note", text="A note."))
        server.add_prompt(Prompt.from_function(a_prompt))
        app = server.streamable_http_app()
        async with app.router.lifespan_context(app), mcp_client(MCPServed(None, app)) as client:
            assert (await client.list_tools()).tools == []
            uris = [str(r.uri) for r in (await client.list_resources()).resources]
            assert "skill://greet/SKILL.md" in uris and "file:///note.txt" in uris, uris
            assert [p.name for p in (await client.list_prompts()).prompts] == ["a_prompt"]
        declared = server._lowlevel_server.extensions  # what `server/discover` declares
        assert declared[MCP_KEY] == {"revision": 1}, "R2C is declared with no tools at all"
        assert list(declared) == [MCP_KEY, "io.modelcontextprotocol/skills"]

    run(go())


def test_approve_does_not_check_who_answers() -> None:
    """The gap `Remote` closes with a build problem (research R7, row 16)."""
    assert Approve(answer_by="caller").answer_by == "caller"  # type: ignore[arg-type]


# --- 6. The test bed: one app, one lifespan, both clients (R14) -------------------------------------


def test_one_app_serves_an_a2a_client_and_an_mcp_client_at_once(lifecycle: list[str]) -> None:
    async def go() -> None:
        a2a, mcp, card, _ = _doors()
        parent = _parent(a2a, mcp, middleware=[Middleware(AuthenticationMiddleware, backend=BearerAuth())])
        async with _http(parent) as http:
            assert (await http.get(CARD_PATH)).status_code == 200
        assert lifecycle == [], "the in-process transport does not run the app's lifespan: the harness must"
        async with parent.router.lifespan_context(parent):
            async with a2a_client(A2AServed(parent, card), user="owner-1") as tc, \
                    mcp_client(MCPServed(None, parent), user="owner-1") as client:
                events = await send(tc, "Write the report")
                assert kinds(events)[-1] == "input_required"
                assert [t.name for t in (await client.list_tools()).tools] == ["agent"]
                first = await call(client, "agent", {"message": "Write the report"})
                assert isinstance(first, types.InputRequiredResult), "the MCP client needs nothing but the app"

    run(go())
