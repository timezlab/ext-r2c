"""A batch in progress (spec 006, research R10, D8).

`HumanInTheLoopMiddleware` in `batched` mode wants every decision of a turn in one resume, and the
graph's state has no place for half of them. So the agent keeps the decisions given so far, here, in
memory: one record per `(thread id, interrupt id)`. It is the only state the agent keeps, it is the
bridge's alone (a restart empties it, and the batch is then asked again from its first call), and it
is bounded so abandoned batches cannot grow without limit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["LIMIT", "Batch", "Batches"]

LIMIT = 1024  # records kept; the oldest is dropped first


@dataclass(slots=True)
class Batch:
    """The decisions given so far for the calls of one batched interrupt, by position."""

    size: int
    decisions: dict[int, dict[str, Any]] = field(default_factory=dict)

    def decide(self, position: int, decision: dict[str, Any]) -> None:
        if not 0 <= position < self.size:
            raise ValueError(f"The batch has {self.size} calls: there is no position {position}.")
        self.decisions[position] = decision

    def complete(self) -> bool:
        return len(self.decisions) == self.size

    def next_open(self) -> int | None:
        """The first position with no decision, or `None` when the batch is complete."""
        return next((p for p in range(self.size) if p not in self.decisions), None)

    def ordered(self) -> list[dict[str, Any]]:
        """The decisions in position order: what the middleware reads. Only a complete batch has them."""
        if not self.complete():
            raise ValueError(f"The batch is not complete: {len(self.decisions)} of {self.size} calls are decided.")
        return [self.decisions[p] for p in range(self.size)]


class Batches:
    """The records, keyed by `(thread id, interrupt id)`; at most `LIMIT`."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], Batch] = {}  # insertion order: oldest first

    def __len__(self) -> int:
        return len(self._records)

    def get(self, thread_id: str, interrupt_id: str) -> Batch | None:
        return self._records.get((thread_id, interrupt_id))

    def record(self, thread_id: str, interrupt_id: str, *, size: int, position: int, decision: dict[str, Any]) -> Batch:
        """Add a decision to the batch of this interrupt, which is started when there is none (or
        when it was started for another size: the interrupt it belonged to is not this one)."""
        key = (thread_id, interrupt_id)
        batch = self._records.get(key)
        if batch is None or batch.size != size:
            batch = self._records[key] = Batch(size)
            while len(self._records) > LIMIT:
                del self._records[next(iter(self._records))]
        batch.decide(position, decision)
        return batch

    def drop(self, thread_id: str, interrupt_id: str) -> None:
        self._records.pop((thread_id, interrupt_id), None)

    def drop_thread(self, thread_id: str) -> None:
        for key in [k for k in self._records if k[0] == thread_id]:
            del self._records[key]

    def prune(self, thread_id: str, alive: Iterable[str]) -> None:
        """Drop the thread's records whose interrupt is no longer pending."""
        keep = set(alive)
        for key in [k for k in self._records if k[0] == thread_id and k[1] not in keep]:
            del self._records[key]
