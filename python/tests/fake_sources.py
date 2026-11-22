"""Two fake agent sources that run one script and differ only in how they pause
(contracts/agent-source-suite.md "The fakes"). Both record in `answers` every answer that reached
them, so the suite can tell whether a source was resumed."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Answer,
    Approval,
    Ask,
    CardInfo,
    CardSkill,
    Question,
    ReplyChunk,
    RunContext,
    RunEvent,
    RunInput,
    Usage,
    UsageEvent,
    parse,
)

QUESTION = parse({
    "kind": "question", "id": "q-1", "title": "Report title", "answer_by": {"role": "person"},
    "fields": [{"key": "title", "header": "Title", "text": "What is the report's title?", "type": "text"}],
})
APPROVAL = parse({
    "kind": "approval", "id": "ap-1", "title": "Publish the page", "answer_by": {"role": "person"},
    "subject": {"type": "tool_call", "name": "publish_page", "args": {"page": "team/reports"}},
    "decisions": ["allow", "deny"],
})
CARD = CardInfo(
    name="Report writer", description="Writes the stock report.", version="0.0.1",
    skills=(CardSkill(id="report", name="Report", description="Writes a report.", tags=("report",)),),
)


def request_for(text: str) -> Question | Approval:
    """The scripted request: an approval when the input asks to publish, a question otherwise."""
    return APPROVAL if "publish" in text else QUESTION  # type: ignore[return-value]


def _step(state: str) -> ActivityEvent:
    return ActivityEvent(Activity.parse({"kind": "activity", "id": "step-1", "type": "step",
                                         "label": "Preparing", "state": state}))


def _reply(request: Question | Approval, answer: Answer) -> str:
    if answer.outcome == "declined":
        return "Declined"
    value: dict[str, Any] = answer.value or {}
    if isinstance(request, Question):
        return "Got: " + ", ".join(str(v) for v in value.values())
    if value["decision"] == "allow":
        return "Done"
    return f"Not done: {value.get('reason', '')}"


def _after(request: Question | Approval, answer: Answer) -> list[RunEvent]:
    return [ReplyChunk(_reply(request, answer), last=True), _step("done"), UsageEvent(Usage(output_tokens=3))]


class CheckpointFake:
    """Yields `Ask` and ends; the pending step lives in `store`, standing in for a checkpointer.
    A second instance on the same `store` is the same remote after a restart."""

    pause = "checkpoint"
    card = CARD

    def __init__(self, store: dict[str, Any], *, fail_after_ask: bool = False, double_ask: bool = False) -> None:
        self.store = store
        self.fail_after_ask = fail_after_ask
        self.double_ask = double_ask
        self.answers: list[Answer] = []

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield _step("running")
        request = request_for(input.text)
        self.store[ctx.thread_id] = request
        yield Ask(request)
        if self.double_ask:
            yield Ask(request)

    async def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        request = self.store.pop(ctx.thread_id)
        self.answers.append(answer)
        if self.fail_after_ask:
            raise RuntimeError("the agent broke")
        for event in _after(request, answer):
            yield event


class LiveFake:
    """Awaits the answer inside `run` through `ctx.ask`."""

    pause = "live"
    card = CARD

    def __init__(self, *, fail_after_ask: bool = False, double_ask: bool = False) -> None:
        self.fail_after_ask = fail_after_ask
        self.double_ask = double_ask
        self.answers: list[Answer] = []

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield _step("running")
        request = request_for(input.text)
        if self.double_ask:
            await asyncio.gather(ctx.ask(request), ctx.ask(request))
        answer = await ctx.ask(request)
        self.answers.append(answer)
        if self.fail_after_ask:
            raise RuntimeError("the agent broke")
        for event in _after(request, answer):
            yield event

    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise NotImplementedError("a live source does not resume")
