# Contract: pause mapping and stream mapping

Phase 1 of [plan.md](../plan.md). This is the table SC-012 is checked against: for each kind of
pause of a graph, what the caller sees and what the graph gets back; and, for each thing a graph
streams, which run event it becomes. The reasons are in [research.md](../research.md) (R4 to R14);
the records are in [data-model.md](../data-model.md).

Words used: **graph decision** is what `HumanInTheLoopMiddleware` reads (`approve`, `edit`,
`reject`, `respond`); **R2C decision** is `allow`, `edit`, `deny`.

## 1. A pause: what the caller sees, what the graph gets

| # | The graph pauses with | The caller sees | The graph gets back |
|---|---|---|---|
| 1 | a `per_call` middleware interrupt (`type: "tool_approval"`), one per gated call | an `Approval` for that call, one at a time, in the model's tool-call order | on `allow`: `{"type": "approve"}`; on `deny`: `{"type": "reject", "message": <reason>}` (no message when there is no reason); on `edit`: `{"type": "edit", "edited_action": {"name": <the call's tool>, "args": <the answer's args>}}`; resumed by the interrupt's id, the others stay pending |
| 2 | a `batched` middleware interrupt (`action_requests`, `review_configs`) | one `Approval` per call, one at a time, in position order; nothing runs yet | nothing until every call has a decision; then one resume `{"decisions": [d0, d1, ...]}` in position order, each as in row 1 |
| 3 | row 1 or 2 where a call allows only `respond` | a `Question` with one text field (`reply`), `answer_by` person | `{"type": "respond", "message": <the text>}` |
| 4 | a hand-written `interrupt(value)` where `value` is a valid R2C `question` | that question, as it is, with its own id | the answer's `value` mapping (`{field key: value}`) |
| 5 | a hand-written `interrupt(value)` where `value` is a valid R2C `approval` for a person or an approver | that approval, as it is, with its own id | the answer's `value` mapping (`{"decision": ..., "reason"?: ..., "args"?: ...}`) |
| 6 | a hand-written `interrupt(value)` where `value` is an approval addressed to the caller | a `Question` for a person with one text field, as in row 7 (it is **never** asked as an approval, V) | the answered text |
| 7 | a hand-written `interrupt(value)` with anything else (a string, a mapping that is not R2C, a list, a number) | a `Question` for a person: one text field (`answer`); a string is the title (cut at 200 characters; an empty one becomes "The agent needs input"), any other value is the title "The agent needs input" with the value as bounded JSON text (2000 characters) in the description | the answered text |
| 8 | the end of a turn whose final state holds a structured reply with `status: "input_required"` and a non-empty `message` | a `Question` for the caller (`answer_by` caller), one text field (`answer`), the message as its title (first line, 200 characters; the whole message in the description when longer); the structured JSON is not streamed as reply | **no resume**: the answer is sent as the next human message of the same thread |
| 9 | several interrupts pending at once (parallel nodes or a `per_call` turn) | one at a time: tool approvals in the model's tool-call order, then the others in the order LangGraph lists them; the leg ends right after each `Ask` | each answer resumes only its own interrupt, by id |
| 10 | two `interrupt()` calls in a row in one node | the first; after its answer the node restarts, the second is then pending and is asked next | each answer resumes the interrupt that is pending |

Notes:
- **Only the checkpointer's pending list is asked** (FR-014); the `__interrupt__` part of the stream
  is never used. After a restart the same pause gives the same request ids (FR-015).
- **`answer_by` is never `caller` for an approval** (V): rows 1, 2, 5 and 6 are decided by shape and
  by the core's own validation, and a test walks every path that yields an approval (SC-006).
- Row 1 and 2's approval is `Subject(type="tool_call", name=<tool>, args=<the model's args>)`,
  title `Approve <tool>?`, the middleware's `description`, `answer_by` person, `decisions` in the
  order `allow`, `edit`, `deny` restricted to what the call allows; `args_schema` is set, and `edit`
  is offered, only when the tool's schema is found (R16).
- A call whose allowed graph decisions leave nothing to offer (for example only `edit` and no schema)
  ends the run `failed` before any ask, with a reason that says so.
- A `per_call` payload with no readable `response_schema` ends the run `failed` before any ask
  (plan, point 5).

## 2. An answer that cannot be applied

| Case | What happens | The pause afterwards |
|---|---|---|
| the answer's `id` matches no pending interrupt (in-memory saver after a restart, a pruned thread, an answer already applied) | `PauseLost`; the run ends `Error("lost")`; the graph is not started | none to resume |
| the answer's `id` is the `input_required` question's, and the turn has moved on (a human message follows, or the reply no longer says `input_required`) | `PauseLost` | none |
| a decision the call does not allow, an `edit` the call cannot take, a batch decision with a wrong count | `ValueError` with the readable problems; the run ends `failed`; the graph is not touched | still pending: a correct answer resumes it, in both modes (SC-005) |
| `declined` for an approval (R2C-ANSWER-3) | the graph decision `reject`, with `note` as the message when present | resumed |
| `declined` for an approval whose call does not allow `reject` | the run ends `failed`: the reason says the call cannot be rejected; the call does not run | still pending |
| `declined` for a question of rows 3 (respond-only) | the run ends `failed` as above: `reject` is not allowed | still pending |
| `declined` for a question of rows 4, 6, 7 | resumed with `None` (the graph's "no answer") | resumed |
| `declined` for the `input_required` question (plan, point 4) | the run ends `done`; the graph is not called | none |
| the answer to a `batched` call that is not the last | recorded in memory; the next undecided call is asked; no graph call | the batch is pending until complete |
| an answer for a batch call when the bridge has no record (a restart in between) | recorded; the first undecided call is asked, so the batch starts again from its first call (FR-019) | pending |

Checks before the graph, in this order: the id is pending; the core's `check_answer` against the
request the bridge would have asked (the door did the same, so this only catches a caller that
skipped the door, as the suite's driver does); the graph-side rules (decision allowed, count,
tool name for an edit).

## 3. A new input while an approval is pending (D9, FR-007)

When a run starts and the thread has a pending **middleware** approval (the shapes of rows 1 and 2),
before the input is sent the bridge appends to the saved state, in one `aupdate_state` with no
`as_node`:
- the `ToolMessage`s that finished `per_call` tool tasks of the unfinished step already produced
  (read from the tasks' results), and
- for each tool call of the last AI message that has no `ToolMessage`: a `ToolMessage` with
  `status="error"`, the tool's name and call id, and the content "The call was withdrawn: a new
  message came before it was approved."

The batch record of the thread is dropped. Other kinds of pending interrupt (rows 4 to 7) are left as
LangGraph leaves them: the node starts again.

## 4. The stream: what each part becomes

Parts come from `astream(stream_mode=["messages", "updates"])` and from the per-run callback
handler; one queue merges them and the generator yields them in arrival order.

| From | Run event | Rules |
|---|---|---|
| `messages`: text of an `AIMessage` or `AIMessageChunk`, id not hidden | `ReplyChunk(text, last=False)` | hold-one: the newest piece is held and the previous one sent; a blank line (`"\n\n"`) goes before the first piece of a different message when both have text |
| the held piece | `ReplyChunk(text, last=True)` at the end of a turn; `last=False` when the model node's update shows tool calls, when the leg ends in an `Ask`, or when the graph raises | if nothing is held but the turn had reply text, one `ReplyChunk("", last=True)` closes it |
| a message produced by a model run tagged `nostream` | nothing | the handler's hidden ids; usage still counts it |
| text of a message whose first non-blank character is `{`, in a graph with a `structured_response` channel | held until that message's node update; dropped when the structured reply is `input_required`, else sent as reply | prose streams at once |
| `messages`: `ToolMessage`, `HumanMessage` | nothing | |
| `messages`: a standard `reasoning` block, option on | `ActivityEvent(Activity(id="reasoning-<message id>", type="reasoning", label="Thinking", delta=<piece>))`, no `state` | coalesced without timers: at least 40 characters at a sentence end or newline, a space near 400, always at the message's end, at a pause, at the turn's end and before the message's first reply text; only the standard `reasoning` field is read |
| `updates` of the model node: a completed message with an `image`, `audio`, `video` or `file` block with data | `ArtifactEvent(id="<message id>-<index>", meta=ArtifactMeta(presentation="file"), parts=(BytesContent or UrlContent,), name=...)` | no data, invalid base64 or `non_standard`: skipped |
| callback `on_tool_start` | `Activity(id=<tool_call_id>, type="tool", label=<name>, name=<name>, state="running")` | fires only when the tool body runs: a call waiting for approval, or denied, shows nothing |
| callback `on_tool_end` | the same id, `state="done"` (`"failed"` when the `ToolMessage` has `status="error"`), `duration_ms` | |
| callback `on_tool_error` | the same id, `state="failed"`, `duration_ms` | **not** when the error is a `GraphBubbleUp` (a pause inside the tool): the activity stays `running`, and the restarted body reports `running` again |
| tool in the exposed set | `args` (the call's input) and `detail` (the result text, or a failure's message, 2000 characters) | otherwise both absent (R2C-ACTIVITY-6) |
| an exception out of the stream | each activity still `running` is closed `failed`, then the exception goes on | the driver ends the run `Error("failed", str(exc))` |
| end of a turn (no pending interrupt) | `UsageEvent` once, after the last reply chunk and before the terminal event | summed from the checkpoint: the same with or without a restart; no `cost`, no `duration_ms`; a total no message reported is absent |
| end of a leg with a pending interrupt | the reply flush, then `Ask`, then the leg ends | no `UsageEvent` at a pause (D7) |

Order guarantees a door can rely on:
- events of one leg come in the order the graph produced them, except that a tool's `running`
  activity may arrive just before or after the text that preceded it (the stream and the handler are
  two sources); the suite's shape check treats activity as free for that reason (D3);
- `Ask` is always the last event of a leg; `UsageEvent` comes only at the end of a turn and just
  before the terminal event the driver emits;
- the reply's `last=True` chunk comes at most once per turn, and after it only `UsageEvent` follows
  (and, for `input_required`, the `Ask`);
- a reply spans a pause: the A2A door keeps appending to the same artifact `reply` and the MCP door
  keeps gathering the text, so a chunk with `last=False` before a pause and more text after it are one
  reply (R15).
