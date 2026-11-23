"""A mistake fails when the `Remote` is built (spec 007, story 2; research R6 and R7).

Section 1 is `RemoteError` itself. The later sections are one test per row of the build-problem
table, the order of the three error kinds, and what a message may say.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import subprocess
import sys
import warnings
from typing import Any, cast

import pytest
from a2a.server.agent_execution import AgentExecutor
from ext_r2c import A2AOptions, MCPOptions, Remote, RemoteError
from ext_r2c.core import CardInfo, ToolSpec, tool_from_function
from ext_r2c.mcp import Approve, SourceTool
from ext_r2c.remote._options import HTTP_OWNED, SERVER_OWNED
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts import Prompt
from mcp.server.mcpserver.resources import TextResource

from fake_sources import CARD, CheckpointFake
from remote_harness import CARD_PATH, URL, a2a_options, identity, mcp_options, serve_remote

# --- 1. `RemoteError` -----------------------------------------------------------------------------


def test_a_remote_error_is_a_value_error_that_lists_its_problems() -> None:
    error = RemoteError(["url: not given; pass the public address of the app", "tools: MCP is not exposed"])
    assert isinstance(error, ValueError)
    assert error.problems == ("url: not given; pass the public address of the app", "tools: MCP is not exposed")
    assert isinstance(error.problems, tuple) and all(isinstance(p, str) for p in error.problems)


def test_its_text_says_what_failed_and_lists_one_problem_per_line() -> None:
    error = RemoteError(["agent: not given", "url: not given"])
    lines = str(error).splitlines()
    assert lines[0].startswith("Remote cannot be built:") and "2 problems" in lines[0]
    assert lines[1:] == ["- agent: not given", "- url: not given"]
    assert str(RemoteError(["agent: not given"])).splitlines()[0] == "Remote cannot be built: 1 problem"


def test_a_remote_error_needs_at_least_one_problem() -> None:
    with pytest.raises(ValueError, match="at least one problem"):
        RemoteError([])
    with pytest.raises(TypeError):
        RemoteError("agent: not given")  # a bare string would be read as a list of letters
    with pytest.raises(TypeError):
        RemoteError(["agent: not given", 3])  # type: ignore[list-item]


def test_a_remote_error_can_be_raised_and_caught_as_a_value_error() -> None:
    with pytest.raises(ValueError) as caught:
        raise RemoteError(["agent: not given"])
    assert caught.value.args == (str(caught.value),)


# --- What the later sections build from -------------------------------------------------------------


def publish_page(slug: str) -> str:
    """Publish a page of the handbook."""
    return f"published {slug}"


def send_notice(text: str) -> str:
    """Send a short notice to the team."""
    return f"sent: {text}"


def a_prompt() -> str:
    """A prompt for tests."""
    return "Say hello"


class Executor(AgentExecutor):
    """A hand-written a2a-sdk executor: it has no card of its own."""

    async def execute(self, context: Any, event_queue: Any) -> None: ...

    async def cancel(self, context: Any, event_queue: Any) -> None: ...


def _source() -> CheckpointFake:
    return CheckpointFake({})


def _both(**changes: Any) -> dict[str, Any]:
    """A valid configuration of both doors, with the changes a test makes."""
    arguments: dict[str, Any] = {
        "expose": ["a2a", "mcp"], "agent": _source(), "url": URL, "tools": [publish_page], "mcp_tool": True,
        "a2a": a2a_options(), "mcp": mcp_options(), "middleware": identity(),
    }
    return _changed(arguments, changes)


def _a2a_only(**changes: Any) -> dict[str, Any]:
    return _changed({"expose": ["a2a"], "agent": _source(), "url": URL, "a2a": a2a_options()}, changes)


def _mcp_only(**changes: Any) -> dict[str, Any]:
    return _changed({"expose": ["mcp"], "tools": [publish_page], "card": CARD, "mcp": mcp_options()}, changes)


def _changed(arguments: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    arguments.update(changes)
    return {name: value for name, value in arguments.items() if value is not _LEFT_OUT}


_LEFT_OUT: Any = object()  # a change that leaves an argument out


def _refused(arguments: dict[str, Any]) -> RemoteError:
    with pytest.raises(RemoteError) as caught:
        Remote(**arguments)
    return caught.value


def _says_what_to_do(problem: str) -> bool:
    """`<argument>: <what is wrong>; <what to do>`."""
    name, _, rest = problem.partition(": ")
    wrong, _, to_do = rest.partition("; ")
    return bool(name) and " " not in name and bool(wrong.strip()) and bool(to_do.strip())


def test_the_three_valid_configurations_build() -> None:
    """The control of every test below: without its one change, each configuration builds."""
    for arguments in (_both(), _a2a_only(), _mcp_only()):
        Remote(**arguments).app()


# --- 2. A missing extra is said first, and names the extra (R6 step 2; FR-006) ------------------------

_CHILD = """
import json, sys
for name in {blocked!r}:
    sys.modules[name] = None
import ext_r2c
from ext_r2c import Remote
out = {{}}
try:
    Remote(expose={expose!r}, agent=object(), url=3, tools="not a list", approve="not a list")
    out["raised"] = None
except BaseException as error:
    out["raised"] = type(error).__name__
    out["text"] = str(error)
    out["cause"] = type(error.__cause__).__name__
print(json.dumps(out))
"""


def _child(code: str) -> dict[str, Any]:
    done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return cast(dict[str, Any], json.loads(done.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize(("blocked", "expose", "named", "not_named"), [
    (["a2a"], ["a2a"], ["ext-r2c[a2a]"], ["ext-r2c[mcp]"]),
    (["starlette"], ["a2a"], ["ext-r2c[a2a]"], ["ext-r2c[mcp]"]),  # a2a-sdk without its HTTP server
    (["mcp"], ["mcp"], ["ext-r2c[mcp]"], ["ext-r2c[a2a]"]),
    (["mcp", "mcp_types"], ["mcp"], ["ext-r2c[mcp]"], ["ext-r2c[a2a]"]),  # what a core-only install shows
    (["yaml"], ["mcp"], ["ext-r2c[mcp]"], ["ext-r2c[a2a]"]),
    (["a2a", "mcp"], ["a2a", "mcp"], ["ext-r2c[a2a]", "ext-r2c[mcp]"], []),
    (["a2a"], ["a2a", "mcp"], ["ext-r2c[a2a]"], ["ext-r2c[mcp]"]),
    (["mcp"], ["a2a", "mcp"], ["ext-r2c[mcp]"], ["ext-r2c[a2a]"]),
])
def test_a_door_whose_extra_is_missing_is_an_import_error_that_names_it_before_any_other_check(
    blocked: list[str], expose: list[str], named: list[str], not_named: list[str],
) -> None:
    """The child's `Remote(...)` also has an agent, a `url`, `tools` and `approve` of the wrong type:
    the missing extra is still what the owner hears."""
    out = _child(_CHILD.format(blocked=blocked, expose=expose))
    assert out["raised"] == "ImportError", out
    assert out["text"].startswith("expose: ") and "pip install" in out["text"], "what is wrong, and what to do"
    assert all(extra in out["text"] for extra in named), out["text"]
    assert not any(extra in out["text"] for extra in not_named), out["text"]
    assert out["cause"] == "ModuleNotFoundError", "the import that failed is kept as the cause"


def test_a_door_that_is_not_exposed_may_be_missing() -> None:
    code = """
import json, sys
sys.modules["a2a"] = None
from ext_r2c import Remote
from ext_r2c.core import CardInfo

def publish_page(slug: str) -> str:
    \"\"\"Publish a page of the handbook.\"\"\"
    return slug

Remote(expose=["mcp"], tools=[publish_page], card=CardInfo(name="Pages", description="Publishes pages.", version="1"))
print(json.dumps({"a2a door loaded": "ext_r2c.a2a" in sys.modules}))
"""
    assert _child(code) == {"a2a door loaded": False}


def test_importing_remote_needs_no_extra_and_loads_no_door() -> None:
    code = """
import json, sys
for name in ("a2a", "mcp", "mcp_types", "yaml", "starlette"):
    sys.modules[name] = None
import ext_r2c
from ext_r2c import A2AOptions, MCPOptions, Remote, RemoteError
print(json.dumps(sorted(m for m in sys.modules if m.startswith(("ext_r2c.a2a", "ext_r2c.mcp", "ext_r2c.bridges")))))
"""
    assert _child(code) == []


def test_an_import_error_that_is_not_a_missing_extra_is_not_renamed(monkeypatch: pytest.MonkeyPatch) -> None:
    fault = ImportError("cannot import name 'gone' from 'somewhere'", name="somewhere")

    def broken(door: str) -> Any:
        raise fault

    monkeypatch.setattr("ext_r2c.remote._doors._load", broken)
    with pytest.raises(ImportError) as caught:
        Remote(**_both())
    assert caught.value is fault, "a fault in an installed door is the fault it is"


# --- 3. A wrong type is a `TypeError`, the first one found (R6 step 3; FR-031) ------------------------


class _Invokable:
    """A stand-in for a framework's tool object: it has `invoke` and is not a function."""

    name = "publish_page"

    def invoke(self, arguments: dict[str, Any]) -> str:
        return "published"


class _CallableInstance:
    def __call__(self, slug: str) -> str:
        return slug


class _AsgiMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app


class _SourceWithoutACard(CheckpointFake):
    card = None  # type: ignore[assignment]


def _langchain_tool() -> Any:
    from langchain_core.tools import tool

    return tool(publish_page)


_RESOURCE = TextResource(uri="file:///note.txt", name="note", text="A note.")
_PROMPT = Prompt.from_function(a_prompt)

WRONG_TYPES: list[tuple[str, dict[str, Any], str]] = [
    ("expose a bare str", _both(expose="mcp"), "expose"),
    ("expose with an item that is not a str", _both(expose=["a2a", 3]), "expose"),
    ("expose None", _both(expose=None), "expose"),
    ("agent of neither kind", _both(agent=object()), "agent"),
    ("agent a number", _both(agent=42), "agent"),
    ("agent a function", _both(agent=publish_page), "agent"),
    ("agent a source whose card is not a CardInfo", _both(agent=_SourceWithoutACard({})), "agent"),
    ("tools a bare str", _both(tools="publish_page"), "tools"),
    ("tools one function, not a list", _both(tools=publish_page), "tools"),
    ("a tool that is a partial", _both(tools=[functools.partial(publish_page, "home")]), "tools"),
    ("a tool that is a callable instance", _both(tools=[_CallableInstance()]), "tools"),
    ("a tool that is a framework's object", _both(tools=[_Invokable()]), "tools"),
    ("a tool that is a LangChain tool", _both(tools=[_langchain_tool()]), "tools"),
    ("approve a bare str", _both(approve="publish_page"), "approve"),
    ("approve with a name that is not a str", _both(approve=[3]), "approve"),
    ("approve with a value that is a str", _both(approve={"publish_page": "yes"}), "approve"),
    ("approve with a value that is a number", _both(approve={"publish_page": 1}), "approve"),
    ("skills a number", _both(skills=42), "skills"),
    ("skills a list with a number", _both(skills=["skills", 42]), "skills"),
    ("skills another object", _both(skills=object()), "skills"),
    ("resources a bare str", _both(resources="note"), "resources"),
    ("a resource of the wrong class", _both(resources=[_RESOURCE, object()]), "resources"),
    ("prompts a bare str", _both(prompts="a_prompt"), "prompts"),
    ("a prompt of the wrong class", _both(prompts=[a_prompt]), "prompts"),
    ("mcp_tool a str", _both(mcp_tool="yes"), "mcp_tool"),
    ("mcp_tool a number", _both(mcp_tool=1), "mcp_tool"),
    ("middleware a bare str", _both(middleware="auth"), "middleware"),
    ("a middleware class that is not wrapped", _both(middleware=[_AsgiMiddleware]), "middleware"),
    ("a2a of the other door's class", _both(a2a=MCPOptions()), "a2a"),
    ("a2a a dict", _both(a2a={"path": "/"}), "a2a"),
    ("mcp of the other door's class", _both(mcp=A2AOptions()), "mcp"),
    ("mcp a dict", _both(mcp={"path": "/mcp"}), "mcp"),
    ("limits a dict", _both(limits={"message_bytes": 1}), "limits"),
    ("clock not callable", _both(clock=5), "clock"),
    ("card a dict", _both(card={"name": "Pages"}), "card"),
    ("url a number", _both(url=3), "url"),
]


@pytest.mark.parametrize(("arguments", "argument"), [case[1:] for case in WRONG_TYPES], ids=[c[0] for c in WRONG_TYPES])
def test_a_wrong_type_is_a_type_error_that_names_the_argument(arguments: dict[str, Any], argument: str) -> None:
    with pytest.raises(TypeError) as caught:
        Remote(**arguments)
    assert not isinstance(caught.value, RemoteError)
    assert str(caught.value).startswith(f"{argument}: "), str(caught.value)


def test_a_call_without_expose_is_pythons_own_type_error() -> None:
    """`expose` is a required keyword, so a type checker sees a call without it; there is no default."""
    arguments = _both(expose=_LEFT_OUT)
    with pytest.raises(TypeError, match="expose"):
        Remote(**arguments)
    assert inspect.signature(Remote.__init__).parameters["expose"].default is inspect.Parameter.empty


def test_every_argument_is_a_keyword() -> None:
    with pytest.raises(TypeError):
        Remote(["a2a"], _source())  # type: ignore[misc]
    kinds = {p.kind for name, p in inspect.signature(Remote.__init__).parameters.items() if name != "self"}
    assert kinds == {inspect.Parameter.KEYWORD_ONLY}


def test_an_agent_of_neither_kind_is_told_both_kinds() -> None:
    with pytest.raises(TypeError) as caught:
        Remote(**_both(agent=object()))
    assert "AgentSource" in str(caught.value) and "AgentExecutor" in str(caught.value)


@pytest.mark.parametrize("tool", [functools.partial(publish_page, "home"), _CallableInstance(), _Invokable(),
                                  _langchain_tool()], ids=["partial", "callable instance", "stand-in", "langchain"])
def test_a_tool_remote_cannot_take_is_told_where_a_langchain_tool_is_converted(tool: Any) -> None:
    with pytest.raises(TypeError) as caught:
        Remote(**_both(tools=[publish_page, tool]))
    text = str(caught.value)
    assert "tools_from_langchain" in text and "ext_r2c.bridges.langgraph" in text
    assert "ToolSpec" in text and "SourceTool" in text and "function" in text, "the kinds it does take"


def many(*slugs: str) -> str:
    """A function that takes any number of arguments."""
    return ",".join(slugs)


def any_fields(**fields: str) -> str:
    """A function that takes any keyword."""
    return ",".join(fields)


def by_position(slug: str, /) -> str:
    """A function whose argument cannot be passed by name."""
    return slug


def underscored(_slug: str) -> str:
    """A function with an argument that begins with an underscore."""
    return _slug


def unreadable(slug: NoSuchType) -> str:  # type: ignore[name-defined]  # noqa: F821
    """A function with a type hint that names nothing."""
    return str(slug)


def no_hints(slug):  # type: ignore[no-untyped-def]
    """A function with no type hints: the core takes it, each argument is any value."""
    return slug


@pytest.mark.parametrize("function", [many, any_fields, by_position, underscored, unreadable],
                         ids=["*args", "**kwargs", "positional only", "underscore", "unreadable hint"])
def test_a_function_the_core_refuses_is_refused_with_the_cores_own_error(function: Any) -> None:
    with pytest.raises(TypeError) as direct:
        tool_from_function(function)
    with pytest.raises(TypeError) as through:
        Remote(**_both(tools=[function]))
    assert str(through.value) == str(direct.value), "the core's own words, with nothing put before them"
    assert through.value.__cause__ is None or type(through.value.__cause__) is type(direct.value.__cause__)


def test_a_function_the_core_takes_is_taken_whatever_its_hints() -> None:
    assert tool_from_function(no_hints).name == "no_hints"
    Remote(**_both(tools=[no_hints])).app()


def test_the_first_wrong_type_is_the_one_reported() -> None:
    """In the order of R6: the agent, the tools, `approve`, ..., `url`."""
    with pytest.raises(TypeError, match="^agent: "):
        Remote(**_both(agent=object(), tools="publish_page", url=3))
    with pytest.raises(TypeError, match="^tools: "):
        Remote(**_both(tools="publish_page", approve="publish_page", url=3))
    with pytest.raises(TypeError, match="^approve: "):
        Remote(**_both(approve="publish_page", url=3))


def test_middleware_is_typed_whichever_door_is_exposed() -> None:
    """Starlette comes with either door, so a wrong middleware entry is a `TypeError` with one door as
    with two."""
    for arguments in (_a2a_only(), _mcp_only(), _both()):
        with pytest.raises(TypeError, match="^middleware: "):
            Remote(**{**arguments, "middleware": [object()]})


def test_a_card_that_is_given_wins_over_the_one_an_agent_brings() -> None:
    """R7 row 3 reads `card=` first: the source's own card is the fallback, not the answer."""
    given = CardInfo(name="Page desk", description="Publishes pages.", version="0.0.2")
    assert given.name != CARD.name

    async def go() -> None:
        async with serve_remote(Remote(**_both(card=given)), info=given) as served:
            async with served.http() as http:
                assert (await http.get(CARD_PATH)).json()["name"] == given.name
            async with served.mcp() as client:
                assert client.server_info.name == given.name

    asyncio.run(go())


def test_a_check_that_needs_a_doors_class_waits_for_that_door() -> None:
    """With MCP not exposed its classes are not loaded, so what was meant for it is not typed against
    them: it is reported as unserved, with the rest (section 4)."""
    error = _refused(_a2a_only(tools=[_Invokable()], approve={"publish_page": "yes"}, skills=object()))
    assert [p.partition(":")[0] for p in error.problems] == ["tools", "approve", "skills"]


# --- 4. One test per row of the build-problem table (R7; FR-032; SC-005) ------------------------------

_WRITER = SourceTool(CheckpointFake({}), name="writer")
_TWIN = ToolSpec(name="publish_page", description="Another tool with the same name.",
                 input_schema={"type": "object", "properties": {}}, call=lambda arguments: None)  # type: ignore[arg-type, return-value]
_NAMED_AGENT = ToolSpec(name="agent", description="A plain tool that took the agent tool's name.",
                        input_schema={"type": "object", "properties": {}}, call=lambda arguments: None)  # type: ignore[arg-type, return-value]
_TO_THE_CALLER = Approve(answer_by=cast(Any, "caller"))

# (what the row is, the configuration with the one mistake, the argument its problem names, the same
#  configuration with only that mistake fixed, a word the problem must say)
ROWS: list[tuple[str, dict[str, Any], str, dict[str, Any], str]] = [
    ("1 expose is empty", _both(expose=[]), "expose", _both(), "a2a"),
    ("1 expose names an unknown door", _both(expose=["a2a", "mcp", "grpc"]), "expose", _both(), "a2a"),
    ("1 expose names a door twice", _both(expose=["a2a", "mcp", "a2a"]), "expose", _both(), "once"),
    ("2 A2A exposed, no agent", _a2a_only(agent=_LEFT_OUT, card=CARD), "agent", _a2a_only(card=CARD), "A2A"),
    ("3 no card: tools only", _mcp_only(card=_LEFT_OUT), "card", _mcp_only(), "CardInfo"),
    ("3 no card: an executor", _a2a_only(agent=Executor()), "card", _a2a_only(agent=Executor(), card=CARD), "CardInfo"),
    ("4 A2A exposed, no url", _a2a_only(url=_LEFT_OUT), "url", _a2a_only(), "base address"),
    ("5 MCP exposed, nothing to serve", _mcp_only(tools=_LEFT_OUT), "tools", _mcp_only(), "MCP"),
    ("5 both doors, the agent is not an MCP tool and nothing else is", _both(tools=_LEFT_OUT, mcp_tool=False), "tools",
     _both(tools=_LEFT_OUT), "mcp_tool"),
    ("6 a source no exposed door serves", _mcp_only(agent=_source(), card=_LEFT_OUT), "agent",
     _mcp_only(agent=_source(), card=_LEFT_OUT, mcp_tool=True), "mcp_tool"),
    ("6 an executor with MCP only", _mcp_only(agent=Executor()), "agent", _mcp_only(), "executor"),
    ("7 mcp_tool with an executor", _both(agent=Executor(), card=CARD), "mcp_tool",
     _both(agent=Executor(), card=CARD, mcp_tool=False), "executor"),
    ("8 tools, MCP not exposed", _a2a_only(tools=[publish_page]), "tools", _a2a_only(), "mcp"),
    ("8 approve, MCP not exposed", _a2a_only(approve=["publish_page"]), "approve", _a2a_only(), "mcp"),
    ("8 skills, MCP not exposed", _a2a_only(skills="skills"), "skills", _a2a_only(), "mcp"),
    ("8 resources, MCP not exposed", _a2a_only(resources=[_RESOURCE]), "resources", _a2a_only(), "mcp"),
    ("8 prompts, MCP not exposed", _a2a_only(prompts=[_PROMPT]), "prompts", _a2a_only(), "mcp"),
    ("8 mcp_tool, MCP not exposed", _a2a_only(mcp_tool=True), "mcp_tool", _a2a_only(), "mcp"),
    ("8 mcp, MCP not exposed", _a2a_only(mcp=mcp_options()), "mcp", _a2a_only(), "mcp"),
    ("9 url, A2A not exposed", _mcp_only(url=URL), "url", _mcp_only(), "a2a"),
    ("9 a2a, A2A not exposed", _mcp_only(a2a=a2a_options()), "a2a", _mcp_only(), "a2a"),
    ("10 approve names no tool", _both(approve=["publish_pgae"]), "approve", _both(approve=["publish_page"]),
     "publish_pgae"),
    ("10 approve names no tool, with False", _both(approve={"publish_pgae": False}), "approve",
     _both(approve={"publish_page": False}), "publish_pgae"),
    ("11 approve names the agent's tool", _both(approve=["agent"]), "approve", _both(), "agent"),
    ("11 approve names a SourceTool", _both(tools=[publish_page, _WRITER], approve=["writer"]), "approve",
     _both(tools=[publish_page, SourceTool(CheckpointFake({}), name="writer")]), "writer"),
    ("12 two tools with one name", _both(tools=[publish_page, _TWIN]), "tools", _both(tools=[publish_page]),
     "publish_page"),
    ("12 a tool with the agent tool's name", _both(tools=[_NAMED_AGENT]), "tools", _both(), "agent"),
    ("13 the two paths are one", _both(a2a=a2a_options(path="/mcp")), "a2a.path", _both(), "mcp.path"),
    ("13 the two paths are one, moved", _both(mcp=mcp_options(path="/")), "a2a.path", _both(), "mcp.path"),
    ("14 mcp_tool with no agent", _mcp_only(mcp_tool=True), "mcp_tool", _mcp_only(), "agent"),
    ("16 an approval addressed to the caller", _both(approve={"publish_page": _TO_THE_CALLER}), "approve",
     _both(approve={"publish_page": Approve(answer_by="approver")}), "person"),
    ("17 url with no scheme", _a2a_only(url="remote.example.com"), "url", _a2a_only(), "https"),
    ("17 url with another scheme", _a2a_only(url="ftp://remote.example.com"), "url", _a2a_only(), "https"),
    ("17 url with no host", _a2a_only(url="https://"), "url", _a2a_only(), "host"),
    ("17 url that is a path", _a2a_only(url="/agents/one"), "url", _a2a_only(), "https"),
    ("17 url with user info", _a2a_only(url="https://someone:secret@remote.example.com"), "url", _a2a_only(), "user"),
    ("17 url with a query", _a2a_only(url="https://remote.example.com/?team=one"), "url", _a2a_only(), "query"),
    ("17 url with a fragment", _a2a_only(url="https://remote.example.com/#top"), "url", _a2a_only(), "fragment"),
    ("18 a2a.path without a leading slash", _both(a2a=a2a_options(path="rpc")), "a2a.path", _both(), "/"),
    ("18 mcp.path without a leading slash", _both(mcp=mcp_options(path="tools")), "mcp.path", _both(), "/"),
    ("18 a2a.path under /.well-known/", _both(a2a=a2a_options(path="/.well-known/rpc")), "a2a.path", _both(),
     "/.well-known/"),
    ("18 mcp.path under /.well-known/", _both(mcp=mcp_options(path="/.well-known/tools")), "mcp.path", _both(),
     "/.well-known/"),
    *[(f"19 mcp.server names {key}", _both(mcp=mcp_options(server={key: None})), "mcp.server", _both(), key)
      for key in SERVER_OWNED],
    *[(f"19 mcp.http names {key}", _both(mcp=mcp_options(http={key: None})), "mcp.http", _both(), key)
      for key in HTTP_OWNED],
]


@pytest.mark.parametrize(("broken", "argument", "fixed", "says"), [row[1:] for row in ROWS], ids=[r[0] for r in ROWS])
def test_one_mistake_is_one_problem_that_names_its_argument(
    broken: dict[str, Any], argument: str, fixed: dict[str, Any], says: str,
) -> None:
    error = _refused(broken)
    assert isinstance(error, ValueError)
    (problem,) = error.problems
    assert problem.startswith(f"{argument}: "), problem
    assert says in problem, problem
    assert _says_what_to_do(problem), problem
    assert str(error).splitlines() == ["Remote cannot be built: 1 problem", f"- {problem}"]
    Remote(**fixed).app()  # with only that argument fixed, the same configuration builds


def test_the_keys_remote_owns_are_keywords_the_sdk_has() -> None:
    """A rename in the SDK fails here, not in a deployment (research R8)."""
    server = set(inspect.signature(MCPServer.__init__).parameters)
    http = set(inspect.signature(MCPServer.streamable_http_app).parameters)
    assert set(SERVER_OWNED) <= server and set(HTTP_OWNED) <= http
    assert set(SERVER_OWNED) == {"name", "description", "version", "extensions", "tools", "resources",
                                 "request_state_security"}
    assert set(HTTP_OWNED) == {"streamable_http_path", "transport_security"}


def test_an_approval_may_be_addressed_to_a_person_or_an_approver_only() -> None:
    """Principle V at build time: `Approve` itself does not check who answers (pinned in the spike)."""
    for answer_by in ("person", "approver"):
        Remote(**_both(approve={"publish_page": Approve(answer_by=cast(Any, answer_by))})).app()
    for answer_by in ("caller", "model", "agent", "", None):
        error = _refused(_both(approve={"publish_page": Approve(answer_by=cast(Any, answer_by))}))
        assert [p.partition(":")[0] for p in error.problems] == ["approve"], answer_by


def test_a_name_list_and_a_mapping_of_approve_are_checked_alike() -> None:
    for approve in (["send_notice"], {"send_notice": True}, {"send_notice": Approve()}, {"send_notice": False}):
        (problem,) = _refused(_both(approve=approve)).problems
        assert problem.startswith("approve: ") and "send_notice" in problem
        Remote(**_both(tools=[publish_page, send_notice], approve=approve)).app()


# --- 5. Every problem at once, and nothing the owner typed is said back (FR-031, FR-033) --------------

CANARY_USER = "canary-user-5b1e"
CANARY_SECRET = "canary-secret-93fd"
CANARY_PATH = "canary-path-7f3a"
CANARY_NAME = "canary-name-2c8d"
CANARY_HTTP = "canary-http-61e0"


def test_several_mistakes_are_one_error_in_a_stable_order_and_fixing_each_ends_in_an_app() -> None:
    arguments = _both(
        expose=["a2a", "mcp", "a2a"],
        url=f"https://{CANARY_USER}:{CANARY_SECRET}@remote.example.com",
        tools=[publish_page, _TWIN],
        approve=["publish_pgae", "agent"],
        a2a=a2a_options(path=CANARY_PATH),
        mcp=mcp_options(path=f"/.well-known/{CANARY_PATH}", server={"name": CANARY_NAME},
                        http={"streamable_http_path": CANARY_HTTP}),
    )
    error = _refused(arguments)
    assert [p.partition(":")[0] for p in error.problems] == [
        "expose", "url", "tools", "approve", "approve", "a2a.path", "mcp.path", "mcp.server", "mcp.http",
    ], "the order of the arguments, whatever order they were typed in"
    assert str(error).splitlines()[0] == "Remote cannot be built: 9 problems"
    assert _refused(dict(reversed(list(arguments.items())))).problems == error.problems
    assert all(_says_what_to_do(problem) for problem in error.problems)
    for canary in (CANARY_USER, CANARY_SECRET, CANARY_PATH, CANARY_NAME, CANARY_HTTP):
        assert canary not in str(error) and not any(canary in p for p in error.problems), "no value is said back"

    fixes: list[dict[str, Any]] = [
        {"expose": ["a2a", "mcp"]}, {"url": URL}, {"tools": [publish_page]}, {"approve": ["publish_page"]},
        {"a2a": a2a_options()}, {"mcp": mcp_options(server={"name": "Pages"}, http={"streamable_http_path": "/x"})},
        {"mcp": mcp_options(http={"streamable_http_path": "/x"})}, {"mcp": mcp_options()},
    ]
    left = list(error.problems)
    for fix in fixes[:-1]:
        arguments.update(fix)
        now = list(_refused(arguments).problems)
        assert len(now) < len(left) and all(problem in left for problem in now), "a fix removes problems, adds none"
        left = now
    arguments.update(fixes[-1])
    Remote(**arguments).app()


def test_a_url_or_a_path_is_never_said_back_in_a_type_error_either() -> None:
    with pytest.raises(TypeError) as caught:
        Remote(**_both(url=CANARY_SECRET.encode()))
    assert CANARY_SECRET not in str(caught.value)


def test_no_problem_of_any_row_says_a_value_back() -> None:
    """Every row above, read again: a problem may name an argument, a door, a tool or a key the owner
    chose; never an address or a path they typed."""
    typed = ("remote.example.com", "someone", "secret", "team=one", "#top", "/agents/one", "/rpc", "/tools",
             "ftp:", "grpc")
    for what, broken, _, _, _ in ROWS:
        text = str(_refused(broken))
        assert not any(value in text for value in typed), (what, text)


# --- 6. The order of the three kinds, and no warning from a refused `Remote` (R6) ---------------------


def test_a_wrong_type_is_reported_before_the_collected_problems() -> None:
    with pytest.raises(TypeError, match="^agent: "):
        Remote(**_a2a_only(agent=object(), url=_LEFT_OUT))  # no `url` either: that one is a problem
    with pytest.raises(TypeError, match="^agent: "):
        Remote(**_both(expose=[], agent=object()))


def test_a_refused_remote_warns_nothing_and_a_careful_one_neither() -> None:
    """A `Remote` with no task store and no request-state keys warns once it is valid (phase 6); one that
    is refused says only what is wrong."""
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        _refused({"expose": ["a2a", "mcp"], "agent": _source(), "mcp_tool": True, "approve": ["publish_pgae"]})
        with pytest.raises(TypeError):
            Remote(expose=["a2a", "mcp"], agent=object())
        Remote(**_both())
    assert seen == []
