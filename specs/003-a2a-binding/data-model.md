# Data model: A2A binding (`ext_r2c.a2a`)

Phase 1 of [plan.md](plan.md). The R2C wire models are the core's (spec 002). The A2A types
are a2a-sdk's (`a2a.types`, protobuf). This file names what the door adds: per-task state, the
outcomes of reading an answer, and the items a caller reads. Python signatures are in
[contracts/a2a-api.md](contracts/a2a-api.md).

## Core change

| Type | Change | Why |
|---|---|---|
| `ReplyChunk` | gains `last: bool = False` | the source knows when its reply ends (research R5) |

The change is additive, and no other core type changes.

## Remote side

### Activation (R3)

A request is **active** when its `A2A-Extensions` header lists `ext_r2c.URI`.
- The context builder decides it once per request and stores it in `call_context.state`, under
  a private key.
- The echo middleware reads it from the ASGI scope.

### Task state as the door sees it

The door keeps nothing durable. Everything below is read back from `context.current_task`
(the stored task) on each `execute` call, except the in-memory `Run` (R1).

| Item | Where it comes from | Used for |
|---|---|---|
| pending request | the newest R2C request Part in `status.message`, then `history` (agent messages, newest first), only while the state is input-required (R2) | checking the answer, re-asking, resume after a restart |
| last usage | the newest R2C usage Part in the same places | the next input-required and terminal status (R4) |
| reply artifact started | an artifact with id `reply` in `current_task.artifacts` | `append` on the next reply chunk (R5) |
| thread | `thread_id("a2a", owner_resolver(call_context), context_id)` (R11) | the source's thread |
| run | `SourceExecutor`'s map from task id to `Run`; absent after a restart | `deliver`, or `Driver.resume` when absent |

### Task lifecycle

```
(no task) ──message──▶ open ──[another unfinished task in the context]──▶ REJECTED
                         │
                         ▼
                       WORKING ◀──────────────── answer accepted / expiry outcome
                         │  ├─ activity, reply, artifact (stay WORKING)
                         │  └─ ask ──▶ INPUT_REQUIRED ──message──▶ check
                         │                 ▲                          │
                         │                 └── re-ask / refuse ◀──────┘
                         ├─ Done  ──▶ COMPLETED
                         ├─ Error(failed | lost | protocol) ──▶ FAILED
                         └─ cancel ──▶ CANCELED   (from WORKING or INPUT_REQUIRED)
```

### Outcome of reading a message at input-required (R7, R8, R9)

`R2CTask.take_answer()` returns one of these:

| Value | Meaning | What the helper has already sent |
|---|---|---|
| `Answer` | acceptable, to deliver | nothing |
| `Answer` (declined, role `policy`, note "The request expired.") | the expiry outcome, to deliver | nothing yet; the refusal note goes into the next status |
| `None` | re-asked or refused | the input-required status (the re-ask with `errors`, or the refusal text) |

### Answer routing table

The full table is in [research.md](research.md#r7-answer-handling):
- too large, malformed, or wrong value → re-ask;
- wrong `id`, or several answers for the pending `id` → refuse in text;
- expired → the expiry outcome plus a refusal note;
- `caller_on_approval` → ignored on this side (O8).

## Caller side

### `Item`s a client reads (FR-021)

Each item is a frozen dataclass. The stream yields them in wire order.

| Item | Fields | From |
|---|---|---|
| `TaskItem` | task_id, context_id, state, text | a `Task` event (the first, or a reattach snapshot) |
| `StatusItem` | state, text | a status update's state and joined text Parts |
| `ActivityItem` | activity (`Activity`) | an R2C activity Part |
| `RequestItem` | request (`Question` or `Approval`) | an R2C request Part |
| `UsageItem` | usage (`Usage`) | an R2C usage Part |
| `ReplyItem` | text, last | a chunk of the artifact whose meta has `response: true` |
| `ArtifactItem` | artifact_id, meta (`ArtifactMeta` or `None`), parts (core `Content`), name, append, last | any other artifact update |

- A status update yields one `StatusItem`, then one item per R2C Part, in Part order.
- Unknown kinds, unknown fields and invalid R2C Parts are skipped without error (R2C-CORE-5,
  -6). Every skipped Part is counted on the client (`skipped`), for tests.

### Connection

| Field | Meaning |
|---|---|
| base URL | the card's JSON-RPC interface URL; its origin is the only one `fetch` contacts (R2C-SAFETY-1) |
| `active` | whether the last response echoed the R2C URI |
| task id, context id | from the first `TaskItem`; exposed for the caller to store (R2C-ID-3) |

### `fetch` result (FR-025)

| Value | When |
|---|---|
| `bytes` | `raw` content, or a `url` on the connection's origin, within `Limits.file_bytes` |
| `Link(url, media_type, name)` | a `url` on another origin; nothing is requested |
| `TooLarge(size_or_none)` | content over the limit; reading stops at the limit |
