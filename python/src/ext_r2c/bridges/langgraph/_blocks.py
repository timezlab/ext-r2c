"""A run's input as one human message (spec 006, research R18; FR-006).

Nothing is read, converted or dropped: the text and every part reach the model as standard content
blocks, and the graph decides what to do with them.
"""

from __future__ import annotations

import base64
from typing import Any

from langchain_core.messages import HumanMessage

from ext_r2c.core import BytesContent, Content, RunInput, TextContent

__all__ = ["to_message"]

_KINDS = ("image", "audio", "video")


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
