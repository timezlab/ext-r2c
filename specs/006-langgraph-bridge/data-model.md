# Data model: LangGraph bridge (`ext_r2c.bridges.langgraph`)

Phase 1 of [plan.md](plan.md). This file names what the bridge holds in memory and the mappings it
applies. The public signatures are in [contracts/langgraph-api.md](contracts/langgraph-api.md); the
pause and stream mappings, row by row, are in [contracts/pause-mapping.md](contracts/pause-mapping.md).
The reasons are in [research.md](research.md).

## Core and the standard

- **Core:** one class added, `PauseLost(Exception)` in `ext_r2c.core.source`, exported from
  `ext_r2c.core`; `Driver._pump` ends the run `Error("lost", ...)` when a source raises it (R13).
  Nothing else in the core changes. Every other type below is the core's own.
- **Standard:** nothing. No schema, no example, no rule.
- **The graph:** nothing. The bridge reads the graph's stream, its checkpointer and its input schema,
  and writes to the thread only through `astream` (a run or a resume) and `aupdate_state` (the
  settle of D9).

## What the bridge holds

### `LangGraphAgent`

| Field | Type | Meaning |
|---|---|---|
| `card` | `CardInfo` | the argument, or `CardInfo(graph.name, "A LangGraph agent served through R2C.", "0.0.0")` |
| `pause` | `"checkpoint"` | fixed |
| `_graph` | compiled graph | checked at construction (R2) |
| `_reasoning` | bool | the option; default off |
| `_expose` | frozenset of str | tool names whose `args` and `detail` may be shown; default empty |
| `_batches` | bounded map | the decisions of batched interrupts in progress (below) |
| `_tools_by_name` | mapping or `None` | the tool node's tools of a `create_agent` graph, read once at construction, used only to find an `edit` schema (R16) |

Nothing else survives a leg. The agent holds no run, no task, no stopping point.

### Wrap check (R2)

In this order, each failure a clear message that names the missing piece:

| Check | Error |
|---|---|
| a compiled graph (has `astream`, `aget_state`) | `TypeError`; for an uncompiled `StateGraph` the message says to call `.compile(checkpointer=...)` |
| `graph.checkpointer` is a `BaseCheckpointSaver` | `ValueError` (`None`, `True` and `False` are refused) |
| `"messages"` in `graph.get_input_jsonschema()["properties"]` | `ValueError`, naming D1 |

An `InMemorySaver` passes and gives one `UserWarning` per wrap (D11).

### Pause (classified from one pending interrupt)

Built after a leg, from `aget_state(config).interrupts`, by the shape of `interrupt.value` (R8). It
is a value object; it is rebuilt on every `resume` and never stored.

| Field | Type | Meaning |
|---|---|---|
| `kind` | one of `tool_call`, `batch_call`, `own_request`, `fallback`, `input_required` | how the payload was read |
| `interrupt_id` | str | LangGraph's id for the interrupt (empty for `input_required`) |
| `request` | `Question` or `Approval` | what the caller is asked; its `id` is the request id below |
| `tool_name` | str or `None` | the gated call's tool |
| `tool_call_id` | str or `None` | the gated call's id (per_call) |
| `position` | int or `None` | the call's position in a batch |
| `batch_size` | int or `None` | number of calls in the batch |
| `allowed` | frozenset of str | the graph's own decision names the call accepts (`approve`, `edit`, `reject`, `respond`) |
| `args_schema` | dict or `None` | the tool's argument schema, only when found (R16) |
| `respond_only` | bool | the call allows only `respond`: the request is a question |

`kind` and what the graph gets back:

| kind | Asked as | Resume value |
|---|---|---|
| `tool_call` | `Approval` (or a `Question` when `respond_only`) | one decision mapping |
| `batch_call` | `Approval` per call, one at a time | none until the batch is complete, then `{"decisions": [...]}` |
| `own_request` | the object itself | its `value` mapping (a `Question`), or its decision mapping (an `Approval`) |
| `fallback` | a one-field `Question` | the answered text, or `None` when declined |
| `input_required` | a one-field `Question`, `answer_by` caller | none: the answer is a new human message |

### Request ids (R8, FR-015)

| Request | Id |
|---|---|
| a `per_call` approval, a `respond_only` question, a fallback question | `lg-<interrupt id>` |
| call `n` of a `batched` interrupt (0-based) | `lg-<interrupt id>-<n>` |
| a hand-written valid R2C request | its own `id` |
| the `input_required` question | `lg-ir-<id of the turn's last AI message>` |

An interrupt id is stable across a restart on the same checkpointer; so are all of these. The
answer's `id` is matched against the pending set rebuilt from the checkpointer; no match is
`PauseLost`.

### Batch record (R10, D8)

| Field | Type | Meaning |
|---|---|---|
| key | `(thread id, interrupt id)` | one batched interrupt on one thread |
| `size` | int | calls in the batch |
| `decisions` | dict `position → graph decision` | what has been given so far |

Operations: record a decision; `complete()` is `len(decisions) == size`; `next_open()` is the lowest
position with no decision; `drop()` on completion, on a settle (D9) and on a lost pause. The map holds
at most 1024 records; the oldest is dropped first. It is the only state the agent keeps (the
bridge's alone: a restart empties it, and the batch is then asked again from its first call).

### Leg (one call of `astream`)

| Part | Meaning |
|---|---|
| `config` | `{"configurable": {"thread_id": ctx.thread_id}, "callbacks": [handler]}`, built per leg |
| producer task | iterates `astream(input, config, stream_mode=["messages", "updates"], version="v2")` and puts each part, or the exception that ended it, in the queue |
| handler | `AsyncCallbackHandler` with `run_inline = True`; puts tool events in the same queue; keeps the hidden message ids |
| queue | `asyncio.Queue`, unbounded; items are stream parts, `ToolStarted`, `ToolEnded`, `ToolFailed`, a `Failure` or the end marker |
| consumer | the `run` or `resume` generator; the only reader; its `finally` cancels and awaits the producer |

Leg inputs: `run` sends one `HumanMessage` (or, on an `input_required` answer, the answer as the
next `HumanMessage`); `resume` sends `Command(resume={interrupt id: value})`.

### Handler state (per leg)

| Field | Meaning |
|---|---|
| `started` | `tool_call_id → (monotonic start, tool name)` for tools whose body is running |
| `hidden` | message ids produced by model runs tagged `nostream` (from `on_chat_model_start` tags and `on_llm_end`) |

A `GraphBubbleUp` in `on_tool_error` is not a failure: the entry stays in `started` and the
activity stays `running` (R4).

### Reply state (per leg)

| Field | Meaning |
|---|---|
| `held` | the newest piece of reply text not yet sent, with its message id |
| `last_msg_id` | the message id of the last piece sent, for the paragraph break |
| `json_hold` | text of a message whose first non-blank character is `{`, kept until its node update, only when the graph has a `structured_response` channel |
| `sent_any` | whether this turn has sent reply text (read from the checkpoint at the end, with the same predicate, when the leg did not see it) |

### Reasoning state (per leg, only when the option is on)

One buffer per message id; the id of the activity is `reasoning-<message id>`. The buffer leaves
at a sentence end or a newline when it holds at least 40 characters, at a space near 400, and always
at the message's end, at a pause, at the turn's end and just before the message's first reply text.

### Structured reply (per leg)

The `structured_response` that this leg's own `updates` carried, normalised (R12): pydantic by
`model_dump()`, a dataclass by `asdict`, a mapping as it is, an `Enum` by its value; anything else
is ignored. Only the pair `status` and `message` is read.

## Mappings

### Graph events → run events

| Source | Run event |
|---|---|
| `messages` part: `AIMessage` or `AIMessageChunk` text, id not hidden | `ReplyChunk(text, last=False)` through the hold-one rule; the last piece of a turn is `last=True` |
| `messages` part: `ToolMessage`, `HumanMessage` | nothing |
| `messages` chunk: standard `reasoning` block, option on | `ActivityEvent(Activity(id="reasoning-<id>", type="reasoning", label="Thinking", delta=...))` |
| `updates` part of the model node: a completed message with file blocks | `ArtifactEvent` per block (below) |
| `on_tool_start` | `ActivityEvent(Activity(id=<tool_call_id>, type="tool", label=<name>, name=<name>, state="running"))` |
| `on_tool_end` | the same id, `state="done"`, or `"failed"` when `status="error"`; `duration_ms` |
| `on_tool_error` (not `GraphBubbleUp`) | the same id, `state="failed"`, `duration_ms`; then the stream raises |
| an exception out of the stream | each activity still `running` closed `failed`; then the exception goes on, and the driver ends the run `Error("failed")` |
| end of a turn | `UsageEvent` (once), then the leg ends; the driver emits `Done` |
| end of a leg with a pending interrupt | the held reply piece with `last=False`, then `Ask`, then the leg ends |

`args` is the call's input mapping and `detail` the result's text (or a failure's message) cut at
2000 characters, both only for a tool in the exposed set (R4).

### Content block → artifact (R6)

| Block | Result |
|---|---|
| `image`, `audio`, `video`, `file` with `base64` | `BytesContent(data, media_type=<mime_type>, name=...)` |
| the same with `url` | `UrlContent(url, media_type=<mime_type>, name=...)` |
| no data, a hosted id only, invalid base64, `non_standard` | skipped; logged at debug |

`ArtifactEvent(id="<message id>-<block index>", meta=ArtifactMeta(presentation="file"),
parts=(content,), name=<the block's filename or name when a string>)`. Read from completed
messages only.

### Run input → message (R18)

| `RunInput` | `HumanMessage` |
|---|---|
| `text` only | `content=text` |
| with parts | `content_blocks`: a `text` block, then one block per part: `image`, `audio` or `video` by the top level of the media type, any other `file`; bytes as `base64`, a URL as `url`; always with `mime_type` |

Nothing is read, converted or dropped.

### Usage (R7)

Over the checkpoint's messages after the last `HumanMessage`: sum of `usage_metadata.input_tokens`
and `output_tokens` of the AI messages that report them, absent when none does; `model` is the last
non-empty `response_metadata["model_name"]`; no `cost`, no `duration_ms`. Sent once, after the last
reply chunk and before the terminal event; not at a pause.

## States of a pause

```text
pending ──ask──▶ asked ──answer──▶ checked ──ok──▶ resumed (per_call, own request, fallback)
                   │                  │
                   │                  └─ batched, not complete ──▶ recorded ──ask next──▶ asked
                   │                  └─ refused (the graph would refuse it) ──▶ run ends failed;
                   │                                                              the pause is still pending
                   ├─ no pending interrupt for the id ───────────▶ PauseLost (the run ends lost)
                   └─ a new input arrives ──────────▶ settled by a state update (D9), batch dropped
```

## Tools (R16)

`tool_from_langchain(tool)` returns a core `ToolSpec(name, description, input_schema, call)`:

| Part | From |
|---|---|
| `name`, `description` | the tool |
| `input_schema` | a copy of `tool.tool_call_schema` as JSON Schema, without `title` |
| `call` | validates the arguments with `jsonschema`, raises `InvalidArguments` with one `Problem("invalid_args", key, message)` per breaking key, then awaits `tool.ainvoke(dict(args))` |
| refusal at conversion | the input schema has an injected argument (`InjectedState`, `InjectedStore`, `ToolRuntime`, `InjectedToolCallId`, `InjectedToolArg`): `TypeError` naming the tool and the argument |

## Limits and constants

| Name | Value | Where chosen |
|---|---|---|
| tool `detail` cut | 2000 characters | plan (the standard sets none) |
| fallback question title | 200 characters | plan |
| fallback JSON text | 2000 characters, `default=str` | plan |
| reasoning pieces | at least 40 characters at a sentence end or newline; a space near 400 | plan |
| batch records kept | 1024, oldest dropped | plan |
| content size | none in the bridge; the doors refuse by `Limits` (5 MiB message, 50 MiB file) | R15 |
| exception text | not bounded by the bridge | spec, Assumptions |

## Test-only types

| Name | File | Meaning |
|---|---|---|
| scripted chat model | `tests/langgraph_models.py` | a `BaseChatModel` with `_generate` and `_astream`; a pure function of the message history; options for strict (rejects a tool call with no answer), streaming off, `nostream`, a gate after `k` tokens, usage metadata |
| graph builders, `restart(path)` | `tests/langgraph_graphs.py` | graphs of the stories; a new graph and a new agent over the same SQLite file |
| suite wrapper | `tests/langgraph_suite_source.py` | records `answers`, builds a graph whose tool raises for `fail_after_ask`, yields a second `Ask` for `double_ask` (D3) |
