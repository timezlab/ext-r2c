# Research: Python core (`ext_r2c.core`)

Phase 0 of [plan.md](plan.md). Each entry: decision, rationale, alternatives. Facts were checked
on 2026-11-20 with Python 3.11.14, pydantic 2.14.4 and jsonschema 4.26.0 (the versions in the CI
venv), by a throwaway script outside the repository.

## R1. Models that round-trip unchanged

**Decision:** pydantic v2 models with `extra="allow"` on every object, written back with
`model_dump(mode="json", exclude_unset=True)`. Defaults (`other`, `required`) are read through
the model but never written. `kind` is always written, also for an object built in code (it is
marked as set when the model is built). Numbers that the schema types as `number` are typed
`int | float`, so `300` stays `300`. Date-times (`expires_at`) stay strings on the model, with a
parse helper, so `Z` is never rewritten as `+00:00`.

**Checked:** a field with an unknown nested key and an option with an unknown key round-trip to
an equal value; `other` reads `True` when absent and stays absent on dump; `int | float` keeps
`300` and `2.5`.

**Alternatives:** dataclasses plus hand-written JSON (no validation, more code); pydantic with
`extra="ignore"` (drops unknown fields, breaks R2C-CORE-6); keeping the raw dict beside the model
(two sources of truth).

## R2. The schema is the judge

**Decision:** parsing validates the object against its packaged schema first, then builds the
model. Writing an object built in code validates the dumped JSON against the schema, so code
cannot emit an object the schema rejects. Rules a schema cannot check on a single object
(R2C-QUESTION-4: unique keys and labels) are checked after the schema. Errors carry a JSON
pointer and a message.

**Rationale:** constitution I. pydantic types alone cannot express every `if/then` of the
schemas (for example `edit` ⇒ `tool_call` with `args_schema`); duplicating them in Python would
create a second source of shape.

**Alternatives:** generating models from the schemas (datamodel-code-generator: a build-time
dependency, and the generated code still misses `if/then`); pydantic-only validation (drifts).

## R3. `date-time` needs a checker of our own

**Finding:** jsonschema checks `format: date-time` only when the optional package
`rfc3339_validator` is importable. The test venv has it (through `jsonschema[format-nongpl]` in
the dev group), a core-only install does not, and there the check is silently skipped:
`invalid/question-expires-not-a-date.json` would pass.

**Decision:** the core registers its own `date-time` check on the format checker it uses: an
RFC 3339 `date-time` regular expression plus `datetime.fromisoformat` for the calendar. The
core-only check of the plan (SC-006) asserts that the invalid example is rejected without
`rfc3339_validator`.

**Alternatives:** adding `rfc3339-validator` as a dependency (breaks constitution VIII);
`datetime.fromisoformat` alone (accepts dates without a time, which RFC 3339 `date-time` does
not).

## R4. No `$ref` leaves the document

**Finding:** jsonschema 4.18+ does not fetch a remote `$ref` by default; validating against
`{"$ref": "https://example.com/x.json"}` raises a referencing error instead.

**Decision:** before an `args_schema` is used, the core walks it and finds every `$ref`. Any
`$ref` that does not start with `#` makes the schema external: `edit` is not offered
(R2C-SAFETY-7), it is not flat for MCP, and it is never handed to a validator. A local `$ref`
(`#/$defs/...`) is resolved by jsonschema within the document. The core imports no
`referencing` API directly (constitution VIII names only `pydantic` and `jsonschema`).

**Alternatives:** catching the referencing error at validation time (the decision comes too
late: `edit` would already be offered); a custom registry that refuses retrieval (needs the
`referencing` package API).

## R5. Sub-schemas of a packaged schema

**Decision:** `answer.json#/$defs/approval_value` is checked with a wrapper schema
`{"$schema", "$defs": <answer.json $defs>, "$ref": "#/$defs/approval_value"}`, the same method the
spec 001 tests use. No registry is needed.

## R6. Problems a person can read

**Decision:** `check_answer` returns `Problem(code, key, message)`. `code` is machine data
(`too_large`, `invalid_answer`, `wrong_id`, `caller_on_approval`, `expired`, `invalid_value`,
`not_offered`, `invalid_args`). `key` is the field key or argument name, taken from the first
step of the error path. For a `required` error the missing names come from the validator's
`required` list. `message` is short English for a person, from a small table per JSON Schema
keyword (`type`, `enum`, `minLength`, `minItems`, `required`, `minimum`, `maximum`,
`uniqueItems`), falling back to "This value is not accepted." (jsonschema's own messages quote
JSON). `Problem.as_error_item()` gives the
re-ask `errors` entry (R2C-ASK-6).

**Rationale:** a door decides from `code` whether to re-ask (`invalid_value`, `invalid_args`,
`not_offered`) or refuse (`wrong_id`, `expired`: R2C-ASK-4, R2C-ASK-5).

**Alternatives:** returning jsonschema errors (technical text in a form); raising on the first
problem (the person fixes one field per round trip).

## R7. Flat MCP forms, exactly as the examples show

**Decision:** the generators reproduce the three MCP examples' `requestedSchema` exactly
(compared as JSON values):

- question property: `type`, `title` = `header`, `description` = `text`; `one` → `oneOf` of
  `{const, title}` (option descriptions are not carried: MCP's titled enum has none); `many` →
  `items.anyOf` of the same; `<key>_other` → `{"type": "string", "title": "<header> (other)",
  "description": "Another <header lower-cased>, if not listed."}`;
- `required`: keys of fields with `required: true`, except fields with `other: true` (the value
  may arrive in either property, FR-013); the key is left out when the list is empty;
- approval: `decision` (`title` "Decision", `oneOf` titled `Allow` / `Edit` / `Deny` in the
  order of `decisions`) and `reason` (`title` "Reason"), `required: ["decision"]`; with `edit`,
  each argument's own property schema, `title` = the argument name, `enum` turned into a titled
  `oneOf`, `default` = the current value; arguments are never required.

**Flat** means `args_schema` has `type: object` and `properties`, every property's `type` is
`string`, `number`, `integer` or `boolean` (or it is an `enum` of strings), no property uses
`$ref`, `anyOf`, `oneOf`, `allOf` or `not`, and no argument is called `decision` or `reason`.

The elicitation `message` is not generated here (O5, spec 004).

**Found while checking:** `mcp/elicitation-question-other.json` leaves `description` out of the
`warehouse` property, while `mcp/elicitation-question.json` always carries it. The rule stays
simple (`description` is always `text`). The example gets the missing `description` in the same
change as the generator. The alternative, leaving `description` out when it equals the
elicitation `message`, would tie the core to the message, which belongs to 004.

## R8. Mapping a flat response back

**Decision:**
- `<key>_other` counts as given when it is a string that is not empty after stripping spaces.
  For `one` it replaces `<key>`; for `many` it is appended once (not if it equals a chosen label).
  Content keys that are not in the form are dropped.
- Approval: `decision` as sent; `reason` only when non-empty; for `edit`, `args` = the current
  `args`, with each `args_schema` property present in the content replacing its value; for any
  other decision, argument values in the content are ignored.
- `accept` → `answered`; `decline`, `cancel` → `declined` with no value; `answered_by.role` is
  `person`.

The mapping never checks; the result goes through `check_answer` like an A2A answer.

## R9. A question answer schema with "not empty" (Q2)

**Decision:** `answer_schema(question)` follows the R2C-QUESTION-5 table, and for a field with
`required: true` adds `minLength: 1` to `text` and `minItems: 1` to `many`. `one` with
`other: true` already has `minLength: 1`; `one` with `other: false` is an `enum`; `number` and
`bool` cannot be empty. No answer in the current examples is empty (checked), so no example
changes meaning.

## R10. One driver for both pause styles

**Decision:** `AgentSource` declares its style (`pause = "checkpoint"` or `"live"`).
- `run(input, ctx)` is an async iterator of run events.
- A **checkpoint** source ends its iterator right after yielding an `Ask`; the driver later
  calls `resume(answer, ctx)`, another async iterator.
- A **live** source calls `await ctx.ask(request)` inside `run`; the context hands the `Ask` to
  the driver's queue and waits on a future that `deliver` resolves.

The driver runs the source in one asyncio task that feeds one queue, so a door reads one ordered
stream either way.
- The driver itself emits `AnswerEvent` when an answer is delivered. It also emits the single
  terminal event: `Done` when the source finishes, `Error` when it raises, is cancelled, or
  breaks the sequence rules (an `Ask` while one is pending; a checkpoint source yielding after
  its `Ask`).
- The driver checks no answer; the door does (it re-asks or refuses), then delivers.

**Restart:** the core keeps no durable state. A door that restarts calls
`driver.resume(thread_id, request, answer)` with the pending request it kept in its own store
(the A2A task store, the MCP `requestState`).
- For a checkpoint source this calls `source.resume`.
- For a live source with no run held in memory, it gives one `Error(code="lost")`, whose reason
  says the paused run was lost on a restart.

**Rationale:** the ADR requires both styles from the first spec; putting the queue and future in
the driver means a live-pause framework later needs no change to `core`.

**Alternatives:** two driver classes (the doors would branch on the style); making checkpoint
sources look live by awaiting inside a persistent task (loses the restart property); letting
sources emit `AnswerEvent` themselves (each source would have to remember to).

## R11. Thread id

**Decision:** `thread_id(door, owner, context_id)` returns `"<door>:" + sha256(json.dumps([door,
owner, context_id]))` in hex, first 32 characters. The JSON array removes ambiguity (`"a:b"` +
`"c"` versus `"a"` + `"b:c"`); the hash keeps the owner out of logs and storage keys; the door
prefix keeps threads readable by door.

**Alternatives:** string joining with a separator (ambiguous); a UUIDv5 (same idea, less
readable prefix).

## R12. `ToolSpec` from a plain function

**Decision:** a frozen dataclass `ToolSpec(name, description, input_schema, call)` where
`call(args: dict) -> Awaitable[Any]`.
- `tool_from_function(fn)` builds a pydantic model from the signature with `create_model`. Its
  `model_json_schema()` gives `input_schema`, without the top-level `title`. The checked run
  gave `{"type": "object", "properties": {"item": {"type": "string", ...}, "quantity":
  {"type": "integer", "default": 1, ...}, "supplier": {"enum": [...], "type": "string", ...}},
  "required": ["item"]}`, which is flat.
- The call validates the arguments with that model before calling the function: bad arguments
  raise an `InvalidArguments` error listing the keys, and the function never runs.
- A sync function runs in a worker thread (`asyncio.to_thread`).
- The description is the first paragraph of the cleaned docstring. Parameters `*args` or
  `**kwargs` are refused when the tool is made.

**Alternatives:** `pydantic.validate_call` (no separate schema access before the call); a
hand-written type → schema mapping (re-does pydantic's work).

## R13. Fallback text format

**Decision:** deterministic, plain text, no Markdown (R2C-CORE-4):
- question: `[<origin.name> asks: ]<title>` / `<description>` / one line per field `- <header>:
  <text> (<hint>)`, where the hint is `one of: A, B[, or another]`, `one or more of: …`,
  `a number`, `yes/no`, nothing for text, and `optional` appended when `required: false`; on a
  re-ask, the error messages come first;
- approval: `Approval needed[ (<approver_role>)]: <title>` / `<description>` /
  `Reply with one of: allow | edit | deny[ (expires <expires_at>)]`;
- activity: `<label>`, plus `: <detail>` when a `detail` is present (as the examples do).

The examples' texts are hand-written and stay as they are (spec FR-019).

## R14. Async without a new dependency

**Decision:** the core uses `asyncio` only. Tests drive async code with `asyncio.run` inside
plain pytest functions; no `pytest-asyncio` or `anyio` is added to the dev group.

## R15. Core-only and import rules

**Decision:** two checks.
- A test in the normal suite parses every module of the installed `ext_r2c.core` with `ast` and
  allows only imports from the standard library (`sys.stdlib_module_names`), `pydantic`,
  `jsonschema` and `ext_r2c` itself (relative imports included). It also imports
  `ext_r2c.core` in a subprocess and asserts that no module of `a2a`, `mcp`, `langchain` or
  `langgraph` is loaded.
- A CI step installs the wheel alone (no dev group) into a second venv and runs
  `python/tests/core_only.py`. That script imports the core, parses one example of each kind,
  rejects `invalid/question-expires-not-a-date.json` (R3) and asserts that `rfc3339_validator`
  is absent.

## R16. Extras

**Decision:** `[langgraph] = ["langchain>=1.3", "langgraph"]`; `[langchain]` removed; `[a2a]` and
`[mcp]` unchanged. A test reads the installed distribution's metadata (`Provides-Extra`,
`Requires-Dist`) and asserts the three extras and that no `langgraph` requirement names
`ext-r2c[a2a]` or `a2a-sdk`.
