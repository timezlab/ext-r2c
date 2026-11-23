"""What the outside review of `Remote` found, one test each (spec 007, T078; research R18).

A code reviewer and a security reviewer read the range with no memory of the work. Each test below
was written first and seen to fail on the code the reviewers read. What was left as it is, and why, is
in R18 and not tested here.

1. A keyword of `mcp_server` or of the HTTP app that `Remote` owns is a problem, not a late `TypeError`.
2. The `owner` callable and the SDK's principal: which is asked first.
3. A list of skill folders is read once, when the `Remote` is built.
4. `url`: what a card must never say.
5. `agent` is an object, never a class.
6. `RemoteError` crosses a process boundary.
7. `limits=` and `clock=` reach each door.
8. The edges of the two paths.
"""

from __future__ import annotations

import copy
import pickle
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from a2a.server.agent_execution import AgentExecutor
from ext_r2c import A2AOptions, MCPOptions, Remote, RemoteError
from ext_r2c.core import Limits, RunContext, RunEvent, RunInput, thread_id
from mcp.server.request_state import RequestStateSecurity

from a2a_harness import run
from fake_sources import CARD, CheckpointFake
from mcp_harness import auth, call, principal
from remote_harness import KEYS, URL, a2a_options, mcp_options, quiet, serve_remote

CONTEXT = "ctx-1"


def publish_page(slug: str) -> str:
    """Publish a page of the handbook."""
    return f"published {slug}"


def _mcp_only(**changes: Any) -> Remote:
    arguments: dict[str, Any] = {"expose": ["mcp"], "tools": [publish_page], "card": CARD, "middleware": ()}
    arguments["mcp"] = changes.pop("mcp", MCPOptions(security=RequestStateSecurity(keys=KEYS)))
    arguments.update(changes)
    return Remote(**arguments)


def _a2a_only(**changes: Any) -> Remote:
    arguments: dict[str, Any] = {"expose": ["a2a"], "agent": CheckpointFake({}), "url": URL, "a2a": a2a_options()}
    arguments.update(changes)
    return Remote(**arguments)


def _problems(build: Any) -> tuple[str, ...]:
    with pytest.raises(RemoteError) as caught:
        build()
    return caught.value.problems


# --- 1. Keywords `Remote` owns ----------------------------------------------------------------------


@pytest.mark.parametrize("key", ["security", "extension"])
def test_a_keyword_of_mcp_server_itself_is_a_problem_when_remote_is_built(key: str) -> None:
    """`mcp_server(name, extension, security=...)` takes these two itself, so `server={key: ...}` would be
    a `TypeError` (two values for one keyword) from `app()`, after the build had passed."""
    (problem,) = _problems(lambda: _mcp_only(mcp=MCPOptions(server={key: None})))
    assert problem.startswith("mcp.server: ") and key in problem, problem


def test_the_security_field_is_the_one_way_to_give_the_request_state_policy() -> None:
    (problem,) = _problems(lambda: _mcp_only(mcp=MCPOptions(server={"security": RequestStateSecurity(keys=KEYS)})))
    assert "MCPOptions" in problem and "security" in problem, problem
    _mcp_only(mcp=MCPOptions(security=RequestStateSecurity(keys=KEYS))).app()


def test_the_bind_address_is_not_an_http_keyword_because_it_turns_the_host_guard_off() -> None:
    """The SDK enables its host guard only for a loopback `host`; `http={"host": "0.0.0.0"}` would answer
    any `Host` with no word said. The server binds the address; `transport_security` names the hosts."""
    (problem,) = _problems(lambda: _mcp_only(mcp=MCPOptions(http={"host": "0.0.0.0"})))
    assert problem.startswith("mcp.http: ") and "host" in problem and "transport_security" in problem, problem


# --- 2. The owner callable and the SDK's principal ---------------------------------------------------


class Recorder(CheckpointFake):
    def __init__(self) -> None:
        super().__init__({})
        self.threads: list[str] = []

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        self.threads.append(ctx.thread_id)
        async for event in super().run(input, ctx):
            yield event


def _thread_of_an_authenticated_call(owner: Any) -> str:
    """The thread the source is given when `bob` (a verified principal) calls the agent tool."""
    async def go() -> str:
        source = Recorder()
        remote = Remote(expose=["mcp"], agent=source, mcp_tool=True, middleware=(),
                        mcp=MCPOptions(security=RequestStateSecurity(keys=KEYS), owner=owner, server=auth()))
        async with serve_remote(remote) as served, served.mcp(user="bob") as client:
            await call(client, "agent", {"message": "Write the report", "context_id": CONTEXT})
        (thread,) = source.threads
        return thread

    return run(go())


def test_an_owner_callable_that_names_an_owner_wins_over_the_verified_principal() -> None:
    """The callable is the owner's own rule, asked first (spec 004); the principal is what is used when it
    answers `None`. So a callable must read the verified user when authentication is on."""
    assert _thread_of_an_authenticated_call(lambda ctx: "callable-owner") == thread_id("mcp", "callable-owner", CONTEXT)


def test_an_owner_callable_that_answers_none_leaves_the_verified_principal() -> None:
    assert _thread_of_an_authenticated_call(lambda ctx: None) == thread_id("mcp", principal("bob"), CONTEXT)


def test_the_documentation_of_the_owner_field_says_the_order_the_code_has() -> None:
    doc = " ".join((MCPOptions.__doc__ or "").split())
    assert "asked first" in doc and "principal" in doc, doc


# --- 3. A list of skill folders is read once ---------------------------------------------------------


def _skill_folder(tmp_path: Path) -> Path:
    skill = tmp_path / "skills" / "hello"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: hello\ndescription: Says hello.\n---\nSay hello.\n", encoding="utf-8")
    return tmp_path / "skills"


def test_a_list_of_skill_folders_changed_after_the_build_is_not_read_again(tmp_path: Path) -> None:
    """The check passed for `[folder]`; `[folder, 42]` was never checked, so `app()` must not see it."""
    folders: list[Any] = [str(_skill_folder(tmp_path))]
    remote = _mcp_only(skills=folders)
    folders.append(42)
    folders[0] = str(tmp_path / "nowhere")
    remote.app()


def test_a_folder_given_as_a_path_or_a_string_is_still_taken(tmp_path: Path) -> None:
    folder = _skill_folder(tmp_path)
    for skills in (folder, str(folder), [folder], (str(folder),)):
        _mcp_only(skills=skills).app()


# --- 4. `url`: what the card must never say ----------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://remote.example.com\n", " https://remote.example.com", "https://remote.example.com/\t",
    "https://ok.example.com\n.evil.example.com", "https://remote.example.com\x00", "https://re mote.example.com",
    "https://remote.example.com:notaport", "https://remote.example.com:99999", "https://[::1",
], ids=["newline", "leading space", "tab", "newline inside", "nul", "space in host", "port is no number",
        "port too large", "unclosed bracket"])
def test_a_url_the_card_could_not_say_as_it_is_is_a_problem(url: str) -> None:
    (problem,) = _problems(lambda: _a2a_only(url=url))
    assert problem.startswith("url: "), problem
    assert url.strip() not in problem or url.strip() == "", "the problem does not say the address back"


@pytest.mark.parametrize("url", [
    "https://remote.example.com", "https://remote.example.com/", "https://remote.example.com:8443/agents/one",
    "http://127.0.0.1:8000", "http://localhost:8000/prefix",
])
def test_the_addresses_an_owner_means_still_build(url: str) -> None:
    _a2a_only(url=url).app()


# --- 5. `agent` is an object, never a class ----------------------------------------------------------


class _Executor(AgentExecutor):
    async def execute(self, context: Any, event_queue: Any) -> None: ...

    async def cancel(self, context: Any, event_queue: Any) -> None: ...


@pytest.mark.parametrize("agent", [_Executor, CheckpointFake], ids=["an executor class", "a source class"])
def test_a_class_given_as_the_agent_is_refused_when_remote_is_built(agent: Any) -> None:
    """A class has `execute` and `cancel` (or `run` and `resume`) as plain functions, so by shape it passes;
    it would fail at the first request, calling a method with no instance."""
    with pytest.raises(TypeError, match=r"^agent: "):
        _a2a_only(agent=agent, card=CARD)


def test_an_instance_of_each_is_still_taken() -> None:
    _a2a_only(agent=_Executor(), card=CARD).app()
    _a2a_only(agent=CheckpointFake({})).app()


# --- 6. `RemoteError` crosses a process boundary -----------------------------------------------------

_PROBLEMS = ["url: not given; pass the public address of the app", "agent: not given; pass an agent"]


@pytest.mark.parametrize("through", [
    lambda e: pickle.loads(pickle.dumps(e)), copy.copy, copy.deepcopy,
], ids=["pickle", "copy", "deepcopy"])
def test_a_remote_error_survives_pickle_and_copy_with_its_problems_in_order(through: Any) -> None:
    error = RemoteError(_PROBLEMS)
    other = through(error)
    assert type(other) is RemoteError
    assert other.problems == tuple(_PROBLEMS) and str(other) == str(error)


def test_the_refusal_of_a_bare_string_stands() -> None:
    with pytest.raises(TypeError):
        RemoteError("url: not given")


# --- 7. `limits=` and `clock=` reach each door -------------------------------------------------------


def _spy(monkeypatch: pytest.MonkeyPatch, module: str, name: str) -> list[dict[str, Any]]:
    import importlib

    owner = importlib.import_module(module)
    real = getattr(owner, name)
    seen: list[dict[str, Any]] = []

    class Spy(real):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.append(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(owner, name, Spy)
    return seen


def _noon() -> datetime:
    return datetime(2030, 1, 2, 12, 0, tzinfo=timezone.utc)


def test_the_limits_and_the_clock_given_reach_the_a2a_door(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy(monkeypatch, "ext_r2c.a2a", "SourceExecutor")
    limits = Limits(message_bytes=1234)
    quiet(expose=["a2a"], agent=CheckpointFake({}), limits=limits, clock=_noon).app()
    (kwargs,) = seen
    assert kwargs["limits"] is limits and kwargs["clock"] is _noon


def test_the_limits_and_the_clock_given_reach_the_mcp_door(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _spy(monkeypatch, "ext_r2c.mcp", "R2CExtension")
    limits = Limits(message_bytes=1234)
    quiet(expose=["mcp"], tools=[publish_page], card=CARD, limits=limits, clock=_noon).app()
    (kwargs,) = seen
    assert kwargs["limits"] is limits and kwargs["clock"] is _noon


def test_without_them_each_door_gets_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    a2a = _spy(monkeypatch, "ext_r2c.a2a", "SourceExecutor")
    mcp = _spy(monkeypatch, "ext_r2c.mcp", "R2CExtension")
    quiet(agent=CheckpointFake({}), mcp_tool=True).app()
    assert a2a[0]["limits"] == Limits() and a2a[0]["clock"] is None
    assert mcp[0]["limits"] == Limits() and mcp[0]["clock"] is None


# --- 8. The edges of the two paths -------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/.well-known", "/.well-known/", "/.well-known/rpc"])
def test_the_well_known_folder_itself_is_not_a_path_for_a_door(path: str) -> None:
    (problem,) = _problems(lambda: _a2a_only(a2a=A2AOptions(task_store=a2a_options().task_store, path=path)))
    assert problem.startswith("a2a.path: ") and "/.well-known" in problem, problem
    (problem,) = _problems(lambda: _mcp_only(mcp=MCPOptions(path=path, security=mcp_options().security)))
    assert problem.startswith("mcp.path: "), problem
