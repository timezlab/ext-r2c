"""One ASGI app from the two door apps (spec 007, research R1, R2 and R10;
contracts/app-composition.md).

The parent is a Starlette app with one route, a dispatcher, and one lifespan that starts and stops
both doors. Each door app is served whole, so it keeps its own middleware (A2A's echo of the
activated extensions, the MCP SDK's authentication) and its own answers for a wrong method or a
missing path. The owner's middleware wraps both, outside.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence
from typing import Any

from ._errors import RemoteError

__all__ = ["Dispatch", "check_no_collision", "parent_app"]


class Dispatch:
    """An ASGI app: a request the MCP app's own router matches goes to MCP, everything else to A2A.

    Asking the router, not a list of paths, is what finds the routes the SDK adds by itself (the
    OAuth metadata when its authentication is on). A match on the path with another method is
    MCP's too: MCP answers it. With one door there is nothing to ask: its app gets everything.
    """

    def __init__(self, a2a: Any, mcp: Any) -> None:
        from starlette.routing import Match

        self._a2a, self._mcp, self._no_match = a2a, mcp, Match.NONE

    def is_mcp(self, scope: Any) -> bool:
        if self._mcp is None or self._a2a is None:
            return self._a2a is None
        return any(route.matches(scope)[0] != self._no_match for route in self._mcp.router.routes)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await (self._mcp if self.is_mcp(scope) else self._a2a)(scope, receive, send)


def check_no_collision(a2a: Any, mcp: Any, a2a_path: str) -> None:
    """Every path the A2A app answers must reach it: one the MCP router takes too is a
    ``RemoteError``. This runs on the built apps, so it sees every route, whoever added it."""
    dispatch = Dispatch(a2a, mcp)
    problems = []
    for route in a2a.router.routes:
        path = getattr(route, "path", None)
        if path is None or not dispatch.is_mcp({"type": "http", "method": "GET", "path": path, "root_path": "",
                                                "headers": []}):
            continue
        if path == a2a_path:
            problems.append("a2a.path: the MCP door answers this path too; give the A2A door another path")
        else:  # the card's path, which the A2A SDK fixes: only an MCP setting can have taken it
            problems.append(f"mcp: the MCP door answers {path}, where the A2A card is; "
                            "change the MCP setting that adds this route")
    if problems:
        raise RemoteError(problems)


def parent_app(a2a: Any, mcp: Any, middleware: Sequence[Any]) -> Any:
    """The app ``Remote.app()`` returns: ``a2a`` and ``mcp`` are the door apps, one of them may be
    ``None``. Its lifespan starts A2A, then MCP, and stops them in the reverse order; a door that
    fails to start unwinds the one already started and the error propagates."""
    from starlette.applications import Starlette
    from starlette.routing import Mount

    @contextlib.asynccontextmanager
    async def both(app: Any) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for door in (a2a, mcp):
                if door is not None:
                    await stack.enter_async_context(door.router.lifespan_context(door))
            yield

    return Starlette(routes=[Mount("/", app=Dispatch(a2a, mcp))], middleware=list(middleware), lifespan=both)
