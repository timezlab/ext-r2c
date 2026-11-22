# Research: LangGraph bridge (`ext_r2c.bridges.langgraph`)

Phase 0 of [plan.md](plan.md). Everything here was checked on 2026-11-22 in a scratch environment
(Python 3.12, no network, no keys) with throwaway scripts that are not committed; the first phase's
spike test (`test_langgraph_spike.py`, phase 1 of the plan's delivery order) turns the facts the
design leans on into pinned tests. Versions: the newest set (`langchain` 1.5.2, `langchain-core` 1.8.4, `langgraph` 1.2.24,
`langgraph-checkpoint` 4.3.2, `langgraph-prebuilt` 1.1.3, `langgraph-checkpoint-sqlite` 3.1.3) for
behaviour, and the oldest set the extra will allow (R1) for the features the bridge needs. The only
fake is a scripted chat model (R17). Items marked **to pin** are facts the spike test must turn into
a failing-first check; none changes the design if it holds.

The spec left these open for the plan, and this file settles them: the bounds of the extra (R1),
how a running tool is told from a paused one (R3, R4: D5), how a new input settles a pause (R11:
D9), how `input_required` is read (R12: D10), how the allowed decisions of a `per_call` interrupt
are read (R9), the order of parallel interrupts (R14), the door limits on artifacts (R15) and the
file layout (R18). Five points were not in the approved spec and are listed in
[plan.md](plan.md#needs-the-maintainer) for the maintainer.

## R1. Bounds of the `[langgraph]` extra, and the dev group

- **Finding**
  - `HumanInTheLoopMiddleware(interrupt_mode=...)`, the switch between `batched` and `per_call`,
    first exists in **langchain 1.4.6**. Versions up to 1.4.5 raise `TypeError` on the keyword;
    1.4.6 to 1.4.10 and the newest accept it.
  - langchain 1.4.6 itself requires `langchain-core>=1.6.10,<2` and `langgraph>=1.2.12,<1.3.0`.
  - The lowest set that those pins allow (`langchain` 1.4.6, `langchain-core` 1.6.10, `langgraph`
    1.2.12, with the newest transitives `langgraph-prebuilt` 1.1.3 and `langgraph-checkpoint`
    4.3.2) passes every feature check the design needs: typed stream parts, interrupt ids and the
    response schema, `tool_call_id` in the callbacks, task results in the state, id-keyed resume in
    both middleware modes, the batched payload, `content_blocks`, and the settle by state update
    in both modes. `--resolution lowest` (every transitive at its oldest) fails on an unrelated
    package (`sniffio` 0.0.0 has no build), so only `lowest-direct` was used.
  - Release dates: langchain 1.4.6 on 2026-10-14, langchain-core 1.6.10 on 2026-10-12, langgraph
    1.2.12 on 2026-09-21: all older than two weeks.
  - The SQLite checkpointer (dev group only): `langgraph-checkpoint-sqlite` 3.1.3 (2026-10-30)
    requires `langgraph-checkpoint>=4.3.1,<5`; 3.0.0 requires `<4` and does not install beside the
    versions above. It brings `aiosqlite`; the bridge uses only async methods, so the tests use
    `AsyncSqliteSaver` (the sync `SqliteSaver` refuses async calls).
  - The constitution's Technical Constraints say `langchain>=1.3` + `langgraph`. Both bounds below
    are tighter, so that sentence is stale once the extra changes.
  - None of the packages has a malicious-package advisory on OSV (checked 2026-11-22; T001 repeats
    it on the day the dependency is added, as spec 005 did for PyYAML).
- **Decision**
  - `langgraph = ["langchain>=1.4.6,<2", "langchain-core>=1.6.10,<2", "langgraph>=1.2.12,<2"]`.
    `langchain-core` is named because the bridge imports it directly; `langchain` is named because
    the constitution names it and because the payloads the bridge reads are
    `HumanInTheLoopMiddleware`'s (the bridge itself imports only `langchain_core` and
    `langgraph`, so a graph built by hand from `langgraph` alone works too). No checkpointer in the
    extra (FR-027): the owner brings theirs.
  - Dev group: the same three bounds, and `langgraph-checkpoint-sqlite>=3.1.3,<4`.
  - The constitution's Technical Constraints line gets a PATCH amendment (1.1.1 to 1.1.2) with a
    Sync Impact Report, in the same commit as `pyproject.toml` (Governance). The first task re-runs
    the OSV vet and the lowest-direct check; there is no CI job for the lowest set.
  - The wheel's `test_extras` changes to match: the extra requires exactly those three names, each
    with a lower and an upper bound.
- **Vet repeated on 2026-11-22 by T001** (OSV and the PyPI JSON API; the lowest-direct check in a
  scratch venv on Python 3.12)
  - **No `MAL-` advisory** for `langchain`, `langchain-core`, `langgraph`, `langgraph-checkpoint`,
    `langgraph-prebuilt`, `langgraph-checkpoint-sqlite` or `aiosqlite`. No file is yanked at any version
    looked at; every package ships a wheel and an sdist.
  - **The floor of `langgraph` moves from 1.2.12 to 1.2.14.** `GHSA-3fx2-cqw9-xr3c` (moderate,
    CWE-22, published 2026-10-28) covers `langgraph` 1.2.3 up to 1.2.14 (fixed in 1.2.14): the
    `RemoteGraph` v3 streaming client builds request paths from an unencoded `thread_id`, with a
    vulnerable `langgraph-sdk` (0.4.0 to 0.4.5). The bridge wraps a local compiled graph and never
    uses `RemoteGraph`, so it is not exposed; the floor moves anyway, because it costs nothing:
    `langgraph` 1.2.14 (uploaded 2026-10-06, 46 days old) requires `langgraph-sdk>=0.4.6`, and
    `langchain` 1.4.6 accepts `langgraph>=1.2.12,<1.3.0`. The advisories on the other packages are all
    fixed below the floors (`langchain-core` 1.3.3, `langgraph-checkpoint` 4.1.1,
    `langgraph-checkpoint-sqlite` 3.1.3: its own floor).
  - Upload dates of the floors: `langchain` 1.4.6 on 2026-10-14 (38 days), `langchain-core` 1.6.10 on
    2026-10-12 (41 days), `langgraph` 1.2.14 on 2026-10-06 (46 days), `langgraph-checkpoint-sqlite`
    3.1.3 on 2026-10-30 (22 days): each older than two weeks. `aiosqlite` 0.22.1 is from 2025-12-23.
  - Lowest-direct: `langchain==1.4.6`, `langchain-core==1.6.10`, `langgraph==1.2.14` resolve together
    (with `langgraph-checkpoint` 4.3.2, `langgraph-prebuilt` 1.1.3, `langgraph-sdk` 0.4.14), and
    `HumanInTheLoopMiddleware(interrupt_mode="per_call")` and `"batched"` are both accepted;
    `langchain==1.4.5` raises `TypeError` on the keyword, so 1.4.6 is still the floor. The spike's
    facts are run on that set too (the closing note of phase 1).
  - **The extra is therefore** `langchain>=1.4.6,<2`, `langchain-core>=1.6.10,<2`,
    `langgraph>=1.2.14,<2`. Everything below that names 1.2.12 as the floor is the earlier reading.
- **Alternatives**
  - Keep `langchain>=1.3`: rejected; 1.3 to 1.4.5 pass the wrap and then fail on the first
    approval, late and far from the cause.
  - No upper bound: rejected; the other two extras have one, and a major release is a decision.
  - A CI job on the lowest versions: rejected for now (cost); the first task's check and the
    spike's pinned facts catch a drift in the newest set, which CI does run.

## R2. Wrapping: what is checked, the card, the options

- **Finding**
  - A compiled graph is a `Pregel` (a `CompiledStateGraph`); a `StateGraph` that was not compiled
    has no `astream`. `graph.checkpointer` is `None` without one. The in-memory saver is
    `langgraph.checkpoint.memory.InMemorySaver` (`MemorySaver` is the same class).
  - `graph.get_input_jsonschema()["properties"]` has `messages` for `create_agent` and
    `MessagesState` graphs; a state of `{x: ...}` does not. `graph.name` defaults to `"LangGraph"`.
  - A sync-only saver (`SqliteSaver`) raises on `aget_tuple`; there is no cheap way to detect that
    at wrap time.
- **Decision**
  - Three checks, in this order, each with a message that names the missing piece: not a compiled
    graph (`TypeError`; when it is a `StateGraph`, say "call `.compile(checkpointer=...)`"); no
    checkpointer, or one that is not a `BaseCheckpointSaver` (`ValueError`; `True`, `False` and
    `None` are refused); no `messages` in the input schema (`ValueError`, naming D1).
  - Card: the argument, or `CardInfo(name=graph.name, description="A LangGraph agent served
    through R2C.", version="0.0.0")`. Nothing is read from the graph's prompts or tools (FR-003).
  - An `InMemorySaver` gives one `UserWarning` per wrap (D11).
  - Options, keyword-only (FR-026): `card=None`, `reasoning=False`, `expose_tools=()` (a set of tool
    names whose arguments and result detail may appear on the timeline).
  - The README says a durable saver with async support is needed for a pause to survive a restart.
- **Alternatives**
  - Accept a `StateGraph` and compile it: rejected, the bridge would own the checkpointer.
  - Warn when a sync-only saver is wrapped: not possible without calling it; the saver's own error
    reaches the caller as a failed run.

## R3. One leg of a run: the stream, a callback handler and a queue (D5)

- **Finding**
  - `astream(input, config, stream_mode=["messages", "updates"], version="v2")` yields typed parts
    `{"type", "ns", "data"}`: `messages` gives `(message_or_chunk, metadata)` and `updates` gives
    `{node: update}`. Pending interrupts are best read from `aget_state(config).interrupts`
    afterwards (FR-014); the `__interrupt__` update is not used.
  - The `tasks` stream starts a `tools` task for **every** call of a model turn, including those a
    `per_call` middleware then pauses, and starts them again on every resume. Only a task's result
    carries `interrupts`, so nothing at the start tells a running tool from a paused one.
  - A LangChain callback handler passed in the run config (`config["callbacks"]`) sees
    `on_tool_start` only when the tool body really runs: a call paused by the middleware, or denied,
    fires nothing. `on_tool_start` carries `tool_call_id` (and `inputs`); `on_tool_end` gets the
    `ToolMessage` (`status="error"` for a handled `ToolException`); `on_tool_error` fires for a
    raising tool, and then the stream raises.
  - A tool that calls `interrupt()` inside its body gives `on_tool_start`, then
    `on_tool_error(GraphInterrupt)` (its class chain includes `GraphBubbleUp`); on resume the body
    restarts from the top and gives `on_tool_start`, then `on_tool_end` with `status="success"`.
  - A tool's `running` has to be visible while it runs. A plain `async for` over the stream sees
    the tool's `ToolMessage` only when the tool has ended, so without a second source of events
    `running` and `done` would arrive together.
- **Decision (D5)**
  - A **per-run handler** (an `AsyncCallbackHandler` with `run_inline = True`) is passed in the run's
    config, beside `{"configurable": {"thread_id": ctx.thread_id}}`. The graph object is not
    touched (see [plan.md](plan.md#needs-the-maintainer), point 2, on FR-001).
  - Merge by a queue: a **producer task** iterates `astream` and puts each part into an
    `asyncio.Queue`; the handler puts its tool events into the same queue; the generator
    (`run` or `resume`) is the only consumer and yields run events. A producer exception is put in
    the queue and raised in the consumer, so the driver turns it into `Error("failed")` (FR-013).
    The consumer's `finally` cancels the producer and awaits it; that also closes the stream when
    the driver cancels the run (a cancel throws `CancelledError` into the consumer's wait).
  - The queue is unbounded, as the driver's own queue is; a slow door buffers tokens in memory
    (named in the plan's risks).
  - The spec's fallback for D5 (hold `running` until the result) is not needed.
- **Alternatives**
  - Read the `tasks` or `debug` streams: cannot tell the two (above).
  - The `custom` stream: needs the graph's own cooperation; against principle III.
  - `running` at the model's request: rejected by D5 (a denied call would stay `running`).
  - Wrap each tool: edits the graph; against III.

## R4. Tool activity

- **Finding**: see R3. Also: the `ToolStrategy` structured reply is a tool call the model node
  handles itself, so no tool callback fires for it and it shows no activity. A node that calls
  `tool.ainvoke(...)` without passing its config does not propagate callbacks, so its call shows no
  activity.
- **Decision** (FR-009; the mapping is a table in [data-model.md](data-model.md))
  - `on_tool_start` → `Activity(id=tool_call_id, type="tool", label=<tool name>, name=<tool name>,
    state="running")`. Without a `tool_call_id` (a tool a node calls itself), the run id is the id.
    The label is a plan choice: the tool's name.
  - `on_tool_end` → `state="done"`, or `"failed"` when the `ToolMessage` has `status="error"`, with
    `duration_ms` from `time.monotonic()` between the two. `on_tool_error` → `failed` with the
    duration, **unless** the error is a `GraphBubbleUp` (a pause inside the tool): then nothing is
    emitted, the activity stays `running`, and the restarted body's `on_tool_start` on the next leg
    emits `running` for the same id again, which R2C-ACTIVITY-2 allows (only a terminal state is
    final). The duration of a restarted body is the last run's.
  - `args` and `detail` only for a tool in `expose_tools` (R2C-ACTIVITY-6, FR-009): `args` is the
    call's input mapping; `detail` is the result's text (or, for a failure, the error's message)
    cut at 2000 characters. The cut is a plan choice; the standard sets none.
  - When the graph raises, each activity still `running` is closed `failed` first, in the consumer's
    exception path, before the exception goes on (FR-013). A cancel emits nothing: the driver has
    already ended the run and drops what follows.
- **Alternatives**: one activity per graph node (`step`): out of scope (spec). `label` from the
  tool's description: too long for a timeline, and it can hold text the owner did not mean to show.
- **Correction after the phase 7 tests (2026-11-22; the finding above is kept as written)**: the claim that
  a node calling `tool.ainvoke(...)` without its config "does not propagate callbacks" is false, on
  Python 3.11 and 3.13. LangChain carries the callbacks in a context variable, so the per-run handler
  reaches that call too, and its activity is shown under the run id (there is no tool call id). The only
  way to hide a call is to pass `callbacks` of its own to the tool, which replaces the inherited ones;
  that is the named limit, and `test_langgraph_timeline.py` pins both cases.
- **Added by the same tests**: `args` is repeated on the terminal update of an exposed tool, so a
  caller that shows only the last update still has the input; and `args` is sent only when the call's
  input is plain JSON (`json.loads(json.dumps(input))` works). Injected state, which is not, is left
  out, never forced to a string.

## R5. The reply: chunks, the final `last`, paragraph breaks, `nostream`, structured JSON

- **Finding**
  - A streaming model gives `AIMessageChunk`s with text; chunks of one call share an id (LangChain
    sets `lc_run--<run id>` when the provider gives none); tool-call-only chunks and the usage chunk
    have empty text. `ToolMessage` parts are never reply.
  - A model that does not stream (only `_generate`) gives **one whole `AIMessage`** in the `messages`
    stream, at the end of its node; LangGraph does not send both the chunks and the whole message
    for one call (it deduplicates by id). **To pin.**
  - **`nostream`** (the tag LangGraph's own docs give for hiding a model call) hides the *tokens*
    only. A model tagged `nostream` and returned from a node still arrives as one whole `AIMessage`
    at the node's end, indistinguishable in the part itself from a non-streaming model (the part's
    metadata carries no tag). The handler of R3 can tell them apart: `on_chat_model_start` receives
    the run's `tags`, and `on_llm_end` receives the message, whose `id` is then the key.
  - The source cannot know which chunk is the reply's last (spec 003, research R5: the source sets
    `last`). `ReplyChunk(text, last=False)`.
  - The model node's `updates` part arrives when the node has finished, and holds the completed
    message(s) and, with a `response_format`, `structured_response`.
  - With a `ProviderStrategy` response format the JSON arrives as text chunks (R12).
- **Decision** (FR-008; D4)
  - Reply text is the `.text` of an `AIMessage` or `AIMessageChunk` from the `messages` stream,
    unless its id is in the handler's **hidden** set (messages produced by a model run tagged
    `nostream`, collected in `on_chat_model_start` and `on_llm_end`). A whole `AIMessage` counts as
    one chunk. A `ToolMessage` or `HumanMessage` never counts.
  - **Hold one chunk back.** The consumer keeps the newest piece of text and yields the previous one
    with `last=False`. The held piece leaves with `last=False` when (a) the model node's update
    holds a completed AI message with tool calls (the reply may or may not go on, and a slow tool
    must not delay text that is ready), (b) the leg ends in an `Ask`, (c) the graph raises. At the
    end of a leg that is not a pause, the held piece leaves with `last=True`. If nothing is held but
    the turn had reply text (read from the checkpoint with the same predicate as the stream, so the
    two agree), one `ReplyChunk("", last=True)` closes the reply; this is the rare case (text, then
    tools, then no more text, or a restart in between), and the A2A door continues an artifact it
    already started, so an empty last chunk is a normal append.
  - **Paragraph break**: when a piece belongs to a different message id than the previous piece and
    both messages have text, `"\n\n"` goes before it. Chunks with no id count as one message while
    they are consecutive in one node call.
  - **Cost**: one chunk of latency. SC-007's test therefore needs at least three tokens before its
    gate. Spec 003's research rejected an always-empty closing chunk and a look-ahead for the
    general case because a source cannot know that no reply follows an activity; the three flush
    rules above are what make the look-ahead safe here.
  - `nostream` is honoured: tokens are never streamed, and the finished message of a hidden call is
    dropped by id. (Usage still counts it; R7.) After a restart in the middle of a turn the hidden
    set is gone, so a hidden message from an earlier leg counts in the "turn had reply text" test of
    the empty closer; the effect is an empty last chunk that may be the first of its artifact. It is
    harmless and rare, and is in the plan's risks.
- **Alternatives**
  - Always send an empty `last=True` chunk at the end: rejected, it adds an event to every reply.
  - Mark the previous chunk `last` when the next AI message starts: cannot know a later message will
    not come.
  - Only the last AI message as the reply: rejected by D4.
  - Honour `nostream` by ignoring every whole `AIMessage`: would drop the reply of a model that does
    not stream.

## R6. Reasoning (FR-010) and files (FR-012)

- **Finding**
  - A streaming chunk's `content_blocks` has a `reasoning` block whose `reasoning` field is the
    text, and `chunk.text` is empty for it. Provider signatures and encrypted reasoning are not in
    the standard block's `reasoning` field (they are `extras` or `non_standard`).
  - A completed `AIMessage.content_blocks` gives `text`, `reasoning`, `image`, `audio`, `video`,
    `file` (with `base64` or `url`, and `mime_type`), `tool_call`, and `non_standard`. An `image`
    with only an `id` (hosted by the provider) has no data.
  - `HumanMessage` accepts standard blocks for input (R18).
- **Decision**
  - Reasoning is off unless `reasoning=True`. When on: one activity per message,
    `Activity(id="reasoning-<message id>", type="reasoning", label="Thinking", delta=<piece>)`, no
    `state` (R2C-ACTIVITY-2: reasoning has none, and the label is repeated).
  - Coalescing is deterministic and has no timers (R2C-ACTIVITY-7): deltas gather in a buffer; the
    buffer leaves at a sentence end or a newline when it holds at least 40 characters, or at a space
    near 400 characters, and always at the message's end (the node's update), at a pause, at the
    turn's end and just before the message's first reply text. A whole non-streamed message's
    reasoning goes out the same way. Only the standard `reasoning` field is read, so a signature or
    encrypted block cannot leave (R2C-ACTIVITY-5).
  - Files: read from the **completed** message in an `updates` part (never from chunks). For each
    block of type `image`, `audio`, `video` or `file`: `base64` becomes `BytesContent`, `url`
    becomes `UrlContent`; no data, or invalid base64, is skipped and logged at debug; `non_standard`
    is skipped. `ArtifactEvent(id="<message id>-<block index>", meta=ArtifactMeta(presentation=
    "file"), parts=(content,), name=<extras "filename" or "name" when it is a string>)`.
- **Alternatives**
  - A timer to coalesce: nondeterministic tests; rejected.
  - Reading files from the stream's whole-message parts: those are not sent for streamed models.

## R7. Usage (D7, FR-011)

- **Finding**: `AIMessage.usage_metadata` has `input_tokens`, `output_tokens`, `total_tokens` and
  `output_token_details` (reasoning tokens are already inside `output_tokens`); the model's name is
  in `response_metadata["model_name"]` for most providers. No cost and no duration exist.
- **Decision**
  - At the end of a turn that does not pause (and just before an `input_required` ask), read the
    checkpoint's messages after the last `HumanMessage` and sum `input_tokens` and `output_tokens`
    over the AI messages that report them. A total no message reported stays **absent** (R2C-USAGE-3).
    `model` is the last non-empty name. One `UsageEvent`, after the reply's last chunk and before
    the terminal event. Nothing is sent at a pause.
  - Because it is read from the checkpoint, the total is the same with or without a restart
    (SC-008). A hidden (`nostream`) message and a structured-reply message count: the tokens were
    spent.
  - The `input_required` answer is a new human message, so its turn counts again from zero (D7's
    limit).
- **Alternatives**: summing in the handler's `on_llm_end`: would lose the earlier legs at a restart;
  rejected. `duration_ms`: not measurable across a pause and a restart (D7).

## R8. Reading pauses: from the checkpointer, classified by shape

- **Finding**
  - After a leg, `aget_state(config).interrupts` lists the pending interrupts as `Interrupt(id,
    value)`; `id` is stable across a restart over the same SQLite file and differs between graphs.
    `Interrupt.response_schema` (R9) is a plain dict that survives the restart.
  - Payload shapes: a `per_call` middleware interrupt is `{type: "tool_approval", tool_call_id,
    name, args, description}`; a `batched` one is `{action_requests: [{name, args, description}],
    review_configs: [{action_name, allowed_decisions}]}`; anything else is the graph's own value.
- **Decision** (FR-014, FR-015, FR-016, FR-021; the table is
  [contracts/pause-mapping.md](contracts/pause-mapping.md))
  - Each pending interrupt is classified by the shape of its value, in this order: `per_call`
    approval (all four keys present), `batched` (both lists present), a valid hand-written R2C
    `question` or `approval` (core's `parse`, and an approval that is not addressed to the caller:
    the schema already refuses `answer_by.role = "caller"` on an approval), and last the fallback
    question of FR-021.
  - **Request ids**: `lg-<interrupt id>` for a `per_call` approval and for a fallback question;
    `lg-<interrupt id>-<n>` for the call at position `n` of a `batched` interrupt; the object's own
    `id` for a valid hand-written request; `lg-ir-<id of the last AI message>` for `input_required`
    (R12). Two parallel hand-written requests with the same own id cannot be told apart: the first
    in order matches. The contract says an author keeps them distinct.
  - **One at a time**: tool approvals first, in the model's tool-call order (the position of
    `tool_call_id` in the last AI message's `tool_calls`), then the others in the order LangGraph
    lists them (R14). The leg ends right after the `Ask`.
  - Only the checkpointer's list is used; a pause it does not hold is never offered. On `resume`
    the pending set is read again, and the answer's `id` is matched against the ids above; no match
    is a lost pause (R13).
  - The fallback question (FR-021): one field `{key: "answer", header: "Answer", text: "Your
    answer", type: "text"}`; a string value is the title (cut at 200 characters; an empty one
    becomes "The agent needs input"), any other value is the title "The agent needs input" with the
    value as bounded JSON text (`default=str`, 2000 characters) in the description. `answer_by` is
    `person`.
- **Alternatives**: asking from the `__interrupt__` stream part: a pause the checkpointer cannot
  resume would be offered; rejected by FR-014. Importing the middleware's types to classify:
  couples the bridge to `langchain` internals for no gain; shape tests are what a hand-written
  graph shares with it.

## R9. Turning an answer into the graph's decision (FR-016 to FR-020)

- **Finding**
  - `per_call`: the interrupt's `response_schema` is a JSON Schema dict. With several allowed
    decisions it holds `$defs` and a `oneOf`; with one it is that decision's schema itself. Every
    decision schema has `properties.type.const` (`approve`, `edit`, `reject`, `respond`). The `edit`
    schema's `edited_action.name` is a `const` equal to the call's own tool name.
  - `batched`: `review_configs[i].allowed_decisions` and `action_requests[i].description` carry it;
    `response_schema` is `None`.
  - A `per_call` decision the call does not allow raises a validation error and **leaves the thread
    intact**; a `batched` one with the wrong count or a disallowed type raises `ValueError` and
    **leaves the thread unable to continue** (spec finding 2).
  - `edit` needs the tool's arguments schema for R2C-APPROVAL-3. In a `create_agent` graph the tool
    node holds the tools by name; their schema is read as in R16.
  - Pinned by the phase 1 spike (2026-11-22): after an `edit`, the `ToolMessage` text is the
    middleware's `edit_notice` followed by the tool's own result; the model is told a person replaced
    the call. The bridge sends nothing of its own for it.
- **Decision**
  - Allowed decisions: `per_call`, every `properties.type.const` found by walking the schema
    (`$defs` and `oneOf` included); `batched`, `allowed_decisions`. **A `per_call` payload whose
    `response_schema` is missing or has no decision is not asked: the run ends `failed` with a
    reason that says the decisions could not be read, and the graph is not touched.**
  - To R2C: `approve` → `allow`; `reject` → `deny`; `edit` → `edit` only when the tool's schema is
    known (it is then `Subject.args_schema`); `respond` is dropped. A call that allows only
    `respond` becomes a `question` (one text field, `answer_by` person). If nothing is left to offer
    (only `edit` and no schema), the run ends `failed` and says so, before any ask.
  - The approval: `Subject(type="tool_call", name=<tool>, args=<model's args>)`, title `Approve
    <tool>?`, the middleware's `description`, `answer_by` `person`, `decisions` in the order
    `allow`, `edit`, `deny`.
  - From an answer to the graph's value: `allow` → `{"type": "approve"}`; `deny` → `{"type":
    "reject", "message": <reason>}` (the message left out when there is no reason); `edit` →
    `{"type": "edit", "edited_action": {"name": <the call's tool name>, "args": <answer args>}}`;
    a text answer to a `respond`-only question → `{"type": "respond", "message": <text>}`;
    `declined` → `reject` (R2C-ANSWER-3), or, when the call does not allow `reject`, a refusal.
    A `per_call` resume value is that decision; a `batched` one is `{"decisions": [...]}` in
    position order (exact shapes: **to pin**).
  - **Validation before the graph** (FR-020): the bridge recomputes the request it would have asked,
    checks the answer with the core's `check_answer` against it (the door did the same, so this
    only catches a caller that skipped the door, as the suite's driver does), and checks the
    graph-side rules: the decision is in the allowed set, the count of a batch is complete. A
    failure raises `ValueError` with the readable problems, so the run ends `failed`
    (`Error("failed", reason)`), nothing was sent to the graph and the pause is still pending. The
    caller's next `resume` with a correct answer finds the same pending interrupt and works, in both
    modes.
- **Alternatives**: offering `respond` as an R2C decision: R2C has no such name; the text question is
  the honest shape. Re-asking with `errors` from inside the bridge: the doors already do that
  before delivery; a second mechanism in a source would be unreachable code.

## R10. A batch in progress (FR-019, D8)

- **Finding**: the middleware needs every decision of a `batched` interrupt in one resume, and the
  graph's state has no place for a partial set. A wrong resume breaks the thread (R9).
- **Decision**
  - The agent keeps `{(thread id, interrupt id): {position: decision}}` in memory. An answer for a
    call of a batched interrupt records its decision; when every position is decided, one resume
    `{"decisions": [...]}` goes out in position order and the record is dropped; otherwise the
    generator yields the next `Ask`, for the first position with no decision, and ends, with no
    graph call.
  - An answer for a position when the bridge has no record (a restart in between) is **kept**, and
    the first undecided position is asked, so the batch is asked again from its first call
    (FR-019). A restart in the middle of a batch therefore costs the caller the answers already given.
  - The record is dropped when the batch completes, when a new input settles the thread (R11), and
    when the pause is found lost. The map is bounded at 1024 records (oldest dropped), so abandoned
    batches cannot grow without limit.
  - One process: two processes serving one thread share nothing; the doors keep one unfinished
    task per context, so there is no concurrent writer.
- **Alternatives**: storing the partial set in the graph's state: needs a field the owner would add
  (against III). Asking the whole batch as one request: against R2C-APPROVAL-4.

## R11. A new input on a pending approval: settle by a state update (D9, FR-007)

- **Finding** (a scripted model that rejects a tool call with no tool message after it, as real
  providers do)
  - Without a settle, a new input on a paused thread fails with "dangling tool calls", in both modes
    (baseline confirmed).
  - A rejecting resume is a poor settle: it runs the graph on, so the model is called, ungated tools
    may run, and the graph may pause again; and a call that allows only `approve` cannot be
    rejected.
  - A state update works in both modes: `aupdate_state(config, {"messages": [...]})` with no
    `as_node`, then the new input. After it, `next` is `('model',)` (`per_call`) or
    `('HumanInTheLoopMiddleware.after_model',)` (`batched`, dropped by the new input). Tools ran as
    expected afterwards: only the ungated one in `per_call`, none in `batched`.
- **Decision**
  - When a run starts and `aget_state` shows a pending interrupt that is a middleware approval
    (shape of R8), append to the state, in one update: the `ToolMessage`s already produced by
    `per_call` tool tasks that finished inside the unfinished step (read from `state.tasks[i].result`,
    a mapping with `messages`), and, for every tool call of the last AI message that has no
    `ToolMessage` in the messages or in those results, a `ToolMessage(content="The call was
    withdrawn: a new message came before it was approved.", name=<tool>, tool_call_id=<id>,
    status="error")`. Then the input is sent. The thread's batch record is dropped.
  - Other kinds of pending interrupt are left as LangGraph leaves them (the node starts again).
  - Mutation check (SC-009): with the update removed, the strict-model test fails.
- **Alternatives**: refuse the new input while a pause is pending (a cancelled task would lock the
  context: D9); a rejecting resume (above); send it as it is (finding 6).

## R12. `input_required` (D10) and the open `completed` reply

- **Finding**
  - With `create_agent(response_format=ToolStrategy(Schema))` or `ProviderStrategy(Schema)`, the
    final state holds `structured_response` (a pydantic instance, or a dataclass or mapping,
    depending on the schema); the graph has a `structured_response` channel and output key.
  - The model node's `updates` part holds `structured_response` (and the messages), so a leg can see
    it as it happens.
  - `ToolStrategy` streams **no text** (tool-call chunks, then a `ToolMessage` "Returning structured
    response: ..."). `ProviderStrategy` streams the JSON **as text chunks**.
  - A `structured_response` of a pydantic type is stored in the checkpoint, and LangGraph warns that
    deserializing an unregistered type will be blocked in a future version unless the owner lists it
    (`allowed_msgpack_modules`). That is the owner's setting, and the README names it.
- **Decision** (FR-022)
  - A leg notes the `structured_response` its own `updates` carried (so a value left from an earlier
    turn is never read), normalised: pydantic by `model_dump()`, a dataclass by `asdict`, a mapping
    as it is, an `Enum` by its value; anything else is ignored. When the leg ends with no pending
    interrupt, `status == "input_required"` and a non-empty `message` string, the bridge yields
    `Ask(question)` after `UsageEvent`: `answer_by` `caller`, one `text` field, title the message's
    first line cut at 200 characters (the whole message in `description` when it was longer),
    id `lg-ir-<id of the last AI message>`.
  - **Not streamed as reply**: when the graph has a `structured_response` channel, the text of an AI
    message whose first non-blank character is `{` is **held** until that message's node update
    arrives; then it is dropped when the update's structured reply is `input_required`, and released
    as ordinary reply text otherwise. Prose streams at once.
  - **The answer** is a new human message of the same thread (`run`'s path, no resume). On `resume`
    the bridge checks the request is still pending: no pending interrupt, the last AI message's id
    matches, no human message follows it, and its structured reply still says `input_required`;
    otherwise the pause is lost (R13). A `declined` answer ends the run `done` without calling the
    graph (the spec only covers declined interrupts; this is a choice, in the plan's points).
  - **Open point for the maintainer, not decided here:** a `completed` structured reply under
    `ToolStrategy` has no text, so the caller gets **no reply text** for such a turn (under
    `ProviderStrategy` it gets the JSON, because only an `input_required` one is held). The A2A
    sample's response format expects the `message` to be the reply. The spec says the reply is the
    AI messages' text, so the default is to leave it; sending `message` as the reply for a
    `completed` structured reply would be an option, not a silent behaviour.
- **Alternatives**: an owner-supplied predicate (D10: later, not now); detecting `input_required`
  from the last AI message's text: fails for `ToolStrategy` (no text).
- **Correction, 2026-11-22 (phase 8), what "a graph that has a `structured_response` channel" means.**
  Every graph `create_agent` builds has that channel, with or without a `response_format`, so the hold
  above applies to all of them, not only to the ones built with a format. The cost is small and bounded: a
  message that starts with `{` is kept apart only until its own node update (which comes when that node
  ends), and is then released as ordinary reply text when the update does not ask. A graph built by hand
  with no such channel streams as before (`test_a_json_reply_is_only_held_when_the_graph_has_a_structured_response`).
  Also seen while testing: `create_agent` clears the channel when the next turn starts, so a stale reply
  reaches `resume` only from a graph that keeps its own `structured_response` from turn to turn; the
  state's pending-interrupt and human-message checks are for those graphs.

## R13. A lost pause ends `lost`: one additive core exception (D2, FR-023)

- **Finding**: `Driver._pump` turns any exception from a source into `Error("failed", str(exc) or
  type name)`. Only a live source gets `Error("lost")`, from the driver itself. For a checkpoint
  source, `resume` is called after the driver has emitted `AnswerEvent`.
- **Decision** (approved as D2)
  - `core/source.py` adds `class PauseLost(Exception)` and `core/__init__.py` exports it. In
    `_pump`, `except PauseLost as exc` comes before `except Exception` and calls
    `self._finish(Error("lost", str(exc) or "The paused run was lost; ask again."))`. The run then
    reads `AnswerEvent`, then `Error("lost")`, the shape the doors already map for a live source.
  - A checkpoint source raises it in `resume` when the checkpointer holds no pending interrupt that
    matches the answer's id: an in-memory saver after a restart, a thread that was pruned, an answer
    that was already applied. The graph is not started (FR-023). The exception's text names the
    request id and says to ask again.
  - Test first, core only: a fake checkpoint source that raises `PauseLost` ends `lost`; the
    core-only check stays green; a note is added to the 002 contract.
  - The A2A door and the MCP door each get one in-process test for it (a lost pause is shown as the
    door shows `lost` today).
- **Alternatives**: `failed` with "lost" in the text: a caller cannot tell it from a real failure,
  and the doors tell a caller that `lost` means "ask again". Let the driver detect it: it checks
  nothing about answers (by design).

## R14. Hand-written interrupts: ordering and sequence (FR-014, FR-021)

- **Finding**
  - Three parallel nodes that each call `interrupt()`: `state.interrupts` was in node order in 3 of 3
    runs, with `tasks` listing one interrupt each; ids differ between graphs and are stable across a
    restart. Answering by id, one at a time, works. Two `interrupt()` calls in a row in one node
    appear one after the other, the second with a new id after the first is answered; the node
    restarts from its top each time.
  - The resume value of an `interrupt()` is whatever `Command(resume={<interrupt id>: value})` carries.
- **Decision**: ask in the order LangGraph lists them; the test asserts the same order before and
  after a SQLite restart (a drift fails it). The resume value is the answer's `value` mapping for a
  valid hand-written R2C request, the answered text for the fallback, and `None` when declined.
  Sequential interrupts need nothing special: each leg ends at the next pending one.
- **Alternatives**: sorting by id or by a graph-given priority: the order is LangGraph's own, and the
  ids are hashes.

## R15. What the doors do with a reply across a pause, and with large content (FR-008, edge cases)

- **Finding** (read from `a2a/task.py`, `a2a/executor.py` and `mcp/source_tool.py`)
  - A2A: `R2CTask.reply(text, last)` sends a chunk of the artifact `reply` with `append` true after
    the first and `lastChunk=last`; the flag "already started" is restored from the stored task's
    artifacts, so a reply continues across a pause and a restart. `check_size` runs on text and on
    base64 content; `ContentTooLarge` fails the task.
  - MCP: the door gathers reply text across the pause (kept in the point's output) and ignores
    `last`; an output over `Limits` is `output_too_large`.
- **Decision**: the `last` rule of R5 fits both. The bridge does **not** size-check content; it hands
  over what the model produced and the door refuses what it cannot carry. A test with a door whose
  limit is small shows a clean failure (SC-001 family). The 5 MiB and 50 MiB limits are the
  standard's defaults.
- **Alternatives**: a size check in the bridge: a second place that knows the limits; the doors are
  the ones configured with them.

## R16. LangChain tools as `ToolSpec`s (FR-024, FR-025)

- **Finding**
  - `tool.args` lists only what the model sees. For a tool with a pydantic `args_schema` (the case
    of `@tool`), `tool.get_input_schema().model_fields` also lists the injected arguments: `state`
    (`InjectedState`), `store` (`InjectedStore`), `runtime` (`ToolRuntime`), `tool_call_id`
    (`InjectedToolCallId`) and any `InjectedToolArg`; the difference of the two is the set to refuse.
    For a dict `args_schema` there is nothing injected; `get_input_schema()` wraps a tool call, so it
    is not used for the schema.
  - `tool.tool_call_schema` is the model-visible schema: a pydantic class (call
    `model_json_schema()`) or the dict itself.
  - `tool.ainvoke(args)` runs a sync tool in an executor (a probe saw the loop tick five times while
    a 0.3 s sync tool ran). A tool with a dict `args_schema` is **not** validated by LangChain: a
    wrong key reaches the function and fails as a `TypeError`.
  - The core's argument checker (`tool_from_function`'s) is private to the core.
  - Pinned by the phase 1 spike (2026-11-22): for a **dict** `args_schema`, `tool_call_schema` comes back
    as a copy with the tool's `description` added at the top level, so the conversion drops it (the
    `ToolSpec` carries the description itself) as it drops `title`.
- **Decision**
  - `tool_from_langchain(tool)`: schema from `tool_call_schema` (a copy; `title` removed, as
    `tool_from_function` does); description and name from the tool; refuse at conversion, with a
    `TypeError` that names the tool and the argument, when the input schema has an injected
    argument. `call` validates the arguments against the schema with `jsonschema` (a core
    dependency), raises `InvalidArguments` with one `Problem("invalid_args", key, message)` per key
    when they break it (the tool does not run), then awaits `tool.ainvoke(dict(args))`.
  - `tools_from_langchain(tools)` converts a list in order and refuses the whole list when one is
    refused (FR-025).
  - The same helper gives the schema for an approval's `edit` (R9), looked up in the tool node of a
    `create_agent` graph (found by looking for a node whose `bound` has `tools_by_name`); a graph
    without one offers no `edit`.
- **Alternatives**: use `get_input_jsonschema()`: wrong for a dict schema. Import the core's private
  checker, or add a public `check_arguments` to the core: a second core change that was not
  approved; the bridge's own fifteen lines are the smaller step, and moving them into the core later
  breaks nothing.
- **Phase 9 (2026-11-22), what the installed packages showed once the conversion was written** (the
  decisions above hold; these add to them):
  - **The description is in the pydantic schema too.** LangChain builds the model of `tool_call_schema`
    with the tool's own description as its docstring (also when the user's model has a docstring of its
    own), so `model_json_schema()` has a top-level `description`, as the dict case has. `schema_of` drops it
    in both cases; the `ToolSpec` carries the description.
  - **`tool_call_schema` is weaker than the tool's own model.** It leaves out `extra="forbid"` and field
    validators, so a call with an extra key or a value a validator refuses passes the JSON Schema check and
    LangChain then raises a raw pydantic `ValidationError` before the body runs. `call` therefore also
    validates with the tool's own pydantic `args_schema` and raises `InvalidArguments` (key from the first
    `loc`, "This value is not accepted.") as `tool_from_function` does. It does not catch what the body raises.
  - **The injected set is read from two models, not from `tool.args`.** A legacy `Tool` with no
    `args_schema` has `args == {"tool_input": ...}` while its input model is made from
    `_run(*args, config, **kwargs)`, so the rule of this note's first bullet ("the difference of the two")
    named `args`, `config` and `kwargs` as injected. The set is now the fields of `get_input_schema()` that
    `tool_call_schema` does not have. A tool with no `args_schema` whose `args` differ from the properties of
    the schema we would pass on (the legacy `Tool`) is refused with a `TypeError` that says there is no
    schema of its arguments. A `BaseTool` subclass without `args_schema` converts (LangChain reads `_run`).
  - **A dict `args_schema` with no `properties` has no `tool.args`** (it raises `KeyError`), so the
    conversion asks `args` only of a tool with no `args_schema`.
  - **Aliases are dropped by `tool_call_schema`** (it shows the field name; the tool's own model asks for the
    alias). Inconsistent in LangChain itself; the bridge refuses a call by name as "not accepted" and the
    tool does not run. Not changed.

## R17. Tests: the scripted model, real checkpointers, the suite

- **Finding**
  - `GenericFakeChatModel` cannot stream a turn that has tool calls and empty text ("No generations
    found in stream"). A small `BaseChatModel` subclass that overrides both `_generate` and
    `_astream` can; `updates`-only streams call `_generate`, so both must agree.
  - A scripted model that keeps a counter breaks a restart test: a new model object after the
    "restart" starts its script again and said "deploying now" a second time. **The model must be a
    pure function of the message history** (for example the count of `ToolMessage`s since the last
    `HumanMessage`).
  - Both modes of the middleware, hand-written interrupts, `response_format`, a strict model that
    rejects dangling tool calls, and a SQLite file restart were all exercised with such a model.
- **Decision** (the files are in [plan.md](plan.md#source-code))
  - `tests/langgraph_models.py`: the scripted model (history to reply; streams word by word; tool
    calls and `usage_metadata` on a last chunk; an optional gate on an `asyncio.Event` after `k`
    tokens for SC-007; `strict=True` rejects a tool call with no answer; `stream=False` for a model
    that does not stream; a `nostream` variant), and `tests/langgraph_graphs.py` (builders for the
    graphs of the stories, and a helper that "restarts" a graph over the same SQLite file with
    `AsyncSqliteSaver`).
  - Real packages everywhere; the model is the only fake (constitution VII). The bridge is tested on
    the installed wheel, like the other doors.
  - **The shared suite (D3)**: (a) the sequence checks (`FULL` and its siblings) compare a
    **shape**: consecutive reply chunks join into one reply entry, `activity` may appear anywhere,
    while `ask`, `answer`, `usage` and the terminal event keep their exact order; (b) the real
    source's graph asks with hand-written R2C payloads that carry `q-1` and `ap-1`, chosen by the
    suite's input text; (c) a test-only wrapper (`tests/langgraph_suite_source.py`) records
    `answers`, builds a graph whose tool raises for `fail_after_ask`, and yields a second `Ask` when
    `double_ask` is set, so the driver's guard (S9) is tested as it was with the fakes. The 002
    contract file gets a dated note.
  - **Mutation check**: with the changed suite, removing an assertion or dropping a reply from a
    fake must still fail it. One scratch run records "N of N mutants died", as phases of 005 did.
- **Alternatives**: a real model: no network or keys in tests. Skip S9 for the bridge: a skipped
  scenario is a hole (D3).

### Mutation check of the suite (phase 2, 2026-11-22)

- **How**: a scratch script (not committed) copies `tests/` to a scratch folder per mutant, changes
  one thing in a fake or in the suite there (or in the installed driver, restored after), and runs
  `test_agent_source.py` and `test_core_pause_lost.py`. It refuses a mutation that changes nothing and
  checks that the baseline is green first (31 passed).
- **Result: 12 of 12 mutants died** (the 13th, "the wrapper never yields the second ask", needs the
  wrapper and runs in T035):

  | Mutant | Died by |
  |---|---|
  | the source drops its reply | S1–S4, S6, S7 (checkpoint): 11 failures |
  | the reply comes before the answer | S1–S4, S6: 10 failures (S7 starts at the answer) |
  | `usage` is missing | 11 failures |
  | `usage` comes before the reply | 11 failures |
  | a second `usage` at the pause | 10 failures |
  | the source yields `Done` itself | 11 failures (the driver ends `protocol`, the shape no longer matches) |
  | the last reply chunk has `last=False` | 11 failures, all from the new `check_last` |
  | the driver calls `resume` on a cancelled run | S5 (checkpoint) and S7, whose last line cancels the first run |
  | the source never records the answer it got | S3 (checkpoint) |
  | the source swallows its exception after the ask | S8 (checkpoint) |
  | the shape check merges non-consecutive replies | the unit test of `shape` only (no fake sends two replies) |
  | the shape check drops `usage` | S1–S4, S6, S7 and the unit test: 12 failures |

- **Beside the 12**, three mutants of the new core piece also died: the `PauseLost` branch removed
  (the run ends `failed`: 4 failures), the empty-message fallback removed (1), and the branch placed
  after `except Exception` (the general branch wins: 4).
- **Survivors**: none, so nothing to fix or to name as equivalent. One mutant a first draft got wrong,
  found while writing the script and fixed before the run: "the source yields `Done`" must build a real
  `Done` (a bare name would raise a `NameError` and kill the mutant for the wrong reason).

### Mutation check of the bridge (phase 3, 2026-11-22)

- **How**: the same scratch script style (not committed): one thing is changed in the installed copy of the
  bridge (restored after), or in a scratch copy of the tests, and the four phase-3 files run with `-x`.
  A mutation that changes nothing is refused, and the baseline must be green first.
- **Result: 17 of 17 mutants died.** The 13th suite mutant, "the wrapper never yields the second ask"
  (S13), and sixteen of the bridge: B1 the last chunk has `last=False`; B2 a pause flushes with
  `last=True`; B3 the paragraph break is removed; B4 the `finally` no longer cancels the producer; B5
  `thread_id` is a constant; B6 a hidden id is not skipped; B7 `PauseLost` is a `RuntimeError`; B8 the
  pending-set match is skipped; E1 no hold-one (a piece leaves at once); E2 a tool-call update does not
  flush; E3 a turn with text closes with no empty chunk; E4 the resumed leg is not seeded; E5 the answer
  is not checked; E6 usage counts only the last message; E7 a declined answer resumes with an empty value;
  E8 a failure drops the held piece.
- **Two holes the first run found**, filled with a test each before the run that counts: B8 would have
  survived (no test had a pending pause and an answer for *another* request), and E5 survived (no test had
  an answer the request refuses). Each test also checks that the graph is untouched and the pause stays
  pending.
- **The core fix found on 3.11** (the pump-local "asked" flag; see the phase 3 note in `tasks.md`): 4 of 4
  mutants died: the end of a pump reads only `pending` again; an `Ask` after an answered `Ask` is
  accepted; nothing is refused after an `Ask`; the pump never records its `Ask`. The third had survived
  once: the "nothing after an `Ask`" rule for events other than `Ask` had no test of its own, and a test
  was added.

### Mutation check of the doors (phase 4, 2026-11-22)

- **How**: as for the bridge (R17 above); the file run is `test_langgraph_doors.py` (9 tests), baseline
  green first.
- **Result: 7 of 8 mutants died**: D2 the held piece is dropped at a pause (two tests added for it, one
  per door, with a graph where a plain node pauses right after the model spoke); D3 a pause flushes with
  `last=True`; D4 the answer's interrupt id is not forwarded; D5 the resumed leg is not seeded; D6 no usage
  at the end; D7 the thread is a constant; D8 the pause is answered without being found again (the graph
  is started).
- **The survivor, D1 `PauseLost` raised as `RuntimeError`, is equivalent at the doors**: A2A and MCP show
  the `reason` of an `Error` whatever its code, so `lost` and `failed` read the same there. The difference
  is killed by the phase 3 test at the `Driver` (B7), where the code is visible.

### Mutation check of approvals and batches (phase 5, 2026-11-22)

- **How**: as for the bridge (R17 above); the two files run are `test_langgraph_approvals.py` and
  `test_langgraph_batch.py`, baseline green first (67 tests, then 71 after the two tests below).
- **Result: 24 of 24 mutants died** (22 on the first run, the other two after a test each). In the code of the
  decisions: allow sent as reject (M1); the deny reason (M2) and the declined note (M3) not sent as the
  message; deny (M4) or approve (M5) offered whatever the graph allows; edit offered without a schema (M6);
  the graph-side check passing everything (M7) or not called (M8); the core's problems ignored (M9); an
  edit taking the tool name from the answer (M12); a reply not sent as the message (M16); a per-call
  answer sent as a hand-written one (M17). In the batch: an incomplete batch sent as it is (M10); the
  batch leaving in the order the answers came (M11); records never pruned (M18); a decided call asked
  again (M19); a record of another size not starting a new batch (M23); the oldest record not dropped at
  the limit (M24). In the request: tool approvals ordered by name (M13); an approval answered by an
  `approver`, not a person (M15, SC-006); the edit schema shown when edit is not offered (M20); the title
  the bare tool name (M22).
- **Two survivors, both holes in the tests**: M14, approvals not ordered at all, had looked equivalent (the
  graph already lists `per_call` interrupts in the model's order, and a batch is in position order), but
  the order is a rule of `read_pauses`, so a unit test over a state whose interrupts are listed in the
  reverse order was added (it also pins that what the graph wrote itself comes after the tool approvals);
  M21, an empty or missing description shown as text, had no test (three cases added).
- **Not mutated**: the "`approval` for the caller" mutant of T054 is M15's neighbour: the model of an
  approval cannot say `caller` (`ApproverBy` is `person` or `approver`), so the only way to break SC-006
  here is the role the bridge picks, which M15 covers. The closing walk over every path is T075.

### Mutation check of the restart (phase 6, 2026-11-22)

- **How**: as for the bridge (R17 above); the file run is `test_langgraph_restart.py` (13 tests), baseline
  green first. All 13 tests had passed on their first run, so the check is what shows they are not vacuous.
- **Result: 10 of 10 mutants died**, none needed a new test. The request id of a `per_call` pause (R1) or of
  a batched call (R2) is a `uuid`, not the interrupt id; the batch records are shared by every agent of the
  process (R3, killed by the half-answered batch: a "restart" that still remembers is not a restart); the
  pause match is skipped (R4); a lost pause is swallowed and the graph started anyway (R5); `resume` sends
  the first input again instead of the answer (R6, so a tool body would run twice); `resume` is sent with
  no interrupt id (R7); a lost pause ends `failed`, not `lost` (R8); no usage at the end of the turn (R9);
  the answer to a hand-written question is not carried into the graph (R10).

### Mutation check of the timeline (phase 7, 2026-11-22)

- **How**: as above; the file run is `test_langgraph_timeline.py` (79 tests), baseline green first.
- **Result: 39 of 39 mutants died, after two test holes were filled.** 37 died on the first run. The two
  survivors were not equivalent mutants:
  - "the thoughts do not end when the reply's words start" and "the thoughts do not end with the message's
    update" both lived, because no test said *when* a message's reasoning is over. Two ordering tests were
    added: a reply of several words after the reasoning (the buffer leaves before the first word) and a
    reasoning-only message that calls a tool (the buffer leaves at the message's update, before the tool's
    `running`). Both mutants died after.
- **What the 39 cover**: a pause in a tool's body treated as a failure; the activity id; a tool message
  with `status="error"` read as done; an input that is not JSON sent as it is; a tool end or start never
  queued; `running` sent at the model's request; `args` and `detail` shown for an unexposed tool; `detail`
  cut one character late; no duration; a failed call ending `done`; a graph that raises leaving its tools
  `running`; the reasoning option ignored; a provider's signature read as reasoning text; the 40 and 400
  limits moved by one, each way; a full stop with no space after it counted as a sentence end; a newline
  not counted; the buffer not drained at a pause or at the turn's end; the thoughts of a hidden call sent;
  usage at a pause; usage of the last message only (what a leg-local sum would give after a restart,
  killed by the SQLite test); the model name taken from the last message even when empty; an absent count
  sent as `null`; a bad base64 block raising; the artifact id counting the files sent, not the position;
  a file with no media type given `text/plain`; a name read from `filename` only; a message seen again
  sending its files again; the files of a hidden call sent; files read from chunks too; and an earlier
  leg's messages not known to the resumed leg.

### Mutation check of other pauses, input_required and the settle (phase 8, 2026-11-22)

- **How**: as above; the files run are `test_langgraph_pauses.py`, `test_langgraph_structured.py` and
  `test_langgraph_settle.py` (72 tests when the check was first run, 85 after), baseline green first. A
  mutant that survives is then run against every `test_langgraph_*.py` file, to tell a hole from a
  mutant an older phase already kills.
- **Result: 42 of 42 mutants died** (43 at the start). 30 died on the first run, and the 13 that did not were:
  - **two killed by older tests**: tool approvals not in the model's order (M51: `test_tool_approvals_come_in_the_models_order`,
    phase 5) and prose held until its node update (M70: the reply's chunk tests, phase 3);
  - **ten holes in the new tests**, each filled and killed afterwards:
    - the description of a *string* was never checked past 2000 characters (the test only cut a large JSON
      value): a string of 2500 characters, in both the fallback and the `input_required` tests;
    - an `Enum` status read by its value: the test's `Kind` was a `str` Enum, whose members equal the text
      anyway; it is a plain `Enum` now;
    - the human-message check of a pending question: the "conversation moved on" test ran a whole new
      turn, which overwrites the reply; a message put on the thread with no turn does what the check is for;
    - the pending-interrupt check of a pending question: it needs a graph that keeps its `structured_response`
      from turn to turn (R12's correction), stopped at an interrupt, and an answer to the id the new last
      message would give;
    - held text whose node update never came is released at the end of the leg: a graph node that streams a
      model's text and returns none of it, and a unit test of `Reply.release_all`;
    - blanks before a `{` do not decide what a message is: a unit test of `Reply` (the scripted model does
      not split its text at a blank);
    - the JSON hold after a pause: the leg that goes on after an answered interrupt, ending `input_required`;
    - **a hand-written interrupt must not be settled**: the first test accepted `Done`, `Error` or `Ask`
      as the end of the run, and a settle that did write ended in an `Error` (a `KeyError` in the graph's
      routing), so it passed. It now asks for `Done` and for the exact messages the run added;
    - an empty write when the calls are not in the graph's own messages: a unit test of `settle` with a
      recording stand-in for the graph;
    - the settle's `as_node`: the first mutant used `"tools"`, which is the node LangGraph infers for a
      `per_call` pause, so it changed nothing; with `"model"` the thread's `next` is the middleware's step
      instead of the model's, and a test now reads it (`per_call` only: in `batched` the waiting step is
      the middleware's own and any `as_node` of the agent gives the same).
  - **one equivalent mutant, so the code went**: `resume` asked for a pending question only when the graph
    had a `structured_response`; `pending_question` already returns nothing without one.
- **What the 42 cover**: a caller-addressed approval asked as an approval; the fallback title not cut, an
  empty title kept, a title that is the whole text repeated as the description; a value that is not text shown
  uncut or with no description; the resume value (the text for the fallback, the mapping for a valid request,
  `None` when declined); requests the graph wrote ordered before the tool approvals, in reverse, or the last
  one asked first; an `Enum` or dataclass reply unread; a blank message a question; the title the whole text
  and not its first line; the question's id not the last AI message's; a question read from the state and
  not from the leg's updates; the answer sent as a resume; a declined question that still calls the graph;
  a conversation that moved on, or a pending interrupt, that does not drop the question; the JSON never
  held, held in every graph, released when it asks, dropped when it does not, dropped when its update never
  came, held after blanks or not, and not held after a pause; a dropped message that still counts as having
  spoken; the settle with another `as_node`, a withdrawn message that is a success, a finished call's
  message dropped, a call that has its answer withdrawn again, a hand-written interrupt settled, no settle
  at all, the batch record kept, an empty reason and an empty write.

### Mutation check of the LangChain tools (phase 9, 2026-11-22)

- **How**: as above, against `test_langgraph_tools.py` (46 tests when the check was first run, 50 after),
  baseline green first; the installed wheel is patched and restored for each mutant.
- **Result: 28 of 28 mutants died.** The first 24 all died on the first run, so no test was a hole. A probe
  after that run found the legacy `Tool` defect (see R16, phase 9) and the injected rule was changed; four
  mutants were added for the new code and died too.
- **What the 28 cover**: the arguments not checked against the schema, and the pydantic check not run; an
  injected argument not refused, only the first one named, the tool not named, a subclass that infers its
  schema not looked at, a plain JSON Schema looked at, the old `tool.args` rule; a tool with no schema of its
  arguments converted, and the legacy check asked of every tool; `title` or `description` left in; a schema
  not copied (a pydantic tool, and a dict tool copied shallowly); a sync tool run on the loop; problems in the
  order they were found, the problem with no key last, a missing key or a breaking key reported with no key,
  the key of a pydantic problem lost; what the tool itself raises turned into invalid arguments; a value that is
  not a tool accepted; the name and description of the spec empty or swapped; one refusal leaving the tool out
  of the list instead of refusing it, and a list reordered; a name missing from `__all__` of the module or of
  the bridge.
- **Not covered, on purpose**: which message a key gets when it breaks two rules (the first, as jsonschema
  finds them): the contract says one problem per key, not which, and pinning it would pin jsonschema's wording.

## R18. Layout, imports and packaging

- **Decision**
  - New package `ext_r2c/bridges/` (an `__init__` with only a docstring) and `ext_r2c/bridges/
    langgraph/` with the modules in [plan.md](plan.md#source-code). Public names: `LangGraphAgent`,
    `tool_from_langchain`, `tools_from_langchain`; `PauseLost` is the core's.
  - `bridges/langgraph/__init__.py` imports `langgraph` and `langchain_core` inside a `try`; the
    `ImportError` it raises names the extra (`pip install "ext-r2c[langgraph]"`), as the doors do.
  - **Imports one way** (VIII, FR-004): `bridges/langgraph` imports `ext_r2c.core` (and `langgraph`,
    `langchain_core`, `jsonschema`, `pydantic`), nothing from `a2a`, `mcp` or another bridge. No
    other module of `ext_r2c` imports it, and `Remote` (007) will not import it. `test_packaging.py`
    gets: an allowed set for it, the rule that an `ext_r2c` import there starts with `ext_r2c.core`,
    a subprocess test that `import ext_r2c.bridges.langgraph` loads no `a2a` and no `mcp` module,
    the existing `core`, `a2a` and `mcp` scans (which already refuse any `ext_r2c` import beyond
    core), and a test that blocking `langgraph` gives an `ImportError` naming the extra.
  - New check scripts: `tests/langgraph_only.py` (the wheel with `[langgraph]` and no dev group
    builds a graph, runs it through the `Driver`, answers a pause), and `core_only.py` gains "no
    `langgraph` module is loaded by the core". `a2a_only.py` and `mcp_only.py` stay as they are. CI
    gets the new step beside the others.
  - Input: `RunInput` becomes one `HumanMessage`: only `text` gives `HumanMessage(content=text)`;
    with parts, `content_blocks` of standard blocks (`text`; `image`, `audio`, `video` chosen by the
    media type's top level, other types `file`; bytes as `base64`, a URL as `url`, always with
    `mime_type`). Nothing is read, converted or dropped (FR-006).
- **Alternatives**: put the bridge under `ext_r2c.langgraph`: ARCHITECTURE.md already names
  `ext_r2c/bridges/<name>/` for bridges. One big `agent.py`: too much for one reader, and the pure
  parts (reply, reasoning, decisions, pauses) are unit-testable without a graph.
