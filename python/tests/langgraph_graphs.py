"""Builders for the LangGraph bridge's tests (spec 006, research R17).

Real packages, one fake: the graph is `langchain.agents.create_agent`, the middleware is LangChain's
`HumanInTheLoopMiddleware`, the checkpointers are LangGraph's own, and only the chat model is
scripted (`langgraph_models.Scripted`). Tool names are invented (constitution VI).

`wrap(graph, **options)` joins this file in phase 3, when `LangGraphAgent` exists.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

from langchain.agents import create_agent
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

DEPLOY = "deploy_release"
NOTICE = "send_notice"
PUBLISH = "publish_page"

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
