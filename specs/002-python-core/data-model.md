# Data model: Python core (`ext_r2c.core`)

Phase 1 of [plan.md](plan.md). The wire shapes are the schemas in `standard/v1/schema/`; this
file names the Python types that carry them and the core's own types (run events, sources,
tools). Python signatures are in [contracts/core-api.md](contracts/core-api.md).

## Wire models (one per kind, R1, R2)

Every model is open (`extra="allow"`), dumps only what was set, and always dumps `kind`.

| Model | Kind | Fields (required in **bold**) | Checks beyond the schema |
|---|---|---|---|
| `Question` | `question` | **id**, **title**, **answer_by** (`AnswerBy`), **fields** (`list[Field]`), description, expires_at, origin, errors | unique field keys, unique option labels per field (R2C-QUESTION-4) |
| `Approval` | `approval` | **id**, **title**, **answer_by** (`ApproverBy`), **subject** (`Subject`), **decisions**, description, expires_at, origin, errors | — |
| `Answer` | `answer` | **id**, **outcome**, **answered_by** (`AnsweredBy`), value, note | — |
| `ArtifactMeta` | `artifact` | **presentation**, state, response | — |
| `Activity` | `activity` | **id**, **type** (open string), **label**, state, name, args, detail, duration_ms, parent_id, delta | — |
| `Usage` | `usage` | input_tokens, output_tokens, duration_ms, cost (`Cost`), model | — |

Shared parts:

| Model | Fields |
|---|---|
| `Field` | **key**, **header**, **text**, **type** (`one` · `many` · `text` · `number` · `bool`), options (`list[Option]`), other (read default `True`), required (read default `True`) |
| `Option` | **label**, description |
| `AnswerBy` | **role** (`person` · `caller`) |
| `ApproverBy` | **role** (`person` · `approver`), approver_role |
| `AnsweredBy` | **role** (`person` · `approver` · `policy` · `caller`), label |
| `Subject` | **type** (open string), **name**, args, args_schema, target |
| `Origin` | **name**, **url** |
| `ErrorItem` | key, **message** |
| `Cost` | **amount** (`int | float`), **currency** |

- Closed enums are `Literal` types and the schema rejects other values (R2C-VERSION-3).
  `Activity.type` and `Subject.type` are open strings (R2C-CORE-6, §6 subject table).
- `expires_at` is a string. `Request.expires()` parses it into an aware `datetime`.
- `Request` = `Question | Approval`. `R2CObject` = the six models.

### Parsing

`parse(obj: dict) -> R2CObject | Unknown`:

1. `kind` missing or not a string → `InvalidObject` (R2C-CORE-7).
2. `kind` not one of the six → `Unknown(kind, data)`, never an error (R2C-CORE-5).
3. Validate against the packaged schema with the core's format checker (R3) → `InvalidObject`
   listing `(pointer, message)` for every error.
4. Checks beyond the schema (table above) → `InvalidObject`.
5. Build the model.

`to_json(model) -> dict` dumps and validates the result against the schema (R2); an object built
in code that breaks its schema raises `InvalidObject` instead of reaching the wire.

## Core types

### `Problem` (R6)

| Field | Meaning |
|---|---|
| `code` | `too_large` · `invalid_answer` · `wrong_id` · `caller_on_approval` · `expired` · `invalid_value` · `not_offered` · `invalid_args` |
| `key` | field key or argument name, or `None` |
| `message` | short English sentence for a person |

`as_error_item()` → `ErrorItem(key, message)`.

### `Limits` (FR-017)

| Field | Default |
|---|---|
| `message_bytes` | 5 × 2^20 (content inside a message, and a whole answer) |
| `file_bytes` | 50 × 2^20 (a file fetched by `url`; checked by callers that fetch) |

### `McpForm` (R7)

| Field | Meaning |
|---|---|
| `requested_schema` | the flat `requestedSchema` |
| `decisions` | for an approval, the decisions offered after `edit` may have been dropped; `None` for a question |

`NotAskableOverMcp` is raised when an approval has no decision left (FR-011).

### Run events (FR-020)

Frozen dataclasses. None holds an A2A or MCP type.

| Event | Fields | Meaning |
|---|---|---|
| `ReplyChunk` | `text` | the next piece of the reply; chunks concatenate in order |
| `ActivityEvent` | `activity: Activity` | a progress record (an update repeats the `id`) |
| `Ask` | `request: Question \| Approval` | the run waits for an answer |
| `AnswerEvent` | `answer: Answer` | the answer delivered to the run (emitted by the driver) |
| `ArtifactEvent` | `id`, `meta: ArtifactMeta`, `parts: tuple[Content, ...]`, `name`, `description` | a file, inline content or a live page; the same `id` again is a new version or update |
| `UsageEvent` | `usage: Usage` | cumulative usage so far |
| `Done` | — | the run finished |
| `Error` | `code`, `reason` | the run ended without finishing: `failed`, `cancelled`, `lost`, `protocol` |

`Content` = `TextContent(text, media_type="text/plain")` · `BytesContent(data: bytes,
media_type, name)` · `UrlContent(url, media_type, name)`.

**Sequence rules** (checked by the driver, FR-020, FR-024):
- exactly one `Done` or `Error`, and nothing after it;
- at most one unanswered `Ask`; the next `Ask` only after the `AnswerEvent` for the previous one;
- a checkpoint source yields nothing after its `Ask` in the same iterator.

A break of these rules ends the run with `Error(code="protocol")`.

### Source side (FR-021, FR-022)

| Type | Fields |
|---|---|
| `CardInfo` | `name`, `description`, `version`, `skills: tuple[CardSkill, ...]` |
| `CardSkill` | `id`, `name`, `description`, `tags`, `examples` |
| `RunInput` | `text`, `parts: tuple[Content, ...]` |
| `RunContext` | `thread_id`, `cancelled` (an `asyncio.Event`), `ask(request) -> Answer` (live sources only; a checkpoint source calling it gets `Error(code="protocol")`) |
| `AgentSource` | `card: CardInfo`, `pause: "checkpoint" \| "live"`, `run(input, ctx)`, `resume(answer, ctx)` (checkpoint only) |

### Driver (FR-023, FR-024, R10)

State of one run:

```
            start                 Ask                    deliver(answer)
  (none) ─────────▶ running ─────────────▶ paused ─────────────────────▶ running
                       │                      │
                       │ source ends          │ cancel
                       ▼                      ▼
                     Done            Error(cancelled)
          source raises → Error(failed)    live run not held → Error(lost)
```

- A live run that is cancelled while paused gets a `declined` answer from `ctx.ask`
  (`answered_by.role = policy`, `note` "The run was cancelled."). The driver then ends the run
  with `Error(cancelled)`, whatever the source does next, and gives the source a few seconds to
  finish before cancelling its task.
- A checkpoint run that is cancelled while paused is never resumed.

### Thread id (FR-025, R11)

`thread_id(door, owner, context_id) -> str`. Equal inputs give equal ids. Any change to one of
the three gives a different id.

### `ToolSpec` (FR-027, FR-028, R12)

| Field | Meaning |
|---|---|
| `name` | the tool name (default: the function name) |
| `description` | first docstring paragraph (default) |
| `input_schema` | JSON Schema of the arguments |
| `call(args) -> Awaitable[Any]` | checks `args` against the input schema, then runs the function |

`InvalidArguments(problems: list[Problem])` is raised before the function runs.
