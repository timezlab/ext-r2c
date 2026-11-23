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

# Keywords of `MCPServer`, of `mcp_server` and of `streamable_http_app` that `Remote` takes out of the
# owner's hands: the server's name, version and description come from the card; the extensions, tools and
# resources from `Remote`'s own arguments; the request-state policy and the HTTP settings from the fields of
# `MCPOptions`. `security` and `extension` are the keywords of `mcp_server` itself (a second value for
# either one is a `TypeError` from the SDK, so it is a problem here); `host` is no collision, but the SDK
# keeps its host guard only for a loopback `host`, so a bind address given here would turn it off in silence.
SERVER_OWNED: Mapping[str, str] = MappingProxyType({
    "name": "leave it out, the card's name is the server's",
    "description": "leave it out, the card's description is the server's",
    "version": "leave it out, the card's version is the server's",
    "extensions": "pass skills= to Remote",
    "tools": "pass tools= to Remote",
    "resources": "pass resources= to Remote",
    "request_state_security": "use the security field of MCPOptions",
    "security": "use the security field of MCPOptions",
    "extension": "leave it out, Remote builds R2C's own extension",
})
HTTP_OWNED: Mapping[str, str] = MappingProxyType({
    "streamable_http_path": "use the path field of MCPOptions",
    "transport_security": "use the transport_security field of MCPOptions",
    "host": "the server that runs this app binds the address; name the hosts it answers to in the "
            "transport_security field of MCPOptions",
})
# Keywords of `MCPServer` that give the MCP door an owner of its own (D5).
OWNER_SOURCES = ("auth", "token_verifier", "auth_server_provider")
_WELL_KNOWN = "/.well-known"


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
    - ``owner``: ``owner(ctx) -> str | None``, the owner of a call. It is asked first: an owner it
      names wins over the SDK's authenticated principal, and ``None`` leaves the principal (or
      ``anonymous`` when the SDK authenticates nobody). So with the SDK's authentication on, a
      callable that returns something other than the verified user replaces it. It may read
      ``ctx.request.user``.
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


def path_problems(a2a: A2AOptions | None, mcp: MCPOptions | None) -> list[str]:
    """What is wrong with the paths of the exposed doors (``None`` is a door that is not exposed).
    A path begins with ``/`` and is not under ``/.well-known/``, and the two differ. No problem says
    a path back: it is this host's own. A route an SDK adds is checked when the app is built."""
    problems = []
    for name, options in (("a2a.path", a2a), ("mcp.path", mcp)):
        if options is None:
            continue
        if not options.path.startswith("/"):
            problems.append(f"{name}: does not begin with /; begin the path with /")
        elif options.path == _WELL_KNOWN or options.path.startswith(_WELL_KNOWN + "/"):
            problems.append(f"{name}: is under /.well-known/, where the card and other well-known documents "
                            "are served; give another path")
    if a2a is not None and mcp is not None and a2a.path == mcp.path:
        problems.append("a2a.path: is the same path as mcp.path; give the two doors different paths")
    return problems


def owned_key_problems(mcp: MCPOptions) -> list[str]:
    """One problem for each keyword in ``server`` or ``http`` that ``Remote`` takes out of the owner's hands."""
    return [
        f"mcp.{field_name}: names {key}, a keyword Remote does not take from here; {to_do}"
        for field_name, given, owned in (("server", mcp.server, SERVER_OWNED), ("http", mcp.http, HTTP_OWNED))
        for key, to_do in owned.items() if key in given
    ]
