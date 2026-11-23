# ext-r2c (Python)

Python SDK for **R2C (Remote-to-Caller)**, an extension for A2A and MCP that
lets a remote ask its caller a question, request an approval, and hand back
artifacts.

> Pre-alpha. The standard v1 is written (draft). This package ships its
> identifiers, its JSON Schemas, the protocol-free core (`ext_r2c.core`), the
> A2A door (`ext_r2c.a2a`), the MCP door (`ext_r2c.mcp`), MCP Skills, which
> is a separate MCP extension served by the same package, the LangGraph
> bridge (`ext_r2c.bridges.langgraph`), and `Remote`, the one adapter that
> serves a remote over A2A, MCP or both.

```python
import ext_r2c

ext_r2c.URI       # A2A extension URI
ext_r2c.MCP_KEY   # MCP _meta key
```

## Remote

`ext_r2c.Remote` wraps a remote that already exists and serves it over A2A, MCP
or both, from one ASGI app. The remote's own code does not change: one install
and one module like this one.

```python
# remote_module.py
from ext_r2c import Remote
from ext_r2c.bridges.langgraph import LangGraphAgent

app = Remote(
    expose=["a2a", "mcp"],
    agent=LangGraphAgent(graph),        # an AgentSource, or an a2a-sdk executor
    url="https://remote.example.com",   # where callers reach this app
    tools=[publish_page],               # functions and ToolSpecs, served on MCP
    approve=["publish_page"],           # a direct call first asks an approval
    mcp_tool=True,                      # the agent is one more MCP tool, `agent`
).app()
```

Run it with any ASGI server, for example `uvicorn remote_module:app`. `Remote`
has no `run()` and no command line. `Remote(...)` and `app()` start nothing: the
app's lifespan, which every ASGI server runs, starts and stops both doors.

As written the module warns twice, because both doors keep a paused call in
memory; see *Durable state* below.

`Remote`, `RemoteError`, `A2AOptions` and `MCPOptions` import with no extra
installed. A door needs its extra (`ext-r2c[a2a]`, `ext-r2c[mcp]`): exposing one
whose extra is missing is an `ImportError` that names it.

| Argument | Served by | What it is |
|---|---|---|
| `expose` | | required: `["a2a"]`, `["mcp"]` or both; there is no default |
| `agent` | A2A; MCP only with `mcp_tool=True` | an `AgentSource`, such as `LangGraphAgent(graph)`, or an a2a-sdk `AgentExecutor` (A2A only, served as it is) |
| `card` | both | a `CardInfo`. Needed when the agent brings none (an executor, or tools only). It also names the MCP server |
| `url` | A2A | the public base address of this app; the card says `url` + `a2a.path` |
| `tools` | MCP | `ToolSpec`s, `SourceTool`s and plain functions (converted with `tool_from_function`) |
| `approve` | MCP | tool names, or `{name: Approve(...) or bool}`: a direct call to a named tool first asks an approval |
| `skills` | MCP | a folder, a list of folders, or a ready `SkillsExtension` (its `include` and `exclude` choose) |
| `resources`, `prompts` | MCP | the MCP SDK's own `Resource` and `Prompt` objects, served as given |
| `mcp_tool` | MCP | `True` serves the agent as one tool named `agent` that takes `{message, context_id?}` |
| `middleware` | both | Starlette `Middleware` objects around both doors, outermost first |
| `a2a`, `mcp` | its door | `A2AOptions(...)` and `MCPOptions(...)`: the settings of one door |
| `limits`, `clock` | both | the core's `Limits`, and a clock for tests |

Every argument is a keyword. An argument whose door is not exposed is an error,
not ignored. A LangChain tool is converted in your own module
(`tools_from_langchain([...])`), because `Remote` imports no bridge. For an
agent tool with another name or input, build a `SourceTool` yourself and give it
in `tools=`.

**Errors come at the `Remote(...)` line.** A value of the wrong type is a
`TypeError`. Everything else is collected into one `RemoteError` (a
`ValueError`), whose `problems` lists each one as
`"<argument>: <what is wrong>; <what to do>"`, so a configuration is fixed in one
pass: a door with nothing to serve, an agent no door serves, `approve` naming
something that is not a plain MCP tool, two tools of one name, a `url` that is
not an absolute `http(s)` base address (or has a space, a control character or a
bad port), a path under `/.well-known/`. A class given as `agent` is a
`TypeError`: give an instance. A message
names the argument and never repeats a value you typed. A skills folder that
fails its scan is the unchanged `SkillsError`, raised by `app()`.

**One `Remote`, one app.** `app()` is called once; a second call is a
`RuntimeError`, also after a first call that failed. Build a new `Remote`. The
app itself starts once too: the SDK parts under it run once, so starting the
same app a second time fails on MCP and serves nothing useful on A2A. A list of
skill folders is copied when `Remote(...)` is called, so changing the list
afterwards changes nothing; the folders are read by `app()`.

**Approvals.** `approve=` covers direct MCP calls to the tools you name, and
only those. The agent's own approvals (for example LangChain's
`HumanInTheLoopMiddleware`) stay with the agent and reach the caller through
either door. The two lists are separate on purpose. An approval is addressed to
a person or an approver (`Approve(answer_by="approver")`), never to the caller,
and nothing in `Remote` answers one.

**Paths and the card.** The A2A JSON-RPC endpoint is `/` (`A2AOptions.path`),
the card is always `/.well-known/agent-card.json`, and the MCP endpoint is
exactly `/mcp` (`MCPOptions.path`), with no redirect and no trailing slash.
`url` is the base the app is reached at, such as `https://remote.example.com` or
`https://remote.example.com/agents`, and the card's address is `url` +
`a2a.path`. The card declares R2C with `required: false`. `skills=` is MCP
Skills only: the skills on the A2A card are the ones of `CardInfo.skills`.

**Inside a larger app.** Starlette's `Mount` does not run the lifespan of what
it mounts, so run it yourself, and put the prefix in `url`:

```python
agents = Remote(expose=["a2a", "mcp"], agent=agent, mcp_tool=True,
                url="https://remote.example.com/agents").app()

@contextlib.asynccontextmanager
async def lifespan(site):
    async with agents.router.lifespan_context(agents):
        yield

site = Starlette(routes=[Mount("/agents", app=agents)], lifespan=lifespan)
```

**Identity.** `Remote` adds no authentication. Each door names the owner of a
call its own way: A2A reads the user an authentication middleware put on the
request (`A2AOptions.owner_resolver` changes the rule), and MCP reads the SDK's
authenticated principal, or `MCPOptions.owner`. `MCPOptions.owner` is asked
first: an owner it names wins over the SDK's authenticated principal, and
returning `None` leaves the principal (or `anonymous`). One middleware in
`middleware=` serves both when the MCP door is told to read its user:

```python
def owner(ctx):
    user = getattr(getattr(ctx, "request", None), "user", None)
    return user.display_name if user is not None and user.is_authenticated else None

Remote(..., middleware=[Middleware(AuthenticationMiddleware, backend=backend)],
       mcp=MCPOptions(owner=owner))
```

With `middleware=` given and an MCP door that has neither `owner` nor the SDK's
own authentication (`auth`, `token_verifier` or `auth_server_provider` set in
`MCPOptions.server`; a key left `None` counts as not set), `Remote` warns once,
naming `mcp.owner`: every MCP caller would be one owner and share one set of
threads. The warning is not an error, because one owner for every MCP caller may
be what you want. A thread belongs to one owner, one context and one
door, so the same context id over both doors is two conversations.

Two things `Remote` does not do for you. The SDK's own authentication in
`MCPOptions.server` protects the MCP door only; the A2A door has no owner until
a middleware (or `A2AOptions.owner_resolver`) gives it one, and without either
every A2A caller is the same owner and shares one set of threads. And no
warning says so, because that may be what you want.

**The host guard.** The MCP endpoint answers `421` to a request whose `Host` is
not its default `127.0.0.1` until you name the public host. `Remote` does not
guess it, and the guard covers `/mcp` only (the A2A door answers any `Host`):

```python
from mcp.server.transport_security import TransportSecuritySettings

MCPOptions(transport_security=TransportSecuritySettings(
    enable_dns_rebinding_protection=True, allowed_hosts=["remote.example.com"]))
```

**Durable state.** A pause survives a restart only when each layer keeps it:

| Layer | Setting | Without it |
|---|---|---|
| the agent | its own store, such as a durable LangGraph checkpointer | the bridge warns; an answer after a restart ends `lost` |
| the A2A door | `A2AOptions(task_store=...)`, such as a2a-sdk's `DatabaseTaskStore` | `Remote` warns once, naming `a2a.task_store`; a restart loses every paused task |
| the MCP door | `MCPOptions(security=RequestStateSecurity(keys=[...]))` | `Remote` warns once, naming `mcp.security`, when something on MCP can pause (an `approve` entry, or an agent of the checkpoint style); a retry after a restart is refused |

Giving `InMemoryTaskStore()` yourself says memory is what you want, and the A2A
warning stays quiet. A `task_store` and an `owner_resolver` go together: the
store keys its tasks by the owner the resolver names, and nothing in `Remote`
compares the two, so give both from the same place. The warnings are `UserWarning`s at the `Remote(...)` line of
a valid configuration; `app()` says nothing again.

**The rest of a door's settings.** `MCPOptions.server` and `MCPOptions.http` are
the remaining keyword arguments of the MCP SDK's `MCPServer` and
`streamable_http_app` (`instructions`, `auth`, `token_verifier`,
`json_response`, `stateless_http`, ...). There is no `mcp_server=` argument: a
server built elsewhere cannot take the R2C extension afterwards. The keywords
`Remote` does not take from there (`name`, `version`, `description`,
`extensions`, `tools`, `resources`, `request_state_security`, `security`,
`extension`, `streamable_http_path`, `transport_security`, `host`) are refused,
with what to do instead: `host` is the address the server that runs the app
binds, so name the hosts the app answers to in `transport_security`.

**Shared by two doors.** With both doors exposed the same agent object serves
both, so it must be safe to share (a `LangGraphAgent` is: its state is the
checkpointer's, keyed by thread). `Remote` sets nothing on the agent, the tools
or the functions it is given.

**An executor you already have.** An a2a-sdk `AgentExecutor` that knows nothing
of R2C is served unchanged: `Remote(expose=["a2a"], agent=executor,
card=CardInfo(...), url=...)`. Its plain-text `input-required` reaches every
caller as before, and a caller that activated R2C simply gets no R2C part.

`Remote` adds no endpoint, no CORS and no logging of its own.

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

## The MCP door

`ext_r2c.mcp` (the `[mcp]` extra) puts R2C on the MCP Python SDK, for the
2026-07-28 protocol. `R2CExtension` is an MCP SDK `Extension` keyed
`io.github.timezlab/r2c`; `mcp_server` builds an `MCPServer` with it. A
question or an approval is asked through a multi-round-trip tool call: the tool
returns `input_required` with an elicitation form, and the client calls it
again with its response and the `requestState` it was given.

```python
from ext_r2c.core import tool_from_function
from ext_r2c.mcp import Approve, R2CExtension, SourceTool, mcp_server


def place_order(item: str, quantity: int) -> str:
    """Places an order."""
    return f"Ordered {quantity} of {item}."


server = mcp_server("stock", R2CExtension(
    tools=[SourceTool(ReportWriter(), name="report"),   # an AgentSource as one tool
           tool_from_function(place_order)],            # a plain tool
    approve={"place_order": Approve(answer_by="person")},
))
app = server.streamable_http_app()   # serve with any ASGI server
```

- `SourceTool` serves an `AgentSource` (the `ReportWriter` above) as one
  tool. Its default input is `{message, context_id}`; give `input_schema` and
  `to_input` for another. Its questions and approvals become elicitations, and
  the reply, artifacts and usage come back in the tool result. Activities go
  out as `notifications/progress` when the client sent a `progressToken`.
- `approve=` asks an approval before a direct tool call. The tool runs only on
  `allow`, or on `edit` with the edited arguments; on `deny`, `decline` or
  expiry it does not run, and the result says why, with `isError: true`.
  `edit` is offered only when the tool's arguments are flat (R2C-MCP-3).
- A `ToolSpec` may return a `str`, a `ToolOutput` (text, structured data,
  artifacts, usage), or any JSON value.
- Answers are checked before the source sees them: a response that does not
  fit is asked again with the problems; a response to another request, or
  after the request expired, is refused.
- One call per owner and context at a time: a second call in a context with an
  unfinished one is refused. Put authentication on the server (the SDK's
  `auth=` and `token_verifier=`, passed through `mcp_server`): its principal
  is the owner.

**Restart and single use.** The SDK seals `requestState` (tamper, expiry,
principal, audience, the tool and its arguments); the door never seals
anything itself. Without `security=`, the SDK uses keys made at start, so a
restart invalidates every paused call. Give fixed keys to keep a paused
checkpoint source across a restart:

```python
from mcp.server.request_state import RequestStateSecurity

server = mcp_server("stock", extension, security=RequestStateSecurity(keys=[KEY]))
```

Each round can be answered once: the door claims it in a `RoundLedger`. The
default `MemoryLedger` lives in one process, so with several processes or
across a restart, pass a shared `ledger=` to `R2CExtension`, or a state could
be answered twice. A live source waits inside the run, in memory: its paused
call works only in the same process, and after a restart the retry says the
run was lost. A paused run ends on its own once its state expires.

**The caller** reads a tool call as typed items with `R2CClient`, and answers
with an `Answer` that is checked before it is sent.

```python
from ext_r2c.core import Answer, AnsweredBy
from ext_r2c.mcp import R2CClient, ReplyItem

client = await R2CClient.connect("http://localhost:8000/mcp")
async for item in client.call("report", {"message": "Write the stock report."}):
    print(item)                     # ActivityItem, UsageItem, RequestItem
(request,) = client.pending.values()
answer = Answer(id=request.request.id, outcome="answered",
                answered_by=AnsweredBy(role="person"), value={"month": "2026-10"})
async for item in client.answer(answer):         # AnswerRejected if it does not fit
    if isinstance(item, ReplyItem):
        print(item.text)                         # The report for 2026-10.
await client.aclose()
```

`respond` answers a plain elicitation (one with no R2C object), `cancel` stops
the running round and forgets a paused one (the server keeps a paused call
until its state expires; `respond(key, "cancel")` ends it there), and `fetch`
reads an artifact:
from the block itself, through `resources/read`, or over http from the
server's own origin only (another origin, or a `live` artifact, comes back as
a `Link`).

Limits to know:

- Serve `R2CExtension` with `mcp_server` only: it gives the extension the
  state's TTL, which each ledger claim is kept for. An `MCPServer` built by
  hand with it is refused.
- Without authentication every caller is the same anonymous owner, and only
  the context ids keep them apart.
- Nothing caps how many calls are paused at once; each ends when its state
  expires. Limit the rate in front of the server.
- MCP does not stream the reply: the text arrives once, in the tool result.
- A tool call that runs longer than the client's request timeout fails on the
  client's side (MCP Tasks is not supported).
- The MCP SDK's client declares URL elicitation along with form elicitation.
  `R2CClient` never asks for a URL itself; a URL request from a server comes
  out as a plain `RequestItem` with its `url`.

## MCP Skills

`ext_r2c.mcp` also serves **MCP Skills** (SEP-2640, extension
`io.modelcontextprotocol/skills`): folders of `SKILL.md` files that an MCP
client loads to learn how to do something. It is a second MCP SDK `Extension`,
**not part of R2C**: it needs no R2C object, imports nothing of `ext_r2c`, and
works on any `MCPServer`. The extension is **Beta**; it was written against the
beta text read on 2026-11-21 and may change in ways that break this package.

```python
from mcp.server.mcpserver import MCPServer
from ext_r2c.mcp import SkillsExtension

skills = SkillsExtension(["skills"], exclude=["draft-*"])
server = MCPServer("docs", extensions=[skills])          # skills alone
```

Each skill is a folder with a `SKILL.md` whose YAML frontmatter has `name` (the
folder's name) and `description`; every other field is passed on as written.
`skills/list` (paged), `skills/get` and every file of the skill are served, the
files as ordinary `resources/read` resources, with a SHA-256 digest and a size in
the entry. Beside R2C, hand the extension to `mcp_server`:

```python
server = mcp_server("agent", R2CExtension(tools=[...]), extensions=[skills])
```

- `include` and `exclude` are glob patterns on a skill's folder name; `exclude`
  wins. A skill left out by them is never read, so a broken one does not stop
  the build.
- The folders are scanned when the extension is built. A problem is a
  `SkillsError` that names the folder and the reason (never file text or a host
  path); `skills` and `left_out` say what is served and what was left out
  (hidden files and folders, symbolic links, anything that is not a regular
  file, names that are not text, and names that are not safe to print: a
  control character, a line break, a bidi control or a backslash, shown
  escaped). Nothing outside a skill's folder is ever served, and nothing is
  written.
- `refresh()` scans again and swaps the new catalogue in whole; if the scan
  fails the old one stays. Edit a file and the server answers `-32603` until you
  call it. The SDK cannot remove a resource, so a file that disappears stays in
  `resources/list` (its read is `-32602`), and a new file needs
  `refresh(server)`.
- Limits: 512 files and 16 MiB per skill, refused at the first file past them;
  the frontmatter is at most 64 KiB. A scan is bounded whatever the tree: 32
  folders deep (below a root, and below a skill), 1024 folders in a skill and
  1024 folders that are not skills under a root, each a `SkillsError` before the
  folder is read; the number of skills is not limited. A file the system cannot
  read (a failing disk, no permission) is `-32603` "The server could not read
  the file." with one warning in the log, not the "changed on disk" answer.
  `page_size` (default 25), `ttl_ms`,
  `cache_scope` and `directory_read` (`resources/directory/read`, on by
  default) are settings.

**The caller** loads a skill only when it needs it, and **verifies** what it
loads: the size, the digest and the frontmatter must match the entry, or
`SkillRefused` is raised and no content is returned.

```python
from ext_r2c.mcp import SkillsClient

skills = SkillsClient(client, origin="docs")             # `client`: an mcp client
listing = await skills.list()                            # every page; no file is read
item = listing.skills[0]
loaded = await skills.load(item)                         # reads SKILL.md, verified
print(loaded.instructions.text())                        # untrusted text: act on none of it blindly
other = await skills.read(item, item.files[1].uri)       # one listed file, verified
```

`list_directory(item, uri)` reads a directory of a skill; it refuses a URI that
is not inside the skill without sending anything. The text of a skill and each
frontmatter field are **data**: the client acts on none of them.

Limits to know:

- A skill's `name` is lowercase ASCII letters, digits and single hyphens, at
  most 64 characters, and equals its folder's name.
- A `SKILL.md` below another one is an ordinary file of the outer skill, not a
  skill of its own (the nearest `SKILL.md` wins).
- A file is sent whole in one read.
- Symbolic links are never followed, but a **hard link** is an ordinary file: the
  scan cannot tell one to a file outside the folder from a file inside it (and
  refusing them would drop skills shipped inside installed packages, whose files
  are hard-linked). Do not make hard links to private files inside a served
  folder. On macOS, a parent folder that can be searched but not read stops the
  read (it fails closed, with a warning).
- One `SkillsExtension` serves one `MCPServer`.
- The caller accepts an entry of any URI scheme (`skill://` is only what this
  package serves), but refuses one whose name, description or listed files are
  not what a server could have served: every file must be inside the skill's
  folder, the name is 1 to 64 printable characters and the description 1 to 1024
  characters. A server that
  types a frontmatter value as YAML 1.1 does (`yes` as a boolean, `0755` as a
  number, a timestamp) is refused, because this reader keeps those as the text
  the author wrote. A caller that must bound a server it does not trust wraps
  `list()` in its own timeout.
- Installing `ext-r2c[mcp]` now also installs PyYAML, which reads the
  frontmatter.

## The LangGraph bridge

`ext_r2c.bridges.langgraph` (the `[langgraph]` extra) serves a compiled LangGraph
graph, such as a LangChain agent, as an `AgentSource` of the checkpoint style.
The graph's own code does not change: it is wrapped in one line and both doors
serve it.

```python
from ext_r2c.a2a import SourceExecutor, a2a_app, agent_card
from ext_r2c.bridges.langgraph import LangGraphAgent
from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server

agent = LangGraphAgent(graph)       # graph: create_agent(..., checkpointer=saver)

app = a2a_app(SourceExecutor(agent), agent_card(agent.card, "http://localhost:8000/"))
server = mcp_server("agent", R2CExtension(tools=[SourceTool(agent, name="agent")]))
```

Wrapping checks three things at once and starts nothing: the graph is compiled
(`TypeError`; an uncompiled `StateGraph` is told to call `.compile(checkpointer=...)`),
it has a checkpointer (`ValueError`), and its input takes `messages` (`ValueError`).
The options are keyword-only: `card=`, `reasoning=False` and `expose_tools=()`.

What a caller sees of a pause, and what the graph gets back:

| The graph pauses with | The caller sees | The graph gets |
|---|---|---|
| `HumanInTheLoopMiddleware`, `per_call` or `batched`, one gated call | an `approval` for that call, one at a time in the model's order, answered by a person or an approver | `approve`, `edit` or `reject` for it (`reject` carries the reason) |
| the same, where the call allows only a reply | a `question` with one text field | `respond` |
| `interrupt(value)` with a valid R2C `question` or `approval` | that object, as it is | the answer's `value` mapping |
| `interrupt(value)` with anything else | a `question` for a person (a string is its title) | the answered text |
| a turn that ends with a structured reply `status = "input_required"` | a `question` for the caller | no resume: the answer is the next human message of the thread |

An approval is never addressed to the caller and never answered by code in the
bridge. An answer the graph would refuse (a decision the call does not allow, an
`edit` its schema does not take) is refused first, with the problems, and the
pause stays pending. An answer for a pause the checkpointer no longer holds ends
the run `lost` and the graph is not started. A declined approval counts as a `deny`:
the graph gets `reject` from the middleware, and `{"decision": "deny"}` (with
`reason` when the caller left a note) from an `approval` it wrote itself. A new
message on a thread with a tool call that nothing answered (an approval waiting, a
tool that raised, a run cancelled in the middle of a tool) first answers that call
with an error the model can read ("withdrawn", or "did not finish"), so the model
never sees a call with no answer, and then reads the message.

Tool activity, `usage` and files are read from the graph's stream. A reply is
streamed as chunks of one artifact; `reasoning` and the arguments and results of
tools are left out unless you ask:

```python
agent = LangGraphAgent(graph, reasoning=True, expose_tools=["search_catalogue"])
```

**LangChain tools** become `ToolSpec`s with no re-declaration, and a call with
arguments that break the schema, or with a key the schema does not declare (unless it
says `additionalProperties` or `patternProperties`), never runs the tool. A tool that takes an injected
argument (`InjectedState`, `ToolRuntime` and the like) only makes sense inside its
graph, so converting it is refused with a `TypeError` that names it:

```python
from ext_r2c.bridges.langgraph import tools_from_langchain

server = mcp_server("stock", R2CExtension(tools=tools_from_langchain([place_order])))
```

Limits to know:

- A pause survives a restart only with a **durable checkpointer with async
  support**, for example `AsyncSqliteSaver` of `langgraph-checkpoint-sqlite`. The
  extra brings none. With the in-memory one the wrap warns once, and an answer
  after a restart ends `lost`. A synchronous-only saver fails at the first run.
- The same pause has the same request ids after a restart.
- In `batched` mode the answers already given for a batch are kept **in memory
  only** (at most 1024 batches). After a restart the batch is asked again from its
  first call. Use `per_call` where a restart in the middle matters.
- The newest piece of the reply is held until the next one arrives, so that the last
  one can say it is the last: expect one chunk of delay.
- `reasoning` and `expose_tools` are off because the model's thinking is not its
  answer, and a tool's arguments and result can hold what the caller should not see.
- A provider's exception text reaches the caller as it is (the run ends `failed`
  with the message). Catch and reword it in your graph if it names a key or a host.
- A pydantic structured reply is stored in the checkpoint, and LangGraph warns
  that an unregistered type will be blocked in a future version: list it in
  `allowed_msgpack_modules` of the checkpointer's serializer.
- The queue between the graph and the door is unbounded: a slow caller makes the
  tokens wait in memory.
- A structured reply that ends `completed` under `ToolStrategy` has **no reply
  text**: LangChain streams none for it. (`ProviderStrategy` streams the JSON.)
- Keep the ids of the requests a graph writes itself distinct: two asked at once
  cannot be told apart (the first one in order takes the answer), and two asked one
  after another under the same id let a repeated answer to the first pass as the
  answer to the second. Ids the bridge makes (middleware approvals, the fallback
  question, `input_required`) are distinct already.
- The answer to an `input_required` question starts a new turn of the same task. On
  the A2A door that turn's text is appended to the `reply` artifact the first turn
  had closed with `last_chunk`, so a client that stops reading a task at the first
  `last_chunk` does not see it (the door's behaviour, not changed by the bridge).
- In `batched` mode a call is decided once: a second answer for a call that already
  has a decision ends the run `lost`, and the first decision stands.
- One run per thread at a time. The doors keep it inside a process, but the bridge
  has no lock of its own: two processes that share a checkpointer must not resume
  one thread at once, or a tool can run twice.
- The graph's thread is the thread id the door gives, which keys an owner and a
  context (a graph served to two callers keeps their conversations apart).
- A URL part of the caller's message reaches the model as it was sent (the bridge
  reads, converts and drops nothing). If your model integration downloads URLs in
  your process, restrict the schemes and hosts there.

## Install

| Install | Pulls in | For |
|---|---|---|
| `ext-r2c` | pydantic, jsonschema | the core: models, forms, checks, run events |
| `ext-r2c[a2a]` | a2a-sdk | the A2A door, A2A callers |
| `ext-r2c[mcp]` | mcp, PyYAML | the MCP door, MCP callers, MCP Skills |
| `ext-r2c[langgraph]` | langchain, langchain-core, langgraph (no checkpointer) | agents written with LangChain / LangGraph |

`Remote` has no extra of its own: it needs the extras of the doors it exposes,
for example `ext-r2c[a2a,mcp,langgraph]` for a LangGraph agent on both doors.

See the [repository](https://github.com/timezlab/ext-r2c) for the standard.
