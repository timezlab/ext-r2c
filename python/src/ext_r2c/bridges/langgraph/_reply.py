"""The reply: hold one piece back so the last chunk can say `last` (spec 006, research R5).

A source cannot know a piece is the reply's last until the turn ends, so the newest piece of text
is held and the one before it leaves with `last=False`. The held piece leaves unmarked when the
model asks for tools, when the leg ends in an ask and when the graph raises (`flush`); at the end of
a turn it leaves with `last=True` (`end_turn`). A blank line goes before the first piece of a
different message when both have text. A message of a hidden model call (tag `nostream`) is skipped.

Pure: no graph, no queue, no model. The leg feeds it and sends what it returns.
"""

from __future__ import annotations

from typing import Any

from ext_r2c.core import ReplyChunk

__all__ = ["Reply"]

_NOTHING: Any = object()  # no message with text yet: a message id may itself be `None`
_BREAK = "\n\n"


class Reply:
    """One leg's view of the reply of a turn.

    `previous` is the id of the last message of this turn that had text, when an earlier leg (before
    a pause) already sent it: the first piece of a different message then gets the blank line.
    """

    def __init__(self, previous: Any = _NOTHING) -> None:
        self._previous = previous
        self._held: str | None = None
        self._hidden: set[str] = set()

    def hide(self, message_id: str) -> None:
        """The message of this id comes from a model call tagged `nostream`: it is not reply."""
        self._hidden.add(message_id)

    def hidden(self, message_id: str | None) -> bool:
        return message_id is not None and message_id in self._hidden

    def feed(self, text: str, message_id: str | None) -> list[ReplyChunk]:
        """The chunks to send now for a piece of a message's text (none while it is the newest)."""
        if not text or self.hidden(message_id):
            return []
        if self._previous is not _NOTHING and message_id != self._previous:
            text = _BREAK + text
        self._previous = message_id
        out = [] if self._held is None else [ReplyChunk(self._held)]
        self._held = text
        return out

    def flush(self) -> list[ReplyChunk]:
        """Send the held piece as it is, not marked last: the reply may go on."""
        if self._held is None:
            return []
        held, self._held = self._held, None
        return [ReplyChunk(held)]

    def end_turn(self, had_text: bool) -> list[ReplyChunk]:
        """Close the reply: the held piece marked last, or an empty chunk marked last when the turn
        had reply text that already left, or nothing when the turn had none."""
        if self._held is not None:
            held, self._held = self._held, None
            return [ReplyChunk(held, last=True)]
        return [ReplyChunk("", last=True)] if had_text else []
