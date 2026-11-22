"""Builders for the LangGraph bridge's tests (spec 006, research R17).

Real packages, one fake: the graph is `langchain.agents.create_agent`, the middleware is LangChain's
`HumanInTheLoopMiddleware`, the checkpointers are LangGraph's own, and only the chat model is
scripted (`langgraph_models.Scripted`). Tool names are invented (constitution VI).

`suite_graph` is the graph the shared `AgentSource` suite drives (D3); `wrap` builds the bridge over a
graph and ignores only the in-memory warning (D11).
"""

from __future__ import annotations

import asyncio
import warnings
from collections import Counter
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import interrupt

from langgraph_models import Call, Say, Scripted, Turn, last_human, tool_results

DEPLOY = "deploy_release"
NOTICE = "send_notice"
PUBLISH = "publish_page"
ASK_QUESTION = "ask_question"
ASK_APPROVAL = "ask_approval"

# What the suite's graph asks, written by hand as valid R2C objects (pause-mapping rows 4 and 5): the
# ids are the suite's own (`q-1`, `ap-1`), so no answer of the suite has to change.
SUITE_QUESTION: dict[str, Any] = {
    "kind": "question", "id": "q-1", "title": "Report title", "answer_by": {"role": "person"},
    "fields": [{"key": "title", "header": "Title", "text": "What is the report's title?", "type": "text"}],
}
SUITE_APPROVAL: dict[str, Any] = {
    "kind": "approval", "id": "ap-1", "title": "Publish the page", "answer_by": {"role": "person"},
    "subject": {"type": "tool_call", "name": "publish_page", "args": {"page": "team/reports"}},
    "decisions": ["allow", "deny"],
}

TIMEOUT = 30.0
T = TypeVar("T")


def run(coro: Coroutine[Any, Any, T], timeout: float = TIMEOUT) -> T:
    """Run a coroutine to its end, or fail the test after `timeout` seconds (never hang)."""
    return asyncio.run(asyncio.wait_for(coro, timeout))


def counted_tools(runs: Counter[str]) -> dict[str, BaseTool]:
    """Three tools whose bodies add one to `runs[name]` each time the body runs.

    A paused or denied call must leave its count at zero: that is how a test sees that a tool was
    (or was not) really called.
    """

    @tool(DEPLOY)
    def deploy_release(version: str, region: str = "north") -> str:
        """Roll a release out to a region."""
        runs[DEPLOY] += 1
        return f"deployed {version} to {region}"

    @tool(NOTICE)
    def send_notice(text: str) -> str:
        """Send a short notice to the team."""
        runs[NOTICE] += 1
        return f"sent: {text}"

    @tool(PUBLISH)
    def publish_page(slug: str) -> str:
        """Publish a page of the handbook."""
        runs[PUBLISH] += 1
        return f"published {slug}"

    return {t.name: t for t in (deploy_release, send_notice, publish_page)}


def agent(
    model: Any,
    tools: Sequence[BaseTool] | None,
    saver: Any,
    *,
    middleware: Sequence[Any] = (),
    response_format: Any = None,
    name: str = "agent",
) -> Any:
    """A compiled LangChain agent over `saver` (a graph with no saver cannot pause)."""
    return create_agent(
        model,
        list(tools or []),
        middleware=tuple(middleware),
        response_format=response_format,
        checkpointer=saver,
        name=name,
    )


def memory_saver() -> InMemorySaver:
    """An in-memory checkpointer: the default of the suite (no file, no restart)."""
    return InMemorySaver()


def sqlite_saver(path: Path) -> AbstractAsyncContextManager[AsyncSqliteSaver]:
    """An async context manager yielding an `AsyncSqliteSaver` on the file `path`.

    The SQLite saver is the tests' durable checkpointer; it is never in the extra (FR-027).
    """

    @asynccontextmanager
    async def opened() -> AsyncIterator[AsyncSqliteSaver]:
        async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
            await saver.setup()
            yield saver

    return opened()


def restart(path: Path) -> AbstractAsyncContextManager[AsyncSqliteSaver]:
    """A new saver over the same file: build a new graph and a new agent on it.

    Nothing of the first process is kept; what the second one knows, the file holds.
    """
    return sqlite_saver(path)


# ---------------------------------------------------------------------------------------------
# The graph of the shared suite (D3, contracts/suite-changes.md)


def suite_script(messages: list[BaseMessage]) -> Turn:
    """A pure function of the history: ask, then say what the tool returned, once."""
    results = tool_results(messages)
    if results:
        return Say(str(results[-1].content), tokens=(8, 4))
    if "publish" in last_human(messages):
        return Call((ASK_APPROVAL, {}), tokens=(6, 2))
    return Call((ASK_QUESTION, {}), tokens=(6, 2))


def suite_tools(*, fail_after_ask: bool = False) -> list[BaseTool]:
    """The two tools whose bodies `interrupt()` with the suite's own payloads.

    With `fail_after_ask` the body raises once its `interrupt()` has returned (S8).
    """

    @tool(ASK_QUESTION)
    def ask_question() -> str:
        """Ask the caller for the report's title."""
        answer = interrupt(SUITE_QUESTION)
        if fail_after_ask:
            raise RuntimeError("the agent broke")
        return "Declined" if answer is None else f"Got: {answer['title']}"

    @tool(ASK_APPROVAL)
    def ask_approval() -> str:
        """Ask the caller to approve publishing the report."""
        answer = interrupt(SUITE_APPROVAL)
        if fail_after_ask:
            raise RuntimeError("the agent broke")
        if answer is None:
            return "Declined"
        if answer["decision"] == "allow":
            return "Done"
        return f"Not done: {answer.get('reason', '')}"

    return [ask_question, ask_approval]


def suite_graph(saver: Any, *, fail_after_ask: bool = False) -> Any:
    """The compiled graph the suite's wrapper serves, over `saver`."""
    return agent(Scripted(script=suite_script), suite_tools(fail_after_ask=fail_after_ask), saver, name="suite")


def wrap(graph: Any, **options: Any) -> Any:
    """A `LangGraphAgent` over `graph`, ignoring only the in-memory warning of D11.

    (The bridge is imported here, not at the top: the spike tests import this file and must run before
    the bridge exists.)
    """
    from ext_r2c.bridges.langgraph import LangGraphAgent

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*not survive a restart.*", category=UserWarning)
        return LangGraphAgent(graph, **options)
