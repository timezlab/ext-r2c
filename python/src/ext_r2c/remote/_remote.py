"""``Remote``: one adapter that serves an existing remote over A2A, MCP or both (spec 007)."""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from os import PathLike
from typing import TYPE_CHECKING, Any, Literal

from ..core import AgentSource, CardInfo, Limits, ToolSpec
from ._check import check, warning_texts
from ._classify import read_expose
from ._compose import check_no_collision, parent_app
from ._doors import build_a2a, build_mcp, load_doors
from ._options import A2AOptions, MCPOptions

if TYPE_CHECKING:
    from a2a.server.agent_execution import AgentExecutor
    from mcp.server.mcpserver.prompts import Prompt
    from mcp.server.mcpserver.resources import Resource
    from starlette.middleware import Middleware
    from starlette.types import ASGIApp

    from ..mcp import Approve, SkillsExtension, SourceTool

__all__ = ["Remote"]


class Remote:
    """Serves an existing remote over A2A, MCP or both, from one ASGI app.

    ``Remote(...)`` checks what it is given and builds nothing; ``app()`` builds the app, once::

        app = Remote(agent=LangGraphAgent(graph), tools=[publish_page], mcp_tool=True,
                     expose=["a2a", "mcp"], url="https://remote.example.com").app()

    The agent, the tools and the graph are served as they are: nothing is set on them, and the
    modules that define them import nothing of R2C. ``expose`` names the doors; the package of a
    door is loaded only when the door is named. Every argument, the door that serves it and every
    error are in ``specs/007-remote/contracts/remote-api.md``.
    """

    def __init__(
        self,
        *,
        expose: Sequence[Literal["a2a", "mcp"]],
        agent: AgentSource | AgentExecutor | None = None,
        card: CardInfo | None = None,
        url: str | None = None,
        tools: Sequence[ToolSpec | SourceTool | Callable[..., Any]] = (),
        approve: Sequence[str] | Mapping[str, Approve | bool] = (),
        skills: str | PathLike[str] | Sequence[str | PathLike[str]] | SkillsExtension | None = None,
        resources: Sequence[Resource] = (),
        prompts: Sequence[Prompt] = (),
        mcp_tool: bool = False,
        middleware: Sequence[Middleware] = (),
        a2a: A2AOptions | None = None,
        mcp: MCPOptions | None = None,
        limits: Limits = Limits(),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        doors, problems = read_expose(expose)
        loaded = load_doors(doors)  # a missing extra is said before anything else
        self._held = check(
            doors=doors, loaded=loaded, problems=problems, agent=agent, card=card, url=url, tools=tools,
            approve=approve, skills=skills, resources=resources, prompts=prompts, mcp_tool=mcp_tool,
            middleware=middleware, a2a=a2a, mcp=mcp, limits=limits, clock=clock,
        )
        self._built = False
        for text in warning_texts(self._held):  # only a valid `Remote` warns; `app()` does not warn again
            warnings.warn(text, UserWarning, stacklevel=2)  # at the owner's `Remote(...)` line

    def app(self) -> ASGIApp:
        """The one ASGI app that serves every exposed door. Its own lifespan starts and stops the
        doors, so an ASGI server needs no other step. One ``Remote`` builds one app: a second
        call, or a call after one that failed, is a ``RuntimeError``."""
        if self._built:
            raise RuntimeError("one `Remote` builds one app; build a new `Remote`")
        self._built = True  # also when the build below fails: what it was given may be half used
        held = self._held
        a2a_app = mcp_app = None
        if "a2a" in held.doors:
            a2a_app = build_a2a(held.loaded["a2a"], agent=held.agent, kind=held.kind, info=held.info, url=held.url,
                                options=held.a2a, limits=held.limits, clock=held.clock)
        if "mcp" in held.doors:
            mcp_app = build_mcp(held.loaded["mcp"], tools=held.tools, approve=held.approve, skills=held.skills,
                                resources=held.resources, prompts=held.prompts, info=held.info,
                                options=held.mcp, limits=held.limits, clock=held.clock)
        if a2a_app is not None and mcp_app is not None:
            check_no_collision(a2a_app, mcp_app, held.a2a.path)
        return parent_app(a2a_app, mcp_app, held.middleware)
