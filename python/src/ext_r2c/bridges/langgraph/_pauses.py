"""Reading a pause from the checkpointer (spec 006, research R8; FR-014, FR-016).

A pause is what the checkpointer holds, never what the stream said: only a pending interrupt the
checkpointer lists can be resumed, so only that is offered. First cut: an interrupt whose value is a
valid hand-written R2C `question` or `approval` (what a graph that speaks R2C writes) is asked as
it is, under its own id. Every other shape comes with the middleware and the fallback question.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ext_r2c.core import Answer, Approval, InvalidObject, Question, parse

__all__ = ["Pause", "read_pauses", "resume_value"]


@dataclass(frozen=True, slots=True)
class Pause:
    """One pending interrupt, as the caller is asked about it."""

    request: Question | Approval
    interrupt_id: str


def _own_request(value: Any) -> Question | Approval | None:
    """The interrupt's value as an R2C request, when it is a valid one the caller may answer."""
    if not isinstance(value, Mapping):
        return None
    try:
        parsed = parse(value)
    except InvalidObject:
        return None
    return parsed if isinstance(parsed, (Question, Approval)) else None


def read_pauses(interrupts: Sequence[Any]) -> list[Pause]:
    """The pending interrupts the bridge can ask about, in the order the checkpointer lists them."""
    pauses: list[Pause] = []
    for interrupt in interrupts:
        request = _own_request(interrupt.value)
        if request is None:
            raise RuntimeError("this kind of pause is not supported yet")
        pauses.append(Pause(request, interrupt.id))
    return pauses


def resume_value(answer: Answer) -> dict[str, Any] | None:
    """What `interrupt()` returns inside the graph: the answer's value, or `None` when declined."""
    return None if answer.outcome == "declined" else dict(answer.value or {})
