"""The Starlette app of an A2A remote with R2C (spec 003 research R15).

One builder puts the pieces together, so none is forgotten: the card route, the JSON-RPC route,
the activation context builder and the echo middleware (research R3), and one request handler
(``R2CRequestHandler``) whose task store and executor use the same owner resolver (research R11).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator, AsyncIterator, Sequence

from a2a.server.agent_execution import AgentExecutor
from a2a.server.context import ServerCallContext
from a2a.server.events import Event
from a2a.server.owner_resolver import OwnerResolver, resolve_user_scope
from a2a.server.request_handlers import DefaultRequestHandlerV2
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskStore
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    GetTaskRequest,
    ListTasksRequest,
    ListTasksResponse,
    Message,
    Role,
    SendMessageRequest,
    SubscribeToTaskRequest,
    Task,
)
from a2a.utils.errors import InvalidParamsError
from starlette.applications import Starlette
from starlette.middleware import Middleware

from ._codec import without_r2c
from .activation import EchoExtensions, R2CContextBuilder, is_active
from .executor import SourceExecutor

__all__ = ["R2CRequestHandler", "a2a_app"]


def _from_the_user(params: SendMessageRequest) -> None:
    """A client's message has the user's role. One with the agent's role would be stored as an
    agent message, and could put a request of its own in the task's history (research R2)."""
    if params.message.role != Role.ROLE_USER:
        raise InvalidParamsError("A client message has role ROLE_USER.")


class R2CRequestHandler(DefaultRequestHandlerV2):
    """a2a-sdk's request handler with two R2C rules it does not know:

    - a client message must have the role ``ROLE_USER``, or it is refused before it is stored;
    - a caller that did not activate R2C gets every task, message and event without the R2C
      Parts and artifact metadata written while R2C was active (R2C-ACT-3): on send, stream,
      get, list, subscribe and cancel.
    """

    async def on_message_send(self, params: SendMessageRequest, context: ServerCallContext) -> Message | Task:
        _from_the_user(params)
        result = await super().on_message_send(params, context)
        return result if is_active(context) else without_r2c(result)

    async def on_message_send_stream(self, params: SendMessageRequest,
                                     context: ServerCallContext) -> AsyncGenerator[Event, None]:
        _from_the_user(params)
        async for event in super().on_message_send_stream(params, context):
            yield event if is_active(context) else without_r2c(event)

    async def on_get_task(self, params: GetTaskRequest, context: ServerCallContext) -> Task | None:
        task = await super().on_get_task(params, context)
        return task if task is None or is_active(context) else without_r2c(task)

    async def on_list_tasks(self, params: ListTasksRequest, context: ServerCallContext) -> ListTasksResponse:
        page = await super().on_list_tasks(params, context)
        if not is_active(context):
            for task in page.tasks:
                task.CopyFrom(without_r2c(task))
        return page

    async def on_cancel_task(self, params: CancelTaskRequest, context: ServerCallContext) -> Task | None:
        task = await super().on_cancel_task(params, context)
        return task if task is None or is_active(context) else without_r2c(task)

    async def on_subscribe_to_task(self, params: SubscribeToTaskRequest,
                                   context: ServerCallContext) -> AsyncGenerator[Event, None]:
        async for event in super().on_subscribe_to_task(params, context):
            yield event if is_active(context) else without_r2c(event)


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
    handler = R2CRequestHandler(agent_executor=executor, task_store=store, agent_card=card)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:  # also when an app that composes this one throws into the lifespan (spec 007, A1)
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
