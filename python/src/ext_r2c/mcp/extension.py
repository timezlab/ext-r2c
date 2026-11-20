"""``R2CExtension``: the MCP SDK extension that serves R2C tools (spec 004, research R1, R2).

It declares ``{"revision": 1}`` under the R2C key in ``server/discover``, lists one tool per
``ToolSpec`` or ``SourceTool`` (a stub binding, whose listed schema a server middleware puts
back to the tool's own), and serves those tools itself in ``intercept_tool_call``: the SDK never
calls the stubs, so each tool owns its ``requestState``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import mcp_types as types
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension, ToolBinding

from .. import MCP_KEY
from ..core import Limits, ToolSpec
from ._state import LostState, MemoryLedger, RoundLedger, load
from .activation import Round, form_supported, is_active, owner_of
from .source_tool import SourceTool, tool_error
from .tools import Approve, approve_first_round, approve_retry, serve_tool

__all__ = ["R2CExtension"]

DEFAULT_TTL = 600.0  # seconds: the SDK's default request-state TTL
_LOST_STATE = "The paused call could not be read; call the tool again."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stub(name: str) -> Callable[[], str]:
    def stub() -> str:  # never called: intercept_tool_call serves the tool
        raise RuntimeError(f"{name} is served by the R2C extension")

    return stub


class R2CExtension(Extension):
    """Serves ``tools`` (``ToolSpec``s and ``SourceTool``s) with R2C. Build the server with
    ``mcp_server``; a server built by hand passes ``extensions=[ext]`` and
    ``middleware=ext.middleware()``."""

    identifier = MCP_KEY

    def __init__(self, *, tools: Sequence[ToolSpec | SourceTool] = (),
                 approve: Mapping[str, Approve | bool] | None = None,
                 clock: Callable[[], datetime] | None = None, limits: Limits = Limits(),
                 ledger: RoundLedger | None = None, owner: Callable[[Any], str | None] | None = None) -> None:
        self._tools: dict[str, ToolSpec | SourceTool] = {}
        for tool in tools:
            if not isinstance(tool, (ToolSpec, SourceTool)):
                raise TypeError(f"a tool is a ToolSpec or a SourceTool, not {type(tool).__name__}")
            if tool.name in self._tools:
                raise ValueError(f"two tools are named {tool.name!r}")
            self._tools[tool.name] = tool
        self._approve: dict[str, Approve] = {}
        for name, setting in (approve or {}).items():
            if isinstance(self._tools.get(name), SourceTool):
                raise ValueError(f"{name!r} is a SourceTool: a source asks its own approvals")
            if setting is True:
                self._approve[name] = Approve()
            elif isinstance(setting, Approve):
                self._approve[name] = setting
            elif setting is not False:
                raise TypeError(f"approve[{name!r}] is an Approve or a bool, not {type(setting).__name__}")
        self.clock = clock or _now
        self.limits = limits
        self.ledger: RoundLedger = ledger if ledger is not None else MemoryLedger()
        self._owner = owner
        self.ttl = DEFAULT_TTL  # mcp_server sets the server's own

    # --- what the server consumes -------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        return {"revision": 1}

    def tools(self) -> list[ToolBinding]:
        bindings = []
        for name, tool in self._tools.items():
            kwargs: dict[str, Any] = {"name": name, "description": tool.description, "structured_output": False}
            if isinstance(tool, SourceTool) and tool.title:
                kwargs["title"] = tool.title
            bindings.append(ToolBinding(_stub(name), kwargs=kwargs))
        return bindings

    def middleware(self) -> list[Any]:
        """The server middleware that lists each tool with its own input schema."""
        return [self._list_schemas]

    async def _list_schemas(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        result = await call_next(ctx)
        if ctx.method != "tools/list" or result is None:
            return result
        data = result if isinstance(result, dict) else result.model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in data.get("tools", []):
            own = self._tools.get(tool.get("name"))
            if own is not None:
                tool["inputSchema"] = own.input_schema
        return data

    # --- serving a call -----------------------------------------------------------------------

    def _round(self, ctx: ServerRequestContext[Any, Any]) -> Round:
        owner = (self._owner(ctx) if self._owner is not None else None) or owner_of(ctx)
        token = (ctx.meta or {}).get("progress_token")
        return Round(ctx=ctx, active=is_active(ctx), form=form_supported(ctx), owner=owner, token=token,
                     clock=self.clock, limits=self.limits, ledger=self.ledger, ttl=self.ttl)

    async def intercept_tool_call(self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any],
                                  call_next: CallNext) -> HandlerResult:
        tool = self._tools.get(params.name)
        settings = self._approve.get(params.name)
        if tool is None and settings is None:
            return await call_next(ctx)
        r = self._round(ctx)
        arguments = params.arguments or {}
        point = None
        if params.request_state is not None:
            try:
                point = load(params.request_state)
            except LostState:
                return tool_error(_LOST_STATE, active=r.active)
            if point.kind != ("approve" if settings is not None else "source"):
                return tool_error(_LOST_STATE, active=r.active)
        responses = params.input_responses or {}

        if settings is not None:
            spec = tool if isinstance(tool, ToolSpec) else None
            if point is None:
                return approve_first_round(r, params.name, arguments, settings, editable=spec is not None,
                                           schema=spec.input_schema if spec is not None else None)

            async def run_tool(args: Mapping[str, Any]) -> Any:
                if spec is not None:
                    return await serve_tool(spec, r, args)
                return await call_next(ctx)  # a tool registered elsewhere: allow only, the call's own arguments

            return await approve_retry(r, point, responses, run_tool)
        if isinstance(tool, SourceTool):
            if point is None:
                return await tool.first_round(r, arguments)
            return await tool.retry(r, point, responses)
        assert isinstance(tool, ToolSpec)
        return await serve_tool(tool, r, arguments)
