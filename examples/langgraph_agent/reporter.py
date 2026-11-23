"""The reporter: a LangGraph agent that writes a stock report, served over A2A and MCP.

It pauses three ways, and none of them is R2C code in the graph:
  - `ask_month` asks its caller a question (`interrupt()` with an R2C question);
  - `publish_page` is gated by LangChain's own `HumanInTheLoopMiddleware`, so a person is asked first;
  - `get_holdings` calls the planner's MCP tool: the two agents call each other.

Run it alone with `uvicorn reporter:app --port 8002`.
"""

from __future__ import annotations

import os
from uuid import uuid4

from a2a.server.tasks import InMemoryTaskStore
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt
from mcp.server.request_state import RequestStateSecurity

from ext_r2c import A2AOptions, MCPOptions, Remote
from ext_r2c.bridges.langgraph import LangGraphAgent
from ext_r2c.core import CardInfo, CardSkill

from models import chat_model, reporter_script
from peers import PLANNER_URL, REPORTER_URL, call_tool

PUBLISHED: list[str] = []


@tool
def ask_month() -> str:
    """Ask the caller which month the report covers, as 2026-10."""
    answer = interrupt({
        "kind": "question", "id": f"month-{uuid4().hex[:8]}", "title": "Which month?",
        "answer_by": {"role": "caller"},
        "fields": [{"key": "month", "header": "Month", "type": "text",
                    "text": "Which month should the report cover? Write it as 2026-10."}],
    })
    return "unknown (the caller declined)" if answer is None else answer["month"]


@tool
async def get_holdings() -> str:
    """Get the holdings the report is about, one per line, from the planner."""
    return await call_tool(PLANNER_URL, "holdings", {})


@tool
def publish_page(slug: str) -> str:
    """Publish the report as a page of the handbook."""
    PUBLISHED.append(slug)
    return f"published {slug}"


graph = create_agent(
    chat_model(reporter_script),
    [ask_month, get_holdings, publish_page],
    system_prompt=("You write the stock report. If you do not know the month, call ask_month. Call "
                   "get_holdings for the data. Call publish_page only when you were asked to publish."),
    middleware=[HumanInTheLoopMiddleware(interrupt_on={"publish_page": True})],
    checkpointer=InMemorySaver(),   # in memory on purpose: a restart loses a paused report
)

app = Remote(
    expose=["a2a", "mcp"],
    agent=LangGraphAgent(graph, card=CardInfo(
        name="Reporter", description="Writes the stock report and publishes it once a person agrees.",
        version="0.1.0", skills=(CardSkill(id="report", name="Report", description="Writes a stock report.",
                                           tags=("report",)),))),
    url=REPORTER_URL,
    mcp_tool=True,   # the same agent is also the MCP tool `agent`
    a2a=A2AOptions(task_store=InMemoryTaskStore()),
    mcp=MCPOptions(security=RequestStateSecurity(keys=[os.urandom(32)])),
).app()
