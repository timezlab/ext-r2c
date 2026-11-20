# Research: A2A binding (`ext_r2c.a2a`)

Phase 0 of [plan.md](plan.md). Each entry gives the decision, the rationale and the
alternatives. Facts about a2a-sdk were checked on 2026-11-20 against a2a-sdk 1.3.1 (the version
in the CI venv), by reading the installed package and by two throwaway in-process spikes kept
outside the repository. "Checked" means a spike ran it; "read" means only the source was read.
Paths are inside the installed `a2a` package.

## R1. One execute call per message, one run per task

**Facts (checked):**
- a2a-sdk's request handler (`DefaultRequestHandlerV2`) calls `AgentExecutor.execute` once per
  client message. It keeps one `ActiveTask` per task id across messages.
- `execute` returns when the task reaches input-required, and the client's streaming request
  then ends by itself.
- The next message with the same `taskId` calls `execute` again. `context.current_task` is then
  the stored task, re-read from the store just before the call
  (`server/agent_execution/active_task.py:683-695`).

**Decision:**
- The door holds one core `Run` per task id, in memory.
- Each `execute` call reads run events until an `Ask` or the terminal event, writes them as A2A,
  and returns.
- The next call checks the answer and `deliver`s it to the same `Run`, then reads on.
- When the door has no `Run` for a task at input-required (after a restart), it calls
  `Driver.resume(thread, request, answer)`. A checkpoint source goes on; a live source gives
  `Error("lost")`, so the task ends failed (FR-020).

**Alternatives:**
- One `execute` call per run that waits inside for the answer. Rejected: a2a-sdk ends the call
  at input-required by design, and the waiting call would not survive a restart.
- A new `Run` per message. Rejected: a live source's `await` lives in the first `Run`.

## R2. The pending request is read from the task, not kept

**Facts (checked):**
- At input-required, `current_task.status.message` holds the request (its text Part, and its
  data Part with the R2C metadata).
- Once a later status replaces it, the earlier status message moves into `history`.
- A refusal (R2C-ASK-5, `a2a/refuse-wrong-id.json`) is an input-required status with text only.

**Decision:**
- The pending request is the newest R2C request Part found in `status.message`, then in
  `history`, newest first, agent messages only.
- It counts only while the task is at input-required.
- This is the only record of what a task waits for (FR-006), so a restart loses nothing.

**Alternatives:**
- An in-memory map from task to request. Rejected: lost on a restart, and a second source of
  truth.
- Re-sending the request in every refusal. Rejected: `a2a/refuse-wrong-id.json` shows a text-only
  refusal.

## R3. Activation and the echoed header

**Facts:**
- **(checked)** The request's `A2A-Extensions` header reaches the server as
  `ServerCallContext.requested_extensions`, and the executor reads it as
  `RequestContext.requested_extensions`.
- **(checked, read)** No part of a2a-sdk writes an `A2A-Extensions` response header. There is no
  "activated" set (only `server/routes/agent_card_routes.py` sets headers, ETag and
  Cache-Control). `required` is never enforced.
- **(checked)** For SSE, the response headers go out right after the first event.

**Decision:**
- Activation is decided before `execute`, from the request alone: R2C is active when the
  requested extensions contain `ext_r2c.URI`.
- A context builder (a subclass of `DefaultServerCallContextBuilder`) stores the decision in
  `call_context.state` and in the ASGI scope.
- A pure-ASGI middleware adds `A2A-Extensions: <uri>` to the response start when R2C is active
  (R2C-ACT-2).
- Both pieces ship in `ext_r2c.a2a`. The app builder (R15) installs them, so a remote owner
  cannot forget one.
- Hand-written executors read the same decision.

**Alternatives:**
- Overriding `JsonRpcDispatcher._create_response`. Rejected: a private method.
- Letting the executor mark activation when it first emits. Rejected: too late for headers on
  some paths.

## R4. The wire mapping

**Decision:** the full table is in [contracts/wire-mapping.md](contracts/wire-mapping.md). Its
main points:
- one activity per working status (R2C-A2A-3);
- the request in an input-required status (R2C-A2A-1);
- artifacts as artifact updates (R2C-A2A-5);
- the last usage held and sent in the next input-required and terminal status (R2C-A2A-4, O10);
- a new task starts with a `Task` event (a status update first is an error in a2a-sdk:
  `active_task.py:352-360`, checked).

**Alternatives:**
- A status of its own per usage. Rejected: noise, and O10 lets it ride with the next status.

## R5. Reply chunks

**Facts:**
- In `a2a/full-streamed-run.json`, the reply is one inline artifact with `response: true`.
- Its first chunk has `append: false` and later chunks `append: true`.
- The chunk marked `lastChunk: true` is sent **before** a final activity update. So the end of
  the reply is known to the source, not to the door.
- In `a2a/not-activated.json` the reply is the text of the completed status. The standard
  artifact there is a CSV file the source made.

**Decision:**
- **Core change:** `ReplyChunk` gains `last: bool = False`, an additive change to the core
  (spec 002's risk table foresaw event fields added by 003). A chunk with `last` sets
  `lastChunk`.
- **With activation:** the door streams the reply artifact as the example shows. Its id is
  `reply`, which is unique within a task.
- **Without activation:** the door gathers the reply text and sends it as the text of the next
  status message.
- The spec's assumption that said the opposite was corrected (2026-11-20).

**Alternatives:**
- The door closes the reply artifact with an empty chunk at the end. Rejected: an empty text
  Part, and it does not match the example.
- A one-event lookahead. Rejected: it cannot know that no more reply follows an activity.

## R6. Text of status messages the door writes

**Decision:** text that is not R2C data is the door's choice, and the replay compares only that
a text Part is present where R2C-CORE-4 requires one (R17).
- **Request and activity:** the text Part is `fallback_text`.
- **Terminal status:**
  - first, a refusal note if one is due (R8);
  - then, without activation, the gathered reply;
  - otherwise `Done.`, the error's reason, or `The run was cancelled.`
- **Input-required status:** a due refusal note, then any gathered reply, come before the
  request's fallback text.

**Alternatives:**
- A run event for free status text. Rejected for now: nothing in the examples needs it, since
  text is not compared. It can be added later without breaking anything.

## R7. Answer handling

**Decision:** on a message to a task at input-required, the door does the following in order:
1. **Size.** The message's R2C parts are measured with `check_size`. Too large → re-ask with
   the "too large" error.
2. **Finding the answer.** The door collects the message's R2C `answer` objects.
   - None, and R2C active → refuse in text (R2C-ASK-5).
   - None, and R2C not active → the text answer path (R9).
   - More than one for the pending `id` → refuse in text.
3. **Checking it.** `check_answer(answer, pending, now=clock())`, with problem code
   `caller_on_approval` dropped (O8, FR-012).
4. **Acting on the problems.**

| Code | Door does | Rule |
|---|---|---|
| `too_large`, `invalid_answer`, `invalid_value`, `invalid_args`, `not_offered` | re-ask: the same request, the same `id`, `errors` = `[p.as_error_item()]` | R2C-ASK-6 |
| `wrong_id` | refuse in text; still input-required; the request stays pending | R2C-ASK-5 |
| `expired` | deliver the expiry outcome (R8), and note the refusal for the next status | R2C-ASK-4, -5 |
| none | deliver the answer | — |

The client side keeps `caller_on_approval` (FR-022).

**Alternatives:**
- A core option `check_answer(..., roles=False)`. Rejected: filtering one code in the door is
  enough, and it changes no core signature.

## R8. Expiry

**Decision:**
- The door takes a `clock` (default: the current UTC time). It applies expiry when the next
  message for the task arrives, as `a2a/refuse-expired.json` shows: the task is still at
  input-required when the late answer comes.
- The run gets a declined answer, `answered_by: {role: "policy"}`, `note: "The request expired."`.
  A declined approval is a deny (R2C-ANSWER-3); a declined question means nobody answered.
- The late answer is refused in the text of the next status.
- No timer (spec Assumptions).

**Alternatives:**
- A timer per pending request. Rejected: it does not survive a restart; out of scope.

## R9. Text answers without activation (R2C-ASK-8)

**Decision:**
- A text-only reply is taken as the answer only when the pending request is a question with
  exactly one field of type `one` or `text`.
  - `one`: the text, stripped, must equal an option label (case-insensitively), or be any
    non-empty text when `other` is true.
  - `text`: any non-empty text.
- The built answer is `{field key: text}` with `answered_by: {role: "person"}`, and goes through
  the same `check_answer`.
- Otherwise, and always for an approval, the door asks again in text.

**Alternatives:**
- Accepting text for `bool` or `number` fields. Rejected: R2C-ASK-8 allows only `one` and
  `text`.

## R10. One unfinished task per context (O9)

**Facts:**
- **(checked)** a2a-sdk accepts a new task in a context that already has an unfinished one.
- **(checked)** `TaskStore.list(ListTasksRequest(context_id=...), call_context)` is
  owner-scoped.
- **(checked)** `TaskUpdater.reject()` ends a task in `TASK_STATE_REJECTED`, which a2a-sdk treats
  as terminal.

**Decision:** when `execute` starts a new task (no `current_task`) on a `contextId`:
1. The door lists the owner's tasks in that context through the same task store.
2. If one is working, input-required or auth-required, the door emits the `Task`, then rejects
   it with a text naming the unfinished task's id. The other task is untouched.
3. A lock per (owner, context) in the process stops two new tasks from both passing the check.
   Several replicas remain the remote owner's concern (a2a-sdk keeps active tasks per process).

**Alternatives:**
- A JSON-RPC error. Rejected by the maintainer (Q2).
- Routing the message into the unfinished task. Rejected by the maintainer.

## R11. Owners and threads

**Facts (checked):**
- `OwnerResolver = Callable[[ServerCallContext], str]`; the default `resolve_user_scope`
  returns `call_context.user.user_name`.
- With no authentication, every caller is `''`.
- Owner B reading owner A's task gets `TaskNotFoundError`.

**Decision:**
- The executor and the task store get **the same** resolver from the app builder (R15).
- The thread is `thread_id("a2a", resolver(context.call_context), context_id)`.
- Running without authentication is documented: every anonymous caller then shares an owner,
  and contexts alone separate them.

## R12. Numbers in protobuf `Value`

**Facts (checked):** a Part's `data` is a `google.protobuf.Value` and metadata is a `Struct`, so
every number comes back as a float (`3` → `3.0`).

**Decision:** the codec turns every float without a fractional part back into an int before it
parses an R2C object. `5200.0` → `5200` matches the schemas' `integer` and the examples' JSON.
A `number` field written `2.0` reads back as `2`, which is the same JSON number.

## R13. The agent card

**Facts (checked):** a2a-sdk serialises `AgentExtension(required=False)` without `required`,
since it is the protobuf default. The served card shows `{"uri": ..., "description": ...}`.

**Decision:**
- `agent_card(info, url, ...)` builds the card from `CardInfo`, with these settings:
  - `capabilities.streaming = True` (a2a-sdk refuses streaming otherwise);
  - one `AgentInterface(url, "JSONRPC", "1.0")`;
  - the R2C extension with `required=False`;
  - the skills.
- The standard gets one sentence in §11: an A2A SDK may leave out `required: false`, since it is
  the default; it means the same.
- The replay treats a field at its protobuf default the same as an absent field.

## R14. In-process transport for tests

**Facts (checked):**
- `httpx.ASGITransport` collects the whole response before returning
  (`httpx/_transports/asgi.py:128-185`).
- A stream cut and reattach test cannot run on it, and a subscribe at input-required yields
  nothing.

**Decision:**
- The tests use a small streaming ASGI transport, a test helper of about 80 lines that is not
  shipped. It runs the app in a task, streams body chunks, and sends `http.disconnect` when the
  client closes, so a cut is a real disconnect.
- No network port.
- uvicorn on a loopback port stays a fallback the tests do not need.

## R15. The app builder

**Decision:**
- `a2a_app(executor, card, *, task_store, owner_resolver)` returns a Starlette app with:
  - the agent card route and the JSON-RPC route;
  - the activation context builder and the echo middleware (R3);
  - one `DefaultRequestHandlerV2` whose store and executor share the resolver.
- `executor` is a `SourceExecutor` or any hand-written a2a-sdk executor.
- `Remote` (006) will mount the same pieces; this is the A2A-only way to serve.
- `[a2a]` becomes `a2a-sdk[http-server]>=1.3,<2`, because the routes need Starlette and
  sse-starlette (absent from a plain `a2a-sdk` install).

**Alternatives:**
- Leaving the assembly to every remote owner. Rejected: it is where a missing middleware or a
  second resolver breaks R2C-ACT-2 or R2C-ID-1 silently.

## R16. A durable store in the tests

**Facts:**
- a2a-sdk's `DatabaseTaskStore` needs SQLAlchemy and aiosqlite (`a2a-sdk[sqlite]`), absent from
  the venv.
- **(checked)** With a store that survives rebuilding the handler, a new handler loads the task at
  input-required and calls `execute` with it as `current_task`.

**Decision:**
- The dev group gets `a2a-sdk[http-server,sqlite]`.
- The restart test rebuilds the whole app (`handler.aclose()`, a new executor and driver) on the
  same SQLite file, using a real `DatabaseTaskStore`. The fake checkpoint source's store
  survives as well.
- No store ships with the package.

## R17. The example replay

**Decision:** every file in `standard/v1/examples/a2a/` runs in **client mode**, and every file
whose remote steps a source can produce runs in **door mode** too. The details are in
[contracts/replay.md](contracts/replay.md).
- **Client mode:** a wire executor sends the file's remote steps as they are. The door's client
  reads them, and its typed items and the messages it sends must equal the file's.
- **Door mode:** the file's remote steps become a scripted `AgentSource`, run in both pause
  styles. The wire the door writes must equal the file's.
- **Equality after normalising:**
  - generated ids are mapped;
  - timestamps and `messageId` are dropped;
  - protobuf defaults count as absent;
  - integral floats count as ints;
  - text Parts are checked for presence only.
- **Door-mode exemptions** are listed with their reason, and a test fails when the list and the
  converter disagree:
  - `agent-card.json`, compared as a card;
  - `unknown-kind-ignored.json`: a source cannot emit an unknown kind;
  - `artifact-no-metadata.json`: a data Part and no metadata, which no run event makes.
- `question-forwarded.json` runs with two in-process remotes: the front remote's source uses the
  client to call the second one and forwards the request with `origin`.

## R18. Helpers for a hand-written executor

**Decision:**
- An `R2CTask` object is built per `execute` call from the `RequestContext` and the
  `EventQueue`. It offers:
  - `active`;
  - `open()` (the first `Task` event, plus the R10 check when given the store);
  - `activity`, `reply`, `artifact`, `usage`, `ask`;
  - `take_answer()`, which re-asks or refuses by itself and returns only an acceptable answer or
    the expiry outcome;
  - `complete`, `fail`, `reject`, `cancelled`.
- `SourceExecutor` is written on top of `R2CTask` (FR-027).
- Its held usage is read back from the task's newest usage Part, so it survives a restart too.
