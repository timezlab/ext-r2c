"""Usage and the turn's messages, read from the checkpoint (spec 006, research R7; FR-011).

Summing what the checkpoint holds, once per turn, gives the same total with or without a restart in
the middle of the turn. First cut: tokens only (the model's name comes with the timeline).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ext_r2c.core import Usage

__all__ = ["turn_of", "usage_of"]


def turn_of(messages: Sequence[Any]) -> list[Any]:
    """The messages after the newest human message: the turn that is running or just ended."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return list(messages[i + 1 :])
    return list(messages)


def _count(report: Any, key: str) -> int | None:
    value = report.get(key) if isinstance(report, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def usage_of(messages: Sequence[Any]) -> Usage | None:
    """The tokens the turn's AI messages reported, or `None` when none did (R2C-USAGE-1: an empty
    usage is not allowed). A hidden call's tokens count: they were spent."""
    totals: dict[str, int] = {}
    for message in turn_of(messages):
        if not isinstance(message, AIMessage):
            continue
        for key in ("input_tokens", "output_tokens"):
            count = _count(message.usage_metadata, key)
            if count is not None:
                totals[key] = totals.get(key, 0) + count
    if not totals:
        return None
    return Usage(input_tokens=totals.get("input_tokens"), output_tokens=totals.get("output_tokens"))
