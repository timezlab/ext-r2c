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
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

__all__ = ["LostState", "MemoryLedger", "RoundLedger", "StoppingPoint", "dump", "load"]

VERSION = 1


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
