"""The options of each door, and one door alone (spec 007, story 7; research R8 and R11).

Section 1 is the two option classes by themselves: they need no SDK. The later sections serve one
door alone, show that each option reaches its door, and check `middleware=` and the identity warning.

1. The option classes.
2. One door alone answers only its own paths and loads only its own SDK (SC-008).
3. Each option reaches the door it belongs to: the task store and the owner resolver, the host rules,
   the rest of the server's and the HTTP app's keywords, and the two paths.
4. `middleware=` wraps both doors; the identity warning (D5) fires exactly when a middleware is given and
   the MCP door has nothing that names a caller's owner; with the recipe one header is one owner on both.
"""

from __future__ import annotations

import dataclasses
import subprocess
import sys
import warnings
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx2
import pytest
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks import InMemoryTaskStore
from ext_r2c import A2AOptions, MCPOptions, Remote, RemoteError
from ext_r2c.core import RunContext, RunEvent, RunInput, thread_id
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.request_state import RequestStateSecurity
from mcp.server.transport_security import TransportSecuritySettings
from mcp_transport import StreamingASGITransport as MCPTransport
from starlette.middleware import Middleware

from a2a_harness import TIMEOUT, kinds, run, send
from fake_sources import CARD, CheckpointFake
from mcp_harness import BASE, auth, call
from remote_harness import CARD_PATH, KEYS, OWNER, a2a_options, identity, mcp_options, owner, quiet, serve_remote

CONTEXT = "ctx-1"
ASK = {"message": "Write the report", "context_id": CONTEXT}


def publish_page(slug: str) -> str:
    """Publish a page of the handbook."""
    return f"published {slug}"


class Recorder(CheckpointFake):
    """A checkpoint fake that records the thread of every run it starts: the owner is in the thread."""

    def __init__(self) -> None:
        super().__init__({})
        self.threads: list[str] = []

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        self.threads.append(ctx.thread_id)
        async for event in super().run(input, ctx):
            yield event


# --- 1. The option classes ------------------------------------------------------------------------


def test_the_defaults_are_the_data_models() -> None:
    a2a, mcp = A2AOptions(), MCPOptions()
    assert (a2a.task_store, a2a.owner_resolver, a2a.path) == (None, None, "/")
    assert (mcp.path, mcp.security, mcp.owner, mcp.transport_security) == ("/mcp", None, None, None)
    assert isinstance(mcp.server, Mapping) and dict(mcp.server) == {}
    assert isinstance(mcp.http, Mapping) and dict(mcp.http) == {}
    assert [f.name for f in dataclasses.fields(A2AOptions)] == ["task_store", "owner_resolver", "path"]
    assert [f.name for f in dataclasses.fields(MCPOptions)] == [
        "path", "security", "owner", "transport_security", "server", "http",
    ]


@pytest.mark.parametrize("options", [A2AOptions, MCPOptions])
def test_the_options_are_keyword_only_and_frozen(options: type) -> None:
    with pytest.raises(TypeError):
        options("/rpc")
    built = options(path="/rpc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        built.path = "/other"


def test_the_mappings_cannot_be_mutated_and_do_not_follow_the_owners_dict() -> None:
    given = {"instructions": "Ask before you publish."}
    options = MCPOptions(server=given, http={"json_response": True})
    with pytest.raises(TypeError):
        options.server["title"] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        MCPOptions().http["stateless_http"] = True  # type: ignore[index]
    given["title"] = "added later"
    assert dict(options.server) == {"instructions": "Ask before you publish."}
    assert dict(MCPOptions().server) == {} and dict(MCPOptions().http) == {}, "a default is never shared state"


@pytest.mark.parametrize("build", [
    lambda: A2AOptions(path=3),  # type: ignore[arg-type]
    lambda: MCPOptions(path=None),  # type: ignore[arg-type]
    lambda: MCPOptions(server=[("instructions", "x")]),  # type: ignore[arg-type]
    lambda: MCPOptions(http="json_response"),  # type: ignore[arg-type]
    lambda: MCPOptions(server={3: "x"}),  # type: ignore[dict-item]
    lambda: MCPOptions(owner="owner-1"),  # type: ignore[arg-type]
])
def test_a_field_of_the_wrong_type_is_a_type_error(build: object) -> None:
    with pytest.raises(TypeError):
        build()  # type: ignore[operator]


def test_the_options_need_no_sdk() -> None:
    """Both classes build with `a2a`, `mcp`, `starlette` and `yaml` blocked."""
    code = (
        "import sys\n"
        "for name in ('a2a', 'mcp', 'mcp_types', 'starlette', 'yaml'):\n"
        "    sys.modules[name] = None\n"
        "from ext_r2c import A2AOptions, MCPOptions\n"
        "print(A2AOptions(path='/rpc').path, MCPOptions(server={'instructions': 'x'}).path)\n"
    )
    out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "/rpc /mcp"


# --- 2. One door alone (SC-008) ---------------------------------------------------------------------


def test_the_a2a_door_alone_answers_the_card_and_the_json_rpc_and_nothing_of_mcp() -> None:
    async def go() -> None:
        remote = quiet(expose=["a2a"], agent=CheckpointFake({}))
        async with serve_remote(remote) as served:
            async with served.http() as http:
                assert (await http.get(CARD_PATH)).status_code == 200
                assert (await http.post("/mcp", content=b"{}")).status_code == 404
            async with served.a2a() as tc:
                events = await send(tc, "Write the report")
                assert kinds(events)[0] == "task" and kinds(events)[-1] == "input_required"

    run(go())


def test_the_mcp_door_alone_answers_the_mcp_endpoint_and_nothing_of_a2a() -> None:
    async def go() -> None:
        remote = quiet(expose=["mcp"], tools=[publish_page], card=CARD)
        async with serve_remote(remote) as served:
            async with served.http() as http:
                assert (await http.get(CARD_PATH)).status_code == 404
                assert (await http.post("/", content=b"{}")).status_code == 404
            async with served.mcp() as client:
                assert [tool.name for tool in (await client.list_tools()).tools] == ["publish_page"]
                done = await call(client, "publish_page", {"slug": "intro"})
                assert not done.is_error

    run(go())


_A2A_ALONE = (
    "import sys\n"
    "from a2a.server.agent_execution import AgentExecutor\n"
    "from a2a.server.tasks import InMemoryTaskStore\n"
    "from ext_r2c import A2AOptions, Remote\n"
    "from ext_r2c.core import CardInfo\n"
    "class Executor(AgentExecutor):\n"
    "    async def execute(self, context, event_queue): ...\n"
    "    async def cancel(self, context, event_queue): ...\n"
    "Remote(expose=['a2a'], agent=Executor(), card=CardInfo(name='n', description='d', version='1'),\n"
    "       url='https://remote.example.com', a2a=A2AOptions(task_store=InMemoryTaskStore())).app()\n"
    "other = ('mcp', 'mcp_types')\n"
)
_MCP_ALONE = (
    "import sys\n"
    "from ext_r2c import MCPOptions, Remote\n"
    "from ext_r2c.core import CardInfo\n"
    "def publish_page(slug: str) -> str:\n"
    "    'Publish a page of the handbook.'\n"
    "    return slug\n"
    "Remote(expose=['mcp'], tools=[publish_page], card=CardInfo(name='n', description='d', version='1')).app()\n"
    "other = ('a2a',)\n"
)
_LOADED = (
    "door = {'mcp': 'ext_r2c.mcp', 'a2a': 'ext_r2c.a2a'}[other[0]]\n"
    "print(sorted(name for name in sys.modules\n"
    "             if name.partition('.')[0] in other or name == door or name.startswith(door + '.')))\n"
    "print('ext_r2c.remote' in sys.modules)\n"
)


@pytest.mark.parametrize("code", [_A2A_ALONE, _MCP_ALONE], ids=["a2a alone", "mcp alone"])
def test_one_door_built_loads_nothing_of_the_other(code: str) -> None:
    """A whole build in a new process: no module of the other door or of its SDK is loaded, and no
    warning fires for the door that is not there."""
    out = subprocess.run([sys.executable, "-I", "-W", "error::UserWarning", "-c", code + _LOADED],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split("\n")[:2] == ["[]", "True"]


def test_the_control_both_doors_built_load_both() -> None:
    """The control of the test above: its way of looking does see a door that is loaded."""
    both = _A2A_ALONE.replace(
        "Remote(expose=['a2a'],",
        "def publish_page(slug: str) -> str:\n    'Publish a page of the handbook.'\n    return slug\n"
        "Remote(expose=['a2a', 'mcp'], tools=[publish_page],",
    )
    assert both != _A2A_ALONE
    out = subprocess.run([sys.executable, "-I", "-W", "ignore", "-c", both + _LOADED], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    loaded = out.stdout.split("\n")[0]
    assert "'ext_r2c.mcp'" in loaded and "'mcp'" in loaded


# --- 3. Each option reaches its door ------------------------------------------------------------------


class CountingStore(InMemoryTaskStore):
    """The SDK's in-memory store, counting what the door asks of it."""

    def __init__(self, **settings: Any) -> None:
        super().__init__(**settings)
        self.saved = 0

    async def save(self, task: Any, context: Any) -> None:
        self.saved += 1
        await super().save(task, context)


def test_the_task_store_and_the_owner_resolver_given_are_the_ones_the_a2a_door_uses() -> None:
    resolved: list[str] = []

    def by_team(context: Any) -> str:  # the owner's own rule for who owns a task
        team = f"team:{resolve_user_scope(context)}"
        resolved.append(team)
        return team

    async def go() -> None:
        store, source = CountingStore(owner_resolver=by_team), Recorder()
        remote = quiet(expose=["a2a"], agent=source, a2a=A2AOptions(task_store=store, owner_resolver=by_team))
        async with serve_remote(remote) as served, served.a2a() as tc:
            events = await send(tc, "Write the report", context_id=CONTEXT)
            assert kinds(events)[-1] == "input_required"
        assert store.saved > 0, "the task went into the store given"
        assert set(resolved) == {f"team:{OWNER}"}
        assert source.threads == [thread_id("a2a", f"team:{OWNER}", CONTEXT)], (
            "the thread is the resolver's owner: the door and the store share one key")

    run(go())


def test_without_an_owner_resolver_the_sdks_default_names_the_owner() -> None:
    async def go() -> None:
        source = Recorder()
        async with serve_remote(quiet(expose=["a2a"], agent=source)) as served, served.a2a() as tc:
            await send(tc, "Write the report", context_id=CONTEXT)
        assert source.threads == [thread_id("a2a", OWNER, CONTEXT)]

    run(go())


HOSTS = ("127.0.0.1:8000", "remote.example.com", "other.example.com")
REFUSED_HOST = 421


async def _statuses(remote: Remote) -> dict[str, int]:
    """What the MCP endpoint answers to the same request under each `Host`."""
    async with serve_remote(remote) as served, served.http(user=OWNER) as http:
        return {host: (await http.post("/mcp", content=b"{}", headers={"Host": host,
                                                                         "Content-Type": "application/json"})
                       ).status_code for host in HOSTS}


def test_the_host_rules_given_decide_which_host_the_mcp_door_answers() -> None:
    """Finding 8: the MCP app guards its default host until `transport_security` names the public one."""
    async def go() -> None:
        by_default = await _statuses(quiet(expose=["mcp"], tools=[publish_page], card=CARD))
        served_status = by_default["127.0.0.1:8000"]
        assert served_status not in (REFUSED_HOST, 404), "the control: the default host reaches the endpoint"
        assert by_default == {"127.0.0.1:8000": served_status, "remote.example.com": REFUSED_HOST,
                              "other.example.com": REFUSED_HOST}

        rules = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=["remote.example.com"])
        named = await _statuses(quiet(expose=["mcp"], tools=[publish_page], card=CARD,
                                      mcp=mcp_options(transport_security=rules)))
        assert named == {"127.0.0.1:8000": REFUSED_HOST, "remote.example.com": served_status,
                         "other.example.com": REFUSED_HOST}

    run(go())


def test_a_server_keyword_reaches_the_mcp_server() -> None:
    async def go() -> None:
        said = "Ask before you publish."
        for options, expected in ((mcp_options(), None), (mcp_options(server={"instructions": said}), said)):
            remote = quiet(expose=["mcp"], tools=[publish_page], card=CARD, mcp=options)
            async with serve_remote(remote) as served, served.mcp() as client:
                assert client.instructions == expected

    run(go())


async def _post_types(remote: Remote) -> set[str]:
    """The content types of the answers to an older client's requests, which the default streams."""
    seen: list[tuple[str, int, str | None]] = []

    async def record(response: httpx2.Response) -> None:
        seen.append((response.request.method, int(response.status_code), response.headers.get("content-type")))

    async with serve_remote(remote) as served:
        http = httpx2.AsyncClient(transport=MCPTransport(served.app), base_url=BASE, timeout=TIMEOUT,
                                  headers={"Authorization": f"Bearer {OWNER}"}, event_hooks={"response": [record]})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # the SDK says the older protocol is on its way out
            async with Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode="legacy",
                              cache=None) as client:
                done = await client.session.call_tool("publish_page", {"slug": "intro"})
                assert [block.text for block in done.content] == ["published intro"]
    return {str(kind).partition(";")[0] for method, status, kind in seen if method == "POST" and status == 200}


def test_an_http_keyword_reaches_the_mcp_app() -> None:
    async def go() -> None:
        streamed = await _post_types(quiet(expose=["mcp"], tools=[publish_page], card=CARD))
        assert streamed == {"text/event-stream"}, "the control: by default an older client's answers stream"
        as_json = await _post_types(quiet(expose=["mcp"], tools=[publish_page], card=CARD,
                                          mcp=mcp_options(http={"json_response": True})))
        assert as_json == {"application/json"}

    run(go())


def test_the_two_paths_move_their_endpoints() -> None:
    async def go() -> None:
        remote = quiet(agent=CheckpointFake({}), tools=[publish_page], a2a=a2a_options(path="/rpc"),
                       mcp=mcp_options(path="/tools"))
        async with serve_remote(remote, path="/rpc") as served:
            async with served.http(user=OWNER) as http:
                assert (await http.post("/", content=b"{}")).status_code == 404, "no JSON-RPC at the old path"
                assert (await http.post("/mcp", content=b"{}")).status_code == 404, "no MCP at the old path"
                assert (await http.get(CARD_PATH)).json()["supportedInterfaces"][0]["url"].endswith("/rpc")
            async with served.a2a() as tc:
                assert kinds(await send(tc, "Write the report"))[-1] == "input_required"
            http = httpx2.AsyncClient(transport=MCPTransport(served.app), base_url=BASE, timeout=TIMEOUT,
                                      headers={"Authorization": f"Bearer {OWNER}"})
            async with Client(streamable_http_client(f"{BASE}/tools", http_client=http), cache=None) as client:
                assert [tool.name for tool in (await client.list_tools()).tools] == ["publish_page"]

    run(go())


# --- 4. `middleware=` and the identity warning (D5) ---------------------------------------------------


class Counting:
    """A pure ASGI middleware: how many HTTP requests went to each path."""

    def __init__(self, app: Any, seen: dict[str, int]) -> None:
        self.app, self.seen = app, seen

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            self.seen[scope["path"]] = self.seen.get(scope["path"], 0) + 1
        await self.app(scope, receive, send)


def test_the_owners_middleware_sees_the_requests_of_both_doors() -> None:
    seen: dict[str, int] = {}

    async def go() -> None:
        remote = quiet(agent=CheckpointFake({}), tools=[publish_page],
                       middleware=[Middleware(Counting, seen=seen), *identity()])
        async with serve_remote(remote) as served, served.a2a() as tc, served.mcp() as client:
            seen.clear()  # an MCP client says hello as it enters: count only what each step below sends
            await send(tc, "Write the report")
            after_a2a = dict(seen)
            await client.list_tools()
        assert after_a2a.get("/", 0) > 0 and "/mcp" not in after_a2a, "an A2A request passed the middleware"
        assert seen["/"] == after_a2a["/"] and seen["/mcp"] > 0, "then an MCP request passed it too"

    run(go())


def _warned(**arguments: Any) -> tuple[Remote, list[warnings.WarningMessage]]:
    """A `Remote` and every warning its construction gave."""
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        remote = Remote(**arguments)
    return remote, list(seen)


def _settings(seen: list[warnings.WarningMessage]) -> list[str]:
    """The setting each warning names: the text before its first colon."""
    return [str(warning.message).partition(":")[0] for warning in seen]


def _keys() -> RequestStateSecurity:
    return RequestStateSecurity(keys=KEYS)


def _mcp(**changes: Any) -> dict[str, Any]:
    """An MCP door behind the owner's middleware, with fixed keys and nothing that names the owner."""
    arguments: dict[str, Any] = {"expose": ["mcp"], "tools": [publish_page], "card": CARD,
                                 "middleware": identity(), "mcp": MCPOptions(security=_keys())}
    arguments.update(changes)
    return arguments


class _Provider:
    """A stand-in for an OAuth authorization server provider: `Remote(...)` only looks for the key."""


def test_a_middleware_with_an_mcp_door_that_names_no_owner_warns_once() -> None:
    _, seen = _warned(**_mcp())
    (warning,) = seen
    text = str(warning.message)
    assert warning.category is UserWarning
    assert text.startswith("mcp.owner: ")
    assert "middleware" in text and "MCPOptions" in text and "owner=" in text
    assert warning.filename == __file__, "the warning points at the line that built the `Remote`"


def test_the_identity_warning_fires_at_construction_and_not_in_app() -> None:
    remote, seen = _warned(**_mcp())
    assert _settings(seen) == ["mcp.owner"]
    with warnings.catch_warnings(record=True) as later:
        warnings.simplefilter("always")
        remote.app()
    assert [w for w in later if issubclass(w.category, UserWarning)] == []


@pytest.mark.parametrize("changes", [
    {"mcp": MCPOptions(security=RequestStateSecurity(keys=KEYS), owner=owner)},
    {"mcp": MCPOptions(security=RequestStateSecurity(keys=KEYS), server=auth())},
    {"mcp": MCPOptions(security=RequestStateSecurity(keys=KEYS), server={"auth": auth()["auth"]})},
    {"mcp": MCPOptions(security=RequestStateSecurity(keys=KEYS),
                       server={"token_verifier": auth()["token_verifier"]})},
    {"mcp": MCPOptions(security=RequestStateSecurity(keys=KEYS), server={"auth_server_provider": _Provider()})},
    {"middleware": []},
    {"middleware": ()},
], ids=["owner", "the SDK's auth", "auth alone", "token_verifier alone", "auth_server_provider alone",
        "no middleware", "an empty middleware tuple"])
def test_an_mcp_door_that_can_name_the_owner_or_has_no_middleware_does_not_warn(changes: dict[str, Any]) -> None:
    _, seen = _warned(**_mcp(**changes))
    assert _settings(seen) == []


@pytest.mark.parametrize("server", [
    {"instructions": "Ask before you publish."},
    {"auth": None, "token_verifier": None, "auth_server_provider": None},
], ids=["a keyword that names no owner", "the three authentication settings, each left None"])
def test_a_server_that_names_no_owner_still_warns(server: dict[str, Any]) -> None:
    _, seen = _warned(**_mcp(mcp=MCPOptions(security=_keys(), server=server)))
    assert _settings(seen) == ["mcp.owner"]


def test_the_owner_callable_alone_is_enough_even_beside_authentication_left_none() -> None:
    _, seen = _warned(**_mcp(mcp=MCPOptions(security=_keys(), owner=owner, server={"auth": None})))
    assert _settings(seen) == []


def test_the_a2a_door_alone_never_gets_the_identity_warning() -> None:
    _, seen = _warned(expose=["a2a"], agent=CheckpointFake({}), url="https://remote.example.com",
                      a2a=a2a_options(), middleware=identity())
    assert _settings(seen) == []


def test_the_identity_warning_comes_after_the_in_memory_warnings() -> None:
    _, seen = _warned(expose=["a2a", "mcp"], agent=CheckpointFake({}), url="https://remote.example.com",
                      mcp_tool=True, middleware=identity())
    assert _settings(seen) == ["a2a.task_store", "mcp.security", "mcp.owner"]
    assert {warning.filename for warning in seen} == {__file__}


def test_a_refused_remote_gives_no_identity_warning() -> None:
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with pytest.raises(RemoteError):
            Remote(**_mcp(approve=["no_such_tool"]))
    assert seen == []


def test_with_the_recipe_one_bearer_header_is_one_owner_on_both_doors() -> None:
    async def go() -> None:
        source = Recorder()
        remote = quiet(agent=source, mcp_tool=True)  # the recipe: one middleware, and `owner` reads its user
        async with serve_remote(remote) as served, served.a2a() as tc, served.mcp() as client:
            await send(tc, "Write the report", context_id=CONTEXT)
            await call(client, "agent", ASK)
        assert source.threads == [thread_id("a2a", OWNER, CONTEXT), thread_id("mcp", OWNER, CONTEXT)]

    run(go())


def test_without_an_owner_source_the_mcp_door_does_not_know_the_middlewares_user() -> None:
    """What the warning is about: the same header is an owner on A2A and nobody in particular on MCP."""
    async def go() -> None:
        source = Recorder()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            remote = Remote(agent=source, mcp_tool=True, expose=["a2a", "mcp"], url="https://remote.example.com",
                            a2a=a2a_options(), mcp=MCPOptions(security=_keys()), middleware=identity())
        async with serve_remote(remote) as served, served.a2a() as tc, served.mcp() as client:
            await send(tc, "Write the report", context_id=CONTEXT)
            await call(client, "agent", ASK)
        a2a_thread, mcp_thread = source.threads
        assert a2a_thread == thread_id("a2a", OWNER, CONTEXT)
        assert mcp_thread != thread_id("mcp", OWNER, CONTEXT)

    run(go())
