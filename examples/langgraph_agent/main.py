"""Run both agents in this process and talk to them as the person at the keyboard.

    python main.py           # you answer the question and the approval
    python main.py --auto    # a scripted person answers: month 2026-10, then allow

Two things happen. First you talk to the reporter directly: it asks you a question, then asks you to
approve publishing the page. Then you talk to the planner, which asks the reporter for the same
report: the reporter's question is answered by the planner, its approval is declined by a rule, and
the two agents call each other without you.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import uvicorn

from ext_r2c.a2a import ActivityItem, Item, RequestItem, UsageItem
from ext_r2c.core import Answer, AnsweredBy, Approval, Question

import planner
import reporter
from peers import PLANNER_URL, REPORTER_URL, ask_agent


@contextlib.asynccontextmanager
async def serving(*servers: tuple[Any, str]) -> AsyncIterator[None]:
    """Serve each `(app, url)` on the port of its url, and stop them all on exit."""
    running = []
    for app, url in servers:
        config = uvicorn.Config(app, host="127.0.0.1", port=urlparse(url).port, log_level="warning")
        server = uvicorn.Server(config)
        running.append((server, asyncio.create_task(server.serve())))
        while not server.started:
            await asyncio.sleep(0.02)
    try:
        yield
    finally:
        # Last started, first stopped: each server puts back the signal handlers it found when it
        # started, so stopped in any other order one leaves a stopped server's handler in the process.
        for server, task in reversed(running):
            server.should_exit = True
            await task


def show(item: Item) -> None:
    """One line for each thing the agent tells the caller besides its reply."""
    if isinstance(item, ActivityItem):
        print(f"    . {item.activity.label} ({item.activity.state or item.activity.type})")
    elif isinstance(item, UsageItem):
        print(f"    . tokens: {item.usage.input_tokens} in, {item.usage.output_tokens} out")
    elif isinstance(item, RequestItem):
        print(f"    ? {item.request.title}")


async def person(request: Question | Approval) -> Answer:
    """The person at the keyboard: type an answer to a question, `allow` or `deny` for an approval."""
    who = AnsweredBy(role="person")
    if isinstance(request, Question):
        value = {f.key: await asyncio.to_thread(input, f"    {f.text} ") for f in request.fields}
        return Answer(id=request.id, outcome="answered", answered_by=who, value=value)
    reply = await asyncio.to_thread(input, f"    {request.title} args={request.subject.args} [allow/deny] ")
    return Answer(id=request.id, outcome="answered", answered_by=who, value={"decision": reply.strip() or "deny"})


async def scripted_person(request: Question | Approval) -> Answer:
    """What `--auto` types."""
    who = AnsweredBy(role="person")
    if isinstance(request, Question):
        return Answer(id=request.id, outcome="answered", answered_by=who, value={f.key: "2026-10" for f in request.fields})
    return Answer(id=request.id, outcome="answered", answered_by=who, value={"decision": "allow"})


async def main(auto: bool = False) -> tuple[str, str]:
    """Both conversations; returns the two replies."""
    answer = scripted_person if auto else person
    async with serving((planner.app, PLANNER_URL), (reporter.app, REPORTER_URL)):
        print("You to the reporter: Write the stock report and publish it.")
        first = await ask_agent(REPORTER_URL, "Write the stock report and publish it.", answer, show)
        print(f"  Reply: {first}\n")
        print("You to the planner: Get the stock report for 2026-10.")
        second = await ask_agent(PLANNER_URL, "Get the stock report for 2026-10.", answer, show)
        print(f"  Reply: {second}")
    return first, second


if __name__ == "__main__":
    # `force` because the SDKs may have set up the root logger already; only the planner talks at INFO.
    logging.basicConfig(level=logging.WARNING, format="    [%(name)s] %(message)s", force=True)
    logging.getLogger("planner").setLevel(logging.INFO)
    asyncio.run(main(auto="--auto" in sys.argv))
