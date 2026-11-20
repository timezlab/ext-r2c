# R2C standard, version 1

> **Status: draft, written 2026-11-20.** v1 may still change until the first remote outside
> timezlab adopts it; after that it takes additive changes only (`R2C-VERSION-2`).

R2C (Remote-to-Caller) is an extension for [A2A](https://a2a-protocol.org/) and
[MCP](https://modelcontextprotocol.io/). A **remote** (an A2A agent or an MCP server) uses it to
ask its **caller** a `question`, request an `approval`, hand back an `artifact`, and report
`activity` and `usage`. The caller replies with an `answer`. R2C adds no protocol of its own: it
uses only the extension points of A2A and MCP, and it is always optional.

This document is normative. The schemas in [`schema/`](schema/) are the single source of each
object's shape; the examples in [`examples/`](examples/) show every rule that can be shown on the
wire, and every SDK replays them in its tests.

## Contents

1. [Conformance and terms](#1-conformance-and-terms)
2. [Declaration and activation](#2-declaration-and-activation)
3. [Placement, fallback, unknown content](#3-placement-fallback-unknown-content)
4. [Asking: rules shared by `question` and `approval`](#4-asking-rules-shared-by-question-and-approval)
5. [`question`](#5-question)
6. [`approval`](#6-approval)
7. [`answer`](#7-answer)
8. [`artifact`](#8-artifact)
9. [`activity`](#9-activity)
10. [`usage`](#10-usage)
11. [A2A binding](#11-a2a-binding)
12. [MCP binding](#12-mcp-binding)
13. [Identifiers and state](#13-identifiers-and-state)
14. [Trust and safety](#14-trust-and-safety)
15. [Versioning](#15-versioning)
16. [Rules not checked by a schema](#16-rules-not-checked-by-a-schema)
17. [Guidance for callers (non-normative)](#17-guidance-for-callers-non-normative)

## 1. Conformance and terms

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted as described in
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) and
[RFC 8174](https://www.rfc-editor.org/rfc/rfc8174) when, and only when, they appear in all
capitals.

### Roles

| Role | Meaning |
|---|---|
| remote | the called party: an A2A agent or an MCP server. It asks, reports and hands back |
| client, caller | the calling party. It renders, routes and answers |
| person | the human a client's session acts for |
| approver | a human with the right to approve, possibly not the person |
| policy | a rule held by the client and applied by code, never by a model |

### Identifiers

| | Value |
|---|---|
| A2A extension URI | `https://github.com/timezlab/ext-r2c/tree/main/standard/v1` (written `<uri>` below) |
| MCP `_meta` key | `io.github.timezlab/r2c` (written `<key>` below) |
| Schema `$id` | `<uri>/schema/<file>` |

The URI and the key are names. Nobody fetches them at runtime.

### How rules are written

Each rule is a list item opening with a tag line:

`R2C-<AREA>-<n>` · level · party bound (`remote`, `client` or `both`) · `wire` or `prose`, then
` · schema` when a schema rejects a violation.

- `wire`: an example under `examples/a2a/` or `examples/mcp/` shows the rule.
- `prose`: the rule cannot be shown in a message (a behaviour, a UI duty, a time limit).
- `schema`: at least one example under `examples/invalid/` proves the schema rejects a
  violation.

Rule identifiers are never renumbered or reused.

## 2. Declaration and activation

- **R2C-ACT-1** · MUST · remote · wire
  An A2A remote that supports R2C lists `{"uri": "<uri>", "required": false}` in its agent card's
  `capabilities.extensions`. R2C is never `required: true`.
- **R2C-ACT-2** · MUST · remote · wire
  On A2A, a remote sends R2C content in a response only when the client activated R2C for that
  request by listing `<uri>` in the `A2A-Extensions` header. The remote echoes the activated
  extensions in the response's `A2A-Extensions` header.
- **R2C-ACT-3** · MUST · remote · wire
  Without activation the remote sends plain text and standard artifacts only: no R2C part, no R2C
  metadata, and no reasoning.
- **R2C-ACT-4** · MUST · remote · wire
  An MCP server that supports R2C lists `<key>` in the `capabilities.extensions` of its
  `server/discover` result, with the value `{"revision": 1}` for this version of the standard.
- **R2C-ACT-5** · MUST · remote · wire
  On MCP, a server adds R2C `_meta` to a response only when the request's
  `_meta["io.modelcontextprotocol/clientCapabilities"].extensions` map has `<key>` as a key
  (its value is an object, `{}` for v1).

## 3. Placement, fallback, unknown content

- **R2C-CORE-1** · MUST · both · wire
  On A2A, a `question`, `approval`, `answer`, `activity` or `usage` travels as a Part whose
  `data` is the R2C object and whose `metadata` is `{"<uri>": {}}`. The empty object marks the
  part as R2C.
- **R2C-CORE-2** · MUST · both · wire
  On A2A, artifact metadata annotates a standard `Artifact`: the R2C object sits in the
  artifact's `metadata["<uri>"]`.
- **R2C-CORE-3** · MUST · both · wire
  On MCP, an R2C object sits in `_meta["<key>"]` of the MCP object named by the binding
  (section 12).
- **R2C-CORE-4** · MUST · remote · wire
  Every A2A message carrying a `question`, `approval` or `activity` also carries a text Part a
  client without R2C can show:
  - for a request, built from `title`, `description` and each field's `text` and options;
  - for an activity, its `label`.
- **R2C-CORE-5** · MUST · both · wire
  A receiver ignores, without error, an R2C object whose `kind` it does not know.
- **R2C-CORE-6** · MUST · both · wire
  A receiver ignores, without error, an unknown field in a known object, and an `activity`
  whose `type` it does not know. The schemas never close an object.
- **R2C-CORE-7** · MUST · both · prose · schema
  Every R2C object has a `kind`: `question`, `approval`, `answer`, `artifact`, `activity` or
  `usage`.

## 4. Asking: rules shared by `question` and `approval`

Shared fields, in [`question.json`](schema/question.json) and
[`approval.json`](schema/approval.json):

| Field | Required | Meaning |
|---|---|---|
| `kind` | yes | `question` or `approval` |
| `id` | yes | identifies the request within its task |
| `title` | yes | one line: what is asked, or what is about to happen |
| `description` | no | context, reason, consequences; markdown allowed |
| `answer_by` | yes | `{role}`; the roles allowed differ per kind |
| `expires_at` | no | RFC 3339 date-time |
| `origin` | no | `{name, url}` of the first asker, only when forwarded |
| `errors` | no | `[{key?, message}]`, only on a re-ask |

- **R2C-ASK-1** · MUST · remote · wire · schema
  A request has a non-empty `id` and a non-empty `title`.
- **R2C-ASK-2** · MUST · remote · prose
  An `id` is never reused within a task for a different request. Sending the same request again
  (`R2C-ASK-6`) or forwarding it (`R2C-ASK-7`) keeps its `id` and is not a reuse.
- **R2C-ASK-3** · MUST · remote · wire
  A task has at most one pending request. The next one is sent only after the previous one has
  its `answer` or has expired.
- **R2C-ASK-4** · MUST · remote · wire · schema
  `expires_at` is an RFC 3339 date-time. The remote checks expiry itself. Past it, a question
  counts as declined and an approval as `deny`.
- **R2C-ASK-5** · MUST · remote · wire
  An answer after expiry, or with an `id` that matches no pending request, is refused in text.
  A pending request then stays pending. On A2A the refusal is the text of the next status
  update: `TASK_STATE_INPUT_REQUIRED` while a request is still pending, otherwise the state the
  run goes on in.
- **R2C-ASK-6** · MUST · remote · wire
  An answer that fails the request (section 5 mapping, or the approval value) makes the remote
  send **the same request again**, with the same `id`, plus `errors`. The bad answer never
  reaches the remote's agent, and the run continues.
- **R2C-ASK-7** · MUST · both · wire
  A party that forwards a request to another party keeps the `id` unchanged and sets `origin` to
  the first asker.
- **R2C-ASK-8** · MAY · remote · wire
  Without activation (`R2C-ACT-3`) a remote asks in text only, in a `TASK_STATE_INPUT_REQUIRED`
  status. When the client replies in text, the remote MAY accept the text as the answer only
  when the form has exactly one `one` or `text` field and the text fits it. Otherwise it asks
  again.

## 5. `question`

Schema: [`question.json`](schema/question.json). A question asks for information the remote
lacks and only a person or the caller has. It is not for permission (use `approval`) or for
progress (use `activity`).

| Field of `fields[]` | Required | Meaning |
|---|---|---|
| `key` | yes | `^[a-z][a-z0-9_]*$`, not ending in `_other`; the key of the value in the answer |
| `header` | yes | short label |
| `text` | yes | the question itself |
| `type` | yes | `one`, `many`, `text`, `number`, `bool` |
| `options` | for `one`, `many` | `[{label, description?}]`; the answer value is the `label` |
| `other` | no, default `true` | `one` / `many`: free text allowed besides the options |
| `required` | no, default `true` | the field must have a value |

- **R2C-QUESTION-1** · MUST · remote · wire · schema
  `answer_by.role` is `person` (a human must answer) or `caller` (the caller may answer itself:
  its agent from the conversation, a job from its configuration).
- **R2C-QUESTION-2** · MUST · remote · wire · schema
  A question has at least one field. Each field has `key`, `header`, `text` and `type`, and its
  `key` does not end in `_other`.
- **R2C-QUESTION-3** · MUST · remote · wire · schema
  `options` is present, with at least one option, for `one` and `many`, and absent for the other
  types.
- **R2C-QUESTION-4** · MUST · remote · prose
  Field keys are unique within a question, and option labels are unique within a field.
- **R2C-QUESTION-5** · MUST · both · wire
  The schema that checks a question's answer is generated from its fields as below; the remote's
  author never writes it by hand. The answer's `value` is keyed by field key; a field with
  `required: false` may be left out.

| Field | Schema of the value |
|---|---|
| `one`, `other: false` | `{"type": "string", "enum": [labels]}` |
| `one`, `other: true` | `{"type": "string", "minLength": 1}` |
| `many`, `other: false` | `{"type": "array", "items": {"enum": [labels]}, "uniqueItems": true}` |
| `many`, `other: true` | `{"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": true}` |
| `text` | `{"type": "string"}` |
| `number` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |

The form's schema is `{"type": "object", "properties": {<key>: <schema>}, "required": [<keys
with required: true>]}`.

## 6. `approval`

Schema: [`approval.json`](schema/approval.json). An approval asks before the remote does
something with effects outside itself that is hard to undo. Examples are writing or deleting
data, sending messages, publishing, deploying, spending money, and sharing data outward. It is
answered by a person, an approver or a policy, never by a model.

| Field | Required | Meaning |
|---|---|---|
| `subject` | yes | `{type: "tool_call", name, args, args_schema?}`, `{type: "operation", name, target?}`, or another `type` with a `name` (never auto-allowed, `R2C-APPROVAL-5`); machine data for a policy to match |
| `decisions` | yes | a non-empty, unique subset of `allow`, `edit`, `deny` |

- **R2C-APPROVAL-1** · MUST · remote · wire · schema
  An approval has one `subject`, with a `type` and a `name`. A `tool_call` subject has `args`.
  `decisions` holds at least one of `allow`, `edit`, `deny`, each at most once.
- **R2C-APPROVAL-2** · MUST NOT · both · wire · schema
  An approval is never addressed to the caller: `answer_by.role` is never `caller`, only
  `person` or `approver`. With `approver`, an optional `approver_role` names who may approve.
- **R2C-APPROVAL-3** · MUST · remote · wire · schema
  `edit` is offered only on a `tool_call` subject that carries `args_schema`, the JSON Schema of
  its `args`.
- **R2C-APPROVAL-4** · MUST · remote · wire
  When several actions need approval at once, the remote sends one approval at a time, in the
  order the actions were requested (the model's tool-call order). Each is decided on its own: one
  `deny` does not drop the others.
- **R2C-APPROVAL-5** · MUST NOT · client · prose
  A client never auto-allows, by policy, an approval whose `subject.type` it does not know. It
  asks a person.

## 7. `answer`

Schema: [`answer.json`](schema/answer.json).

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | the `id` of the request answered |
| `outcome` | yes | `answered` or `declined` |
| `answered_by` | yes | `{role: person \| approver \| policy \| caller, label?}`: the client's claim |
| `value` | when `answered` | a question: `{<key>: value}`; an approval: `{decision, args?, reason?}` |
| `note` | no | free text |

- **R2C-ANSWER-1** · MUST · client · wire · schema
  An answer has `kind`, `id`, `outcome` and `answered_by`. `value` is present when `outcome` is
  `answered` and absent when it is `declined`.
- **R2C-ANSWER-2** · MUST · client · wire
  An approval's value has a `decision` among the approval's `decisions`. With `edit` it carries
  `args` that fit `args_schema`. It MAY carry a `reason`, which the remote passes to its agent
  (a deny's reason becomes the tool's rejection message). `answer.json` alone cannot tell which
  kind of request was answered, so a receiver checks an approval's value against
  `answer.json#/$defs/approval_value` and a question's against its generated form schema.
- **R2C-ANSWER-3** · MUST · client · wire
  `declined` means the person refused or closed the form, or nobody could answer (an unattended
  run). A declined approval counts as `deny`: the action does not happen.
- **R2C-ANSWER-4** · MUST NOT · client · prose
  A model never answers an approval. The client never sends `answered_by.role = caller` for an
  approval, and lets no agent of its own decide one. Only the client can enforce this.
- **R2C-ANSWER-5** · MAY · client · wire
  A client MAY answer an approval itself from a rule it holds (remembered consent, "always
  allow"). It then writes `answered_by.role = policy`. The rule is applied by code, never by a
  model, and never to an approval with `answer_by.role = approver`, which asks every time.
- **R2C-ANSWER-6** · MUST · remote · prose
  The remote treats `answered_by` as the client's claim, not as verified identity, and keeps no
  per-user consent state.

## 8. `artifact`

Schema: [`artifact-meta.json`](schema/artifact-meta.json). R2C adds no artifact container: an
artifact is a standard A2A `Artifact` (or MCP content). R2C only says how to present it.

| Field | Required | Meaning |
|---|---|---|
| `presentation` | yes | `file` (download or save), `inline` (show in place), `live` (embed a page of the remote while it runs) |
| `state` | no | `open` / `closed`, `live` only |
| `response` | no | `true`: this is the task's reply text, `inline` only |

- **R2C-ARTIFACT-1** · MUST · remote · wire · schema
  Artifact metadata has `kind: "artifact"` and a `presentation`. `state` appears only with
  `live`.
- **R2C-ARTIFACT-2** · MUST · remote · wire · schema
  A task's reply text is **one** artifact with `presentation: "inline"` and `response: true`. A
  task has at most one such artifact.
- **R2C-ARTIFACT-3** · MUST · remote · wire
  The reply artifact is streamed:
  - the first chunk is sent with `append: false`, the following ones with `append: true`, and
    the last with `lastChunk: true`;
  - it holds all the text the model writes during the task, in order, including short narration
    between tool calls;
  - activities and chunks interleave in the order they happen;
  - each chunk repeats the artifact's R2C metadata;
  - the reply stays open across an input-required pause: `lastChunk` comes with the last text
    of the task, not before a request.
- **R2C-ARTIFACT-4** · MUST · remote · wire
  A `file` is one artifact per file. Its part carries the content by `url` or `raw`, together
  with `filename` and `mediaType`.
- **R2C-ARTIFACT-5** · MUST · remote · wire
  Sending the same `artifactId` again with `append: false` is a new version that replaces the
  previous one.
- **R2C-ARTIFACT-6** · MUST · remote · wire
  On A2A, a `live` artifact is a part with a `url` of `mediaType: text/html` and
  `state: "open"`. When the page is done, the remote sends the same `artifactId` again, part
  included, with `state: "closed"`. On MCP a result arrives once, so a `live` artifact there has
  no `state`.
- **R2C-ARTIFACT-7** · SHOULD · client · wire
  For an artifact without R2C metadata, a client guesses:
  - a part with `raw`, or a `url` with `filename`, is a `file`;
  - a `text` or `data` part is `inline`;
  - a `url` with `mediaType: text/html` is only a link opened in a new tab, never fetched and
    never embedded.

  `live` is never guessed.
- **R2C-ARTIFACT-8** · SHOULD · remote · prose
  A file `url` stays valid at least 24 hours after the task ends. A client copies the file
  rather than keeping the link.
- **R2C-ARTIFACT-9** · MUST NOT · remote · prose
  A file never travels inside a status message.

## 9. `activity`

Schema: [`activity.json`](schema/activity.json). What the remote is doing, for the caller to
show as a timeline.

| `type` | Is |
|---|---|
| `tool` | one tool call, from start to result |
| `step` | a phase of work that is not a single tool call: a graph node, a sub-agent or handoff (its own activities nest under it), or a progress line the remote reports itself |
| `reasoning` | the model's reasoning text, only when the remote's owner allows it |

Other fields: `state` (`running`, `done`, `failed`), `label`, `name`, `args`, `detail`,
`duration_ms`, `parent_id` and `delta`. See the schema for each.

- **R2C-ACTIVITY-1** · MUST · remote · wire · schema
  An activity has `id`, `type` and `label`. A `tool` or `step` activity has a `state`. A `tool`
  activity has the tool's `name`.
- **R2C-ACTIVITY-2** · MUST · remote · wire
  Updates of one activity keep its `id`. The state of a `tool` or `step` goes `running`, then
  `done` or `failed`, and nothing follows a terminal state. `duration_ms` and `detail` (a short
  summary, never the whole output) come with the terminal state. A `reasoning` activity has no
  `state`: it is the sum of its deltas, each update repeating its `label`.
- **R2C-ACTIVITY-3** · MUST · remote · wire
  An activity nested under another one sets `parent_id` to the outer activity's `id`, for
  example the tool calls of a sub-agent's step.
- **R2C-ACTIVITY-4** · MUST · remote · wire · schema
  `delta` appears only on a `reasoning` activity. It is text appended to the reasoning with the
  same `id`.
- **R2C-ACTIVITY-5** · MUST NOT · remote · prose
  A remote sends no `reasoning` unless its owner turned it on, and never sends provider
  signatures or encrypted reasoning.
- **R2C-ACTIVITY-6** · MUST NOT · remote · prose
  A tool activity carries `args` only when the remote's owner exposed that tool's arguments.
- **R2C-ACTIVITY-7** · SHOULD · remote · wire
  Reasoning deltas are coalesced into readable pieces, not sent one token per event.

## 10. `usage`

Schema: [`usage.json`](schema/usage.json). Fields: `input_tokens`, `output_tokens`,
`duration_ms`, `cost {amount, currency}` (ISO 4217) and `model`.

- **R2C-USAGE-1** · MUST · remote · wire · schema
  A usage has at least one of `input_tokens`, `output_tokens`, `duration_ms`, `cost`. A `cost`
  has an `amount` and a three-letter upper-case `currency`.
- **R2C-USAGE-2** · MUST · both · wire
  Usage is cumulative for the task: a later `usage` replaces an earlier one.
- **R2C-USAGE-3** · MUST · client · prose
  A missing field means unknown, never zero. Usage is the remote's claim: a client shows it and
  never bills from it.

## 11. A2A binding

The binding targets A2A 1.0. Objects below are written in A2A's JSON form (`taskId`,
`TASK_STATE_INPUT_REQUIRED`, parts with `text` / `data` / `url` / `raw`). The examples show them
complete. A remote's messages have `role: ROLE_AGENT` and a client's `ROLE_USER`. The order of
the parts in a message carries no meaning; the examples put the text Part first.

- **R2C-A2A-1** · MUST · remote · wire
  A `question` or `approval` travels in the message of a status update with state
  `TASK_STATE_INPUT_REQUIRED`, together with its text Part.
- **R2C-A2A-2** · MUST · client · wire
  An `answer` travels in a new message with the task's `taskId` and `contextId`. It is a data
  Part, together with a text Part saying the answer in words.
- **R2C-A2A-3** · MUST · remote · wire
  An `activity` travels in the message of a status update with state `TASK_STATE_WORKING`, one
  activity per update, together with its text Part.
- **R2C-A2A-4** · MUST · remote · wire
  A `usage` travels as a data Part in a status update's message, at the latest in the terminal
  one (`TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, `TASK_STATE_CANCELED`). It MAY also travel in
  a `TASK_STATE_INPUT_REQUIRED` one.
- **R2C-A2A-5** · MUST · remote · wire
  An artifact travels as an artifact update (`artifactUpdate`) whose artifact carries the R2C
  metadata.
- **R2C-A2A-6** · MAY · client · wire
  A client whose stream was cut reattaches with `SubscribeToTask`. `GetTask` returns the task's
  artifacts and its last status, `usage` included.
- **R2C-A2A-7** · MUST · client · wire
  A follow-up in the same conversation is a new message with the same `contextId` and no
  `taskId`. It opens a new task that remembers the conversation. R2C adds nothing to this core
  A2A behaviour.

## 12. MCP binding

The binding targets MCP protocol revision 2026-07-28. A question or approval is asked through a
multi-round-trip tool call: the tool call returns an `InputRequiredResult` with an elicitation
form, and the client calls the tool again with its responses.

- **R2C-MCP-1** · MUST · remote · wire
  A `question` or `approval` is one `elicitation/create` form request in the result's
  `inputRequests`. The R2C object sits in the **result's** `_meta["<key>"]` as
  `{"input_requests": {"<request key>": <object>}}`, where the request key is the key in
  `inputRequests` and SHOULD equal the object's `id`. (MCP 2026-07-28 gives an elicitation's
  params no `_meta`.)
- **R2C-MCP-2** · MUST · remote · wire
  The elicitation's `requestedSchema` is flat and generated from the question's fields:

  | Field | `requestedSchema` property |
  |---|---|
  | `one`, `other: false` | `{"type": "string", "oneOf": [{"const": label, "title": label}]}` |
  | `one`, `other: true` | as above, plus `<key>_other: {"type": "string"}` |
  | `many`, `other: false` | `{"type": "array", "items": {"anyOf": [{"const": label, "title": label}]}}` |
  | `many`, `other: true` | as above, plus `<key>_other: {"type": "string"}` |
  | `text`, `number`, `bool` | `{"type": "string" / "number" / "boolean"}` |

  `<key>_other` is never required. On the way back, `<key>` and `<key>_other` become one value,
  and a non-empty `<key>_other` wins.
- **R2C-MCP-3** · MUST · remote · wire
  An approval's elicitation has a `decision` property (`oneOf` the offered decisions) and an
  optional `reason` string. `edit` survives only when `args_schema` is flat (every property a
  string, number, boolean or enum). In that case each argument is added as a property, with its
  current value as `default`. Otherwise `edit` is dropped from the offered decisions.
- **R2C-MCP-4** · MUST · both · wire
  The client calls the tool again with `inputResponses` keyed like `inputRequests` and with
  `requestState` echoed unchanged. The remote derives the R2C `answer` from each response:
  - `accept` gives `answered`, with `content` as the value;
  - `decline` and `cancel` give `declined`;
  - `answered_by.role` is `person`, because MCP requires the user to review every response.

  No R2C answer object travels on MCP, so a `policy` answer (`R2C-ANSWER-5`) does not exist
  there.
- **R2C-MCP-5** · MUST · remote · prose
  `requestState` is opaque to the client, sealed against tampering, time-limited, and bound to
  the requesting principal and audience.
- **R2C-MCP-6** · MUST · remote · wire
  An `activity` travels as `notifications/progress` for a request that carried a
  `progressToken`. `message` is the activity's `label`, and the activity sits in the
  notification params' `_meta["<key>"]`. Without a `progressToken`, no activity is sent.
- **R2C-MCP-7** · MUST · remote · wire
  Artifacts travel as content of the tool result, with the artifact metadata in the content
  block's `_meta["<key>"]`:
  - `file` is a `resource_link` or an embedded `resource`;
  - `inline` is `text`;
  - `live` is a `resource_link`.

  The reply text is the result's `text` content with `response: true`. MCP does not stream it.
- **R2C-MCP-8** · MUST · remote · wire
  `usage` sits in the tool result's `_meta["<key>"]`.

## 13. Identifiers and state

| Identifier | Issued by | Meaning |
|---|---|---|
| `contextId` | the client on the first message, or the remote | one conversation, several tasks |
| `taskId` | the remote | one unit of work: the thing that stops at `input-required` |
| request `id` | the remote | one request within a task |
| `requestState` | the MCP server | the sealed stopping point of one tool call |

- **R2C-ID-1** · SHOULD · remote · prose
  A remote keys its internal conversation state by owner and context, never by the bare
  `contextId`. Clients may choose context ids, so two owners can pick the same one.
- **R2C-ID-2** · MUST · remote · prose
  A context has at most one unfinished task. The remote refuses a second one.
- **R2C-ID-3** · SHOULD · client · prose
  A client stores `contextId` and `taskId` durably per connection and conversation, so it can
  continue and resume after its own restart.
- **R2C-ID-4** · SHOULD · remote · prose
  A remote keeps tasks and conversation state in durable storage and documents how long it keeps
  a context.

## 14. Trust and safety

- **R2C-SAFETY-1** · MUST · client · prose
  The client sends the user's credentials only to the connection's own origin. A `url` on another
  host is shown as a link and never fetched by the client.
- **R2C-SAFETY-2** · MUST · client · prose
  `inline` HTML or SVG is shown in a sandboxed frame without `allow-same-origin`, or as source.
- **R2C-SAFETY-3** · MUST · client · prose
  A `live` page is framed with:
  - `frame-src` limited to the origins of the client's own connections;
  - no `postMessage` bridge;
  - an "open in new tab" control always shown.
- **R2C-SAFETY-4** · SHOULD · remote · prose
  Content inside a message (`raw`, or `inline` text) is at most 5 MiB (5 × 2^20 bytes)
  after decoding; larger content goes by `url`. A file fetched by `url` is at most 50 MiB.
- **R2C-SAFETY-5** · MUST · client · prose
  A client enforces its own size limits (it MAY choose its own thresholds). It shows an oversized
  inline part as "content too large", and an oversized file as a link.
- **R2C-SAFETY-6** · MUST · client · prose
  `activity` and `usage` are display data from another party. The client escapes them and never
  treats them as instructions.
- **R2C-SAFETY-7** · MUST NOT · client · prose
  A client never follows a `$ref` in an `args_schema` that leaves the document. It treats such an
  approval as not offering `edit`.

## 15. Versioning

- **R2C-VERSION-1** · MUST · both · prose
  The major version is in the URI. A breaking change opens `standard/v2/` with a new URI (A2A)
  and the next `revision` in the MCP declaration (`R2C-ACT-4`); v1 stays valid beside it.
- **R2C-VERSION-2** · MUST · both · prose
  v1 is a draft until the first remote outside timezlab adopts it, and may change until then.
  Afterwards it takes additive changes only.
- **R2C-VERSION-3** · MUST · both · prose
  A new value in a closed enum (`decisions`, `presentation`, `state`, `outcome`, a role, a
  field `type`) is a breaking change and needs a new major version: a receiver validating
  against v1 rejects a value v1 does not list. Additive changes are new optional fields, new
  kinds, and new `activity` types (`R2C-CORE-5`, `R2C-CORE-6`).

## 16. Rules not checked by a schema

These rules cannot be expressed in JSON Schema. Implementations enforce them in code, and the
examples show the ones marked `wire`.

- Shown by examples:
  `R2C-ACT-1`–`5`, `R2C-CORE-1`–`6`, `R2C-ASK-3`, `R2C-ASK-5`–`8`, `R2C-QUESTION-5`,
  `R2C-APPROVAL-4`, `R2C-ANSWER-2`, `R2C-ANSWER-3`, `R2C-ANSWER-5`, `R2C-ARTIFACT-3`–`7`,
  `R2C-ACTIVITY-2`, `R2C-ACTIVITY-3`, `R2C-ACTIVITY-7`, `R2C-USAGE-2`, `R2C-A2A-1`–`7`,
  `R2C-MCP-1`–`4`, `R2C-MCP-6`–`8`.
- Prose only:
  `R2C-ASK-2`, `R2C-QUESTION-4`, `R2C-APPROVAL-5`, `R2C-ANSWER-4`, `R2C-ANSWER-6`,
  `R2C-ARTIFACT-8`, `R2C-ARTIFACT-9`, `R2C-ACTIVITY-5`, `R2C-ACTIVITY-6`, `R2C-USAGE-3`,
  `R2C-MCP-5`, `R2C-ID-1`–`4`, `R2C-SAFETY-1`–`7`, `R2C-VERSION-1`–`3`.

Some of the rules marked `schema` above have a part a schema cannot check:
- the "at most one per task" of `R2C-ARTIFACT-2`;
- the expiry behaviour of `R2C-ASK-4`.

## 17. Guidance for callers (non-normative)

How a caller presents and routes requests is its own design. These are the shapes R2C was
designed against.

- **`answer_by.role` is `person` or `approver`.** Show a form or an approval dialog to the user,
  labelled with the remote's name (and `origin` when forwarded). An approval looks like a
  warning, and the client records who approved.
- **`answer_by.role` is `caller`.** The request goes to the caller's own agent first. The agent
  answers from what it already knows, or forwards the request to its user. `answered_by` records
  who really answered.
- **A remote without R2C (text only).** The caller's agent may answer from what it already has,
  and shows each such answer to the user with its source. It never answers an approval.
- **"Always allow".** A client-held policy, whose scope is the caller's choice: same user, same
  connection, same `subject.name`, per conversation or permanent.
- **An unattended run.** A request for a `person` is answered `declined`, or the task is
  canceled.
