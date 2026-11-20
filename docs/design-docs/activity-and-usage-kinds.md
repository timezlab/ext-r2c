# Structured activity, usage, and a streamed response in v1

**Status:** accepted, 2026-11-20. Supersedes the "No `plan` / `step`" part of
[four kinds](four-kinds.md); v1 now has six kinds.

## Context

The first decision kept progress out of R2C: a remote's `working` status text (A2A) or
`notifications/progress` `message` (MCP) was enough. Checked against what a caller's chat UI
actually renders, it is not. Such a UI typically consumes a neutral event stream of about
seven events: text tokens, reasoning, a tool call with `running` / `done` (name, args, a
short output, duration), usage (tokens, cost, time), a question, an error, and done. Against
A2A's standard stream (`task`, `message`, `status_update`, `artifact_update`):

| UI event | A2A, without R2C | MCP |
|---|---|---|
| text tokens | `artifact_update` with `append` / `last_chunk`: the only chunked channel in A2A (a `message` is always whole) | none: a tool result arrives once |
| question / approval | R2C `question` / `approval` | elicitation (MRTR) |
| error, done | task state `failed`, `completed` | error result, tool result |
| tool running / done | free text only | free text only (`notifications/progress` `message`) |
| reasoning | none | none |
| usage | none | none |

The last three rows cannot be told apart from free text, so a caller can show a line, not a
tool timeline, a reasoning panel, or a cost. A2A also has no notion of "the reply": the chat
answer and a generated spreadsheet are both artifacts.

## Decision

### 1. New kind `activity`

One kind for what the remote is doing, with a `type`:

```jsonc
{ "kind": "activity",
  "id": "string",                  // required; stable across updates of one activity (a tool call id)
  "type": "tool" | "step" | "reasoning",
  "state": "running" | "done" | "failed",   // tool and step
  "label": "string",               // one line for the reader; the text fallback
  "name": "string?",               // tool: the tool's name
  "args": {}?,                     // tool: only when the remote exposes that tool's args
  "detail": "string?",             // short summary of the output or the failure, never the whole output
  "duration_ms": 0,                // optional, on done / failed
  "parent_id": "string?",          // nesting (a sub-agent's steps under its own activity)
  "delta": "string?" }             // reasoning: text appended to the activity with this id
```

The three types:

- `tool`: one tool call, from start to result.
- `step`: a phase of work that is **not** a single tool call: a graph node (a pipeline of
  `retrieve` → `rank` → `write`), a sub-agent or handoff (its tool calls nest under it through
  `parent_id`), or a progress line the remote reports itself ("Validating the input"). It
  replaces the free-text progress of the first design.
- `reasoning`: the model's reasoning text, only when the remote's owner allows it.

Placement:

- **A2A:** a `status_update` in state `working`; the message carries a TextPart (`label`) and a
  DataPart with the `activity` (marked by `metadata[uri] = {}`, as for `question`). One activity
  per event. A client that did not activate R2C gets the TextPart only, and never reasoning.
- **MCP:** `notifications/progress` with `message` = `label` and the `activity` in
  `_meta["io.github.timezlab/r2c"]`; only when the client sent a `progressToken`.
- **Reasoning is the remote's decision.** A remote MAY send `type: "reasoning"`; the adapter
  sends none unless the remote's owner turns it on. It never carries provider signatures or
  encrypted reasoning. Deltas SHOULD be coalesced rather than sent one token per event.
- **Args are opt-in per tool.** By default a tool activity carries `name` and `state` only;
  args and output may hold the remote's internal data.

### 2. New kind `usage`

```jsonc
{ "kind": "usage",
  "input_tokens": 0, "output_tokens": 0,          // all fields optional, at least one present
  "duration_ms": 0,
  "cost": { "amount": 0.0, "currency": "USD" },   // ISO 4217
  "model": "string?" }
```

- Cumulative for the task: a later `usage` replaces an earlier one.
- **A2A:** a DataPart in a status message: at the latest in the terminal one (`completed`,
  `failed`, `canceled`), and MAY also be in `input-required` (a paused task has spent tokens).
  `GetTask` returns it with the task's status.
- **MCP:** `_meta["io.github.timezlab/r2c"]` on the tool result (result level, not content).
- It is the remote's claim: a caller shows it and MUST NOT bill from it. A missing field means
  unknown, never zero.

### 3. The reply is one streamed `inline` artifact

A task's reply text is **one** `artifact` with `presentation: "inline"` and `response: true` (at
most one per task). It is streamed: the first chunk `append: false`, the next ones
`append: true`, the last `last_chunk: true`. It holds **all** the text the model writes during
the task, in order, including the short narration between tool calls ("Let me read the
file."), exactly as a chat UI shows it. Files stay separate artifacts (`presentation: "file"`,
one per file, not streamed). Activities and artifact chunks interleave in arrival order, and
the caller renders them in that order. MCP has no streaming: the tool result's text content is
the whole reply.

## Alternatives

- **Keep progress as text** (the first decision). Rejected: a caller cannot build a tool
  timeline, a reasoning panel or a cost display from free text.
- **Separate kinds `tool`, `step`, `reasoning`.** Three schemas for one idea (something the
  remote is doing, with a lifecycle); one kind with `type` is smaller and nests with
  `parent_id`.
- **AG-UI events** (`RUN_STARTED`, `TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`…). A third protocol
  with its own endpoint, not the A2A or MCP stream.
- **Emit a caller's own wire format** (for example OpenAI Responses frames). Ties the standard to
  one client; the caller maps R2C events to its own vocabulary instead.
- **Reply narration as `activity` text, only the final answer in the artifact.** A cleaner
  product for a caller agent, but while tokens stream the adapter cannot know whether the
  current model message ends in a tool call; it would have to buffer each message (the final
  answer stops streaming) or send it twice.
- **`usage` later.** Rejected by the maintainer: callers already show tokens, time and cost per
  turn, and a remote's share belongs in that display.

## Consequences

- **Better:** a caller can render a remote's run the way it renders its own: streamed reply,
  tool timeline with durations and nesting, optional reasoning, usage. Clients that did not
  activate R2C still get text and standard artifacts.
- **Worse:** six kinds to specify, validate and test instead of four. A remote that wants this
  must use the adapter (plain status text still works). The reply artifact includes the
  narration, so a caller agent receives it too. MCP shows activity and usage but never streams
  the reply.
- **Must now be true:**
  - Activity and usage are display data from the remote: the caller escapes them, never treats
    them as instructions, and never bills from `usage`.
  - No reasoning, and no tool args, leave a remote unless its owner turned them on.
  - Clients still ignore unknown kinds, unknown `activity.type` values and unknown fields.
  - A remote's status stream must actually arrive while the remote runs (a proxy that buffers
    SSE defeats streaming); a deployment checks this before relying on it.
