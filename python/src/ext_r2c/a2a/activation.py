"""Activation of R2C on a request, and the echoed header (R2C-ACT-2, spec 003 research R3).

R2C is **active** on a request when its ``A2A-Extensions`` header lists ``ext_r2c.URI``. The
decision is taken from the request alone, before the executor runs:

- ``R2CContextBuilder`` stores it in the call context's ``state``;
- ``EchoExtensions`` adds ``A2A-Extensions: <uri>`` to the response, since a2a-sdk writes no
  such header itself;
- ``is_active`` reads it back for an executor.

``a2a_app`` installs both, so a remote cannot forget one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

from a2a.extensions.common import HTTP_EXTENSION_HEADER, get_requested_extensions
from a2a.server.agent_execution import RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import DefaultServerCallContextBuilder
from starlette.requests import Request

from .. import URI

__all__ = ["EchoExtensions", "R2CContextBuilder", "is_active"]

_STATE_KEY = "ext_r2c.active"
_HEADER = HTTP_EXTENSION_HEADER.lower().encode("latin-1")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def _requested(values: Iterable[str]) -> bool:
    return URI in get_requested_extensions(list(values))


class R2CContextBuilder(DefaultServerCallContextBuilder):
    """The default call context, plus whether R2C is active on this request."""

    def build(self, request: Request) -> ServerCallContext:
        context = super().build(request)
        context.state[_STATE_KEY] = URI in context.requested_extensions
        return context


def is_active(context: RequestContext | ServerCallContext) -> bool:
    """Whether R2C is active on the request behind ``context``."""
    call = context.call_context if isinstance(context, RequestContext) else context
    if _STATE_KEY in call.state:
        return bool(call.state[_STATE_KEY])
    return URI in call.requested_extensions


class EchoExtensions:
    """Pure ASGI middleware: echoes ``A2A-Extensions: <uri>`` on a response to a request that
    activated R2C."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        values = [v.decode("latin-1") for k, v in scope.get("headers", []) if k.lower() == _HEADER]
        if not _requested(values):
            await self.app(scope, receive, send)
            return

        async def echo(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER]
                headers.append((_HEADER, URI.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, echo)
