"""A new message on a thread that has a tool call nothing answered (spec 006, research R11, R19; FR-007; D9).

The model must never see a tool call with no answer: real providers refuse such a history. So before a
new input is sent to a thread whose last step left calls open, those calls are answered here: the ones
that already ran keep their own message, the others get a message marked as an error, which is how a
rejected call reads to the model. A call waits for a person's approval (the message says it was
withdrawn), or it was left so by a run that ended on it: a tool body that asked and was abandoned, a tool
that raised, a run cancelled in the middle of a tool (the message says it did not finish).

It is one write through LangGraph's own API (`aupdate_state`). For an approval it names no writer, so it is
recorded as the step that was waiting; for any other unfinished step it names that step (see `settle`).
The new input then starts the next step. Only the calls of the AI message the
thread ends on are answered, and only on a thread whose last step did not finish (an approval waiting, or
steps still to run): a graph that ended keeps the state it ended with. A pause that holds no call of its
own (a hand-written `interrupt()` in a node) is left as LangGraph leaves it (the node starts again).
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from ._pauses import is_approval_payload

__all__ = ["UNFINISHED", "WITHDRAWN", "settle"]

WITHDRAWN = "The call was withdrawn: a new message came before it was approved."
UNFINISHED = "The call did not finish: the run that made it ended before it returned."


def _finished(state: Any) -> list[ToolMessage]:
    """The tool messages that tasks of the unfinished step already produced (`per_call`: an ungated
    call runs while another waits for its approval, and its message waits in the task's result)."""
    found: list[ToolMessage] = []
    for task in state.tasks:
        result = task.result
        if isinstance(result, dict):
            found += [m for m in result.get("messages", ()) if isinstance(m, ToolMessage)]
    return found


def _last_calls(messages: list[BaseMessage]) -> list[Any]:
    """The calls of the AI message the thread ends on; only tool messages may come after it (a history
    that goes on with anything else is already broken, and a message written now would not mend it)."""
    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            return list(message.tool_calls) if isinstance(message, AIMessage) else []
    return []


async def settle(graph: Any, thread_id: str, state: Any) -> bool:
    """Answer the calls nothing answered on `thread_id`; whether anything was written."""
    approval = any(is_approval_payload(interrupt.value) for interrupt in state.interrupts)
    unfinished = set(getattr(state, "next", ()) or ())
    if not approval and not unfinished:  # a graph that ended: what it ended with is its own
        return False
    values = state.values if isinstance(state.values, dict) else {}
    found = values.get("messages")
    messages = list(found) if isinstance(found, (list, tuple)) else []
    # The snapshot shows the finished calls' messages in `values`, but the write below starts from the saved
    # checkpoint, which does not hold them yet: they are written again (a message with the same id replaces).
    finished = _finished(state)
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)} | {m.tool_call_id for m in finished}
    text = WITHDRAWN if approval else UNFINISHED
    open_calls = [
        ToolMessage(content=text, name=call["name"], tool_call_id=call["id"], status="error")
        for call in _last_calls(messages)
        if call.get("id") and call["id"] not in answered
    ]
    update = finished + open_calls
    if not update:  # no call is open, or the calls are not in this graph's own messages (a graph inside another)
        return False
    # Without `as_node` LangGraph takes the node that wrote last, the model's, and routes on from there: the
    # model's own edge has no way back to the model and raises. A run that ended on a step names it as the
    # writer, so the thread stands where that step would have left it. (An approval is recorded by LangGraph
    # itself as the step that waited, which the tests of R11 check.)
    as_node = next(iter(unfinished)) if not approval and len(unfinished) == 1 else None
    config = {"configurable": {"thread_id": thread_id}}
    if as_node is None:
        await graph.aupdate_state(config, {"messages": update})
    else:
        await graph.aupdate_state(config, {"messages": update}, as_node=as_node)
    return True
