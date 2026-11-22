"""The per-run callback handler (spec 006, research R3, R5; plan point 2).

It travels in the `config` of each call, so the graph object, its nodes and its tools are never
touched (FR-001): another caller of the same graph sees no difference. It reports two things.

- Which messages come from a model call tagged `nostream`. That tag hides the tokens only, and the
  finished message still arrives whole, so the id of that message is what keeps it out of the reply.
- Each tool call as it starts and as it ends (R4). Only a tool that really starts is reported: a call
  that waits for approval, or one a person denied, never reaches here. The callbacks travel with the
  run's config, so a tool a node calls without passing its own config is seen as well.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langgraph.errors import GraphBubbleUp

__all__ = ["Handler", "Hidden", "ToolEnded", "ToolStarted"]

_NOSTREAM = "nostream"


@dataclass(frozen=True, slots=True)
class Hidden:
    """On the leg's queue: the message of this id was produced by a hidden model call."""

    id: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    """On the leg's queue: a tool's body starts. `id` is the tool call's id, or the run id when the
    tool was not called from a tool call; `args` is the call's input when it is JSON, else `None`."""

    id: str
    name: str
    args: dict[str, Any] | None
    at: float  # `time.monotonic()`, so the duration does not depend on when the leg reads the queue


@dataclass(frozen=True, slots=True)
class ToolEnded:
    """On the leg's queue: a tool's body ended, with a result or with a failure; `text` is the result's
    text, or the failure's message."""

    id: str
    failed: bool
    text: str
    at: float


def _json_args(inputs: Any) -> dict[str, Any] | None:
    """The call's input as plain JSON, or `None`: an input that is not JSON (state a tool asked to
    have injected, for one) is not something to send."""
    if not isinstance(inputs, dict):
        return None
    try:
        return json.loads(json.dumps(inputs))  # type: ignore[no-any-return]
    except (TypeError, ValueError):
        return None


class Handler(AsyncCallbackHandler):
    """Puts what it sees on the leg's queue, in the order it happens."""

    run_inline = True  # awaited in order, in the run's own task: a hidden id is queued before the node ends

    def __init__(self, queue: asyncio.Queue[Any]) -> None:
        self._queue = queue
        self._tags: dict[UUID, list[str]] = {}
        self._calls: dict[UUID, str] = {}  # the tools in their body: run id -> the id their activity has

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

    async def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        call_id = kwargs.get("tool_call_id")
        call_id = call_id if isinstance(call_id, str) and call_id else str(run_id)
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        self._calls[run_id] = call_id
        self._queue.put_nowait(ToolStarted(call_id, str(name), _json_args(inputs), time.monotonic()))

    async def on_tool_end(self, output: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any) -> None:
        call_id = self._calls.pop(run_id, None)
        if call_id is None:
            return
        failed = isinstance(output, ToolMessage) and output.status == "error"
        text = str(output.text) if isinstance(output, ToolMessage) else str(output)
        self._queue.put_nowait(ToolEnded(call_id, failed, text, time.monotonic()))

    async def on_tool_error(
        self, error: BaseException, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        call_id = self._calls.pop(run_id, None)
        if call_id is None or isinstance(error, GraphBubbleUp):
            return  # a pause inside the tool's body is not a failure: the call goes on when it is answered
        self._queue.put_nowait(ToolEnded(call_id, True, str(error), time.monotonic()))
