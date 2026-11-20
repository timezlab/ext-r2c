"""Neutral run events (FR-020): what a source yields and a door reads. No A2A or MCP type here.

A run's events end with exactly one ``Done`` or one ``Error``; the driver emits ``AnswerEvent``
and the terminal event itself (research R10).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from .models import Activity, Answer, Approval, ArtifactMeta, Question, Usage

__all__ = [
    "ActivityEvent", "AnswerEvent", "ArtifactEvent", "Ask", "BytesContent", "Content", "Done", "Error",
    "ReplyChunk", "RunEvent", "TextContent", "UrlContent", "UsageEvent",
]


@dataclass(frozen=True, slots=True)
class TextContent:
    text: str
    media_type: str = "text/plain"


@dataclass(frozen=True, slots=True)
class BytesContent:
    data: bytes
    media_type: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class UrlContent:
    url: str
    media_type: str
    name: str | None = None


Content: TypeAlias = TextContent | BytesContent | UrlContent


@dataclass(frozen=True, slots=True)
class ReplyChunk:
    """The next piece of the reply; chunks concatenate in order."""

    text: str


@dataclass(frozen=True, slots=True)
class ActivityEvent:
    """A progress record; an update repeats the activity's ``id``."""

    activity: Activity


@dataclass(frozen=True, slots=True)
class Ask:
    """The run waits for an answer to ``request``."""

    request: Question | Approval


@dataclass(frozen=True, slots=True)
class AnswerEvent:
    """The answer delivered to the run (emitted by the driver)."""

    answer: Answer


@dataclass(frozen=True, slots=True)
class ArtifactEvent:
    """A file, inline content or a live page; the same ``id`` again is a new version or update."""

    id: str
    meta: ArtifactMeta
    parts: tuple[Content, ...]
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """Cumulative usage so far."""

    usage: Usage


@dataclass(frozen=True, slots=True)
class Done:
    """The run finished."""


@dataclass(frozen=True, slots=True)
class Error:
    """The run ended without finishing."""

    code: Literal["failed", "cancelled", "lost", "protocol"]
    reason: str


RunEvent: TypeAlias = ReplyChunk | ActivityEvent | Ask | AnswerEvent | ArtifactEvent | UsageEvent | Done | Error
