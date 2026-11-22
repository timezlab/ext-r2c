# ext-r2c (Python)

Python SDK for **R2C (Remote-to-Caller)**, an extension for A2A and MCP that
lets a remote ask its caller a question, request an approval, and hand back
artifacts.

> Pre-alpha. The standard v1 is written (draft). This package ships its
> identifiers, its JSON Schemas, the protocol-free core (`ext_r2c.core`), the
> A2A door (`ext_r2c.a2a`), the MCP door (`ext_r2c.mcp`) and MCP Skills, which
> is a separate MCP extension served by the same package.

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

## Install

| Install | Pulls in | For |
|---|---|---|
| `ext-r2c` | pydantic, jsonschema | the core: models, forms, checks, run events |
| `ext-r2c[a2a]` | a2a-sdk | the A2A door, A2A callers |
| `ext-r2c[mcp]` | mcp, PyYAML | the MCP door, MCP callers, MCP Skills |
| `ext-r2c[langgraph]` | langchain, langgraph | agents written with LangChain / LangGraph |

See the [repository](https://github.com/timezlab/ext-r2c) for the standard.
