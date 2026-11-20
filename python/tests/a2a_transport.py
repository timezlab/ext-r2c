"""An in-process ASGI transport for httpx that streams the response (spec 003, research R14).

`httpx.ASGITransport` awaits the whole app before it returns the response, so a server-sent
event stream arrives in one lump at the end: a test cannot see events one by one, cannot cut a
stream halfway, and a stream that never ends (a2a-sdk's `SubscribeToTask` at input-required)
yields nothing at all. This transport runs the app in a task and hands the body over chunk by
chunk. Closing the response sends `http.disconnect` to the app, so a cut is a real disconnect.
No network port is opened. Test helper only: not shipped in the wheel.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from typing import Any

import httpx

Message = MutableMapping[str, Any]
ASGIApp = Callable[[Message, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]], Awaitable[None]]

_DONE = object()


class StreamingASGITransport(httpx.AsyncBaseTransport):
    def __init__(self, app: ASGIApp, *, client: tuple[str, int] = ("127.0.0.1", 50000)) -> None:
        self.app = app
        self.client = client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = b"".join([chunk async for chunk in request.stream])  # type: ignore[union-attr]
        scope: Message = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for k, v in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port or (443 if request.url.scheme == "https" else 80)),
            "client": self.client,
            "root_path": "",
        }
        queue: asyncio.Queue[Any] = asyncio.Queue()
        disconnected = asyncio.Event()
        body_sent = False

        async def receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            await queue.put(message)

        async def run() -> None:
            try:
                await self.app(scope, receive, send)
            except BaseException as exc:  # handed to the reader, which raises it
                await queue.put(exc)
            finally:
                await queue.put(_DONE)

        task = asyncio.get_running_loop().create_task(run())
        start = await queue.get()
        if isinstance(start, BaseException):
            raise start
        if start is _DONE or start.get("type") != "http.response.start":
            raise RuntimeError(f"the app sent no response start: {start!r}")

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                while True:
                    message = await queue.get()
                    if message is _DONE:
                        return
                    if isinstance(message, BaseException):
                        raise message
                    if message["type"] == "http.response.body":
                        if message.get("body"):
                            yield message["body"]
                        if not message.get("more_body", False):
                            return

            async def aclose(self) -> None:
                disconnected.set()
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(asyncio.shield(task), 2.0)
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task

        return httpx.Response(start["status"], headers=list(start.get("headers", [])), stream=Body())
