"""The planner: a LangGraph agent that delegates the stock report to the reporter.

It is a caller (its tool `ask_reporter` talks to the reporter over A2A) and a remote (it is served
over A2A and MCP, and its plain function `holdings` is an MCP tool the reporter calls back).

When the reporter pauses to ask, the planner answers what its role allows. It answers a question
addressed to the caller, from what it knows. It never approves anything: an approval is for a person
or a rule, never a model, so a rule here declines every approval.

Run it alone with `uvicorn planner:app --port 8001`.
"""

from __future__ import annotations

import logging
import os

from a2a.server.tasks import InMemoryTaskStore
from langchain.agents import create_agent
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from mcp.server.request_state import RequestStateSecurity

from ext_r2c import A2AOptions, MCPOptions, Remote
from ext_r2c.bridges.langgraph import LangGraphAgent
from ext_r2c.core import Answer, AnsweredBy, Approval, CardInfo, CardSkill, Question

from models import chat_model, planner_script
from peers import PLANNER_URL, REPORTER_URL, ask_agent

log = logging.getLogger("planner")


def holdings() -> str:
    """The holdings of the portfolio, one per line: a ticker and a quantity."""
    return "ACME 120\nGLOBEX 40"


@tool
async def ask_reporter(request: str, month: str) -> str:
    """Ask the reporter agent for something about the stock report. `month` is the month it covers, as 2026-10."""

    async def answer(asked: Question | Approval) -> Answer | None:
        if isinstance(asked, Question) and asked.answer_by.role == "caller":
            log.info("the reporter asks %r; answering %s from my own context", asked.title, month)
            return Answer(id=asked.id, outcome="answered", answered_by=AnsweredBy(role="caller"),
                          value={field.key: month for field in asked.fields})
        if isinstance(asked, Approval):
            log.info("the reporter asks %r; a rule declines it, since an agent never approves", asked.title)
            return Answer(id=asked.id, outcome="declined", answered_by=AnsweredBy(role="policy"),
                          note="An agent that calls an agent does not approve.")
        return None   # a question for a person: this agent has nobody to ask

    return await ask_agent(REPORTER_URL, request, answer)


graph = create_agent(
    chat_model(planner_script),
    [ask_reporter],
    system_prompt=("You plan. When asked to get the stock report, call ask_reporter with the request "
                   "and the month, then say in one sentence what the reporter answered."),
    checkpointer=InMemorySaver(),   # in memory on purpose: a restart loses a paused conversation
)

app = Remote(
    expose=["a2a", "mcp"],
    agent=LangGraphAgent(graph, card=CardInfo(
        name="Planner", description="Plans the work and delegates the stock report to the reporter.",
        version="0.1.0", skills=(CardSkill(id="plan", name="Plan", description="Delegates the stock report.",
                                           tags=("plan",)),))),
    url=PLANNER_URL,
    tools=[holdings],   # a plain function becomes an MCP tool, named by its signature and docstring
    mcp_tool=True,
    a2a=A2AOptions(task_store=InMemoryTaskStore()),
    mcp=MCPOptions(security=RequestStateSecurity(keys=[os.urandom(32)])),
).app()
