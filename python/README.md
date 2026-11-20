# ext-r2c (Python)

Python SDK for **R2C (Remote-to-Caller)**, an extension for A2A and MCP that
lets a remote ask its caller a question, request an approval, and hand back
artifacts.

> Pre-alpha. The standard v1 is written (draft). This package ships its
> identifiers, its JSON Schemas, the protocol-free core (`ext_r2c.core`) and
> the A2A door (`ext_r2c.a2a`). The MCP door is being written.

```python
import ext_r2c

ext_r2c.URI       # A2A extension URI
ext_r2c.MCP_KEY   # MCP _meta key
```

## The core

`ext_r2c.core` needs only `pydantic` and `jsonschema`. It holds the models of
the six kinds, the forms both doors show, the answer check, fallback text, the
run events, `AgentSource` with its `Driver`, and `ToolSpec`.

```python
from ext_r2c.core import answer_from_mcp, answer_schema, check_answer, mcp_form, parse

q = parse({"kind": "question", "id": "q-1", "title": "Which warehouse?",
           "answer_by": {"role": "person"},
           "fields": [{"key": "warehouse", "header": "Warehouse", "text": "Which warehouse?",
                       "type": "one", "options": [{"label": "North"}, {"label": "South"}]}]})

answer_schema(q)              # JSON Schema of the answer's value (A2A)
mcp_form(q).requested_schema  # the flat MCP form, with warehouse_other
a = answer_from_mcp(q, "accept", {"warehouse_other": "East annex"})
a.value                       # {'warehouse': 'East annex'}
check_answer(a, q)            # [] — no problem
check_answer(answer_from_mcp(q, "accept", {}), q)
# [Problem(code='invalid_value', key='warehouse', message='This is needed.')]
```

## The A2A door

`ext_r2c.a2a` (the `[a2a]` extra) puts R2C on a2a-sdk. `a2a_app` serves an
`AgentSource` as a Starlette app: questions and approvals go out in
input-required status messages with a text fallback, answers are checked
before the source sees them, and a context keeps one unfinished task per owner.

```python
from ext_r2c.a2a import SourceExecutor, a2a_app, agent_card
from ext_r2c.core import CardInfo, CardSkill, ReplyChunk, parse

CARD = CardInfo(name="Report writer", description="Writes the stock report.", version="0.1.0",
                skills=(CardSkill(id="report", name="Report", description="Writes a report.",
                                  tags=("report",)),))
MONTH = parse({"kind": "question", "id": "q-month", "title": "Which month?",
               "answer_by": {"role": "person"},
               "fields": [{"key": "month", "header": "Month", "type": "text",
                           "text": "Which month should the report cover?"}]})


class ReportWriter:               # a live source: it waits for the answer inside the run
    card = CARD
    pause = "live"

    async def run(self, input, ctx):
        answer = await ctx.ask(MONTH)
        yield ReplyChunk(f"The report for {answer.value['month']}.", last=True)

    def resume(self, answer, ctx):  # only a checkpoint source is resumed
        raise NotImplementedError


app = a2a_app(SourceExecutor(ReportWriter()), agent_card(CARD, "http://localhost:8000/"))
```

Serve `app` with any ASGI server. Put authentication in `middleware=`: the
user it sets is the owner of the tasks. Pass `task_store=` (for example
a2a-sdk's `DatabaseTaskStore`) to keep tasks across a restart. A paused
checkpoint source then resumes; a live source, like the one above, waits in
memory, so its paused task ends failed after a restart.

**An executor written by hand** keeps working: `R2CTask` gives it the same
wire as the door.

```python
from a2a.server.agent_execution import AgentExecutor
from ext_r2c.a2a import PendingMemory, R2CTask


class Hand(AgentExecutor):
    def __init__(self, store):
        self.store, self.memory = store, PendingMemory()   # the store given to a2a_app

    async def execute(self, context, queue):
        task = R2CTask(context, queue, memory=self.memory)
        if context.current_task is None:
            if await task.open(store=self.store):   # False: a second task was rejected
                await task.ask(MONTH)
            return
        answer = await task.take_answer()           # None: re-asked or refused already
        if answer is None:
            return
        if answer.outcome == "declined":            # declined, or expired
            await task.reply("No report.", last=True)
        else:
            await task.reply(f"The report for {answer.value['month']}.", last=True)
        await task.complete()

    async def cancel(self, context, queue):
        await R2CTask(context, queue, memory=self.memory).cancelled()
```

**The caller** reads the stream as typed items with `R2CClient`, and answers
with an `Answer` that is checked before it is sent.

```python
from ext_r2c.a2a import R2CClient, ReplyItem
from ext_r2c.core import Answer, AnsweredBy

client = await R2CClient.connect("http://localhost:8000/")
async for item in client.send("Write the stock report."):
    print(item)                     # TaskItem, StatusItem(input_required), RequestItem
answer = Answer(id=client.pending.id, outcome="answered",
                answered_by=AnsweredBy(role="person"), value={"month": "2026-10"})
async for item in client.answer(answer):         # AnswerRejected if it does not fit
    if isinstance(item, ReplyItem):
        print(item.text)                         # The report for 2026-10.
await client.aclose()
```

`reattach` picks a task up again after a cut, `get_task` reads it back, and
`fetch` downloads an artifact's file from the remote's own origin only (a
page is never fetched: it comes back as a `Link`).

Limits to know:

- Without authentication every caller is the same anonymous owner, and only
  the context ids keep them apart.
- On a2a-sdk's SQL task store a context id is a `String(36)` column, so a
  longer id fails there. The door does not shorten ids.
- `expires_at` is applied when the next message for the task arrives. Nothing
  ends a paused task on its own.

## Install

| Install | Pulls in | For |
|---|---|---|
| `ext-r2c` | pydantic, jsonschema | the core: models, forms, checks, run events |
| `ext-r2c[a2a]` | a2a-sdk | the A2A door, A2A callers |
| `ext-r2c[mcp]` | mcp | the MCP door, MCP callers |
| `ext-r2c[langgraph]` | langchain, langgraph | agents written with LangChain / LangGraph |

See the [repository](https://github.com/timezlab/ext-r2c) for the standard.
