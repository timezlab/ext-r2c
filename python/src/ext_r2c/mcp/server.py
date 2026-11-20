"""``mcp_server``: an ``MCPServer`` with the R2C extension wired in (spec 004, research R1)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.request_state import RequestStateSecurity

from .extension import R2CExtension

__all__ = ["mcp_server"]


def mcp_server(name: str, extension: R2CExtension, *, security: RequestStateSecurity | None = None,
               **mcp_server_kwargs: Any) -> MCPServer:
    """``MCPServer(name, extensions=[extension], middleware=extension.middleware() + middleware,
    request_state_security=security, ...)``. Without ``security`` the SDK's ephemeral policy seals
    the state: a restart then invalidates every paused call. Give fixed ``keys`` for a checkpoint
    source to resume after a restart.

    The extension's round ledger keeps each claim as long as the state lives, so the extension
    takes this server's TTL, and serves this one server only."""
    if extension.ttl is not None:
        raise ValueError("this R2CExtension is already served by another server")
    middleware = [*extension.middleware(), *mcp_server_kwargs.pop("middleware", ())]
    extension.ttl = (security or RequestStateSecurity.ephemeral()).ttl
    try:
        return MCPServer(name, extensions=[extension], middleware=middleware, request_state_security=security,
                         **mcp_server_kwargs)
    except BaseException:
        extension.ttl = None
        raise
