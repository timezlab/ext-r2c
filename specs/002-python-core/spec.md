# Feature Specification: Python core (`ext_r2c.core`)

**Feature Branch**: `main` (no branch; the directory is `specs/002-python-core`)

**Created**: 2026-11-20

**Status**: Draft

**Input**: User description: "002-python-core — ext_r2c.core, the protocol-free core of the
Python SDK: models for the six kinds that round-trip every example object unchanged; form →
JSON Schema and form → flat MCP `requestedSchema`, plus mapping a flat MCP response back to an
answer value; answer validation against its request with size limits and no external `$ref`;
text fallback; the neutral run events; the extension points `AgentSource` (checkpoint and live
pause) and `ToolSpec`; a packaged schema loader; extras reshaped (`[langchain]` → `[langgraph]`,
no longer pulling `[a2a]`). Owns open points O2 and O3 of `specs/001-standard-v1/research.md`."

## Context

Spec 001 wrote the standard: `standard/v1/README.md` (84 tagged rules), six JSON Schemas and
57 example files. The Python package ships the schemas but does nothing with them. Every later
spec needs the same protocol-free pieces: the A2A door (003) and the MCP door (004) translate run
events to their wire; the LangGraph bridge (005) produces run events; `Remote` (006) composes.
This spec builds those shared pieces once, in `ext_r2c.core`, so that no door and no bridge
writes its own model, form generator or answer check.

Readers of this spec are the people who write the doors and bridges in this repository, and the
remote owners and third parties who implement `AgentSource` or `ToolSpec` themselves.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read and write R2C objects without losing anything (Priority: P1)

A door author receives an R2C object (from an A2A part, an MCP `_meta`, or a test file), turns
it into a typed object, works with it, and writes it back. What comes out is the same JSON that
went in: no field added, none dropped, none reordered in meaning. An object of a kind the core
does not know is passed over without error; an object that breaks its schema is rejected with a
message that names the failing place.

**Why this priority**: every other part of this spec, and every later spec, reads and writes
these objects. A model that drops an unknown field breaks R2C-CORE-6; one that adds defaults
changes the wire.

**Independent Test**: load every R2C object found in `standard/v1/examples/` (valid files),
parse it, write it back, and compare with the original; load every file in
`standard/v1/examples/invalid/` and check each is rejected.

**Acceptance Scenarios**:

1. **Given** the question in `a2a/question-fields.json`, **When** it is parsed and written back,
   **Then** the result equals the original JSON, and `other` and `required` stay absent where the
   original left them out (their defaults apply when read, not when written).
2. **Given** an `activity` with an extra field `tone: "calm"` and a `type` the core does not know,
   **When** it is parsed, **Then** no error is raised, the unknown field and type are kept, and
   writing it back gives the original.
3. **Given** the `provenance` object in `a2a/unknown-kind-ignored.json`, **When** the core is asked
   to parse it, **Then** it reports "unknown kind, ignored" and raises nothing (R2C-CORE-5).
4. **Given** `invalid/approval-answer-by-caller.json` (or any invalid file), **When** it is parsed,
   **Then** it is rejected and the error names the JSON pointer and the reason.
5. **Given** `invalid/approval-unknown-decision.json`, whose `decisions` holds a value v1 does
   not list, **When** it is parsed,
   **Then** it is rejected (R2C-VERSION-3).

---

### User Story 2 - Check an answer against the request it answers (Priority: P1)

A remote that receives an answer, and a client that is about to send one, both ask the core one
question: is this answer acceptable for this request, and if not, why? The core answers with a
list of problems, each with the field `key` and a message, in the shape of a re-ask's `errors`
(R2C-ASK-3), so the remote can re-ask without writing its own messages.

**Why this priority**: answer checking carries the safety rules (an approval is never answered
by a model, `edit` arguments must fit their schema, no `$ref` is followed). Getting it wrong in
each door separately is the risk this spec removes.

**Independent Test**: for every request/answer pair in the examples, the check passes, except
for an answer that the example later re-asks, which must fail (the pairing rule of spec 001);
plus a table of hand-built bad answers, each failing with the expected `key`.

**Acceptance Scenarios**:

1. **Given** the question of `a2a/reask-errors.json` and the answer `{threshold: "twenty"}`,
   **When** it is checked, **Then** it fails with one problem whose `key` is `threshold`.
2. **Given** an approval offering `allow | deny` and an answer with `decision: edit`, **When**
   checked, **Then** it fails: `edit` is not offered.
3. **Given** an approval offering `edit` with an `args_schema` that limits `quantity` to 1–1000,
   **When** the answer edits `quantity` to 5000, **Then** it fails with `key` `quantity`.
4. **Given** an approval answer with `answered_by.role = caller`, **When** checked, **Then** it
   fails (R2C-ANSWER-4, constitution V).
5. **Given** an approval with `expires_at` in the past at the time of the check, **When** an
   `allow` arrives, **Then** the check reports the request as expired (R2C-ASK-4).
6. **Given** an approval whose `args_schema` holds a `$ref` to another document, **When** the
   core is asked whether `edit` is offered, **Then** it says no, and no network or file access
   happens (R2C-SAFETY-7).
7. **Given** an answer whose `id` is not the request's `id`, **When** checked, **Then** it fails
   (R2C-ASK-5).
8. **Given** a `declined` answer to an approval, **When** the remote asks the core for the
   decision, **Then** the decision is `deny` (R2C-ANSWER-3).

---

### User Story 3 - Generate forms for both doors from one question (Priority: P1)

A remote's author writes a question's fields once. The core generates the JSON Schema that
checks its answer (R2C-QUESTION-5), the flat MCP `requestedSchema` (R2C-MCP-2), and, for an
approval, the MCP form with `decision`, `reason` and editable arguments (R2C-MCP-3). On the way
back, the core turns a flat MCP response into the R2C answer value.

**Why this priority**: the MCP door (004) and the answer check (story 2) cannot exist without
it, and the standard says the author never writes these schemas by hand.

**Independent Test**: for each MCP example, the generated `requestedSchema` equals the one in
the file; each flat response in the examples maps to the derived answer the example states.

**Acceptance Scenarios**:

1. **Given** the question in `mcp/elicitation-question.json`, **When** its flat form is
   generated, **Then** it equals the file's `requestedSchema`, including `title` (from
   `header`), `description` (from `text`) and the `required` list.
2. **Given** `mcp/elicitation-question-other.json` and the response
   `{warehouse_other: "East annex"}`, **When** mapped back, **Then** the value is
   `{warehouse: "East annex"}`.
3. **Given** `mcp/elicitation-approval.json` and the response with `decision: edit` and
   `quantity: 300`, **When** mapped back, **Then** the value is
   `{decision: edit, args: {item: A-113, quantity: 300, supplier: S-7}}`.
4. **Given** `mcp/elicitation-approval-edit-dropped.json`, **When** the approval form is
   generated, **Then** `edit` is not among the offered decisions and no argument property is
   added.
5. **Given** an approval whose only decision is `edit` and whose `args_schema` is not flat,
   **When** the MCP form is requested, **Then** the core reports that the approval cannot be
   asked over MCP, and offers no decision of its own.

---

### User Story 4 - Write an agent source of either pause style (Priority: P1)

A bridge author (or a remote owner without a bridge) implements `AgentSource` for an agent
framework. If the framework saves its stopping point and returns (LangGraph, ADK, OpenAI Agents
SDK), the source yields an ask and ends, and is resumed later with the answer. If the framework
waits in memory (Claude Agent SDK), the source awaits the answer inside the run. A door drives
both the same way: it starts a run, reads run events, and delivers an answer when one arrives;
it never knows which style it is driving.

**Why this priority**: the ADR `one-remote-two-doors.md` requires both styles to be tested from
the first spec that defines `AgentSource`, so that a live-pause framework later does not change
`core`.

**Independent Test**: one contract test suite runs against a fake checkpoint-style source and a
fake live-style source, and both pass it unchanged.

**Acceptance Scenarios**:

1. **Given** a checkpoint-style fake that asks one question, **When** a run starts, **Then**
   the events are activity, ask, and the run pauses; **When** the answer is delivered, **Then**
   the source is resumed with it and the events continue with answer, reply chunks, usage,
   done.
2. **Given** a live-style fake that asks the same question, **When** driven by the same test,
   **Then** the event sequence is identical.
3. **Given** a checkpoint-style source paused on an ask, **When** the process restarts and the
   answer is delivered to a new driver for the same thread, **Then** the run resumes.
4. **Given** a live-style source paused on an ask, **When** the answer reaches a driver that does
   not hold that run (as after a restart), **Then** the run ends with an error event whose reason
   says the paused run was lost.
5. **Given** a source that is denied an approval with a reason, **When** the answer is
   delivered, **Then** the source receives the deny and its reason.
6. **Given** a paused run, **When** it is cancelled, **Then** the source sees a declined answer
   (live) or is not resumed (checkpoint), and the run ends.

---

### User Story 5 - Offer a plain function as a tool (Priority: P2)

A remote owner passes a plain Python function (sync or async, with type hints and a docstring)
and gets a `ToolSpec`: a name, a description, a JSON Schema of its input, and an async call. A
framework's own tool type becomes a `ToolSpec` through its bridge (005), not here.

**Why this priority**: the MCP door (004) serves `ToolSpec`s, and approvals of tool calls
(`args_schema`) come from the tool's input schema; it is needed before 004 but not by 003.

**Independent Test**: turn three functions (sync, async, with an enum and a default) into
`ToolSpec`s and check their schemas, a call with valid arguments, and a call with bad ones.

**Acceptance Scenarios**:

1. **Given** `def reorder(item: str, quantity: int = 1) -> str` with a docstring, **When** made
   a `ToolSpec`, **Then** its name is `reorder`, its description is the docstring's first
   paragraph, and its input schema requires `item` and gives `quantity` a default.
2. **Given** a `ToolSpec`, **When** called with arguments that break its input schema, **Then**
   the call fails before the function runs, with the failing keys.
3. **Given** a `ToolSpec` whose input schema is flat, **When** an approval is built for a call of
   it, **Then** the approval's `args_schema` is that input schema and `edit` survives on MCP.

---

### User Story 6 - Install the core alone (Priority: P2)

A caller that only needs models and validation installs `ext-r2c` with no extra and imports
`ext_r2c` and `ext_r2c.core`. Nothing pulls in a protocol SDK or an agent framework.
`ext-r2c[langgraph]` installs LangChain and LangGraph without the A2A SDK.

**Why this priority**: constitution VIII; it is cheap but must hold from now on.

**Independent Test**: in a clean environment with only the wheel and its required
dependencies, import the package and the core; inspect the wheel's metadata for the extras.

**Acceptance Scenarios**:

1. **Given** a clean environment with the wheel installed and no extra, **When** `ext_r2c.core`
   is imported, **Then** it succeeds and no module of `a2a`, `mcp`, `langchain` or `langgraph`
   is loaded.
2. **Given** the wheel's metadata, **When** its extras are read, **Then** they are `a2a`, `mcp`
   and `langgraph`; `langgraph` does not require `a2a`; `langchain` is gone.

---

### Edge Cases

- A question field with `other: true` and `required: true`, answered over MCP with neither
  `<key>` nor `<key>_other`: the merged value is missing, so the check fails with that `key`
  (the flat form cannot mark either property required, see FR-013).
- `<key>_other` present but empty (`""`): it does not win; `<key>` is used.
- A `many` field answered over MCP with options and a `<key>_other` (Q1, decided 2026-11-20):
  a non-empty `<key>_other` is added as one more item after the chosen options
  (`["Stock", "Returns"]` + `"Suppliers"` → `["Stock", "Returns", "Suppliers"]`), not split on
  commas; if it equals a chosen label it is not added twice.
- A `required: true` field of type `text` answered with `""`, or of type `many` with `[]` (Q2,
  decided 2026-11-20): `required` means present **and** not empty, so the answer schema gives
  such a field `minLength: 1` or `minItems: 1` and the answer fails with that `key`. The flat
  MCP form does not change; the check after the merge catches the empty value.
- An argument of a flat `args_schema` named `decision` or `reason`: it would collide with the
  approval form's own properties, so the schema counts as not flat and `edit` is dropped on MCP.
- An MCP `edit` response that leaves out an argument: the argument keeps its current value;
  the rebuilt `args` are then checked against `args_schema`.
- An MCP response with `decision: allow` that also carries argument values: the values are
  ignored; only `edit` carries `args`.
- An `args_schema` with a `$ref` inside the document (`#/$defs/...`): allowed and resolved; a
  `$ref` to anything else makes `edit` not offered and is never fetched.
- An answer or inline content larger than the size limit: rejected with a "too large" problem
  before any schema check runs. The unit is MiB, 2^20 bytes (Q3, O11, decided 2026-11-20;
  R2C-SAFETY-4 and the constitution now say MiB).
- Two fields with the same `key`, or two options with the same `label` (R2C-QUESTION-4): the
  core rejects the question when it is built or parsed, since a schema cannot check it.
- An `answer` to a question with `answered_by.role = policy`: reported, not decided here (O8
  belongs to 003); the check accepts it unless 003 says otherwise.
- A source whose run raises an exception: the run ends with one error event; no done event
  follows.
- A source that yields an ask while another ask of the same run is still unanswered: rejected,
  one pending request per run (R2C-APPROVAL-4 asks one at a time).

## Requirements *(mandatory)*

### Functional Requirements

**Models (story 1)**

- **FR-001**: The core MUST offer a typed model for each of the six kinds (`question`,
  `approval`, `answer`, artifact metadata, `activity`, `usage`) and for the parts they share
  (field, option, subject, origin, error item, answered-by).
- **FR-002**: Parsing then writing any R2C object that satisfies its schema MUST give back the
  same JSON value: unknown fields kept, absent fields left absent, no default written out.
- **FR-003**: Parsing MUST reject what the kind's schema rejects, with errors that name the JSON
  pointer and the reason. The packaged schema is the judge: where the model and the schema
  could disagree, the schema wins (constitution I).
- **FR-004**: The core MUST also reject what a schema cannot check but the standard requires of
  a single object: duplicate field keys and duplicate option labels (R2C-QUESTION-4).
- **FR-005**: Parsing an object of an unknown `kind` MUST return an "unknown kind" result
  instead of raising (R2C-CORE-5). An `activity` with an unknown `type` MUST parse (R2C-CORE-6).
  A value outside a closed enum MUST be rejected (R2C-VERSION-3).
- **FR-006**: The core MUST load the six schemas from the files packaged in the wheel
  (`ext_r2c/schema/v1/`) and expose them by kind, with no network or file access outside the
  package.

**Forms (story 3)**

- **FR-007**: The core MUST generate a question's answer schema as the R2C-QUESTION-5 table
  says, with one change written into that table (Q2): a `text` field with `required: true` gets
  `minLength: 1`, and a `many` field with `required: true` gets `minItems: 1`.
- **FR-008**: The core MUST generate a question's flat `requestedSchema` exactly as R2C-MCP-2
  says, with each property's `title` from `header` and `description` from `text`, and for
  `<key>_other` the title `"<header> (other)"` and the description
  `"Another <header in lower case>, if not listed."`, as in `mcp/elicitation-question-other.json`.
- **FR-009**: The core MUST generate an approval's flat `requestedSchema` as R2C-MCP-3 says:
  `decision` (`oneOf` the offered decisions, titled `Allow`, `Edit`, `Deny`) and `reason`, both
  titled; `decision` required; when `edit` survives, one property per argument with its
  constraints, its enum as titled `oneOf`, its title the argument name, and its current value as
  `default`.
- **FR-010**: `edit` MUST survive on MCP only when the `args_schema` is flat (every property a
  string, number, integer, boolean or enum), has no external `$ref`, and has no argument named
  `decision` or `reason`. Otherwise it is dropped from the offered decisions.
- **FR-011**: When dropping `edit` leaves no decision, the core MUST report that the approval
  cannot be asked over MCP, and MUST NOT offer `allow` or `deny` in its place.
- **FR-012**: The core MUST map a flat MCP response back to an R2C answer value:
  - a question: `<key>` and `<key>_other` merged; for `one`, a non-empty `<key>_other`
    replaces `<key>`; for `many`, it is added as one more item, once (Q1);
  - an approval: `decision`, `reason` if given, and for `edit` the `args` rebuilt from the
    response, each argument left out keeping its current value;
  - `accept` gives `answered`, `decline` and `cancel` give `declined`, with
    `answered_by.role = person` (R2C-MCP-4).
- **FR-013**: A field with `other: true` MUST NOT be listed in the flat form's `required`, since
  the value may come in either property; the merged value is checked against the answer schema
  instead (FR-007), so a required field left empty fails there.

**Answer checking (story 2)**

- **FR-014**: The core MUST check an answer against the request it answers and return a list of
  problems, each with an optional `key` and a `message`, usable as a re-ask's `errors`
  (R2C-ASK-3). An empty list means acceptable.
- **FR-015**: The check MUST cover: the `id` matches; `value` present only when `answered`; a
  question's value fits its generated answer schema; an approval's value fits
  `answer.json#/$defs/approval_value`, its `decision` is offered, and with `edit` its `args` fit
  `args_schema`; an approval is never answered with `answered_by.role = caller`; a request past
  its `expires_at` at the time of the check is expired.
- **FR-016**: The check MUST NOT follow any `$ref` that leaves the schema document, and MUST
  treat an approval whose `args_schema` has one as not offering `edit` (R2C-SAFETY-7).
- **FR-017**: The core MUST enforce size limits before schema checks: an answer, and inline
  content (`raw` after decoding, `inline` text), above the limit is refused as too large. The
  defaults are the standard's (5 MiB in a message, 50 MiB for a file by `url`); a
  caller of the core MAY set its own thresholds (R2C-SAFETY-5).
- **FR-018**: The core MUST give the effective decision of an approval answer: the `decision`
  when answered, `deny` when declined or expired (R2C-ANSWER-3, R2C-ASK-4).

**Text fallback**

- **FR-019**: The core MUST generate a plain text for a `question` or `approval` from its
  `title`, `description`, and each field's `text` and options (with the offered decisions for
  an approval), and for an `activity` its `label` (R2C-CORE-4). The text is never empty. A
  remote MAY supply its own text instead; the examples' texts are hand-written and are not the
  generator's expected output.

**Run events and `AgentSource` (story 4)**

- **FR-020**: The core MUST define neutral run events, free of any A2A or MCP term: reply chunk,
  activity, ask, answer, artifact, usage, done, error. A run's events end with exactly one done
  or one error.
- **FR-021**: The core MUST define `AgentSource`: card information (name, description, version,
  card skills) and a run that takes an input message and a run context and yields run events.
- **FR-022**: `AgentSource` MUST support a checkpoint pause (the run yields an ask and ends; the
  source is resumed later for the same thread with the answer) and a live pause (the run awaits
  the answer through its context and goes on).
- **FR-023**: The core MUST offer one driver that runs a source of either style the same way: a
  door starts a run, reads events, delivers an answer, cancels; the events it sees do not depend
  on the style.
- **FR-024**: A run MUST have at most one unanswered ask at a time. Delivering an answer to a
  live run the driver does not hold MUST end that run with an error event saying the paused run
  was lost (the live-pause limit of the ADR).
- **FR-025**: The core MUST compute a thread id from door, owner and context id, so two owners
  using the same context id, or the same context over two doors, never share a thread
  (R2C-ID-1, ADR decision 6).
- **FR-026**: The repository MUST hold one `AgentSource` contract test suite, and a fake
  checkpoint-style source and a fake live-style source MUST both pass it unchanged.

**`ToolSpec` (story 5)**

- **FR-027**: The core MUST define `ToolSpec`: name, description, input schema, and an async
  call.
- **FR-028**: The core MUST make a `ToolSpec` from a plain function (sync or async) with type
  hints, its name from the function, its description from the docstring, and its input schema
  from the parameters; a call MUST check the arguments against the input schema first.

**Packaging (story 6)**

- **FR-029**: `import ext_r2c` and `import ext_r2c.core` MUST work with no extra installed, and
  the core MUST import nothing beyond the standard library, `pydantic` and `jsonschema`. A test
  MUST enforce this.
- **FR-030**: The extras MUST become `[a2a]`, `[mcp]` and `[langgraph]` (`langchain>=1.3`,
  `langgraph`), with `[langgraph]` not pulling `[a2a]`; `[langchain]` is removed.

**The standard follows the decisions (constitution I)**

- **FR-031**: The decisions this spec takes on O2 and O3 (FR-007 to FR-013, the edge cases
  above, Q1 and Q2) MUST be written into `standard/v1/README.md` §5 (the QUESTION-5 table) and
  §12 (MCP-2, MCP-3) in the same change as the code, with an example where they show on the
  wire: at least one MCP example of a `many` field answered with options and `<key>_other`, and
  one invalid-answer case of an empty required `text`.
- **FR-032**: The spec 001 tests that generate a form schema of their own MUST use the core's
  generator instead, so there is one generator.

### Key Entities

- **R2C object**: one of the six kinds; open (unknown fields kept), closed enums.
- **Request**: a `question` or an `approval`; has an `id`, maybe `expires_at`, maybe `errors`.
- **Answer value**: per field key for a question; `{decision, args?, reason?}` for an approval.
- **Problem**: one reason an answer is not acceptable: optional `key`, `message`.
- **Form schema**: the JSON Schema checking a question's answer (R2C-QUESTION-5).
- **Flat form**: an MCP `requestedSchema` generated from a question or an approval.
- **Run event**: one of reply chunk, activity, ask, answer, artifact, usage, done, error.
- **Agent source**: a framework adapter producing run events; checkpoint or live pause.
- **Run context**: what a running source gets: thread id, a way to ask (live), a cancel signal.
- **Driver**: runs one source for a door, hides the pause style.
- **Tool spec**: a tool's name, description, input schema and async call.
- **Thread id**: derived from door, owner and context id.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the R2C objects in the valid example files (every kind, both bindings)
  round-trip through the models to an equal JSON value; the test run prints the count.
- **SC-002**: 100% of the 20 invalid objects are rejected by the models, each with an error
  naming a JSON pointer.
- **SC-003**: For 100% of the MCP examples, the generated `requestedSchema` equals the file's,
  and every flat response maps to the answer the example's description states.
- **SC-004**: Every request/answer pair in the examples passes the answer check, except each
  answer that the example later re-asks, which fails; and a table of at least one bad answer per
  rule in FR-015 fails with the expected `key`.
- **SC-005**: The fake checkpoint-style and the fake live-style source pass the same contract
  suite with no test skipped or specialised for either.
- **SC-006**: In a clean environment holding only the wheel, `pydantic` and `jsonschema`,
  `import ext_r2c.core` succeeds, and the import-rule test passes.
- **SC-007**: The full suite passes on the installed wheel on Python 3.11, 3.12 and 3.13, and
  every `wire` rule of the README still has an example.
- **SC-008**: A reviewer who has not seen the code can write a working fake `AgentSource` of
  each style from the core's docstrings and the ADR alone (checked once, like SC-005 of 001).

## Assumptions

- **Users**: door and bridge authors in this repository first; remote owners and third parties
  implementing `AgentSource` or `ToolSpec` second. End users of R2C never see the core.
- **Dependencies** are those of constitution VIII and the Technical Constraints: the core uses
  `pydantic` and `jsonschema` only.
- **O1 is decided** (2026-11-20, `R2C-VERSION-3`): closed enums stay closed, so the models may
  reject an unknown enum value.
- **Decided by the maintainer** (2026-11-20): Q1 A (`many` + `<key>_other` adds one item),
  Q2 A (required means not empty), Q3 A (MiB; O11 closed).
- **O2 and O3 defaults** taken here, unless the maintainer says otherwise: a field with
  `other: true` is never in the flat `required` list (as `mcp/elicitation-question-other.json`
  already shows); an argument named `decision` or `reason` makes `args_schema` not flat; an
  argument left out of an MCP edit keeps its current value; `decisions: ["edit"]` with a
  non-flat schema cannot be asked over MCP.
- **Not decided here** (owned elsewhere, see `specs/001-standard-v1/research.md`): the
  elicitation `message`, several `inputRequests`, `requestState`, re-ask and refusal on MCP
  (O4, O5, O6, O7: 004); what a remote does with an approval answer claiming `caller` or a
  `policy` answer to a question, refusing a second task, label changes (O8, O9, O10: 003).
- **Storage**: the core keeps no durable state. A checkpoint-style source's stopping point lives
  in its framework's store (for LangGraph, its checkpointer); the driver keeps live runs in
  memory only.
- **The contract suite** lives in the repository's tests, not in the wheel, until a bridge
  outside this repository needs it.
- **Out of scope**: any wire translation (003, 004), MCP Skills (004), the LangGraph bridge
  (005), `Remote` (006), a caller's presentation of requests, remembered-consent storage.
