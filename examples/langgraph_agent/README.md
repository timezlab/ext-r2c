# Two LangGraph agents that call each other

Two small agents, each a LangChain agent (`create_agent`, a LangGraph graph) that **keeps its own
code**. Each is wrapped by one `Remote(...)` and served over A2A and MCP from one ASGI app.

- **reporter** writes a stock report. It asks its caller a question (which month?), asks a person to
  approve publishing the page, and calls the planner's MCP tool for the data.
- **planner** delegates the report to the reporter over A2A, and serves the data tool the reporter
  calls back. So each one calls the other, over a different door.

`main.py` starts both in one process and talks to them as the person at the keyboard.

## Run it

```
pip install "ext-r2c[a2a,mcp,langgraph] @ https://github.com/timezlab/ext-r2c/releases/download/v0.1.0a1/ext_r2c-0.1.0a1-py3-none-any.whl" uvicorn
python main.py --auto        # a scripted person answers: month 2026-10, then allow
python main.py               # you answer
```

Run it from this folder in a checkout of the tag `v0.1.0a1`; the example is not in the wheel. The first
line installs the pre-release from its GitHub release page: the bare name `ext-r2c` on PyPI is not this
project. To use a wheel file you already have, put its path in place of the address:
`"./ext_r2c-<version>-py3-none-any.whl[a2a,mcp,langgraph]"`.

No key and no network are needed: without `R2C_EXAMPLE_MODEL` the agents use a scripted stand-in for the
model (`models.py`). To use a real one, name a LangChain `provider:model` whose package and key you have:

```
R2C_EXAMPLE_MODEL=<provider>:<model> python main.py
```

The apps listen on `127.0.0.1:8001` (planner) and `127.0.0.1:8002` (reporter); set `PLANNER_URL` and
`REPORTER_URL` for other ports. Each also runs alone: `uvicorn reporter:app --port 8002`.

## What you see

Abridged output of `python main.py --auto`:

```
You to the reporter: Write the stock report and publish it.
    . ask_month (running)
    ? Which month?                                   <- the reporter's question (answered 2026-10)
    . get_holdings (done)                            <- the reporter called the planner's MCP tool
    ? Approve publish_page?                          <- an approval (answered allow)
    . publish_page (done)
    . tokens: 160 in, 36 out
  Reply: Stock report for 2026-10: ACME 120, GLOBEX 40. Published.

You to the planner: Get the stock report for 2026-10.
    [planner] the reporter asks 'Which month?'; answering 2026-10 from my own context
    [planner] the reporter asks 'Approve publish_page?'; a rule declines it, since an agent never approves
  Reply: The reporter says: Stock report for 2026-10: ACME 120, GLOBEX 40. Not published: the approval was refused.
```

The second conversation is the point of the example. The planner is an agent, so it answers a question
addressed to the caller from what it knows, and **declines every approval with a rule**: an approval is
answered by a person or a rule, never by a model, and the SDK refuses a `caller` answer to one.
Nothing was published for it (`reporter.PUBLISHED` holds one page, from the first conversation).

## Where to look

| File | What it shows |
|---|---|
| `reporter.py` | a graph that pauses three ways (`interrupt()`, `HumanInTheLoopMiddleware`, a call to another agent's tool) and the one `Remote(...)` that serves it |
| `planner.py` | a graph whose tool calls another agent, answers its question, declines its approval; a plain function served as an MCP tool |
| `peers.py` | the caller's side: `ask_agent` (A2A) and `call_tool` (MCP), the loop *send, read items, answer what pauses, read on* |
| `main.py` | both apps in one process, and the person's answers (`person`, `scripted_person`) |
| `models.py` | the model switch, and the scripted stand-in |

The SDK parts used: `ext_r2c.Remote` (and `A2AOptions`, `MCPOptions`), `ext_r2c.bridges.langgraph.LangGraphAgent`,
`ext_r2c.a2a.R2CClient` and `ext_r2c.mcp.R2CClient` with their typed items, and `ext_r2c.core`'s `Answer`,
`AnsweredBy`, `Question`, `Approval` and `CardInfo`. The reporter's question is a plain dict handed to
LangGraph's `interrupt()`; the bridge shows it to the caller as an R2C `question`.

## What this example does not do

It is a local demonstration, not a deployment.

- **In memory.** The checkpointers, task stores and request-state keys live in the process, so a restart
  loses a paused conversation. The bridge says so with a warning when the example starts. The *Durable
  state* paragraph of [`python/README.md`](../../python/README.md) lists what each layer needs to keep a pause.
- **No authentication.** Every caller is the same anonymous owner. Put authentication in front before
  anything reaches a network; the *Identity* paragraph of the same README says how each door names its owner.
- **Loopback only.** The MCP door answers `421` to a `Host` that is not a loopback address until you name
  the public host (*The host guard* paragraph).
- **No loop guard between the agents.** The reporter calls the planner's plain tool, not its agent, so the
  two cannot call each other forever. Two agents that call each other's *agents* need a depth limit that
  travels in the message text, because a tool never sees the owner or the door of the call.
- **One hop.** The planner answers or declines what the reporter asks; it does not pass a question on to
  its own caller.
