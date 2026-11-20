---
description: "Task list for 003-a2a-binding"
---

# Tasks: A2A binding (`ext_r2c.a2a`)

**Input**: design documents in `specs/003-a2a-binding/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII asks for tests first, against the installed wheel, and
bindings tested by real round trips. Every phase:
1. writes its tests first;
2. runs them, and confirms they fail for the expected reason;
3. only then writes production code.

**Organization**: the nine phases of the plan's delivery order. `/speckit-implement` runs **one
phase per go**: finish the phase, verify, commit, report, stop.
- Phases 1 and 2 have no story label: they are the setup and the foundation every story uses.
- The stories run in dependency order: US1 and US3 → US2 → US4 → US5 → US6 → US7.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US7 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `rm -rf dist && uv build`;
  2. recreate `../.ci-venv`, install the wheel and the `dev` group (Python 3.11);
  3. `../.ci-venv/bin/pytest -q -W error::UserWarning`;
  4. recreate `../.core-venv` with the wheel alone, run `../.core-venv/bin/python -I tests/core_only.py`;
  5. recreate `../.a2a-venv` with `wheel[a2a]`, run `../.a2a-venv/bin/python -I tests/a2a_only.py` (from phase 1 on);
  6. `uvx ruff check --select F src tests`;
  7. leak-scan the staged added lines (must be 0);
  8. commit with an explicit pathspec and no co-author trailer.

## Path conventions

- Package: `python/src/ext_r2c/a2a/`; core: `python/src/ext_r2c/core/`; tests: `python/tests/`
- Standard: `standard/v1/` (README, `examples/a2a/`)
- CI: `.github/workflows/python.yml`
- Example files are named without their folder below (`refuse-wrong-id.json` means
  `standard/v1/examples/a2a/refuse-wrong-id.json`).

---

## Phase 1: Packaging and test bed

**Goal**: `[a2a]` brings what the door needs. `ext_r2c.a2a` exists and imports only what it
may. `ReplyChunk.last` exists. The tests have a streaming in-process transport, test
authentication, and factories for an app and a client.

**Independent test**: `test_packaging.py`; `a2a_only.py` in `../.a2a-venv`; a trivial round
trip that sees events one by one.

- [X] T001 [P] Extend `python/tests/test_packaging.py`:
  - **`test_extras`:** the `a2a` extra requires `a2a-sdk[http-server]` with a version range
    `>=1.3,<2`.
  - **`test_a2a_imports_only_allowed_modules`:** AST over the installed `ext_r2c/a2a/`. Allowed:
    the standard library, `ext_r2c` (core only, never `ext_r2c.mcp`, `ext_r2c.bridges` or
    `ext_r2c.remote`), `a2a`, `google.protobuf`, `httpx`, `starlette`, `sse_starlette`,
    `pydantic`, and relative imports. A failure lists `file:line module`.
  - **`test_a2a_import_loads_no_other_door`:** a subprocess that imports `ext_r2c.a2a` loads no
    `mcp`, `langchain` or `langgraph`.
- [X] T002 [P] Create `python/tests/a2a_only.py`, a script that pytest does not collect. It:
  - imports `ext_r2c.a2a`;
  - asserts that no `mcp`, `langchain` or `langgraph` module is loaded;
  - prints `a2a only: ok`.

  Leave a `# phase 3:` comment where the app and card checks go (T030).
- [X] T003 [P] Add `test_reply_chunk_last` to `python/tests/test_agent_source.py`:
  - `ReplyChunk("x").last is False`;
  - `ReplyChunk("x", last=True).last is True`;
  - the dataclass stays frozen.
- [X] T004 Build, install, run the new tests. Confirm the expected failures:
  - the extra has no `http-server`;
  - `ext_r2c.a2a` is missing;
  - `ReplyChunk` has no `last`.
- [X] T005 Change `python/pyproject.toml`:
  - `a2a = ["a2a-sdk[http-server]>=1.3,<2"]`;
  - in the dev group, `a2a-sdk[http-server,sqlite]>=1.3,<2`.
- [X] T006 Create `python/src/ext_r2c/a2a/__init__.py`: a module docstring and an empty
  `__all__`.
- [X] T007 Add `last: bool = False` to `ReplyChunk` in `python/src/ext_r2c/core/events.py`, with
  a docstring line: the source sets it on the reply's final chunk (research R5).
- [X] T008 [P] Create `python/tests/a2a_transport.py` (research R14). It holds
  `StreamingASGITransport(app)`, an `httpx.AsyncBaseTransport` that:
  - runs the ASGI app in a task;
  - yields body chunks as they are sent;
  - sends `http.disconnect` when the response is closed.

  Add a module docstring that says why `httpx.ASGITransport` cannot be used.
- [X] T009 [P] Create `python/tests/a2a_harness.py` with:
  - **`BearerAuth`**: a Starlette `AuthenticationBackend` mapping `Authorization: Bearer <name>`
    to `SimpleUser(name)`.
  - **`serve(executor, card, *, store=None)`**: an async context manager that yields a running
    app. Until T030 it is a minimal one that uses a2a-sdk directly; T030 switches it to
    `a2a_app`.
  - **`a2a_client(app, card, *, user=None)`**: an a2a-sdk client over `StreamingASGITransport`,
    with the bearer header and a response hook that records headers.
  - **`TIMEOUT`**: 10 s, with `run(coro)` wrapping `asyncio.wait_for`, like
    `agent_source_suite._run`.

  *Note (2026-11-20):* `serve` yields a `Served` (app, handler, card, store), and
  `a2a_client(served, *, user=None)` takes it in place of `(app, card)`.
- [X] T010 Add `test_transport_streams_event_by_event` in `python/tests/test_a2a_transport.py`. A
  tiny executor emits a `Task` and three working statuses 0.1 s apart. The client must receive
  the first status before the executor emits the third.

  *Note (2026-11-20):* the test uses a handshake instead of sleeps, so it does not depend on
  timing. After the first status, the executor waits (up to 2 s) until the client signals that
  it has seen it. With `httpx.ASGITransport` in place, the test fails as it should.
- [X] T011 Add the A2A-only step to `.github/workflows/python.yml`, after the core-only step:
  `uv venv ../.a2a-venv`, `uv pip install "<wheel>[a2a]"`, then `python -I tests/a2a_only.py`.
- [X] T012 Verify, then commit `feat(003): a2a extra, test transport, ReplyChunk.last`.

---

## Phase 2: Codec (foundation)

**Goal**: R2C objects travel to and from A2A Parts and Artifacts unchanged. A stored Task gives
back its pending request and its last usage. Answers get their words. A text reply becomes an
answer only where R2C-ASK-8 allows.

**Independent test**: `test_a2a_codec.py`, against every R2C Part and artifact in the A2A
examples.

- [X] T013 [P] Create `python/tests/test_a2a_codec.py`, all tests first, with these test
  groups:
  - **Parts from the examples.** Every R2C Part in every A2A example is parsed with
    `google.protobuf.json_format.ParseDict` into `a2a.types.Part`. `read_part` gives the core
    object, and `r2c_part(obj)` written back equals the file's Part as JSON after normalising
    integral floats (research R12). The parametrised ids are `<file>#<step>.<part>`.
  - **Artifacts.** Every artifact update gives back the same `ArtifactMeta` (or `None` without
    metadata) and parts as core `Content`, and encodes back equal.
  - **Unknown and invalid.** The `provenance` Part in `unknown-kind-ignored.json` reads as
    `Unknown`; a Part whose data breaks its schema reads as invalid, and is skipped and counted.
  - **Pending and usage.** Built `Task` objects check `pending_request(task)`:
    - (a) at input-required with the request in `status.message`;
    - (b) after a text-only refusal (the request is in `history`);
    - (c) at working (gives `None`);
    - (d) after an accepted answer and a new ask (gives the newer request).
    `last_usage(task)` gives the newest usage.
  - **`answer_text`.** The question in `question-fields.json`, allow, deny, deny with a reason,
    edit, and declined, each against the text in `contracts/wire-mapping.md`.
  - **`text_answer` (R9).**
    - Accepted: `one` with an exact label, a label in another case, and other text when
      `other: true`; `text` with any non-empty text.
    - Refused (gives `None`): a `bool` field, two fields, an approval, and empty text.
- [X] T014 Run it; confirm it fails because `ext_r2c.a2a._codec` is missing.
- [X] T015 Create `python/src/ext_r2c/a2a/_codec.py`:
  - `r2c_part`, `read_part`, `read_parts` (yields core objects, `Unknown`, or a skip marker);
  - `artifact_update(...)` and `read_artifact(...)`;
  - `content_to_part` and `part_to_content` (text, raw, url);
  - `_ints(value)` (research R12);
  - `pending_request(task)` and `last_usage(task)` (research R2);
  - `answer_text(answer, request)`;
  - `text_answer(request, text)`.

  The URI comes from `ext_r2c.URI`.

  *Note (2026-11-20):*
  - The skip marker is `Invalid(kind, errors)`.
  - `read_artifact` gives `(meta, contents)`. A `data` Part has no core `Content`, so it is
    left out (`art-3` in `artifact-no-metadata.json`). How the client shows such a Part is
    decided in phase 6.
  - The round-trip tests compare protobuf messages: in protobuf, `20` and `20.0` are the same
    double, and `append: false` equals an unset field.
- [X] T016 Run `test_a2a_codec.py` until green, then the whole suite.
- [X] T017 Verify, then commit `feat(003): codec between R2C objects and A2A parts`.

---

## Phase 3: Serve a source, with and without activation (US1 and US3, P1)

**Goal**: a source served by `a2a_app` streams activities, the reply artifact, artifacts and
requests. It goes on after an answer and ends completed, failed or canceled. A client that did
not activate R2C gets text and standard artifacts only. The header is echoed only when R2C is
active.

**Independent test**: the two fakes of spec 002 over real round trips.

- [ ] T018 [P] [US1] Create `python/tests/test_a2a_serve.py`, parametrised over `CheckpointFake`
  and `LiveFake` from `fake_sources.py`. All of these run with activation:
  - **question** (`RunInput("Write the report")`):
    - the wire is: `Task`; a working status with the activity Part and its text; then
      input-required with the question Part and a text Part (R2C-A2A-1, R2C-CORE-4);
    - answering `q-1` gives reply artifact chunks (`artifactId` `reply`, `response: true`), then
      completed with the usage Part (R2C-A2A-4);
    - the source's `answers == [answer]`.
  - **approval allowed**; **approval denied** with a reason (the reply text carries it); and
    **declined**.
  - **cancel while paused:** `CancelTask` gives canceled. The live fake saw a declined answer;
    the checkpoint fake saw none.
  - **same wire for both styles:** the two wires are equal after normalising ids (SC-002).
- [ ] T019 [P] [US3] Create `python/tests/test_a2a_activation.py`:
  - **card:** `agent_card(CardInfo(...), url)` lists the R2C URI with `required` false (it may
    be omitted on the wire) and `streaming: true`. Compare it with `agent-card.json` in card
    mode (contracts/replay.md).
  - **echo:** with the header, the response echoes it (on the first stream and on the answer's
    stream).
  - **not active**, with the same fake and no header:
    - no Part, Artifact or Message carries R2C data or metadata;
    - the question comes as text in input-required;
    - the reply comes as the completed status text;
    - no `reply` artifact;
    - no echoed header (SC-004).
  - **reasoning:** a reasoning `ActivityEvent` is sent only when active.
  - **text answer when not active** (`text-answer-not-activated.json` flow): a one-field `one`
    question answered "South" goes on. "Somewhere" is asked again in text. An approval is never
    taken from text.
- [ ] T020 Run both files; confirm they fail on the missing `a2a_app`, `SourceExecutor` and
  `agent_card`.
- [ ] T021 [US3] Create `python/src/ext_r2c/a2a/activation.py` (research R3):
  - `R2CContextBuilder` stores `active` in `call_context.state` and in the ASGI scope;
  - `EchoExtensions` is a pure ASGI middleware that adds `A2A-Extensions` on
    `http.response.start`;
  - `is_active(context)`.
- [ ] T022 [P] [US3] Create `python/src/ext_r2c/a2a/card.py` with `agent_card(...)`
  (research R13).
- [ ] T023 [US1] Create `python/src/ext_r2c/a2a/task.py`, `R2CTask` with its emitting side
  (contracts/wire-mapping.md): `open` (without the store check yet), `activity`, `reply`,
  `artifact`, `usage` (held), `ask`, `complete`, `fail`, `cancelled`. It handles:
  - the gathered reply when not active;
  - the size check on outgoing content (R2C-SAFETY-4).

  `take_answer` is a stub here: it delivers only a well-formed answer whose `id` matches; the
  rest comes in phase 4.
- [ ] T024 [US1] Create `python/src/ext_r2c/a2a/executor.py`, `SourceExecutor` (research R1):
  - a `Driver` and a task-id → `Run` map;
  - `execute` reads events until `Ask` or the end, through `R2CTask`;
  - `cancel` calls `Run.cancel` and emits canceled;
  - `bind(store, resolver)`.
- [ ] T025 [US1] Create `python/src/ext_r2c/a2a/app.py`, `a2a_app(...)` (research R15):
  - the card route and the JSON-RPC route;
  - `R2CContextBuilder` and `EchoExtensions`;
  - one `DefaultRequestHandlerV2`;
  - `executor.bind(...)` when the executor is a `SourceExecutor`.
- [ ] T026 Export the public names in `python/src/ext_r2c/a2a/__init__.py`.
- [ ] T027 Run `test_a2a_serve.py` and `test_a2a_activation.py` until green.
- [ ] T028 [US1] Switch `a2a_harness.serve` to `a2a_app`; re-run `test_a2a_transport.py`.
- [ ] T029 Run the whole suite.
- [ ] T030 In `a2a_only.py`, build `agent_card` and `a2a_app` for a trivial source, and assert
  the card JSON lists the URI.
- [ ] T031 Verify, then commit `feat(003): serve an agent source over A2A`.

---

## Phase 4: Answers (US2, P1)

**Goal**: no bad answer reaches the agent. Re-ask with `errors`, refuse in text, apply expiry,
and take every `answered_by` role as given.

**Independent test**: `test_a2a_answers.py`; after each case the source has received nothing
(or the expiry outcome) and the next status is the one the standard names.

- [ ] T032 [P] [US2] Create `python/tests/test_a2a_answers.py`, with the checkpoint and live
  fakes, all activated:
  - **empty required field** (`reask-empty-required.json`): input-required again with the same
    `id` and `errors[0].key == "title"`; the source has no answer; a good answer afterwards
    completes the task (R2C-ASK-6).
  - **wrong `id`** (`refuse-wrong-id.json`): input-required, text only; `q-1` is still pending,
    and its later answer works (R2C-ASK-5).
  - **expired approval** (`refuse-expired.json`), with the clock 5 minutes past `expires_at`:
    - the source gets a declined answer with role `policy`;
    - the run completes;
    - the completed status text says the answer came too late.
  - **edit with bad args:** re-ask with `errors` on `args`. **Edit not offered:** re-ask keyed
    `decision`.
  - **not well formed:** an answer Part missing `outcome` is re-asked.
  - **too large:** an answer of 6 MiB is re-asked with the too-large error.
  - **several answers** for `q-1` in one message: refused in text.
  - **text only while active:** refused in text; still pending.
  - **roles (O8):** each of these answers is delivered to the source as it is (FR-011):
    - an approval answered by `caller`;
    - an approver approval answered by `policy`;
    - a question answered by `policy`.
  - **counts:** a table-driven assertion that the source's `answers` grew only on the accepted
    and expiry cases (SC-003).
- [ ] T033 Run it; confirm the failures are the expected ones (the stub delivers bad answers).
- [ ] T034 [US2] Implement `R2CTask.take_answer` in `python/src/ext_r2c/a2a/task.py`. It follows
  research R7–R9, with these points:
  - the size check comes first;
  - answer Parts are collected;
  - `check_answer(..., now=clock())` runs, with `caller_on_approval` dropped;
  - each problem code is routed per R7;
  - the expiry outcome and its refusal note follow R8;
  - the not-active path is `text_answer`.
- [ ] T035 [US2] Use `take_answer` in `SourceExecutor` on every message to a task at
  input-required. Pass the clock and the limits through.
- [ ] T036 [US2] In `standard/v1/README.md`, add the O8 text to R2C-ANSWER-6 (plan "Changes to the
  standard"). In `specs/001-standard-v1/research.md`, the O8 note gets "written into R2C-ANSWER-6".
- [ ] T037 Run `test_a2a_answers.py` until green, then the whole suite (including `test_rules.py`).
- [ ] T038 Verify, then commit `feat(003): answers checked, re-asked or refused`.

---

## Phase 5: Threads, a second task, restart (US4, P1)

**Goal**: two owners never share a thread. A second unfinished task in a context is rejected. A
follow-up opens a new task on the same thread. A paused checkpoint run survives a restart on a
durable store; a live one ends with "lost".

**Independent test**: `test_a2a_threads.py` and `test_a2a_restart.py`.

- [ ] T039 [P] [US4] Create `python/tests/test_a2a_threads.py`:
  - **owners:**
    - Alice and Bob both send `contextId: "ctx-1"`;
    - the source records two different `ctx.thread_id` values, each equal to
      `thread_id("a2a", owner, "ctx-1")`;
    - Bob's `GetTask` on Alice's task gives `TaskNotFoundError` (SC-005).
  - **second task (O9):**
    - while task A waits at input-required, Alice sends `contextId` only;
    - the new task is `REJECTED`, its status text names A's id;
    - A is still input-required and its answer still works;
    - Bob with the same `contextId` is **not** rejected.
  - **after the end:** once A is completed, a message with the same `contextId` opens task B on
    the same thread (`follow-up-context.json` flow).
  - **race:** two new messages sent at once on one context give one running task and one
    rejected task.
- [ ] T040 [P] [US4] Create `python/tests/test_a2a_restart.py`:
  - **setup:** `DatabaseTaskStore` on `sqlite+aiosqlite:///{tmp_path}/tasks.db`; a
    `CheckpointFake` whose store dict outlives the app.
  - **checkpoint:** pause at `q-1`, then:
    1. `handler.aclose()` and drop the app;
    2. build a new app, executor and fake on the same store and dict;
    3. answer;
    4. check that the task completes and the source received the answer (SC-006).
  - **live:** the same with `LiveFake`; the task ends failed and its text contains "lost".
  - **re-ask after restart:** a bad answer sent after the restart is re-asked from the stored
    request (R2).
- [ ] T041 Run both; confirm the failures are the expected ones (no rejection; the restart
  answer reaches no run).
- [ ] T042 [US4] In `R2CTask.open`, given the store, list the owner's tasks in the context, and
  reject the new task when one is unfinished. Add a lock per (owner, context) (research R10).
  `SourceExecutor` passes its bound store and resolver.
- [ ] T043 [US4] In `SourceExecutor`:
  - the thread is `thread_id("a2a", resolver(call_context), context_id)`;
  - a paused task without a `Run` goes through `Driver.resume(thread, pending, answer)` (R1);
  - the held usage is restored with `last_usage(current_task)`.
- [ ] T044 [US4] Add `standard/v1/examples/a2a/second-task-rejected.json`:
  - the steps: task-1 at input-required, the new message with `contextId` only, then the
    `Task` and the rejected status naming `task-1`;
  - rules `R2C-ID-2`, `R2C-A2A-7`.

  Add the R2C-ID-2 text to `standard/v1/README.md`, and the "written into" note on O9 in
  `specs/001-standard-v1/research.md`.
- [ ] T045 Run both files until green, then the whole suite (example validation included).
- [ ] T046 Verify, then commit `feat(003): threads per owner, one unfinished task, restart`.

---

## Phase 6: The caller's client (US5, P2)

**Goal**: a caller reads typed items, answers, reattaches and fetches safely.

**Independent test**: `test_a2a_client.py` against the door from phases 3–5.

- [ ] T047 [P] [US5] Create `python/tests/test_a2a_client.py`:
  - **reading:** `R2CClient.send` over the question flow yields `TaskItem`, `StatusItem`,
    `ActivityItem`, `StatusItem`, `RequestItem` in order. The client sets `pending`, `task_id`
    and `context_id`, and `active` is true.
  - **unknown kind:** a wire executor sends `unknown-kind-ignored.json`; the client yields the
    activity and `skipped == 1`.
  - **answer:**
    - a bad answer raises `AnswerRejected` and nothing is sent (a counting hook on the
      transport);
    - an approval answered as `caller` raises `AnswerRejected` (FR-022);
    - a good answer sends one message with `taskId`, `contextId`, the text Part (from
      `answer_text`) and the answer Part, then yields the rest.
  - **reattach:**
    - cut the first stream after the activity;
    - `reattach()` yields a `TaskItem` snapshot, then the following items, and stops at
      input-required;
    - after the answer, `get_task()` gives the artifacts and the last status with usage
      (`resubscribe.json` flow).
  - **fetch:** a wire executor sends two `file` artifacts, one at the connection's own origin
    and one at `https://other.example.com/x`.
    - The first gives bytes. The second gives a `Link`, and the transport saw 0 requests to
      `other.example.com` (SC-008).
    - A same-origin file over `Limits(file_bytes=10)` gives `TooLarge`, and reading stops at the
      limit.
  - **cancel:** `cancel()` gives a canceled `StatusItem`.
- [ ] T048 Run it; confirm it fails because `R2CClient` is missing.
- [ ] T049 [US5] Create `python/src/ext_r2c/a2a/client.py` (contracts/a2a-api.md). It holds:
  - the item dataclasses;
  - `R2CClient`, built on a2a-sdk `ClientFactory`;
  - the header through `ServiceParametersFactory` and `with_a2a_extensions`;
  - the echoed header through an httpx response hook;
  - the end of `reattach` at input-required or terminal;
  - `fetch` with the origin compared on scheme, host and port, and a streamed read that stops
    at the limit;
  - `AnswerRejected`.

  Export the names.
- [ ] T050 Run `test_a2a_client.py` until green, then the whole suite.
- [ ] T051 Verify, then commit `feat(003): the caller's A2A client`.

---

## Phase 7: A hand-written executor with R2C helpers (US6, P2)

**Goal**: an a2a-sdk executor that is not an `AgentSource` speaks R2C through `R2CTask` and
gets the same wire and the same answer rules.

**Independent test**: `test_a2a_helpers.py`.

- [ ] T052 [P] [US6] Create `python/tests/test_a2a_helpers.py`. Its `HandWritten(AgentExecutor)`
  uses only a2a-sdk and `R2CTask`:
  - it asks `q-1`, delivers one `file` artifact, reports usage, and completes;
  - on the answer message, it calls `take_answer()` and returns when it gives `None`.

  The tests:
  - **same wire:** activated, the R2C wire equals `SourceExecutor`'s for a scripted source with
    the same events (SC-007).
  - **not active:** the wire is text only.
  - **bad answer:** an empty required field is re-asked by the helper, and `HandWritten` never
    sees it.
  - **second task:** `open(store=...)` rejects a second unfinished task.
- [ ] T053 Run it. Report what fails; if nothing fails, say so: the helpers already exist since
  phase 3, so this phase may be green at once. In that case, record that the tests are
  regression guards.
- [ ] T054 [US6] Fix any gap the tests show. Write the docstrings of `R2CTask` and its methods,
  following the order of contracts/a2a-api.md "An executor written by hand".
- [ ] T055 Verify, then commit `test(003): a hand-written executor with R2C helpers`.

---

## Phase 8: The example replay and the rest of the standard (US7, P1)

**Goal**: every A2A example is a real round trip (contracts/replay.md). The standard records
O10 and the card note.

**Independent test**: `test_a2a_replay.py`, one test per file and mode.

- [ ] T056 [US7] Add to `standard/v1/examples/a2a/` the file `usage-with-activity.json`:
  - a `step` activity whose `label` changes between running and done;
  - a usage Part in the done activity's working status;
  - rules `R2C-A2A-4`, `R2C-ACTIVITY-2`, `R2C-USAGE-2`.

  Add the O10 text to R2C-ACTIVITY-2 and R2C-A2A-4, and the `required: false` note to §11 of
  `standard/v1/README.md`. Add the "written into" note on O10 in
  `specs/001-standard-v1/research.md`.
- [ ] T057 [P] [US7] Extend `python/tests/a2a_harness.py`:
  - **`WireExecutor(steps)`:** emits a file's remote steps as they are, one `execute` call per
    client step.
  - **`script_from_example(example)`:** the converter of contracts/replay.md. It returns a
    scripted source definition, or raises `NotScriptable(reason)`.
  - **`ScriptedSource(script, pause)`:** a checkpoint or live source.
  - **`normalise(event_json, idmap)`.**
  - **`sample_answer(request)`:** a valid answer, for files with no client step after a request.
- [ ] T058 [US7] Create `python/tests/test_a2a_replay.py`:
  - **`client:<file>`:** for every A2A file.
  - **`door:<file>:<pause>`:** for every file not in `DOOR_EXEMPT`, for both pause styles.
  - **`test_exemptions_are_exact`:** the converter raises `NotScriptable` exactly for the
    `DOOR_EXEMPT` files.
  - **card mode:** for `agent-card.json`.
  - **special flows:** `question-forwarded.json` with two remotes, `resubscribe.json` with a
    cut, `follow-up-context.json`.

  Add the replay line to `pytest_terminal_summary` in `python/tests/conftest.py` (quickstart §2).
- [ ] T059 Run it. Record every failing file with its first difference; each is a door or client
  bug, or a converter bug. Do not add exemptions for them.
- [ ] T060 [US7] Fix the failures at their cause: the door, the client, or the converter.
  Change an example only if it breaks the standard. Any change goes into the notes at the end of
  this file.
- [ ] T061 Run the whole suite. Check that every `wire` rule still has an example
  (`test_rules.py`).
- [ ] T062 Verify, then commit `feat(003): every A2A example replayed in process`.

---

## Phase 9: Docs and final gate

**Goal**: the docs say what exists. The suite passes on all three Pythons. An outside review is
done.

- [ ] T063 [P] Update the docs:
  - **`ARCHITECTURE.md`:** list the `a2a/` modules, and the test bed (`a2a_transport.py`,
    `a2a_harness.py`).
  - **`python/README.md`:** serving a source with `a2a_app`; a hand-written executor with
    `R2CTask`; the caller's `R2CClient`; the limits (anonymous owner, `String(36)` context ids
    on SQL stores, expiry applied on the next message).
  - **`CHANGELOG.md`:** under Added, the A2A door, the client and `ReplyChunk.last`; under
    Changed, R2C-ANSWER-6, R2C-ID-2, R2C-ACTIVITY-2, R2C-A2A-4, the §11 note and the two new
    examples.
- [ ] T064 [P] Update the remaining records:
  - **`WORKSTATE.md`:** 003 closed; next `004-mcp-binding`.
  - **`docs/whitepaper.md`:** wherever it names the A2A door's API.
  - **`specs/002-python-core/contracts/core-api.md`:** a dated note for `ReplyChunk.last`.
- [ ] T065 Run the verify steps on Python 3.11, 3.12 and 3.13 (SC-009).
- [ ] T066 Get an outside review of the 003 diff: the `code-reviewer` agent, briefed with the
  range, the spec and the contracts. Fix what it confirms, and record what was left with a
  reason in `research.md` "Outside review".
- [ ] T067 Tick every task, and add "Notes: where reality differed" at the end of this file.
- [ ] T068 Verify, then commit `chore(003): close the A2A binding`.

---

## Dependencies

```
Phase 1 ──▶ Phase 2 ──▶ Phase 3 (US1, US3) ──▶ Phase 4 (US2) ──▶ Phase 5 (US4)
                              │                      │
                              └──▶ Phase 6 (US5) ◀───┘ (round trips need 3; answers need 4)
                                                     └──▶ Phase 7 (US6)
Phases 3–7 ──▶ Phase 8 (US7) ──▶ Phase 9
```

- **US1 and US3** share the executor and land together.
- **US2** needs the emitting side.
- **US4** needs `take_answer` (re-ask after restart).
- **US5** needs a door to talk to.
- **US6** needs `take_answer`.
- **US7** needs everything.

## Parallel opportunities

- **Phase 1:** T001, T002 and T003 (three test files); then T008 and T009 (two helper files).
- **Phase 3:** T018 and T019 (two test files); T022 alongside T021.
- **Phase 5:** T039 and T040.
- **Phase 8:** T057 can be written while T056 is reviewed.
- **Phase 9:** T063 and T064.
- **Not parallel:** anything that edits `task.py` or `executor.py` (phases 3, 4, 5).

## Implementation strategy

- **MVP:** phases 1–3, a source served over A2A with and without R2C.
- Phases 4 and 5 make it safe to put in front of real callers.
- Phase 6 gives callers their side.
- Phase 8 is the proof against the standard.
- Each phase ends with a commit and a report. The maintainer says "tiếp" for the next one.
