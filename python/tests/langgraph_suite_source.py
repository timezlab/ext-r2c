"""The real source behind the shared `AgentSource` suite (spec 006, D3 c; contracts/suite-changes.md).

`SuiteSource(saver, **options)` wraps a `LangGraphAgent` over a graph built for the options, and does
the three things the suite asks of every source that the bridge, being correct, does not do by itself:

- it records in `answers` every answer that reached `resume` (S3, S5);
- with `fail_after_ask=True` the graph's tool raises once its `interrupt()` returned (S8);
- with `double_ask=True` it yields a second `Ask` right after the first one the agent yields: a correct
  bridge asks one request at a time, so the suite's driver guard (S9) needs this to be tested at all.

A "restart" is a new `SuiteSource` over the same `saver`: a new graph and a new agent, and what the
second one knows, the checkpointer holds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from ext_r2c.core import Answer, Ask, CardInfo, RunContext, RunEvent, RunInput

from langgraph_graphs import suite_graph, wrap


class SuiteSource:
    pause = "checkpoint"

    def __init__(self, saver: Any, *, fail_after_ask: bool = False, double_ask: bool = False) -> None:
        self.saver = saver
        self.double_ask = double_ask
        self.answers: list[Answer] = []
        self._agent = wrap(suite_graph(saver, fail_after_ask=fail_after_ask))
        self.card: CardInfo = self._agent.card

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        async with aclosing(self._agent.run(input, ctx)) as events:
            async for event in events:
                yield event
                if self.double_ask and isinstance(event, Ask):
                    yield event

    async def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        self.answers.append(answer)
        async with aclosing(self._agent.resume(answer, ctx)) as events:
            async for event in events:
                yield event
