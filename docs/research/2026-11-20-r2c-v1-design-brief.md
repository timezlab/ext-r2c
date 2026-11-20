# R2C v1: design brief

**Status:** approved by the maintainer on 2026-11-20. This brief is the input to the first
Spec Kit feature (`specs/001-standard-v1/`). It records what was decided and why; the
normative text will live in `standard/v1/README.md`, and where the two disagree the standard
wins once it is written.

> **Note 2026-11-20:** the normative text is now written in
> [`standard/v1/README.md`](../../standard/v1/README.md), with its schemas and wire examples,
> and it wins over this brief. Where it differs (D1–D4: the MCP placement of a request, the
> derived answer on MCP, complete MCP messages, a skill in every agent card), the deviations
> are listed in [`specs/001-standard-v1/research.md`](../../specs/001-standard-v1/research.md).
> The body below is kept as written.

**Decisions with their own ADR:** [own extension, not Structured Input](../design-docs/own-extension-not-structured-input.md),
[four kinds](../design-docs/four-kinds.md), [standard and SDK in one repo](../design-docs/standard-and-sdk-in-one-repo.md),
[approval is never answered by a model](../design-docs/approval-never-answered-by-a-model.md),
[thread per owner and context](../design-docs/thread-per-owner-and-context.md),
[activity, usage and the streamed reply](../design-docs/activity-and-usage-kinds.md).

> **Amendment, 2026-11-20 (after approval).** Approved by the maintainer the same day; the
> body below is kept as approved and these points override it:
> - **Six kinds, not four.** `activity` (`type: tool | step | reasoning`, with `state`, `label`,
>   optional `args`, `detail`, `duration_ms`, `parent_id`, `delta`) and `usage` (tokens,
>   `duration_ms`, `cost {amount, currency}`, `model`) join v1. This replaces §3 "Progress: the
>   remote's SSE, not a kind", the "Progress" row of the §1 table, `progress(text)` in §5, the
>   "Progress" row of §6, and the "`plan` / `step` kinds" row of the alternatives.
> - **Reasoning is the remote's decision:** sent only when the remote's owner turns it on.
> - **The reply is one streamed `inline` artifact** (`response: true`), holding all the model's
>   text during the task including narration between tool calls; files stay separate
>   artifacts. This sharpens §2 `artifact` ("the final text answer is still a message or an
>   `inline` artifact") and the "Result" row of §6.
>
> Shapes and placement: the [ADR](../design-docs/activity-and-usage-kinds.md). Exact field
> names are settled by the schemas of `specs/001-standard-v1`.
>
> **Amendment 2, 2026-11-20: one adapter, `Remote`.** See the
> [ADR](../design-docs/one-remote-two-doors.md). It overrides:
> - §4 layout and extras: the LangGraph bridge is `bridges/langgraph` under `core` (no longer
>   `a2a/langchain`); extra `[langgraph]` replaces `[langchain]` and no longer pulls `[a2a]`;
>   one bridge and one extra per agent framework later; a new `remote` module holds `Remote`.
> - §5 and §6: `serve(graph, card)` and the `AgentExecutor` wrapper become what is passed to
>   `Remote` (`agent=LangGraphAgent(graph)` or `agent=<executor>`), exposed over A2A, MCP or
>   both by a setting. Tools, skills, resources and prompts are passed in too; no decorators.
> - §7 "No framework bridge on the server side": the agent may also be one MCP tool, only when
>   asked (`mcp_tool=True`); approvals for direct MCP tool calls are `approve=` on `Remote`,
>   separate from the agent framework's own approval configuration.
> - §3b: `thread_id = f(door, owner, context_id)`; a thread is never shared across doors.
> - Success criteria 1–5 read "served by `Remote`" where they say "served by `serve()`".

## Goal

A party that is called (the **remote**: an A2A agent or an MCP server, running anywhere) can
**ask, request approval, and hand back artifacts** to the party that called it, through **one
standard**, without **changing the remote's own logic**. The remote's owner installs one package
and adds one line. A remote that does nothing still works with an R2C caller, at a lower level
(plain text in, plain text out).

R2C serves every kind of caller: a chat app, another agent, an unattended workflow, a client
with no UI, an off-the-shelf MCP client. It does not depend on where anything is deployed: it
only uses A2A and MCP, and identity and transport are theirs.

## Who hurts today

- **The caller's user.** When a remote agent stops at `input-required`, the question is text
  only: no form, no way to tell it is asking for approval, and the caller's agent may answer on
  the user's behalf without anyone seeing it. Files and live screens from the remote cannot be
  shown properly.
- **The remote's owner.** To ask a person through a caller, they hand-write about 60 lines of
  `AgentExecutor` (see the official A2A LangGraph sample) and invent their own way to describe
  the question. With no common standard, every remote does it differently.

## Constraints found (checked 2026-11-20)

- **A2A 1.0.** `TASK_STATE_INPUT_REQUIRED` is an interrupted state; to continue, the client
  sends a new message with the same `taskId` and `contextId`. Core A2A has no schema field and
  no "decline".
- **A2A extensions** are a specification plus a URI used as a name. The URI is compared as a
  string and never fetched at runtime. Extension data lives in `metadata[<uri>]`. An extension
  must not add enums or change core structures. The client activates extensions with the
  `A2A-Extensions` header.
- **A2A artifacts** already exist (`artifactId`, `name`, `description`, `parts`, `metadata`),
  sent as `TaskArtifactUpdateEvent` with `append` / `lastChunk`. Streaming
  (`SendStreamingMessage`; `message/stream` in 0.3) is SSE carrying `TaskStatusUpdateEvent`
  (state `working` with a text message) and `TaskArtifactUpdateEvent`.
- **a2a-sdk 1.3.1** (read from the wheel: `a2a/types/a2a_pb2.pyi`,
  `server/request_handlers/default_request_handler_v2.py`):
  - Part fields: `text`, `raw`, `url`, `data`, `metadata`, `filename`, `mediaType`.
  - JSON-RPC methods: `SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`,
    `CancelTask`, `SubscribeToTask` (reattach a stream; `tasks/resubscribe` in 0.3).
  - The client **may** set `contextId` on the first message (the SDK uses it as given, or
    generates a UUID). A message with only `taskId` takes its context from the task; a
    `contextId` that differs from the task's is rejected (`InvalidParamsError`).
  - The TaskStore is scoped by owner (`OwnerResolver`, default `resolve_user_scope` from the
    request's identity): nobody else can read or resume your task.
  - The SDK ships only generic extension helpers (`HTTP_EXTENSION_HEADER`,
    `RequestContext.requested_extensions`, `find_extension_by_uri`,
    `validate_required_extensions`). A library per extension is separate, following the
    a2a-samples `timestamp_ext` pattern (`WrapExecutor`).
- **MCP 2026-07-28.** Elicitation is **core**. `tools/call` can return
  `resultType: "input_required"` (MRTR); the client calls again with `inputResponses` and
  `requestState`. `requestedSchema` allows only a flat object (string / number / boolean /
  enum). The client **MUST** "allow users to review and modify their responses before
  sending" and show which server is asking. Tool results carry `text`, `resource_link` and
  embedded `resource` content. `notifications/progress` carries a `message` string.
- **MCP extensions** are named reverse-DNS style; private data lives in `_meta["<prefix>/<key>"]`.
  Naming precedent: repo `modelcontextprotocol/ext-apps`, key `io.modelcontextprotocol/ui`.
- **MCP Python SDK 2.3.0** has MRTR (`InputRequiredResult`, `InputRequiredRoundsExceededError`)
  and `mcp/server/request_state.py` `RequestStateBoundary`, which seals every outgoing
  `requestState` (AES-GCM) and checks TTL, principal and audience on every one sent back.
- **LangChain `HumanInTheLoopMiddleware`.** In 1.3.x it runs at `after_model` and raises one
  `interrupt(HITLRequest{action_requests, review_configs})` for every blocked tool call, resumed
  with `{"decisions": [...]}` in the same count and order. Four decisions: `approve`, `edit`,
  `reject` (with `message`), `respond`; a disallowed decision raises `ValueError`. In **1.5.2**
  the field names are unchanged and `interrupt_mode="per_call"` was added: **one interrupt per
  blocked tool call**, value `ToolApprovalRequest{type: "tool_approval", tool_call_id, name,
  args, description}` plus `response_schema`, answered with one `Decision` keyed by interrupt id
  (`Command(resume={interrupt_id: decision})`). The default is still `"batched"`, but
  `"per_call"` "is planned to become the default in the next major release".
- **The official A2A LangGraph sample does not use `interrupt()`.** It ends the turn with
  `structured_response.status = "input_required"`, text only, written against the 0.3 API, and
  reports progress as `working` status text ("Looking up…").
- **One known deployment target** (a managed app platform) caps each request or stream at
  300 s behind its proxy; it passes WebSocket and SSE; each app is its own site, so an app's
  cookies inside an iframe are third-party cookies. This is a property of that deployment,
  not of the standard: streams must survive a reconnect (`SubscribeToTask`).

**Assumption:** most remotes in the first deployment are Python and serve A2A through a2a-sdk.

## Use cases

| # | Use case | Example |
|---|---|---|
| U1 | A chat app calls a remote, a person is online | a chat assistant calls a report-building service; a team-chat bot |
| U2 | Agent calls agent, a person stands behind the caller | the caller's main agent delegates a task to a remote agent |
| U3 | Agent calls agent, nobody is there | headless turn, nightly job, pipeline |
| U4 | Asynchronous approval, the approver is not the requester | four-eyes approval by email, chat, or an approval inbox |
| U5 | A policy answers by itself | "always allow this remote to read the inventory report" |
| U6 | A client with no UI | CLI, notebook, test |
| U7 | Forwarding | B asks A, A forwards to its person with the same `id` |
| U8 | Off-the-shelf MCP client | a desktop assistant or an IDE using our MCP server |
| U9 | Follow-up: the caller returns to an earlier conversation with the remote | "add a column comparing with last year" after the remote built the report |

**Roles** (protocol concepts only, never a particular caller's concepts): `remote` (the called
party, the one asking), `caller`, `person` (the human the session acts for), `approver` (a human
with the right to approve, possibly not the `person`), `policy`.

## Design

### 1. One extension, two bindings

| | A2A | MCP |
|---|---|---|
| Name | URI `https://github.com/timezlab/ext-r2c/tree/main/standard/v1` | key `io.github.timezlab/r2c` |
| Declaration | `capabilities.extensions: [{uri, required: false}]` | `server/discover`; client declares in `_meta["io.modelcontextprotocol/clientCapabilities"].extensions` |
| `question`, `approval` | DataPart in the `input-required` status message; `data` = the R2C object | elicitation form (core), the R2C object in `_meta[key]` |
| `answer` | DataPart in the reply message (same `taskId` / `contextId`) | elicitation result (`accept` / `decline` / `cancel`) |
| `artifact` | standard A2A `Artifact` plus `metadata[uri]` | tool result content plus `_meta[key]` |
| Progress | `working` status text in SSE (not a kind) | `notifications/progress` `message` |

The URI and the key are names only. Nobody fetches them at runtime, so a machine without
GitHub access is fine.

**Placement rule.** When the part **is** an R2C object (`question`, `approval`, `answer`), the
object sits in `data` and `metadata[uri] = {}` marks the part. When R2C **annotates** a standard
A2A thing (`artifact`), the R2C object sits in `metadata[uri]`.

**Ignore unknown.** Remote and client **MUST** ignore, without error, an R2C object whose `kind`
they do not know, and an unknown field in a known object. This keeps adding a kind later
(for example `provenance`, `caller_context`) compatible with v1.

**Activation per request.** The remote sends R2C parts only when the client activated the
extension through `A2A-Extensions`. Otherwise it sends text and standard artifacts only. Every
request always carries a fallback TextPart built from `title` + `description` + a description
of each field.

### 2. The four kinds

#### Common fields of `question` and `approval`

```jsonc
{
  "kind": "question" | "approval",
  "id": "string",              // required; never reused within a task
  "title": "string",           // required; one line: what is asked, or what is about to happen
  "description": "string?",    // context, reason, consequences; markdown allowed
  "answer_by": { "role": "person" | "caller" | "approver", "approver_role": "string?" },
  "expires_at": "RFC 3339?",   // past it: a question counts as declined, an approval as deny
  "origin": { "name": "string", "url": "string" },        // only when forwarded (U7); id unchanged
  "errors": [{ "key": "string?", "message": "string" }]   // only on a re-ask after a bad answer
}
```

Common rules:
- Each task has at most **one** pending request.
- The remote checks expiry itself. An answer after expiry, or with a wrong `id`, is refused in
  text.
- An answer that fails the schema: the remote sends **the same request** again, same `id`, with
  `errors`; the remote's agent never sees the bad attempt. (Idea taken from §7 of A2A
  Structured Input.)
- A client that did not activate the extension and answers in text: the adapter accepts it only
  when the form has exactly one `one` or `text` field and the text matches; otherwise it asks
  again.

**Agent-to-agent exchange is never blocked.** A remote may need information from the **caller
agent** rather than from a person, and R2C must not stand in the way:
- `answer_by: caller` is the structured way to ask the caller agent. **How** the caller answers
  is its own business: answer itself, or forward to its person; `answered_by` records who really
  answered.
- Plain multi-turn A2A text stays valid: a remote may stop at `input-required` with text only,
  and the caller agent answers in text, over several turns. R2C is always `required: false`; a
  remote need not wrap every exchange in a `question`.
- Only `approval` is locked away from agents (never `answer_by: caller`, never
  `answered_by: caller`). A `question` with `answer_by: person` should be forwarded to a person;
  with nobody there (U3) the answer is `declined`.

#### `question`

```jsonc
{ ...common, "kind": "question", "answer_by": { "role": "person" | "caller" },
  "fields": [{
    "key": "string", "header": "string", "text": "string",
    "type": "one" | "many" | "text" | "number" | "bool",
    "options": [{ "label": "string", "description": "string?" }],  // one/many only; the answer value is the label
    "other": true,         // default true: free text allowed besides the options
    "required": true       // default true
  }] }
```

The form is the source. The adapter **generates** the JSON Schema used to check the answer; the
remote's author never writes one by hand:

| Form | JSON Schema to check (A2A) | `requestedSchema` (MCP, flat) |
|---|---|---|
| `one`, `other: false` | `{"type":"string","enum":[labels]}` | `oneOf: [{const, title}]` |
| `one`, `other: true` | `{"type":"string","minLength":1}` | enum as above plus a field `<key>_other: string` |
| `many` | `{"type":"array","items":{"enum":[labels]},"uniqueItems":true}` | array enum |
| `text` / `number` / `bool` | `string` / `number` / `boolean` | unchanged |

Example (A2A, remote → client, `input-required`):

```jsonc
{ "role": "agent", "parts": [
  { "text": "Pick the target environment\nStaging was refreshed this morning…\nEnvironment: staging | production | other" },
  { "data": { "kind": "question", "id": "q-7f3a", "title": "Pick the target environment",
              "description": "Staging was refreshed this morning; production is frozen until Friday.",
              "answer_by": { "role": "person" },
              "fields": [{ "key": "env", "header": "Environment", "text": "Where should the build go?",
                           "type": "one",
                           "options": [{ "label": "staging" },
                                       { "label": "production", "description": "Frozen until Friday" }] }] },
    "metadata": { "https://github.com/timezlab/ext-r2c/tree/main/standard/v1": {} } } ] }
```

**Use when** the remote lacks one piece of information to continue, and only a person or the
caller has it. `person` when only a human knows; `caller` when the caller probably has it
already (U2: the caller agent answers from its conversation; U3: a job answers from its
configuration). **Do not use** to ask permission (use `approval`), to report progress (use
SSE), or to ask what the remote can look up itself.

#### `approval`

```jsonc
{ ...common, "kind": "approval",
  "answer_by": { "role": "person" | "approver", "approver_role": "string?" },  // never caller
  "subject":
      { "type": "tool_call", "name": "string", "args": {}, "args_schema": {}? }  // edit needs args_schema
    | { "type": "operation", "name": "string", "target": "string?" },
  "decisions": ["allow", "edit", "deny"] }
```

`subject` holds machine data only (for a policy or an "always allow" rule to match); text for
the reader lives in `title` + `description`. Each `approval` has **one** `subject` (matches
LangChain's `interrupt_mode="per_call"`). When several actions need approval at once, the
remote queues them: it sends one `approval` at a time **in arrival order** (the model's tool
call order), the next after the previous one has its `answer`; each is decided on its own (one
`deny` does not drop the others).

Example (four-eyes approval, U4):

```jsonc
{ "kind": "approval", "id": "ap-91c2",
  "title": "Publish the release notes to the public site",
  "description": "The page goes live for all visitors and is cached by the CDN for a day. Public pages need a second approver.",
  "answer_by": { "role": "approver", "approver_role": "Release manager" },
  "expires_at": "2026-11-21T17:00:00Z",
  "subject": { "type": "tool_call", "name": "publish_page",
               "args": { "page_id": "release-notes-4-2", "audience": ["public"] },
               "args_schema": { "type": "object", "required": ["page_id", "audience"],
                                "properties": { "page_id": { "type": "string" },
                                                "audience": { "type": "array", "items": { "type": "string" } } } } },
  "decisions": ["allow", "edit", "deny"] }
```

**Use when** the remote is about to do something with effects outside itself that is hard to
undo: write or delete data, send email or messages, publish, deploy, spend money, share data
outward. U2: the caller agent **only forwards**, it never approves. U3: only a `policy` can
answer; otherwise expiry counts as `deny`. **Do not use** to ask for information ("send it to
whom?" is a `question`).

#### `answer`

```jsonc
{ "kind": "answer", "id": "string",                      // id of the request being answered
  "outcome": "answered" | "declined",
  "answered_by": { "role": "person" | "approver" | "policy" | "caller", "label": "string?" },
  "value": {}?,                                          // absent when declined
  "note": "string?" }

// value of a question: one value per key
{ "env": "staging" }
// value of an approval
{ "decision": "allow" | "edit" | "deny", "args": {}?,  // args required for edit
  "reason": "string?" }                                // optional, mostly for deny
```

Example (A2A, client → remote):

```jsonc
{ "role": "user", "parts": [
  { "text": "Denied: the notes still mention an unreleased feature" },
  { "data": { "kind": "answer", "id": "ap-91c2", "outcome": "answered",
              "answered_by": { "role": "approver", "label": "Release manager" },
              "value": { "decision": "deny", "reason": "The notes still mention an unreleased feature; publish after the 4.2 cut." } },
    "metadata": { "https://github.com/timezlab/ext-r2c/tree/main/standard/v1": {} } } ] }
```

- `declined`: the person refused or closed the form, or the caller could not answer (U3). MCP
  `decline` and `cancel` both map to `declined`.
- `answered_by` is **the client's claim**; the remote cannot verify it. The rule "no model
  answers an `approval`" is therefore a **MUST on the client**.
- **The client may remember, the remote does not.** A client MAY answer an `approval` itself
  from a rule it holds (for example the user clicked "Always allow"); it MUST then write
  `answered_by: policy`. The rule is applied by code, never by a model, and never for
  `answer_by: approver` (four-eyes approval asks every time). There is no `remember` field on
  the wire; the remote keeps no per-user state and still sees every policy answer.
- A `deny` `reason` reaches the remote's model: through the LangChain bridge it becomes the
  `reject` `message`, i.e. the ToolMessage content.

#### `artifact`

No new container: it is a standard A2A `Artifact`. R2C adds only the two things A2A cannot tell
apart (is a link a file to download or a live page to embed; should content be shown in place
or downloaded):

```jsonc
{ "artifactId": "string", "name": "string", "description": "string?",
  "parts": [ Part ],    // file: { "url" | "raw", "filename", "mediaType" }; text: { "text", "mediaType"? }; data: { "data" }
  "metadata": { "https://github.com/timezlab/ext-r2c/tree/main/standard/v1": {
      "kind": "artifact",
      "presentation": "file" | "inline" | "live",
      "state": "open" | "closed"      // live only
  } } }
```

- **Without metadata** (a remote with no adapter): a part with `raw`, or a `url` with
  `filename` → `file`; `text` / `data` → `inline`; a `url` with `mediaType: text/html` → only a
  link opening a new tab, never fetched, never embedded. `live` cannot be guessed; it needs the
  metadata.
- **Updates:** same `artifactId` with `append: false` is a new version (replace);
  `append: true` continues content being streamed.

Examples:

```jsonc
// a spreadsheet
{ "artifactId": "inventory-2026-10", "name": "Inventory, October",
  "parts": [{ "url": "https://remote.example.com/files/inventory-2026-10.xlsx",
              "filename": "inventory-2026-10.xlsx",
              "mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }],
  "metadata": { "<uri>": { "kind": "artifact", "presentation": "file" } } }

// a live screen; when done, send the same artifactId again with "state": "closed"
{ "artifactId": "build-42-live", "name": "Building the dashboard",
  "parts": [{ "url": "https://remote.example.com/builds/42", "mediaType": "text/html" }],
  "metadata": { "<uri>": { "kind": "artifact", "presentation": "live", "state": "open" } } }
```

**Files at task end** go the same way:
- **One artifact per file**, each with its own `artifactId` (updated or replaced on its own);
  `filename` and `mediaType` are required for `presentation: "file"`.
- Sending while running (stream) or at the end are both fine; at the end, `GetTask` returns all
  of the task's `artifacts`. The final text answer is still a message or an `inline` artifact;
  files never go into a status message.
- Size limits per client safety rule 3 below.
- A `url` SHOULD stay alive **at least 24 hours** after the task ends (U4: the approver opens it
  late); a client should copy the file, not keep the link.

**Use when** the remote returns a product rather than a chat reply: a file (txt, md, csv, pdf,
xlsx, docx, png…), long content that should stand on its own (a memo, a table), or a screen
running live. U2: the caller agent passes it up unchanged or uses it as input. U3/U6: save the
file; for live, record the link only. **Do not use** for a short chat answer, for progress, or
to ask the user something.

**Client safety rules:**
1. The user's token is sent **only to the connection's own origin**. A `url` on another host is
   shown as a link; the client does not fetch it.
2. `inline` HTML/SVG is shown in a sandboxed iframe without `allow-same-origin`, or as source.
3. Size: content **inside a message** (`raw`, or `inline` text) is **≤ 5 MB** after decoding;
   larger content must use `url`, and a client that receives an oversized part does not show it,
   only "content too large". A file the client fetches through `url` is **≤ 50 MB**; above that
   the client does not fetch, it shows an "open in new tab" link. For the remote this is SHOULD;
   the client enforces its own limits (MUST) and may set its own thresholds.
4. `live`: `frame-src` lists only the origins of the caller's connections, no `postMessage`
   bridge, and an "open in new tab" button is always shown.

### 3. Progress: the remote's SSE, not a kind

> **Superseded, 2026-11-20:** progress is now the `activity` kind, plus `usage`; see the
> amendment at the top and the [ADR](../design-docs/activity-and-usage-kinds.md).

A streaming remote sends `TaskStatusUpdateEvent` with state `working` and a text message. The
caller relays these to its own UI (a browser usually cannot reach the remote directly: it needs
the user's token in a header and runs into CORS). Each status message becomes one line under
the "calling remote X" step. The remote installs nothing for this.

- Lost compared with a kind: no start/finish per step, no duration, no nesting, no task list.
  If needed, add a kind later.
- A remote with only `SendMessage` (no streaming) gives no progress, only the final result.
- When a proxy cuts the stream, reattach with `SubscribeToTask`.
- MCP: `notifications/progress` `message` is shown the same way.
- The LangChain bridge turns graph events (tool call started/finished) into status text on its
  own.

### 3b. Identifiers and resume

A2A does not carry the remote's internal thread id, and does not need to: the caller sees only
protocol identifiers, and the adapter maps them to its internal thread.

| Identifier | Issued by | Meaning | Used to |
|---|---|---|---|
| `contextId` | the client on the first message, or the remote; the caller sends it back on later messages | one conversation, several tasks | continue a conversation; the adapter sets `thread_id = f(owner, contextId)` (the official LangGraph sample uses the bare `contextId`) |
| `taskId` | the remote | one unit of work, the thing that stops at `input-required` | resume exactly the stopped turn |
| R2C request `id` | the remote, when asking | one question within a task | match an `answer` to the pending request; reject stale or stray answers |

**Resume:** the caller sends a new message with `taskId` + `contextId` + an `answer` part with
`id`. The adapter reads the task from the TaskStore (which request is pending), checks
`answer.id` and `value`, computes `thread_id = f(owner, contextId)`, reads
`graph.get_state(...).interrupts`, then `Command(resume=…)`. A finished task cannot be resumed;
a new message with the same `contextId` opens a new task and still remembers the conversation
through the shared thread.

**Follow-up (U9):** the caller sends a new message with **the same `contextId` and no `taskId`**.
The remote opens a new task in the same context, on the same thread, so it remembers the earlier
conversation. This is core A2A; R2C adds nothing. Two notes: the SDK accepts any `contextId`, so
a remote that lost its state (for example `MemorySaver` and a restart) silently starts over — a
remote should use a durable checkpointer and SHOULD document how long it keeps a context. MCP
has no context; a follow-up there is the server's business (its own id in the args, for example
`job_id`).

Rules:
- **The thread is split by owner: `thread_id = f(owner, contextId)`, never the bare
  `contextId`.** Clients may choose `contextId`, and a2a-sdk's TaskStore is owner-scoped but
  LangGraph checkpoints are not: with the bare `contextId`, two users who pick the same value
  read one thread. `owner` comes from the same `OwnerResolver` as the TaskStore.
- **One unfinished task per context.** Two tasks in one context would run on one thread and
  overwrite each other's checkpoints; the adapter refuses the second one.
- **The caller durably stores `contextId` and `taskId`** per connection per conversation, so it
  can continue the right remote conversation and resume after its own restart.
- **MCP has no `taskId`**: MRTR returns an opaque `requestState` that the client sends back as
  is. The remote packs its stopping point (thread id included if needed) into it, so it must be
  sealed and expire (§7).

### 4. Repository layout

Settled 2026-11-20: PyPI `ext-r2c` (name not reserved yet; it may change if taken), import
`ext_r2c`, MCP key `io.github.timezlab/r2c`, npm later `@timezlab/ext-r2c`, Apache-2.0. The
standard lives in **`standard/`** (not `spec/` or `contracts/`, both clash with Spec Kit's
`specs/` and the `contracts/` folders `/speckit-plan` generates).

```
ext-r2c/
  README.md  LICENSE  CHANGELOG.md
  standard/v1/               ← the A2A URI points here
    README.md                normative text: four kinds, two bindings, every MUST/SHOULD
    schema/                  JSON Schema per kind: question, approval, answer, artifact-meta
    examples/a2a/            question, approval-edit, answer-declined, reask-errors, artifact-file, artifact-live…
    examples/mcp/            elicitation-question, elicitation-approval, tool-result-artifact…
  python/
    pyproject.toml           package ext-r2c, extras
    src/ext_r2c/
      __init__.py            URI, MCP_KEY, STANDARD_VERSION
      core/                  models (per standard/v1/schema); forms (form → JSON Schema, → flat
                             requestedSchema); validate (jsonschema, no external $ref, size
                             limits); fallback (text fallback)
      a2a/                   server.py (wraps an a2a-sdk 1.x AgentExecutor), client.py (caller
                             side), langchain.py (serve(graph, card))
      mcp/                   server.py (elicitation from a form, _meta on artifacts), client.py
                             (decode input_required, build inputResponses + requestState)
    tests/                   real client ⇄ server round trips; every standard/v1/examples/ file
  examples/langchain_agent/  a sample remote served as a plain A2A server (uvicorn)
  .github/workflows/         CI: Python tests; every example validates against the schema
```

A TypeScript SDK later sits beside `python/` as `typescript/`, sharing `standard/v1/schema` and
`standard/v1/examples`.

| Extra | Pulls in | Who installs it |
|---|---|---|
| (none) | `core` only: pydantic, jsonschema | anyone who needs the models and the validator |
| `[a2a]` | `a2a-sdk>=1.3` | A2A remotes and callers |
| `[mcp]` | `mcp>=2.3` | MCP servers and callers |
| `[langchain]` | `[a2a]` + `langchain>=1.3`, `langgraph` | remotes written with LangChain |

Python ≥ 3.11. No A2A ⇄ MCP translating gateway. A remote in another language follows the
standard. If language SDKs ever move out, they become `ext-r2c-python`, `ext-r2c-ts`.

The repository is public; every example uses fake data and neutral names.

**Versioning:** a breaking change moves to URI `.../standard/v2` (A2A) and bumps `revision`
(MCP). v1 stays *draft* until the first remote outside timezlab uses it; until then v1 may still
change.

### 5. A2A core on the remote side (`a2a/server`)

1. **Declare** the R2C URI in `capabilities.extensions`, `required: false`.
2. **Activate per request:** read `A2A-Extensions`, echo the activated extensions in the
   response header.
3. **Ask:** `ask(request)` takes a `question` or `approval`, assigns a fresh `id`, emits
   `input-required` with the fallback TextPart and the R2C DataPart.
4. **Receive the answer:** take the `answer` DataPart with the right `id`; check `value` against
   the generated schema; on failure re-ask with `errors`; wrong `id` or expired → refuse in text.
5. **No private state:** the pending request is read back from the task's status message in the
   TaskStore. To survive a restart, the TaskStore must be durable (a2a-sdk has PostgreSQL and
   SQLite stores).
6. **Artifacts:** `deliver(artifact, presentation=..., state=...)` emits
   `TaskArtifactUpdateEvent`.
7. **Progress:** `progress(text)` emits a `working` status.
8. **Version:** the URI and revision constants live in one place.

### 6. LangChain bridge (`a2a/langchain`)

```python
graph = create_agent(model, tools=[...], checkpointer=<durable checkpointer>,
                     middleware=[HumanInTheLoopMiddleware(interrupt_on={"deploy": True})])
app = serve(graph, card=AgentCard(name=..., skills=[...]))   # replaces agent_executor.py + __main__.py
```

| Concern | How |
|---|---|
| Thread | `thread_id = f(owner, contextId)` (§3b) |
| Progress | each graph update becomes a short `working` status text (tool name, progress) |
| `HumanInTheLoopMiddleware` | `__interrupt__` carries `HITLRequest`. A tool allowing only `["respond"]` → `question` (title/description from `args`/`description`). Otherwise → `approval`, `subject.type = "tool_call"`, `decisions` from `allowed_decisions` (`approve`→`allow`, `reject`→`deny`). `per_call`: each `ToolApprovalRequest` is exactly one `approval` (`args_schema` from `response_schema`), answered by interrupt id. `batched`: N tool calls in one interrupt → N `approval`s asked one after another in `action_requests` order. Both modes: collect all N decisions, then resume once |
| Hand-written `interrupt(value)` | `value` is a valid `question` / `approval` object → used as is. Anything else → a `question` with one `text` field, the value serialised into `description` |
| Turn ended with `status = "input_required"` (the sample's pattern) | the adapter wraps the text as a `question` with `title` = the question, one `text` field, and **`answer_by: caller`** (the remote does not say who the question is for, so the caller decides). The answer enters the graph as **the next message**, not as a resume. Detected by the sample's convention (`structured_response.status` ∈ `input_required` / `completed` / `error`); other conventions pass a detector function to `serve()` |
| Answer | `answer.value` → `Command(resume={"decisions": [...]})` in order; `reason` → `reject` `message`; `edit` → `edited_action`. Only decisions in `allowed_decisions` are used; a `ValueError` never kills the run |
| Stopping point | read back from `graph.get_state(config).interrupts` when an answer arrives. No stopping point left → a clear error, never a hang |
| Checkpointer | `serve()` warns on `MemorySaver`: a restart loses the stopping point |
| Result | the last AI message becomes an `inline` artifact. `file` content blocks (langchain-core 1.x standard content blocks) in a model or tool message become `file` artifacts, one per file; the remote's owner writes nothing |

The repo's docs **recommend** `HumanInTheLoopMiddleware` over calling `interrupt()` inside a
tool body, because on resume the whole tools node runs again. The adapter does not enforce
this.

### 7. MCP side (`mcp/server`, `mcp/client`)

- **`question`** → elicitation form: `message` = `title` + `description`, `requestedSchema`
  generated from the form (table in §2), the R2C object in `_meta[key]`.
- **`approval`** → elicitation with a `decision` field (enum) and `reason` (string, optional).
  `edit` survives only when `args_schema` is flat (one field per arg, pre-filled with the
  current value); otherwise `edit` is dropped from `decisions`.
- **`answer`**: `accept` → `answered`, `decline` / `cancel` → `declined`; `answered_by` is
  always `person` (elicitation's MUST).
- **`artifact`** → `file`: `resource_link {uri, name, mimeType, size}` or an embedded
  `resource`; `inline`: `text` content; `live`: `resource_link` + `_meta[key] = {presentation:
  "live"}`. MCP returns artifacts only with the tool result, so there is no live link mid-run
  (MCP Tasks not considered yet).
- No framework bridge on the server side: an MCP server is a set of tools, not an agent.
- Client side: decode `inputRequests`, build `inputResponses`, send `requestState` back as is.
  The server enables the MCP Python SDK's `RequestStateBoundary` (≥ 2.3.0) to seal
  `requestState` and check TTL, principal and audience; the adapter does not write its own.

### 8. Guidance for callers (non-normative)

How a caller presents and routes requests is its own design; these are the shapes R2C was
designed against:
- `answer_by: person` or `approver` → show a form or an approval dialog to the user, labelled
  with the remote's name (and `origin` when forwarded); approvals look like a warning and record
  who approved.
- `answer_by: caller` → goes to the caller's agent, not straight to the user. The agent answers
  from information it already has, or forwards to its user; `answered_by` records who answered.
- A remote without R2C (text only): the caller's agent may answer from information it already
  has (the user's own words, earlier results quoted verbatim); every self-answer is shown to the
  user with its source; otherwise it asks the user. It **never** answers an `approval`. For MCP,
  elicitation requires user review, so the agent may only pre-fill.
- "Always allow" is a client-held policy (`answered_by: policy`); its scope (same user, same
  connection, same `subject.name`; per conversation or permanent) is the caller's choice.
- A headless turn: a remote asking `person` gets `declined` (or the task is cancelled).

## Alternatives considered

| Alternative | Why not |
|---|---|
| Build on A2A Structured Input v1 plus a small vocabulary | Chosen 2026-11-19, **dropped 2026-11-20**: no client understands only Structured Input; the schema is generated from the form anyway; every part would carry two keys, a repeated `id`, an answer split in two, and a dependency on an experimental spec pinned by commit. Kept as a possible compatibility mode later |
| `plan` / `step` kinds | The remote's SSE status text is enough and needs no install |
| A separate `live_view` kind | Folded into `artifact` with `presentation: "live"` |
| `provenance`, `caller_context` in v1 | Deferred: adding them later is compatible thanks to "ignore unknown kind". Sketches for later: `provenance` on a Part `{source: {type: sql\|api\|document\|model\|person, system, ref, statement}, as_of, retrieved_at}`, tables per Frictionless Table Schema; `caller_context` `{locale, timezone, presence: online\|async\|none, renders}` |
| Agent Stack (BeeAI) Approval v1 + Form Request v1 | Two different envelopes; the text fallback is nearly empty; the URI belongs to another ecosystem |
| One adapter per framework | One shared adapter; per-framework parts are thin bridges |
| An A2A ⇄ MCP translating gateway | An agent task and a tool call differ in kind |
| The caller detects each framework's native way of asking (LangGraph Agent Server, Strands, ADK) | N dialects to maintain, and it only works with each framework's own server. Deferred, not ruled out |
| A2UI / MCP Apps for asking and live view | Heavy: a component catalog or a separate sandbox origin. Later |
| Names `hitl-bridge`, `agent-interaction`, `handback`, `a2a-handback`, `agent-handback`, R2U | Too narrow (no `artifact`), unclear, taken on PyPI/npm (`handback`), tied to A2A alone, or saying "agent" when the remote may be an MCP server |

## Out of scope

- Multi-hop chains (X calls Y calls Z). The adapter handles one hop between a caller and one
  remote.
- Identity and permissions: the transport and the platform handle them. The adapter neither
  reads nor issues tokens.
- Deciding when to ask: that is the remote's logic.
- Drawing the question UI: that is the client's job. The live UI is the remote's own UI.
- Kinds `auth`, `client_tool` (names reserved, no schema yet), A2A push notifications.
- SDKs for languages other than Python.

## Compatibility

- A remote that changes nothing (for example the official Currency sample) still works with an
  R2C caller in text.
- A client that does not activate the extension still works with a remote that has the adapter:
  text fallback, standard artifacts.
- A remote without the adapter that sends standard artifacts: the client guesses
  `presentation` from the part.
- Breaking change: `v1` → `v2` in the URI (A2A), `revision` bump (MCP).

## Success criteria

1. A `create_agent` agent with `HumanInTheLoopMiddleware(interrupt_on={"deploy": True})` served
   by `serve()` (a local server in tests). A test caller receives an `approval` with a `title`
   and `subject` `deploy` with its args; it answers `allow`; the `deploy` tool runs **exactly
   once** (a counter in the test); the task ends `completed`.
2. Same agent, the caller answers `deny` with a `reason`. The tool does not run; the model gets a
   `ToolMessage` containing the reason; the task continues to `completed`.
3. Send an `answer` that fails the schema (a required field missing). The remote re-sends the
   same request, same `id`, with `errors`; the run **does not die**.
4. Restart the remote while it is at `input-required`, with a durable checkpointer and
   TaskStore. An answer sent after the restart resumes at the right place.
5. The unmodified official Currency sample: a caller receives a text-only `input-required` and
   continues in text.
6. An MCP server calls elicitation through `mcp/server`: the client receives a flat
   `requestedSchema` plus the R2C object in `_meta`, and the answer maps back to an R2C
   `answer`.
7. A remote sends a `file` artifact with a same-origin `url`: the test client fetches it. One
   with a `url` on another host: the client makes no request to that host.
8. The round-trip tests replay every wire example in `standard/v1/examples/` exactly.

## Sources

- [A2A Extensions](https://a2a-protocol.org/latest/topics/extensions/), [`a2a.proto`](https://github.com/a2aproject/A2A/blob/main/specification/a2a.proto)
- [Structured Input v1](https://github.com/a2aproject/experimental-ext-structured-input/blob/main/v1/spec.md) (the re-ask and `id`-matching idea; not used on the wire)
- [a2a-python](https://github.com/a2aproject/a2a-python) (`extensions/common.py`, `utils/extension_validator.py`)
- [a2a-samples: timestamp extension](https://github.com/a2aproject/a2a-samples/tree/main/extensions/timestamp), [LangGraph agent](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/langgraph/app)
- [MCP Extensions](https://modelcontextprotocol.io/docs/extensions/overview), [Elicitation (draft)](https://modelcontextprotocol.io/specification/draft/client/elicitation)
- [MCP Apps (`ext-apps`)](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx), [A2UI v1.0](https://a2ui.org/specification/v1.0-a2ui-extension-specification/)
- [Agent Stack approval.py](https://github.com/i-am-bee/agentstack/blob/main/apps/agentstack-sdk-py/src/agentstack_sdk/a2a/extensions/interactions/approval.py)
- [Frictionless Table Schema](https://specs.frictionlessdata.io/table-schema/) (for `provenance`, later)
- Wheels read on 2026-11-20: `a2a_sdk-1.3.1`, `mcp-2.3.0`, `langchain-1.5.2`
