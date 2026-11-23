"""`Remote` serving a remote that is already an a2a-sdk executor (spec 007, US6; SC-002).

The executor of `remote_executor.py` was written with the a2a-sdk alone, in the shape of the official
Currency sample: it asks in plain text with an `input-required` status and has never heard of R2C.

1. The executor is what it says: it imports nothing of the R2C SDK.
2. `Remote` serves it on the A2A door as it is: the card declares R2C and never requires it, a caller that
   activated R2C gets the question in words and continues in words, and every caller gets, event for
   event, what the a2a-sdk alone serves for the same executor.
3. `Remote` serves the object given and sets nothing on it.
4. An executor is served by the A2A door only: the build-time problems, and an executor on A2A beside
   tools on MCP.
"""

from __future__ import annotations

import ast
import contextlib
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import AgentCard, StreamResponse
from ext_r2c import URI, RemoteError
from ext_r2c.a2a import ArtifactItem, R2CClient, StatusItem, TaskItem
from ext_r2c.core import TextContent
from google.protobuf import json_format
from starlette.applications import Starlette

import remote_executor
from a2a_harness import Served as A2AServed
from a2a_harness import a2a_client, ids, kinds, plain_card, run, send, wire
from fake_sources import CARD
from mcp_harness import call, texts
from remote_executor import LOOKING, RESULT, WHICH_UNIT, ConverterExecutor
from remote_harness import CARD_PATH, OWNER, URL, Served, quiet, serve_remote

ASKED = "Convert 3 km"
CM = "3 km is 300000 cm."
AT_ONCE = "Convert 3 km to m"
M = "3 km is 3000 m."


def publish_page(slug: str) -> str:
    """Publish a page of the handbook."""
    return f"published {slug}"


def _a2a_only(executor: ConverterExecutor, **arguments: Any) -> Any:
    return quiet(expose=["a2a"], agent=executor, card=CARD, **arguments)


def _problems(**arguments: Any) -> list[str]:
    """The problems `Remote` finds, as it words them."""
    with pytest.raises(RemoteError) as caught:
        quiet(**arguments)
    return list(caught.value.problems)


def _refused(**arguments: Any) -> list[str]:
    """The problems `Remote` finds, each as the argument it names."""
    return [problem.partition(":")[0] for problem in _problems(**arguments)]


# --- 1. The executor has never heard of R2C -----------------------------------------------------------


def test_the_executor_imports_the_a2a_sdk_and_the_standard_library_only() -> None:
    tree = ast.parse(Path(remote_executor.__file__).read_text("utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert {name.partition(".")[0] for name in imported} == {"__future__", "a2a", "collections", "re", "typing"}


def test_importing_the_executor_loads_no_module_of_the_r2c_sdk() -> None:
    code = ("import sys\n"
            f"sys.path.insert(0, {str(Path(remote_executor.__file__).parent)!r})\n"
            "import remote_executor\n"
            "print(sorted(name for name in sys.modules if name.partition('.')[0] == 'ext_r2c'))\n")
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "[]"


# --- 2. Served as it is on the A2A door (SC-002) -------------------------------------------------------


def test_the_card_declares_r2c_and_never_requires_it() -> None:
    async def go() -> None:
        async with serve_remote(_a2a_only(ConverterExecutor())) as served, served.http() as http:
            body = (await http.get(URL + CARD_PATH)).json()
        (declared,) = body["capabilities"]["extensions"]
        assert declared["uri"] == URI
        assert declared.get("required", False) is False
        (extension,) = json_format.ParseDict(body, AgentCard()).capabilities.extensions
        assert extension.uri == URI and extension.required is False

    run(go())


@contextlib.asynccontextmanager
async def _r2c_client(served: Served) -> AsyncIterator[R2CClient]:
    """The SDK's own caller side, which activates R2C on every request."""
    http = served.http(user=OWNER)
    client = await R2CClient.connect(URL, httpx_client=http)
    try:
        yield client
    finally:
        await client.aclose()
        await http.aclose()


def test_a_caller_that_activated_r2c_gets_the_question_in_words_and_continues_in_words() -> None:
    async def go() -> None:
        async with serve_remote(_a2a_only(ConverterExecutor())) as served, _r2c_client(served) as client:
            first = [item async for item in client.send(ASKED)]
            assert [type(item) for item in first] == [TaskItem, StatusItem, StatusItem]
            _, working, asked = first
            assert (working.state, working.text) == ("working", LOOKING)
            assert (asked.state, asked.text) == ("input_required", WHICH_UNIT)
            assert client.pending is None, "a question in words only: there is no R2C request to answer"

            more = [item async for item in client.send("cm", context_id=client.context_id, task_id=client.task_id)]
            states = [item.state for item in more if isinstance(item, StatusItem)]
            assert states[-1] == "completed" and "input_required" not in states
            (result,) = [item for item in more if isinstance(item, ArtifactItem)]
            assert result.name == RESULT and result.meta is None
            assert result.parts == (TextContent(CM),)
            assert client.skipped == 0, "nothing of R2C came, so nothing was skipped"

    run(go())


@contextlib.asynccontextmanager
async def _the_sdk_alone(executor: ConverterExecutor) -> AsyncIterator[A2AServed]:
    """The same executor served by the a2a-sdk with nothing of R2C: what its owner had before."""
    card = plain_card()
    handler = DefaultRequestHandlerV2(agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card)
    app = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")])
    try:
        yield A2AServed(app, card)
    finally:
        await handler.aclose()


def _without_artifact_ids(node: Any) -> Any:
    """`wire` without the id of each artifact too: the executor gives the SDK none, so each run makes one."""
    if isinstance(node, dict):
        return {k: _without_artifact_ids(v) for k, v in node.items() if k != "artifactId"}
    if isinstance(node, list):
        return [_without_artifact_ids(v) for v in node]
    return node


def _same_wire(events: list[StreamResponse]) -> Any:
    return _without_artifact_ids(wire(events))


def _shape(events: list[StreamResponse]) -> list[str]:
    """One word per event, an artifact without its id."""
    return [kind.partition(":")[0] for kind in kinds(events)]


async def _a_question_and_a_direct_run(tc: Any) -> list[list[StreamResponse]]:
    first = await send(tc, ASKED)
    second = await send(tc, "cm", **ids(first))
    third = await send(tc, AT_ONCE)
    return [first, second, third]


@pytest.mark.parametrize("r2c", [False, True], ids=["without R2C", "with R2C activated"])
def test_a_caller_gets_event_for_event_what_the_sdk_alone_serves(r2c: bool) -> None:
    async def go() -> None:
        async with _the_sdk_alone(ConverterExecutor()) as before, a2a_client(before, r2c=False) as tc:
            expected = await _a_question_and_a_direct_run(tc)
        assert [_shape(events) for events in expected] == [
            ["task", "working", "input_required"],
            ["working", "artifact", "completed"],
            ["task", "working", "artifact", "completed"],
        ], "the control: the executor asks in words, continues on the reply, and can answer at once"
        assert CM in str(wire(expected[1])) and M in str(wire(expected[2]))

        async with serve_remote(_a2a_only(ConverterExecutor())) as served, served.a2a(r2c=r2c) as tc:
            through_remote = await _a_question_and_a_direct_run(tc)
        assert [_same_wire(events) for events in through_remote] == [_same_wire(events) for events in expected]
        assert URI not in str([json_format.MessageToDict(event) for events in through_remote for event in events])

    run(go())


# --- 3. The object given, with nothing set on it (FR-005) ---------------------------------------------


def _attributes(thing: Any) -> dict[str, int]:
    """The attributes of an object and which object each one is."""
    return {name: id(value) for name, value in vars(thing).items()}


def test_remote_serves_the_executor_given_and_sets_nothing_on_it() -> None:
    async def go() -> None:
        executor = ConverterExecutor()
        before = {"the executor": _attributes(executor), "its agent": _attributes(executor.agent)}
        assert sorted(before["the executor"]) == ["agent"]

        remote = _a2a_only(executor)
        async with serve_remote(remote) as served, served.a2a() as tc:
            first = await send(tc, ASKED)
            await send(tc, "cm", **ids(first))
            context = ids(first)["context_id"]
        assert executor.agent.said == {context: [ASKED, "cm"]}, "the object given is the one that ran"
        after = {"the executor": _attributes(executor), "its agent": _attributes(executor.agent)}
        assert after == before, "`Remote` set nothing on the executor or on what it holds"

    run(go())


class _CountingExecutor(ConverterExecutor):
    """The executor of the sample that counts its own calls on itself: a copy of it would count apart."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        self.calls += 1
        await super().execute(context, event_queue)


def test_the_executor_that_runs_is_the_object_given_not_a_copy_of_it() -> None:
    async def go() -> None:
        executor = _CountingExecutor()
        async with serve_remote(_a2a_only(executor)) as served, served.a2a() as tc:
            first = await send(tc, ASKED)
            await send(tc, "cm", **ids(first))
        assert executor.calls == 2, "each call reached the object given, so none reached a copy of it"

    run(go())


# --- 4. An executor is served by the A2A door only ------------------------------------------------------


def test_an_executor_with_the_mcp_door_only_is_a_problem_of_agent() -> None:
    assert _refused(expose=["mcp"], agent=ConverterExecutor(), card=CARD, tools=[publish_page]) == ["agent"]
    assert _refused(expose=["mcp"], agent=ConverterExecutor(), card=CARD) == ["agent", "tools"], (
        "an executor is nothing the MCP door can serve")
    (problem,) = _problems(expose=["mcp"], agent=ConverterExecutor(), card=CARD, tools=[publish_page])
    assert "executor" in problem and "A2A" in problem, "it says what the agent is and which door serves it"
    assert "mcp_tool" not in problem, "mcp_tool is no way out for an executor: it is advice for an AgentSource"


def test_an_executor_as_an_mcp_tool_is_a_problem_of_mcp_tool() -> None:
    assert _refused(agent=ConverterExecutor(), card=CARD, tools=[publish_page], mcp_tool=True) == ["mcp_tool"]
    with pytest.raises(RemoteError) as caught:
        quiet(agent=ConverterExecutor(), card=CARD, tools=[publish_page], mcp_tool=True)
    (problem,) = caught.value.problems
    assert "executor" in problem and "AgentSource" in problem


def test_an_executor_on_a2a_beside_tools_on_mcp() -> None:
    async def go() -> None:
        executor = ConverterExecutor()
        remote = quiet(agent=executor, card=CARD, tools=[publish_page])
        async with serve_remote(remote) as served, served.a2a() as tc, served.mcp() as client:
            first = await send(tc, ASKED)
            assert kinds(first) == ["task", "working", "input_required"]
            second = await send(tc, "cm", **ids(first))
            assert kinds(second)[-1] == "completed" and CM in str(wire(second))

            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == ["publish_page"], "the executor is no MCP tool"
            done = await call(client, "publish_page", {"slug": "intro"})
            assert not done.is_error and texts(done) == ["published intro"]

    run(go())
