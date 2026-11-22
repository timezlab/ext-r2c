"""Usage and the turn's messages, read from the checkpoint (spec 006, research R7; FR-011).

Summing what the checkpoint holds, once per turn, gives the same total with or without a restart in
the middle of the turn. The model's name is the last one a message of the turn reported.
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


def _model_name(message: AIMessage) -> str | None:
    name = message.response_metadata.get("model_name") if isinstance(message.response_metadata, dict) else None
    return name if isinstance(name, str) and name else None


def usage_of(messages: Sequence[Any]) -> Usage | None:
    """The tokens the turn's AI messages reported and the last model name, or `None` when no message
    reported tokens (R2C-USAGE-1: an empty usage is not allowed). A field no message reported stays
    absent, not zero. A hidden call's tokens count: they were spent."""
    totals: dict[str, int] = {}
    model: str | None = None
    for message in turn_of(messages):
        if not isinstance(message, AIMessage):
            continue
        for key in ("input_tokens", "output_tokens"):
            count = _count(message.usage_metadata, key)
            if count is not None:
                totals[key] = totals.get(key, 0) + count
        model = _model_name(message) or model
    if not totals:
        return None
    # A field no message reported is left unset (a `None` given in code counts as set and is sent as `null`).
    return Usage(**totals, **({"model": model} if model else {}))
