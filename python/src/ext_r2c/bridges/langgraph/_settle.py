"""A new message on a thread that waits for an approval (spec 006, research R11; FR-007; D9).

The model must never see a tool call with no answer: real providers refuse such a history. So before a
new input is sent to a thread whose last step is an approval waiting for a person, the calls of that
step are answered here: the ones that already ran keep their own message, the others get a message that
says the call was withdrawn, marked as an error, which is how a rejected call reads to the model.

It is one write through LangGraph's own API (`aupdate_state`), with no `as_node`, so it is recorded as
the step that was waiting; the new input then starts the next step. Only an approval of the middleware
is settled: any other kind of pause is left as LangGraph leaves it (the node starts again).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from ._pauses import is_approval_payload

__all__ = ["WITHDRAWN", "settle"]

WITHDRAWN = "The call was withdrawn: a new message came before it was approved."


def _finished(state: Any) -> list[ToolMessage]:
    """The tool messages that tasks of the unfinished step already produced (`per_call`: an ungated
    call runs while another waits for its approval, and its message waits in the task's result)."""
    found: list[ToolMessage] = []
    for task in state.tasks:
        result = task.result
        if isinstance(result, dict):
            found += [m for m in result.get("messages", ()) if isinstance(m, ToolMessage)]
    return found


async def settle(graph: Any, thread_id: str, state: Any) -> bool:
    """Answer the calls of an approval that waits on `thread_id`; whether anything was written."""
    if not any(is_approval_payload(interrupt.value) for interrupt in state.interrupts):
        return False
    values = state.values if isinstance(state.values, dict) else {}
    found = values.get("messages")
    messages = list(found) if isinstance(found, (list, tuple)) else []
    # The snapshot shows the finished calls' messages in `values`, but the write below starts from the saved
    # checkpoint, which does not hold them yet: they are written again (a message with the same id replaces).
    finished = _finished(state)
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)} | {m.tool_call_id for m in finished}
    last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
    withdrawn = [
        ToolMessage(content=WITHDRAWN, name=call["name"], tool_call_id=call["id"], status="error")
        for call in (last_ai.tool_calls if last_ai is not None else ())
        if call.get("id") and call["id"] not in answered
    ]
    update = finished + withdrawn
    if not update:  # the calls are not in this graph's own messages (a graph inside another): nothing to answer
        return False
    await graph.aupdate_state({"configurable": {"thread_id": thread_id}}, {"messages": update})
    return True
