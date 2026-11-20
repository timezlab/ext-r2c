# Feature Specification: A2A binding (`ext_r2c.a2a`)

**Feature Branch**: `main` (no branch; the directory is `specs/003-a2a-binding`)

**Created**: 2026-11-20

**Status**: Draft

**Input**: User description: "003-a2a-binding — ext_r2c.a2a, the A2A door of the Python SDK,
behind the [a2a] extra (a2a-sdk 1.3). Run events ⇄ A2A wire over a2a-sdk, for both sides.
Remote side: an a2a-sdk AgentExecutor that drives an ext_r2c.core AgentSource through Driver and
turns run events into A2A (streamed `response` inline artifact for reply chunks, `activity` and
`usage` parts, questions and approvals in TASK_STATE_INPUT_REQUIRED status messages with the
text fallback, artifacts by presentation, done/error as task states); reads answers from client
messages, checks them with check_answer, re-asks with `errors`, refuses wrong id and expired,
one unfinished task per context, thread_id = f(door, owner, contextId), resume after restart
through the task store; agent card with the extension declared; activation per R2C-ACT rules.
Caller side: a client that reads R2C parts from the stream, builds answer parts, and reattaches
after a cut. Plus the example replay. A hand-written AgentExecutor keeps working with R2C
helpers. Done when real a2a-sdk client↔server round trips in process cover every a2a example's
flow. Owns open points O8, O9 and O10 of `specs/001-standard-v1/research.md`."

## Context

Spec 001 wrote the standard (84 tagged rules, 30 A2A wire examples). Spec 002 built
`ext_r2c.core`: the models, forms, the answer check, the text fallback, the neutral run events,
`AgentSource` with its two pause styles, and the `Driver` that runs either style the same way.
Nothing in the package speaks A2A yet: a remote cannot serve R2C to an A2A caller, and a caller
cannot read it.

This spec builds the A2A door, `ext_r2c.a2a`, behind the `[a2a]` extra, on a2a-sdk 1.3. It has
two sides:

- **Remote side**: an a2a-sdk agent executor that runs an `AgentSource` through the `Driver` and
  writes its run events as A2A, and reads the caller's answers back; plus helpers a remote owner
  can call from an executor they wrote by hand.
- **Caller side**: a client that sends messages with R2C activated, reads R2C content out of the
  stream as typed objects, sends answers, and reattaches after a cut.

`Remote` (006) will compose this door with the MCP door (004); this spec does not build `Remote`.
The LangGraph bridge (005) will be one `AgentSource`; this spec tests with the fake sources of
002 and with sources written in the tests.

Readers of this spec are the people who write `Remote` and the bridges in this repository, remote
owners who keep their own a2a-sdk executor, and authors of A2A callers.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Serve an agent source over A2A, with questions and approvals (Priority: P1)

A remote owner has an `AgentSource` (any pause style) and an agent card's name, description and
skills. They hand both to the A2A door and serve it with a2a-sdk. A caller that activates R2C
sends a message; it sees the agent's reply stream in as one `response` artifact, each activity
as a working status with its text, and, when the agent needs a person, a question or an
approval in an input-required status with its text fallback. The caller answers in a new message
on the same task; the agent goes on from where it stopped and the task completes with the usage
so far.

**Why this priority**: this is the door. Without it no remote can offer R2C over A2A, and the
example flows cannot be replayed.

**Independent Test**: serve the fake checkpoint source and the fake live source from spec 002
in process; a real a2a-sdk client sends the two inputs of the contract suite (question,
approval), answers, and checks the task's events and final state.

**Acceptance Scenarios**:

1. **Given** a served source that asks a question, **When** an activated client sends "Write
   the report", **Then** the stream shows a working status with the activity and its label as
   text, then an input-required status whose message holds the question as an R2C data Part and
   the fallback text Part (R2C-A2A-1, R2C-CORE-4), and the task stops at input-required.
2. **Given** that task, **When** the client sends a new message with the task's `taskId` and
   `contextId` and an `answer` Part for `q-1` (R2C-A2A-2), **Then** the agent receives exactly
   that answer, the reply chunks arrive as updates of one inline artifact marked
   `response: true`, and the task ends completed with a `usage` Part in its last status
   (R2C-A2A-4).
3. **Given** a served source that asks an approval, **When** the client answers
   `{"decision": "deny", "reason": "Not before Monday."}`, **Then** the agent receives the deny
   with its reason and the task completes; the tool behind the approval never runs.
4. **Given** the same flows, **When** they run once with a checkpoint source and once with a
   live source, **Then** the wire is the same (same states, same parts, same order).
5. **Given** a running or paused task, **When** the client calls `CancelTask`, **Then** the task
   ends canceled, a paused live source sees a declined answer, and a checkpoint source is never
   resumed.

---

### User Story 2 - Refuse or re-ask, never pass a bad answer to the agent (Priority: P1)

The remote receives answers it must not hand to the agent: a value that fails the form, an
`edit` whose args break `args_schema`, an answer for an `id` that is not pending, an answer after
the request expired, an answer claiming a role the request does not allow. The door decides,
using the core's answer check, and the agent sees only an acceptable answer.

**Why this priority**: these are the safety and robustness rules of R2C (R2C-ASK-4, -5, -6,
R2C-ANSWER-4). A door that lets a bad answer through breaks the guarantee that a run never dies
from a malformed reply and that an approval is never decided by the wrong party.

**Independent Test**: for each case, a client sends the bad answer to a paused task and the
test checks the next status and that the source received nothing.

**Acceptance Scenarios**:

1. **Given** a task paused on `q-1`, **When** the answer leaves a required field empty, **Then**
   the next status is input-required with the same request, same `id`, plus `errors` naming the
   field (R2C-ASK-6), and the source received no answer.
2. **Given** a task paused on `q-1`, **When** the client answers `q-9`, **Then** the next status
   is input-required, its text says the answer was refused and why, `q-1` stays pending, and
   the source received nothing (R2C-ASK-5).
3. **Given** an approval with `expires_at` in the past, **When** an answer arrives, **Then** the
   approval counts as deny, the agent goes on with a deny, and the text of the next status says
   the answer came too late (R2C-ASK-4, `a2a/refuse-expired.json`).
4. **Given** a task paused on an approval, **When** the answer claims `answered_by.role =
   caller`, **Then** it is re-asked with `errors` and never reaches the agent (R2C-ANSWER-4; the
   core's check already reports it).
5. **Given** the answer roles that the standard leaves to the remote, **When** an approval with
   `answer_by: approver` is answered with `answered_by.role = policy`, or a question is answered
   with `answered_by.role = policy`, **Then** the remote accepts both: `answered_by` is the
   client's claim (R2C-ANSWER-6), and keeping a `policy` off an approver's approval is the
   client's duty (R2C-ANSWER-5). (O8, decided 2026-11-20: Q1 C.)
6. **Given** an answer larger than the size limit, **When** it arrives, **Then** it is re-asked
   with a "too large" error and the oversized content is not parsed further.

---

### User Story 3 - Show only plain A2A to a caller that did not activate R2C (Priority: P1)

A caller that knows nothing of R2C talks to the same remote. It must get a working A2A agent:
plain text progress, text questions, standard artifacts, and no R2C part or metadata anywhere.
A caller that lists the R2C URI in its `A2A-Extensions` header gets R2C, and sees the URI echoed
back.

**Why this priority**: R2C is an extension, never a requirement (constitution IV, R2C-ACT-1..3).
A door that leaks R2C parts to a plain client breaks that client.

**Independent Test**: run the same source twice, with and without the header; compare the
streams with `a2a/activation.json` and `a2a/not-activated.json`.

**Acceptance Scenarios**:

1. **Given** the served remote, **When** a client reads the agent card, **Then**
   `capabilities.extensions` lists the R2C URI with `required: false` (R2C-ACT-1,
   `a2a/agent-card.json`).
2. **Given** a request with the R2C URI in `A2A-Extensions`, **When** the remote answers,
   **Then** the response header echoes the URI and the stream carries R2C parts (R2C-ACT-2).
3. **Given** the same request without the header, **When** the remote answers, **Then** no Part
   and no artifact carries R2C data or metadata, no reasoning is sent, the question is asked as
   text in an input-required status, and the reply is a standard artifact (R2C-ACT-3,
   R2C-ASK-8).
4. **Given** a text-only question whose form has a single `one` or `text` field, **When** the
   plain client replies in text that fits it, **Then** the remote takes the text as the answer
   and goes on (`a2a/text-answer-not-activated.json`); **When** the text does not fit, or the
   form has other fields, **Then** the remote asks again in text.

---

### User Story 4 - Keep conversations apart and survive a restart (Priority: P1)

Two owners may choose the same `contextId`; their agent threads must never meet. A context has
at most one unfinished task. A follow-up in a finished conversation opens a new task that
remembers it. A remote restarted while a task waits at input-required resumes that task when the
answer arrives, as long as its task store and the source's own storage are durable.

**Why this priority**: these are R2C-ID-1, R2C-ID-2 and the resume promise of the brief
(success criterion 4). Getting the thread key wrong leaks one user's conversation to another.

**Independent Test**: in-process server with a durable test task store and a checkpoint source
with a durable store; drop the server object and build a new one on the same stores between
the question and the answer.

**Acceptance Scenarios**:

1. **Given** owners A and B who both send `contextId: "ctx-1"`, **When** both run, **Then**
   the source sees two different thread ids, and neither owner can read or resume the other's
   task.
2. **Given** a context whose first task is completed, **When** the client sends a message with
   the same `contextId` and no `taskId`, **Then** a new task opens on the same thread
   (R2C-A2A-7, `a2a/follow-up-context.json`).
3. **Given** a context with a task at input-required, **When** the same owner sends a message
   with that `contextId` and no `taskId`, **Then** the remote refuses to open a second task
   (R2C-ID-2): the new task ends at once in `TASK_STATE_REJECTED` with a text naming the
   unfinished task, and the first task is untouched. (O9, decided 2026-11-20: Q2 A.)
4. **Given** a checkpoint source paused on `q-1` and a remote restarted on durable stores,
   **When** the answer arrives, **Then** the door reads the pending request back from the
   task's last status, checks the answer against it, and the source resumes and completes.
5. **Given** a live source paused on `q-1` and a restarted remote, **When** the answer arrives,
   **Then** the task ends failed with a text saying the paused run was lost and should be asked
   again.

---

### User Story 5 - Read R2C as a caller, answer, and reattach (Priority: P2)

An A2A caller (a person-facing app or an orchestrating agent) uses the client of this door. It
sends a message with R2C activated and reads an ordered stream of typed items: reply text,
activities, requests, artifacts with their presentation, usage, and the task's state. It builds
an answer for a pending request, checked with the core before it is sent. When its stream is
cut, it reattaches to the task and goes on, and it can fetch the task's last status and
artifacts.

**Why this priority**: callers need it to use R2C at all, and the round-trip tests need a client.
It ranks below the remote side because a caller can read R2C parts with a2a-sdk alone.

**Independent Test**: the same in-process round trips as stories 1–4, driven only through this
client; plus a cut stream reattached with `SubscribeToTask` (`a2a/resubscribe.json`).

**Acceptance Scenarios**:

1. **Given** a running task, **When** the client reads the stream, **Then** it yields one typed
   item per R2C object and per reply chunk, and ignores, without error, an unknown kind or an
   unknown field (R2C-CORE-5, -6, `a2a/unknown-kind-ignored.json`).
2. **Given** a pending request, **When** the caller builds an answer that fails the request,
   **Then** the client reports the problems before sending anything; **When** the answer is
   good, **Then** it sends a message with the task's `taskId` and `contextId`, the answer Part
   and a text Part saying the answer in words (R2C-A2A-2).
3. **Given** a stream cut after the second event, **When** the client reattaches, **Then** it
   receives the following events and the task's end, and `GetTask` gives the artifacts and the
   last status with usage (R2C-A2A-6).
4. **Given** a file artifact with a `url` on the connection's own origin and another with a `url`
   on a different host, **When** the caller asks the client for their content, **Then** the
   first is fetched and the second is returned as a link with no request made to that host
   (R2C-SAFETY-1).
5. **Given** an approval, **When** the caller's own agent tries to answer it through the client
   as `caller`, **Then** the client refuses (R2C-ANSWER-4).

---

### User Story 6 - Keep a hand-written executor, add R2C with helpers (Priority: P2)

A remote owner already has an a2a-sdk agent executor and does not want to rewrite it as an
`AgentSource`. They call R2C helpers from their own code: tell whether R2C is active for this
request, emit an activity, ask a question or an approval and read the answer back, deliver an
artifact with its presentation, report usage. The helpers apply the same rules as the door:
fallback text, activation, answer check, re-ask.

**Why this priority**: the brief and the ADR promise that an existing a2a-sdk remote adds R2C
without being rewritten (constitution III). It is P2 because `Remote` (006) accepts such an
executor, so the helpers must exist before 006.

**Independent Test**: a test-only executor, written against a2a-sdk only, uses the helpers to
ask one question and deliver one artifact; the round trip matches the same example files as
story 1.

**Acceptance Scenarios**:

1. **Given** a hand-written executor that asks a question through the helpers, **When** an
   activated client runs it, **Then** the wire equals what the door sends for the same request.
2. **Given** the same executor, **When** a plain client runs it, **Then** the helpers send text
   only (R2C-ACT-3).
3. **Given** a bad answer, **When** the executor reads it through the helpers, **Then** the
   helpers re-ask or refuse as in story 2 and the executor's code receives only a good answer.

---

### User Story 7 - Every A2A example is a real round trip (Priority: P1)

The A2A example files (30 today) are the shared test suite (constitution II). Each one's flow is
reproduced by a real a2a-sdk client talking to a real a2a-sdk server in process, through this
door, and the R2C content on the wire matches the file.

**Why this priority**: it is the done condition of this spec, and the evidence that the door
implements the standard rather than an idea of it.

**Independent Test**: one parametrised test per A2A example file.

**Acceptance Scenarios**:

1. **Given** any A2A example file, **When** its flow is played in process (the remote side by a
   scripted source, the client side by the steps from the client), **Then** every R2C object and
   every state on the wire equals the file's, ignoring only values the file marks or the
   replay names as generated (message ids, timestamps, task ids where the server issues them).
2. **Given** an example whose flow this door cannot produce, **When** the replay runs, **Then**
   the test fails with the file name; no example is skipped silently.

### Edge Cases

- **Reply chunks without activation**: the reply still streams, as a standard artifact with no
  R2C metadata.
- **An activity whose `label` changes between updates**: allowed; the `id` is the activity's
  identity and a client shows the latest label. **A `usage` that comes while an activity is
  running or a request is pending**: any status message may carry at most one usage Part, next
  to a request or an activity; this door still sends it only in input-required and terminal
  statuses. (O10, decided 2026-11-20: Q3 A.)
- **A source that yields usage several times**: each is cumulative (R2C-USAGE-2); the door sends
  the latest, and the terminal status always carries the last one known.
- **A source that ends with an error**: the task ends failed, the error's reason as text, plus
  the last usage. A cancelled run ends canceled, not failed.
- **A message with a `taskId` of a finished task**: refused by a2a-sdk as it already is; the
  door adds nothing.
- **A message with `taskId` but a `contextId` that differs from the task's**: refused by a2a-sdk
  (`InvalidParamsError`); the door adds nothing.
- **An answer message with several answer Parts, or none**: no Part matches the pending `id`
  means "no answer for the pending request" (R2C-ASK-5); several Parts for the pending `id`
  are refused in text.
- **An answer Part that is not a valid `answer` object**: re-asked with `errors`, like a value
  that fails its form.
- **Text sent to a task that waits on an approval, without activation or without an answer
  Part**: an approval is never taken from free text; the remote asks again.
- **Inline content (`raw` or `inline` text) over 5 MiB from a source**: the door does not send
  it inline (R2C-SAFETY-4); the run ends failed with a reason naming the size, unless the
  source gives a `url`.
- **A `live` artifact or a `file` with a `url`**: sent as the source gave it; the door never
  fetches or proxies it.
- **The client's stream is cut while the task waits at input-required**: reattaching shows the
  same pending request; answering it works as before.
- **The client reattaches to a task of another owner**: refused by a2a-sdk's owner-scoped task
  store; the door adds nothing.
- **Owner unknown** (a server with no authentication): every request has the same owner, the
  a2a-sdk default; thread ids still differ by context.

## Requirements *(mandatory)*

### Functional Requirements

**Serving (story 1)**

- **FR-001**: The A2A door MUST offer an a2a-sdk agent executor that runs one `AgentSource`
  through the core's `Driver`, and a way to build the agent card from the source's card info.
- **FR-002**: The door MUST map run events to the A2A wire as follows, when R2C is active:
  reply chunks → updates of one inline artifact with R2C metadata `response: true`; activity →
  a working status with the activity Part and its fallback text, one activity per update
  (R2C-A2A-3); ask → an input-required status with the request Part and its fallback text
  (R2C-A2A-1); artifact → an artifact update carrying R2C metadata with its presentation and
  state (R2C-A2A-5); usage → a usage Part in a status message (R2C-A2A-4); done → completed;
  error → failed, or canceled for a cancel.
- **FR-003**: Every status message carrying a request or an activity MUST also carry its text
  Part, from the core's fallback text (R2C-CORE-4).
- **FR-004**: The terminal status MUST carry the last usage the source reported, if any.
- **FR-005**: `CancelTask` MUST cancel the run through the driver and end the task canceled.
- **FR-006**: The door MUST keep no state of its own about a pending request: it reads the
  pending request back from the task's last input-required status in the task store.

**Answers (story 2)**

- **FR-007**: On a message to a task at input-required, the door MUST find the answer Part for
  the pending request and check it with the core's answer check before the source sees it.
- **FR-008**: An answer that fails the request MUST make the door send the same request again,
  same `id`, with the problems as `errors`; the source receives nothing and the task stays at
  input-required (R2C-ASK-6).
- **FR-009**: An answer whose `id` matches no pending request MUST be refused in text; the
  pending request stays pending (R2C-ASK-5).
- **FR-010**: Past `expires_at`, the pending request MUST count as declined (a question) or
  deny (an approval); the source receives that outcome, the run goes on, and an answer that
  arrives late is refused in the text of the next status (R2C-ASK-4, R2C-ASK-5).
- **FR-011**: An approval answered with `answered_by.role = caller` MUST be re-asked with
  `errors`, never delivered (R2C-ANSWER-4).
- **FR-012**: A `policy` answer MUST be accepted for a question and for an approval, including
  one with `answer_by: approver`; the door refuses no answer for its `answered_by` role except
  `caller` on an approval (O8; R2C-ANSWER-5, R2C-ANSWER-6).

**Activation (story 3)**

- **FR-013**: The agent card MUST list the R2C URI in `capabilities.extensions` with
  `required: false` (R2C-ACT-1).
- **FR-014**: R2C content MUST be sent only when the request activated R2C, and the response
  MUST echo the activated extensions (R2C-ACT-2).
- **FR-015**: Without activation the door MUST send text and standard artifacts only: no R2C
  Part, no R2C metadata, no reasoning activity; requests are asked in text (R2C-ACT-3).
- **FR-016**: Without activation, a text reply MUST be taken as the answer only when the form is
  a question with exactly one `one` or `text` field and the text fits it; otherwise the door
  asks again in text. An approval is never answered by text (R2C-ASK-8).

**Threads (story 4)**

- **FR-017**: The thread id given to the source MUST be the core's
  `thread_id("a2a", owner, contextId)`, with the owner from the same owner resolver as the task
  store (R2C-ID-1).
- **FR-018**: A message that would open a second unfinished task in a context MUST be refused,
  leaving the unfinished task untouched (R2C-ID-2): the new task ends in
  `TASK_STATE_REJECTED` with a text naming the unfinished task's id (O9).
- **FR-019**: A message with a known `contextId`, no `taskId`, and no unfinished task in that
  context MUST open a new task on the same thread (R2C-A2A-7).
- **FR-020**: After a restart on a durable task store, an answer to a paused checkpoint run MUST
  resume it through the driver; an answer to a paused live run MUST end the task failed with a
  text saying the run was lost.

**Client (story 5)**

- **FR-021**: The client MUST send messages with R2C activated, and yield, in stream order,
  typed items for reply text, activities, requests, artifacts, usage and task state; unknown
  kinds and unknown fields are skipped without error.
- **FR-022**: The client MUST check an answer with the core before sending it, refuse to send an
  approval answer as `caller`, and send it with the task's `taskId` and `contextId` and a text
  Part saying the answer in words (R2C-A2A-2, R2C-ANSWER-4).
- **FR-023**: The client MUST reattach to a task after a cut (`SubscribeToTask`) and fetch its
  last status and artifacts (`GetTask`) (R2C-A2A-6).
- **FR-024**: The client MUST expose a task's `contextId` and `taskId` so its user can store them
  (R2C-ID-3); storing them is the caller's business.
- **FR-025**: When asked for an artifact's content by `url`, the client MUST fetch only from the
  connection's own origin, and return any other `url` as a link without a request
  (R2C-SAFETY-1). It MUST apply its size limits and report oversized content as too large
  (R2C-SAFETY-5).

**Helpers (story 6)**

- **FR-026**: The door MUST offer helpers for a hand-written a2a-sdk executor to tell whether R2C
  is active, and to emit an activity, ask and read back a checked answer, deliver an artifact,
  and report usage, with the same wire and the same rules as FR-002 to FR-016.
- **FR-027**: The door's own executor MUST be built on those helpers, so the two cannot drift.

**Replay and packaging (story 7)**

- **FR-028**: Every file in `standard/v1/examples/a2a/` MUST be replayed as a real in-process
  a2a-sdk round trip through this door; a file the replay cannot cover fails the test.
- **FR-029**: `ext_r2c.a2a` MUST import only from `ext_r2c.core`, the standard library and the
  `[a2a]` extra's packages; `import ext_r2c` and `import ext_r2c.core` MUST keep working without
  the extra (constitution VIII).
- **FR-030**: The decisions on O8, O9 and O10 MUST be written into `standard/v1/README.md`:
  O8 as prose on R2C-ANSWER-6 (the remote accepts the role claim, `caller` on an approval
  aside); O9 on R2C-ID-2 with a new A2A example of the rejected task; O10 on R2C-ACTIVITY-2
  (the label may change, the latest is shown) and R2C-A2A-4 (any status message may carry at
  most one usage Part) with an example of a usage next to an activity. Every example MUST
  still validate and replay.

### Key Entities

- **A2A door**: the executor plus card builder that serves one `AgentSource` over A2A.
- **Activation**: whether the current request listed the R2C URI; decides R2C content or text.
- **Pending request**: the request in a task's last input-required status; the only record of
  what the task waits for.
- **Response artifact**: the one inline artifact per task that carries the reply chunks.
- **Owner**: who the task store says the request belongs to; with the `contextId`, it keys the
  thread.
- **Unfinished task**: a task in a working or input-required state; at most one per context.
- **Client stream item**: one typed thing a caller reads: reply text, activity, request,
  artifact, usage, state.
- **R2C helpers**: the functions a hand-written executor calls to speak R2C.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the A2A example files (30 today, plus the ones FR-030 adds) are replayed as real in-process round trips, and
  every R2C object and state on the wire equals the file's; the test run prints the count.
- **SC-002**: The fake checkpoint source and the fake live source from spec 002 both complete
  the question, approval, deny, decline and cancel flows over A2A with byte-equal R2C content
  on the wire.
- **SC-003**: In every bad-answer case of story 2, the source receives 0 answers, the run does
  not end, and the next status is the one the standard names.
- **SC-004**: Run without activation, the same flows put 0 R2C Parts and 0 R2C metadata entries
  on the wire.
- **SC-005**: Two owners with the same `contextId` get two different thread ids; a second
  unfinished task in one context is refused 100% of the time.
- **SC-006**: A checkpoint source paused at input-required, with the server rebuilt on the same
  durable stores, completes after the answer; a live source in the same situation ends failed
  with the "lost" text.
- **SC-007**: A hand-written executor using the helpers produces the same R2C wire as the door
  for the same request.
- **SC-008**: The client makes 0 requests to a host other than its connection's origin when
  reading artifacts.
- **SC-009**: The full suite passes on the installed wheel on Python 3.11, 3.12 and 3.13; the
  core-only environment (no extra) still imports `ext_r2c.core`; every `wire` rule of the
  README still has an example.

## Assumptions

- **Users**: `Remote` (006) and bridge authors in this repository first; remote owners who keep
  their own a2a-sdk executor; authors of A2A callers.
- **a2a-sdk 1.3** is the only A2A dependency, behind `[a2a]`. Its task store is owner-scoped,
  the client may choose `contextId`, and messages with a wrong `contextId` or to a finished task
  are refused by the SDK itself; the door relies on these and does not re-check them.
- **Transport**: the in-process tests use a2a-sdk's own client and server over its JSON-RPC
  transport, without opening a network port where the SDK allows it. Other transports work as
  far as a2a-sdk supports them; they are not tested here.
- **Durability**: the door is as durable as the task store and the source's storage it is given.
  The tests use a durable store a2a-sdk ships (or a test store that survives rebuilding the
  server). How long a context is kept is the remote owner's to document (R2C-ID-4).
- **Expiry** is applied when the next message for the task arrives (as `a2a/refuse-expired.json`
  shows): the expired request counts as declined or deny, the run goes on, and the late answer
  is refused in that status's text. A timer that ends an idle expired task on its own is out of
  scope.
- **Decided by the maintainer** (2026-11-20): Q1 C (O8: the remote accepts `policy` answers,
  for questions and for approver approvals alike), Q2 A (O9: a second unfinished task is
  rejected with `TASK_STATE_REJECTED` and a text), Q3 A (O10: an activity's label may change;
  any status message may carry one usage Part).
- **Usage placement**: the door holds the last usage and sends it in the next input-required
  status and in the terminal one, never in a status of its own; the standard allows more
  (O10), receivers must accept it anywhere.
- **Reply without R2C**: a reply streamed to a plain client is a standard artifact, as
  `a2a/not-activated.json` shows.
- **Reasoning** activities are sent only when the source yields them and R2C is active;
  deciding whether to produce reasoning is the source's (and its owner's) business
  (R2C-ACTIVITY-5).
- **Already decided elsewhere**: an approval answered as `caller` is refused (the core's check,
  R2C-ANSWER-4); the size unit is MiB (O11).
- **Out of scope**: the MCP door (004), the LangGraph bridge (005), `Remote` and its ASGI app
  (006), authentication (the remote owner configures a2a-sdk's), push notifications, a caller's
  presentation of requests and artifacts, remembered-consent storage, an expiry timer.
