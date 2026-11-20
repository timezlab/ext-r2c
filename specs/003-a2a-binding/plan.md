# Implementation Plan: A2A binding (`ext_r2c.a2a`)

**Branch**: `main` (folder `specs/003-a2a-binding`) | **Date**: 2026-11-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-a2a-binding/spec.md`

## Summary

Build `ext_r2c.a2a`, the A2A door, on a2a-sdk 1.3 behind `[a2a]`. It has these parts:

**Remote side**
- `SourceExecutor` runs an `AgentSource` through the core's `Driver`. It holds one `Run` per
  task across a2a-sdk's one-`execute`-per-message calls, and re-reads the pending request from
  the stored task.
- `R2CTask` is the helper set that `SourceExecutor` is built on, and that a hand-written
  executor can use.
- `agent_card` and `a2a_app` assemble the card and the app. The app builder installs the two
  pieces a2a-sdk lacks: activation decided per request, and the echoed `A2A-Extensions` header.

**Caller side**
- `R2CClient` reads typed items, checks and sends answers, reattaches, and fetches same-origin
  content only.

**Tests and standard**
- Every A2A example is replayed in client mode, and where a source can produce it, in door mode
  for both pause styles.
- The standard records O8, O9 and O10, with two new examples.

Research found these gaps in a2a-sdk:
- no extension echo ([R3](research.md#r3-activation-and-the-echoed-header));
- a buffering test transport ([R14](research.md#r14-in-process-transport-for-tests));
- floats for every number ([R12](research.md#r12-numbers-in-protobuf-value));
- no check for a second task in a context ([R10](research.md#r10-one-unfinished-task-per-context-o9)).

It also found one core change: `ReplyChunk.last` ([R5](research.md#r5-reply-chunks)). The spec's
reply-without-activation assumption was wrong and has been corrected.

## Technical Context

**Language/Version**: Python ≥ 3.11 (CI: 3.11, 3.12, 3.13)

**Primary Dependencies**:
- runtime core: `pydantic>=2` and `jsonschema>=4` (unchanged);
- extra: `[a2a]` = `a2a-sdk[http-server]>=1.3,<2` (adds Starlette and sse-starlette; httpx and
  protobuf come with a2a-sdk);
- dev group: `a2a-sdk[http-server,sqlite]>=1.3,<2` (SQLite `DatabaseTaskStore` for the restart
  test), the rest unchanged.

**Storage**:
- The door keeps a `Run` per task in memory only. Durable state is the task store's (any a2a-sdk
  `TaskStore`) and the source's own.
- The tests use `InMemoryTaskStore`, and `DatabaseTaskStore` on a SQLite file in `tmp_path`.

**Testing**:
- pytest on the installed wheel. Async tests use `asyncio.run`, as in 002.
- Round trips use a2a-sdk's client and server over the streaming in-process ASGI transport
  (`tests/a2a_transport.py`, not shipped).
- Owners come from a test authentication middleware (`Authorization: Bearer <name>` →
  `SimpleUser`).

**Target Platform**: CPython on any OS; CI on Linux

**Project Type**: library (the `a2a` subpackage of `ext-r2c`)

**Performance Goals**:
- the door adds no I/O beyond a2a-sdk's own, except one owner-scoped `list` of the context's
  tasks when a new task opens (R10);
- the replay suite finishes in under 30 s in CI.

**Constraints**:
- import rules (constitution VIII; AST test plus an A2A-only venv);
- no network port in tests;
- public repository: invented data, `example.com`;
- R2C text never parsed for instructions (R2C-SAFETY-6 is the caller's, and the client hands
  out typed data only).

**Scale/Scope**:
- 8 modules in `a2a/`, about 25 public names ([contracts/a2a-api.md](contracts/a2a-api.md));
- 30 → 32 A2A examples;
- about 10 new test files.

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | every R2C object crossing the wire is parsed and written by the core models, which the schemas judge; no new shape | pass |
| II. Wire examples are the shared test suite | every A2A example is replayed in client mode, door mode where possible, and the exemptions are listed and enforced (R17); two new examples for O9 and O10 | pass |
| III. Remote's logic unchanged | an `AgentSource` is served as it is; a hand-written executor adds helpers without a rewrite (story 6) | pass |
| IV. An extension, never a protocol | only `metadata[URI]`, `capabilities.extensions` and `A2A-Extensions`; `required: false`; without activation only text and standard artifacts; O9 uses A2A's own `TASK_STATE_REJECTED` | pass |
| V. Approval never answered by a model | enforced by the client (FR-022), as the principle says ("clients MUST enforce this"); the remote takes `answered_by` as a claim (O8, R2C-ANSWER-6) | pass |
| VI. Public, neutral data | new examples reuse the invented report data; leak scan per commit | pass |
| VII. Test first, against the built artifact | each phase starts with failing tests on the installed wheel; round trips through the real a2a-sdk client and server, with only the network edge replaced | pass |
| VIII. Small core, bindings behind extras | `a2a` imports core and a2a-sdk only; an A2A-only venv step; the core change is additive and needs no new dependency | pass |
| IX. Versioned by URI | v1 is draft; the O8, O9 and O10 text is additive prose; the URI is unchanged | pass |

Re-check after Phase 1 design: still pass. The only core change is one defaulted field. No
Complexity Tracking entry.

## Project Structure

### Documentation (this feature)

```text
specs/003-a2a-binding/
├── spec.md
├── plan.md                      # this file
├── research.md                  # R1–R18
├── data-model.md                # door state, answer outcomes, client items
├── quickstart.md                # validation guide
├── contracts/
│   ├── a2a-api.md               # public names and signatures
│   ├── wire-mapping.md          # run events ⇄ A2A, active and not
│   └── replay.md                # the example replay: modes, normalising, exemptions
├── checklists/requirements.md
└── tasks.md                     # from /speckit-tasks
```

### Source code

```text
python/
├── pyproject.toml               # [a2a] = a2a-sdk[http-server]; dev a2a-sdk[http-server,sqlite]
├── src/ext_r2c/
│   ├── core/events.py           # ReplyChunk.last
│   └── a2a/
│       ├── __init__.py
│       ├── _codec.py
│       ├── activation.py
│       ├── card.py
│       ├── task.py
│       ├── executor.py
│       ├── app.py
│       └── client.py
└── tests/
    ├── a2a_transport.py         # streaming in-process ASGI transport (R14)
    ├── a2a_harness.py           # app/client factories, test auth, scripted source, wire executor
    ├── test_a2a_codec.py
    ├── test_a2a_serve.py        # US1, both fakes of 002
    ├── test_a2a_activation.py   # US3
    ├── test_a2a_answers.py      # US2
    ├── test_a2a_threads.py      # US4: owners, O9, follow-up
    ├── test_a2a_restart.py      # US4: SQLite store rebuilt
    ├── test_a2a_client.py       # US5
    ├── test_a2a_helpers.py      # US6
    ├── test_a2a_replay.py       # US7
    ├── test_packaging.py        # + a2a import rules, extras
    └── a2a_only.py              # run by CI in a wheel[a2a] venv (not collected)

standard/v1/
├── README.md                    # R2C-ANSWER-6, R2C-ID-2, R2C-ACTIVITY-2, R2C-A2A-4 prose; §11 note
└── examples/a2a/
    ├── second-task-rejected.json   # new (R2C-ID-2, O9)
    └── usage-with-activity.json    # new (R2C-A2A-4, R2C-ACTIVITY-2, O10)

.github/workflows/python.yml     # + A2A-only step
```

**Structure Decision:** one subpackage `ext_r2c/a2a/`, as fixed by `ARCHITECTURE.md`.
- Test helpers stay in `python/tests/` and are not shipped. The streaming transport and the
  harness are importable there for 006.
- `a2a_only.py` is a script, like `core_only.py`.

## Key design decisions

The full reasoning is in [research.md](research.md).

1. **One run per task across execute calls** (R1). Answers are `deliver`ed. After a restart,
   `Driver.resume` with the request read from the task.
2. **No private state** (R2). The pending request and the last usage are read from the stored
   task.
3. **Activation decided before execute, echoed by middleware** (R3). Both are installed by
   `a2a_app`.
4. **The reply is one `reply` artifact, ended by the source** (R5). `ReplyChunk.last` is new.
   Without activation, the reply goes into the next status text.
5. **Answers routed by problem code** (R7). `caller_on_approval` is dropped on the remote side
   (O8). Expiry is applied when the next message arrives (R8). Text answers only per R2C-ASK-8
   (R9).
6. **A second unfinished task is rejected** (R10). It uses an owner-scoped store `list` and a
   lock per (owner, context).
7. **Same owner resolver for store and thread** (R11). The app builder guarantees it.
8. **Replay in two modes with enforced exemptions** (R17).
9. **`SourceExecutor` is built on `R2CTask`** (R18).

## Changes to the standard (FR-030)

- **R2C-ANSWER-6:** add that a remote takes `answered_by` as given and need not refuse an answer
  for its role; R2C-ANSWER-4 and R2C-ANSWER-5 are enforced by the client.
- **R2C-ID-2:** the refusal is a new task ended in `TASK_STATE_REJECTED` whose status text names
  the unfinished task. New example `a2a/second-task-rejected.json`.
- **R2C-ACTIVITY-2:** an update MAY change `label`; a client shows the latest.
- **R2C-A2A-4:** any status message MAY carry at most one usage Part, beside a request or an
  activity. New example `a2a/usage-with-activity.json`: a step whose label changes from
  running to done, and a usage in the same working status.
- **§11 note:** an A2A SDK may leave out `required: false` on the card; absent means the same.
- **Records:** in `CHANGELOG.md`, an Added entry for the door and a Changed entry for the four
  rules. The O8, O9 and O10 notes in `specs/001-standard-v1/research.md` say where the text went.
  The rule count stays 84.

## Delivery order (input to `/speckit-tasks`; one phase per go)

| Phase | Content | Done when |
|---|---|---|
| 1. Packaging and test bed | extras; `a2a/` skeleton; import rules and the A2A-only step; `ReplyChunk.last`; `a2a_transport.py`, test auth, app/client factories | tests on the wheel pass; `a2a only: ok`; a trivial round trip streams event by event |
| 2. Codec (foundational) | `_codec.py`: R2C ⇄ Part and Artifact, the Value number fix, reading the pending request and the last usage from a Task, `answer_text`, the text answer (R9) | every R2C Part and artifact in the A2A examples decodes to its object and encodes back equal |
| 3. Serve (US1 and US3, P1) | `activation.py`, `card.py`, `task.py` (emitting), `executor.py`, `app.py`; question, approval, deny, decline and cancel, both fakes; with and without activation; `agent-card.json` | SC-002, SC-004 |
| 4. Answers (US2, P1) | `R2CTask.take_answer`; re-ask, refuse, expiry with a clock, size, several answers, roles ignored; R2C-ANSWER-6 text | SC-003 |
| 5. Threads and restart (US4, P1) | thread id per owner, R10 rejection, follow-up, SQLite restart, live lost; R2C-ID-2 text and `second-task-rejected.json` | SC-005, SC-006 |
| 6. Client (US5, P2) | `client.py`: items, `answer`, `reattach`, `get_task`, `cancel`, `fetch` with the origin rule and limits | story 5 scenarios; SC-008 |
| 7. Helpers by hand (US6, P2) | a test-only hand-written executor on `R2CTask`; docstrings for the helper API | SC-007 |
| 8. Replay and the rest of the standard (US7, P1) | `a2a_harness.py` scripted source and wire executor; `test_a2a_replay.py`; R2C-ACTIVITY-2 and R2C-A2A-4 text, `usage-with-activity.json`, the §11 note | SC-001; every `wire` rule still has an example |
| 9. Docs and final gate | `ARCHITECTURE.md`, `python/README.md`, `WORKSTATE.md`, `CHANGELOG.md`, `docs/whitepaper.md` where names changed; dated note on spec 002's contract for `ReplyChunk.last`; 3.11 / 3.12 / 3.13; leak scan; outside review of the diff | SC-009 |

**Order:**
- Phases 1 and 2 come first: every later phase uses the transport and the codec.
- Phases 3, 4 and 5 are serial; each extends `task.py` and `executor.py`.
- Phase 6 needs only phase 2 for its unit parts, and phase 3 for round trips.
- Phase 7 needs phase 4.
- Phase 8 needs all of them, and is last because it covers every example at once.

## Risks

| Risk | Mitigation |
|---|---|
| a2a-sdk changes the private-feeling pieces we lean on (`DefaultServerCallContextBuilder`, the producer's one-execute-per-message) in a 1.x release | `>=1.3,<2`; the round trips fail loudly; the builder and middleware are about 50 lines to adapt |
| A subscribe at input-required never ends (a2a-sdk) | `reattach` stops reading at input-required or a terminal state, and the tests have a timeout |
| A cut stream does not stop the run; events emitted while nobody listens are only in the snapshot | `reattach` starts from the snapshot (`TaskItem`) and the client diffs nothing it did not see; documented |
| The replay converter grows clever enough to hide door bugs | the converter only maps objects to events, never states or text; exemptions are a fixed list, checked both ways |
| A context id longer than 36 characters fails on a SQL task store (`String(36)` in a2a-sdk) | documented in the README; the door does not shorten ids |
| Anonymous callers share an owner | documented; authentication is the deployment's (constitution Technical Constraints) |

## Complexity Tracking

None.
