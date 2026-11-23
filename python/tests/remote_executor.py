"""A hand-written a2a-sdk executor that has never heard of R2C (spec 007, US6). Test helper only: not
shipped in the wheel.

It has the shape of the official Currency sample of the A2A samples: an agent object whose
`stream(query, context_id)` yields `{"is_task_complete", "require_user_input", "content"}`, and an
`AgentExecutor` that turns each of them into a status update, a plain-text `input-required` or an
artifact and a completed task. A scripted pure function stands in the place of the model, so a run is
the same every time.

This module imports the a2a-sdk only. A test reads its source to prove that it imports nothing of the
R2C SDK: what `Remote` serves here is an executor written before R2C existed.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Part, TaskState
from a2a.utils.errors import UnsupportedOperationError

LOOKING = "Reading the length..."
WHICH_UNIT = "Which unit do you want the length in: m or cm?"
RESULT = "conversion_result"
_PER_KM = {"m": 1000, "cm": 100_000}


def model(said: Sequence[str]) -> dict[str, Any]:
    """What the "model" says to everything the caller said so far in one context: a pure function.

    The first message names a length in km; the last one may name the unit asked for."""
    found = re.search(r"\d+", said[0])
    km = int(found.group()) if found else 0
    unit = next((word for word in re.findall(r"[a-z]+", said[-1].lower()) if word in _PER_KM), None)
    if unit is None:
        return {"is_task_complete": False, "require_user_input": True, "content": WHICH_UNIT}
    return {"is_task_complete": True, "require_user_input": False, "content": f"{km} km is {km * _PER_KM[unit]} {unit}."}


class ConverterAgent:
    """The agent the executor drives: it keeps what was said in each context, as a framework would."""

    def __init__(self) -> None:
        self.said: dict[str, list[str]] = {}

    async def stream(self, query: str, context_id: str) -> AsyncIterator[dict[str, Any]]:
        said = self.said.setdefault(context_id, [])
        said.append(query)
        yield {"is_task_complete": False, "require_user_input": False, "content": LOOKING}
        yield model(said)


class ConverterExecutor(AgentExecutor):
    """The executor of the sample: a status update while working, a plain-text question with an
    `input-required` status, an artifact and a completed task at the end."""

    def __init__(self) -> None:
        self.agent = ConverterAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input()
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        async for item in self.agent.stream(query, task.context_id):
            said = updater.new_agent_message([Part(text=item["content"])])
            if item["require_user_input"]:
                await updater.update_status(TaskState.TASK_STATE_INPUT_REQUIRED, said)
                break
            if item["is_task_complete"]:
                await updater.add_artifact([Part(text=item["content"])], name=RESULT)
                await updater.complete()
                break
            await updater.update_status(TaskState.TASK_STATE_WORKING, said)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()
