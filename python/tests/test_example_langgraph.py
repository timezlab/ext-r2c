"""`examples/langgraph_agent` runs against the installed wheel: two LangGraph agents, both doors, real
sockets, a scripted model. The example is documentation, so this test is what keeps it true.

It pins the things the example is there to show:
- an agent asks its caller a question and a person approves, over A2A (flow 1);
- one agent calls another over A2A, and the callee calls back a plain MCP tool of the first (flow 2);
- the calling agent answers what is its to answer (a question for the caller) and a rule declines an
  approval, so the gated tool never runs (principle 5: no model answers an approval);
- the same agent is also an MCP tool.
"""

from __future__ import annotations

import asyncio
import importlib
import signal
import socket
import sys
from collections.abc import Coroutine, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, TypeVar

import pytest
from ext_r2c.core import Answer, AnsweredBy, Approval, Question

T = TypeVar("T")

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "langgraph_agent"
MODULES = ("models", "peers", "planner", "reporter", "main")
TIMEOUT = 60.0

pytestmark = pytest.mark.filterwarnings("ignore:.*not survive a restart.*:UserWarning")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to its end, or fail the test after `TIMEOUT` seconds (never hang)."""
    return asyncio.run(asyncio.wait_for(coro, TIMEOUT))


@pytest.fixture
def example(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """The example's `main` module, imported fresh on two free ports."""
    if not EXAMPLE.is_dir():
        pytest.fail(f"the example is not at {EXAMPLE}; run the tests from a repository checkout", pytrace=False)
    monkeypatch.setenv("PLANNER_URL", f"http://127.0.0.1:{free_port()}")
    monkeypatch.setenv("REPORTER_URL", f"http://127.0.0.1:{free_port()}")
    monkeypatch.delenv("R2C_EXAMPLE_MODEL", raising=False)
    monkeypatch.syspath_prepend(str(EXAMPLE))
    for name in MODULES:
        sys.modules.pop(name, None)
    yield importlib.import_module("main")
    for name in MODULES:
        sys.modules.pop(name, None)


def test_both_conversations_end_as_the_example_says(example: ModuleType) -> None:
    first, second = run(example.main(auto=True))

    # Flow 1: the person answered the question and allowed the page.
    assert first == "Stock report for 2026-10: ACME 120, GLOBEX 40. Published."
    # Flow 2: the planner answered the month, and a rule declined the approval.
    assert second == "The reporter says: Stock report for 2026-10: ACME 120, GLOBEX 40. Not published: the approval was refused."
    # The gated tool ran once, for the person's `allow`, and never for the planner's declined approval.
    assert sys.modules["reporter"].PUBLISHED == ["reports/2026-10"]


def test_a_person_who_denies_stops_the_page(example: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    async def deny(request: Question | Approval) -> Answer:
        who = AnsweredBy(role="person")
        if isinstance(request, Question):
            return Answer(id=request.id, outcome="answered", answered_by=who, value={f.key: "2026-09" for f in request.fields})
        return Answer(id=request.id, outcome="answered", answered_by=who, value={"decision": "deny", "reason": "Not this week."})

    monkeypatch.setattr(example, "scripted_person", deny)
    first, _ = run(example.main(auto=True))

    assert first == "Stock report for 2026-09: ACME 120, GLOBEX 40. Not published: the approval was refused."
    assert sys.modules["reporter"].PUBLISHED == []


def test_the_reporter_is_also_an_mcp_tool(example: ModuleType) -> None:
    peers, planner, reporter = sys.modules["peers"], sys.modules["planner"], sys.modules["reporter"]

    async def go() -> tuple[str, str]:
        async with example.serving((planner.app, peers.PLANNER_URL), (reporter.app, peers.REPORTER_URL)):
            holdings = await peers.call_tool(peers.PLANNER_URL, "holdings", {})
            report = await peers.call_tool(peers.REPORTER_URL, "agent", {"message": "Write the stock report for 2026-10."})
            return holdings, report

    holdings, report = run(go())

    assert holdings == "ACME 120\nGLOBEX 40"
    assert report == "Stock report for 2026-10: ACME 120, GLOBEX 40. Not published."


def test_serving_two_apps_leaves_the_signal_handlers_as_it_found_them(example: ModuleType) -> None:
    """Each uvicorn server puts back the handler it found when it started. Stopped in the order they
    started, the second puts back the first's handler, which says `should_exit`: sse-starlette reads
    that handler, thinks a server is shutting down, and ends every later event stream of the process
    (found as 34 other tests failing after this one ran)."""
    peers, planner, reporter = sys.modules["peers"], sys.modules["planner"], sys.modules["reporter"]
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

    async def go() -> None:
        async with example.serving((planner.app, peers.PLANNER_URL), (reporter.app, peers.REPORTER_URL)):
            pass

    run(go())

    assert {s: signal.getsignal(s) for s in before} == before


def test_a_caller_with_nobody_to_answer_stops_the_call(example: ModuleType) -> None:
    peers, planner, reporter = sys.modules["peers"], sys.modules["planner"], sys.modules["reporter"]

    async def nobody(request: Question | Approval) -> Answer | None:
        return None

    async def go() -> str:
        async with example.serving((planner.app, peers.PLANNER_URL), (reporter.app, peers.REPORTER_URL)):
            return await peers.ask_agent(peers.REPORTER_URL, "Write the stock report and publish it.", nobody)

    assert run(go()) == "Stopped: nobody here can answer 'Which month?'."
    assert reporter.PUBLISHED == []
