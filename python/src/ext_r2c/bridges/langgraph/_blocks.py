"""Content blocks, both ways (spec 006, research R6 and R18; FR-006, FR-012).

In: a run's input is one human message. Nothing is read, converted or dropped: the text and every
part reach the model as standard content blocks, and the graph decides what to do with them.

Out: the files a model's message holds (`image`, `audio`, `video`, `file` blocks) become artifacts.
A block that holds no data the bridge can read is skipped: the run goes on.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ext_r2c.core import ArtifactEvent, ArtifactMeta, BytesContent, Content, RunInput, TextContent, UrlContent

__all__ = ["files_of", "to_message"]

_log = logging.getLogger(__name__)

_KINDS = ("image", "audio", "video")
_FILES = (*_KINDS, "file")
_OCTETS = "application/octet-stream"


def _kind(media_type: str) -> str:
    """The block type of a media type, read by its top level whatever its case or parameters."""
    top = media_type.split(";", 1)[0].strip().lower().split("/", 1)[0]
    return top if top in _KINDS else "file"


def _block(part: Content) -> dict[str, Any]:
    if isinstance(part, TextContent):
        return {"type": "text", "text": part.text}
    block: dict[str, Any] = {"type": _kind(part.media_type), "mime_type": part.media_type}
    if isinstance(part, BytesContent):
        block["base64"] = base64.b64encode(part.data).decode("ascii")
    else:
        block["url"] = part.url
    return block


def to_message(input: RunInput) -> HumanMessage:
    """One human message: the text alone, or the text block (when there is text) and one block per part."""
    if not input.parts:
        return HumanMessage(content=input.text)
    blocks: list[dict[str, Any]] = [{"type": "text", "text": input.text}] if input.text else []
    blocks += [_block(part) for part in input.parts]
    return HumanMessage(content=blocks)  # type: ignore[arg-type]


def _name(block: dict[str, Any]) -> str | None:
    """The file's name, when the provider gave one in `extras` (a string, under `filename` or `name`)."""
    extras = block.get("extras")
    if not isinstance(extras, dict):
        return None
    for key in ("filename", "name"):
        value = extras.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _content(block: dict[str, Any], name: str | None) -> Content | None:
    """The bytes or the URL of a file block, or `None` when it holds neither (a file the provider keeps,
    or bytes that are not base64)."""
    media_type = block.get("mime_type")
    media_type = media_type if isinstance(media_type, str) and media_type else _OCTETS
    data, url = block.get("base64"), block.get("url")
    if isinstance(data, str):
        try:
            return BytesContent(base64.b64decode(data, validate=True), media_type, name)
        except (binascii.Error, ValueError):
            return None
    if isinstance(url, str) and url:
        return UrlContent(url, media_type, name)
    return None


def files_of(message: AIMessage) -> list[ArtifactEvent]:
    """One file artifact per file block of a completed message, with the id `<message id>-<position>`:
    the block's position in the message, counting the blocks that were skipped, so the same message
    always gives the same ids."""
    out: list[ArtifactEvent] = []
    for position, block in enumerate(message.content_blocks):
        if block.get("type") not in _FILES:
            continue
        name = _name(block)  # type: ignore[arg-type]
        part = _content(block, name)  # type: ignore[arg-type]
        if part is None:
            _log.debug("skipped a %s block of message %s: no data to read", block.get("type"), message.id)
            continue
        out.append(ArtifactEvent(f"{message.id}-{position}", ArtifactMeta(presentation="file"), (part,), name))
    return out
