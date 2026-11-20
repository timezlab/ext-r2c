"""The test bed streams: a client sees an event before the server has sent the next one
(spec 003, research R14). Without this, no cut-and-reattach test means anything."""

from __future__ import annotations

import asyncio

from a2a.helpers.proto_helpers import new_task_from_user_message, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types.a2a_pb2 import Message, Part, Role, SendMessageRequest, TaskState
from a2a_harness import a2a_client, plain_card, run, serve


class Paced(AgentExecutor):
    """Sends one working status, waits until the test has seen it, then sends two more."""

    def __init__(self) -> None:
        self.seen_first = asyncio.Event()
        self.waited_in_vain = False

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        assert context.message is not None
        await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        for i in range(3):
            await updater.update_status(TaskState.TASK_STATE_WORKING, new_text_message(f"step {i}"))
            if i == 0:
                try:
                    await asyncio.wait_for(self.seen_first.wait(), 2.0)
                except TimeoutError:
                    self.waited_in_vain = True
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def test_transport_streams_event_by_event() -> None:
    async def go() -> list[str]:
        executor = Paced()
        states: list[str] = []
        async with serve(executor, plain_card()) as served, a2a_client(served) as tc:
            request = SendMessageRequest(message=Message(message_id="m-1", role=Role.ROLE_USER,
                                                         parts=[Part(text="Start.")]))
            async for event in tc.client.send_message(request):
                if event.HasField("status_update"):
                    states.append(TaskState.Name(event.status_update.status.state))
                    parts = event.status_update.status.message.parts
                    if parts and parts[0].text == "step 0":
                        executor.seen_first.set()
        assert not executor.waited_in_vain, "the first status arrived only after the server went on"
        return states

    assert run(go()) == ["TASK_STATE_WORKING"] * 3 + ["TASK_STATE_COMPLETED"]
