# Implementation Plan: `Remote`, one adapter for A2A, MCP or both (`ext_r2c.Remote`)

**Branch**: `main` (folder `specs/007-remote`) | **Date**: 2026-11-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-remote/spec.md`. The maintainer asked for the plan
and the tasks on 2026-11-23 ("sinh plan và task"); this plan reads that as approval of the spec with
decisions D1–D13 as written. **D3** (no `mcp_server=`) and **D5** (the identity warning) are the two
that change what an owner can do; either can be overruled before its phase.

## Summary

`Remote(...)` is the one class an owner writes to serve an existing remote over A2A, MCP or both.
It holds what was passed in, checks it, and `.app()` builds one ASGI application from the pieces
specs 003 to 006 already made: the A2A card, executor and app; the MCP extension, server and app. It
adds no protocol logic, no authentication and no route (FR-026). The graph, the tools and the skill
folders are **passed in**, so the modules that define them never import R2C and `Remote` imports no bridge.

**Two jobs, kept apart.** *Checking* happens in `__init__`, is pure, and ends in one of three error
kinds: an `ImportError` that names a missing extra, a `TypeError` for a wrong type, or one `RemoteError`
that lists every other problem. *Building* happens in `.app()`: fresh door pieces, one parent Starlette
whose routes are a single dispatcher, whose lifespan starts and stops both doors.

Research settled what the spec left open, against `a2a-sdk` 1.3.1, `mcp` 2.3.0 and `starlette` 1.10.0
([research.md](research.md)):
- **Composition** is a dispatcher that asks the MCP app's own router "is this yours?", inside a parent
  Starlette; each sub-app keeps its own middleware and the owner's `middleware=` wraps both
  ([R1](research.md#r1-one-app-from-two-door-apps-a-dispatcher-inside-a-parent-starlette-d11));
- **Start and stop** go through an `AsyncExitStack`; one **additive door change, A1**, makes the A2A app
  close its handler when it is left by an exception, so a failing MCP start leaves nothing running
  ([R2](research.md#r2-start-stop-and-failure-of-the-two-doors-fr-022-and-door-change-a1));
- **The agent and the tools are classified by shape**, never by importing an SDK or a bridge: an
  `AgentSource` has `card`, `pause`, `run`, `resume`; an executor has `execute`, `cancel`; a tool is a
  `ToolSpec`, a `SourceTool` or a routine ([R4](research.md#r4-classifying-agent-by-shape-without-importing-an-sdk-fr-004-fr-010),
  [R5](research.md#r5-classifying-tools-the-agent-tool-and-the-card-fr-003-fr-008-fr-011-fr-012-d6));
- **Errors** come in a fixed order, the `ImportError` first, and one table of build problems
  ([R6](research.md#r6-order-of-checks-and-the-three-error-kinds-d10-fr-006-fr-031-fr-032-fr-034),
  [R7](research.md#r7-the-table-of-build-problems-completed-fr-032-and-what-the-plan-adds));
- **Door options** are two small dataclasses with named fields and two pass-through mappings, and the
  keywords `Remote` owns are refused in them
  ([R8](research.md#r8-door-options-and-the-keywords-remote-owns-d12-fr-027));
- **Warnings** (D5, D13) have exact rules ([R11](research.md#r11-the-two-warnings-d5-d13-fr-027-fr-029)).

Three points were not in the approved spec and need the maintainer ([below](#needs-the-maintainer)).

## Technical Context

**Language/Version**: Python ≥ 3.11 (CI: 3.11, 3.12, 3.13)

**Primary Dependencies**:
- runtime core: `pydantic>=2` and `jsonschema>=4`, unchanged;
- extras: unchanged (`[a2a]`, `[mcp]`, `[langgraph]`). **No new dependency and no new extra** (FR-036):
  `Remote` needs the extras of the doors it opens; `starlette` comes with both doors' SDKs.

**Storage**: None. `Remote` holds its configuration in memory. Durable state is the owner's (an A2A task
store, a checkpointer, the MCP request-state keys), reached through the door options.

**Testing**:
- pytest on the installed wheel; async tests use `asyncio.run`, as specs 003 to 006 do.
- Real SDKs and real round trips in process; one app served with its own lifespan to an A2A client and an
  MCP client at once. The only fakes: the scripted chat model (006) and the doors' existing fake sources.
- Real `AsyncSqliteSaver` and an A2A SQLite store over files in `tmp_path` for the restart tests.

**Target Platform**: CPython on any OS; CI on Linux.

**Project Type**: library (the `remote` subpackage of `ext-r2c`)

**Performance Goals**: none beyond the doors'. `Remote` adds one route lookup per request (the MCP router's
match) and nothing else on the request path. The new tests finish in under 60 s on CI.

**Constraints**:
- import rules (constitution VIII): `ext_r2c/remote/` imports `ext_r2c.core` and the standard library at
  module level and a door only inside a function when that door is exposed; no bridge, anywhere; only
  `ext_r2c/__init__.py` imports `remote` (an AST test, as for the doors and the bridge);
- the agent, a tool and a graph are never edited, subclassed or given an attribute (FR-005);
- an approval is asked to a person or an approver and is never answered by `Remote` (V);
- a public repository: invented names and `example.com`; no local path in a test or a message.

**Scale/Scope**:
- 8 modules in `ext_r2c/remote/`, 4 public names ([contracts/remote-api.md](contracts/remote-api.md));
- one two-line change in one door (`a2a/app.py`, A1) and a lazy export in `ext_r2c/__init__.py`;
- about 9 new test files, 3 helper modules, 5 changed existing tests or scripts.

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | `Remote` makes no shape: every ask, answer, card and result is built by the doors from the core's models. `standard/v1/schema/` is untouched | pass |
| II. Wire examples are the shared test suite | No R2C rule is added, so no example is added. The proof is real round trips through both doors and the brief's criteria 1 to 5 served by `Remote`; the replays of 003 and 004 run unchanged | pass (n/a) |
| III. Remote's logic unchanged | The agent, tools and graph are passed in and never edited, wrapped in a subclass or given an attribute; a test snapshots them before and after (FR-005). One line to wrap, one to build | pass |
| IV. An extension, never a protocol | `Remote` adds no route, no card field, no header. The card is `agent_card(...)` as it is; callers that did not activate R2C get text and standard artifacts on both doors (SC-009). The one change to a door (A1) is additive and changes no wire behaviour | pass |
| V. Approval never answered by a model | `Remote` offers no option that answers an approval and never reads the agent framework's list; `answer_by` must be `person` or `approver` (a build error otherwise); a test walks every path that makes an approval (SC-004). [Point 1](#needs-the-maintainer) notes that `Approve` does not check this itself today | pass, one point to confirm |
| VI. Public, neutral data only | Tests use invented tools, texts and ids and `example.com`; messages echo no value the owner typed; leak scan per commit | pass |
| VII. Test first, against the built artifact | Every phase starts with failing tests on the installed wheel; real SDKs and real clients; the model is the only fake; phase 1 pins every SDK fact the design leans on; a mutation check on the safety rows | pass |
| VIII. Small core, bindings behind extras | `remote` imports `core` (and, per exposed door, `a2a` or `mcp` inside a function) and nothing else; no bridge; `import ext_r2c` does not load it; the core-only, a2a-only, mcp-only and langgraph-only runs stay, each extended with `Remote` checks. No new extra | pass |
| IX. Versioned by URI | `standard/v1` untouched. `Remote` names no standard version | pass (n/a) |

Re-check after the Phase 1 design: still a pass. Two additions are worth a line. First, `Remote` loads a
door inside a function, so principle VIII's "loads a door only when it is enabled" is a runtime fact a
test observes (`sys.modules`), not only an import rule. Second, the one door change (A1) fixes a leak in
spec 003's lifespan that only a composing caller can trigger; it is listed here and made test first, as
`PauseLost` was for 006 (spec Assumptions). There is no Complexity Tracking entry.

## Project Structure

### Documentation (this feature)

```text
specs/007-remote/
├── spec.md
├── plan.md                      # this file
├── research.md                  # R1–R16
├── data-model.md                # what Remote holds, derives and builds; states; check order
├── quickstart.md                # validation guide
├── contracts/
│   ├── remote-api.md            # public names, signatures, the errors and warnings table
│   └── app-composition.md       # the dispatcher, the lifespan, A1, identity, the test bed
├── checklists/requirements.md
└── tasks.md                     # from /speckit-tasks (83 tasks in 10 phases, written 2026-11-23)
```

### Source code

```text
python/
├── src/ext_r2c/
│   ├── __init__.py              # + Remote, RemoteError, A2AOptions, MCPOptions, lazily (PEP 562)
│   ├── a2a/
│   │   └── app.py               # A1: try/finally around the lifespan's yield
│   └── remote/
│       ├── __init__.py          # the four public names
│       ├── _errors.py           # RemoteError(ValueError), .problems
│       ├── _options.py          # A2AOptions, MCPOptions, the owned keys (no SDK import)
│       ├── _classify.py         # agent shape, tool normalisation, approve and skills shapes
│       ├── _check.py            # steps 3 to 5 of R6: type checks, collected problems, warnings
│       ├── _doors.py            # load a door (ImportError names the extra); build the two door apps
│       ├── _compose.py          # Dispatch, the lifespan, the parent app, the collision check
│       └── _remote.py           # class Remote: __init__ (R6 steps 1 to 5) and app()
└── tests/
    ├── remote_harness.py            # one app, own lifespan, an A2A and an MCP client over it
    ├── remote_executor.py           # a hand-written executor in the shape of the Currency sample
    ├── test_remote_spike.py         # phase 1: the SDK facts the design leans on
    ├── test_remote_compose.py       # US1/US7: the dispatcher, the paths, `auth` routes, middleware
    ├── test_remote_serve.py         # US1: one real graph through both doors, threads, no-R2C callers
    ├── test_remote_lifecycle.py     # US1: start, stop, a failing door, a second app()
    ├── test_remote_errors.py        # US2: one test per build problem; collected; no echo
    ├── test_remote_approvals.py     # US3: both approval paths, answer_by, never answered by Remote
    ├── test_remote_restart.py       # US4: a rebuild over the same files and keys; D13 warnings
    ├── test_remote_mcp_extras.py    # US5: skills, resources, prompts, the agent tool
    ├── test_remote_executor.py      # US6: a hand-written executor on A2A
    ├── test_remote_options.py       # US7: one door, the options, middleware, the D5 warning
    ├── test_a2a_serve.py            # A1: a test added
    ├── test_packaging.py            # + the remote import rule, the lazy export
    ├── core_only.py                 # + Remote importable, names the extra
    ├── a2a_only.py                  # + an A2A-only Remote serves; mcp is not loaded
    ├── mcp_only.py                  # + the mirror
    └── langgraph_only.py            # + Remote composes with LangGraphAgent

docs and records:
├── python/README.md             # a Remote section (the one line, the table, identity, host guard, durable state)
├── docs/design-docs/one-remote-two-doors.md        # dated notes: mcp_server=, Skills(...), url
├── docs/research/2026-11-20-r2c-v1-design-brief.md # amendment 4
├── ARCHITECTURE.md              # the remote/ rows
├── CHANGELOG.md                 # Added: Remote; Fixed: the A2A lifespan
├── WORKSTATE.md
└── AGENTS.md                    # what it says about Remote; stays under 150 lines
```

**Structure decision.**
- One subpackage `remote/`, as `ARCHITECTURE.md` fixes. Eight small modules keep the pure parts (classify,
  check, options, errors) unit-testable without a door installed, and let one AST test say "module-level
  imports are core and the standard library" for exactly this folder.
- `test_packaging.py` already scans `a2a/`, `mcp/` and `bridges/` recursively; phase 2 adds `remote/` with its
  own two sets (module level, function level).
- The test helpers stay in `python/tests/` and are not shipped. `remote_harness.py` reuses the doors'
  transports, the 006 graph builders and the scripted model.

## Key design decisions

The full reasoning is in [research.md](research.md); the build is in
[contracts/app-composition.md](contracts/app-composition.md).

1. **The app is a dispatcher in a parent Starlette** (R1, D11). The MCP router decides what is MCP's;
   each sub-app keeps its middleware; `middleware=` wraps both.
2. **The lifespan is an `AsyncExitStack` of the two door lifespans** (R2). A1 makes a failing start safe.
3. **Check in `__init__`, build in `app()`** (R6, R12). Three error kinds, one fixed order, nothing built
   before the checks end, one `RemoteError` listing every problem; a failed `app()` consumes the `Remote`.
4. **Shapes, not SDK types** (R4, R5). The agent, the tools and the options are classified without importing
   an SDK or a bridge, so a door that is not exposed is never loaded.
5. **The MCP server always carries R2C** (R9), even with skills only, and takes its name, version and
   description from the one `CardInfo`.
6. **The card address is `url` + `a2a.path`** (R10), so the card cannot advertise a path the app does not serve
   ([point 3](#needs-the-maintainer)).
7. **Warnings by rule** (R11): D13 once per door that can lose a pause; D5 once when `middleware` is given and
   MCP has no owner source.
8. **A lazy export** (R13): `import ext_r2c` stays light; `from ext_r2c import Remote` works with no extra.
9. **Tests spy on the two real objects** (R14) instead of `Remote` exposing the door apps.

## Changes outside the new package

- **`a2a/app.py` (A1)**: the lifespan's `yield` is inside `try`/`finally`. Test first in
  `tests/test_a2a_serve.py`; every existing test passes unchanged; the a2a-only check stays green.
- **`ext_r2c/__init__.py`**: the lazy export (R13). `import ext_r2c.core` still loads nothing of `remote`.
- **`test_packaging.py`, `core_only.py`, `a2a_only.py`, `mcp_only.py`, `langgraph_only.py`**: the import rule,
  the lazy export, the `ImportError` that names the extra, `Remote` in each single-extra run. The CI already
  runs the four scripts, so the workflow does not change.
- **`standard/`**: nothing. No schema, no example, no README rule: `Remote` is an SDK piece.
- **The ADR, the brief, `ARCHITECTURE.md`, `WORKSTATE.md`, `AGENTS.md`, `CHANGELOG.md`, the package README**:
  dated notes and rows in the closing phase (FR-038); bodies of old records are not rewritten.

## Delivery order (input to `/speckit-tasks`; one phase per go)

| Phase | Content | Done when |
|---|---|---|
| 1. Vet and spike | versions and bounds checked, no dependency change; `test_remote_spike.py` pins the facts of R1 to R5, R8 and R9 | tests on the wheel pass; every pinned fact holds, or the plan is updated first |
| 2. Foundation | A1 test first then the fix; `RemoteError`, the options, the empty `remote/` package, the lazy export; the import rule in `test_packaging.py` | a2a suite green; export and rule tests pass; core-only green |
| 3. One line, one app, both doors (US1, P1) 🎯 MVP | `remote_harness.py`; tests for the dispatcher, the real-graph round trips, the lifecycle; `_classify`, `_doors`, `_compose`, `_remote` with the checks one round trip needs (extras, agent shape, expose) | SC-003, SC-007, SC-008 (both doors), SC-009 |
| 4. Build errors (US2, P1) | one test per row of the problem table (R7); `_check.py` complete; collected, ordered, no echo | SC-005 |
| 5. Approvals (US3, P1) | A2A (agent's own gate) and MCP (`approve=`) paths, the `answer_by` check, never `answer_by: caller` | SC-004, SC-001 (approval part) |
| 6. A restart in the middle (US4, P1) | rebuild over the same A2A SQLite files and checkpointer, and the same MCP keys; the D13 warnings | SC-001 (restart part), SC-006 |
| 7. Skills, resources, prompts, agent tool (US5, P2) | `test_remote_mcp_extras.py`; skills, `add_resource`, `add_prompt`, `mcp_tool` | the US5 scenarios |
| 8. A hand-written executor (US6, P2) | `remote_executor.py` in the shape of the Currency sample; on A2A, refused on MCP | SC-002 |
| 9. One door, door options (US7, P3) | `test_remote_options.py`: one door serves only itself and loads only itself; every option takes effect; `middleware` wraps both; the D5 warning | SC-008 (one door) |
| 10. Packaging, docs and final gate | single-extra scripts, the mutation check, README, ADR notes, brief amendment, `WORKSTATE.md` and the rest; an outside review by a code reviewer and a security reviewer; 3.11 / 3.12 / 3.13; leak scan | SC-010, SC-011, SC-012 |

**Order.**
- Phases 1 and 2 first; phase 3 needs both (the harness and `Remote` use the foundation).
- Phase 3 is the MVP. Its `Remote.__init__` has the **first cut** of the checks: the extras, the agent shape,
  `expose` and the tool table, enough for one valid round trip. Phase 4 extends them, each row starting with a
  test that fails on the first cut.
- Phases 5 and 6 need phase 3 (and phase 4 for the `approve` rows). Phases 7, 8 and 9 each need phase 3 and
  are independent of each other.
- Phase 10 is last because it covers everything at once.

## Needs the maintainer

Three points the approved spec did not settle. Each has a default the plan already follows; none blocks
implementation, and any can be reversed before its phase. The plan also made the additions and readings
listed after them; those only tighten (more refusals), and are named so they are not a surprise.

1. **`Approve(answer_by="caller")` is not refused by spec 004 today.**
   - *Example:* `Remote(..., approve={"publish_page": Approve(answer_by="caller")})`. A probe built
     `Approve(answer_by="caller")` with no error, and `mcp_server` would serve the approval as
     `{"role": "caller"}`: an approval addressed to the caller, which principle V forbids (a model could
     answer it).
   - *A (default):* `Remote` refuses it with a build problem naming the tool (problem 16 of R7). `Approve`
     is unchanged. *Cost:* an owner who builds `mcp_server(...)` by hand still has the hole.
   - *B:* also check `answer_by` in `Approve`'s own construction (a few lines and one test in
     `test_mcp_approve.py`, a fix to spec 004). *Cost:* a second door change in a spec that needs only one,
     and a behaviour change to a public dataclass (only for a value its type already forbids).
   - *Recommendation:* A now, because `Remote` does not need B. B is the right next fix and is one task; say
     so and it goes in as its own commit after this spec.
2. **A `Remote` with one door still returns the parent application** (a reading of FR-020).
   - *Example:* `Remote(expose=["a2a"], ...).app()` is a Starlette that wraps the A2A app; its routes are
     the A2A app's and nothing else, and the MCP paths answer `404`. It is not the object `a2a_app(...)`
     returned.
   - *A (default):* one code path for one or two doors, so `middleware=` and the lifespan work the same.
   - *B:* return the door's own app for one door. *Cost:* `middleware=` would be applied two ways (A2A takes it
     as an argument; MCP has no such argument, so `add_middleware` after the fact), and the lifespan twice.
   - *Recommendation:* A. Only the identity of the returned object differs; no route or header does.
3. **`url` is the base of the app, and the card advertises `url` + `a2a.path`** (a refinement of D2).
   - *Example:* `url="https://remote.example.com/api"`, `A2AOptions(path="/rpc")`: the card advertises
     `https://remote.example.com/api/rpc`. With the default path `/`, `url="https://remote.example.com"`
     advertises `https://remote.example.com/`, which is what D2 says too.
   - *A (default):* the base form. The card cannot advertise a path the app does not serve (finding 5's worry).
   - *B:* D2 as worded: `url` is the JSON-RPC address as given. *Cost:* an owner who changes `a2a.path` must
     repeat it inside `url`, and a mismatch is silent.
   - *Recommendation:* A. The two forms differ only when the path is changed.

**Added or read by the plan, beyond the spec's text** (all tighten; each is a row of R7 or a line of
[research.md](research.md)):
- problems 14 (`mcp_tool` without an agent), 16 (`answer_by`), 17 (the `url` shape, value never echoed),
  18 (paths begin with `/`, none under `/.well-known/`) and 19 (keys `Remote` owns in `MCPOptions.server`
  and `.http`);
- `approve` naming any `SourceTool` is a problem (`R2CExtension` would raise a `ValueError` at build;
  `Remote` says it first, with the argument's name);
- a bare `str` for `expose`, `tools`, `approve`, `resources`, `prompts` or `middleware` is a `TypeError`
  (a string would be read as a list of letters); `skills` may be a `str` (a folder);
- the `ImportError` for a missing extra comes first, then `TypeError`, then the collected `RemoteError` (R6);
- the exact D13 and D5 detection rules (R11) and the `MCPOptions.server` keys D5 reads;
- the dynamic collision check against the built MCP router (R10);
- the host guard (`421` for a non-default `Host`) is documented, not defaulted (R8);
- **A1**, the one door change (R2).

## Risks

| Risk | Mitigation |
|---|---|
| The MCP router's matching is an SDK internal (`Starlette.router.routes`) and a new SDK could change the app's shape | the spike pins it on the installed set; `[mcp]` is bounded `<3`; a failing test names the fact; the dispatcher is one small class |
| `StreamableHTTPSessionManager.run` is once per manager; a parent that starts twice breaks | one `Remote` builds one app (D4); the lifespan test enters it once; the second `app()` raises |
| The A2A lifespan fix (A1) touches a door | two lines, test first, the whole a2a suite and the replays unchanged; the fix is exception-safety only |
| The owner's middleware wraps MCP, whose SDK also has authentication | the sub-apps keep their own middleware; a test with both an outer middleware and `auth` on shows each runs once, in order |
| `Remote` becomes a place where authentication is assumed | it adds none (FR-026) and warns (D5); the README says where each door reads its owner |
| The in-memory defaults silently lose a pause at restart | D13 warns once per door (R11); the README shows the durable form for each |
| A source that is not safe to share is served on both doors | the contract is the source's (FR-009); `LangGraphAgent` documents it safe; the README says so for an owner's own source |
| An owner mounts the app inside a larger ASGI app that does not run its lifespan | the README says so; the failure is loud (the MCP door answers an error, not silence) |
| Messages leak a value (a URL with user info, a path) | problems name arguments only; a test asserts a canary value does not appear in any message |
| `Approve` does not validate `answer_by` (spec 004) | `Remote` refuses it; the gap is [point 1](#needs-the-maintainer) |

## Complexity Tracking

None.

## Notes

- Facts about the installed packages were checked on 2026-11-23 with throwaway scripts (the A2A and MCP apps
  composed in one parent Starlette; the lifespan failure; the argument shapes). Phase 1 turns every fact the
  design leans on into a test.
- Specs 002 to 004 call this adapter `006`; the spec numbered it 007. The older records keep their numbers;
  `WORKSTATE.md` has the current sequence.
- The spec's open-for-plan list (names, the exact constructor, how two doors share one agent and one thread,
  how an ASGI app is mounted, errors at build time) is settled in R1, R6, R7 and [contracts/](contracts/):
  the constructor is D1 as written; one source feeds both doors, each with its own `Driver` and its own
  thread id (data-model 7); the app is the dispatcher (R1); errors are R6 and R7.

> **Closing note, 2026-11-23.** Spec 007 is built and closed locally: all ten phases of
> [tasks.md](tasks.md) are done, each committed on its own, none pushed. The body above is kept as planned.
> Where the build differs from it, the reasons are in [research.md](research.md) (R17 the mutation check
> of the safety rows, R18 the outside review), in the notes of `tasks.md` and in the dated notes of
> [contracts/remote-api.md](contracts/remote-api.md) and [contracts/app-composition.md](contracts/app-composition.md).
> The three points of "Needs the maintainer" were built with the recommended answer, A (the reading of
> the maintainer's go that `tasks.md` records; they were not answered one by one). The risks table held: the one that
> did not is the identity row (the review showed the A2A door has no owner of its own without a
> middleware or a resolver, and no warning says so; a warning is proposed, not built). What the maintainer
> still has to read or decide is at the end of `tasks.md` and in `WORKSTATE.md`.
