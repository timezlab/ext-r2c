---
description: "Task list for 004-mcp-binding"
---

# Tasks: MCP binding (`ext_r2c.mcp`)

**Input**: design documents in `specs/004-mcp-binding/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII asks for tests first, run against the installed wheel,
with bindings tested by real round trips. In every phase:
1. write the phase's tests first;
2. run them and confirm they fail for the expected reason;
3. only then write production code.

**Organization**: the nine phases of the plan's delivery order. `/speckit-implement` runs **one
phase per go**: finish the phase, verify, commit, report, stop.
- Phases 1 and 2 have no story label. They are the setup and the foundation every story uses.
- The stories run in dependency order: US1 and US4 → US2 → US3 → US5 → US6 → US7.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US7 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `rm -rf dist && uv build`;
  2. recreate `../.ci-venv`, install the wheel and the `dev` group (Python 3.11);
  3. `../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider`;
  4. `../.core-venv` with the wheel alone: `python -I tests/core_only.py`;
  5. `../.a2a-venv` with `wheel[a2a]`: `python -I tests/a2a_only.py`;
  6. `../.mcp-venv` with `wheel[mcp]`: `python -I tests/mcp_only.py` (from phase 1 on);
  7. `uvx ruff check --select F src tests`;
  8. leak-scan the staged added lines (must be 0);
  9. commit with an explicit pathspec and no co-author trailer.

## Path conventions

- Package: `python/src/ext_r2c/mcp/`; tests: `python/tests/`
- Standard: `standard/v1/` (README, `examples/mcp/`)
- CI: `.github/workflows/python.yml`
- Example files are named without their folder (`tool-result.json` means
  `standard/v1/examples/mcp/tool-result.json`).
- `key` means `io.github.timezlab/r2c` (`ext_r2c.MCP_KEY`).

---

## Phase 1: Packaging, test bed and spike

**Goal**:
- `[mcp]` is pinned, and `ext_r2c.mcp` exists and imports only what it may.
- The tests have a streaming, recording transport for `httpx2`, owners per bearer token, and
  server and client factories.
- The SDK facts the design leans on are pinned by tests.

**Independent test**: `test_packaging.py`; `mcp_only.py` in `../.mcp-venv`; `test_mcp_spike.py`.

- [X] T001 [P] Extend `python/tests/test_packaging.py`:
  - **`test_extras`**: the `mcp` extra requires `mcp` with the range `>=2.3,<3`.
  - **`test_mcp_imports_only_allowed_modules`**: an AST scan over the installed `ext_r2c/mcp/`.
    - Allowed: the standard library; `ext_r2c` (core only, never `ext_r2c.a2a`,
      `ext_r2c.bridges` or `ext_r2c.remote`); `mcp`, `mcp_types`, `anyio`, `httpx2`, `starlette`,
      `pydantic`, `jsonschema`; relative imports.
    - A failure lists `file:line module`.
  - **`test_mcp_import_loads_no_other_door`**: a subprocess that imports `ext_r2c.mcp` loads no
    `a2a`, `langchain` or `langgraph` module.
- [X] T002 [P] Create `python/tests/mcp_only.py`, a script that pytest does not collect. It:
  - imports `ext_r2c.mcp`;
  - asserts that no `a2a`, `langchain` or `langgraph` module is loaded;
  - prints `mcp only: ok`.

  Leave a `# phase 3:` comment where the server and discover checks go (T040).
- [X] T003 Build, install, and run the new tests. Confirm the expected failures: the extra has no
  upper bound, and `ext_r2c.mcp` is missing.
- [X] T004 Change `python/pyproject.toml`: `mcp = ["mcp>=2.3,<3"]`.
- [X] T005 Create `python/src/ext_r2c/mcp/__init__.py`, with a module docstring and an empty
  `__all__`.
- [X] T006 [P] Create `python/tests/mcp_transport.py` (research R15) with
  `StreamingASGITransport(app, *, record=None)`, an `httpx2` async transport that:
  - runs the ASGI app in a task group the transport owns;
  - yields body chunks as they are sent;
  - sends `http.disconnect` when the response is closed;
  - when `record` is a list, appends every JSON-RPC message in both directions, as
    `("client" | "remote", dict)`, parsing SSE `data:` frames.

  Its module docstring says why `httpx2.ASGITransport` cannot be used.
- [X] T007 [P] Create `python/tests/mcp_harness.py` with:
  - **`StubVerifier`**: a `TokenVerifier` that maps `Bearer <name>` to an `AccessToken` with
    `subject=<name>`, `client_id="test"` and `iss="https://idp.example.com"`. If the spike
    (T010) shows the SDK's bearer path cannot be used in process, it is replaced by an ASGI
    middleware that sets `auth_context_var` (research R15).
  - **`serve(server, *, record=None)`**: an async context manager that enters
    `server.session_manager.run()` and yields a `Served` (app, server, record).
  - **`mcp_session(served, *, user=None, active=True, form=True, message_handler=None)`**: an MCP
    SDK `Client` over `StreamingASGITransport`, with:
    - `base_url="http://127.0.0.1:8000"`;
    - the bearer header;
    - `advertise(MCP_KEY, {})` when `active`;
    - an `elicitation_callback` that raises, when `form`.
    It is used raw, through `client.session`.
  - **`TIMEOUT`** of 10 s, with `run(coro)`, as in `a2a_harness`.
- [X] T008 Add `test_transport_streams_progress_before_result` to
  `python/tests/test_mcp_transport.py`. A lowlevel tool sends one progress notification, then
  waits (up to 2 s) until the client signals that it has seen it, then returns. With
  `httpx2.ASGITransport` in its place, the test fails.
- [X] T009 Write `python/tests/test_mcp_spike.py`. Each test pins one SDK fact the design leans
  on; a failing one stops the phase and updates the plan first.
  1. `test_interceptor_short_circuits_before_argument_validation`: a bound stub tool with no
     parameters is called with arguments; the interceptor answers, and the stub never runs (R1).
  2. `test_middleware_rewrites_tools_list_schema`: a server middleware replaces one tool's
     `inputSchema` in `tools/list` (R1).
  3. `test_interceptor_input_required_is_sealed_and_unsealed`: the interceptor returns plaintext
     state; the wire shows a `v1.` token; the retry shows the plaintext again (R3).
  4. `test_replayed_state_runs_twice`: the same retry sent twice reaches the interceptor twice.
     This is the fact the ledger exists for (R3).
  5. `test_principal_from_bearer`: `authenticated_principal` differs for `Bearer alice` and
     `Bearer bob`, and bob's replay of alice's state gets `-32602` (R5, R15).
  6. `test_progress_with_meta`: a notification built by hand with `_meta` reaches the client's
     `message_handler` with `params.meta` intact, before the result (R8).
  7. `test_raw_input_required_on_client`: `session.call_tool(..., allow_input_required=True)`
     returns the `InputRequiredResult`, never calls the elicitation callback, and a retry sends
     `requestState` byte for byte (R13).
  8. `test_client_capabilities_per_request`: the server sees `extensions[key]` and `elicitation`
     in each request's capabilities, and not `extensions[key]` from a client that did not
     advertise it (R5).
- [X] T010 Run T008 and T009 on the wheel. Fix the harness, not the facts. If a fact does not
  hold, stop and update `research.md` and `plan.md` before going on.
- [X] T011 Add the MCP-only step to `.github/workflows/python.yml`, after the A2A-only step:
  `uv venv ../.mcp-venv`, `uv pip install "<wheel>[mcp]"`, `python -I tests/mcp_only.py`.
- [X] T012 Verify, then commit `feat(004): mcp extra, test transport, SDK spike`.

---

## Phase 2: Codec and stopping point (foundation)

**Goal**: R2C objects travel to and from MCP results, notifications and content blocks
unchanged. The message rule is one function. An answer turns into an elicitation response and
back. The stopping point round-trips through JSON, and a round is claimed once.

**Independent test**: `test_mcp_codec.py` over every MCP example.

- [ ] T013 [P] Write `python/tests/test_mcp_codec.py`, decoding part:
  - for every MCP example, every R2C object in a result `_meta`, an `input_requests` wrapper, a
    progress `_meta` or a content block `_meta` decodes to its core model and encodes back equal;
  - `read_input_required(result)` gives one `RequestItem`-like record per entry: key, R2C object
    (or `None` in `not-activated.json`), message and schema;
  - `read_result(result)` gives the reply, the artifacts with their presentation and the usage
    of `tool-result.json`.
- [ ] T014 [P] Add the encoding part to `test_mcp_codec.py`:
  - `input_required(request, state, *, active, usage)` for the requests of
    `elicitation-question.json`, `…-other.json`, `…-many-other.json` and
    `elicitation-approval*.json` equals the file's result, apart from `requestState` and the
    approval messages O5 corrects (marked xfail until T083);
  - without `active` there is no `_meta`;
  - with `usage` it sits beside `input_requests`.
- [ ] T015 [P] Add `test_message_rule` to `test_mcp_codec.py` (research R7). Cover: title only;
  title and description; with `origin` (`Inventory agent asks: …`); a re-ask with two errors; a
  refusal sentence first.
- [ ] T016 [P] Add `test_progress_notification` to `test_mcp_codec.py`:
  - `progress_params(activity, token, n, *, active)` equals the two notifications of
    `progress-activity.json`;
  - without `active` there is no `_meta`.
- [ ] T017 [P] Add `test_content_blocks` to `test_mcp_codec.py`, one case per row of
  [wire-mapping.md](contracts/wire-mapping.md#the-final-result), including:
  - the `urn:r2c:artifact:<id>` uri for bytes without a url;
  - `image` and `audio` for inline media (O7);
  - an embedded resource for other inline bytes.
- [ ] T018 [P] Add `test_mcp_response_inverts_answer_from_mcp` to `test_mcp_codec.py`. For each
  example's derived answer (from its description), `answer_from_mcp(request,
  *mcp_response(request, answer))` equals the answer. Cover:
  - `other` text for a `one` field;
  - extra values for a `many` field;
  - `edit` with args;
  - `declined`.
- [ ] T019 [P] Write `python/tests/test_mcp_state.py`:
  - the stopping point round-trips through `dump`/`load`;
  - an unknown `v` raises `LostState`;
  - `MemoryLedger.claim` gives True once per nonce, False after, and True again once the entry
    is past its expiry and swept.
- [ ] T020 Run T013–T019. They fail with `ImportError` (no `_codec`, no `_state`).
- [ ] T021 Implement `python/src/ext_r2c/mcp/_codec.py`:
  - `message`;
  - `input_required`;
  - `read_input_required`;
  - `progress_params`;
  - `content_block` and `read_block`;
  - `final_result` (refusal text, reply, artifacts, usage, `structuredContent`, `isError`);
  - `read_result`;
  - `mcp_response`.

  The block mapping lives in one table, and the size of gathered output is checked with the
  core's `check_size`.
- [ ] T022 Implement `python/src/ext_r2c/mcp/_state.py`:
  - `StoppingPoint` (a frozen dataclass, fields as in
    [data-model.md](data-model.md#stopping-point));
  - `dump`, `load` and `LostState`;
  - the `RoundLedger` protocol;
  - `MemoryLedger` (a dict of nonce to expiry, swept on each claim).
- [ ] T023 Verify, then commit `feat(004): the MCP codec and the stopping point`.

---

## Phase 3: Serve a source as a tool (US1 and US4, P1) 🎯 MVP

**Goal**: an `AgentSource` is one MCP tool. A question or an approval goes out as one form
elicitation. The answer comes back derived. The final result has the reply, artifacts and usage.
A client without R2C gets plain MCP. A client without forms gets `declined`.

**Independent test**: the fakes of 002 served in process; a raw MCP SDK session answers; the
same flows without activation and without forms.

- [ ] T024 [P] [US1] Write `python/tests/test_mcp_serve.py` (story 1, scenarios 1–2). Both fakes
  of 002, parametrised by pause style, are served as `SourceTool(fake)`. An active session calls
  `agent` with `{"message": "Write the report"}`. Check:
  - one `inputRequests` entry keyed by the question's `id`;
  - a flat `requestedSchema` equal to `mcp_form(question)`;
  - the question in `_meta[key].input_requests[id]`;
  - the retry with `accept` delivers `answer_from_mcp`'s answer to the fake, with
    `answered_by.role == "person"`;
  - the call completes.
- [ ] T025 [P] [US1] Add to `test_mcp_serve.py`:
  - **`other`**: a merged value (scenario 3).
  - **Decline and cancel**: each gives `declined`, and the run goes on (scenario 4).
  - **Approval**: deny with a reason reaches the fake.
- [ ] T026 [P] [US1] Add `test_two_questions_one_after_the_other` (scenario 5). A scripted source
  asks `q-1`, then `q-2`:
  - each input-required result has exactly one entry;
  - the second carries the usage so far beside `input_requests`, after the source yields one
    (O6);
  - the final usage is the latest.
- [ ] T027 [P] [US1] Add `test_final_result` (scenario 6). A scripted source yields reply chunks,
  a file artifact by url, an inline text artifact and usage, with an ask in the middle:
  - the reply is one `text` block marked `response: true`;
  - the output from before the ask is in the final result;
  - the usage is in `_meta[key]`;
  - the default tool's result has `structuredContent.context_id`.
- [ ] T028 [P] [US1] Add `test_same_wire_for_both_pause_styles` (scenario 7). The two runs'
  recorded wires are equal once `requestState` is mapped.
- [ ] T029 [P] [US1] Add `test_cancel` (spec Edge Cases). The client cancels the round while the
  live fake runs: the fake sees `ctx.cancelled`, and its paused ask gets `declined`.
- [ ] T030 [P] [US1] Add `test_source_error` (spec Edge Cases). A source that raises gives
  `isError: true`, its reason as text, and the last usage.
- [ ] T031 [P] [US4] Write `python/tests/test_mcp_activation.py`:
  - **discover**: `server/discover` lists `key` with `{"revision": 1}` (scenario 1).
  - **active**: an active round's results and notifications carry R2C `_meta` (scenario 2).
  - **not active**: the same flow from an inactive session has the same elicitation (form and
    message), the answer is still derived and checked, the run completes, and there is no R2C
    `_meta` anywhere on the recorded wire (scenario 3, SC-006).
  - **no reasoning**: a reasoning activity is not sent to an inactive session.
- [ ] T032 [P] [US4] Add `test_no_form_support` (scenario 4). With a session that declares no
  elicitation, the fake's question is answered `declined` by the door, and the run goes on with
  no input-required result.
- [ ] T033 [P] [US4] Add `test_activation_per_round` (scenario 5). The first round is active and
  the retry is not: the retry's result has no R2C `_meta`.
- [ ] T034 [P] [US1] Add `test_progress_only_with_token`. Activities arrive as progress,
  numbered from 1, only when the round carried a token (R2C-MCP-6).
- [ ] T035 Run T024–T034. They fail with `ImportError`.
- [ ] T036 [US1] Implement `python/src/ext_r2c/mcp/activation.py`: `is_active`,
  `form_supported`, `owner_of` (research R5).
- [ ] T037 [US1] Implement `python/src/ext_r2c/mcp/source_tool.py`:
  - **Shape**: `SourceTool(source, *, name, title, description, input_schema, to_input)` with
    the default schema and `to_input` (research R12).
  - **`first_round(ctx, arguments)`**:
    - the thread from the owner and the context, choosing a context id when none is given;
    - `Driver.start`;
    - read until an ask or the end (`_pump`).
  - **`_pump`**:
    - progress per activity;
    - gather the reply, artifacts and usage;
    - on an ask: `declined` when forms are not supported, otherwise an input-required result
      with a new stopping point;
    - on the end: `final_result`.
  - **`retry(ctx, arguments, point, responses)`**, accepted path only in this phase: derive,
    then `deliver` to the held run or `Driver.resume`.
  - **Cancel**: cancellation of the round cancels the run through the driver.
- [ ] T038 [US1] Implement `python/src/ext_r2c/mcp/extension.py`:
  - `R2CExtension(tools=..., approve=..., clock=..., limits=..., ledger=..., owner=...)`;
  - `settings()`;
  - `tools()`: one stub `ToolBinding` per tool, with name, title and description;
  - `middleware()`: the `tools/list` schema rewrite (R1);
  - `intercept_tool_call`: for one of its own names, dispatch to the tool, first round or retry
    by `params.request_state`; otherwise call `call_next`.
  - The construction-time `ValueError`s.
- [ ] T039 [US1] Implement `python/src/ext_r2c/mcp/server.py`: `mcp_server(name, extension, *,
  security=None, **kwargs)`.
- [ ] T040 [US1] Re-export the public names in `ext_r2c/mcp/__init__.py`. Then finish
  `mcp_only.py`: build `mcp_server("check", R2CExtension(tools=[...]))` and assert that
  `server/discover` declares `key`.
- [ ] T041 Verify (SC-002, SC-003, SC-006), then commit
  `feat(004): serve an agent source as an MCP tool`.

---

## Phase 4: Approve a direct tool call (US2, P1)

**Goal**: a tool named in `approve=` never runs before an `allow` or `edit`. It runs exactly
once after one, and a replayed round never runs it again.

**Independent test**: a counting tool; allow, edit, deny, decline, replay.

- [ ] T042 [P] [US2] Write `python/tests/test_mcp_approve.py` with a `ToolSpec` from
  `tool_from_function(place_order)` that counts its calls, behind `approve={"place_order":
  True}`:
  - **Ask**: the input-required approval has `subject` = name, arguments and the listed schema,
    and the form has `decision`, `reason`, and every argument with its value as `default`
    (scenario 1).
  - **Allow**: the tool runs once with the call's arguments (scenario 2).
  - **Edit**: the tool runs once with the edited arguments. An edited value that breaks the
    schema is re-asked, and the tool does not run (scenario 3).
  - **Deny**: deny with a reason, and decline, give `isError: true`, `Not run: denied.` (plus the
    reason) and a count of 0 (scenario 4).
- [ ] T043 [P] [US2] Add `test_edit_dropped_for_nested_args` (scenario 5) and
  `test_approver_and_expiry_from_settings` (scenario 6). The latter uses `Approve(answer_by=
  "approver", expires_in=timedelta(minutes=5))` and a fixed clock, and checks
  `answer_by.role == "approver"` and `expires_at`.
- [ ] T044 [P] [US2] Add `test_tool_without_approval_runs_at_once` (scenario 7). Its
  `ToolOutput(text, artifacts, usage)` gives blocks with R2C metadata and the usage.
- [ ] T045 [P] [US2] Add `test_tool_registered_elsewhere`. A tool registered on the `MCPServer`
  with `@server.tool()` and named in `approve=`:
  - the form offers `allow` and `deny` only;
  - allow runs it once.
- [ ] T046 [P] [US2] Add `test_replayed_round_does_not_run_again`. The same allow retry sent
  twice: the second gets `This request was already answered.`, `isError: true`, and the count
  stays 1 (research R3).
- [ ] T047 [P] [US2] Add `test_listed_schema`. `tools/list` shows each `ToolSpec`'s
  `input_schema` exactly.
- [ ] T048 [P] [US2] Add `test_return_values`. A `str`, a `dict`, a `ToolOutput` and a raised
  `InvalidArguments` each give the result the contract names.
- [ ] T049 Run T042–T048. They fail for the expected reasons: no approval half yet, no ledger
  claim.
- [ ] T050 [US2] Implement `python/src/ext_r2c/mcp/tools.py`:
  - `Approve` and `ToolOutput`;
  - `serve_tool(spec, ctx, arguments)` (check the arguments, call, map the return value);
  - `approval_for(name, arguments, schema, settings, *, editable, clock)`;
  - `approve_round(...)` for the first round and the retry: `decision` with allow, edit or deny;
    edited arguments checked; `Not run` texts.
- [ ] T051 [US2] Wire `tools.py` into `extension.py`:
  - `approve=` names are checked before dispatch;
  - for a tool of the door, `edit` is offered when flat;
  - for a tool registered elsewhere, `call_next` runs on allow.

  Claim the round through the ledger before acting, in both the approval path and the source
  path.
- [ ] T052 Verify (SC-004), then commit `feat(004): approval before a direct tool call`.

---

## Phase 5: Refuse and re-ask (US3, P1)

**Goal**: no bad response, late response, missing response or forged state ever reaches a
source or runs a tool.

**Independent test**: each bad retry to a paused call; the source's received answers and the
tool's count stay 0.

- [ ] T053 [P] [US3] Write `python/tests/test_mcp_answers.py`:
  - **Re-ask**: a response leaving a required field empty is re-asked with the same key and
    `id`; `errors` names the field; the message lists the error (scenario 1).
  - **Missing response**: a retry with no entry for the pending key, or only other keys, is
    re-asked with `No response was received for "<title>".` first (scenario 2).
- [ ] T054 [P] [US3] Add `test_expired`, with a clock moved past `expires_at` (scenario 3):
  - **Question**: it counts as declined, and the final result starts with the "too late" text.
  - **Approval**: it counts as deny, and the tool does not run.
- [ ] T055 [P] [US3] Add `test_state_refused_by_the_boundary` (scenario 4). Each of these gets
  `-32602`, and the source and the tool see nothing:
  - an altered token;
  - another tool's token;
  - other arguments;
  - another owner's token;
  - a token past a short TTL (`RequestStateSecurity(keys=..., ttl=0.5)`).
- [ ] T056 [P] [US3] Add `test_response_too_large` (scenario 5): a response over
  `Limits.message_bytes` is re-asked with `too_large`.
- [ ] T057 [P] [US3] Add `test_roles_not_checked_on_the_door`. A derived answer is always
  `person`; the door applies no role problem.
- [ ] T058 [P] [US3] Add `test_gathered_reply_too_large` (FR-014). A source whose reply chunks
  add up to more than 5 MiB ends with a tool error naming the size.
- [ ] T059 [P] [US3] Add `test_a2a_gathered_reply_too_large` to
  `python/tests/test_a2a_activation.py` (FR-014, spec 003 follow-up). Without activation, reply
  chunks that add up to more than 5 MiB end the task failed with a reason naming the size.
- [ ] T060 Run T053–T059. They fail for the expected reasons.
- [ ] T061 [US3] Implement the retry outcome table in `source_tool.py` and `tools.py`, through
  one function, `outcome(point, responses, clock, limits)`: claimed, missing, expired, re-ask,
  accepted (data-model). Refusal sentences come from `_codec.message`.
- [ ] T062 [US3] Add the whole-text size check for the gathered reply in
  `python/src/ext_r2c/a2a/task.py`. Without activation, gathering raises `ContentTooLarge` after
  the task ends failed, as `reply` does with activation.
- [ ] T063 Verify (SC-005), then commit `feat(004): refuse and re-ask over MCP`.

---

## Phase 6: Threads and restart (US5, P1)

**Goal**: owners never share a thread; a busy context refuses a second call; a checkpoint source
resumes after a rebuild on fixed keys; a live run is lost after a restart and declined at
expiry.

**Independent test**: two bearer owners; a server rebuilt between the question and the retry.

- [ ] T064 [P] [US5] Write `python/tests/test_mcp_threads.py`:
  - **Owners**: alice and bob both use `context_id: "ctx-1"`; the fake sees
    `thread_id("mcp", alice_principal, "ctx-1")` and bob's, two different ids (scenario 1).
  - **Chosen context**: a call without `context_id` returns one in `structuredContent`, and a
    second call with it reaches the same thread (scenario 2).
- [ ] T065 [P] [US5] Add `test_busy_context` (scenario 3):
  - a new call on a context with a paused call of the same owner gets the busy text and
    `isError: true`, and the paused call still completes;
  - another owner's call on the same `context_id` is not refused;
  - once the paused call's state has expired (short TTL), the context is free.
- [ ] T066 [P] [US5] Write `python/tests/test_mcp_restart.py`, using
  `RequestStateSecurity(keys=[fixed])` and a checkpoint fake on a durable store:
  - **Checkpoint**: the server object is dropped and rebuilt between the question and the retry.
    The source resumes from the stopping point and completes, and the output from before the
    ask is in the final result (scenario 4).
  - **Live**: a live fake in the same situation ends with the "lost" text (scenario 5).
- [ ] T067 [P] [US5] Add `test_live_run_declined_at_expiry` (scenario 6). With a short TTL and no
  retry, the paused live run receives `declined` and ends, and its context is free.
- [ ] T068 Run T064–T067. They fail for the expected reasons.
- [ ] T069 [US5] Implement in `source_tool.py`:
  - **Context lock**: `_open`, with the busy refusal.
  - **Expiry**: timers from the server's TTL. A live run gets `declined`; the context is freed.
  - **Not held**: the `lost` and `Driver.resume` paths for a run that is not held.
  - **Owner**: the `owner=` override.
- [ ] T070 Verify (SC-007, SC-008), then commit `feat(004): MCP threads, busy contexts, restart`.

---

## Phase 7: Client (US6, P2)

**Goal**: a caller reads R2C over MCP as typed items, answers through the core check, and
fetches only from its connection's origin.

**Independent test**: the round trips of phases 3–6, driven only through `R2CClient`.

- [ ] T071 [P] [US6] Write `python/tests/test_mcp_client.py`, items:
  - **Activities**: activity items in order from progress, and `ProgressItem` for plain
    progress (scenario 1).
  - **Skipped**: unknown kinds, fields and activity types are skipped and counted.
  - **Requests**: one `RequestItem` per entry, typed or plain (scenario 2).
  - **Result**: the reply, artifacts with their presentation, usage, and a `ResultItem` with
    `context_id` (scenario 5).
- [ ] T072 [P] [US6] Add answer tests (scenarios 3–4):
  - a bad answer raises `AnswerRejected` and sends nothing;
  - a good one sends the same name and arguments and the state byte for byte (seen on the
    recording);
  - `caller` on an approval and `policy` anywhere are refused;
  - `respond` checks content against `requestedSchema`.
- [ ] T073 [P] [US6] Add `test_several_requests`. Against a wire server that sends two entries in
  one round, the client sends one retry only after both have a response.
- [ ] T074 [P] [US6] Add `test_fetch` (scenario 6, SC-009):
  - a resource of the same server is read through `resources/read`;
  - an `https` url on the origin is fetched, with no redirect followed and a size limit;
  - a url on another host, and every `live` artifact, comes back as a `Link`, with no request
    to that host (an `httpx2` mock transport counts requests);
  - an embedded resource over the limit is `TooLarge`.
- [ ] T075 [P] [US6] Add:
  - `test_version_checked`: a server that negotiates the legacy handshake makes `connect` fail;
  - `test_cancel`;
  - `test_call_while_paused_raises`.
- [ ] T076 Run T071–T075. They fail with `ImportError`.
- [ ] T077 [US6] Implement `python/src/ext_r2c/mcp/client.py`:
  - `R2CClient` with `connect`, `call`, `answer`, `respond`, `cancel`, `fetch` and `aclose`;
  - the item types, `AnswerRejected`, `Link` and `TooLarge`;
  - one `message_handler` routing progress by token;
  - `session.call_tool(..., allow_input_required=True)` for every round (research R13, R14).
- [ ] T078 Verify (story 6 scenarios, SC-009), then commit `feat(004): the caller's MCP client`.

---

## Phase 8: Replay and the standard (US7, P1)

**Goal**: every MCP example is a real round trip, against the client and against the door. The
standard records O4–O7.

**Independent test**: `test_mcp_replay.py`, one test per file and mode.

- [ ] T079 [P] [US7] Write the standard text first (FR-023, plan "Changes to the standard") in
  `standard/v1/README.md`: the prose on R2C-MCP-1, R2C-ASK-5, R2C-MCP-6, R2C-MCP-7 and
  R2C-MCP-8. Keep the rule count at 84.
- [ ] T080 [P] [US7] Add the new examples:
  - `elicitation-two-rounds.json`;
  - `elicitation-reask.json`;
  - `elicitation-no-response.json`;
  - `tool-result-inline-image.json` (a small invented PNG);
  - `approval-tool-call.json`.
  Correct the `message` of `elicitation-approval.json` and `elicitation-approval-edit-dropped.json`
  to the rule (O5). Run `test_examples.py` and `test_rules.py`: every file validates, and every
  `wire` rule has an example.
- [ ] T081 [US7] Create `python/tests/mcp_replay_kit.py` ([contracts/replay.md](contracts/replay.md)):
  - `load`, `names` and the `turns` of a file;
  - the derived answer, read from the file's description;
  - the converter to a scripted source (`script_from_example`) and the scripted source for both
    pause styles;
  - the wire server for client mode (a lowlevel `Server` replaying remote steps);
  - `normalise` (state, ids and tokens mapped; SDK `_meta` dropped; floats as ints);
  - the exemption list.
- [ ] T082 [US7] Write `python/tests/test_mcp_replay.py`:
  - **`client:<file>`** for every file;
  - **`door:<file>:<pause>`** for every file not exempt;
  - **`discover:discover.json`**;
  - **`test_exemptions_hold_both_ways`**.

  Add the summary line `MCP replay: …` to `conftest.py`, beside the A2A one.
- [ ] T083 Run T082. Fix the door where the replay finds a difference, each fix with its own
  failing test first, and record it in this file's Notes. Remove the xfail of T014.
- [ ] T084 [US7] Update `specs/001-standard-v1/research.md`: dated notes on O4–O7 saying where
  the text went.
- [ ] T085 Verify (SC-001), then commit `feat(004): every MCP example replayed in process`.

---

## Phase 9: Docs and final gate

**Goal**: the docs say what exists, and the whole suite passes on 3.11, 3.12 and 3.13 and in the
core-only, A2A-only and MCP-only environments. An outside review of the diff is done, and its
confirmed findings are fixed.

- [ ] T086 [P] Update `ARCHITECTURE.md`:
  - the `mcp/` modules;
  - the testing shape (`mcp_transport.py`, `mcp_harness.py`, the MCP replay, `mcp_only.py`);
  - the "exist today" line.
- [ ] T087 [P] Update `python/README.md` with an MCP section:
  - `mcp_server` and `R2CExtension` with `tools=`, `SourceTool` and `approve=`;
  - fixed keys for restart, and the single-use ledger across processes;
  - live sources and the same process;
  - `R2CClient`;
  - the limits (no streaming, long runs, URL elicitation declared).
- [ ] T088 [P] Update `CHANGELOG.md`: an Added entry for `ext_r2c.mcp`, and a Changed entry for
  the O4–O7 rules and the corrected examples.
- [ ] T089 [P] Update `docs/whitepaper.md` where names or behaviour changed: the MCP section,
  usage while waiting, the message rule, single use.
- [ ] T090 [P] Write `specs/004-mcp-binding/contracts/mcp-api.md` notes (dated) for anything
  that differs from the plan.
- [ ] T091 Run the full verify on Python 3.11, 3.12 and 3.13 (`../.ci-venv`, `../.v3.12-venv`,
  `../.v3.13-venv`), plus core-only, A2A-only and MCP-only. Record the test count.
- [ ] T092 Ask for an outside review of the whole 004 diff, using the code-reviewer and
  security-reviewer agents with fresh context:
  - focus: `requestState` handling and single use, approvals, owners, the origin rule in
    `fetch`;
  - for each finding, reproduce it, write a failing test, fix it, or record why it is left, in
    `research.md` ("Outside review").
- [ ] T093 Update `WORKSTATE.md` (004 closed, the test count, next `005-mcp-skills`) and the
  memory note on the repository's state.
- [ ] T094 Tick every task here, and add "Notes: where reality differed".
- [ ] T095 Verify, then commit `chore(004): close the MCP binding`.

---

## Dependencies and execution order

- **Phase 1 → Phase 2 → Phase 3** are strictly serial: the transport, the spike facts and the
  codec come before any door code.
- **Phase 3 (US1, US4)** is the MVP. **Phases 4 (US2) and 5 (US3)** extend `extension.py` and
  share the retry outcome table, so they are serial.
- **Phase 6 (US5)** needs phase 3, and phase 5 for the claimed-round and expiry paths.
- **Phase 7 (US6)** needs phase 2 for its unit parts and phase 3 for round trips. It can start
  after phase 3 if phases 4–6 wait, but one phase per go keeps it serial.
- **Phase 8 (US7)** needs every earlier phase.
- **Phase 9** is last.

## Parallel opportunities

Inside each phase, the tests marked [P] are separate test functions or files and can be written
together:
- phase 1: T001, T002, T006, T007;
- phase 2: T013–T019;
- phase 3: T024–T034;
- phase 4: T042–T048;
- phase 5: T053–T059;
- phase 6: T064–T067;
- phase 7: T071–T075;
- phase 8: T079 and T080;
- phase 9: T086–T090.

Production tasks in a phase touch the same modules and stay serial.

## Implementation strategy

- **MVP**: phases 1–3. An `AgentSource` is served as an MCP tool, with a question answered
  through an elicitation and mapped back to an R2C answer. That is success criterion 6, with
  activation and the no-form case.
- **Then**: approvals (4), robustness (5), threads and restart (6), the client (7), the replay and
  the standard (8), docs and the gate (9).
- **Each phase** ends verified and committed, and waits for the maintainer's go.
