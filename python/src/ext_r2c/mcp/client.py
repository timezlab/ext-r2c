"""The caller's side of R2C over MCP, on the MCP SDK's client (spec 004 story 6, research R13,
R14, contracts/mcp-api.md "Caller side").

``R2CClient`` calls tools with R2C advertised and turns what comes back into typed items, in
wire order (data-model.md "Client items"). It drives every round itself: an input-required
result leaves the call open, and ``answer`` or ``respond`` sends the next round with the same
name and arguments and the ``requestState`` as received. It checks an answer before sending it,
never sends an approval answer as ``caller`` nor any answer as ``policy``, and fetches files from
its connection's own origin only.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, TypeAlias
from uuid import uuid4

import httpx2
import mcp_types as types
from jsonschema import Draft202012Validator
from mcp.client import Client, advertise
from mcp.client.streamable_http import streamable_http_client

from .. import MCP_KEY
from ..core import Activity, Answer, Approval, ArtifactMeta, Limits, Problem, Question, Usage, check_answer
from ._codec import ReadBlock, mcp_response, read_input_required, read_progress, read_result

__all__ = [
    "ActivityItem",
    "AnswerRejected",
    "ArtifactItem",
    "Item",
    "Link",
    "ProgressItem",
    "R2CClient",
    "ReplyItem",
    "RequestItem",
    "ResultItem",
    "TooLarge",
    "UsageItem",
    "VERSION",
]

VERSION = "2026-07-28"  # the MCP version R2C's binding is written for
_ACTIVITY_TYPES = frozenset({"tool", "step", "reasoning"})  # v1; others are skipped (R2C-CORE-6)
_DEFAULT_PORTS = {"https": 443, "http": 80}
_POLICY = "On MCP a person reviews every response, so no answer is given by policy."
_TYPED = "This request carries an R2C object: answer it with answer()."


# --- Items --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActivityItem:
    """A progress notification that carries an R2C activity."""

    activity: Activity


@dataclass(frozen=True, slots=True)
class ProgressItem:
    """A progress notification without one (or with one the client skipped)."""

    message: str | None
    progress: float


@dataclass(frozen=True, slots=True)
class RequestItem:
    """One entry of an input-required result. ``request`` is the R2C question or approval when
    the remote sent one; otherwise it is a plain elicitation, answered with ``respond``. ``url``
    is set for a URL-mode elicitation."""

    key: str
    request: Question | Approval | None
    message: str
    requested_schema: dict[str, Any] | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class UsageItem:
    usage: Usage


@dataclass(frozen=True, slots=True)
class ReplyItem:
    """The reply: the text block marked ``response``, or the first text block when no block
    carries R2C metadata."""

    text: str


@dataclass(frozen=True, slots=True)
class ArtifactItem:
    """Any other content block. ``meta`` is ``None`` without R2C; ``presentation`` is then the
    client's guess (R2C-ARTIFACT-7). ``block`` is the raw block as wire JSON."""

    meta: ArtifactMeta | None
    presentation: str
    block: dict[str, Any]
    uri: str | None = None
    media_type: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ResultItem:
    """The end of the call. ``context_id`` is ``structuredContent.context_id`` when given."""

    is_error: bool
    structured: Any
    context_id: str | None


Item: TypeAlias = ActivityItem | ProgressItem | RequestItem | UsageItem | ReplyItem | ArtifactItem | ResultItem


@dataclass(frozen=True, slots=True)
class Link:
    """A file on another origin, or a page: given back, never requested (R2C-SAFETY-1)."""

    uri: str
    media_type: str | None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class TooLarge:
    """A file over ``Limits.file_bytes``; ``size`` when it is known (R2C-SAFETY-5)."""

    size: int | None


class AnswerRejected(ValueError):
    """The answer was not sent: ``problems`` says why (FR-022)."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__("; ".join(p.message for p in problems))
        self.problems = problems


@dataclass
class _OpenCall:
    """The paused call: what the next round sends again, unchanged."""

    name: str
    arguments: dict[str, Any]
    state: str | None
    progress: bool
    responses: dict[str, types.ElicitResult] = field(default_factory=dict)


# --- Helpers ------------------------------------------------------------------------------------


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = httpx2.URL(url)
    return parsed.scheme, parsed.host, parsed.port or _DEFAULT_PORTS.get(parsed.scheme)


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)  # type: ignore[no-any-return]


def _strip(node: Any) -> tuple[Any, int]:
    """``node`` without the R2C key in any ``_meta``, and how many were removed: what a remote
    that did not declare R2C sends anyway is skipped (R2C-ACT-2)."""
    if isinstance(node, list):
        out, n = [], 0
        for value in node:
            cleaned, m = _strip(value)
            out.append(cleaned)
            n += m
        return out, n
    if not isinstance(node, dict):
        return node, 0
    result: dict[str, Any] = {}
    removed = 0
    for key, value in node.items():
        if key == "_meta" and isinstance(value, dict) and MCP_KEY in value:
            value = {k: v for k, v in value.items() if k != MCP_KEY}
            removed += 1
        cleaned, m = _strip(value)
        result[key] = cleaned
        removed += m
    return result, removed


def _decoded(data: Any) -> bytes | None:
    try:
        return base64.b64decode(str(data), validate=True)
    except (binascii.Error, ValueError):
        return None


async def _never(context: Any, params: types.ElicitRequestParams) -> types.ErrorData:
    """Declares elicitation; never answers one: the client drives every round itself (R13)."""
    return types.ErrorData(code=types.INVALID_REQUEST, message="This client answers input requests itself.")


# --- The client ---------------------------------------------------------------------------------


class R2CClient:
    """One connection to an MCP server, with R2C advertised on every request."""

    def __init__(self, url: str, http: httpx2.AsyncClient, *, limits: Limits = Limits(),
                 clock: Callable[[], datetime] | None = None, owns_http: bool = False) -> None:
        self.url = url
        self.http = http
        self.limits = limits
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.active = False
        self.pending: dict[str, RequestItem] = {}
        self.context_id: str | None = None
        self.skipped = 0
        self._owns_http = owns_http
        self._mcp: Client | None = None
        self._stack = contextlib.AsyncExitStack()
        self._open: _OpenCall | None = None
        self._running: asyncio.Task[Any] | None = None
        self._routes: dict[str | int, asyncio.Queue[dict[str, Any]]] = {}

    @classmethod
    async def connect(cls, url: str, *, http_client: httpx2.AsyncClient | None = None,
                      limits: Limits = Limits(), clock: Callable[[], datetime] | None = None,
                      client_info: types.Implementation | None = None) -> R2CClient:
        """Connect over streamable HTTP and check that the negotiated version is 2026-07-28.
        ``clock`` is the time an answer is checked against ``expires_at`` at (now, by default)."""
        http = http_client if http_client is not None else httpx2.AsyncClient()
        self = cls(url, http, limits=limits, clock=clock, owns_http=http_client is None)
        try:
            mcp = Client(streamable_http_client(url, http_client=http), extensions=[advertise(MCP_KEY, {})],
                         elicitation_callback=_never, message_handler=self._on_message,
                         client_info=client_info, cache=None)
            await self._stack.enter_async_context(mcp)
            if mcp.protocol_version != VERSION:
                raise ConnectionError(f"the server speaks MCP {mcp.protocol_version}; R2C over MCP needs {VERSION}")
            self._mcp = mcp
            self.active = MCP_KEY in (mcp.server_capabilities.extensions or {})
        except BaseException:
            await self.aclose()
            raise
        return self

    async def aclose(self) -> None:
        if self._running is not None:
            self._running.cancel()
        await self._stack.aclose()
        self._mcp = None
        if self._owns_http:
            await self.http.aclose()

    @property
    def mcp(self) -> Client:
        if self._mcp is None:
            raise RuntimeError("not connected")
        return self._mcp

    # --- Rounds ---------------------------------------------------------------------------------

    async def call(self, name: str, arguments: Mapping[str, Any] | None = None, *,
                   progress: bool = True) -> AsyncIterator[Item]:
        """Call ``name``: one round, ending with request items or a result item. A call cannot
        start while another is paused (answer or cancel it first) or running."""
        if self._open is not None or self._running is not None:
            raise RuntimeError("a call is paused or running: answer it or cancel it first")
        async for item in self._round(_OpenCall(name, dict(arguments or {}), None, progress)):
            yield item

    async def answer(self, *answers: Answer) -> AsyncIterator[Item]:
        """Answer pending R2C requests, matched by id. Each answer is checked first; a problem
        raises ``AnswerRejected`` and nothing is sent. The next round goes out once every
        pending request has a response."""
        call = self._paused()
        staged: dict[str, types.ElicitResult] = {}
        for answer in answers:
            item = next((p for p in self.pending.values() if p.request is not None and p.request.id == answer.id), None)
            if item is None or item.request is None:
                raise AnswerRejected([Problem("wrong_id", None, "This answer is for no pending request.")])
            problems = check_answer(answer, item.request, now=self.clock(), limits=self.limits)
            if answer.answered_by.role == "policy" and not any(p.code == "policy_on_approver" for p in problems):
                problems.append(Problem("invalid_answer", None, _POLICY))
            if problems:
                raise AnswerRejected(problems)
            staged[item.key] = mcp_response(item.request, answer)
        call.responses.update(staged)
        async for out in self._next(call):
            yield out

    async def respond(self, key: str, action: Literal["accept", "decline", "cancel"],
                      content: Mapping[str, Any] | None = None) -> AsyncIterator[Item]:
        """Respond to a plain elicitation (no R2C object). Accepted content is checked against
        its ``requestedSchema``; a problem raises ``AnswerRejected`` and nothing is sent."""
        call = self._paused()
        item = self.pending.get(key)
        if item is None:
            raise AnswerRejected([Problem("wrong_id", None, f"No request {key!r} is pending.")])
        if action == "accept" and item.request is not None:
            raise AnswerRejected([Problem("invalid_answer", None, _TYPED)])
        value = dict(content or {})
        if action == "accept" and item.requested_schema is not None:
            errors = sorted(Draft202012Validator(item.requested_schema).iter_errors(value), key=lambda e: list(e.path))
            if errors:
                raise AnswerRejected([Problem("invalid_value", str(e.path[0]) if e.path else None, e.message)
                                      for e in errors])
        call.responses[key] = types.ElicitResult(action=action, content=value if action == "accept" else None)
        async for out in self._next(call):
            yield out

    async def cancel(self) -> None:
        """Cancel the running round, and forget a paused call."""
        running = self._running
        if running is not None:
            running.cancel()
            await asyncio.wait({running})
        self._open = None
        self.pending = {}

    def _paused(self) -> _OpenCall:
        if self._open is None:
            raise AnswerRejected([Problem("wrong_id", None, "No request is waiting for an answer.")])
        return self._open

    async def _next(self, call: _OpenCall) -> AsyncIterator[Item]:
        if set(self.pending) - set(call.responses):
            return  # more responses to gather before the next round
        self._open = None
        self.pending = {}
        async for item in self._round(call):
            yield item

    async def _round(self, call: _OpenCall) -> AsyncIterator[Item]:
        token = uuid4().hex if call.progress else None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        if token is not None:
            self._routes[token] = queue
        task = asyncio.ensure_future(self.mcp.session.call_tool(
            call.name, call.arguments, meta={"progressToken": token} if token else None,
            input_responses=call.responses or None, request_state=call.state, allow_input_required=True,
        ))
        self._running = task
        try:
            while not task.done():
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    for item in self._progress(getter.result()):
                        yield item
                else:
                    getter.cancel()
            while not queue.empty():
                for item in self._progress(queue.get_nowait()):
                    yield item
            if task.cancelled():
                return
            result = task.result()
        finally:
            if token is not None:
                self._routes.pop(token, None)
            if not task.done():
                task.cancel()
            self._running = None
        for item in self._result(call, result):
            yield item

    # --- Reading the wire -----------------------------------------------------------------------

    async def _on_message(self, message: object) -> None:
        if not isinstance(message, types.ProgressNotification):
            return
        params = _dump(message.params)
        queue = self._routes.get(params.get("progressToken"))  # type: ignore[arg-type]
        if queue is not None:
            queue.put_nowait(params)

    def _wire(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            return data
        cleaned, removed = _strip(data)
        self.skipped += removed
        return cleaned  # type: ignore[no-any-return]

    def _progress(self, params: dict[str, Any]) -> Iterator[Item]:
        activity, text, progress, skipped = read_progress(self._wire(params))
        self.skipped += skipped
        if activity is not None and activity.type in _ACTIVITY_TYPES:
            yield ActivityItem(activity)
            return
        if activity is not None:
            self.skipped += 1
        yield ProgressItem(text, progress)

    def _result(self, call: _OpenCall, result: Any) -> Iterator[Item]:
        data = self._wire(_dump(result))
        if isinstance(result, types.InputRequiredResult):
            asked = read_input_required(data)
            self.skipped += asked.skipped
            if asked.usage is not None:
                yield UsageItem(asked.usage)
            self.pending = {p.key: RequestItem(p.key, p.request, p.message, p.requested_schema, p.url)
                            for p in asked.requests}
            self._open = _OpenCall(call.name, call.arguments, result.request_state, call.progress)
            yield from self.pending.values()
            return
        read = read_result(data)
        self.skipped += read.skipped
        if read.reply is not None:
            yield ReplyItem(read.reply)
        for block in read.artifacts:
            yield _artifact(block)
        if read.usage is not None:
            yield UsageItem(read.usage)
        structured = read.structured
        context = structured.get("context_id") if isinstance(structured, Mapping) else None
        if isinstance(context, str):
            self.context_id = context
        yield ResultItem(read.is_error, structured, context if isinstance(context, str) else None)

    # --- Fetching -------------------------------------------------------------------------------

    async def fetch(self, item: ArtifactItem) -> bytes | str | Link | TooLarge:
        """The content of an artifact (research R14):

        - an embedded resource, image or audio block from its own bytes, size-limited;
        - a resource link whose uri is not ``http(s)`` through ``resources/read`` on this
          connection;
        - an ``http(s)`` uri on this connection's origin with no redirect followed and no
          compression asked for; reading stops at ``Limits.file_bytes``;
        - any other uri, and every page (``live``, or a ``link`` guessed for html), as a ``Link``
          for the user to open.
        """
        block, limit = item.block, self.limits.file_bytes
        kind = block.get("type")
        if item.presentation in ("live", "link") and item.uri:
            return Link(item.uri, item.media_type, item.name)
        if kind == "text":
            return _sized(str(block.get("text") or ""), limit)
        if kind in ("image", "audio"):
            return _sized(_decoded(block.get("data")) or b"", limit)
        if kind == "resource":
            return _contents(block.get("resource") or {}, limit)
        if kind != "resource_link" or not item.uri:
            raise ValueError("this artifact has nothing to fetch")
        scheme = httpx2.URL(item.uri).scheme
        if scheme not in ("http", "https"):
            read = await self.mcp.read_resource(item.uri)
            if not read.contents:
                raise ValueError(f"the server has no content for {item.uri}")
            return _contents(_dump(read.contents[0]), limit)
        if _origin(item.uri) != _origin(self.url):
            return Link(item.uri, item.media_type, item.name)
        async with self.http.stream("GET", item.uri, follow_redirects=False,
                                    headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            size = int(declared) if declared and declared.isdigit() else None
            if size is not None and size > limit:
                return TooLarge(size)
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > limit:
                    return TooLarge(size)
            return bytes(body)


def _artifact(block: ReadBlock) -> ArtifactItem:
    return ArtifactItem(block.meta, block.presentation, block.block, block.uri, block.media_type, block.name)


def _sized(value: bytes | str, limit: int) -> bytes | str | TooLarge:
    size = len(value.encode("utf-8")) if isinstance(value, str) else len(value)
    return TooLarge(size) if size > limit else value


def _contents(resource: Mapping[str, Any], limit: int) -> bytes | str | TooLarge:
    """The text or the decoded blob of resource contents, size-limited."""
    if "text" in resource:
        return _sized(str(resource["text"]), limit)
    if "blob" in resource:
        data = _decoded(resource["blob"])
        if data is None:
            raise ValueError("the resource's blob is not base64")
        return _sized(data, limit)
    raise ValueError("the resource has neither text nor blob")
