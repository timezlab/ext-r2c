# Feature Specification: MCP binding (`ext_r2c.mcp`)

**Feature Branch**: `main` (no branch; the directory is `specs/004-mcp-binding`)

**Created**: 2026-11-20

**Status**: Draft

**Input**: User description: "004-mcp-binding — ext_r2c.mcp, the MCP door of the Python SDK,
behind the [mcp] extra (the MCP Python SDK, protocol 2026-07-28). Run events ⇄ MCP wire, for
both sides, as an MCP SDK `Extension` keyed `io.github.timezlab/r2c`. Remote side: an agent
source as an MCP tool, and plain tools (`ToolSpec`) with R2C; questions and approvals asked
through multi-round-trip requests (an `InputRequiredResult` with an elicitation built from
`mcp_form`, the R2C object in `_meta[key].input_requests[<key>]`, the elicitation `message` as
the text fallback); answers derived with `answer_from_mcp`, checked, re-asked with `errors`,
refused on a wrong key or expiry; approval of a direct tool call (`approve=`), `edit` included
when the arguments are flat (R2C-MCP-3); `activity` through `notifications/progress`; `usage`
and artifacts on tool results; `requestState` sealed by the SDK's `RequestStateBoundary`;
threads by owner and context; activation per R2C-ACT-4 and R2C-ACT-5; MCP Skills (SEP-2640)
from folders. Caller side: a client that decodes `inputRequests` and R2C `_meta`, builds
`inputResponses` from an R2C answer, sends `requestState` back unchanged, and reads activities,
usage and artifacts. Plus the replay of every MCP example. Settles O3 (MCP side), O4, O5, O6,
O7. Done when real MCP SDK client↔server round trips in process cover every MCP example's
flow, and success criterion 6 of the brief holds."

## Context

Spec 001 wrote the standard, with 9 MCP wire examples. Spec 002 built `ext_r2c.core`: the
models, the flat MCP form (`mcp_form`) and its way back (`answer_from_mcp`), the answer check,
the run events, `AgentSource` with its two pause styles, the `Driver`, and `ToolSpec`. Spec 003
built the A2A door. Nothing in the package speaks MCP yet: an MCP server cannot ask its client
an R2C question, and an MCP client cannot read one.

This spec builds the MCP door, `ext_r2c.mcp`, behind the `[mcp]` extra, on the MCP Python SDK
2.3. It has two sides:

- **Remote side**: an MCP SDK `Extension` that serves tools with R2C. A tool is either a plain
  `ToolSpec`, optionally behind an approval, or an `AgentSource` offered as one tool. Questions
  and approvals go out as elicitations in a multi-round-trip tool call; the answer comes back in
  the next call of the same tool.
- **Caller side**: a client that calls tools with R2C activated, reads R2C content as typed
  items, answers a pending request, and sends the call again.

MCP differs from A2A in ways that shape every story:

- **No task id.** The stopping point of a tool call travels in `requestState`, sealed by the
  SDK's `RequestStateBoundary` (TTL, principal, audience, bound to the tool and its arguments).
  The door never seals anything itself.
- **No streaming of the reply.** The reply text arrives once, in the tool result.
- **No R2C answer object.** The answer is derived from the elicitation result, and is always
  answered by a `person`, because MCP requires the user to review every response (R2C-MCP-4).

MCP Skills (SEP-2640), first planned here, is its own spec, `005-mcp-skills` (decided
2026-11-20, Q1 A): it is a separate MCP extension, not R2C, and the SDK does not ship it. The
specs after it move up one number.

> **Note, 2026-11-22.** Spec 005 is built (locally): `SkillsExtension` and `SkillsClient` in
> `ext_r2c.mcp`. This spec's `mcp_server` gained one keyword, `extensions=`, to serve other MCP
> extensions after R2C's; without it the behaviour is exactly as written here, and the R2C wire on
> `tools/call` is unchanged beside a skills extension (005's `test_skills_compose.py`).

`Remote` (007) will offer this door beside the A2A door, as `tools=`, `approve=` and
`mcp_tool=True`; this spec does not build `Remote`. The LangGraph bridge (006) will be one
`AgentSource`; this spec tests with the fake sources of 002 and sources written in the tests.

Readers of this spec are the people who write `Remote` in this repository, owners of an MCP
server who add R2C to it, and authors of MCP clients.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask a question over MCP and get an R2C answer back (Priority: P1)

A remote owner serves an `AgentSource` as one MCP tool. An MCP client that activated R2C calls
it. When the agent needs a person, the call ends with an input-required result: one
elicitation form, built from the question, and the R2C question in the result's `_meta`. The
client shows the form, the person fills it in, and the client calls the tool again with the
response and the `requestState` it received. The agent receives an R2C answer, goes on, and the
call ends with the reply text, the artifacts and the usage.

**Why this priority**: it is success criterion 6 of the brief, and the core of the MCP binding.

**Independent Test**: serve the fake checkpoint source and the fake live source from spec 002
as one tool in process; a real MCP SDK client calls it, answers, and checks both rounds.

**Acceptance Scenarios**:

1. **Given** a served source that asks a question, **When** an activated client calls the
   tool, **Then** the result has `resultType: input_required`, exactly one entry in
   `inputRequests`, an `elicitation/create` form whose `requestedSchema` is the question's flat
   form (R2C-MCP-2), and the question in `_meta[key].input_requests[<same key>]` (R2C-MCP-1,
   `mcp/elicitation-question.json`).
2. **Given** that result, **When** the client calls the tool again with the same arguments,
   `inputResponses` for that key with `action: accept`, and the `requestState` unchanged,
   **Then** the source receives the answer that `answer_from_mcp` derives, with
   `answered_by.role = person` (R2C-MCP-4), and the call ends with `resultType: complete`.
3. **Given** a question with `other: true` fields, **When** the person types a value in
   `<key>_other`, **Then** the source receives the merged value
   (`mcp/elicitation-question-other.json`, `mcp/elicitation-question-many-other.json`).
4. **Given** the person declines or cancels the form, **When** the client calls again,
   **Then** the source receives a `declined` answer and the run goes on.
5. **Given** a source that asks two questions one after the other, **When** the client answers
   the first, **Then** the next call ends input-required again with the second question only;
   one tool call never has two pending requests (R2C-ASK-3).
6. **Given** a finished run, **When** the call completes, **Then** the result's content holds
   the reply as one `text` block marked `response: true`, each artifact as a content block with
   its R2C metadata, and `usage` in the result's `_meta` (R2C-MCP-7, R2C-MCP-8,
   `mcp/tool-result.json`).
7. **Given** the same flows, **When** they run once with a checkpoint source and once with a
   live source, **Then** the wire is the same, except the sealed `requestState`.

---

### User Story 2 - Approve a direct tool call before it runs (Priority: P1)

A remote owner serves plain tools and marks some of them as needing approval. When an MCP client
calls such a tool, the door asks an R2C approval through the same multi-round-trip call before
running it. The person allows, edits the arguments, or denies. The tool runs once on allow or
edit, never on deny or decline.

**Why this priority**: an approval is the reason R2C exists (constitution V), and over MCP a
tool call from the client's model is the most common thing to approve.

**Independent Test**: one tool with a call counter, served with approval; a real client calls
it and answers allow, edit, deny, decline; the counter and the arguments the tool received are
checked.

**Acceptance Scenarios**:

1. **Given** a tool marked for approval whose arguments are flat, **When** the client calls it,
   **Then** the result is input-required with an approval whose `subject` is the tool's name
   and arguments, and the form has `decision`, `reason`, and one property per argument with its
   current value as `default` (R2C-MCP-3, `mcp/elicitation-approval.json`).
2. **Given** that approval, **When** the person accepts with `decision: allow`, **Then** the tool
   runs exactly once with the arguments of the call, and the call completes with its result.
3. **Given** that approval, **When** the person accepts with `decision: edit` and a new value
   for one argument, **Then** the tool runs exactly once with the edited arguments, after they
   pass the tool's own input schema.
4. **Given** that approval, **When** the person denies with a reason, or declines the form,
   **Then** the tool never runs and the call completes with a text saying it was denied, with
   the reason when one was given.
5. **Given** a tool whose arguments are not flat, **When** it is called, **Then** `edit` is not
   offered (`mcp/elicitation-approval-edit-dropped.json`).
6. **Given** an approval with `answer_by.role = approver` and an `expires_at` set from the
   approval settings, **When** it is asked, **Then** both are in the R2C object, and the
   approval is still answered by the person who reviews the form (R2C-MCP-4).
7. **Given** a tool not marked for approval, **When** it is called, **Then** it runs at once,
   and its result still carries R2C artifact metadata and usage when it returns them.

---

### User Story 3 - Refuse or re-ask, never pass a bad answer on (Priority: P1)

The remote receives responses it must not hand to the agent or use to run a tool: content that
fails the form, an `edit` whose arguments break the tool's schema, no response for the pending
key, a response after the request expired, a `requestState` that is forged, changed, expired, or
sent by another principal. The door decides with the core's answer check and the SDK's
boundary; the source and the tool see only an acceptable answer.

**Why this priority**: the robustness rules of R2C (R2C-ASK-4 to -6) and the security of
`requestState` (R2C-MCP-5). A door that lets a bad answer through runs an action nobody approved.

**Independent Test**: for each case, a client sends the bad round to a paused call; the test
checks the next result, that the source received nothing, and that the tool's counter is 0.

**Acceptance Scenarios**:

1. **Given** a call paused on `q-1`, **When** the response leaves a required field empty,
   **Then** the next result is input-required with the same request under the same key, the
   R2C object carries `errors` naming the field, the elicitation `message` lists the errors in
   words (R2C-ASK-6), and the source received no answer.
2. **Given** a call paused on `q-1`, **When** `inputResponses` has no entry for `q-1` (none, or
   only other keys), **Then** the next result asks `q-1` again, its `message` starts with a
   sentence saying no response for it was received, and keys that are not pending are ignored
   (R2C-ASK-5).
3. **Given** an approval with `expires_at` in the past, **When** a response arrives, **Then**
   the approval counts as deny, the tool never runs, and the result's text says the response
   came too late (R2C-ASK-4).
4. **Given** a paused call, **When** the client sends a `requestState` that was altered, that
   was sealed for another tool, other arguments or another principal, or that outlived its
   TTL, **Then** the call is refused by the SDK's boundary with its own error, and the source
   and the tool see nothing (R2C-MCP-5).
5. **Given** a response larger than the size limit, **When** it arrives, **Then** it is re-asked
   with a "too large" error and the oversized content is not parsed further.

---

### User Story 4 - Plain MCP for a client without R2C (Priority: P1)

A client that knows nothing of R2C calls the same tools. It must get a working MCP server: plain
elicitations it can show, plain progress messages, plain content blocks, and no R2C `_meta`
anywhere. A client that lists the R2C key in its declared extensions gets R2C.

**Why this priority**: R2C is an extension, never a requirement (constitution IV, R2C-ACT-4,
R2C-ACT-5). R2C `_meta` sent to a plain client is noise at best.

**Independent Test**: the same tools called twice, with and without the key in the client's
capabilities; compare with `mcp/discover.json` and `mcp/not-activated.json`.

**Acceptance Scenarios**:

1. **Given** the served extension, **When** a client calls `server/discover`, **Then**
   `capabilities.extensions` lists the R2C key with `{"revision": 1}` (R2C-ACT-4,
   `mcp/discover.json`).
2. **Given** a request whose `_meta` client capabilities list the R2C key, **When** the server
   answers, **Then** it adds R2C `_meta` to that response (R2C-ACT-5).
3. **Given** the same request without the key, **When** the server answers, **Then** the
   question is still asked as an elicitation with the same form and message, the answer is
   still derived and checked, and no result, content block or notification carries R2C `_meta`
   (`mcp/not-activated.json`).
4. **Given** a client whose capabilities have no form elicitation at all, **When** a source asks
   a question, **Then** the source receives `declined` and the run goes on; **When** a tool needs
   approval, **Then** it is not run and the result says approval could not be asked.
5. **Given** a call whose first round was activated and whose retry was not, **When** the
   server answers the retry, **Then** activation follows the retry's own `_meta`.

---

### User Story 5 - Keep conversations apart, survive a restart (Priority: P1)

The agent offered as a tool keeps a conversation across calls through a `context_id`. Two
owners may choose the same one; their threads never meet. A context has at most one unfinished
call. A server restarted while a call waits for input can take the retry and resume, as long as
its request-state keys and the source's storage are durable.

**Why this priority**: R2C-ID-1, R2C-ID-2 and the resume promise of the brief (success
criterion 4), on the door that has no task store.

**Independent Test**: in-process server with fixed request-state keys and a checkpoint source on
a durable store; drop the server object and build a new one between the question and the retry.

**Acceptance Scenarios**:

1. **Given** owners A and B who both call the agent tool with `context_id: "ctx-1"`, **When** both
   run, **Then** the source sees two different thread ids, `thread_id("mcp", owner, context)`.
2. **Given** a call without `context_id`, **When** it completes, **Then** the result's structured
   content holds the `context_id` the server chose, and a later call with it continues the same
   thread (one-remote-two-doors ADR, decision 5).
3. **Given** a call with `context_id: "ctx-1"` paused for input, **When** the same owner starts a
   new call (no `requestState`) with `ctx-1`, **Then** the new call is refused with a text saying
   the context has an unfinished call; the paused call is untouched (R2C-ID-2). Once the paused
   call's `requestState` has expired, the context is free again.
4. **Given** a checkpoint source paused on `q-1` and a server rebuilt with the same request-state
   keys, **When** the retry arrives, **Then** the door reads the pending request back from the
   unsealed `requestState`, checks the response against it, and the source resumes and completes.
5. **Given** a live source paused on `q-1` and a rebuilt server, **When** the retry arrives,
   **Then** the call ends with a tool error saying the paused run was lost and should be asked
   again.
6. **Given** a live source paused and a client that never retries, **When** the
   `requestState` TTL passes, **Then** the paused run receives `declined`, ends, and frees its
   context.

---

### User Story 6 - Read R2C as an MCP caller, answer, and call again (Priority: P2)

An MCP caller (a person-facing app or an orchestrating agent) uses the client of this door. It
calls a tool with R2C activated and reads typed items: activities while the tool runs, a
pending request when the call needs input, then the reply, artifacts with their presentation,
and usage. It builds an answer for the pending request, checked with the core before it is
sent, and the client calls the tool again with the matching `inputResponses` and the
`requestState` as received.

**Why this priority**: callers need it to use R2C over MCP at all, and the round-trip tests need
a client. It ranks below the remote side because a caller can read R2C `_meta` with the MCP SDK
alone.

**Independent Test**: the same in-process round trips as stories 1–5, driven only through this
client.

**Acceptance Scenarios**:

1. **Given** a call with a progress token, **When** the tool reports activities, **Then** the
   client yields one activity item per notification, in order (R2C-MCP-6,
   `mcp/progress-activity.json`); unknown kinds, unknown fields and unknown activity types are
   skipped and counted, never an error (R2C-CORE-5, -6).
2. **Given** an input-required result, **When** the client reads it, **Then** it yields one
   request item per entry, typed from the R2C `_meta` when present and as a plain elicitation
   otherwise.
3. **Given** a pending request, **When** the caller gives an answer that fails it, **Then** the
   client reports the problems and sends nothing; **When** the answer is good, **Then** it turns
   it into the elicitation response (the inverse of `answer_from_mcp`), calls the tool again with
   the same name and arguments, and sends `requestState` byte for byte as received.
4. **Given** an approval, **When** the caller's agent tries to answer it as `caller`, or any
   request with `policy`, **Then** the client refuses: on MCP the person reviews every response
   (R2C-ANSWER-4, R2C-MCP-4).
5. **Given** a completed call, **When** the client reads the result, **Then** it yields the
   reply, each artifact with its presentation (guessed when the block has no R2C `_meta`,
   R2C-ARTIFACT-7), and the usage (`mcp/tool-result.json`).
6. **Given** a `resource_link` to a resource of the same server, one to an `https` url on the
   connection's origin, and one to another host, **When** the caller asks for their content,
   **Then** the first is read through the same connection, the second fetched, and the third
   returned as a link with no request to that host (R2C-SAFETY-1).

---

### User Story 7 - Every MCP example is a real round trip (Priority: P1)

The MCP example files (9 today, plus those this spec adds) are the shared test suite
(constitution II). Each one's flow is reproduced by a real MCP SDK client talking to a real MCP
SDK server in process, through this door, and the wire matches the file.

**Why this priority**: the done condition of this spec, and the evidence that the door
implements the standard rather than an idea of it.

**Independent Test**: one parametrised test per MCP example file, against the door and against
the client, like the A2A replay of spec 003.

**Acceptance Scenarios**:

1. **Given** any MCP example file, **When** its flow is played in process (the remote side by a
   scripted source or tool, the client side by the steps from the client), **Then** every R2C
   object, every elicitation, every progress notification and every result on the wire equals
   the file's, ignoring only values the replay names as generated (the sealed `requestState`,
   JSON-RPC ids, fields the SDK adds that the file does not show).
2. **Given** an example whose flow this door cannot produce, **When** the replay runs, **Then**
   the test fails with the file name; no example is skipped silently.

### Edge Cases

- **Several `inputRequests` from another server**: the door sends one per round; the client
  still accepts several, yields each, and sends every response in one retry. An input request
  that is not a form elicitation (the client declares no other input capability) ends the call
  on the client with an error naming the method.
- **An approval left with no decision that MCP can ask** (only `edit`, and arguments that are
  not flat): `mcp_form` refuses it (O3, R2C-MCP-3). From a source, the source receives a
  declined answer and the run goes on; the action never happens.
- **No `progressToken`**: no activity is sent (R2C-MCP-6); the run is otherwise the same.
- **Progress numbers**: `progress` starts at 1 for each request and grows by 1 per
  notification; no `total` is sent. A new round is a new request with its own token.
- **Usage over several rounds**: cumulative over the whole tool call, every round included
  (R2C-USAGE-2); the final result carries the last one known.
- **Usage while the call waits for input**: the input-required result carries the usage so far
  in `_meta[key].usage`, beside `input_requests` (FR-015), so a call the person abandons still
  reports what it cost.
- **A source that ends with an error**: the result is a tool error (`isError: true`) with the
  reason as text, plus the last usage. A cancelled run (the client cancels the request) ends the
  run through the driver; a live source sees `declined`.
- **Reply text that is never sent in chunks**: the door gathers every reply chunk and sends the
  text once. The gathered text is size-checked as a whole: over 5 MiB, the call ends with a tool
  error naming the size (R2C-SAFETY-4). The A2A door gathers the reply of a client without R2C
  the same way and gets the same check (left open by spec 003's outside review).
- **An `inline` artifact that is not text**: an image or audio inline artifact is an `image` or
  `audio` content block with its R2C metadata; any other inline binary content goes as an
  embedded `resource` with `presentation: inline` (O7, decided here by default; written into
  R2C-MCP-7).
- **A `live` artifact**: a `resource_link` in the final result only; MCP has no live link
  mid-run.
- **The retry changes the tool's arguments**: refused by the SDK's boundary (the state is bound
  to the arguments' digest); an `edit` changes arguments only through the form.
- **Text sent for an approval**: there is no free text on MCP; an approval is only ever taken
  from its form's `decision`.
- **The elicitation message**: the request's `title`, then its `description` when present, then
  one line per error on a re-ask; a refusal sentence comes first. With `origin`, the title is
  prefixed `<origin.name> asks: `. The two approval examples, whose message today adds words the
  title does not have, are corrected to this rule (O5).
- **Owner unknown** (a server with no authentication): every request has the same owner; thread
  ids still differ by context.
- **Long runs**: an agent tool that runs longer than the client's request timeout fails on the
  client side; MCP Tasks, which would fix it, is out of scope.

## Requirements *(mandatory)*

### Functional Requirements

**The extension (stories 1, 2, 4)**

- **FR-001**: The MCP door MUST be an MCP SDK `Extension` with the identifier
  `io.github.timezlab/r2c` and the settings `{"revision": 1}`, so that `server/discover`
  declares it (R2C-ACT-4), usable on a server the remote owner already has.
- **FR-002**: The door MUST serve plain `ToolSpec`s as MCP tools, and an `AgentSource` as one
  tool with input `{message, context_id?}` whose result has the reply text, structured content
  `{context_id}`, the artifacts and the usage.
- **FR-003**: The door MUST add R2C `_meta` to a response only when that request's client
  capabilities list the R2C key (R2C-ACT-5); everything else it sends is plain MCP.

**Asking (stories 1, 2)**

- **FR-004**: A question or an approval MUST be asked as an input-required result with exactly
  one form elicitation in `inputRequests`, keyed by the request's `id`; its `requestedSchema` is
  `mcp_form`'s; its `message` follows the rule of O5 (Edge Cases); when R2C is active the R2C
  object is in the result's `_meta[key].input_requests[<id>]` (R2C-MCP-1 to -3).
- **FR-005**: The stopping point of a paused call (what the door needs to resume it, the pending
  request included) MUST travel only in `requestState`, sealed and checked by the SDK's
  `RequestStateBoundary`; the door MUST NOT seal, sign or encrypt anything itself (R2C-MCP-5).
- **FR-006**: The door MUST derive the answer from the elicitation response with
  `answer_from_mcp`, `answered_by.role = person` (R2C-MCP-4), and check it with the core's
  answer check before the source or the tool sees it, leaving out the role checks (as in spec
  003, FR-012).
- **FR-007**: A tool marked for approval MUST NOT run until an approval for that call is
  answered `allow` or `edit`; on `edit` it runs with the edited arguments after they pass its
  input schema; on deny, decline or expiry it never runs. The approval's `subject` is the tool's
  name and arguments, and its `answer_by` role and expiry come from the tool's approval
  settings.
- **FR-008**: An approval MUST offer `edit` only when the tool's input schema is flat
  (R2C-MCP-3); an approval left with no decision MCP can ask counts as declined.

**Refusing (story 3)**

- **FR-009**: A response that fails the request MUST make the door ask the same request again,
  same key and `id`, with the problems as `errors` in the R2C object and in the `message`
  (R2C-ASK-6); the source receives nothing.
- **FR-010**: A retry with no response for the pending key MUST ask the pending request again,
  with a refusal sentence first in the `message` (R2C-ASK-5); keys that are not pending are
  ignored.
- **FR-011**: Past `expires_at`, a pending question MUST count as declined and an approval as
  deny; the run goes on, and the text of the next result says the response came too late
  (R2C-ASK-4, R2C-ASK-5).

**Activity, reply, artifacts, usage (story 1)**

- **FR-012**: An activity MUST be sent as `notifications/progress` for a request with a
  `progressToken`: `message` is the activity's `label`, `progress` counts up from 1, and the
  activity sits in the params' `_meta[key]` when R2C is active; with no token, nothing is sent
  (R2C-MCP-6). Reasoning activities are sent only when R2C is active.
- **FR-013**: The reply MUST be one `text` content block of the final result, marked
  `response: true` when R2C is active; artifacts are content blocks by presentation (R2C-MCP-7,
  O7 as in Edge Cases); `usage` is in the result's `_meta[key]` (R2C-MCP-8).
- **FR-014**: The gathered reply text MUST be size-checked as a whole, on this door and on the
  A2A door for a client without R2C; over the limit, the run ends with an error naming the size
  (R2C-SAFETY-4).
- **FR-015**: When R2C is active and the source has reported usage, an input-required result
  MUST carry the usage so far beside the request, as `_meta[key].usage` next to
  `_meta[key].input_requests` (O6, decided 2026-11-20: Q2 A). The final result keeps `usage` as
  the whole of `_meta[key]` (R2C-MCP-8).

**Threads (story 5)**

- **FR-016**: The thread id given to the source MUST be `thread_id("mcp", owner, context_id)`,
  with the owner from the same principal the SDK's boundary binds `requestState` to (R2C-ID-1).
- **FR-017**: A new call (no `requestState`) on a context with an unfinished call of the same
  owner MUST be refused with a text naming that the context is busy; a call counts as
  unfinished until it completes or its `requestState` expires (R2C-ID-2).
- **FR-018**: After a restart with the same request-state keys, a retry for a paused checkpoint
  run MUST resume it through the driver; a retry for a paused live run MUST end with a tool
  error saying the run was lost. A live run whose `requestState` expires MUST receive `declined`.

**Client (story 6)**

- **FR-019**: The client MUST declare the R2C key and form elicitation in its capabilities, and
  yield typed items for activities, requests, reply, artifacts, usage and the end of the call;
  unknown kinds, fields and activity types are skipped and counted.
- **FR-020**: The client MUST check an answer with the core before sending it, refuse an
  approval answered as `caller` and any answer by `policy`, map it to the elicitation response,
  and call the tool again with the same name and arguments and the unchanged `requestState`.
- **FR-021**: When asked for an artifact's content, the client MUST read resources only through
  its own connection, fetch `http(s)` urls only on the connection's origin without following a
  redirect, return any other url as a link, and apply its size limits (R2C-SAFETY-1, -5).

**Replay, standard and packaging (story 7)**

- **FR-022**: Every file in `standard/v1/examples/mcp/` MUST be replayed as a real in-process MCP
  SDK round trip through this door and through the client; a file the replay cannot cover fails
  the test.
- **FR-023**: The decisions on O4, O5, O6 and O7 MUST be written into `standard/v1/README.md`
  (R2C-MCP rules), each with a new or corrected MCP example: one request per round and usage
  across rounds (O4); the elicitation `message`, a re-ask with `errors` and a refusal (O5); usage
  while waiting (O6); a non-text inline artifact (O7). Every example MUST still validate and
  replay.
- **FR-024**: `ext_r2c.mcp` MUST import only from `ext_r2c.core`, the standard library and the
  `[mcp]` extra's packages; `import ext_r2c`, `ext_r2c.core` and `ext_r2c.a2a` MUST keep working
  without the extra (constitution VIII), and a test run with the wheel and `[mcp]` alone passes.

### Key Entities

- **MCP door**: the `Extension` that serves tools and the agent tool with R2C.
- **Approval settings**: per tool: whether it needs approval, who answers (`answer_by` role),
  how long the request stays open.
- **Round**: one `tools/call` request and its result. A **tool call** is the chain of rounds
  linked by `requestState`, from the first call to the complete result; it is what a task is on
  A2A (O4).
- **Stopping point**: what the door seals in `requestState`: the thread, the pending request,
  the usage so far, the round.
- **Activation**: whether this round's client capabilities list the R2C key.
- **Owner**: the principal the SDK's boundary binds `requestState` to; with `context_id`, it keys
  the thread.
- **Client item**: one typed thing a caller reads: activity, request, reply, artifact, usage, end.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the MCP example files (9 today, plus those FR-023 adds) are replayed as real
  in-process round trips against the door and against the client; the test run prints the count.
- **SC-002**: An MCP elicitation asked through the door reaches a real client as a flat
  `requestedSchema` plus the R2C object in `_meta`, and the response maps back to the R2C
  answer the example names (brief, success criterion 6).
- **SC-003**: The fake checkpoint source and the fake live source both complete the question,
  approval, deny, decline and cancel flows over MCP with equal R2C content on the wire.
- **SC-004**: A tool behind an approval runs exactly 1 time after `allow` or `edit`, and 0 times
  after deny, decline, expiry, a bad response or a refused `requestState`.
- **SC-005**: In every bad-response case of story 3, the source receives 0 answers and the next
  result is the one the standard names.
- **SC-006**: Without activation, the same flows put 0 R2C `_meta` entries on the wire, and still
  complete.
- **SC-007**: Two owners with the same `context_id` get two different thread ids; a second
  unfinished call in one context is refused 100% of the time.
- **SC-008**: A checkpoint source paused for input, with the server rebuilt on the same keys,
  completes after the retry; a live source in the same situation ends with the "lost" text.
- **SC-009**: The client makes 0 requests to a host other than its connection's origin when
  reading artifacts.
- **SC-010**: The full suite passes on the installed wheel on Python 3.11, 3.12 and 3.13; the
  core-only and A2A-only environments still pass; every `wire` rule of the README still has an
  example.

## Assumptions

- **Users**: `Remote` (007) in this repository first; owners of an MCP server who add R2C to it;
  authors of MCP clients.
- **MCP Python SDK 2.3** (`mcp>=2.3,<3`) is the only MCP dependency, behind `[mcp]`. It has
  multi-round-trip results, the `Extension` interface (tools, resources, methods, a `tools/call`
  interceptor) and `RequestStateBoundary`, which `MCPServer` installs by default with a
  process-local key and a 600 s TTL. The state is bound to the tool, a digest of its arguments,
  the principal and the audience; the door relies on this and does not re-check it.
- **Durability**: with the default process-local key, a restart makes every paused call's
  `requestState` invalid; resuming after a restart needs fixed keys (the SDK's
  `RequestStateSecurity(keys=...)`) and a durable source store. The record of unfinished calls
  per context lives in memory; across several processes it is not shared (a store for it can be
  added later).
- **Live sources** need the retry to reach the process that holds the paused run (ADR, decision
  4). This is documented, not solved.
- **Expiry** is applied when the retry arrives, as on A2A; the `requestState` TTL is the outer
  limit of any paused call.
- **Transport**: the in-process tests use the MCP SDK's own client and server over streamable
  HTTP without opening a network port where the SDK allows it.
- **What a plain tool returns**: a string becomes a `text` block; other JSON values become
  structured content with a text rendering; a tool may also return R2C artifacts and usage. The
  exact shape is for `plan.md`.
- **The client's MCP answers are always the person's**: the client refuses `caller` on an
  approval and `policy` everywhere, because MCP requires user review and the derived answer is
  always `person`. A caller's agent may pre-fill a form (brief, section 8), not send it.
- **Decided by the maintainer** (2026-11-20): Q1 A (MCP Skills is its own spec, 005), Q2 A
  (O6: the usage so far rides beside `input_requests` on an input-required result).
- **Already decided elsewhere**: O3 (R2C-MCP-3, spec 002); one thread per door (ADR, decision
  6); the agent is a tool only when asked (`mcp_tool=True` on `Remote`, decision 5); MiB (O11).
- **Out of scope**: MCP Skills (005); `Remote` and its ASGI app (007); the LangGraph bridge
  (006); MCP Tasks; URL
  mode elicitation on the remote side; sampling and roots; authentication (the owner configures
  the SDK's); a caller's presentation of forms; remembered consent.
