"""The per-run callback handler (spec 006, research R3, R5; plan point 2).

It travels in the `config` of each call, so the graph object, its nodes and its tools are never
touched (FR-001): another caller of the same graph sees no difference. First cut: it reports which
messages come from a model call tagged `nostream`. `nostream` hides the tokens only, and the
finished message still arrives whole, so the id of that message is what keeps it out of the reply.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import ChatGeneration, LLMResult

__all__ = ["Handler", "Hidden"]

_NOSTREAM = "nostream"


@dataclass(frozen=True, slots=True)
class Hidden:
    """On the leg's queue: the message of this id was produced by a hidden model call."""

    id: str


class Handler(AsyncCallbackHandler):
    """Puts what it sees on the leg's queue, in the order it happens."""

    run_inline = True  # awaited in order, in the run's own task: a hidden id is queued before the node ends

    def __init__(self, queue: asyncio.Queue[Any]) -> None:
        self._queue = queue
        self._tags: dict[UUID, list[str]] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._tags[run_id] = list(tags or ())

    async def on_llm_end(
        self, response: LLMResult, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        if _NOSTREAM not in self._tags.pop(run_id, ()):
            return
        for generations in response.generations:
            for generation in generations:
                message_id = generation.message.id if isinstance(generation, ChatGeneration) else None
                if message_id:
                    self._queue.put_nowait(Hidden(message_id))

    async def on_llm_error(
        self, error: BaseException, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        self._tags.pop(run_id, None)
