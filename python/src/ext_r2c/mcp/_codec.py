"""R2C ⇄ MCP: input-required results, the elicitation message, progress notifications, content
blocks, and an answer turned into an elicitation response (spec 004, research R7–R9, R13,
contracts/wire-mapping.md).

Writing builds `mcp_types` models, R2C objects always through the core's ``to_json``; reading
takes wire JSON (a dict) and parses R2C objects with the core's ``parse``. An unknown kind or an
object its schema rejects is skipped and counted, never raised (R2C-CORE-5, R2C-CORE-6).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

import mcp_types as types

from .. import MCP_KEY
from ..core import (
    Activity,
    Answer,
    Approval,
    ArtifactEvent,
    ArtifactMeta,
    Content,
    InvalidObject,
    Limits,
    Problem,
    Question,
    TextContent,
    Unknown,
    UrlContent,
    Usage,
    check_size,
    mcp_form,
    parse,
    to_json,
)

__all__ = [
    "Asked", "Block", "Pending", "ReadBlock", "ReadResult", "content_blocks", "final_result", "input_required",
    "mcp_response", "message", "output_too_large", "progress_params", "read_block", "read_input_required",
    "read_progress", "read_result", "reply_block", "strip",
]

Block: TypeAlias = (
    types.TextContent | types.ImageContent | types.AudioContent | types.ResourceLink | types.EmbeddedResource
)
Presentation: TypeAlias = Literal["file", "inline", "live", "link"]

_REPLY_META = ArtifactMeta(presentation="inline", response=True)
_URN = "urn:r2c:artifact:"


# --- Reading R2C objects -------------------------------------------------------------------------


def _r2c(meta: Any) -> Any:
    """The value under the R2C key of a `_meta`, or ``None``."""
    return meta.get(MCP_KEY) if isinstance(meta, Mapping) else None


def _read(obj: Any, kinds: tuple[type, ...]) -> tuple[Any, int]:
    """(model, skipped): the parsed object when it is one of ``kinds``, else ``None`` and 1."""
    if obj is None:
        return None, 0
    try:
        found = parse(obj)
    except InvalidObject:
        return None, 1
    if isinstance(found, Unknown) or not isinstance(found, kinds):
        return None, 1
    return found, 0


# --- The elicitation message (research R7) -------------------------------------------------------


def message(request: Question | Approval, *, refusal: str | None = None) -> str:
    """The refusal sentence, ``[<origin.name> asks: ]<title>``, the description, one line per error."""
    lines = [refusal] if refusal else []
    lines.append(f"{request.origin.name} asks: {request.title}" if request.origin else request.title)
    if request.description:
        lines.append(request.description)
    lines.extend(e.message for e in request.errors or [])
    return "\n".join(lines)


# --- Input-required results ----------------------------------------------------------------------


def input_required(request: Question | Approval, state: str, *, active: bool, usage: Usage | None,
                   refusal: str | None = None) -> types.InputRequiredResult:
    """One form elicitation keyed by the request's id (O4); the R2C object, and the usage so far,
    in ``_meta`` when active (R2C-MCP-1, O6). ``NotAskableOverMcp`` when no form can ask it."""
    form = types.ElicitRequestFormParams(message=message(request, refusal=refusal),
                                         requested_schema=mcp_form(request).requested_schema)
    meta: dict[str, Any] | None = None
    if active:
        value: dict[str, Any] = {"input_requests": {request.id: to_json(request)}}
        if usage is not None:
            value["usage"] = to_json(usage)
        meta = {MCP_KEY: value}
    return types.InputRequiredResult(input_requests={request.id: types.ElicitRequest(params=form)},
                                     request_state=state, _meta=meta)


@dataclass(frozen=True)
class Pending:
    """One entry of ``inputRequests``: ``request`` is the R2C object, or ``None`` when none came."""

    key: str
    request: Question | Approval | None
    message: str
    requested_schema: dict[str, Any] | None
    url: str | None
    method: str


@dataclass(frozen=True)
class Asked:
    requests: list[Pending]
    usage: Usage | None
    skipped: int


def read_input_required(result: Mapping[str, Any]) -> Asked:
    meta = _r2c(result.get("_meta"))
    objects = meta.get("input_requests") if isinstance(meta, Mapping) else None
    objects = objects if isinstance(objects, Mapping) else {}
    skipped = 0
    usage, n = _read(meta.get("usage") if isinstance(meta, Mapping) else None, (Usage,))
    skipped += n
    requests: list[Pending] = []
    for key, entry in (result.get("inputRequests") or {}).items():
        params = entry.get("params") if isinstance(entry, Mapping) else None
        params = params if isinstance(params, Mapping) else {}
        request, n = _read(objects.get(key), (Question, Approval))
        skipped += n
        if request is not None and request.id != key:
            request, skipped = None, skipped + 1
        schema = params.get("requestedSchema")
        requests.append(Pending(
            key=key, request=request, message=str(params.get("message") or ""),
            requested_schema=dict(schema) if isinstance(schema, Mapping) else None,
            url=params.get("url") if params.get("mode") == "url" else None,
            method=str(entry.get("method") or "") if isinstance(entry, Mapping) else "",
        ))
    return Asked(requests, usage, skipped)


# --- Progress (research R8) ----------------------------------------------------------------------


def progress_params(activity: Activity, token: str | int, n: int, *, active: bool) -> types.ProgressNotificationParams:
    """The ``n``-th progress of a request: the label as ``message``, the activity in ``_meta``."""
    return types.ProgressNotificationParams(progress_token=token, progress=n, message=activity.label,
                                            _meta={MCP_KEY: to_json(activity)} if active else None)


def read_progress(params: Mapping[str, Any]) -> tuple[Activity | None, str | None, float, int]:
    """(activity, message, progress, skipped) of a progress notification's params."""
    activity, skipped = _read(_r2c(params.get("_meta")), (Activity,))
    text = params.get("message")
    progress = params.get("progress")
    return activity, text if isinstance(text, str) else None, float(progress or 0), skipped


# --- Content blocks (research R9, O7) ------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _name(event: ArtifactEvent, content: Content) -> str:
    named = getattr(content, "name", None) or event.name
    if named:
        return named
    if isinstance(content, UrlContent):
        tail = content.url.rstrip("/").rsplit("/", 1)[-1]
        if tail:
            return tail
    return event.id


def _block(event: ArtifactEvent, content: Content, meta: dict[str, Any] | None) -> Block:
    presentation = event.meta.presentation
    urn = f"{_URN}{event.id}"
    if isinstance(content, UrlContent):
        return types.ResourceLink(uri=content.url, name=_name(event, content), mime_type=content.media_type, _meta=meta)
    if isinstance(content, TextContent):
        if presentation == "inline":
            return types.TextContent(type="text", text=content.text, _meta=meta)
        resource: Any = types.TextResourceContents(uri=urn, mime_type=content.media_type, text=content.text)
        return types.EmbeddedResource(type="resource", resource=resource, _meta=meta)
    media = content.media_type
    if presentation == "inline" and media.startswith("image/"):
        return types.ImageContent(type="image", data=_b64(content.data), mime_type=media, _meta=meta)
    if presentation == "inline" and media.startswith("audio/"):
        return types.AudioContent(type="audio", data=_b64(content.data), mime_type=media, _meta=meta)
    blob = types.BlobResourceContents(uri=urn, mime_type=media, blob=_b64(content.data))
    return types.EmbeddedResource(type="resource", resource=blob, _meta=meta)


def content_blocks(event: ArtifactEvent, *, active: bool) -> list[Block]:
    """One block per part, each with the artifact's metadata in ``_meta`` when active (R2C-MCP-7)."""
    meta = {MCP_KEY: to_json(event.meta)} if active else None
    return [_block(event, content, meta) for content in event.parts]


def reply_block(text: str, *, active: bool) -> types.TextContent:
    return types.TextContent(type="text", text=text, _meta={MCP_KEY: to_json(_REPLY_META)} if active else None)


def strip(blocks: Iterable[Block]) -> list[Block]:
    """The blocks without the R2C key in their ``_meta``, for a round that is not active."""
    out: list[Block] = []
    for block in blocks:
        meta = {k: v for k, v in (block.meta or {}).items() if k != MCP_KEY} or None
        out.append(block.model_copy(update={"meta": meta}))
    return out


def output_too_large(reply: str, blocks: Sequence[Block], limits: Limits) -> Problem | None:
    """``too_large`` when the gathered reply and blocks together pass the message limit (FR-014)."""
    encoded = json.dumps([b.model_dump(mode="json", by_alias=True, exclude_none=True) for b in blocks])
    return check_size(text=reply + encoded, limits=limits)


def final_result(*, reply: str, blocks: Sequence[Block], usage: Usage | None, active: bool,
                 refusal: str | None = None, is_error: bool = False, structured: Any = None) -> types.CallToolResult:
    """The complete result: the refusal sentence, the reply, the artifacts; usage in ``_meta``."""
    content: list[Any] = []
    if refusal:
        content.append(types.TextContent(type="text", text=refusal))
    if reply:
        content.append(reply_block(reply, active=active))
    content.extend(blocks if active else strip(blocks))
    meta = {MCP_KEY: to_json(usage)} if active and usage is not None else None
    return types.CallToolResult(content=content, is_error=is_error, structured_content=structured, _meta=meta)


@dataclass(frozen=True)
class ReadBlock:
    """A content block read back: its R2C metadata (or ``None``) and what a caller fetches."""

    meta: ArtifactMeta | None
    presentation: Presentation
    block: dict[str, Any]
    uri: str | None
    media_type: str | None
    name: str | None
    skipped: int = 0


def read_block(block: Mapping[str, Any]) -> ReadBlock:
    meta, skipped = _read(_r2c(block.get("_meta")), (ArtifactMeta,))
    kind = block.get("type")
    resource = block.get("resource") if isinstance(block.get("resource"), Mapping) else {}
    if kind == "resource_link":
        uri, media = block.get("uri"), block.get("mimeType")
    elif kind == "resource":
        uri, media = resource.get("uri"), resource.get("mimeType")
    else:
        uri, media = None, block.get("mimeType") if kind in ("image", "audio") else None
    if meta is not None:
        presentation: Presentation = meta.presentation
    elif kind == "resource_link" and isinstance(media, str) and media.startswith("text/html"):
        presentation = "link"
    elif kind in ("resource_link", "resource"):
        presentation = "file"
    else:
        presentation = "inline"
    name = block.get("name") if kind == "resource_link" else None
    return ReadBlock(meta, presentation, dict(block), uri if isinstance(uri, str) else None,
                     media if isinstance(media, str) else None, name if isinstance(name, str) else None, skipped)


@dataclass(frozen=True)
class ReadResult:
    reply: str | None
    artifacts: list[ReadBlock]
    usage: Usage | None
    structured: Any
    is_error: bool
    skipped: int
    texts: list[str] = field(default_factory=list)


def read_result(result: Mapping[str, Any]) -> ReadResult:
    """The reply (the block marked ``response``, or the first text block when no block carries R2C
    metadata), the other blocks as artifacts, and the usage of a complete result."""
    usage, skipped = _read(_r2c(result.get("_meta")), (Usage,))
    blocks = [b for b in result.get("content") or [] if isinstance(b, Mapping)]
    read = [read_block(b) for b in blocks]
    skipped += sum(r.skipped for r in read)
    marked = any(_r2c(b.get("_meta")) is not None for b in blocks)
    reply: str | None = None
    artifacts: list[ReadBlock] = []
    for item in read:
        is_text = item.block.get("type") == "text"
        if reply is None and is_text and (item.meta is not None and item.meta.response or not marked):
            reply = str(item.block.get("text") or "")
        else:
            artifacts.append(item)
    return ReadResult(reply, artifacts, usage, result.get("structuredContent"), bool(result.get("isError")), skipped,
                      [str(b.get("text")) for b in blocks if b.get("type") == "text"])


# --- An answer as an elicitation response (the inverse of answer_from_mcp) -------------------------


def mcp_response(request: Question | Approval, answer: Answer) -> types.ElicitResult:
    """The response a client sends for ``answer``: declined → ``decline``; a `one` value not among
    the options goes in ``<key>_other``; `many` values not among them are joined into it."""
    if answer.outcome == "declined":
        return types.ElicitResult(action="decline")
    value = answer.value or {}
    content: dict[str, Any] = {}
    if isinstance(request, Question):
        for f in request.fields:
            if f.key not in value:
                continue
            given = value[f.key]
            labels = [o.label for o in f.options or []]
            if f.type == "one" and f.other and isinstance(given, str) and given not in labels:
                content[f"{f.key}_other"] = given
            elif f.type == "many" and f.other and isinstance(given, list):
                listed = [v for v in given if v in labels]
                extra = [v for v in given if v not in labels]
                content[f.key] = listed
                if extra:
                    content[f"{f.key}_other"] = ", ".join(str(v) for v in extra)
            else:
                content[f.key] = given
    else:
        content["decision"] = value.get("decision")
        if value.get("reason"):
            content["reason"] = value["reason"]
        if value.get("decision") == "edit":
            content.update(value.get("args") or {})
    return types.ElicitResult(action="accept", content=content)
