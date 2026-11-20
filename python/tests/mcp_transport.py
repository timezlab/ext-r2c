"""An in-process ASGI transport for httpx2 that streams the response and records the wire (spec
004, research R15).

The MCP SDK speaks HTTP through `httpx2`, and `httpx2.ASGITransport` awaits the whole app before
it returns the response: every progress notification of a `tools/call` then arrives together
with its result, and a closed response never reaches the app as a disconnect. This transport
runs the app in its own task and hands the body over chunk by chunk; closing the response sends
`http.disconnect` to the app. No network port is opened.

With `record=[...]`, every JSON-RPC message in both directions is appended as
`("client", message)` or `("remote", message)`, in the order it crossed, parsing the SSE
`data:` frames of a streamed response. The replay compares that list with an example's steps.
Test helper only: not shipped in the wheel.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from typing import Any

import httpx2

Message = MutableMapping[str, Any]
ASGIApp = Callable[[Message, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]], Awaitable[None]]
Record = list[tuple[str, dict[str, Any]]]

_DONE = object()


def _append(record: Record | None, side: str, data: Any) -> None:
    if record is None:
        return
    for message in data if isinstance(data, list) else [data]:
        if isinstance(message, dict):
            record.append((side, message))


class _SSE:
    """Splits a streamed body into SSE events and records each `data:` payload."""

    def __init__(self, record: Record | None) -> None:
        self.record = record
        self.buffer = ""

    def feed(self, chunk: bytes) -> None:
        self.buffer += chunk.decode("utf-8").replace("\r\n", "\n")
        while "\n\n" in self.buffer:
            event, self.buffer = self.buffer.split("\n\n", 1)
            data = "\n".join(line[5:].lstrip(" ") for line in event.split("\n") if line.startswith("data:"))
            if data:
                with contextlib.suppress(ValueError):
                    _append(self.record, "remote", json.loads(data))


class StreamingASGITransport(httpx2.AsyncBaseTransport):
    def __init__(self, app: ASGIApp, *, record: Record | None = None,
                 client: tuple[str, int] = ("127.0.0.1", 50000)) -> None:
        self.app = app
        self.record = record
        self.client = client

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        body = b"".join([chunk async for chunk in request.stream])  # type: ignore[union-attr]
        if body and request.method == "POST":
            with contextlib.suppress(ValueError):
                _append(self.record, "client", json.loads(body))
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
        headers = [(bytes(k), bytes(v)) for k, v in start.get("headers", [])]
        streamed = any(k.lower() == b"content-type" and v.startswith(b"text/event-stream") for k, v in headers)
        record = self.record

        class Body(httpx2.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                sse = _SSE(record) if streamed else None
                whole = b""
                while True:
                    message = await queue.get()
                    if message is _DONE:
                        break
                    if isinstance(message, BaseException):
                        raise message
                    if message["type"] == "http.response.body":
                        chunk = message.get("body", b"")
                        if chunk:
                            if sse is not None:
                                sse.feed(chunk)
                            else:
                                whole += chunk
                            yield chunk
                        if not message.get("more_body", False):
                            break
                if sse is None and whole:
                    with contextlib.suppress(ValueError):
                        _append(record, "remote", json.loads(whole))

            async def aclose(self) -> None:
                disconnected.set()
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(asyncio.shield(task), 2.0)
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task

        return httpx2.Response(start["status"], headers=headers, stream=Body())
