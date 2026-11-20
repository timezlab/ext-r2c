# Feature Specification: R2C standard, version 1

**Feature Branch**: none (work lands on `main`; this folder is `specs/001-standard-v1`)

**Created**: 2026-11-20

**Status**: Draft

## Clarifications

### Session 2026-11-20

- Q: Should the example check also validate each example's protocol envelope against the real
  A2A and MCP SDK types, or only the R2C objects inside it? → A: Both (option B). The envelope is
  parsed with a2a-sdk and the MCP Python SDK as test-only dependencies (FR-021a, SC-001a).

**Input**: User description: "001-standard-v1: Write the normative R2C v1 standard in
standard/v1/README.md; JSON Schemas (draft 2020-12) in standard/v1/schema/ for the six kinds
question, approval, answer, artifact (artifact-meta), activity, usage; wire examples in
standard/v1/examples/a2a/ and standard/v1/examples/mcp/ covering every rule that can be shown on
the wire, including a full streamed run (reply chunks in the streamed response artifact, tool and
step activities, a file artifact, usage); a CI step validating every example against its schema;
the schemas shipped byte-identical inside the Python wheel. Done when every example validates,
the wheel carries byte-identical schemas, and a test fails if one example breaks its schema.
Source of truth: docs/research/2026-11-20-r2c-v1-design-brief.md (with amendments 1 and 2),
docs/design-docs/*.md, docs/whitepaper.md. No SDK models, bindings or Remote in this feature
(those are specs 002–006)."

## Context

R2C v1 is designed and approved (design brief of 2026-11-20 with two amendments, seven ADRs,
the white paper), but nothing an outside implementer can rely on exists yet: the standard's
folder holds only a placeholder. Until the normative text, the schemas and the wire examples
exist, no SDK (ours or anyone else's) has a contract to be tested against, and specs 002–006
have nothing to round-trip.

This feature turns the approved design into the **standard itself**: what a remote and a client
MUST, SHOULD and MAY do, the exact shape of each of the six kinds, and one example on the wire
for every rule that can be shown there. Once it is written, the standard wins over the brief and
the white paper wherever they differ.

**Readers of the result:**

- **A remote implementer** (any language) who wants their A2A agent or MCP server to ask, request
  approval, report activity and usage, and hand back artifacts the R2C way.
- **A client / caller implementer** who wants to render and answer those requests safely.
- **An SDK author** (this repo's Python SDK in specs 002–006, later TypeScript, or a third party)
  who needs a fixed, machine-checkable contract.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Implement R2C from the standard alone (Priority: P1)

A remote implementer who has never seen this repo's design notes reads `standard/v1/README.md`
and the schema of each kind, builds the R2C objects their remote sends, and checks them against
the published schemas with any JSON Schema 2020-12 validator, in any language. A client
implementer does the same for the objects they receive and the `answer` they send back.

**Why this priority**: The standard is the product of this repository. Without normative text and
schemas, R2C is a design note, not something a second party can adopt (constitution IX: v1 leaves
draft only when an outside remote adopts it).

**Independent Test**: Give the README and `schema/` to a reviewer who did not take part in the
design; they can answer, for each of the six kinds, which fields are required, where the object
sits on A2A and on MCP, and what the receiver must do with an unknown kind or field, without
opening any other document. Validate a hand-written object of each kind against its schema with
a stock validator.

**Acceptance Scenarios**:

1. **Given** the six schema files, **When** an implementer validates a well-formed `question`,
   `approval`, `answer`, `artifact` metadata object, `activity` and `usage` taken from the
   README, **Then** each validates with a stock JSON Schema 2020-12 validator, with no network
   access and no file other than its own schema.
2. **Given** an `approval` with `answer_by.role = "caller"`, **When** it is validated, **Then**
   it fails: the schema itself enforces that an approval is never addressed to a model.
3. **Given** a known object carrying a field the schema does not define (a later addition),
   **When** it is validated, **Then** it still validates (the schemas follow "ignore unknown").
4. **Given** the README, **When** an implementer looks up any rule (for example "one pending
   request per task" or "a later `usage` replaces an earlier one"), **Then** the rule has a
   stable identifier, a MUST / SHOULD / MAY level, and says who it binds (remote or client).

---

### User Story 2 - Use the wire examples as the shared test suite (Priority: P1)

An SDK author points their round-trip tests at `standard/v1/examples/` and replays every file:
complete A2A and MCP messages showing each rule on the wire, including one full streamed run. The
maintainer can see that every wire-showable rule has an example and that every example is read
by a test.

**Why this priority**: Constitution II makes the examples the test suite every SDK shares; specs
003 and 004 are "done" only when they replay them. Examples written now fix the exact wire before
any binding code exists.

**Independent Test**: Run the repository's example check: every example validates; every rule
marked wire-showable in the README is cited by at least one example; deliberately broken copies
of examples fail.

**Acceptance Scenarios**:

1. **Given** the examples folder, **When** the example check runs, **Then** every R2C object
   inside every example (found by the placement rule: a part's `data` marked by `metadata[uri]`,
   an A2A object's `metadata[uri]`, or MCP `_meta["io.github.timezlab/r2c"]`) validates against
   its kind's schema.
2. **Given** the full streamed run example, **When** a reader follows it in order, **Then** it
   shows: the client activating R2C, a `step` activity, a `tool` activity running then done with
   a duration, reply text streamed as one `response: true` inline artifact (first chunk
   `append: false`, then `append: true`, then `last_chunk: true`) interleaved with activities, a
   `file` artifact, an `approval` at `input-required` and its `answer`, and a terminal
   `completed` status carrying `usage`.
3. **Given** an example that breaks its schema (for example a `question` without `title`),
   **When** the check runs, **Then** it fails and names the file and the failing object.
4. **Given** a rule in the README marked wire-showable, **When** no example cites it, **Then**
   the check fails; **Given** an example file no check reads, **Then** the check fails.

---

### User Story 3 - Get the schemas with the Python package (Priority: P2)

A Python user who installs `ext-r2c` (no extras) finds the six v1 schemas inside the installed
package, byte-for-byte the same as `standard/v1/schema/`, so tools and later SDK code can load
them without a checkout of this repository.

**Why this priority**: Specs 002–004 validate against these schemas at runtime; shipping them in
the wheel now proves the packaging path. It is P2 because the standard is usable without it.

**Independent Test**: Build the wheel, install it into a clean environment with no extras, list
the schema files inside the installed package and compare each one, byte for byte, with the file
in `standard/v1/schema/`.

**Acceptance Scenarios**:

1. **Given** a freshly built wheel installed in a clean environment, **When** the packaged
   schemas are compared with `standard/v1/schema/`, **Then** the same six files are present and
   identical byte for byte.
2. **Given** a schema edited in `standard/v1/schema/` but a stale wheel, **When** the comparison
   runs on a rebuilt wheel, **Then** it still passes (the wheel takes the schemas from
   `standard/`, never from a hand-kept copy).
3. **Given** the installed package with no extras, **When** it is imported, **Then** the import
   still works exactly as before this feature (no new runtime dependency).

---

### User Story 4 - Know when the standard and the design disagree (Priority: P3)

The maintainer and a future contributor can tell that the standard is now the source of truth:
the brief, the white paper and the docs index point to it, and any place where writing the
standard changed a design detail is recorded.

**Why this priority**: Stale design docs that contradict the standard would mislead the next
spec. It is P3 because it is bookkeeping around the main deliverable.

**Independent Test**: Read `AGENTS.md`, `WORKSTATE.md`, the brief's status line and the white
paper's wire sections: each points to `standard/v1/` for exact shapes, and a list of deviations
from the brief (possibly empty) exists in this feature's folder.

**Acceptance Scenarios**:

1. **Given** the standard is written, **When** a reader opens the brief or the white paper,
   **Then** a dated note says the normative text now lives in `standard/v1/README.md` and wins
   where they differ.
2. **Given** a field name or rule that changed while writing the schemas, **When** a reader looks
   at this feature's folder, **Then** the change and its reason are listed.

---

### Edge Cases

- **Unknown kind** (`"kind": "provenance"`) inside a marked part: receivers ignore it; the
  example check does not try to validate it and does not fail on it.
- **Unknown `activity.type`** (a later value): receivers ignore the activity; the `activity`
  schema does not reject an unknown `type`, while it still rejects a known type with a wrong
  shape.
- **An approval's `subject.type` is unknown**: the approval cannot be matched by a policy; the
  standard says the client treats it as needing a person and never auto-allows it.
- **`one` field with `other: true` on MCP**: the flat form gains a `<key>_other` string; an
  example shows both the request and the answer mapped back to one value.
- **`edit` with a nested `args_schema` on MCP**: `edit` is dropped from the offered decisions;
  an example shows the flat form without it.
- **Expired request, or an answer with a wrong `id`**: the remote refuses in text and the request
  stays pending (or expires); an example shows the refusal message.
- **Client did not activate R2C**: the same run shows text and standard artifacts only, never an
  R2C part and never reasoning; an example shows this.
- **Reasoning deltas**: several deltas append to one `reasoning` activity by `id`; deltas are
  coalesced (the example does not send one token per event).
- **`usage` with only some fields**: a missing field means unknown, never zero; a `usage` with no
  measured field at all fails its schema.
- **Oversized content** (inline content over 5 MB): not expressible in a schema; the README states
  the limit and the client's behaviour; no example carries 5 MB.
- **A `url` artifact on another host**: shown as a link, never fetched with the user's token;
  covered by the README's client safety rules (wire-showable only as the artifact itself).
- **Several approvals at once**: one `approval` at a time, in tool-call order; the next only after
  the previous has its `answer`; an example sequence shows two in a row.

## Requirements *(mandatory)*

### Functional Requirements

**Normative text (`standard/v1/README.md`)**

- **FR-001**: The README MUST state the conformance language (RFC 2119 / RFC 8174 keywords), the
  roles (`remote`, `caller`/client, `person`, `approver`, `policy`), the identifiers (A2A URI
  `https://github.com/timezlab/ext-r2c/tree/main/standard/v1`, MCP key `io.github.timezlab/r2c`),
  and that v1 is *draft* until the first outside remote adopts it.
- **FR-002**: Every normative rule MUST carry a stable identifier (for example `R2C-APPROVAL-3`),
  a level (MUST / SHOULD / MAY), the party it binds (remote, client, or both), and a mark saying
  whether it can be shown on the wire.
- **FR-003**: The README MUST specify declaration and activation for both bindings: the A2A agent
  card entry with `required: false` and per-request activation through `A2A-Extensions`; MCP
  declaration through `server/discover` and the client's declared extensions; and that without
  activation a remote sends text and standard artifacts only.
- **FR-004**: The README MUST specify the placement rule (an R2C object as a part's `data` marked
  by `metadata[uri] = {}`; an R2C annotation in a standard object's `metadata[uri]`; on MCP, the
  object in `_meta["io.github.timezlab/r2c"]`) and the text fallback every request carries.
- **FR-005**: The README MUST require both parties to ignore, without error, an unknown kind, an
  unknown field in a known kind, and an unknown `activity.type`.
- **FR-006**: The README MUST specify all six kinds with their fields, defaults and rules, as
  decided in the brief and its amendments:
  - `question` and `approval` common fields (`id`, `title`, `description`, `answer_by`,
    `expires_at`, `origin`, `errors`) and rules: at most one pending request per task; `id`
    never reused within a task; expiry checked by the remote (a question counts as declined, an
    approval as deny); re-ask with the same `id` and `errors` on a bad answer; refusal in text for
    a wrong `id` or after expiry; when a text answer from a client that did not activate R2C is
    accepted.
  - `question`: fields of type `one`, `many`, `text`, `number`, `bool`; options, `other` and
    `required` with their defaults; `answer_by` `person` or `caller`.
  - `approval`: `subject` (`tool_call` with `name`, `args`, optional `args_schema`; or
    `operation` with `name`, optional `target`), `decisions` from `allow`, `edit`, `deny`;
    `edit` requires `args_schema`; one subject per approval; several approvals queued one at a
    time in tool-call order, each decided on its own.
  - `answer`: `id`, `outcome` (`answered` / `declined`), `answered_by`, `value`, `note`; the
    value of a question (one value per field key) and of an approval (`decision`, `args` required
    for `edit`, optional `reason`).
  - `artifact` metadata: `presentation` (`file` / `inline` / `live`), `state` (`open` / `closed`,
    live only), `response: true` (at most one per task, `inline` only); `filename` and
    `mediaType` required for `file`; the reply streamed in chunks; versions by `artifactId`; how
    a client guesses `presentation` when the metadata is missing; a `url` SHOULD stay valid at
    least 24 hours after the task ends.
  - `activity`: `id`, `type` (`tool` / `step` / `reasoning`), `state`, `label`, `name`, `args`,
    `detail`, `duration_ms`, `parent_id`, `delta`, with the definition of each type; reasoning
    only when the remote's owner turns it on, never with provider signatures or encrypted
    reasoning; tool args opt-in per tool; deltas coalesced.
  - `usage`: `input_tokens`, `output_tokens`, `duration_ms`, `cost {amount, currency}` (ISO 4217),
    `model`; cumulative for the task (a later one replaces an earlier one); a missing field means
    unknown; never used for billing by the client.
- **FR-007**: The README MUST specify the A2A binding of each kind (status message parts for
  `question`, `approval`, `activity`, `usage`; reply message parts for `answer`; standard
  `Artifact` with `metadata[uri]` and `append` / `last_chunk` for `artifact`; `usage` at the
  latest in the terminal status, optionally at `input-required`) and resume through a new message
  with the same `taskId` and `contextId`, follow-up through the same `contextId` without
  `taskId`, and reattaching with `SubscribeToTask`.
- **FR-008**: The README MUST specify the MCP binding of each kind: `question` and `approval` as
  elicitation within a multi-round-trip tool call, with the flat `requestedSchema` generated from
  the form (including `<key>_other` for `one` + `other`, and `edit` dropped when `args_schema` is
  not flat); `accept` → `answered`, `decline` / `cancel` → `declined`, `answered_by` always
  `person`; artifacts as tool result content with `_meta`; `activity` through
  `notifications/progress` only when the client sent a `progressToken`; `usage` in the tool
  result's `_meta`; `requestState` opaque to the client, sealed and expiring.
- **FR-009**: The README MUST specify the form → JSON Schema mapping a remote uses to check a
  question's answer, for every field type, so two implementations generate equivalent schemas.
- **FR-010**: The README MUST state the trust and safety rules: an approval is never addressed to
  or answered by a model (a MUST on the client, which alone can enforce `answered_by`);
  remembered consent is a client-held policy (`answered_by: policy`), never for
  `answer_by: approver`; the user's token goes only to the connection's own origin; sandboxed
  `inline` HTML/SVG; `live` framing rules; size limits (content inside a message ≤ 5 MB, files
  fetched by `url` ≤ 50 MB; SHOULD for the remote, the client enforces its own); `activity` and
  `usage` are display data, escaped and never treated as instructions; no external `$ref` in an
  `args_schema` a client receives.
- **FR-011**: The README MUST state the identifier rules a remote SHOULD follow: the remote's
  internal thread keyed by owner and context (never the bare context id), one unfinished task per
  context, and that the caller durably stores `contextId` and `taskId`.
- **FR-012**: The README MUST state versioning: a breaking change opens `standard/v2/` with a new
  URI (A2A) and a `revision` bump (MCP); after leaving draft, v1 takes additive changes only.
- **FR-013**: The README MAY carry a short, clearly marked non-normative section of guidance for
  callers (how to present `answer_by` roles), taken from the brief's §8.

**Schemas (`standard/v1/schema/`)**

- **FR-014**: There MUST be exactly six schema files, one per kind: `question.json`,
  `approval.json`, `answer.json`, `artifact-meta.json`, `activity.json`, `usage.json`, each a
  JSON Schema draft 2020-12 document with a stable `$id` under the standard's URI.
- **FR-015**: Each schema MUST be self-contained: no `$ref` to another file or to the network, so
  a client can load one file on its own.
- **FR-016**: Schemas MUST NOT reject unknown fields (no closed objects), MUST NOT reject an unknown
  `activity.type`, and MUST reject a known shape that breaks a rule a schema can express (missing
  required field, wrong enum value of a closed field, `approval` addressed to `caller`, `edit`
  offered without `args_schema`, `usage` with no measured field, `currency` not three capital
  letters).
- **FR-017**: Rules a schema cannot express (expiry, one pending request per task, size limits,
  "no model answers an approval" beyond `answer_by`) MUST be stated in the README and marked as
  not schema-checked.

**Wire examples (`standard/v1/examples/`)**

- **FR-018**: Examples MUST be complete protocol messages (A2A 1.0 JSON under `examples/a2a/`, MCP
  2026-07-28 JSON-RPC under `examples/mcp/`), using only invented data and `example.com` hosts.
- **FR-019**: Every rule marked wire-showable MUST be cited by at least one example, and every
  example MUST cite the rule identifiers it shows. The set MUST include at least: agent card
  declaration; MCP declaration; a question of each field type; `one` with `other` on both
  bindings; a forwarded request with `origin`; a re-ask with `errors`; a refusal for a wrong `id`
  or expiry; an approval with `tool_call` and `edit`, and one with `operation`; two queued
  approvals; answers for allow, edit, deny with reason, declined, and `answered_by: policy`;
  artifacts `file` (by `url` and by `raw`), `inline`, `live` open then closed, and one without
  R2C metadata; activities of each type, including nesting by `parent_id` and a `failed` tool;
  `usage` at `input-required` and at the end; a client that did not activate R2C; an unknown
  kind that is ignored; and one full streamed run as in User Story 2, scenario 2.
- **FR-020**: There MUST be a set of invalid examples, each expected to fail its schema for one
  stated reason, covering at least the cases in FR-016.
- **FR-021**: Examples MUST be read by an automated check that validates every R2C object in every
  valid example, expects every invalid example to fail, and fails when a wire-showable rule has
  no example or an example is read by no check.
- **FR-021a**: The check MUST also parse every example's protocol envelope with the real protocol
  SDK types (A2A messages, events and agent card through a2a-sdk; MCP JSON-RPC requests, results
  and notifications through the MCP Python SDK) and fail on any envelope those types reject.
  These SDKs are **test-only** dependencies: they never become runtime dependencies of the
  package (FR-025). (Clarified 2026-11-20, option B: wire examples are the contract for every
  SDK, so a wrong envelope must be caught here, not in specs 003 / 004.)

**Packaging and CI**

- **FR-022**: The Python wheel MUST carry the six schemas inside the `ext_r2c` package, taken from
  `standard/v1/schema/` at build time and identical byte for byte; no hand-kept copy exists in
  the source tree.
- **FR-023**: A test run against the installed wheel MUST compare the packaged schemas with
  `standard/v1/schema/` byte for byte and fail on any difference or missing file.
- **FR-024**: CI MUST run the example check and the packaged-schema comparison on every push and
  pull request, on the Python versions CI already covers, and fail the build on any failure.
- **FR-025**: The package MUST keep its current dependencies and its current import surface; no
  models, bindings, bridges or `Remote` are added (specs 002–006).

**Docs**

- **FR-026**: `standard/v1/README.md` replaces its placeholder; the brief and the white paper get a
  dated note that the standard now wins; `AGENTS.md`, `WORKSTATE.md` and `CHANGELOG.md` reflect
  the new state; deviations from the brief found while writing are listed in this feature's
  folder.
- **FR-027**: Every file added by this feature MUST pass the repository's private-token scan
  (constitution VI).

### Key Entities

- **Kind**: one of the six R2C object types (`question`, `approval`, `answer`, `artifact`
  metadata, `activity`, `usage`), identified by its `kind` field; has one schema.
- **Rule**: one normative statement in the README, with an identifier, a level, the party bound,
  and whether it is wire-showable and whether a schema checks it.
- **Binding**: how the kinds travel on A2A or on MCP (placement, mapping, activation).
- **Wire example**: one complete A2A or MCP message (or an ordered sequence of them), with the
  rule identifiers it shows; valid or deliberately invalid.
- **Packaged schema**: the copy of a schema file inside the built wheel, identical to its source.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the R2C objects in the valid wire examples validate against their kind's
  schema, and 100% of the invalid examples fail for their stated reason.
- **SC-001a**: 100% of the example envelopes are accepted by the real A2A and MCP SDK types.
- **SC-002**: 100% of the rules marked wire-showable are cited by at least one example, and 0
  example files are left unread by the check.
- **SC-003**: Breaking any one valid example (removing a required field) makes the check fail,
  shown by at least one invalid example per schema (six or more).
- **SC-004**: The installed wheel carries all six schemas, 0 bytes different from
  `standard/v1/schema/`, on every Python version CI covers.
- **SC-005**: A reviewer who did not take part in the design can, from the README and schemas
  alone, state for each of the six kinds its required fields and its placement on A2A and MCP
  with no error (checked once, before the maintainer approves the feature).
- **SC-006**: The full streamed run example shows all of: R2C activation, a `step` activity, a
  `tool` activity with a duration, at least three reply chunks of the `response` artifact
  interleaved with activities, a `file` artifact, an approval answered, and a final `usage`.
- **SC-007**: 0 private-token hits in the added lines of every commit of this feature.

## Assumptions

- The approved brief (with amendments 1 and 2) and the ADRs are the design; this feature writes it
  down normatively and fixes exact field spellings. A detail that turns out wrong while writing
  is changed in the standard and listed as a deviation, not silently.
- A2A wire spellings follow A2A 1.0 as implemented by a2a-sdk 1.3 (the forms used in the brief and
  the white paper, for example `TASK_STATE_INPUT_REQUIRED`, `statusUpdate`, parts with
  `text` / `data` / `url` / `raw`). MCP wire spellings follow protocol revision 2026-07-28 as
  implemented by the MCP Python SDK 2.3.
- R2C objects use `snake_case` field names (as designed), inside protocols that use `camelCase`.
- Sequences of messages (the full streamed run, queued approvals) are one example each, as an
  ordered list of messages.
- The schemas for `answer.value` cover the approval value shape in full; a question's value is
  checked by the schema generated from that question's form (FR-009), so a question-answer
  example is checked against its paired request.
- Packaging only places the schema files inside the package; a public loader for them is part of
  spec 002.
- MCP Skills, `Remote`, the bridges and thread-per-door are SDK matters (ADR
  `one-remote-two-doors.md`) and are not part of the standard.
- Out of scope: kinds `auth`, `client_tool`, `provenance`, `caller_context`; MCP Tasks; A2A push
  notifications; multi-hop chains; a TypeScript SDK.
