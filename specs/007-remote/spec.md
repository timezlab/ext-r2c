# Feature Specification: `Remote`, one adapter for A2A, MCP or both (`ext_r2c.Remote`)

**Feature Branch**: `main` (no branch; the directory is `specs/007-remote`)

**Created**: 2026-11-23

**Status**: Draft

**Input**: User description: "007-remote — `ext_r2c.Remote`, the only remote-side adapter (WORKSTATE.md
spec 7; ADR docs/design-docs/one-remote-two-doors.md). One adapter wraps an existing remote and
exposes it over A2A, MCP or both from one ASGI app, so the remote's own logic does not change
(principle III). Configured declaratively: `expose` = A2A, MCP or both; `agent=` (an `AgentSource`,
such as `LangGraphAgent(graph)` from spec 006, or an a2a-sdk executor); `tools=` (`ToolSpec`s, with
`tool_from_langchain` for LangChain tools); `approve=` (MCP approvals on `Remote`, separate from the
agent framework's own); `skills=` (folders, include / exclude, spec 005); `resources=`, `prompts=`,
`mcp_server=`; `mcp_tool=True` makes the agent an MCP tool; build-time errors for a door with
nothing to serve, something no door serves, or a missing extra. `Remote` imports no bridge
(principle VIII). Success criteria 1-5 of the design brief served by `Remote`, plus one agent
through both doors in one process (one thread per door). Settle what the ADR and the brief left
open for `Remote` (names, the exact constructor, how two doors share one agent and one thread, how
an ASGI app is mounted, errors at build time). Read the INSTALLED a2a-sdk and MCP SDK packages, not
memory."

## Context

Specs 002 to 006 built every piece `Remote` composes. Nothing composes them yet.

| Spec | What exists today | Public names |
|---|---|---|
| 002 core | the neutral run, `AgentSource` (checkpoint or live), `Driver`, `ToolSpec`, `thread_id(door, owner, context_id)` | `ext_r2c.core` |
| 003 A2A door | an A2A app for any `AgentSource` or hand-written executor | `agent_card`, `SourceExecutor`, `a2a_app`, `R2CRequestHandler`, `R2CTask`, `PendingMemory` |
| 004 MCP door | an MCP server with R2C as an SDK extension, tools, `approve=`, the agent as one tool | `R2CExtension`, `mcp_server`, `SourceTool`, `Approve`, `ToolOutput` |
| 005 MCP skills | MCP Skills from folders, as a second SDK extension that is not R2C | `SkillsExtension`, `SkillsClient` |
| 006 LangGraph bridge | a compiled graph as an `AgentSource`; LangChain tools as `ToolSpec`s | `LangGraphAgent`, `tool_from_langchain`, `tools_from_langchain` |

An owner who wants both doors today writes two programs' worth of glue: build a card, an executor, an
app and a store for A2A; build an extension, a server, a session policy and a path for MCP; run
both apps' start and stop by hand; and keep the two apart. The ADR
[one remote, two doors](../../docs/design-docs/one-remote-two-doors.md) decided the answer: one class,
`Remote`, configured declaratively, with the agent, the tools and the skills **passed in** so the
modules that define them never import R2C. This spec turns that decision into a settled API and
checks it against what the installed SDKs do now.

A remote's owner writes one module that knows R2C:

```python
from ext_r2c import Remote
from ext_r2c.bridges.langgraph import LangGraphAgent, tools_from_langchain

remote = Remote(
    expose=["a2a", "mcp"],
    url="https://remote.example.com",                          # where callers reach it
    agent=LangGraphAgent(graph, card=CardInfo("report-service", "Builds monthly reports", "1.0.0")),
    tools=tools_from_langchain(TOOLS),                         # MCP tools
    approve=["publish_page"],                                  # MCP: ask before a direct call
    skills="skills/",                                          # MCP skills (spec 005)
)
app = remote.app()                                             # one ASGI app
```

### What the installed packages do (checked 2026-11-23)

Read from the wheels in the project's test environment: `a2a-sdk` 1.3.1, `mcp` 2.3.0, `starlette`
1.10.0, and the code of specs 003 to 006. The ADR was written before these were read in detail; where
they differ from it, this spec follows them and says so. Each finding says what this spec does with it.

1. **An existing `MCPServer` cannot take R2C afterwards.** The SDK applies a server's extensions in
   its constructor and offers no way to add one later (`MCPServer(extensions=...)` only; the code
   marks them "fixed"). R2C's interceptor (approvals, the agent tool) is an extension, and the door's
   own `mcp_server(...)` refuses an extension already served. So the ADR's `mcp_server=` row,
   "R2C added to an existing `MCPServer`", cannot be built on this SDK. *This spec drops it (D3) and
   gives the MCP server's own settings a place instead.*
2. **Each door's app carries its own start and stop, and a parent does not run them.** The MCP app
   runs the streamable-HTTP session manager as its lifespan (once per manager); the A2A app closes
   its request handler in its lifespan. A probe of Starlette's `Mount` showed that a mounted
   sub-app's lifespan never runs, so a naive "mount both" serves a dead MCP door and leaks the A2A
   handler. The same probe showed `Mount("/mcp")` answers `/mcp` with `404` (only `/mcp/` matches),
   while a client configured with `.../mcp` sends exactly that. *The app must run both lifespans and
   answer `/mcp` exactly (FR-021 to FR-023).*
3. **Identity is two mechanisms, not one.** The A2A door reads the user a Starlette middleware set
   (`request.user`) through an `OwnerResolver`, which also keys the task store. The MCP door reads the
   principal of the SDK's own bearer path (`token_verifier` inside the MCP app), or an `owner`
   callable of `R2CExtension` that sees the HTTP request (`ctx.request`). An authentication
   middleware placed outside `a2a_app` therefore protects the A2A door and leaves the MCP door
   open. *`Remote` offers one place outside both doors for it, and says what each door reads (D5, FR-027
   to FR-029).*
4. **Two extensions serve one server each.** `R2CExtension` takes the session policy's TTL from the
   server that serves it and refuses a second one; `SkillsExtension` scans its folders when it is
   built and serves one server. *One `Remote` builds one app (D4).*
5. **The A2A card needs a URL, and nothing can supply it.** `a2a_app` takes a ready `AgentCard`; the
   card's interface carries the JSON-RPC URL; a2a-sdk serves the card as written and does not read the
   request's host. A wrong default would advertise the wrong address silently. *`url` is required
   when A2A is exposed (D2).*
6. **Both doors drive one source object with their own `Driver`.** `SourceExecutor(source)` and
   `SourceTool(source)` each build a `Driver`; their threads differ by door
   (`thread_id("a2a" | "mcp", owner, context_id)`), so two drivers never run one thread.
   `LangGraphAgent` is documented safe to share across threads (spec 006). *One source feeds both
   doors; a source that cannot be shared says so in its own contract (FR-009).*
7. **`ToolSpec` has two producers, in two places.** `tool_from_function` lives in the core;
   `tool_from_langchain` lives in the LangGraph bridge, which `Remote` must not import (principle
   VIII), and no duck-typing on a LangChain object is allowed without importing it. *`tools=` takes
   `ToolSpec`s, `SourceTool`s and plain callables; a LangChain tool goes through the bridge's
   converter in the owner's module (D6).*
8. **The MCP app guards the host by default.** `streamable_http_app` turns DNS-rebinding protection on
   for its default `127.0.0.1` host and answers a request with another `Host` header `421` until
   `transport_security` names it. *A deployment's host rules are a setting of the MCP door that `Remote` passes through
   (FR-027).*
9. **The test helpers run one door each.** The in-process transports and the MCP harness build one
   app per door and start the MCP session manager by hand. *`Remote`'s tests need one app served
   in process with its own lifespan, for an A2A client and an MCP client at once (FR-037).*

## User Scenarios & Testing *(mandatory)*

The "user" of this feature is a developer: the owner of a remote (an agent, a set of tools, or both)
who wants it callable over A2A, MCP or both, with R2C's questions, approvals, activity and artifacts,
without restructuring it (constitution III).

### User Story 1 - One line, one app, both doors (Priority: P1)

An owner has a LangGraph agent and a few plain tools. They write one `Remote(...)` and call `.app()`.
An A2A caller and an MCP caller each reach the agent: the agent starts, asks a question, the caller
answers, and the agent finishes with a streamed reply. The graph and the tool modules are the same
as before and import nothing from R2C.

**Why this priority**: it is the point of the feature. Until it works, the doors have no entry point
a remote's owner can use.

**Independent Test**: serve one `Remote` (real graph with a scripted model, a real checkpointer, two
tools, `mcp_tool=True`) as one app in process, with its own lifespan. Drive it with the A2A client
and with the MCP client of this repo, each through a pause and an answer, and compare the reply text
and the end states.

**Acceptance Scenarios**:

1. **Given** a `Remote` with `expose=["a2a", "mcp"]`, **When** `.app()` is called, **Then** one ASGI app
   comes back that serves the A2A card and JSON-RPC and the MCP endpoint, and no extra step starts
   either door.
2. **Given** the agent pauses with a question, **When** an A2A caller answers, **Then** the same task
   continues and completes; **When** an MCP caller answers the same agent through its tool, **Then**
   that call continues and completes.
3. **Given** one context id used over both doors by one person, **When** each door runs a turn,
   **Then** the two conversations do not see each other: one thread per door (FR-030).
4. **Given** a caller that did not activate R2C on either door, **When** it calls, **Then** it gets
   text and standard artifacts (constitution III, IV).
5. **Given** the modules that define the graph and the tools, **When** `Remote` serves them, **Then**
   neither module is edited and neither imports `ext_r2c`.

---

### User Story 2 - A mistake fails when the app is built, not at the first request (Priority: P1)

An owner passes something no door will serve, enables a door with nothing to serve, or lacks an
extra. They find out in the module that builds the app, from a message that names the argument and
what to do, not from a caller's first request.

**Why this priority**: the ADR chose "an error, not a silent no-op". Without it, a typo in
`approve=` leaves a tool unguarded, which is a safety fault, not a nuisance.

**Independent Test**: one test per row of the table in FR-032, each asserting the error type, that
the message names the argument, that the app was not built, and (for the extra) that only the missing
extra is named.

**Acceptance Scenarios**:

1. **Given** `expose=["mcp"]` and only an agent, **When** the `Remote` is built, **Then** it fails
   naming the agent as served by no door and `mcp_tool=True` as the way to serve it.
2. **Given** `approve=["publish_pgae"]` (a typo) and tools without that name, **When** it is built,
   **Then** it fails naming `publish_pgae`, not silently guarding nothing.
3. **Given** `expose=["a2a"]` and `tools=[...]`, **When** it is built, **Then** it fails naming
   `tools`, which A2A does not serve.
4. **Given** the `[a2a]` extra is not installed, **When** `Remote(expose=["a2a"], ...)` is built,
   **Then** it fails with a message naming `ext-r2c[a2a]`; `import ext_r2c` and
   `from ext_r2c import Remote` still work.
5. **Given** several mistakes at once, **When** it is built, **Then** one error lists all of them, so
   the owner fixes them in one pass.

---

### User Story 3 - Approvals sit where each caller path is (Priority: P1)

An agent calls a tool that needs a person's approval, and an MCP client calls the same tool directly.
The first is the agent framework's own configuration (for LangGraph, the middleware's list); the
second is `approve=` on `Remote`. Each asks a person; neither is answered by a model or by `Remote`.

**Why this priority**: principle V. A guard that is declared in the wrong place, or one that a typo
disables, is the failure mode of this feature.

**Independent Test**: serve a graph whose tool `publish_page` the middleware gates, and the same tool
in `tools=` with `approve=["publish_page"]`. Through A2A, the agent's call asks an approval and the
tool runs once after `allow`, never after `deny` (brief criteria 1 and 2). Through MCP, a direct call
asks an approval through elicitation and runs once after `allow`.

**Acceptance Scenarios**:

1. **Given** the agent calls a gated tool through A2A, **When** the caller answers `allow`, **Then**
   the tool body ran exactly once and the task is `completed`; **When** it answers `deny` with a
   reason, **Then** the tool did not run, the model received the reason, and the task is `completed`
   (brief criteria 1 and 2).
2. **Given** an answer that fails the schema, **When** it is sent, **Then** the same request is
   asked again with the same id and `errors`, and the run lives (criterion 3).
3. **Given** `approve=["publish_page"]`, **When** an MCP client calls `publish_page` directly,
   **Then** the first round is an approval, the tool does not run before `allow`, and it runs at most
   once.
4. **Given** the agent's own approval list and `approve=` name different tools, **When** both
   callers act, **Then** each list governs only its own path, and `Remote` read neither from the
   other (the drift is documented, not derived away).
5. **Given** any approval `Remote` serves, **Then** it never has `answer_by: caller`, `Remote` offers
   no way to auto-answer one, and `approve=` names that are the agent's own tool are refused.

---

### User Story 4 - A restart in the middle (Priority: P1)

A remote is paused waiting for an answer and the process restarts. With a durable task store and
checkpointer on the A2A side, and fixed request-state keys on the MCP side, the answer sent after the
restart continues at the right place, through the app `Remote` built.

**Why this priority**: brief criterion 4; a pause that does not survive a restart is not usable for
approvals that take hours.

**Independent Test**: build the app, pause on a question, drop the app and every in-memory object,
build a new `Remote` over the same SQLite files and keys, answer, and check the tool body ran once.
Once per door.

**Acceptance Scenarios**:

1. **Given** a paused A2A task and a rebuilt app over the same durable store and checkpointer,
   **When** the answer arrives, **Then** the task completes and the tool ran once.
2. **Given** a paused MCP call and a rebuilt app with the same request-state keys, **When** the retry
   arrives, **Then** the call completes.
3. **Given** the A2A task store or the MCP keys are not given, **Then** `Remote` uses the doors'
   in-memory defaults and gives one `UserWarning` for that door (a restart then loses the pause),
   as `LangGraphAgent` does for an in-memory checkpointer.

---

### User Story 5 - MCP skills, resources, prompts and the agent as a tool (Priority: P2)

An owner also wants MCP clients to load a skill folder, read a resource, list a prompt, or call the
agent as one tool. They pass them to the same `Remote`.

**Why this priority**: the ADR's table lists them, but each is an addition to a working one-line
`Remote`, not part of it.

**Independent Test**: serve `skills=` with two skill folders (one excluded), one resource, one
prompt and `mcp_tool=True`; list and read each through the SDK client and `SkillsClient`; check the
A2A card is unchanged by them.

**Acceptance Scenarios**:

1. **Given** `skills="skills/"`, **When** an MCP client lists skills, **Then** each kept skill is
   listed and readable as spec 005 defines, and a bad folder fails the build with `SkillsError`
   unchanged.
2. **Given** `mcp_tool=True`, **When** an MCP client lists tools, **Then** one more tool takes
   `{message, context_id?}`; without it, none exists (the default).
3. **Given** the agent's `card` lists a card skill, **When** the MCP skills are listed, **Then** the
   card skill is not among them, and the MCP skills are not on the card.
4. **Given** `resources=` and `prompts=` objects of the MCP SDK, **When** a client lists them,
   **Then** they are served as given.

---

### User Story 6 - A remote that is already an a2a-sdk executor (Priority: P2)

An owner already has a hand-written `AgentExecutor` that asks in plain text. They pass it as
`agent=` with `expose=["a2a"]`. A caller that knows R2C receives its text-only `input-required` and
continues in text; one that does not works as it did.

**Why this priority**: brief criterion 5, and the proof that `Remote` adopts a remote that never heard
of R2C.

**Independent Test**: an executor written in the shape of the official Currency sample (a scripted
model in place of a provider; it imports nothing of R2C) served by `Remote(agent=executor, ...)`;
an activated `R2CClient` gets the text-only `input-required` and answers in text.

**Acceptance Scenarios**:

1. **Given** the executor is passed unchanged, **When** a caller sends a message, **Then** the card
   declares R2C with `required: false` and the executor's own text flow works end to end.
2. **Given** `expose=["mcp"]` with only an executor, or `mcp_tool=True` with one, **When** built,
   **Then** it fails: an executor is A2A-only (the ADR: it would mean translating A2A events into MCP).
3. **Given** `expose=["a2a", "mcp"]`, an executor and `tools=`, **Then** the executor is served on
   A2A and the tools on MCP.

---

### User Story 7 - Only one door, and each door's own deployment settings (Priority: P3)

An owner who wants only A2A, or only MCP, writes the same configuration with a different `expose`. A
deployment's own settings (a durable task store, an owner resolver, host rules for MCP, a request-state
policy, an authentication middleware) reach the door they belong to.

**Why this priority**: it is what makes `Remote` usable outside tests; it adds no behaviour of its own.

**Independent Test**: `expose=["a2a"]` and `expose=["mcp"]` each serve only their door (the other door's
paths answer `404`, its module is not imported); a store, a resolver, a policy and an allowed host each
visibly take effect on their door.

**Acceptance Scenarios**:

1. **Given** `expose=["a2a"]`, **Then** the app serves the card and JSON-RPC only, and no `mcp`
   module was imported. **Given** `expose=["mcp"]`, **Then** the reverse.
2. **Given** a durable `task_store` and an `owner_resolver` for A2A, **Then** they are the ones the
   door and its store use (spec 003's rule that both share one resolver holds).
3. **Given** MCP `security` keys and an allowed host, **Then** a paused call survives a rebuild and a
   request with that `Host` is served.
4. **Given** a `middleware` list for `Remote`, **Then** it wraps both doors; and if MCP is exposed
   with no way to tell its callers apart, one warning says every MCP caller is one owner (D5).

---

### Edge Cases

- `expose` is missing, empty, has an unknown door (`"grpc"`), or repeats one: an error (D1).
- A2A is exposed and there is no `agent`, or there is no `url`; or no card information at all
  (`card=` and `agent.card` both absent, as with an executor or tools only): an error naming the
  missing piece.
- MCP is exposed with no tools, no agent tool, no skills, no resources and no prompts: an error
  ("nothing to serve"). One `tools=` entry, or `mcp_tool=True`, is enough.
- `mcp_tool=True` and a tool in `tools=` named like the agent tool (`agent` by default): an error; two
  tools never share a name.
- `approve=` names a tool that does not exist, or the agent's own tool: an error. `approve=` is
  never a no-op.
- A LangChain `BaseTool` (or anything that is not a `ToolSpec`, a `SourceTool` or a plain callable)
  in `tools=`: an error that says the bridge's converter turns it into a `ToolSpec`.
- A plain callable with `*args`, no type hints or a leading underscore: the core's own refusal passes
  through unchanged.
- The A2A JSON-RPC path equals the MCP path, or the MCP path is `/.well-known/...`: an error.
- A trailing slash on the MCP path (`/mcp/`): not promised; `/mcp` exactly is (finding 2).
- `.app()` called twice on one `Remote`: the second raises (D4); a new `Remote` builds a new app.
- A door fails while the app starts: the other door is stopped too; nothing is left running.
- The same context id over both doors by one person: two threads, never one (FR-030).
- A source of the live style over MCP: it needs the retry to reach the same process (the ADR's
  stated limit); `Remote` neither hides nor fixes it.
- An owner mounts the app inside a larger ASGI app: that app must run this app's lifespan; the README
  says so.
- A card skill and an MCP skill with the same name: unrelated; no error (FR-018).
- The agent's own approval list and `approve=` disagree: allowed, documented, never derived.

## Requirements *(mandatory)*

### Functional Requirements

**Construction**

- **FR-001**: `Remote` MUST be importable as `from ext_r2c import Remote`, and importing it MUST work
  with no extra installed. Its constructor takes keyword arguments only: `expose`, `agent`, `card`,
  `url`, `tools`, `approve`, `skills`, `resources`, `prompts`, `mcp_tool`, `middleware`, `a2a`, `mcp`,
  `limits` and `clock` (the shape is in D1; types are the plan's contract).
- **FR-002**: `expose` MUST be given, MUST hold one or two of `"a2a"` and `"mcp"`, and MUST NOT repeat
  one. There is no default and no inference from what else is passed (D1).
- **FR-003**: The remote's card information (name, description, version, card skills) MUST be one
  `CardInfo`: `card=` when given, else `agent.card` when the agent is an `AgentSource`. The same
  information names the MCP server and its version. When neither source exists (an executor, or
  tools only), construction fails, whichever door is exposed.
- **FR-004**: `agent=` MUST accept an `AgentSource` (served on A2A; on MCP only with `mcp_tool=True`)
  or an a2a-sdk `AgentExecutor` (A2A only). Any other object is a `TypeError` that names both kinds.
- **FR-005**: `Remote` MUST load a door's module only when that door is exposed, MUST import no
  bridge, and MUST NOT edit, wrap in a subclass, or set an attribute on the agent, a tool or a graph
  it is given (constitution III, VIII).
- **FR-006**: A door whose extra is missing MUST fail at construction with an `ImportError` that
  names the extra (`ext-r2c[a2a]` or `ext-r2c[mcp]`), before any other check.

**The agent**

- **FR-007**: On A2A the agent MUST be served as spec 003 serves it: the card from `agent_card(card,
  url)` with R2C declared `required: false`, an executor (`SourceExecutor` for a source, the given
  executor as it is), the store and resolver of the door.
- **FR-008**: With `mcp_tool=True` and an `AgentSource`, the MCP door MUST serve the agent as one tool
  (`SourceTool`, spec 004; default name `agent`, input `{message, context_id?}`). Without it the agent
  MUST NOT be an MCP tool. A tool with another name or schema is built by the owner as a `SourceTool`
  and passed in `tools=`.
- **FR-009**: When both doors serve one `AgentSource`, the same object MUST feed both, each door with
  its own `Driver`. The doors' threads MUST differ by door.
- **FR-010**: An executor MUST be served by the A2A door only. `mcp_tool=True` with an executor, or an
  executor with no A2A door, MUST be a build error.

**Tools and approvals**

- **FR-011**: `tools=` MUST accept `ToolSpec`s, `SourceTool`s and plain callables (converted with
  the core's `tool_from_function`). Anything else MUST be a `TypeError` naming the accepted kinds and,
  for a LangChain tool, the bridge's converter. `Remote` MUST NOT recognise a LangChain tool itself.
- **FR-012**: Two tools with one name, the agent tool included, MUST be a build error.
- **FR-013**: `approve=` MUST accept tool names, or a mapping from name to `Approve` or `bool`
  (spec 004). Every name MUST be a tool of the MCP door; a name that is not, or that is the agent's
  tool, MUST be a build error. `answer_by` is `person` or `approver` only.
- **FR-014**: A tool in `approve=` MUST NOT run before an `allow` or `edit`, and MUST run at most
  once per approval, as spec 004 guarantees, through the app `Remote` built.
- **FR-015**: `Remote` MUST NOT answer an approval, offer an option that does, or read the agent's
  own approval configuration to derive `approve=` (principle V; the ADR's decision 2).

**Skills, resources, prompts**

- **FR-016**: `skills=` MUST accept a folder, a list of folders, or a ready `SkillsExtension`
  (spec 005; include and exclude patterns are its own arguments). It MUST be served on the MCP door
  only. A problem in the folders MUST surface as the `SkillsError` spec 005 defines, unchanged.
- **FR-017**: `resources=` and `prompts=` MUST take the MCP SDK's own objects and serve them as given,
  with no translation.
- **FR-018**: Card skills and MCP skills MUST NOT be derived from each other, in either direction.
- **FR-019**: Each argument MUST be served by exactly the doors this table gives it, and an
  argument whose door is not exposed MUST be a build error (FR-032):

  | Argument | A2A door | MCP door |
  |---|---|---|
  | `agent=` an `AgentSource` | the agent: card, runs, questions, approvals, artifacts | one tool, only with `mcp_tool=True` |
  | `agent=` an a2a-sdk executor | the agent | never |
  | `card=` | the card | the server's name and version |
  | `url=` | the card's address | not served |
  | `tools=` | not served (A2A has no tools) | tools |
  | `approve=` | not served | an approval before a direct call |
  | `skills=` | not on the card | MCP skills |
  | `resources=`, `prompts=` | not served | served as given |
  | `mcp_tool=` | not served | the agent tool |
  | `middleware=`, `limits=`, `clock=` | wraps / applies | wraps / applies |
  | `a2a=` / `mcp=` | its own options | its own options |

**The app**

- **FR-020**: `app()` MUST return one ASGI application. A `Remote` with one door MUST serve exactly
  that door's app.
- **FR-021**: With both doors, the A2A JSON-RPC endpoint (default path `/`) and the agent card (A2A's
  well-known path, at the root) and the MCP streamable-HTTP endpoint (default path `/mcp`) MUST all
  answer. The MCP endpoint MUST answer `/mcp` exactly, with no redirect and no trailing slash
  (finding 2). Both paths MUST be settable.
- **FR-022**: Starting the app MUST start both doors and stopping it MUST stop both, including the
  MCP session manager and the A2A request handler. A failure in one door's start MUST stop the other.
  Nothing outside the app has to start a door.
- **FR-023**: A door's own middleware (A2A's echo of the activated extensions, MCP's authentication)
  MUST wrap that door only. `middleware=` given to `Remote` MUST wrap both doors, outside them.
- **FR-024**: The two paths, and A2A's well-known card path, MUST NOT collide; a collision MUST be a
  build error.
- **FR-025**: `app()` MUST be callable once per `Remote`; a second call MUST raise (D4).
- **FR-026**: `Remote` MUST add no authentication, no routes of its own, no CORS or logging
  middleware, and no protocol logic: it composes (the ADR).
- **FR-027**: The settings that belong to one door MUST reach it: for A2A, `task_store`,
  `owner_resolver` and the JSON-RPC path; for MCP, the request-state `security`, the transport's
  host rules, the SDK's `auth` and `token_verifier`, the path, and the server's other keyword
  arguments, and the `owner` callable of the extension. They are two small option objects, `A2AOptions`
  and `MCPOptions`, which import no SDK at module level, so `Remote` stays importable with no extra.
  A door left on its in-memory defaults (no `task_store` on A2A; no `security` on MCP) while something
  on it can pause (an agent, or an `approve=` entry) MUST give one `UserWarning` per door at build:
  a restart loses the pause (D13).

**Threads and identity**

- **FR-028**: Each door MUST resolve the owner its own way and key its thread as specs 003 and 004
  do (`thread_id(door, owner, context_id)`); `Remote` adds no resolver of its own.
- **FR-029**: When `middleware=` is given and MCP is exposed with no MCP owner source (no SDK
  authentication and no `owner` callable), `Remote` MUST warn once at build that every MCP caller is
  one owner. It is a warning, not an error: a gateway may authenticate in front of the app (D5).
- **FR-030**: A conversation begun on one door MUST NOT continue on the other with the same context
  id (the ADR's decision 6).

**Errors**

- **FR-031**: Wrong-type arguments MUST be a `TypeError` at the first one found. Every other
  configuration problem MUST be collected and raised as one `RemoteError` (a `ValueError`) whose
  message lists each, and which carries them in `problems`. Nothing is half built and no door starts.
- **FR-032**: The cases are:

  | Case | Result |
  |---|---|
  | a door exposed whose extra is missing | `ImportError` naming the extra (FR-006) |
  | `expose` missing, empty, unknown or repeated | `RemoteError` |
  | A2A exposed, no `agent` | `RemoteError`: A2A has nothing to serve |
  | no card information (no `card=` and no source `card`), or A2A exposed with no `url` | `RemoteError` naming `card` or `url` |
  | MCP exposed, no tools, agent tool, skills, resources or prompts | `RemoteError`: MCP has nothing to serve |
  | an agent given that no exposed door serves (an `AgentSource` with MCP only and no `mcp_tool`; an executor with MCP only) | `RemoteError` naming `agent`, and `mcp_tool=True` where it applies |
  | `mcp_tool=True` with an executor | `RemoteError` |
  | `tools`, `approve`, `skills`, `resources`, `prompts`, `mcp_tool` or `mcp` given and MCP not exposed | `RemoteError` naming each |
  | `url` or `a2a` given and A2A not exposed | `RemoteError` naming each |
  | `approve` names no tool, or the agent's tool | `RemoteError` naming the name |
  | two tools with one name | `RemoteError` naming it |
  | the paths collide | `RemoteError` |
  | a skills folder that fails the scan | `SkillsError`, unchanged (FR-016) |
  | `agent`, a tool or an option of the wrong type | `TypeError` |

- **FR-033**: Each message MUST name the argument and say what to do, and MUST carry no secret, no
  absolute path of this host and no file content.
- **FR-034**: An error a build can show MUST NOT wait for a request.

**Packaging, tests and docs**

- **FR-035**: `ext_r2c.remote` MUST import `ext_r2c.core`, the standard library and, per exposed door,
  `ext_r2c.a2a` or `ext_r2c.mcp` at build time; no bridge, no other module of `ext_r2c`. Only
  `ext_r2c/__init__.py` imports it, and not at import time of a door.
- **FR-036**: No new dependency and no new extra: `Remote` needs the extras of the doors it opens.
- **FR-037**: Behaviour MUST start with a failing test, against the installed wheel, with real round
  trips through the real SDK clients in process, and one app served with its own lifespan to an A2A
  client and an MCP client at once (constitution VII). The suite MUST cover the brief's criteria 1 to
  5 through `Remote`, and one agent through both doors in one process.
- **FR-038**: At close the docs MUST say what built: the package README section; the ADR (a dated note
  for `mcp_server=`, for `Skills(...)` and for `url`); the brief (amendment 4); `WORKSTATE.md`,
  `ARCHITECTURE.md`, `AGENTS.md`, `CHANGELOG.md`, and `specs/007-remote/contracts/remote-api.md`.

### Key Entities

- **Remote**: the owner's one configuration. Holds what was passed in; builds the doors' pieces and
  the app. Has no behaviour of its own on the wire.
- **Door**: A2A or MCP; present when it is in `expose`. Each reads the same neutral run; neither
  translates the other.
- **Agent**: an `AgentSource` (both doors) or an a2a-sdk executor (A2A only).
- **MCP tool**: a `ToolSpec` or `SourceTool` the MCP door serves; the agent is one only with
  `mcp_tool=True`.
- **Approval list**: the tool names an MCP client's direct call must have a person approve; separate
  from the agent framework's own.
- **Door options**: `A2AOptions` and `MCPOptions`, the settings of one door's deployment.
- **Build problem**: one entry of `RemoteError.problems`; names an argument and what to do.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The brief's criteria 1 to 4, run through `Remote` on the A2A door with a real graph: an
  approval with the tool's `title` and `subject`; `allow` runs the tool exactly once and the task
  completes; `deny` with a reason does not run it, the model gets the reason, the task completes; an
  answer that fails the schema is asked again with the same id and `errors` and the run lives; a
  paused task answered after a rebuild over the same durable files resumes and the tool ran once.
- **SC-002**: The brief's criterion 5: an executor written in the shape of the official Currency
  sample, importing nothing of R2C, served by `Remote(agent=executor, expose=["a2a"], ...)`, gives an
  activated `R2CClient` a text-only `input-required` that it continues in text.
- **SC-003**: One wrapped real graph, served by one `Remote` as one app in one process, completes a
  pause and an answer for an A2A caller and for an MCP caller; the two threads differ; the same
  context id over both doors does not share a conversation.
- **SC-004**: With `approve=`, an MCP client's direct call to a guarded tool asks an approval and the
  tool body ran 0 times before `allow` and once after; no approval `Remote` serves is
  `answer_by: caller` (a test of every path that makes one).
- **SC-005**: Every row of the table in FR-032 is a test: the error type, a message that names the
  argument, no app built, and the offending argument absent from any success path; several mistakes at
  once give one error listing all.
- **SC-006**: A paused MCP call survives a rebuild with the same request-state keys; without keys,
  `Remote` says once that a restart loses it.
- **SC-007**: The app starts and stops both doors by itself: after a start, each door answers a request;
  after a stop, the MCP session manager and the A2A handler are closed; a failing door start leaves
  neither running.
- **SC-008**: `/mcp` answers with no redirect; the A2A card, the A2A endpoint and the MCP endpoint
  answer at their paths with both doors on; with one door on, the other's paths answer `404` and its
  module is not in `sys.modules`.
- **SC-009**: Callers that did not activate R2C get text and standard artifacts on both doors (0 R2C
  parts or metadata), as specs 003 and 004 guarantee on their own.
- **SC-010**: `import ext_r2c` and `from ext_r2c import Remote` work with no extra; `Remote` with only
  `[mcp]` installed and `expose=["a2a"]` fails naming `[a2a]`; an `ast` scan finds no bridge import
  in `ext_r2c.remote`; the core-only, a2a-only, mcp-only and langgraph-only checks still pass.
- **SC-011**: The full suite passes on the installed wheel on Python 3.11, 3.12 and 3.13; every replay
  is unchanged; `standard/` is untouched.
- **SC-012**: A maintainer who has read only this spec, the plan and the ADR can say, for each argument
  of `Remote`, which door serves it, what happens when no door does, and which identity each door reads
  (checked once, like SC-012 of 006).

## Assumptions

**Out of scope:** authentication and authorization (identity stays with A2A, MCP and the deployment;
`Remote` adds none); an existing `MCPServer` as an argument (D3); a richer A2A card (security schemes,
other input and output modes): the owner who needs one uses `a2a_app` with their own card; a
`Remote.run()` or a command line (the README shows `uvicorn`); bridges for other agent frameworks;
MCP Tasks for long agent runs; A2A push notifications; one thread shared across doors (the ADR:
possible later as an option without changing the wire); decorators; a `Skills(root, ...)` helper
class (the ADR's sketch; `SkillsExtension` takes the same arguments); any change to the standard.

- The doors are as specs 003 and 004 left them, and `Remote` calls their public API only. If the plan
  finds a door needs an additive change (for example a hook to hand `Remote` a door's lifespan), that
  change is listed in the plan and made test first, as `PauseLost` was for 006.
- The tests have no network and no keys; a scripted model stands in for a provider. The graph for
  stories 1, 3 and 4 is the one spec 006's suite uses.
- Python 3.11, 3.12 and 3.13, as the rest of the package.
- The official Currency sample is not vendored (it needs a model and a network); the test executor
  reproduces its protocol behaviour, which is what criterion 5 checks.
- A durable checkpointer and task store are the owner's to bring (the ADR on threads); `Remote` only
  passes them through.
- `uvicorn` and the server that runs the app are the deployment's choice; the SDK already depends on
  one for the MCP extra, and `Remote` does not import it.
- A source of the live style is served as spec 004 serves it; its limits (no restart, same process over
  MCP) are its own and are documented there.

### Decisions taken in this draft

Each has a default, so the plan can start; the maintainer can overrule any of them at the gate.
D3 changes the ADR and is the one the maintainer is asked about first; D5 is a safety choice.

- **D1. `expose` is required, and the constructor is keyword-only.** Default:

  ```python
  Remote(*, expose, agent=None, card=None, url=None, tools=(), approve=(), skills=None,
         resources=(), prompts=(), mcp_tool=False, middleware=(), a2a=None, mcp=None,
         limits=Limits(), clock=None)
  remote.app() -> ASGI app
  ```

  *Why:* the ADR picks "which doors it opens, as a setting"; an inferred default would turn "I
  passed `tools=`" into "MCP is open" and make a typo change what is exposed. One explicit word.
  *Alternative:* default to every door the arguments can serve. Rejected: magic that changes with
  the arguments, which the ADR already rejected for framework detection.
- **D2. One `CardInfo` describes the remote; `url` is required for A2A.** Default: `card=` or the
  source's own `card`; the ADR's `name`, `description` and `version` arguments are not separate (they
  are `CardInfo`'s fields, which spec 006's `LangGraphAgent(card=...)` already takes). The A2A card
  advertises `url` as the JSON-RPC address and the well-known card path stays at the root. *Why:*
  finding 5; one type already exists. *Alternative:* take `name`, `description`, `version` and build
  the card; rejected, a second way to write the same thing.
- **D3. `mcp_server=` is not in v1.** Default: drop the ADR's "an existing `MCPServer`, R2C added to
  it" row. The MCP door builds its own server; an owner with an existing server passes its tools
  (plain callables, which a `@server.tool()` decorator leaves unchanged), resources and prompts, and
  its server's own settings (`instructions`, `auth`, `token_verifier`, `lifespan`, host rules) through
  `MCPOptions`. *Why:* finding 1; the SDK cannot add an extension after construction, so the row cannot
  be built without reaching into private members. *Alternative:* a callable `mcp_server=lambda
  extensions: MCPServer(...)`. Rejected for v1: more surface for a case with a workable path; it can
  be added later without breaking anything. **This changes the ADR; the maintainer's call.**
- **D4. One `Remote`, one `app()`.** Default: a second `app()` raises. *Why:* finding 4; both
  extensions serve one server each, and quietly sharing one agent between two apps hides a double
  serving. *Alternative:* build fresh door pieces on every call; rejected, a source could then be
  driven by two apps at once. A test or a factory builds a new `Remote`.
- **D5. Identity: one place outside both doors, and each door reads its own owner.** Default:
  `middleware=` wraps both doors; A2A's owner is its `OwnerResolver` (the user that middleware sets, by
  default); MCP's owner is the SDK's authenticated principal, or `MCPOptions.owner`, a callable that
  may read the same user from the request. With `middleware=` given, MCP exposed and no MCP owner
  source, one `UserWarning` at build. *Why:* finding 3; an owner who authenticates in one middleware
  must not find MCP callers sharing one owner and one thread namespace silently. A warning, not an
  error, because a gateway may authenticate in front. *Alternative:* an error; rejected, it would
  refuse a valid deployment. *Alternative:* derive the MCP owner from the middleware's user by
  default; rejected, magic across two mechanisms.
- **D6. `tools=` takes `ToolSpec`, `SourceTool` and plain callables only.** Default: a LangChain tool
  is converted in the owner's module with `tools_from_langchain(...)`. *Why:* finding 7 and
  principle VIII; one more import line in the module that already imports the bridge for the agent.
  This narrows the ADR's table ("plain callables or framework tools"). *Alternative:* duck-type a
  LangChain tool; rejected.
- **D7. `approve=` is checked against the tools the door serves.** Default as FR-013. *Why:* an
  `approve=` that names nothing guards nothing, silently; this is the one build error that is a
  safety fault if skipped.
- **D8. `skills=` is a folder, folders, or a `SkillsExtension`.** Default as FR-016. *Why:* spec 005
  built the extension with include and exclude; a second class with the same arguments would be two
  ways to do one thing. The ADR's `Skills(root, ...)` and `exclude_files` are not built (spec 005's
  own notes already say so).
- **D9. The agent as an MCP tool is a boolean on `Remote`.** Default: `mcp_tool=True` builds
  `SourceTool(agent)` with its defaults; a customised tool is a `SourceTool` the owner passes in
  `tools=`. *Why:* the ADR's wording put it "on the agent source", but spec 006's `LangGraphAgent`
  has no such option and a future bridge should not need one. *Alternative:* `mcp_tool` takes
  `bool | SourceTool`; rejected, two ways.
- **D10. Errors: types by kind, collected by pass.** Default as FR-031. *Why:* a wrong type is a
  programming slip with one cause; a combination problem often has several, and the owner should fix
  them together. `RemoteError` is a `ValueError`, as `SkillsError` is.
- **D11. Composition is a small ASGI dispatcher, not a mount.** Default: the app routes `/mcp` to the MCP
  app and everything else to the A2A app, runs both lifespans itself, and wraps both in `middleware=`.
  *Why:* finding 2. This is a plan-level choice stated here because it follows from a tested fact;
  the plan may pick another way that meets FR-021 to FR-024. The MCP app also serves routes beside its
  endpoint when the SDK's `auth` is set (OAuth metadata under `/.well-known/`, which shares a folder
  with A2A's card path), so the plan must route those to it and test one with `auth` on.
- **D12. Door options are two small dataclasses with no SDK import.** Default `A2AOptions` and
  `MCPOptions` (FR-027). *Why:* the deployment settings differ by door and are many; flat keywords
  on `Remote` would be a dozen mostly-unused names, and the dataclasses keep `import ext_r2c` free of
  any extra. *Alternative:* flat keywords; rejected, the constructor would grow with every SDK option.
- **D13. A door on its in-memory defaults warns once.** Default as FR-027's last sentence. *Why:* the
  spec 006 rule for an in-memory checkpointer, applied to the two other places a pause is kept: a
  pause that does not survive a restart should not be a surprise at the first restart. Tests give a
  store and keys, or filter the warning, as spec 006's tests do. *Alternative:* silence, as
  `a2a_app` and `mcp_server` are today; rejected, `Remote` is the entry point most owners will use,
  and the one place that can say it.
