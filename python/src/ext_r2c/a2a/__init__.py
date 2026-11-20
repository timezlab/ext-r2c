"""The A2A door of R2C, on a2a-sdk (install the ``[a2a]`` extra).

Remote side: ``SourceExecutor`` serves an ``ext_r2c.core.AgentSource``; ``R2CTask`` helps a
hand-written a2a-sdk executor speak R2C; ``agent_card`` and ``a2a_app`` assemble the card and
the app. Caller side: ``R2CClient``. See ``specs/003-a2a-binding/contracts/a2a-api.md``.
"""

from __future__ import annotations

from ._codec import answer_text
from .activation import EchoExtensions, R2CContextBuilder, is_active
from .app import R2CRequestHandler, a2a_app
from .card import agent_card
from .client import (
    ActivityItem,
    AnswerRejected,
    ArtifactItem,
    Item,
    Link,
    R2CClient,
    ReplyItem,
    RequestItem,
    StatusItem,
    TaskItem,
    TooLarge,
    UsageItem,
)
from .executor import SourceExecutor
from .task import ContentTooLarge, PendingMemory, R2CTask

__all__ = [
    "ActivityItem",
    "AnswerRejected",
    "ArtifactItem",
    "ContentTooLarge",
    "EchoExtensions",
    "Item",
    "Link",
    "PendingMemory",
    "R2CClient",
    "R2CContextBuilder",
    "R2CRequestHandler",
    "R2CTask",
    "ReplyItem",
    "RequestItem",
    "SourceExecutor",
    "StatusItem",
    "TaskItem",
    "TooLarge",
    "UsageItem",
    "a2a_app",
    "agent_card",
    "answer_text",
    "is_active",
]
