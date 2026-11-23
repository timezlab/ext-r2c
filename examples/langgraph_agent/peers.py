"""How one process calls another: two small helpers over the R2C clients.

This is the example's own code, not part of the SDK. `ask_agent` is the loop that every caller of an
agent writes: send, read the items, answer what pauses, read on. `call_tool` is the same for one MCP
tool. The planner, the reporter and `main.py` all use them.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any

import ext_r2c.mcp as mcp
from ext_r2c.a2a import AnswerRejected, Item, R2CClient, ReplyItem, RequestItem
from ext_r2c.core import Answer, Approval, Question

PLANNER_URL = os.environ.get("PLANNER_URL", "http://127.0.0.1:8001")
REPORTER_URL = os.environ.get("REPORTER_URL", "http://127.0.0.1:8002")

# What decides a question or an approval a remote asked: an `Answer`, or `None` when nobody can.
Answerer = Callable[[Question | Approval], Awaitable[Answer | None]]


async def ask_agent(url: str, text: str, answer: Answerer, show: Callable[[Item], None] | None = None) -> str:
    """Send `text` to the A2A agent at `url` and return its reply.

    Each time the agent pauses to ask, `answer` decides. If it returns `None`, or the remote refuses
    its answer, the call is cancelled and the reply says so.
    """
    client = await R2CClient.connect(url)
    reply: list[str] = []
    try:
        items = client.send(text)
        while True:
            pending: Question | Approval | None = None
            async for item in items:
                if show is not None:
                    show(item)
                if isinstance(item, ReplyItem):
                    reply.append(item.text)
                elif isinstance(item, RequestItem):
                    pending = item.request
            if pending is None:
                return "".join(reply)
            given = await answer(pending)
            if given is None:
                await client.cancel()
                return f"Stopped: nobody here can answer {pending.title!r}."
            items = client.answer(given)
    except AnswerRejected as refused:
        await client.cancel()
        return f"Stopped: the answer was refused ({refused.problems[0].message})."
    finally:
        await client.aclose()


async def call_tool(url: str, name: str, arguments: dict[str, Any]) -> str:
    """Call the MCP tool `name` of the server at `url` and return its text."""
    client = await mcp.R2CClient.connect(f"{url}/mcp")
    text: list[str] = []
    failed = False
    try:
        async for item in client.call(name, arguments):
            if isinstance(item, mcp.ReplyItem):
                text.append(item.text)
            elif isinstance(item, mcp.ResultItem):
                failed = item.is_error
            elif isinstance(item, mcp.RequestItem):
                await client.cancel()
                return f"Stopped: the tool {name} asked for input."
    finally:
        await client.aclose()
    return f"The tool {name} failed: {''.join(text)}" if failed else "".join(text)
