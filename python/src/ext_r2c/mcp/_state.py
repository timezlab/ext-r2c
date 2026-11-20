"""The stopping point the door puts in ``requestState``, and the single-use round ledger (spec
004, research R3, data-model.md "Stopping point").

The door never seals, signs or encrypts the stopping point (R2C-MCP-5): the SDK's
``RequestStateBoundary`` seals it on the way out and hands it back unsealed on the retry, after
checking the tool, the arguments, the principal, the audience and the expiry. What the boundary
does not check is that a round is answered once; a ``RoundLedger`` does.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

import mcp_types as types

from ..core import (
    Answer,
    AnsweredBy,
    Approval,
    Limits,
    Problem,
    Question,
    answer_from_mcp,
    check_answer,
    check_size,
    parse,
    to_json,
)

__all__ = ["LostState", "MemoryLedger", "Outcome", "RoundLedger", "StoppingPoint", "dump", "load", "outcome"]

VERSION = 1
CLAIMED = "This request was already answered."
TOO_LATE = "The response came too late; the request had expired."
_NOT_CHECKED = ("caller_on_approval", "policy_on_approver", "expired")  # roles: O8; expiry: its own row


class LostState(ValueError):
    """A ``requestState`` the door cannot read: another format version, or not a stopping point."""


@dataclass(frozen=True)
class StoppingPoint:
    """Where a tool call paused. ``call`` stays the same in every round; ``round`` is new in each
    and is claimed once. ``request`` is the pending request's R2C JSON, as asked. The source fields
    are empty for an approval of a direct tool call."""

    call: str
    round: str
    kind: Literal["source", "approve"]
    request: dict[str, Any]
    thread: str | None = None
    context: str | None = None
    pause: Literal["checkpoint", "live"] | None = None
    usage: dict[str, Any] | None = None
    output: dict[str, Any] = field(default_factory=dict)  # {"reply": str, "blocks": [content block JSON]}
    v: int = VERSION


def dump(point: StoppingPoint) -> str:
    """Compact JSON, the plaintext the boundary seals."""
    data = {k: v for k, v in asdict(point).items() if v not in (None, {})}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def load(text: str) -> StoppingPoint:
    try:
        data = json.loads(text)
    except ValueError:
        raise LostState("the state is not JSON") from None
    if not isinstance(data, dict) or data.get("v") != VERSION:
        raise LostState("the state is not a stopping point of this version")
    try:
        point = StoppingPoint(**data)
    except TypeError:
        raise LostState("the state has missing or unknown fields") from None
    if point.kind not in ("source", "approve") or not isinstance(point.request, dict):
        raise LostState("the state is not a stopping point")
    return point


class RoundLedger(Protocol):
    """Claims a round's nonce once (research R3). ``until`` is the wall-clock time (``time.time``)
    after which the boundary refuses the state anyway, so the entry can be forgotten then. A
    deployment with several processes gives one shared ledger to every process."""

    async def claim(self, nonce: str, until: float) -> bool:
        """True the first time ``nonce`` is claimed, False after."""
        ...


class MemoryLedger:
    """The default ledger: in memory, swept on each claim. A restart empties it (documented)."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._claimed: dict[str, float] = {}

    def __len__(self) -> int:
        return len(self._claimed)

    async def claim(self, nonce: str, until: float) -> bool:
        now = self._clock()
        for old in [n for n, end in self._claimed.items() if end < now]:
            del self._claimed[old]
        if nonce in self._claimed:
            return False
        self._claimed[nonce] = until
        return True


# --- The outcome of a retry (data-model.md "Outcome of a retry", research R10) -------------------


@dataclass(frozen=True)
class Outcome:
    """What a retry comes to.

    - ``claimed``: the round was answered before; nothing happens.
    - ``missing``: no response for the pending key; ``request`` is asked again, ``refusal`` first.
    - ``expired``: ``answer`` is declined (an approval: deny); ``refusal`` goes in the next result.
    - ``reask``: ``request`` is the same request with ``errors``.
    - ``accepted``: ``answer`` is the derived answer, checked.
    """

    kind: Literal["claimed", "missing", "expired", "reask", "accepted"]
    request: Question | Approval
    answer: Answer | None = None
    refusal: str | None = None


def pending_of(point: StoppingPoint) -> Question | Approval:
    request = parse(point.request)
    if not isinstance(request, (Question, Approval)):
        raise LostState("the state holds no question or approval")
    return request


def with_errors(request: Question | Approval, problems: list[Problem]) -> Question | Approval:
    """The same request, the same id, with ``problems`` as its ``errors`` (R2C-ASK-6)."""
    data = to_json(request)
    data["errors"] = [p.as_error_item().model_dump(mode="json", exclude_none=True) for p in problems]
    again = parse(data)
    assert isinstance(again, (Question, Approval))
    return again


def _without_errors(request: Question | Approval) -> Question | Approval:
    return request.model_copy(update={"errors": None}) if request.errors else request


async def outcome(point: StoppingPoint, responses: Mapping[str, types.ElicitResult], *, ledger: RoundLedger,
                  ttl: float, now: datetime, limits: Limits) -> Outcome:
    """The row of the outcome table this retry falls in, in the order of research R10. The round
    is claimed first, so every later row happens at most once per round."""
    request = pending_of(point)
    if not await ledger.claim(point.round, until=time.time() + ttl):
        return Outcome("claimed", request)
    response = responses.get(request.id)
    if response is None:
        return Outcome("missing", request, refusal=f'No response was received for "{request.title}".')
    expires = request.expires()
    if expires is not None and now >= expires:
        late = Answer(id=request.id, outcome="declined", answered_by=AnsweredBy(role="policy"),
                      note="The request expired.")
        return Outcome("expired", request, late, TOO_LATE)
    content = response.content or {}
    too_large = check_size(text=json.dumps(content, ensure_ascii=False, default=str), limits=limits)
    if too_large is not None:
        return Outcome("reask", with_errors(request, [too_large]))
    asked = _without_errors(request)
    answer = answer_from_mcp(asked, response.action, content)
    problems = [p for p in check_answer(answer, asked, now=now, limits=limits) if p.code not in _NOT_CHECKED]
    if problems:
        return Outcome("reask", with_errors(asked, problems))
    return Outcome("accepted", asked, answer)
