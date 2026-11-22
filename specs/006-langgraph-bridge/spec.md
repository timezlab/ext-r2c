# Feature Specification: LangGraph bridge (`ext_r2c.bridges.langgraph`)

**Feature Branch**: `main` (no branch; the directory is `specs/006-langgraph-bridge`)

**Created**: 2026-11-22

**Status**: Draft

**Input**: User description: "006-langgraph-bridge — `ext_r2c.bridges.langgraph`, the first bridge
behind `AgentSource` (spec 002), behind the `[langgraph]` extra (no `[a2a]`, no `[mcp]`;
principle VIII). `LangGraphAgent` wraps a compiled LangGraph graph (a LangChain agent) and is an
`AgentSource`, so the A2A door (003) and the MCP door (004) serve it with no change to the graph
(principle III). LangChain tools become `ToolSpec`s. It passes the shared conformance suite
(`python/tests/agent_source_suite.py`). Graph to run events: reply tokens as streamed reply
chunks, tool activity as `activity`, reasoning only when the owner turns it on, usage, file
content blocks as artifacts, errors, done. Human-in-the-loop: `HumanInTheLoopMiddleware` in its
`batched` and `per_call` modes, a hand-written `interrupt()`, and the `status = "input_required"`
turn end, all turned into `question` and `approval` asks; an approval is never answered by a
model (principle V). It is a checkpoint-style source: it works across a restart with the
checkpointer's state, the thread keyed by owner and context. Done when a real LangGraph graph
passes the suite, a real A2A round trip and a real MCP round trip (in process, the replay kits)
each serve one wrapped graph including a pause and an answer, and `Remote` (007) can take
`agent=LangGraphAgent(graph)`. Read the installed langgraph / langchain packages, not memory."

## Context

Spec 002 built the neutral core: `AgentSource` (an agent behind R2C, with `run` and `resume` as
async generators of run events and a `pause` style of `checkpoint` or `live`), the `Driver` that
runs a source on a thread, the run events, and `ToolSpec`. Specs 003 and 004 built the A2A door
and the MCP door; both serve any `AgentSource`, and both were tested with two fakes only. This
spec builds the first **real** source: `LangGraphAgent`, in `ext_r2c.bridges.langgraph`, behind
the extra `[langgraph]`.

An owner of a LangGraph agent has a compiled graph, usually from LangChain's `create_agent`, with
a checkpointer, and often a `HumanInTheLoopMiddleware` or a hand-written `interrupt()`. One line,
`LangGraphAgent(graph)`, makes it an `AgentSource`; both doors then serve it. The graph is not
edited (constitution III). The bridge does one job: **turn what the graph streams and where it
pauses into neutral run events, and turn the caller's answer back into what the graph expects.**

Specs 002 to 004 call this bridge `005` and `Remote` `006`. When MCP Skills became 005 they moved
to 006 (this spec) and 007.

### What the installed packages do (checked 2026-11-22)

Checked in a scratch environment on Python 3.12 with `langchain` 1.5.2, `langchain-core` 1.8.4,
`langgraph` 1.2.24, `langgraph-checkpoint` 4.3.2, `langgraph-prebuilt` 1.1.3 and
`langgraph-checkpoint-sqlite` 3.1.3, with a small scripted chat model (no network, no keys). None of
the packages has a malicious-package advisory on OSV. Each finding says what this spec does with it.

1. **The stream.** `astream` with the modes `messages` and `updates` gives typed parts. Tokens
   arrive as AI message chunks; usage arrives on a late chunk; a tool's result arrives as a tool
   message; a pause arrives as an update `__interrupt__`. After the stream ends, `aget_state`
   lists the pending interrupts (`id`, `value`, a response schema), read back from the
   checkpointer. *The bridge asks from that read-back, never from the stream part (FR-014).*
2. **`HumanInTheLoopMiddleware`, `batched`.** One interrupt per model turn holds every gated call:
   `{action_requests: [{name, args, description}], review_configs: [{action_name,
   allowed_decisions}]}`. One resume carries all decisions, in order. **A resume with the wrong
   number of decisions, or a decision type the tool does not allow, raises `ValueError` and
   leaves the thread unable to continue:** a later, correct resume fails the same way (tried:
   a plain resume, a resume keyed by the interrupt id, and a resume from the earlier checkpoint).
   *The bridge never sends such a resume (FR-020).*
3. **`HumanInTheLoopMiddleware`, `per_call`.** One interrupt per gated call, each with its own
   `id`, a payload `{type: "tool_approval", tool_call_id, name, args, description}` and a response
   schema that lists the decisions it accepts. They are raised together, in one pass. Each is
   resumed by its own `id`; the others stay pending. A decision the call does not accept raises a
   validation error but **leaves the thread intact** (a retry works). *Each answer resumes only its
   own interrupt (FR-018).*
4. **Decisions.** `approve`, `edit` (an edited action: name and arguments), `reject` (an optional
   message) and `respond` (a message that becomes the tool's result). A tool's `allowed_decisions`
   picks which; the default is all four. An edit leaves a note in the tool's result. *R2C has
   `allow`, `edit`, `deny`; `respond` has no R2C name (FR-016).*
5. **A hand-written `interrupt(value)`.** `value` is any value; the resume value becomes the
   call's return value; the node restarts from its top on resume; several `interrupt()` calls in
   one node pause one after another; it also works inside a tool. A resume keyed by the
   interrupt's `id` works for every kind of interrupt, `batched` included.
6. **A new input on a paused thread** starts over from the graph's start; the old pause is
   dropped. In an agent, the model then sees an AI message with a tool call that has no tool
   message after it (checked for both modes), a shape real providers reject. *The bridge settles
   a pending approval before it sends a new input (FR-007).*
7. **A restart.** A new graph object over the same SQLite file sees the same pending interrupts,
   and each tool then ran exactly once. *This is the S7 case (FR-015, SC-003).*
8. **A tool that raises after a resume** raises out of the stream; the thread keeps the failed
   task, so a retry would run the tool again. *The run ends `failed` (FR-013).*
9. **Content.** `content_blocks` normalises a message to standard blocks: `text`, `reasoning` (a
   `reasoning` field), `file`, `image` (each with `base64` or `url`, and a `mime_type`),
   `non_standard` for a provider's own shape. Token counts are in `usage_metadata`, with
   `output_token_details` (such as reasoning tokens).
10. **Tools and graphs.** A `BaseTool` has `name`, `description` and a JSON schema of its
    arguments. For a tool whose `args_schema` is a plain JSON Schema dict, `get_input_jsonschema()`
    returns a wrapper around a tool call, not that schema. A compiled `create_agent` graph has
    `.checkpointer`, `.name`, an input schema with `messages`, and its tool node holds the tools by
    name.
11. **Test models.** `GenericFakeChatModel` cannot stream a turn that has tool calls and empty
    text (`No generations found in stream`). A small `BaseChatModel` subclass can.

## User Scenarios & Testing *(mandatory)*

The "user" of this feature is a developer: the owner of a LangGraph agent who wants it served
through A2A or MCP without rewriting it, and the people who write `Remote` (007).

### User Story 1 - Wrap a graph and serve it through both doors, pause and answer included (Priority: P1)

An owner has a compiled agent graph with a checkpointer. They wrap it in one line and serve it
through the A2A door and through the MCP door. A caller sends a request; the agent starts, calls a
tool whose code asks the person a question, the run pauses, the caller answers, and the agent
finishes with a streamed reply. The graph's own code is the same as before.

**Why this priority**: it is the point of the bridge. Without it, the doors have only fakes.

**Independent Test**: build a real graph (a scripted model, a tool that calls `interrupt()` with a
valid R2C question). Run the shared conformance suite on it (S1 to S10). Then serve the same graph
once through a real in-process A2A round trip and once through a real in-process MCP round trip,
each with a pause and an answer, and check the reply text and the end state.

**Acceptance Scenarios**:

1. **Given** a compiled graph with a checkpointer, **When** it is wrapped as
   `LangGraphAgent(graph)`, **Then** the result has `card`, `pause = "checkpoint"`, `run` and
   `resume`, and a `Driver` accepts it as an `AgentSource`.
2. **Given** a wrapped graph whose tool asks a question, **When** the driver runs it, **Then** the
   run yields an `Ask` carrying that question and ends; after the answer the run yields the
   answer's effect, the reply and `Done`, and the graph ran each step once.
3. **Given** the same wrapped graph served through the A2A door, **When** a caller sends a
   message, **Then** the task reaches `input-required` with the question, the caller's answer
   continues the same task, and it completes with the reply text. The same holds through the MCP
   door.
4. **Given** a graph that is not compiled, has no checkpointer, or has no `messages` in its input,
   **When** it is wrapped, **Then** the wrap fails at once with a message that names what is
   missing.
5. **Given** the model streams its text in pieces, **When** a run is read, **Then** the first
   reply chunk reaches the reader before the model has produced its last token.

---

### User Story 2 - Approve, edit or deny tool calls, one at a time (Priority: P1)

A graph uses `HumanInTheLoopMiddleware`. A model turn asks for two sensitive tool calls. Each call
reaches the caller as its own approval, one at a time, in the order the model asked. The caller
allows one and denies the other with a reason. The allowed call runs; the denied one does not, and
the model is told why. This works in both of the middleware's modes.

**Why this priority**: approvals are R2C's reason to exist (constitution V) and HITL is how
LangChain agents ask for them.

**Independent Test**: two graphs on the same script, one `per_call` and one `batched`, each with
two gated tools that count their calls. Drive each through the `Driver` with scripted answers
(allow, deny with a reason) and check the counts, the order of the asks, and the model's final
reply.

**Acceptance Scenarios**:

1. **Given** a `per_call` graph with two gated calls in one model turn, **When** the run pauses,
   **Then** the caller sees one approval, for the first call in the model's order; after it is
   answered, the second; no two are pending at once.
2. **Given** a `batched` graph with two gated calls, **When** the first is allowed and the second
   denied, **Then** nothing runs until both are decided, then the first runs and the second does
   not, and the model sees the second as rejected with the caller's reason.
3. **Given** a tool whose `allowed_decisions` are only `approve` and `reject`, **When** it is
   asked, **Then** the approval offers `allow` and `deny` and no `edit`.
4. **Given** a tool that allows `edit` and whose input schema the bridge can read, **When** the
   caller edits the arguments, **Then** the tool runs with the edited arguments.
5. **Given** an answer whose decision the graph would refuse (a decision the approval did not
   offer), **When** it reaches the bridge, **Then** the bridge refuses it without touching the
   graph, and a later correct answer still resumes the same thread, in both modes.
6. **Given** a tool that allows only `respond`, **When** it is asked, **Then** the caller sees a
   `question` with one text field, and the answer text becomes the tool's result.
7. **Given** any approval, **When** it is asked, **Then** it is addressed to a person or an
   approver, never to the calling model, and the bridge answers none itself.

---

### User Story 3 - A pause survives a restart (Priority: P1)

A graph pauses for an approval. The process stops. A new process starts, builds the same graph
over the same durable checkpointer, and the caller's answer arrives. The agent continues where it
left off, every tool ran once, and the reply is whole.

**Why this priority**: a human may take hours to answer. A pause that dies with the process is
not a pause (spec 002 S7).

**Independent Test**: run the pause test against a real SQLite checkpointer file: process A runs
to the ask and is dropped; process B builds a new graph object and a new `LangGraphAgent` over
the same file and resumes from the saved request and the answer. Repeat for `per_call`, for
`batched`, and for a hand-written `interrupt()`.

**Acceptance Scenarios**:

1. **Given** a pause made before a restart, **When** the same remote restarts and the answer
   arrives, **Then** the run continues with `answer`, the rest of the work, `usage` and `done`,
   and each tool ran exactly once.
2. **Given** the same pause, **When** the request ids are compared before and after the restart,
   **Then** they are equal.
3. **Given** a `batched` pause with two calls, the first answered, **When** the process restarts
   before the second is answered, **Then** nothing has run, and the batch is asked again from its
   first call (FR-019).
4. **Given** a graph on an in-memory checkpointer, **When** the process restarts and an answer
   arrives, **Then** the run ends with a clear "the pause was lost" reason, and the graph is not
   started again.
5. **Given** an answer for a request that is no longer pending (it was already applied, or the
   thread was pruned), **When** it arrives, **Then** the graph is not started again.
6. **Given** the usage of a turn split by a restart, **When** the run ends, **Then** the
   cumulative `usage` equals the sum over every model call of the turn.

---

### User Story 4 - Show what the agent is doing (Priority: P2)

A caller's UI wants a timeline: which tools ran, how long, whether they failed, what the agent
used in tokens, optionally its reasoning, and the files it produced. The bridge gives it, and
gives no more than the owner allows.

**Why this priority**: the activity and usage kinds exist for this (ADR activity-and-usage-kinds);
a bridge that only streams text wastes them. The run is correct without them, so P2.

**Independent Test**: a graph whose scripted model calls two tools (one fails), reasons, and
returns a file block. Read the run events and check the timeline, the usage and the artifact; run
it again with each option changed.

**Acceptance Scenarios**:

1. **Given** a tool call, **When** the tool runs and returns, **Then** the caller sees a `tool`
   activity for it, `running` then `done`, with the tool's name and a duration; a failing tool
   ends `failed`.
2. **Given** a tool call that is waiting for approval, **When** the caller looks at the timeline,
   **Then** there is no `running` activity for it; if it is denied it has no activity at all.
3. **Given** default options, **When** a tool is called, **Then** the activity carries no
   arguments and no result detail; **When** the owner exposes that tool, **Then** it carries
   them.
4. **Given** a model that reasons, **When** the owner has not turned reasoning on, **Then** no
   reasoning leaves the bridge; **When** it is on, **Then** reasoning text arrives as `reasoning`
   activity deltas in readable pieces, and a provider's signature or encrypted reasoning never
   does.
5. **Given** a turn with several model calls, **When** the run ends, **Then** one cumulative
   `usage` states the tokens of all of them, and a field the model did not report is absent, not
   zero.
6. **Given** an AI message with a file block (bytes or a URL), **When** the run is read, **Then**
   an artifact event carries it with its media type, and a block that cannot be handed over (no
   data, not valid) is skipped without ending the run.

---

### User Story 5 - Other ways a graph asks (Priority: P2)

Not every graph uses the middleware. Some call `interrupt()` with their own payload; some end a
turn with a structured reply that says `input_required`. Each becomes an R2C ask. A person who
sends a new message while an approval is pending does not leave the agent in a broken state.

**Why this priority**: real graphs mix these. The middleware path (stories 2 and 3) is the one
that must be right first.

**Independent Test**: three small graphs (a node that interrupts with a valid R2C question, a
node that interrupts with a plain string, an agent that ends a turn with `input_required`) and
one paused approval followed by a new message, each driven through the `Driver`.

**Acceptance Scenarios**:

1. **Given** `interrupt()` called with a valid R2C `question` or `approval`, **When** it pauses,
   **Then** that object is asked as it is, and the answer's value is what `interrupt()` returns.
2. **Given** `interrupt("Which region?")` or any other payload that is not a valid R2C question
   or approval, **When** it pauses, **Then** the caller sees a `question` for a person with one
   text field, and the answered text is what `interrupt()` returns.
3. **Given** a hand-written payload that is an approval addressed to the caller's model, **When**
   it pauses, **Then** it is not asked as an approval; it falls back to a question for a person.
4. **Given** several `interrupt()` calls in a row in one node, **When** the run goes on, **Then**
   each is asked and answered in order.
5. **Given** a turn that ends with a structured reply whose `status` is `input_required`,
   **When** the turn ends, **Then** its message is asked as a question for the caller, and the
   caller's answer is sent to the agent as the next message of the same thread.
6. **Given** an approval waiting, **When** a new message arrives for the same thread, **Then**
   the model never sees a tool call without an answer: the pending call is withdrawn first and
   the model sees it as rejected, with a reason that says it was withdrawn.

---

### User Story 6 - Use a LangChain tool as an R2C tool (Priority: P3)

The owner has LangChain tools (made with `@tool`, `StructuredTool`, or a `BaseTool` subclass)
and wants to serve some of them as MCP tools through `Remote` (007). They convert them without
declaring them again.

**Why this priority**: `Remote(tools=...)` is spec 007. The conversion is small, and the agent
path (stories 1 to 5) does not need it.

**Independent Test**: convert a tool made with `@tool`, one with a pydantic `args_schema`, one with
a plain JSON Schema `args_schema`, and an async-only tool; check name, description, schema and a
call each; convert a tool that needs the running graph and check the refusal.

**Acceptance Scenarios**:

1. **Given** a LangChain tool, **When** it is converted, **Then** the `ToolSpec` has the tool's
   name, its description, and the JSON Schema of its arguments, including a tool whose
   `args_schema` is a plain JSON Schema.
2. **Given** the converted tool, **When** it is called with valid arguments, **Then** the tool
   runs (a sync tool does not block the event loop) and its result comes back.
3. **Given** arguments that break the schema, **When** the converted tool is called, **Then** the
   tool does not run and the caller learns what is wrong.
4. **Given** a tool that needs something only a running graph supplies (injected state, runtime
   or store), **When** it is converted, **Then** the conversion fails at once, naming the
   argument, not at the first call.

---

### Edge Cases

- **No checkpointer, or a state without `messages`:** refused when the graph is wrapped (FR-002).
- **An in-memory checkpointer:** the wrap works and warns that a pause will not survive a restart;
  after a restart the answer ends the run "lost", it never starts the graph again (FR-023).
- **Two approvals in one turn, one denied:** the other still runs (R2C-APPROVAL-4: each is decided
  on its own). Three in a `batched` turn, the middle one denied: the order of results stays the
  model's order.
- **A tool with `allowed_decisions` of only `approve`:** `deny` is not offered. A declined answer
  to it cannot reject the call; the run ends `failed` with a reason that says so, and the call
  does not run (FR-017).
- **`edit` allowed, tool schema unknown** (a graph that is not from `create_agent`): `edit` is
  dropped from the offered decisions (R2C-APPROVAL-3).
- **An answer that is declined** for an approval: a deny (R2C-ANSWER-3). For a question: the
  graph is resumed with a value that means "no answer" (FR-017).
- **A cancel while paused:** the graph is never resumed (S5). The thread stays paused until a new
  input withdraws the pending approval (FR-007).
- **A cancel while the graph runs:** the graph's stream is closed promptly; the model call is not
  left running.
- **A tool that raises after an answer:** the run ends `failed` with the exception's message; open
  tool activities are closed `failed` first (FR-013).
- **A turn with no text at all** (only tool calls): no reply chunk, no error; the turn still ends
  `done`.
- **A model that does not stream:** the whole text arrives, as one chunk.
- **A reply split across a pause** (text, then an approval, then more text): the text is in
  order; the final chunk of the turn carries `last`.
- **An AI message whose chunks have no id:** consecutive chunks of one model call are one message
  for the paragraph break (FR-008).
- **A file block with no data or URL** (the provider hosts it by id), or invalid base64: skipped,
  never fatal.
- **A graph that runs a sub-graph:** the sub-graph's tokens follow LangGraph's own default (not
  streamed); an interrupt raised inside it still reaches the caller through the parent.
- **The same answer delivered twice, or after the pause is gone:** the graph is not started again
  (FR-023); the driver already refuses a second delivery on a live run (S6).
- **A very large file block:** handed over as the model produced it; what a door will carry is the
  door's refusal, not the bridge's (plan to confirm against 003 and 004).

## Requirements *(mandatory)*

### Functional Requirements

**Wrapping**

- **FR-001**: `LangGraphAgent(graph)` MUST be an `AgentSource`: `card`, `pause = "checkpoint"`,
  `run(input, ctx)` and `resume(answer, ctx)` as async generators of the core's run events. The
  doors, the `Driver` and (007) `Remote` take it without a change. The graph is not edited, wrapped
  in a subclass, or given a hook.
- **FR-002**: Wrapping MUST fail at once, with a message that names the missing piece, when the
  object is not a compiled LangGraph graph, has no checkpointer, or its input has no `messages`.
- **FR-003**: The `card` MUST come from an argument; when none is given, a minimal card is made
  from the graph's name. The bridge reads nothing from the graph's prompts or tools for the card.
- **FR-004**: `ext_r2c.bridges.langgraph` MUST import only `ext_r2c.core` and the packages of the
  `[langgraph]` extra: no `a2a`, no `mcp`, no other bridge. No other module of `ext_r2c` imports
  it. Importing it without the extra MUST raise an `ImportError` that names the extra
  (constitution VIII).

**Threads and input**

- **FR-005**: The graph's thread id MUST be `ctx.thread_id` as given. The same owner and context
  continue one conversation (the messages accumulate); another owner or another context shares
  nothing (ADR thread-per-owner-and-context).
- **FR-006**: A run's input MUST become one human message: the text, plus each part as a standard
  content block chosen by its media type (`image/*`, `audio/*`, `video/*`, other as `file`; bytes
  as base64, a URL as a URL). The bridge does not read, convert or drop a part; a model that
  cannot take one fails in its own way.
- **FR-007**: When a new input arrives on a thread that still has a pending approval, the bridge
  MUST settle it before it sends the input, so that the model never sees a tool call with no
  answer: the call is withdrawn and the model sees it as rejected, with a reason that says it was
  withdrawn. Other kinds of pause are left as LangGraph leaves them (the node starts again). The
  mechanism (a rejecting resume, or a state update) is the plan's, chosen by test against a model
  that refuses a dangling tool call, as real providers do.

**What the run says**

- **FR-008**: The reply MUST be the text of the graph's AI messages, streamed in order as
  `ReplyChunk`s, as the model produces it. Nothing is added except one blank line between the
  text of two different AI messages when both have text. Text of tool messages and human messages
  is never reply. A model call that the graph's author hides with LangGraph's own `nostream` tag
  stays hidden. The final chunk of a turn MUST carry `last`; a pause is not the end of a turn.
- **FR-009**: Each tool call MUST be one `tool` activity: `id` is the tool call's id, `name` the
  tool's, `running` when the tool starts, then `done` or `failed` with its duration. A call that
  is waiting for approval MUST NOT show `running`; a call that is denied has no activity. `args`
  and `detail` MUST be absent unless the owner exposed that tool (R2C-ACTIVITY-6); the default is
  to expose none.
- **FR-010**: `reasoning` MUST be off by default. When the owner turns it on, reasoning text from
  standard `reasoning` blocks MUST go out as one `reasoning` activity per message, with deltas
  coalesced into readable pieces (R2C-ACTIVITY-7). A provider signature, encrypted reasoning or
  non-standard block MUST NEVER go out (R2C-ACTIVITY-5).
- **FR-011**: `usage` MUST be cumulative for the turn (R2C-USAGE-2), from the token counts the
  graph's models reported, with `model` when a message names it. It MUST be sent once at the end
  of a turn, before `done` (or before the `input_required` ask of FR-022), and the total MUST be
  the same whether or not a restart came between. The turn is the messages since the last human
  message. The bridge MUST NOT invent a cost or a duration; a missing field is absent
  (R2C-USAGE-3).
- **FR-012**: A standard content block of an AI message that is not `text`, `reasoning` or a tool
  call, and that carries bytes or a URL (`file`, `image`, `audio`, `video`), MUST become an
  `ArtifactEvent` with `presentation = "file"`, its media type, a name when the block gives one,
  and an id stable within the task. Blocks are read from the completed message, not from chunks.
  A block with no data, or with data that is not valid, MUST be skipped, not fatal.
- **FR-013**: An exception out of the graph MUST end the run `failed` with its message as the
  reason (the driver does this). Before it does, each tool activity still `running` MUST be
  closed `failed`. When the door cancels a run, the bridge MUST close the graph's stream promptly.

**Pauses**

- **FR-014**: A pause MUST be asked from the checkpointer's pending interrupts, read after the
  stream ended, never from the stream part alone; a pause the checkpointer does not hold is never
  offered. Pending interrupts MUST be asked **one at a time**, tool approvals in the model's
  tool-call order (R2C-APPROVAL-4), the others in the order LangGraph lists them. `run` and
  `resume` MUST end right after the `Ask`.
- **FR-015**: Request ids MUST be stable: the same pause gives the same ids after a restart. A
  generated request's id comes from the interrupt's id (and, in a `batched` pause, the position
  of the call); a hand-written valid R2C request keeps its own id.
- **FR-016**: Each gated call of `HumanInTheLoopMiddleware`, in both modes, MUST be an `approval`
  to a person: a `tool_call` subject with the tool's name and the model's arguments, a short
  title, the middleware's description, and `decisions` mapped from what that call allows:
  `approve` to `allow`, `reject` to `deny`, `edit` to `edit` only when the tool's input schema
  is known (R2C-APPROVAL-3). `respond` is not offered as a decision. A call that allows only
  `respond` MUST be a `question` with one text field instead.
- **FR-017**: An answer MUST be turned into the graph's own decision: `allow` to `approve`;
  `deny` to `reject`, the reason as its message; `edit` to `edit`, with the answer's arguments
  and the call's own tool name; a text answer to `respond`'s message; `declined` to `reject`
  (R2C-ANSWER-3). When the call does not allow `reject`, a declined answer MUST end the run
  `failed` with a reason that says so, and the call MUST NOT run.
- **FR-018**: In `per_call`, an answer MUST resume only its own interrupt, by id; the others stay
  pending and are asked next.
- **FR-019**: In `batched`, nothing MUST run until every call of the batch has a decision. The
  decisions are collected in order and sent in one resume. Decisions collected so far are kept in
  the bridge's memory only: after a restart in the middle of a batch, the batch is asked again
  from its first call. When an answer arrives for a call of a batch the bridge has no record of,
  it keeps that answer and asks the first call whose decision it does not hold.
- **FR-020**: The bridge MUST NEVER send the graph a resume the graph would refuse: a decision
  the call does not allow, a wrong count, an edit that renames the tool. An answer that would
  need one is refused by the bridge, the graph is not touched, and the pause stays pending, so
  that a correct answer still resumes it (finding 2: the middleware's refusal leaves a `batched`
  thread unable to continue).
- **FR-021**: A hand-written `interrupt(value)` MUST be asked as `value` itself when it is a valid
  R2C `question`, or a valid `approval` that is addressed to a person or an approver. Anything
  else (a string, a mapping that is not an R2C object, an approval addressed to the caller) MUST
  be a `question` for a person with one text field: a string is its title, any other value is a
  bounded text in its description. The resume value is the answer's `value` mapping for a valid
  R2C request, the answered text for the fallback, and `None` when declined.
- **FR-022**: When a turn ends with no pause and the graph's final state holds a structured reply
  whose `status` is `input_required`, its message MUST be asked as a `question` with
  `answer_by: caller` and one text field; the structured reply MUST NOT be streamed as reply
  text. The answer MUST be sent as the next human message of the same thread, not as a resume.
- **FR-023**: When an answer arrives and the checkpointer holds no pending interrupt for it (an
  in-memory checkpointer after a restart, a pruned thread, an answer already applied), the run
  MUST end with a reason that says the pause was lost, and the graph MUST NOT be started again.
  See D2 for the code the run ends with.

**Tools**

- **FR-024**: `tool_from_langchain(tool)` MUST return a `ToolSpec` with the tool's name, its
  description and the JSON Schema of its arguments (also when `args_schema` is a plain JSON
  Schema). Its `call` runs the tool's own async entry; a sync tool runs without blocking the
  loop. Arguments MUST be checked against the schema before the tool runs, the way
  `tool_from_function` checks them. A tool that needs something only a running graph supplies
  MUST be refused at conversion, naming the argument.
- **FR-025**: A list of tools MUST convert in one call, keeping the order and refusing the whole
  list when one is refused.

**Options, packaging, proof**

- **FR-026**: The options are keyword-only and default to the safest value: the card, `reasoning`
  (off), and which tools to expose (none).
- **FR-027**: The extra `[langgraph]` MUST name the lower bounds the tests prove and an upper
  bound the plan decides; it MUST NOT include a checkpointer (the owner brings theirs). The dev
  group carries what the tests need, among it the SQLite checkpointer. The core-only, a2a-only
  and mcp-only checks stay green, and a langgraph-only check proves FR-004.
- **FR-028**: Tests MUST run against the installed wheel, with real LangGraph and LangChain
  packages and a scripted chat model as the only fake (constitution VII). The suite of spec 002
  MUST run, S1 to S10, on a real graph (D3).
- **FR-029**: The docs MUST be brought up to date: `python/README.md`, `ARCHITECTURE.md`, the
  white paper where it names the bridge, a dated note on the stale parts of the design brief
  (`serve()`, `a2a/langchain`), `WORKSTATE.md`, and a design doc that records finding 2 and the
  pause-to-ask rules.
- **FR-030**: Nothing in the repo MUST name a private person, host or figure (constitution VI).

### Key Entities

- **LangGraphAgent**: the wrapper. Holds the graph, the card and the options; keeps no stopping
  point of its own, except the decisions of a batch in progress (FR-019).
- **Pause**: what the checkpointer says is pending for a thread: one or more interrupts, each
  with an id, a payload and the decisions it accepts. The only source of an ask.
- **Request id**: the stable name of one ask (FR-015); the answer's `id` is matched against the
  pending pauses by it.
- **Batch**: the decisions collected for one `batched` interrupt, in memory, until complete.
- **Exposed tools**: the set of tool names whose arguments and result detail may be shown on the
  timeline; empty by default.
- **Conformance wrapper** (test only): a thin object around `LangGraphAgent` that records every
  answer that reached `resume` and can misbehave on demand, because the suite asks every source
  for `answers`, `fail_after_ask` and `double_ask` (D3).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A real graph passes the shared suite, S1 to S10, on the installed wheel on Python
  3.11, 3.12 and 3.13, and the two fakes still pass the suite as changed (D3).
- **SC-002**: One wrapped real graph completes a real in-process A2A round trip and a real
  in-process MCP round trip, each with a pause and an answer: the caller sees the question, the
  answer continues the same task, and the reply text equals the script's.
- **SC-003**: A pause made by process A is answered in process B, over the same SQLite file and
  a new graph object, in `per_call`, in `batched` (the batch asked again, FR-019) and for a
  hand-written `interrupt()`; each tool body ran once; the request ids are equal.
- **SC-004**: With two gated calls in one turn, in both modes, the caller is asked exactly twice,
  one at a time, in the model's order; the allowed call runs once and the denied one never does
  (counted in the tool bodies); the model's final reply mentions the reason.
- **SC-005**: A decision the graph would refuse is refused by the bridge in both modes, with no
  call into the graph, and the same thread then resumes with a correct answer (the thread that
  the middleware itself leaves stuck, finding 2).
- **SC-006**: No approval ever reaches `answer_by: caller` or is answered by code in the bridge:
  a hand-written approval addressed to the caller is asked to a person (a test of every path
  that yields an approval).
- **SC-007**: With a gate on the scripted model, the first reply chunk is read before the model
  is released to produce its last token.
- **SC-008**: Cumulative `usage` equals the sum of the model calls of the turn, with a restart
  in the middle, and carries no `cost` and no `duration_ms`.
- **SC-009**: A new input on a paused thread, against a model that rejects a tool call with no
  answer, reaches a normal reply; without the settle step the same test fails (a mutation check).
- **SC-010**: Importing the bridge in an environment with only the `[langgraph]` extra works and
  pulls in no `a2a` or `mcp` module; the core-only, a2a-only and mcp-only checks still pass; the
  bridge's import without the extra names the extra.
- **SC-011**: The converted tools of the examples in story 6 keep name, description and schema,
  and a call with bad arguments never runs the tool.
- **SC-012**: A maintainer who has read only this spec, the plan and the ADR can say, for each
  kind of pause of a graph, what the caller sees and what the graph gets back (checked once,
  like SC-005 of 001).

## Assumptions

**Out of scope:** `Remote` and the policy that answers approvals for a person (007); bridges for
other agent frameworks; graphs whose input has no `messages` (D1); the LangGraph server or a
remote graph client (a graph is wrapped in process); a caller changing a graph's saved state,
forking it or going back in time; a `step` activity per graph node; a cost figure; the caller
side, a LangGraph agent that *calls* an R2C remote (not in this repo); publishing to PyPI.

- A wrapped graph keeps its conversation in a `messages` list and has its own checkpointer. The
  owner chooses the checkpointer; a durable one is what makes a pause survive a restart.
- The tests have no network and no keys: a scripted chat model stands in for a provider. The
  streaming of the real providers' models is the same typed stream the scripted model produces.
- The bounds of the extra come from a test of the oldest version that passes, as spec 005 did
  for its YAML reader; the plan decides them. The upper bound follows the same rule as the other
  extras.
- Python 3.11, 3.12 and 3.13, as the rest of the package.
- `Remote` (007) wires the agent, the approval policy and the doors. This spec builds none of it;
  the policy that answers an approval for a person (`approve=`) lives there, not here.
- How a door shows a reply that spans a pause is settled by 003 and 004; the plan reads them and
  checks that the bridge's `last` rule (FR-008) fits both.
- An exception's message from the graph reaches the caller as it is. What a provider puts in its
  error text is the owner's to watch; the plan decides whether to bound its length.
- Sub-graphs and sub-agents follow LangGraph's own defaults; nothing here changes them.
- Changes outside the bridge are small and listed: the suite (D3) and, if D2 is accepted, one
  additive piece of the core.

### Decisions taken in this draft

Each has a default, so the plan can start; the maintainer can overrule any of them at the gate.

- **D1. Only graphs with a `messages` state.** Default: the bridge wraps compiled graphs whose
  input has `messages` (`create_agent`, `MessagesState`). Another shape is refused at wrap time
  with a message that says so. *Why:* one wrapping line stays honest for the common case.
  *Alternative:* an `input` hook for other shapes. Rejected for now: it is more surface for a
  case nobody has asked for; it can be added without breaking anything.
- **D2. A lost pause ends `lost`, which needs one small core piece.** A checkpoint source that
  cannot find its stopping point can only raise, and the driver turns a raise into `failed`; only
  a live source gets `lost` (the driver gives it). Default: add to the core one exception that a
  checkpoint source raises in `resume`, which the driver turns into `Error("lost")`, an additive
  change like spec 003's `ReplyChunk.last`, done test first with the core-only check. *Why:* the
  doors tell a caller `lost` means "ask again"; `failed` does not. *Alternative:* no core change;
  the run ends `failed` with "lost" in the reason, and a caller cannot tell the two apart.
  **This changes spec 002's contract; the maintainer's call.**
- **D3. The suite changes in three places; every source still passes it.** Findings: the fakes
  have one reply chunk and fixed event orders (`FULL`), which a streaming graph cannot match, and
  the suite asks every source for `answers`, `fail_after_ask` and `double_ask`. Default:
  (a) the sequence checks become structural: consecutive reply chunks count as one reply and
  `activity` events may interleave, while the order of `ask`, `answer`, `usage` and the terminal
  event stays exact; (b) the graph under test asks with hand-written R2C payloads that carry the
  suite's own ids (`q-1`, `ap-1`), so no answer in the suite changes; (c) the real source is
  wrapped in a test-only object that records `answers`, and that yields a second `Ask` when
  `double_ask` is set, which tests the driver's guard (S9) as it did with the fakes. `fail_after_ask`
  builds a graph whose tool raises. The suite's contract file gets a dated note. *Why:* S9 cannot
  be produced by a correct bridge, which asks one at a time by construction; the wrapper is the
  suite's own way to make any source misbehave. *Alternative:* skip S9 for the bridge; rejected,
  a skipped scenario is a hole. A mutation check (an assertion removed, a reply dropped) must show
  the changed suite still fails a wrong source.
- **D4. Reply text is all of the model's text.** Default: every AI message's text streams, with a
  blank line between two messages. *Alternative:* only the last message. Rejected: it hides the
  agent's own words ("I will deploy now") and the doors cannot tell which message is last until
  it has ended.
- **D5. A tool is `running` only while it runs.** Default: no `running` while a call waits for
  approval; none ever for a denied call. The stream's task events start a call before the
  middleware pauses it in `per_call`, so the plan must read the stream to tell the two apart.
  *Fallback* the plan may take if it cannot: hold `running` until the call's result, so a tool
  shows `running` and `done` together; slow tools lose live progress, and this is recorded as a
  limit. *Alternative:* `running` at the model's request. Rejected: a tool would be `running`
  while a person is deciding, and a denied one would stay `running` forever.
- **D6. Any non-text block with data is a file.** Default: `file`, `image`, `audio` and `video`
  blocks with bytes or a URL become `file` artifacts. *Alternative:* only `file`. Rejected:
  models that return images would lose them.
- **D7. Usage reports tokens and the model, nothing else, once per turn.** Default: the counts the
  models reported, summed from the checkpoint so they survive a restart; no `duration_ms` (the
  bridge cannot measure it across a pause and a restart) and no `cost` (R2C-USAGE-3: unknown is
  absent). Sent at the end of the turn, not at each pause: it keeps the order the suite checks
  (`ask`, `answer`, `usage`, terminal), and a run that is never answered reports nothing.
  *Limit:* the answer to an `input_required` ask is a new human message, so its turn starts a new
  count, while the doors may treat both turns as one task. *Alternative:* also send usage at each
  pause. Rejected for now: it is more events for a number nobody reads during a pause.
- **D8. A batch in progress lives in memory.** Default: decisions already given are not kept past
  a restart, and the batch is asked again. *Why:* the middleware needs every decision in one
  resume, and the graph's state has no place to keep a partial set. *Alternatives:* store it in
  the graph's state (needs a field the owner would have to add; against III); ask the whole batch
  as one request (against R2C-APPROVAL-4). Documentation will say `per_call` when a restart in
  the middle matters.
- **D9. A new message settles a pending approval first.** Default: FR-007. *Alternative:* refuse
  the new message while a pause is pending. Rejected: a cancelled or abandoned task would lock a
  context for good. *Alternative:* send it as it is. Rejected: finding 6, real providers reject
  it.
- **D10. `input_required` is read from the final structured reply.** Default: FR-022, detected
  from the structured reply in the final state (the shape LangChain's `response_format` writes),
  checked in the plan against a real `create_agent` with a response format. *Alternative:* an
  owner-supplied predicate. Not now; it can be added later without breaking this.
- **D11. An in-memory checkpointer works and warns.** Default: a `UserWarning` at wrap time, once,
  that a pause will not survive a restart. *Alternative:* silence, docs only. Rejected: it is the
  default in every LangGraph tutorial and the failure shows up only in production.

## Notes after approval

The text above is the approved spec and is not rewritten. What changed since is dated here.

- **2026-11-22, FR-007 and D9 widened** (phase 10, an outside review; [research.md](research.md) R19,
  F1). As approved, only a pending middleware approval was settled before a new input. A tool that
  raised, a run cancelled in a tool, or a tool body whose `interrupt()` was abandoned left a tool call
  with no answer all the same, and a provider that checks the history refused every later message on
  that thread. The bridge now answers any tool call of the final AI message that no tool message
  answers, on an unfinished thread, with an error message ("withdrawn" for an approval, "did not
  finish" otherwise), before it sends the new input. Other pauses (a hand-written `interrupt()` in a
  plain node) and a graph that ended are still left as LangGraph leaves them. The reason of FR-007 is
  unchanged; its scope grew to the cases that reason covers.
- **2026-11-22, FR-024 (a LangChain tool as a `ToolSpec`) tightened** (R19, S1, S2). A tool served on its own
  refuses a key its schema does not declare, unless the schema says `additionalProperties` or
  `patternProperties`, and runs through `arun`. It is stricter than JSON Schema's default and the same
  as a function tool of the core.
- **2026-11-22, FR-019 and R2C-ANSWER-3** (R19, S4, S6). An answer for a `batched` call that already has
  a decision ends the run `lost` and the first decision stands; a declined hand-written approval gives
  the graph `{"decision": "deny"}`.
