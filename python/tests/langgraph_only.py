"""Run in a venv that holds the wheel with the `[langgraph]` extra only (no dev group): the LangGraph
bridge works there, loads no door, and says which extra it needs when `langgraph` is missing
(constitution VIII, spec 006 SC-010).

Not collected by pytest (no `test_` prefix), and self-contained on purpose: `python -I` takes this
folder off the path, so it cannot import the test helpers. CI runs it as:
    python -I tests/langgraph_only.py
It prints `langgraph only: ok` or fails with an assertion.
"""

from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
import warnings
from typing import Any

DOORS = ("a2a", "mcp")

QUESTION = {
    "kind": "question", "id": "q-1", "title": "Report title", "answer_by": {"role": "person"},
    "fields": [{"key": "title", "header": "Title", "text": "What is the report's title?", "type": "text"}],
}


def main() -> None:
    assert importlib.util.find_spec("pytest") is None, "pytest is installed: this is not a langgraph-only venv"
    asyncio.run(asyncio.wait_for(_round_trip(), 30))
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(DOORS))
    assert not loaded, f"using the LangGraph bridge loaded {loaded}"
    _blocked_check()
    print("langgraph only: ok")


async def _round_trip() -> None:
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.types import interrupt

    from ext_r2c.bridges.langgraph import LangGraphAgent
    from ext_r2c.core import Answer, Ask, Done, Driver, ReplyChunk, RunInput, UsageEvent, thread_id

    def ask(state: Any) -> dict[str, Any]:
        answer = interrupt(QUESTION)
        return {"messages": [AIMessage(content=f"Got: {answer['title']}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("ask", ask)
    builder.add_edge(START, "ask")
    builder.add_edge("ask", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        source = LangGraphAgent(graph)
    assert [str(w.message) for w in caught if issubclass(w.category, UserWarning)], "no in-memory warning"

    run = Driver(source).start(thread_id("a2a", "owner-1", "ctx-1"), RunInput("Write the report"))
    events: list[Any] = []
    async for event in run:
        events.append(event)
        if isinstance(event, Ask):
            break
    request = run.pending
    assert request is not None and request.id == "q-1", request
    await run.deliver(Answer.parse({
        "kind": "answer", "id": "q-1", "outcome": "answered", "answered_by": {"role": "person"},
        "value": {"title": "October stock"},
    }))
    events += [event async for event in run]
    replies = [e for e in events if isinstance(e, ReplyChunk)]
    assert "".join(r.text for r in replies) == "Got: October stock", replies
    assert replies[-1].last and not any(r.last for r in replies[:-1]), replies
    assert not [e for e in events if isinstance(e, UsageEvent)], "no message reported tokens: no usage"
    assert isinstance(events[-1], Done), events[-1]


def _blocked_check() -> None:
    """With `langgraph` unavailable, importing the bridge says which extra brings it."""
    code = (
        "import sys\n"
        "sys.modules['langgraph'] = None\n"
        "sys.modules['langchain_core'] = None\n"
        "try:\n"
        "    import ext_r2c.bridges.langgraph\n"
        "except ImportError as exc:\n"
        "    assert 'ext-r2c[langgraph]' in str(exc), str(exc)\n"
        "    print('blocked: ok')\n"
        "else:\n"
        "    raise SystemExit('the bridge imported with langgraph blocked')\n"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0 and "blocked: ok" in result.stdout, result.stdout + result.stderr


if __name__ == "__main__":
    main()
