"""Reasoning text: read from a message and cut into readable pieces (spec 006, research R6; FR-010).

Only the standard `reasoning` field of a content block is read, so a provider's signature or its
encrypted reasoning (`extras`, `non_standard`) cannot leave (R2C-ACTIVITY-5).

The buffer has no timer (R2C-ACTIVITY-7): what leaves, and when, depends only on the text it was
given. A piece leaves at a sentence end or a newline once it holds `_SENTENCE` characters, or at the
last space before `_LIMIT` characters (at `_LIMIT` when there is no space); the rest leaves when its
message ends (`end`) or the leg stops (`drain`).

Pure: no graph, no queue, no model.
"""

from __future__ import annotations

from typing import Any

__all__ = ["Reasoning", "thoughts"]

_SENTENCE = 40  # a sentence end cuts a piece only once the piece holds this many characters
_LIMIT = 400  # a piece never holds more than about this many characters
_ENDS = ".!?"


def thoughts(message: Any) -> str:
    """The reasoning text of a message (or of a chunk of one); blocks are parts, so a blank line
    separates them. `""` when it has none: a signature with no text is not reasoning."""
    if not isinstance(message.content, list):  # a plain string holds text and nothing else
        return ""
    texts = [
        block["reasoning"]
        for block in message.content_blocks
        if block.get("type") == "reasoning" and isinstance(block.get("reasoning"), str) and block["reasoning"]
    ]
    return "\n\n".join(texts)


def _cut(text: str) -> int | None:
    """Where the first piece of `text` ends, or `None` while it should go on gathering."""
    for i, char in enumerate(text):
        through = i + 1
        if through > _LIMIT:
            break
        if through < _SENTENCE:
            continue
        if char == "\n":
            return through
        # A full stop with nothing after it yet may be a decimal point: the next character decides.
        if char in _ENDS and text[through : through + 1].isspace():
            return through + 1
    if len(text) >= _LIMIT:
        space = text.rfind(" ", 0, _LIMIT)
        return space + 1 if space >= 0 else _LIMIT
    return None


class Reasoning:
    """One buffer per message: reasoning deltas in, readable pieces out."""

    def __init__(self) -> None:
        self._buffers: dict[str | None, str] = {}

    def feed(self, message_id: str | None, delta: str) -> list[str]:
        """The pieces that are ready now, after `delta` was added to the message's buffer."""
        if not delta:
            return []
        text = self._buffers.get(message_id, "") + delta
        pieces: list[str] = []
        while (cut := _cut(text)) is not None:
            pieces.append(text[:cut])
            text = text[cut:]
        if text:
            self._buffers[message_id] = text
        else:
            self._buffers.pop(message_id, None)
        return pieces

    def end(self, message_id: str | None) -> list[str]:
        """What the message's buffer still holds, as one piece: the message has ended."""
        text = self._buffers.pop(message_id, "")
        return [text] if text else []

    def drain(self) -> list[tuple[str | None, str]]:
        """What every buffer still holds, with its message: the leg stops (a pause, the end, a failure)."""
        left = [(message_id, text) for message_id, text in self._buffers.items() if text]
        self._buffers.clear()
        return left
