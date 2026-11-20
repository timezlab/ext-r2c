"""``mcp_server``: an ``MCPServer`` with the R2C extension wired in (spec 004, research R1)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.request_state import RequestStateSecurity

from .extension import DEFAULT_TTL, R2CExtension

__all__ = ["mcp_server"]


def mcp_server(name: str, extension: R2CExtension, *, security: RequestStateSecurity | None = None,
               **mcp_server_kwargs: Any) -> MCPServer:
    """``MCPServer(name, extensions=[extension], middleware=extension.middleware() + middleware,
    request_state_security=security, ...)``. Without ``security`` the SDK's ephemeral policy seals
    the state: a restart then invalidates every paused call. Give fixed ``keys`` for a checkpoint
    source to resume after a restart."""
    middleware = [*extension.middleware(), *mcp_server_kwargs.pop("middleware", ())]
    server = MCPServer(name, extensions=[extension], middleware=middleware, request_state_security=security,
                       **mcp_server_kwargs)
    extension.ttl = security.ttl if security is not None else DEFAULT_TTL
    return server
