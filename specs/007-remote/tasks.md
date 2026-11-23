---
description: "Task list for 007-remote"
---

# Tasks: `Remote`, one adapter for A2A, MCP or both (`ext_r2c.Remote`)

**Input**: design documents in `specs/007-remote/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII asks for tests first, run against the installed wheel, with the
real SDKs and real clients; the scripted chat model of spec 006 and the doors' fake sources are the only
fakes. In every phase:
1. write the phase's tests first;
2. run them and confirm they fail for the expected reason;
3. only then write production code.

If a test passes on its first run (a later phase often exercises what an earlier one built), say so in
the phase's report and prove it is not vacuous by a **mutation check**: break the line of production code
it guards, watch the test fail, restore.

**Organization**: the ten phases of the plan's delivery order. `/speckit-implement` runs **one phase per
go**: finish the phase, verify, commit, report in Vietnamese, stop, unless the maintainer says "hết spec".
- Phases 1 and 2 have no story label: the facts and the foundation every story uses.
- Phase 3 is the MVP (US1). Then US2, US3, US4 (P1), US5, US6 (P2), US7 (P3); phase 10 closes everything.
- Phase 3 builds a **first cut** of the checks in `Remote.__init__`; phase 4 completes them, each row
  starting with a test that fails on the first cut (plan, "Order").

## The decisions this list relies on

The maintainer asked for the plan and the tasks on 2026-11-23 ("sinh plan và task"). The plan reads that as
approval of the spec with D1–D13 as written, and takes the recommended answer on its three points. If the
maintainer overrules one, the tasks named change first.

| Point / decision | Settled as | Where it shows |
|---|---|---|
| D3 no `mcp_server=` | dropped; `MCPOptions.server` carries the server's settings | T024, T037, T073 |
| D5 identity | `middleware=` wraps both doors; one warning when MCP has no owner source | T068, T069 |
| Plan point 1: `Approve(answer_by="caller")` | **A**: `Remote` refuses it; `Approve` unchanged | T032, T042 |
| Plan point 2: one door still returns the parent app | **A** | T025, T066 |
| Plan point 3: `url` is the base, the card says `url` + `a2a.path` | **A** | T019, T024 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US7 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `rm -rf dist && uv build`;
  2. recreate `../.ci-venv`, install the wheel and the `dev` group (Python 3.11);
  3. `../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider` (the whole suite: the tests
     of specs 001–006 must still pass unchanged);
  4. `../.core-venv` with the wheel alone: `python -I tests/core_only.py`;
  5. `../.a2a-venv` with `wheel[a2a]`: `python -I tests/a2a_only.py`;
  6. `../.mcp-venv` with `wheel[mcp]`: `python -I tests/mcp_only.py`;
  7. `../.lg-venv` with `wheel[langgraph]` and no dev group: `python -I tests/langgraph_only.py`;
  8. `uvx ruff check --select F src tests`;
  9. repeat 1–3 on Python 3.12 and 3.13 at the end of phases 1, 3 and 10 (and when a task says so);
  10. leak-scan the staged added lines (must be 0);
  11. commit with an explicit pathspec and no co-author trailer. **Never push.**

## Path conventions

- Package: `python/src/ext_r2c/remote/`; tests: `python/tests/`.
- Test modules may import the package's private modules (`ext_r2c.remote._check`, …): they test the
  installed wheel.
- Async tests use `asyncio.run(asyncio.wait_for(coro, 10))`, as the doors' suites do.
- **Warnings.** `-W error::UserWarning` is on. `tests/remote_harness.py` (T018) builds every `Remote` with an
  explicit in-memory task store and an explicit request-state policy, so the D13 warning does not fire where
  it is not the test's subject; the D13 and D5 tests use `pytest.warns` and assert there is no other.
  If an SDK call raises another warning, handle it where it is raised and record its category in
  `research.md`; never relax the flag.
- All fixture content is invented (constitution VI): tools such as `publish_page`, `send_notice`; owners
  `owner-1`; `example.com` only; no real people, hosts or local paths. Files go in `tmp_path`. A test that
  asserts "no value is echoed" uses a canary string that appears nowhere else.
- The scratch probes of the plan's research stay out of the repo.
- A restart test builds a **new `Remote`, new agent and new store/saver objects** over the same files and
  shares only the counters the test passes in.

---

## Phase 1: Vet and spike

**Goal**: the installed set is confirmed, no dependency changes, and every SDK fact the design leans on is
pinned by a test.

**Independent test**: `tests/test_remote_spike.py`.

- [ ] T001 Confirm the set: in `../.ci-venv` list `a2a-sdk`, `mcp`, `starlette`, `httpx`, `httpx2`,
  `langchain`, `langgraph`; check that the `[a2a]` and `[mcp]` bounds in `python/pyproject.toml` admit them;
  confirm **no dependency or extra changes** for this spec (FR-036). Write one dated line under "Phase 1" in
  the notes of this file. If a bound would have to move, stop and tell the maintainer.
- [ ] T002 [P] `tests/test_remote_spike.py`, section 1 (R1): build the real A2A app and the real MCP app
  (plain, and with the SDK's `auth` using `mcp_harness.auth()`); in the test, a small `Dispatch` asks the
  MCP router; pin: `/mcp` is MCP's exactly and `POST /mcp` has no redirect; the card path, `/` and an unknown
  path are A2A's; with `auth`, the OAuth protected-resource path is MCP's; `Mount("/mcp", mcp_app)` answers
  `/mcp` with `404` and does not run the sub-app's lifespan (so the design is not a mount).
- [ ] T003 [P] `tests/test_remote_spike.py`, section 2 (R2): an `AsyncExitStack` over the two door lifespans
  starts and stops both in order; the MCP session manager's second `run()` raises; `handler.aclose()` twice is
  harmless. (The lifespan leak is A1's test, T010, not a pinned fact.)
- [ ] T004 [P] `tests/test_remote_spike.py`, section 3 (R3): under one outer `AuthenticationMiddleware`
  (`BearerAuth` of `a2a_harness.py`) the A2A default resolver and an `R2CExtension(owner=...)` callable both
  see the same user (`ctx.request.user`).
- [ ] T005 [P] `tests/test_remote_spike.py`, section 4 (R4, R5): `isinstance(x, AgentSource)` raises
  `TypeError`; an a2a-sdk executor has `execute` and `cancel` and none of `card`, `pause`, `run`, `resume`;
  `inspect.isroutine` is true for a function and a method and false for a `functools.partial`, a callable
  instance and an object with `invoke`; `tool_from_function` of such an object raises `AttributeError` (the
  reason `Remote` classifies first).
- [ ] T006 [P] `tests/test_remote_spike.py`, section 5 (R8, R9): the keyword names of
  `MCPServer.__init__` and `streamable_http_app` equal the sets written in the test (a rename fails here);
  `mcp_server(..., extensions=[SkillsExtension(...)])` with `R2CExtension(tools=())`, one `add_resource`
  and one `add_prompt` starts, lists the skills, the resource and the prompt, answers `tools/list` empty and
  declares the R2C key; `Approve(answer_by="caller")` constructs (the gap `Remote` closes).
- [ ] T007 [P] `tests/test_remote_spike.py`, section 6 (R14): one parent app served inside its own lifespan
  gives an A2A client (`a2a_harness.a2a_client(Served(app, card))`) and an MCP client
  (`mcp_harness.mcp_client(Served(None, app))`) at once, one bearer header naming the owner on both; the
  in-process transports do not run the lifespan themselves (the test enters it). If the MCP client needs
  anything from `Served.server`, record what and plan a stand-in in T018.
- [ ] T008 Run the spike: every test passes. A failing fact means stop, update `research.md` and `plan.md`
  first, and tell the maintainer.
- [ ] T009 Verify and commit: `test(007): pin the SDK facts Remote leans on`.

**Checkpoint**: facts pinned; no production code yet.

---

## Phase 2: Foundation

**Goal**: A1 (the A2A lifespan is exception-safe); the empty `remote/` package with `RemoteError` and the two
option classes; the lazy export; the import rule. Core-only stays green.

**Independent test**: `test_a2a_serve.py`; `test_packaging.py`; `test_remote_errors.py` and
`test_remote_options.py` (their first sections).

- [ ] T010 [P] A1 test first, in `tests/test_a2a_serve.py`: spy on the request handler's `aclose`; (a) a
  clean stop of `a2a_app`'s lifespan closes it once; (b) an exception thrown into the lifespan at its `yield`
  (inside `async with app.router.lifespan_context(app): raise ...`) closes it too and the exception
  propagates. Run: (b) fails because the handler stays open (this is the leak of research R2).
- [ ] T011 A1 fix in `src/ext_r2c/a2a/app.py`: `try: yield` / `finally: await handler.aclose()`. Run the whole
  a2a suite and its replays unchanged.
- [ ] T012 [P] `tests/test_remote_errors.py`, section 1: `RemoteError` is a `ValueError`; `problems` is a
  non-empty tuple of `str`; `str(error)` begins `Remote cannot be built:` and lists one problem per line;
  building one with no problems raises `ValueError`.
- [ ] T013 [P] `tests/test_remote_options.py`, section 1: `A2AOptions` and `MCPOptions` are frozen and
  keyword-only (a positional argument is a `TypeError`); defaults are those of `data-model.md` §3
  (`MCPOptions.server` and `.http` are empty read-only mappings that cannot be mutated); both import with
  `a2a` and `mcp` blocked (a child process with those names set to `None` in `sys.modules`).
- [ ] T014 [P] `tests/test_packaging.py`: (a) the lazy export: `import ext_r2c` leaves `ext_r2c.remote` out of
  `sys.modules` (child process); `from ext_r2c import Remote, RemoteError, A2AOptions, MCPOptions` works;
  the four names are in `ext_r2c.__all__`; an unknown attribute raises `AttributeError`; (b) the import
  rule of R13 for `src/ext_r2c/remote/`: module-level imports are the standard library, `ext_r2c.core` and
  `ext_r2c.remote`'s own modules; imports inside functions may also name `ext_r2c.a2a`, `ext_r2c.mcp`,
  `starlette`, `a2a`, `mcp`; no module names `ext_r2c.bridges`, `langgraph` or `langchain`; no module outside
  `ext_r2c/__init__.py` imports `ext_r2c.remote`. Add a unit test that the rule catches a bad snippet.
- [ ] T015 Run T012–T014: each fails for the expected reason (the modules and names do not exist; A1 already
  green). Report the reasons.
- [ ] T016 Create `src/ext_r2c/remote/__init__.py`, `_errors.py`, `_options.py` (the dataclasses and the owned
  key sets of R8), and a `_remote.py` whose `Remote.__init__` raises `NotImplementedError` (replaced in phase
  3); the lazy export in `src/ext_r2c/__init__.py` (PEP 562 `__getattr__`, `__dir__`, `__all__`, and a
  `TYPE_CHECKING` import for type checkers). Run T012–T014 green.
- [ ] T017 Verify and commit: `feat(007): the remote package, A1 and the lazy export`.

**Checkpoint**: core-only green; `from ext_r2c import Remote` works with no extra.

---

## Phase 3: One line, one app, both doors (US1, P1) 🎯 MVP

**Goal**: one `Remote` over a real graph and plain tools, served as one app in one process, an A2A caller and
an MCP caller each reaching the agent through a pause and an answer; both doors start and stop with the app.

**Independent test**: `test_remote_serve.py`, `test_remote_compose.py`, `test_remote_lifecycle.py`.

### Tests for User Story 1 ⚠️ (write first, watch them fail)

- [ ] T018 [US1] `tests/remote_harness.py` (a helper, not a test): `serve_remote(remote)` builds
  `remote.app()`, enters `app.router.lifespan_context(app)`, and yields an object with `.app`, `.a2a(user=,
  r2c=)` (an A2A client over the same app; the card is built by the same `agent_card(info, address)` call
  `Remote` makes) and `.mcp(user=, active=)` (an MCP client over the same app); `quiet(**kw)` builds a
  `Remote` with an explicit in-memory task store and request-state policy, the recommended identity recipe
  (`Middleware(AuthenticationMiddleware, backend=BearerAuth())` and `MCPOptions(owner=<reads
  ctx.request.user>)`), and the arguments given. One bearer header names the owner on both doors.
- [ ] T019 [P] [US1] `tests/test_remote_compose.py`: with `CheckpointFake` as the agent and `mcp_tool=True`:
  the card at `/.well-known/agent-card.json`, the JSON-RPC at `/` and the MCP endpoint at `/mcp` all answer;
  `/mcp` answers with **no redirect**; the served card equals the one `agent_card` builds and its address is
  `url` + `a2a.path` (default `https://remote.example.com/`; with `A2AOptions(path="/rpc")`
  `https://remote.example.com/rpc`, and the JSON-RPC answers there); with the SDK's `auth` on
  (`mcp_harness.auth()`) the OAuth protected-resource metadata path answers from MCP, not A2A; a recording
  middleware given as `middleware=` runs once per request on both doors and outside each door's own
  middleware.
- [ ] T020 [P] [US1] `tests/test_remote_serve.py`: SC-003 and SC-009 with the real graph of spec 006
  (`langgraph_graphs.py`, `langgraph_models.py`: scripted model, checkpointer, two tools) wrapped by
  `LangGraphAgent`, `mcp_tool=True`: (a) an A2A caller gets a question, answers, and gets the reply; (b) an MCP
  caller gets the same through the tool `agent`; (c) the two threads differ (the checkpointer holds one thread
  per door, `a2a:` and `mcp:` keyed) and the same context id over both doors shares nothing; (d) a caller that
  did not activate R2C gets text and standard artifacts on both doors (0 R2C parts or metadata); (e) nothing
  is set on the agent, the graph, a tool or a function it was given (a snapshot of `vars()` before `app()` and
  after the round trips).
- [ ] T021 [P] [US1] `tests/test_remote_lifecycle.py`: SC-007: entering the app's lifespan starts both doors
  (each answers a request); leaving it closes the A2A handler once (spy on `R2CRequestHandler.aclose`) and
  exits the MCP session manager (spy on `StreamableHTTPSessionManager.run`, enter and exit around the real
  one); an MCP start that fails (the spy raises on enter) leaves the A2A handler closed and the error
  propagates (this needs A1); an exception thrown while serving unwinds both; a second `app()` raises
  `RuntimeError` naming "build a new `Remote`" (D4).
- [ ] T022 [US1] Run T019–T021 against the stub: each fails for the expected reason (`NotImplementedError`
  from `Remote.__init__`). Report.

### Implementation for User Story 1

- [ ] T023 [P] [US1] `src/ext_r2c/remote/_classify.py` (first cut): `agent_kind(agent)` by shape (R4);
  `normalise_tools(...)` (kept, converted with `tool_from_function`, or the static `TypeError` of R5);
  `normalise_approve(...)` (a name list becomes `{name: True}`).
- [ ] T024 [P] [US1] `src/ext_r2c/remote/_doors.py`: `load_door(name)` (imports inside the function; an
  `ImportError` whose `name` is the door's SDK becomes an `ImportError` naming `ext-r2c[<door>]`, any other
  propagates); `build_a2a(...)` (executor by kind, `agent_card(info, url.rstrip("/") + path)`, `a2a_app` with
  `task_store` and `owner_resolver` only when set, `rpc_url`); `build_mcp(...)` (the agent tool, `R2CExtension`,
  `mcp_server` with the card's name, version and description, `streamable_http_app` with `path` and
  `transport_security`). Skills, resources and prompts are phase 7.
- [ ] T025 [US1] `src/ext_r2c/remote/_compose.py`: `Dispatch` (the MCP router's own matching, R1), the `both`
  lifespan over an `AsyncExitStack`, `parent_app(...)` (`Mount("/", Dispatch)`, the owner's `middleware`),
  `check_no_collision(...)` (the dynamic check of R10, a `RemoteError`).
- [ ] T026 [US1] `src/ext_r2c/remote/_remote.py`: `Remote.__init__` first cut (R6: read `expose`, load the
  doors, classify `agent` and `tools`, resolve the card information, the first problems: `expose` empty,
  unknown or repeated) and `app()` (the once-flag at entry, build, compose); replace the stub.
- [ ] T027 [US1] Run T019–T021 green, then the whole suite; fix what breaks.
- [ ] T028 [US1] Mutation check (a scratch script, not committed; baseline green first): route `/mcp` to the
  A2A app; enter only the A2A lifespan; remove A1's `finally`; let `app()` run twice; set an attribute on the
  agent. Each mutant must fail a named test of T019–T021.
- [ ] T029 Verify (also on 3.12 and 3.13) and commit: `feat(007): Remote serves one agent over A2A and MCP in
  one app`.

**Checkpoint**: SC-003, SC-007, SC-008 (both doors) and SC-009 hold. After it, a `Remote` is servable end to
end.

---

## Phase 4: A mistake fails when the app is built (US2, P1)

**Goal**: every row of the build-problem table is an error at construction, in the fixed order, with a message
that names the argument and says what to do.

**Independent test**: `test_remote_errors.py`.

### Tests for User Story 2 ⚠️ (write first, watch them fail on the first cut)

- [ ] T030 [P] [US2] `tests/test_remote_errors.py`, section 2 (ImportError): with `a2a` blocked (child
  process, `sys.modules["a2a"] = None`), `Remote(expose=["a2a"], ...)` raises an `ImportError` naming
  `ext-r2c[a2a]`; with `mcp` blocked, `[mcp]`; both blocked, both named; `import ext_r2c` and `from ext_r2c
  import Remote` still work; the error comes before any other check (a config with other mistakes still
  raises it).
- [ ] T031 [P] [US2] section 3 (TypeError, first found): `expose` a bare `str` or with a non-`str` item;
  `agent` of neither kind (the message names both kinds); a `tools` entry that is a `functools.partial`, a
  callable instance, a stand-in with `invoke` (the message names `tools_from_langchain`); `tools`, `approve`,
  `resources`, `prompts`, `middleware` as a bare `str`; `approve` with a value that is neither `Approve` nor
  `bool`; a `middleware` item that is not a `Middleware`; `resources` or `prompts` items of the wrong class;
  `a2a=` or `mcp=` of the wrong class; `skills` of an unaccepted kind; `card`, `url`, `limits`, `clock`,
  `mcp_tool` of the wrong type. A callable the core refuses (`*args`, no type hints, a leading underscore)
  passes through with the core's own error, unchanged.
- [ ] T032 [P] [US2] section 4 (`RemoteError`, one test per row of R7, rows 1 to 14 and 16 to 19): the error
  type, the message names the argument, the `problems` entry begins with its name, and a companion test
  fixes only that argument and builds (the offending argument is absent from every success path). Includes:
  `approve` naming a tool that does not exist (a typo), the agent's tool and any `SourceTool`; an
  `Approve(answer_by="caller")` (built with a `cast`); two tools with one name (the agent tool included); the
  paths colliding, a path without a leading `/`, a path under `/.well-known/`; a `url` that is not an absolute
  `http(s)` address, with user info, a query or a fragment; `MCPOptions.server` naming `name`, `extensions`,
  `request_state_security`, …; `.http` naming `streamable_http_path`; the owned keys are a subset of the SDK's
  keyword sets pinned in T006.
- [ ] T033 [P] [US2] section 5 (collected, no echo): several mistakes at once give one `RemoteError` listing
  all, in a stable order, and fixing them one at a time ends in a built app; a canary in `url` user info and a
  canary path in an option appear in no message and no `problems` entry; every message says what to do.
- [ ] T034 [P] [US2] section 6 (order): with an extra missing and other mistakes, the `ImportError` wins; with
  a wrong type and a collected problem, the `TypeError` wins; a refused `Remote` emits no warning; a valid one
  emits only the warnings of phases 6 and 9.
- [ ] T035 [US2] Run T030–T034 against the first cut: each fails for the expected reason (a row is missing, an
  error is the wrong type). Report which rows the first cut already met.

### Implementation for User Story 2

- [ ] T036 [US2] `src/ext_r2c/remote/_check.py`: the type checks (R6 step 3) and the collected problems (every
  row of R7, with messages in the convention `"<argument>: <what is wrong>; <what to do>"`), called from
  `Remote.__init__` in the R6 order; the unserved-argument rule of FR-019; tool-name and approve tables.
- [ ] T037 [US2] `src/ext_r2c/remote/_options.py`: the owned-key sets and the path helpers used by the checks
  (a path begins with `/`, not under `/.well-known/`, the two differ); extend `_classify.py` for
  `normalise_skills` shape and the `approve` shapes.
- [ ] T038 [US2] Run T030–T034 green and the whole suite; one pass over every message: it names the argument
  and says what to do, and contains no value the owner typed.
- [ ] T039 Verify and commit: `feat(007): build errors, one test per row`.

**Checkpoint**: SC-005 holds.

---

## Phase 5: Approvals sit where each caller path is (US3, P1)

**Goal**: both approval paths work through the app `Remote` built, each governed by its own list, none answered
by `Remote`, none addressed to the caller.

**Independent test**: `test_remote_approvals.py`.

- [ ] T040 [P] [US3] `tests/test_remote_approvals.py`, section 1 (A2A, the agent's own gate; SC-001 criteria 1
  to 3): the real graph with `HumanInTheLoopMiddleware` gating `publish_page`, served by `Remote`: the approval
  carries the tool's `title` and `subject`; `allow` runs the body exactly once and the task completes; `deny`
  with a reason does not run it, the model gets the reason, the task completes; an answer that fails the schema
  is asked again with the same id and `errors` and the run lives.
- [ ] T041 [P] [US3] section 2 (MCP, `approve=`): the same function as a plain tool in `tools=` with
  `approve=["publish_page"]`: a direct call first asks an approval; the body does not run before `allow` and
  runs once after; `deny` does not run it; `approve={"publish_page": Approve(answer_by="approver")}` asks an
  approver; the agent's own list and `approve=` name different tools and each governs only its own path.
- [ ] T042 [P] [US3] section 3 (SC-004, never answered by `Remote`): every path through `Remote` that makes an
  approval has `answer_by` of `person` or `approver`; `Approve(answer_by="caller")` is refused at build; the
  parameters of `Remote.__init__` equal the list of D1 exactly and the fields of both option classes equal the
  data model's (a surface pin: no hidden knob answers an approval).
- [ ] T043 [US3] Run T040–T042. Expected: they pass on the code of phases 3 and 4 (this phase composes what
  004 and 006 built). For each that passes on its first run, say so and prove it is not vacuous in T045.
- [ ] T044 [US3] Fix what the tests find in production code, test first (expected: nothing; record it).
- [ ] T045 [US3] Mutation check (scratch, green baseline): skip the `approve` existence check; skip the
  `answer_by` check; make `approve=` pass nothing to `R2CExtension`; serve the tool before the approval. Each
  mutant fails a named test of T040–T042 or T032.
- [ ] T046 Verify and commit: `test(007): approvals through Remote on both doors`.

**Checkpoint**: SC-004 and the approval half of SC-001 hold.

---

## Phase 6: A restart in the middle (US4, P1)

**Goal**: a pause survives a rebuild on each door with durable state; an in-memory door says so once.

**Independent test**: `test_remote_restart.py`.

- [ ] T047 [P] [US4] `tests/test_remote_restart.py`, section 1 (A2A, SC-001 criterion 4): a graph on an
  `AsyncSqliteSaver` file and the durable task store `test_a2a_restart.py` uses, paused on a question; drop
  the app and every in-memory object; build a new `Remote` over the same files; answer; the task completes
  and the tool body ran once.
- [ ] T048 [P] [US4] section 2 (MCP, SC-006): `approve=["publish_page"]` and fixed `RequestStateSecurity` keys
  in `MCPOptions.security`; a paused direct call is retried after a rebuild with the same keys and completes,
  the body once; with another key (or the ephemeral policy) the retry is refused as spec 004 defines.
- [ ] T049 [P] [US4] section 3 (D13): A2A with no `task_store` gives one `UserWarning` naming `a2a.task_store`;
  with one, none; MCP with a non-empty `approve` or a checkpoint-style `SourceTool` and no `security` gives one
  naming `mcp.security`; plain `ToolSpec`s only, or a live-style source, none; both doors give two warnings,
  one each; they fire at construction, not in `app()`; `warning.filename` is the test file (the `stacklevel`).
- [ ] T050 [US4] Run T047–T049: T049 fails (no warning yet); T047 and T048 are expected to pass on the earlier
  code (say so; T052 proves them).
- [ ] T051 [US4] `_check.py`: the D13 rule of R11, called after the problems pass; wire it in
  `Remote.__init__`.
- [ ] T052 [US4] Run green; mutation check (scratch): drop the D13 check; key the MCP rule on the wrong
  setting; let a plain tool warn; use `stacklevel=1`; make `app()` warn again. Each dies. Break the rebuild
  (new keys) and watch T048 fail.
- [ ] T053 Verify and commit: `feat(007): restart tests and the in-memory warnings`.

**Checkpoint**: SC-006 and the restart half of SC-001 hold.

---

## Phase 7: Skills, resources, prompts and the agent as a tool (US5, P2)

**Goal**: an MCP client loads a skill folder, reads a resource, lists a prompt, or calls the agent as one tool.

**Independent test**: `test_remote_mcp_extras.py`.

- [ ] T054 [P] [US5] `tests/test_remote_mcp_extras.py`, section 1 (skills): `skills=` as a folder, as a list of
  folders, and as a ready `SkillsExtension` with `exclude`: each kept skill is listed and readable with
  `SkillsClient`; a bad folder fails `app()` with the unchanged `SkillsError` and the `Remote` is then consumed
  (a second `app()` is a `RuntimeError`); the A2A card JSON is identical with and without `skills=`; a card
  skill and an MCP skill of one name are unrelated (no error).
- [ ] T055 [P] [US5] section 2 (the agent tool): with `mcp_tool=True` one more tool `agent` takes
  `{message, context_id?}` and completes a pause and an answer over MCP; without it there is none; a
  customised `SourceTool` in `tools=` works beside it; a `tools=` entry named `agent` with `mcp_tool=True` is
  the problem of T032.
- [ ] T056 [P] [US5] section 3 (resources and prompts): a `TextResource` and a `Prompt.from_function` are
  listed, read and fetched as given; the A2A card is unchanged by them.
- [ ] T057 [P] [US5] section 4 (no tools): `Remote(expose=["mcp"], skills=...)`, or only a resource or a
  prompt, serves; `tools/list` is empty; the R2C key is declared.
- [ ] T058 [US5] Run T054–T057: they fail because phase 3's `build_mcp` does not add them (expected: no
  skills, no resource, no prompt listed). Report.
- [ ] T059 [US5] `_doors.build_mcp`: build `SkillsExtension` from a folder or a list (or use the given one) and
  pass it in `extensions=`; `add_resource` and `add_prompt` for each object; `_classify.normalise_skills`.
- [ ] T060 [US5] Run green; mutation check (scratch): serve skills on the A2A card; drop `add_prompt`; build
  the skills extension twice. Each dies.
- [ ] T061 Verify and commit: `feat(007): skills, resources, prompts and the agent tool`.

**Checkpoint**: the US5 scenarios hold.

---

## Phase 8: A remote that is already an a2a-sdk executor (US6, P2)

**Goal**: a hand-written executor that never heard of R2C is served unchanged on A2A.

**Independent test**: `test_remote_executor.py`.

- [ ] T062 [US6] `tests/remote_executor.py`: an `AgentExecutor` in the shape of the official Currency sample (a
  scripted pure-function "model"; asks in plain text with an `input-required` status; continues on the reply);
  it imports nothing of `ext_r2c`, and a test in T063 scans its source to prove it.
- [ ] T063 [P] [US6] `tests/test_remote_executor.py`: `Remote(expose=["a2a"], agent=executor, card=..., url=...)`:
  the card declares R2C with `required: false`; an activated `R2CClient` gets the text-only `input-required`
  and continues in text (SC-002); a caller that did not activate R2C works as before; the executor is the
  same object, with no attribute set; `expose=["mcp"]` with only an executor and `mcp_tool=True` with one are
  the problems of T032; `expose=["a2a", "mcp"]` with an executor and `tools=` serves the executor on A2A and the
  tools on MCP.
- [ ] T064 [US6] Run T063. Expected: it passes on the earlier code (the executor kind and `build_a2a` came in
  phase 3); if so, say so and prove it is not vacuous by mutation (serve the executor wrapped in
  `SourceExecutor`; skip the shape check). Fix anything it finds, test first.
- [ ] T065 Verify and commit: `test(007): a hand-written executor through Remote`.

**Checkpoint**: SC-002 holds.

---

## Phase 9: One door, and each door's own settings (US7, P3)

**Goal**: one door alone serves and loads only itself; each deployment setting reaches the door it belongs to;
`middleware=` wraps both; the identity warning is exact.

**Independent test**: `test_remote_options.py`.

- [ ] T066 [P] [US7] `tests/test_remote_options.py`, section 2: `expose=["a2a"]` answers the card and the
  JSON-RPC only and the MCP path answers `404`, and `ext_r2c.mcp` and `mcp` are not in `sys.modules` (child
  process); `expose=["mcp"]` the reverse (SC-008).
- [ ] T067 [P] [US7] section 3 (the options take effect): the `task_store` object given is the one the door
  and its store use, and the `owner_resolver` given is read for a task's owner and shares its key with the store
  (spec 003's rule); `MCPOptions.transport_security` allowing `remote.example.com` serves a request with that
  `Host` and a request with another `Host` is `421` (finding 8); `server={"instructions": ...}` reaches the
  initialize result; `http={"json_response": True}` changes the response type; `MCPOptions.path` and
  `A2AOptions.path` move their endpoints.
- [ ] T068 [P] [US7] section 4 (`middleware` and D5): a counting middleware wraps both doors; `middleware=`
  given with MCP exposed and no `owner` and no SDK authentication gives one `UserWarning` naming `mcp.owner`;
  with `owner` given, with `token_verifier`, `auth` or `auth_server_provider` in `server`, with no middleware,
  or with A2A only, none; with the recommended recipe one bearer header makes the same owner on both doors
  (an A2A task's owner and the MCP extension's owner are equal).
- [ ] T069 [US7] Run T066–T068: T068's warning half fails (no D5 yet); the rest are expected to pass. Then
  `_check.py`: the D5 rule of R11, wired in `Remote.__init__` after D13. Run green.
- [ ] T070 Verify and commit: `feat(007): one door, door options and the identity warning`.

**Checkpoint**: SC-008 (one door) holds; every story is built.

---

## Phase 10: Packaging, docs and the final gate

**Goal**: the single-extra checks, the docs and the outside review are done and every success criterion is
checked on three Pythons.

**Independent test**: the whole suite and `quickstart.md`, end to end.

- [ ] T071 [P] Extend `tests/core_only.py`, `tests/a2a_only.py`, `tests/mcp_only.py` and
  `tests/langgraph_only.py` (SC-010): core-only: `from ext_r2c import Remote` works, no `a2a` or `mcp` is
  loaded, `expose=["a2a"]` and `["mcp"]` raise an `ImportError` naming `ext-r2c[a2a]` and `ext-r2c[mcp]`;
  a2a-only: an A2A-only `Remote` serves a card and `mcp` is not in `sys.modules`; `expose=["mcp"]` names `[mcp]`;
  mcp-only: the mirror; langgraph-only: `Remote` composes with `LangGraphAgent` and only one door can be
  exposed. Run each in its venv with `-I`.
- [ ] T072 [P] `python/README.md`: a `Remote` section that says everything in
  [contracts/remote-api.md](contracts/remote-api.md) and [contracts/app-composition.md](contracts/app-composition.md)
  that an owner needs: the one-line form and the argument table (which door serves each, what happens when
  none does); `url` is the base and the card says `url` + `a2a.path`; identity per door and the `owner=`
  recipe; the host guard (`transport_security`, the `421`); durable state per door and the two warnings; one
  `Remote`, one `app()`; mounting inside a larger ASGI app (run this app's lifespan, put the prefix in
  `url`); `uvicorn module:app`; an agent source shared by two doors must be safe to share; no `mcp_server=`.
- [ ] T073 [P] Dated notes (never rewrite a body): `docs/design-docs/one-remote-two-doors.md` (three: no
  `mcp_server=` and why; `Skills(...)` is `skills=`; `url` is required for A2A, and the base form);
  `docs/research/2026-11-20-r2c-v1-design-brief.md` amendment 4 (what `Remote` serves and criteria 1 to 5);
  `specs/003-a2a-binding` contract (A1). Grep the old names (`mcp_server=`, `Skills(`) across docs and code
  until only intentional hits remain.
- [ ] T074 [P] `ARCHITECTURE.md` (the `remote/` rows and its import rule), `CHANGELOG.md` (Added: `Remote`;
  Fixed: the A2A lifespan), `AGENTS.md` (what it says about `Remote`; the file stays under 150 lines, it is 68
  now).
- [ ] T075 [P] Mark `contracts/remote-api.md` and `contracts/app-composition.md` as built (the status line and a
  dated note with what differed, if anything).
- [ ] T076 Run `quickstart.md` end to end on 3.11, 3.12 and 3.13; fix the guide where it and the code
  disagree (the guide moves, unless the code is wrong).
- [ ] T077 Mutation check of the safety rows (quickstart §6), green baseline first: skip the `approve` name
  check; skip the `answer_by` check; drop A1's `finally`; route `/mcp` to A2A; run only the A2A lifespan; let
  `app()` run twice. Record "N of N mutants died" as R17 in `research.md`. Restore from a copy, not by
  reinstalling (the `uv` hard-link trap).
- [ ] T078 Outside review: dispatch a **code reviewer** and a **security reviewer** (the `.claude/agents/`
  ones), each with no memory of the work, on the range from `d07f9c6` to HEAD, briefed with what `Remote`
  does and the plan's risks (identity, the `421` host guard, the once-flag, what the messages echo). Check
  every finding against the code. For each one acted on, write a test that **fails first**, then fix. Record
  the review, with what was left on purpose and why, as R18 in `research.md`.
- [ ] T079 Mutation check of the review fixes, baseline green first; record in R18.
- [ ] T080 The closing numbers, recorded in this file under "Phase 10 (date)": the suite's count on 3.11, 3.12
  and 3.13 against the installed wheel; core only, a2a only, mcp only and langgraph only ok; `ruff check
  --select F` clean; the replays unchanged; `git diff --stat d07f9c6 -- standard` empty.
- [ ] T081 Walk SC-001 to SC-012 and write the result against each in this file ("met by T0xx, run
  <date>"); name any not fully met and what is left. SC-012 is for the maintainer to read (the spec, the plan
  and the ADR only).
- [ ] T082 Update `WORKSTATE.md` (007 closed locally; what is next; the push waits for the maintainer's go) and
  `specs/007-remote/plan.md` (a dated closing note; the body stays).
- [ ] T083 Final leak scan of the whole range since `d07f9c6` (must be 0), then commit
  `docs(007): README, ADR notes and close Remote`. **Do not push.**

**Checkpoint**: the maintainer decides on the push.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1** has no dependency. **Phase 2** has none on phase 1 (A1 and the skeleton are independent of the
  spike) but runs after it by order.
- **Phase 3** depends on 1 and 2: the harness uses the spike's findings (T007), the code uses the skeleton.
- **Phase 4** depends on 3 (it completes the first cut).
- **Phases 5 and 6** depend on 3 and on 4's `approve` and `answer_by` rows (T032, T036).
- **Phases 7, 8 and 9** each depend on 3 and are independent of each other (phase 9's D5 warning shares
  `_check.py` with phases 4 and 6, so do not run them in parallel with those).
- **Phase 10** is last: it covers everything at once.

### Within each phase

- Tests are written first and must fail for the expected reason (or be shown non-vacuous by mutation).
- Helpers before the tests that use them (T018 before T019–T021; T062 before T063).
- Pure modules (`_classify`, `_check`, `_options`, `_errors`) before `_doors`, `_compose` and `_remote`, which
  glue them.
- Each phase ends with its verify and its commit; the next phase starts only on the maintainer's go, unless
  the maintainer says "hết spec".

### Parallel opportunities

- Phase 1: T002 to T007 (one file, so write them one after the other, or split the file by section).
- Phase 2: T010, T012, T013, T014 (different files).
- Phase 3 tests: T019, T020, T021; modules: T023, T024 (T025 and T026 wait for them).
- Phase 4 tests: T030 to T034 (one file; split it or write in order). Phase 5: T040 to T042. Phase 6: T047 to
  T049. Phase 7: T054 to T057. Phase 9: T066 to T068.
- Phase 10: T071 to T075.
- Subagents, if used (the `parallel-agents` rule), take whole independent test files with a self-contained
  brief and an output contract; never the shared `_remote.py`, `_check.py` or `_compose.py`.

## Implementation strategy

### MVP first (US1)

1. Phase 1 (facts) and phase 2 (A1, skeleton, export).
2. Phase 3: **stop and validate**: one real graph through both doors in one app, both doors start and stop.
3. Phase 4: the build errors. After it, a mistake never reaches a request.

### Incremental delivery

1. Phases 5 and 6 (approvals, restart): the P1 stories are done.
2. Phases 7 and 8 (skills and the rest, an executor): the P2 stories.
3. Phase 9: the one-door and options story (P3).
4. Phase 10: packaging, docs, the outside review and the final gate.

## Notes

- Each phase is one commit, with an explicit pathspec and no co-author trailer; none is pushed.
- If reality diverges from the plan (a pinned fact fails, a door needs a change beyond A1), stop, update
  `research.md` and `plan.md` first, and tell the maintainer; do not force the code through.
- `spec.md` keeps its status "Draft", as the specs of 005 and 006 did.
- Out of scope, as the spec says: authentication and authorization; an existing `MCPServer` as an argument
  (D3); a richer A2A card; a `Remote.run()` or command line; bridges for other frameworks; MCP Tasks; A2A push
  notifications; one thread shared across doors; decorators; a `Skills(root, ...)` helper; any change to the
  standard. A hardening of `Approve` itself (plan point 1, option B) is a spec 004 follow-up and is not in these
  tasks unless the maintainer asks.

## Notes: where reality differed (dated; the bodies above are not rewritten)

None yet.
