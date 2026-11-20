# One adapter, `Remote`, exposing A2A, MCP, or both

**Status:** accepted, 2026-11-20.

## Context

The approved brief had one adapter per situation: `serve(graph, card)` for a LangChain agent
(A2A only), a wrapper around a hand-written a2a-sdk `AgentExecutor`, and an MCP server helper.
It also said "no framework bridge on the server side: an MCP server is a set of tools, not an
agent". A remote that wants to offer its agent to A2A callers **and** its tools and skills to
MCP clients would then write two pieces of code against two classes, and the two would drift
(two cards, two tool lists, two approval rules).

What an MCP server exposes today (spec 2026-07-28): core tools, resources (and templates,
`subscriptions/listen`), prompts, completion, `server/discover`, input from the client through
MRTR; official extensions MCP Apps (`io.modelcontextprotocol/ui`), Tasks
(`io.modelcontextprotocol/tasks`, beta) and Skills (`io.modelcontextprotocol/skills`, SEP-2640:
`skills/list`, `skills/get`, `resources/directory/read`, `skill://` resources). The MCP Python
SDK 2.3.0 has tools, resources, prompts, completion, Apps, and a pluggable `Extension`
(SEP-2133: tools, resources, methods, `intercept_tool_call`); it has neither Skills nor Tasks.

"Skills" means two different things: an A2A `AgentCard.skills` entry advertises what the agent
does when sent a message (no files); an MCP skill is a `SKILL.md` package the client loads for
**its own** model, telling it how to use the server's tools.

LangGraph is the first agent framework, not the last. Others (Google ADK, the OpenAI Agents
SDK, the Claude Agent SDK) pause for a human in two different ways:

- **Checkpoint pause** (LangGraph `interrupt()`, ADK resumability, OpenAI `RunState`): the
  framework saves the stopping point and returns; a later call resumes it. Survives a restart.
- **Live pause** (Claude Agent SDK `can_use_tool` / `AskUserQuestion`): the run waits on an
  `await` in memory. Lost on a restart; over MCP the retry must reach the same process.

## Decision

### 1. `Remote` is the only remote-side adapter, configured declaratively

A remote's owner writes one configuration against one class and chooses, as a setting, which
doors it opens: A2A, MCP, or both. Tools, the agent and skills are **passed in**: the modules
that define them never import R2C.

```python
# myapp/tools.py and myapp/agent.py: plain LangChain code, no ext_r2c import
TOOLS = [query_data, publish_page]
graph = create_agent(model, tools=TOOLS, checkpointer=...,
                     middleware=[HumanInTheLoopMiddleware(interrupt_on={"publish_page": True})])

# myapp/serve.py: the only module that knows R2C
from pathlib import Path
from ext_r2c import Remote, Skills
from ext_r2c.bridges.langgraph import LangGraphAgent

remote = Remote(
    name="report-service", description="Builds monthly reports", version="1.0.0",
    expose=["a2a", "mcp"],                                  # or ["a2a"], or ["mcp"]
    agent=LangGraphAgent(graph, card_skills=[AgentSkill(id="build-report", ...)]),
    tools=TOOLS,                                            # MCP tools
    approve=["publish_page"],                               # MCP: ask approval before running
    skills=Skills(Path(__file__).parent / "skills", exclude=["drafts-*"]),
)
app = remote.app()                                          # one ASGI app
```

Names are illustrative; the spec of `007-remote` settles the API (renumbered 2026-11-20, when
MCP Skills became `005-mcp-skills`).

| Passed in | A2A door | MCP door |
|---|---|---|
| `agent=` an `AgentSource` (e.g. `LangGraphAgent(graph)`) | the agent: card, streamed runs, questions, approvals, artifacts | one tool `{message, context_id?}` only with `mcp_tool=True` (off by default) |
| `agent=` a hand-written a2a-sdk `AgentExecutor` | the agent | never (it would mean translating A2A events into MCP) |
| `tools=` plain callables or framework tools | not exposed (A2A has no tools) | tools |
| `approve=` tool names (or per-tool settings: `answer_by`, `approver_role`, `expires_in`) | — | asks `approval` through MRTR before running the tool |
| `skills=` | not on the card | MCP skills (`skill://…`), implemented here on the SDK's `Extension` |
| `resources=`, `prompts=` | — | passed through to the MCP server |
| `mcp_server=` an existing `MCPServer` | — | R2C added to it as an `Extension` |

- An enabled door with nothing to serve, or something passed in that no enabled door serves,
  is an error when the app is built, not a silent no-op.
- A door whose extra is not installed fails with a message naming the extra.
  `import ext_r2c` works with no extra installed.
- The app mounts the A2A JSON-RPC endpoint and agent card at the root and MCP streamable HTTP
  at `/mcp` (paths configurable). `Remote` only composes: no authentication, no HTTP middleware
  of its own, no protocol logic. Identity stays with A2A, MCP and the deployment.

### 2. Approvals are declared where each caller path is

- **The agent calling a tool:** approval is the agent framework's own configuration (for
  LangGraph, `HumanInTheLoopMiddleware(interrupt_on=...)`); the bridge turns the pause into an
  R2C `approval`.
- **An MCP client calling a tool directly:** approval is `approve=` on `Remote`.

`Remote` does not read the agent's configuration to derive `approve=`: every framework
configures approval differently, and a derivation would have to be written per framework. The
cost is that the two lists can drift; the docs say so, and a bridge MAY later offer a check.

### 3. Skills are read from folders, with include and exclude

`skills=` takes a folder, a list of folders, or `Skills(root, include=[...], exclude=[...])`:

- A folder that contains `SKILL.md` is one skill; a folder whose subfolders contain `SKILL.md`
  is a set of skills. Relative paths resolve against the working directory, so
  `Path(__file__).parent / "skills"` is the safe form.
- `include` / `exclude` are glob patterns on the skill name (the folder name); `exclude` wins.
- `exclude_files` are glob patterns on files inside a skill. Hidden files and folders,
  `__pycache__` and editor leftovers are excluded by default.
- Checked when the app is built: the frontmatter `name` equals the folder name, `description`
  is present, at most 512 files and 16 MiB per skill (SEP-2640), no symlink leaving the root.
- On the MCP door every kept file is a resource `skill://<name>/<path>`; `skills/list` returns
  each skill's `uri`, `frontmatter` and files with `sha256` digest and size; content is read
  with `resources/read`.

Card skills (`card_skills=` on the agent source) and MCP skills are never derived from each
other: an A2A caller cannot fetch a `SKILL.md`, so listing it on the card would advertise
something the agent does not do.

### 4. Three extension points, so new frameworks need no change to `Remote`

| Extension point | Interface in `core` | v1 ships | Later |
|---|---|---|---|
| Agent | `AgentSource`: card info; `run(input, ctx)` yielding run events; supports both pause styles: return an `Ask` and be `resume`d later (checkpoint), or `await ctx.ask(...)` inside the run (live) | `LangGraphAgent` | ADK, OpenAI Agents SDK, Claude Agent SDK bridges |
| Tool | `ToolSpec`: name, description, input schema, async `call` | plain callables (`core`), LangChain tools (`bridges.langgraph`) | each framework's tool type |
| Door | A2A, MCP | both | fixed: two protocols |

- `Remote` imports **no bridge**: the owner passes in an object that satisfies `AgentSource`.
  Adding a framework adds a module under `bridges/` (and an extra), nothing else.
- A framework without a bridge works by implementing `AgentSource` directly; a third party may
  publish one as its own package.
- Every bridge passes one shared conformance suite (approval, deny with reason, re-ask, expiry,
  restart for checkpoint sources, streamed reply, activity, usage).
- A live-pause source survives no restart (the task ends `failed` with a clear reason) and,
  over MCP, needs the retry to reach the same process; both limits are documented per bridge.

### 5. The agent is an MCP tool only when asked

`mcp_tool=True` on the agent source adds one tool with input `{message, context_id?}` and a
result of the reply text, `structuredContent {context_id}` and file artifacts. Through MCP the
agent has no token streaming, no `live` artifact mid-run, approvals only through elicitation
(`answered_by: person`), and long runs meet request timeouts until MCP Tasks is supported;
`activity` still flows through `notifications/progress`.

### 6. One thread per door

`thread_id = f(door, owner, context_id)`. A conversation started over A2A is not continued over
MCP with the same id. The two doors resolve the owner independently, and a shared thread would
also need a cross-door lock for "one unfinished task per context".

### 7. Module layout and import direction

```
ext_r2c/
  core/                models, forms, run events, AgentSource, ToolSpec   (pydantic, jsonschema)
  a2a/                 A2A door and caller-side client                     extra [a2a]
  mcp/                 MCP door (an MCP SDK Extension), Skills, client     extra [mcp]
  bridges/langgraph/   LangGraphAgent; LangChain tools → ToolSpec          extra [langgraph]
  bridges/<other>/     later, one extra each
  remote/              Remote
```

```
core ← a2a          core ← mcp          core ← bridges.*          core ← remote
```

`a2a`, `mcp` and the bridges never import each other; `remote` imports `core` and loads a door
only when it is enabled. Both doors read the same neutral run; neither translates the other.

## Alternatives

- **Separate adapters per protocol and framework** (the brief). Two pieces of code for a remote
  that serves both, and they drift.
- **Decorators** (`@remote.tool`, `@remote.skill`). Every module defining a tool would import the
  `remote` object (import cycles, tools tied to R2C), and existing LangChain tools could not be
  reused as they are.
- **Detecting the framework from the object passed in.** Magic that breaks on a framework
  upgrade; an explicit bridge object is one import.
- **Deriving MCP approvals from the agent's configuration.** One source of truth, but written per
  framework; rejected while more frameworks are coming.
- **`Remote` as an optional layer over public bindings** (`[serve]` extra). Two public ways to do
  the same thing.
- **A separate package for `Remote`.** A second release train depending on `core` internals
  before they are stable.
- **An A2A ⇄ MCP gateway.** Still rejected: an agent task and a tool call differ in kind.
- **Card skills derived from MCP skills.** Rejected, see decision 3.
- **Agent as an MCP tool by default.** Every remote would expose an expensive, long-running tool
  that a client's model may call in a loop.
- **One thread shared across doors.** Needs one owner resolver for both doors and a durable
  cross-door lock; a wrong owner on either side leaks a conversation. Can be added later as an
  option without changing the wire.

## Consequences

- **Better:** one class, one install, one app; tool and agent modules stay free of R2C; a remote
  that only wants MCP or only A2A writes the same configuration with a different setting; a new
  framework is a new bridge, not a change to `Remote` or the doors.
- **Worse:** the repository owns a small server-composition layer as well as an extension.
  `AgentSource` and the run events become a public design surface that must serve both pause
  styles. MCP approvals and the agent's approvals are declared separately and can drift. MCP
  Skills are implemented here until the MCP SDK ships them.
- **Must now be true:**
  - `Remote` composes and never translates between protocols; a hand-written `AgentExecutor`
    is A2A-only.
  - `remote` imports no bridge and stays thin: anything beyond mounting the doors (auth,
    routing rules, deployment) is out of scope and needs a new decision.
  - `AgentSource` is tested with a checkpoint-style and a live-style source from the first spec
    that defines it, even while only the LangGraph bridge ships.
  - Each door is tested by real round trips through its own protocol SDK, every bridge by the
    conformance suite, and `remote` by one source served through both doors in one process.
  - Constitution principle VIII lists the import direction above.
