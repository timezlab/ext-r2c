"""The Starlette app of an A2A remote with R2C (spec 003 research R15).

One builder puts the pieces together, so none is forgotten: the card route, the JSON-RPC route,
the activation context builder and the echo middleware (research R3), and one request handler
whose task store and executor use the same owner resolver (research R11).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Sequence

from a2a.server.agent_execution import AgentExecutor
from a2a.server.owner_resolver import OwnerResolver, resolve_user_scope
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types import AgentCard
from starlette.applications import Starlette
from starlette.middleware import Middleware

from .activation import EchoExtensions, R2CContextBuilder
from .executor import SourceExecutor

__all__ = ["a2a_app"]


def a2a_app(
    executor: AgentExecutor,
    card: AgentCard,
    *,
    task_store: TaskStore | None = None,
    owner_resolver: OwnerResolver = resolve_user_scope,
    rpc_url: str = "/",
    middleware: Sequence[Middleware] = (),
) -> Starlette:
    """The app serving ``executor`` (a ``SourceExecutor`` or any a2a-sdk executor) and ``card``.

    - ``task_store`` defaults to an ``InMemoryTaskStore`` with ``owner_resolver``; a store given
      here must use the same resolver.
    - ``middleware`` goes outside the R2C pieces, so authentication there sets the owner.
    - The request handler is ``app.state.request_handler``; it is closed when the app shuts down.
    """
    store = task_store if task_store is not None else InMemoryTaskStore(owner_resolver=owner_resolver)
    if isinstance(executor, SourceExecutor):
        executor.bind(store, owner_resolver)
    handler = DefaultRequestHandlerV2(agent_executor=executor, task_store=store, agent_card=card)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        yield
        await handler.aclose()

    app = Starlette(
        routes=[
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, rpc_url, context_builder=R2CContextBuilder()),
        ],
        middleware=[*middleware, Middleware(EchoExtensions)],
        lifespan=lifespan,
    )
    app.state.request_handler = handler
    return app
