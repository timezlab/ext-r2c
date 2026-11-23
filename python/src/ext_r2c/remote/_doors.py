"""The two doors ``Remote`` composes: loading a door's package, and building each door's app from
what the door already offers (spec 007, research R6 step 2 and R8 to R10; data-model §6).

A door's package is imported inside a function and only when that door is exposed, so a ``Remote``
on one door never loads the other's SDK. Nothing here is protocol logic: every piece is a public
name of ``ext_r2c.a2a`` or ``ext_r2c.mcp``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..core import CardInfo, Limits

if TYPE_CHECKING:
    from ._classify import AgentKind
    from ._options import A2AOptions, MCPOptions

__all__ = ["Kinds", "build_a2a", "build_mcp", "kinds", "load_doors"]


@dataclass(frozen=True)
class Kinds:
    """The classes the type checks compare against. ``None`` where the door that has the class is
    not exposed: that check then waits for the door."""

    middleware: type | None = None
    source_tool: type | None = None
    approve: type | None = None
    skills: type | None = None
    resource: type | None = None
    prompt: type | None = None


def kinds(loaded: Mapping[str, Any]) -> Kinds:
    """The classes of the doors in ``loaded``. Starlette comes with either door."""
    if not loaded:
        return Kinds()
    from starlette.middleware import Middleware

    if "mcp" not in loaded:
        return Kinds(middleware=Middleware)
    from mcp.server.mcpserver.prompts import Prompt
    from mcp.server.mcpserver.resources import Resource

    door = loaded["mcp"]
    return Kinds(middleware=Middleware, source_tool=door.SourceTool, approve=door.Approve,
                 skills=door.SkillsExtension, resource=Resource, prompt=Prompt)

# The module whose import fails first when a door's extra is not installed. Any other ImportError
# is a real fault and is not turned into "install the extra".
_OF_THE_EXTRA = {
    "a2a": frozenset({"a2a", "starlette", "sse_starlette"}),
    "mcp": frozenset({"mcp", "mcp_types", "yaml"}),
}


def _load(door: str) -> Any:
    if door == "a2a":
        from .. import a2a

        return a2a
    from .. import mcp

    return mcp


def load_doors(doors: Sequence[str]) -> dict[str, Any]:
    """The package of each exposed door. A door whose extra is missing is an ``ImportError`` that
    names the extra; with both missing, one error names both."""
    loaded: dict[str, Any] = {}
    missing: dict[str, ImportError] = {}
    for door in doors:
        try:
            loaded[door] = _load(door)
        except ImportError as error:
            if (error.name or "").partition(".")[0] not in _OF_THE_EXTRA[door]:
                raise
            missing[door] = error
    if missing:
        needs = " and ".join(f'the "{door}" door needs ext-r2c[{door}]' for door in missing)
        install = " ".join(f'"ext-r2c[{door}]"' for door in missing)
        first = next(iter(missing.values()))
        raise ImportError(f"expose: {needs}, which is not installed; run: pip install {install}",
                          name=first.name) from first
    return loaded


def build_a2a(door: Any, *, agent: Any, kind: AgentKind, info: CardInfo, url: str, options: A2AOptions,
              limits: Limits, clock: Callable[[], datetime] | None) -> Any:
    """The A2A door's app: the agent behind an executor, the card at ``url`` + the door's path."""
    executor = door.SourceExecutor(agent, clock=clock, limits=limits) if kind == "source" else agent
    card = door.agent_card(info, url.rstrip("/") + options.path)
    given: dict[str, Any] = {}  # what the owner left out stays the SDK's own default
    if options.task_store is not None:
        given["task_store"] = options.task_store
    if options.owner_resolver is not None:
        given["owner_resolver"] = options.owner_resolver
    return door.a2a_app(executor, card, rpc_url=options.path, **given)


def build_mcp(door: Any, *, tools: Sequence[Any], approve: Mapping[str, Any], info: CardInfo, options: MCPOptions,
              limits: Limits, clock: Callable[[], datetime] | None) -> Any:
    """The MCP door's app: the tools behind the R2C extension, in a server named by the card."""
    extension = door.R2CExtension(tools=tools, approve=approve, clock=clock, limits=limits, owner=options.owner)
    server = door.mcp_server(info.name, extension, security=options.security, version=info.version,
                             description=info.description, **options.server)
    return server.streamable_http_app(streamable_http_path=options.path,
                                      transport_security=options.transport_security, **options.http)
