# Data model: R2C standard, version 1

**Feature**: [spec.md](spec.md) · **Date**: 2026-11-20

The six kinds below are what `standard/v1/schema/` encodes. Field names are `snake_case`. Every
object is **open**: unknown fields are allowed and ignored (FR-016). "Schema" in the last column
of a rule means the schema rejects a violation; anything else is prose only (FR-017).

## Shared definitions (repeated inside each schema that uses them; no cross-file `$ref`)

| Name | Shape |
|---|---|
| `id` | non-empty string |
| `answer_by` | `{role, approver_role?}`; `role` is `person`, `caller` or `approver` (narrowed per kind) |
| `origin` | `{name, url}`, both required, `url` a string; present only when forwarded |
| `error_item` | `{key?, message}`; `message` required |
| `timestamp` | string, `format: date-time` (RFC 3339) |

## `question` (`question.json`)

| Field | Type | Required | Rule (schema-checked unless marked) |
|---|---|---|---|
| `kind` | `"question"` | yes | const |
| `id` | string ≥ 1 | yes | never reused within a task (prose) |
| `title` | string ≥ 1 | yes | one line (prose) |
| `description` | string | no | markdown allowed |
| `answer_by` | `{role: person \| caller}` | yes | `approver` rejected |
| `expires_at` | timestamp | no | past it, the question counts as declined (prose) |
| `origin` | origin | no | |
| `errors` | `[error_item]`, ≥ 1 | no | only on a re-ask (prose) |
| `fields` | `[field]`, ≥ 1 | yes | keys unique within the form (prose) |

`field`:

| Field | Type | Required | Rule |
|---|---|---|---|
| `key` | string matching `^[a-z][a-z0-9_]*$` | yes | must not end in `_other` (the MCP flat form uses that suffix) |
| `header` | string ≥ 1 | yes | short label |
| `text` | string ≥ 1 | yes | the question itself |
| `type` | `one` \| `many` \| `text` \| `number` \| `bool` | yes | closed enum |
| `options` | `[{label, description?}]`, ≥ 1 | for `one` and `many` | required when `type` is `one` or `many`; forbidden otherwise |
| `other` | boolean, default `true` | no | meaningful for `one` and `many` only |
| `required` | boolean, default `true` | no | |

## `approval` (`approval.json`)

| Field | Type | Required | Rule |
|---|---|---|---|
| `kind` | `"approval"` | yes | const |
| common | `id`, `title`, `description`, `expires_at`, `origin`, `errors` | as for `question` | |
| `answer_by` | `{role: person \| approver, approver_role?}` | yes | `caller` rejected (constitution V) |
| `subject` | `tool_call` or `operation` (below) | yes | one subject per approval |
| `decisions` | non-empty, unique subset of `allow`, `edit`, `deny` | yes | `edit` requires `subject.type = tool_call` with `args_schema` |

`subject`:

- `{type: "tool_call", name, args (object), args_schema? (object)}`: `name` and `args` required.
- `{type: "operation", name, target?}`: `name` required.
- Any other `type`: allowed by the schema (open) but never auto-allowed by a client (prose).
- `args_schema` holds no `$ref` that leaves the document (prose; a client checks it).

## `answer` (`answer.json`)

| Field | Type | Required | Rule |
|---|---|---|---|
| `kind` | `"answer"` | yes | const |
| `id` | string ≥ 1 | yes | the request being answered |
| `outcome` | `answered` \| `declined` | yes | |
| `answered_by` | `{role: person \| approver \| policy \| caller, label?}` | yes | `caller` on an approval's answer is forbidden (prose; client MUST) |
| `value` | object | when `answered` | absent when `declined` |
| `note` | string | no | |

`$defs/approval_value` (used by the check for answers paired with an approval):
`{decision: allow | edit | deny, args? (object), reason? (string)}`, where `args` is required
when `decision = edit`. A question's `value` is `{<field key>: value}`, checked against the
schema generated from that question's form (FR-009 mapping, below).

## `artifact` metadata (`artifact-meta.json`)

The object under an A2A artifact's `metadata[uri]` (or under `_meta[key]` of an MCP content
block).

| Field | Type | Required | Rule |
|---|---|---|---|
| `kind` | `"artifact"` | yes | const |
| `presentation` | `file` \| `inline` \| `live` | yes | |
| `state` | `open` \| `closed` | no | only with `live` (schema) |
| `response` | `true` | no | only with `inline` (schema); at most one per task (prose) |

Rules on the surrounding artifact (prose plus examples): `filename` and `mediaType` on the part
for `file`; streaming by `append` / `lastChunk`; versions by `artifactId`; guessing when the
metadata is missing; `url` valid ≥ 24 h; size limits.

## `activity` (`activity.json`)

| Field | Type | Required | Rule |
|---|---|---|---|
| `kind` | `"activity"` | yes | const |
| `id` | string ≥ 1 | yes | stable across updates of one activity |
| `type` | string ≥ 1 | yes | known values `tool`, `step`, `reasoning`; an unknown value is allowed and ignored by receivers |
| `state` | `running` \| `done` \| `failed` | for `tool` and `step` | conditional on known `type` |
| `label` | string ≥ 1 | yes | the text fallback |
| `name` | string | for `tool` | |
| `args` | object | no | only when the remote's owner exposes that tool's args (prose) |
| `detail` | string | no | short summary, never the whole output (prose) |
| `duration_ms` | integer ≥ 0 | no | on `done` / `failed` (prose) |
| `parent_id` | string | no | refers to another activity's `id` (prose) |
| `delta` | string | no | only for `reasoning` (schema) |

State transitions for one `id`: `running` → `done` | `failed`; nothing after a terminal state.
`reasoning` streams by `delta` and MAY carry `state` (`running`, then `done`).

## `usage` (`usage.json`)

| Field | Type | Required | Rule |
|---|---|---|---|
| `kind` | `"usage"` | yes | const |
| `input_tokens` | integer ≥ 0 | no | |
| `output_tokens` | integer ≥ 0 | no | |
| `duration_ms` | integer ≥ 0 | no | |
| `cost` | `{amount: number ≥ 0, currency: ^[A-Z]{3}$}` | no | both inner fields required |
| `model` | string | no | |

At least one of `input_tokens`, `output_tokens`, `duration_ms`, `cost` is present (schema:
`anyOf` of `required`). Cumulative per task; a later one replaces an earlier one (prose).

## Form → schema mapping (FR-009)

| Field | Schema that checks the answer (A2A and the remote) | MCP flat `requestedSchema` property |
|---|---|---|
| `one`, `other: false` | `{"type":"string","enum":[labels]}` | `{"type":"string","oneOf":[{"const":label,"title":label}]}` |
| `one`, `other: true` | `{"type":"string","minLength":1}` | as above, plus `<key>_other: {"type":"string"}` (not required) |
| `many`, `other: false` | `{"type":"array","items":{"enum":[labels]},"uniqueItems":true}` | `{"type":"array","items":{"anyOf":[{"const":label,"title":label}]}}` |
| `many`, `other: true` | `{"type":"array","items":{"type":"string","minLength":1},"uniqueItems":true}` | as above, plus `<key>_other: {"type":"string"}` |
| `text` | `{"type":"string"}` | `{"type":"string"}` |
| `number` | `{"type":"number"}` | `{"type":"number"}` |
| `bool` | `{"type":"boolean"}` | `{"type":"boolean"}` |

The form's schema is `{"type":"object","properties":{…},"required":[keys with required: true]}`.
On MCP, `<key>` and `<key>_other` map back to one value: `<key>_other` wins when it is non-empty.

An approval over MCP: `{"decision": {"type":"string","oneOf":[…decisions…]}, "reason":
{"type":"string"}}`. When `edit` is offered and `args_schema` is flat (every property a primitive
type), the arg properties are added, pre-filled through `default`; otherwise `edit` is dropped.

## Non-kind entities

- **Rule**: `{id: R2C-<AREA>-<n>, level, party, wire|prose, schema?}`; grammar in
  [contracts/rule-format.md](contracts/rule-format.md).
- **Wire example**: a file under `examples/a2a/` or `examples/mcp/`; format in
  [contracts/example-file.md](contracts/example-file.md).
- **Invalid example**: a file under `examples/invalid/`; same contract.
- **Packaged schema**: `ext_r2c/schema/v1/<file>.json` in the wheel; see
  [contracts/packaged-schemas.md](contracts/packaged-schemas.md).
