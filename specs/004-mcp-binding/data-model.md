# Data model: MCP binding (`ext_r2c.mcp`)

Phase 1 of [plan.md](plan.md). The R2C models are the core's (spec 002), and the MCP types are
`mcp_types`'. This file names what the door adds:
- the stopping point it seals;
- the state it holds in memory;
- the outcomes of a retry;
- the items a caller reads.

Signatures are in [contracts/mcp-api.md](contracts/mcp-api.md).

## Core

No change. The door uses `mcp_form`, `answer_from_mcp`, `check_answer`, `decision`,
`fallback_text`, `check_size`, `Driver`, `Run`, `thread_id`, `ToolSpec` and
`InvalidArguments` as they are.

## Remote side

### Round and tool call

- A **round** is one `tools/call` request and its result.
- A **tool call** is the chain of rounds that `requestState` links, from the first request (no
  state) to the final result. It is what a task is on A2A (O4): at most one pending request, and
  usage cumulative over its rounds.

### Stopping point

The plaintext `requestState` the door mints. The SDK's `RequestStateBoundary` seals it on the
way out and gives it back unsealed on the retry (research R3). It is compact JSON:

| Field | Type | Meaning |
|---|---|---|
| `v` | `1` | format version |
| `call` | str (uuid4 hex) | the tool call, the same in every round |
| `round` | str (uuid4 hex) | this round's nonce, claimed once (R3) |
| `kind` | `"source"` or `"approve"` | who paused |
| `request` | R2C JSON | the pending `question` or `approval`, as asked (with `errors` on a re-ask) |
| `thread` | str | source only: the thread id |
| `context` | str | source only: the context id |
| `pause` | `"checkpoint"` or `"live"` | source only |
| `usage` | R2C JSON or null | source only: the usage so far |
| `output` | list | source only: the reply text and the artifacts gathered before the ask (R6), as R2C artifact metadata plus content |

An unknown `v` is refused like a lost run. The boundary has already refused anything it did not
seal.

### In memory (lost on a restart)

| Holder | Key | Value | Freed |
|---|---|---|---|
| `SourceTool._runs` | call id | the `Run`, its timer, the gathered output | on the final result, or on expiry (a live run then gets `declined`) |
| `SourceTool._open` | (owner, context) | call id, expiry | with the run, or on expiry |
| `RoundLedger` (default `MemoryLedger`) | round nonce | expiry | after expiry |

### Activation and owner (per round)

| Name | Source | Use |
|---|---|---|
| active | `MCP_KEY in client_capabilities.extensions` | R2C `_meta` on this round's results and notifications |
| form | `client_capabilities.elicitation` present and not URL-only | whether a request can be asked at all |
| owner | `authenticated_principal(ctx)`, else `"anonymous"` | the thread id and the context lock |
| progress token | `ctx.meta["progress_token"]` | whether activities are sent |

### Outcome of a retry

| Outcome | When | Result |
|---|---|---|
| `claimed` | the round's nonce was already used | tool error `This request was already answered.` |
| `missing` | no `inputResponses` entry for the pending key | re-ask, with the refusal sentence first in the message |
| `expired` | `expires_at` before the clock | declined (question) or deny (approval), and the run goes on; "too late" text in the next result |
| `reask` | the derived answer fails `check_answer` (minus role problems) | re-ask, same key and `id`, with `errors` |
| `accepted` | otherwise | `deliver`, `Driver.resume`, or run the tool |
| `lost` | a live run not held | tool error `The paused run was lost (the server restarted); call the tool again.` |

> **Note (2026-11-20, outside review):** `expired` is now checked before `missing`, so an
> expired request is never asked again (it could not be answered). Before the table, a state
> from another owner is refused without claiming its round, and a checkpoint run that is no
> longer held resumes only on a free context (otherwise a `BUSY` tool error, round unclaimed).
> The stopping point carries `owner`.

### Tool call lifecycle (a source tool)

```
first round ──▶ busy context? ──yes──▶ tool error (R2C-ID-2)
     │no
     ▼
  run reads events ──Ask──▶ form? ──no──▶ deliver declined, keep reading
     │                         │yes
     │                         ▼
     │                 input_required (one request, usage beside it)
     │                         │ retry
     │                         ▼
     │                 outcome table above ──accepted──▶ run reads events …
     ▼
  Done ──▶ complete: reply, artifacts, usage, structuredContent {context_id}?
  Error ──▶ complete, isError: true, reason, usage
```

An approval through `approve=` has the same rounds. `accepted` with allow or edit runs the tool
once; deny or decline gives `Not run: …` with `isError: true`.

## Caller side

### Client items

| Item | Fields | From |
|---|---|---|
| `ActivityItem` | `activity: Activity` | a progress notification with R2C `_meta` |
| `ProgressItem` | `message: str \| None`, `progress: float` | a progress notification without it |
| `RequestItem` | `key`, `request: Question \| Approval \| None`, `message`, `requested_schema`, `url: str \| None` | one `inputRequests` entry; `request` from `_meta[key].input_requests[key]` |
| `UsageItem` | `usage: Usage` | `_meta[key]` of the final result, or `_meta[key].usage` of an input-required one |
| `ReplyItem` | `text: str` | the `text` block with `response: true` (or the first text block, guessed, when no block has R2C `_meta`) |
| `ArtifactItem` | `meta: ArtifactMeta \| None`, `presentation`, `block` (the raw content block as a dict), `uri`, `media_type`, `name` | every other content block |
| `ResultItem` | `is_error: bool`, `structured: Any`, `context_id: str \| None` | the end of the call |

- `skipped` counts unknown kinds, invalid R2C objects and unknown activity types (R2C-CORE-5,
  -6).
- Without R2C `_meta`, the presentation is guessed:
  - `resource_link` with an html `mimeType` → `link`;
  - `resource_link` or `resource` → `file`;
  - `text`, `image`, `audio` → `inline`.

### Client state

| Name | Meaning |
|---|---|
| `active` | the server declared the R2C key in `server/discover` |
| `pending` | the `RequestItem`s of the last input-required result, by key |
| `context_id` | the last `structuredContent.context_id` seen |
| the open call | tool name, arguments and `requestState` of the paused call, for the next round |
