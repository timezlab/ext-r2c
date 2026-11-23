"""The deployment options of each door (spec 007, D12; research R8).

Both classes are plain data and import no SDK, so they can be built with no extra installed. A
field's type is checked here (a ``TypeError``); what a value means for a ``Remote`` (a path that
collides, a keyword ``Remote`` owns) is a problem the ``Remote`` reports with its others.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from a2a.server.owner_resolver import OwnerResolver
    from a2a.server.tasks import TaskStore
    from mcp.server.request_state import RequestStateSecurity
    from mcp.server.transport_security import TransportSecuritySettings

__all__ = ["A2AOptions", "MCPOptions"]

# Keywords of `MCPServer` and of `streamable_http_app` that `Remote` sets itself: the server's name,
# version and description come from the card; the extensions, tools and resources from `Remote`'s own
# arguments; the request-state policy and the two HTTP settings from the fields of `MCPOptions`.
SERVER_OWNED: Mapping[str, str] = MappingProxyType({
    "name": "the card's name is the server's name",
    "description": "the card's description is the server's",
    "version": "the card's version is the server's",
    "extensions": "pass skills= to Remote",
    "tools": "pass tools= to Remote",
    "resources": "pass resources= to Remote",
    "request_state_security": "use the security field of MCPOptions",
})
HTTP_OWNED: Mapping[str, str] = MappingProxyType({
    "streamable_http_path": "use the path field of MCPOptions",
    "transport_security": "use the transport_security field of MCPOptions",
})
# Keywords of `MCPServer` that give the MCP door an owner of its own (D5).
OWNER_SOURCES = ("auth", "token_verifier", "auth_server_provider")


def _path(owner: str, value: Any) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{owner}.path is a str, not {type(value).__name__}")


def _keywords(owner: str, name: str, value: Any) -> Mapping[str, Any]:
    """A read-only copy of a mapping of keyword arguments."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{owner}.{name} is a mapping of keyword arguments, not {type(value).__name__}")
    for key in value:
        if not isinstance(key, str):
            raise TypeError(f"{owner}.{name} has a key that is not a str ({type(key).__name__})")
    return MappingProxyType(dict(value))


@dataclass(frozen=True, kw_only=True)
class A2AOptions:
    """How the A2A door is deployed.

    - ``task_store``: an a2a-sdk ``TaskStore``. ``None`` is the SDK's in-memory store: a restart
      then loses every paused task. A store given here must use ``owner_resolver``.
    - ``owner_resolver``: who owns a task. ``None`` is the SDK's default, the user an
      authentication middleware put on the request.
    - ``path``: the JSON-RPC endpoint. The card stays at ``/.well-known/agent-card.json`` and
      says ``url`` + ``path``.
    """

    task_store: TaskStore | None = None
    owner_resolver: OwnerResolver | None = None
    path: str = "/"

    def __post_init__(self) -> None:
        _path("A2AOptions", self.path)
        if self.owner_resolver is not None and not callable(self.owner_resolver):
            raise TypeError(f"A2AOptions.owner_resolver is a callable, not {type(self.owner_resolver).__name__}")


@dataclass(frozen=True, kw_only=True)
class MCPOptions:
    """How the MCP door is deployed.

    - ``path``: the streamable-HTTP endpoint, exactly this path.
    - ``security``: the SDK's ``RequestStateSecurity``. ``None`` is its ephemeral policy: a
      restart then invalidates every paused call. Give fixed keys to resume after one.
    - ``owner``: ``owner(ctx) -> str | None``, the owner of a call when the SDK's own
      authentication does not name one. It may read ``ctx.request.user``.
    - ``transport_security``: the SDK's host rules. Without it only ``127.0.0.1`` is served and
      any other ``Host`` is answered ``421``.
    - ``server``: other keyword arguments of ``MCPServer`` (``instructions``, ``auth``,
      ``token_verifier``, ``lifespan``, ...).
    - ``http``: other keyword arguments of ``streamable_http_app`` (``json_response``,
      ``stateless_http``, ...).
    """

    path: str = "/mcp"
    security: RequestStateSecurity | None = None
    owner: Callable[[Any], str | None] | None = None
    transport_security: TransportSecuritySettings | None = None
    server: Mapping[str, Any] = field(default_factory=dict)
    http: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _path("MCPOptions", self.path)
        if self.owner is not None and not callable(self.owner):
            raise TypeError(f"MCPOptions.owner is a callable, not {type(self.owner).__name__}")
        object.__setattr__(self, "server", _keywords("MCPOptions", "server", self.server))
        object.__setattr__(self, "http", _keywords("MCPOptions", "http", self.http))
