"""The reply: hold one piece back so the last chunk can say `last` (spec 006, research R5).

A source cannot know a piece is the reply's last until the turn ends, so the newest piece of text
is held and the one before it leaves with `last=False`. The held piece leaves unmarked when the
model asks for tools, when the leg ends in an ask and when the graph raises (`flush`); at the end of
a turn it leaves with `last=True` (`end_turn`). A blank line goes before the first piece of a
different message when both have text. A message of a hidden model call (tag `nostream`) is skipped.

In a graph that has a `structured_response`, a message whose first word is `{` may be the structured
reply written out as text, which is not the reply to the caller when it asks for input (FR-022). Its
text is kept apart until the message's node update says which it is: `drop` when it asks, `release`
as ordinary reply text when it does not (`resolve`). Prose, which does not start with `{`, streams at once.

Pure: no graph, no queue, no model. The leg feeds it and sends what it returns.
"""

from __future__ import annotations

from typing import Any

from ext_r2c.core import ReplyChunk

__all__ = ["Reply"]

_NOTHING: Any = object()  # no message with text yet: a message id may itself be `None`
_BREAK = "\n\n"
_PROSE, _JSON = "prose", "json"


class Reply:
    """One leg's view of the reply of a turn.

    `previous` is the id of the last message of this turn that had text, when an earlier leg (before
    a pause) already sent it: the first piece of a different message then gets the blank line.
    `structured` says the graph has a `structured_response`, so a message that starts with `{` is kept apart.
    """

    def __init__(self, previous: Any = _NOTHING, *, structured: bool = False) -> None:
        self._previous = previous
        self._held: str | None = None
        self._hidden: set[str] = set()
        self._structured = structured
        self._kind: dict[Any, str] = {}  # message id → prose or json, once its first word is known
        self._kept: dict[Any, str] = {}  # message id → the text kept apart (json), or only blanks so far
        self._dropped: set[Any] = set()

    def hide(self, message_id: str) -> None:
        """The message of this id comes from a model call tagged `nostream`: it is not reply."""
        self._hidden.add(message_id)

    def hidden(self, message_id: str | None) -> bool:
        return message_id is not None and message_id in self._hidden

    def spoke(self, message: Any) -> bool:
        """Whether an AI message of the turn is reply text: it has text and is neither hidden nor dropped."""
        return bool(message.text) and not self.hidden(message.id) and message.id not in self._dropped

    def feed(self, text: str, message_id: str | None) -> list[ReplyChunk]:
        """The chunks to send now for a piece of a message's text (none while it is the newest)."""
        if not text or self.hidden(message_id):
            return []
        if self._structured:
            text = self._sort(text, message_id)
        return self._send(text, message_id)

    def _sort(self, text: str, message_id: Any) -> str:
        """What of this piece goes on as prose now: all of it for prose, none while a message that starts
        with `{` is kept apart, and nothing yet for a message that has had only blanks."""
        kind = self._kind.get(message_id)
        if kind == _PROSE:
            return text
        kept = self._kept.get(message_id, "") + text
        if kind is None and not kept.strip():
            self._kept[message_id] = kept  # blanks: the first word is not known yet
            return ""
        if kind is None:
            kind = self._kind[message_id] = _JSON if kept.lstrip().startswith("{") else _PROSE
            if kind == _PROSE:
                self._kept.pop(message_id, None)
                return kept
        self._kept[message_id] = kept
        return ""

    def resolve(self, message_id: str | None, asks: bool) -> list[ReplyChunk]:
        """The node update of a message arrived: what was kept apart is dropped when the structured reply
        asks for input, and is ordinary reply text when it does not."""
        if message_id not in self._kept:
            return []
        if asks:
            del self._kept[message_id]
            self._dropped.add(message_id)
            return []
        return self._release(message_id)

    def release_all(self) -> list[ReplyChunk]:
        """The leg ends: what is still kept apart (its node update never came) is reply text after all."""
        return [chunk for message_id in list(self._kept) for chunk in self._release(message_id)]

    def _release(self, message_id: Any) -> list[ReplyChunk]:
        self._kind[message_id] = _PROSE
        return self._send(self._kept.pop(message_id), message_id)

    def _send(self, text: str, message_id: str | None) -> list[ReplyChunk]:
        if not text:
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
