# Implementation Plan: LangGraph bridge (`ext_r2c.bridges.langgraph`)

**Branch**: `main` (folder `specs/006-langgraph-bridge`) | **Date**: 2026-11-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-langgraph-bridge/spec.md` (approved by the
maintainer on 2026-11-22, decisions D1–D11 as written, D2 and D3 included)

## Summary

`LangGraphAgent(graph)` makes a compiled LangGraph graph (a LangChain agent) an `AgentSource` of
the checkpoint style, so the A2A door and the MCP door serve it with no change to the graph. The
bridge does one job: turn what the graph streams and where it pauses into the core's run events,
and turn the caller's answer back into what the graph expects. It lives in
`ext_r2c.bridges.langgraph`, behind the `[langgraph]` extra, and imports only `ext_r2c.core`.

**One run is a sequence of legs.** A leg is one call of `astream`: `run` starts one with the new
human message, `resume` starts one with the answer. A leg has three parts:
- a **producer task** that iterates `astream(stream_mode=["messages", "updates"])`;
- a **per-run callback handler** in the run's config that reports tool starts, ends and errors,
  and which model calls are tagged `nostream`;
- one `asyncio.Queue` that merges both into one ordered stream, read by the generator that yields
  the run events.

**A pause is read from the checkpointer, never from the stream.** After the stream ends, the leg
reads the pending interrupts, classifies each one by the shape of its payload (a middleware
approval in `per_call` or `batched` mode, a hand-written R2C request, anything else), and yields
one `Ask` for the first. An answer is matched by the request id against the pending set again, so a
pause the checkpointer does not hold is never resumed (the one core addition, `PauseLost`, makes
that end the run `lost`).

**The bridge never sends the graph a resume it would refuse.** It reads what each call allows from
the interrupt's own response schema, checks the answer against that before the graph is touched,
keeps the decisions of a `batched` interrupt in memory until all are given, and settles a pending
approval by a state update before a new input.

Research settled what the spec left open, against langchain 1.5.2 and langgraph 1.2.24 and against
the lowest set the extra will allow ([research.md](research.md)):
- the extra's bounds come from a check of the oldest set that has the `per_call` mode
  ([R1](research.md#r1-bounds-of-the-langgraph-extra-and-the-dev-group));
- the stream cannot tell a running tool from one the middleware paused, but a callback handler can
  ([R3](research.md#r3-one-leg-of-a-run-the-stream-a-callback-handler-and-a-queue-d5));
- `nostream` hides tokens only, and the finished message still arrives whole; the handler's list of
  hidden message ids is what keeps FR-008's promise
  ([R5](research.md#r5-the-reply-chunks-the-final-last-paragraph-breaks-nostream-structured-json));
- a new input on a pause is settled by `aupdate_state`, not by a rejecting resume
  ([R11](research.md#r11-a-new-input-on-a-pending-approval-settle-by-a-state-update-d9-fr-007));
- `input_required` is read from the `structured_response` the model node's update carries, and a
  JSON text that starts with `{` is held back until then
  ([R12](research.md#r12-input_required-d10-and-the-open-completed-reply));
- the allowed decisions of a `per_call` interrupt are read from its `response_schema`
  ([R9](research.md#r9-turning-an-answer-into-the-graphs-decision-fr-016-to-fr-020)).

Five points were not in the approved spec and need the maintainer ([below](#needs-the-maintainer)).

## Technical Context

**Language/Version**: Python ≥ 3.11 (CI: 3.11, 3.12, 3.13)

**Primary Dependencies**:
- runtime core: `pydantic>=2` and `jsonschema>=4`, unchanged;
- extra: `[langgraph]` = `langchain>=1.4.6,<2`, `langchain-core>=1.6.10,<2` and
  `langgraph>=1.2.14,<2` (the floor moved from 1.2.12 on 2026-11-22: R1, T001; replaces `langchain>=1.3` and `langgraph`; R1). No checkpointer in the
  extra (FR-027);
- dev group: the same three bounds and `langgraph-checkpoint-sqlite>=3.1.3,<4` (the tests'
  durable checkpointer; it brings `aiosqlite`).

**Storage**:
- None written by the bridge. The thread's state is the owner's checkpointer.
- In memory: the decisions of a `batched` interrupt in progress (D8), at most 1024 records; nothing
  else survives a leg.

**Testing**:
- pytest on the installed wheel. Async tests use `asyncio.run`, as specs 003 to 005 do.
- Real `langgraph` and `langchain` everywhere; the only fake is a scripted chat model (a pure
  function of the message history, R17). A real `AsyncSqliteSaver` over a file in `tmp_path` for
  the restart tests; `InMemorySaver` where a restart must lose the pause.
- The shared suite (S1–S10) on the real source through a test-only wrapper (D3); the two door round
  trips use the existing replay-kit harnesses (`tests/a2a_replay_kit.py`, `tests/mcp_replay_kit.py`
  and the in-process transports).

**Target Platform**: CPython on any OS; CI on Linux.

**Project Type**: library (the `bridges.langgraph` subpackage of `ext-r2c`)

**Performance Goals**:
- The first reply chunk reaches a reader before the model produces its last token (SC-007); the
  hold-one rule costs one chunk of latency (R5).
- The bridge adds one `aget_state` per leg (two when a pause is asked) and, at the end of a turn,
  one read of the messages for usage. No other graph calls.
- The new tests finish in under 60 s on CI.

**Constraints**:
- the import rules (constitution VIII): `bridges/langgraph/` imports `ext_r2c.core` and the extra's
  packages only (an AST test, as for the doors); no other module of `ext_r2c` imports it;
- the graph is not edited, subclassed or given a hook (FR-001): the handler travels in the run's
  `config`, not on the graph;
- an approval is asked to a person or an approver and is never answered by the bridge (V);
- a public repository: invented names and `example.com`; no local paths in the tests.

**Scale/Scope**:
- 13 modules in `bridges/langgraph/`, 3 public names ([contracts/langgraph-api.md](contracts/langgraph-api.md))
  and one in the core (`PauseLost`);
- one small change in `core/source.py` and `core/__init__.py`; the shared suite
  (`tests/agent_source_suite.py`), its caller and the fakes' one reply chunk;
- about 12 new test files, 3 new helper modules, 3 changed existing tests or scripts.

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | The bridge makes no new shape: every ask is built with the core's models, and a hand-written payload is accepted only when the core's `parse` says it is a valid R2C object. `standard/v1/schema/` is untouched | pass |
| II. Wire examples are the shared test suite | No R2C rule is added, so no example is added. The bridge's proof is the shared `AgentSource` suite on a real graph and two real door round trips (SC-001, SC-002); the replay kits of 003 and 004 are used as they are | pass (n/a) |
| III. Remote's logic unchanged | The graph object is never touched: no subclass, no wrapper node, no hook. The only thing added to a run is a per-run callback handler inside the `config` the bridge builds itself, and the only writes to the thread are the settle of D9 (messages in the saved state, written through LangGraph's own API) and the answer's resume. See [point 2](#needs-the-maintainer) for the wording of FR-001 | pass, one point to confirm |
| IV. An extension, never a protocol | One additive piece in the core (`PauseLost`, D2, approved); no change to A2A or MCP; the doors map `lost` as they do today. Unknown fields and kinds are untouched | pass |
| V. Approval never answered by a model | Every approval the bridge builds has `answer_by` of person or approver; an approval a graph writes by hand and addresses to the caller is asked as a question for a person instead (R8); the bridge answers none, and a test walks every path that yields an approval (SC-006) | pass |
| VI. Public, neutral data only | Tests use invented tools, texts and ids; scratch probes stay out of the repo; leak scan per commit | pass |
| VII. Test first, against the built artifact | Every phase starts with failing tests on the installed wheel; real packages and a real SQLite file; the model is the only fake; the first phase pins every library fact the design leans on; a mutation check on the changed suite (SC-009 and R17) | pass |
| VIII. Small core, bindings behind extras | One class added to the core; the bridge is behind `[langgraph]`; imports go `core ← bridges.langgraph` only; `Remote` (007) will not import it; the core-only, a2a-only and mcp-only runs stay, and a langgraph-only run is added. The Technical Constraints line is amended (PATCH, [point 3](#needs-the-maintainer)) | pass |
| IX. Versioned by URI | `standard/v1` is untouched. The bridge names no standard version | pass (n/a) |

Re-check after the Phase 1 design: still a pass. Two additions are worth a line. First, the
bridge reads `HumanInTheLoopMiddleware`'s payloads by shape and never imports the middleware, so a
hand-built graph that uses the same shapes is served the same way, and a change in LangChain shows
up in the spike test, not in the field. Second, D3 changes a file of spec 002 (the suite); that is
a test file, not behaviour, and the change is dated in the 002 contract. There is no Complexity
Tracking entry.

## Project Structure

### Documentation (this feature)

```text
specs/006-langgraph-bridge/
├── spec.md
├── plan.md                      # this file
├── research.md                  # R1–R18
├── data-model.md                # records the bridge holds, the mappings, the limits
├── quickstart.md                # validation guide
├── contracts/
│   ├── langgraph-api.md         # public names and signatures
│   ├── pause-mapping.md         # graph pause kind → what the caller sees → what the graph gets;
│   │                            #   stream and callback → run events
│   └── suite-changes.md         # D3: the shared suite, before and after
├── checklists/requirements.md
└── tasks.md                     # from /speckit-tasks (104 tasks in 10 phases, written 2026-11-22)
```

### Source code

```text
python/
├── pyproject.toml               # [langgraph] bounds; dev group the same + the SQLite saver
├── src/ext_r2c/
│   ├── core/
│   │   ├── source.py            # + class PauseLost; _pump: except PauseLost → Error("lost")
│   │   └── __init__.py          # + PauseLost
│   └── bridges/
│       ├── __init__.py          # a docstring only
│       └── langgraph/
│           ├── __init__.py      # public names; the ImportError that names the extra
│           ├── agent.py         # LangGraphAgent: wrap checks, card, run and resume, the glue
│           ├── _leg.py          # one leg: producer task, queue, the consumer that yields events
│           ├── _handler.py      # the per-run callback handler: tool events, hidden message ids
│           ├── _reply.py        # hold-one and `last`, paragraph break, the JSON hold
│           ├── _reasoning.py    # reasoning deltas coalesced without timers
│           ├── _blocks.py       # RunInput → one HumanMessage; content blocks → ArtifactEvent
│           ├── _usage.py        # usage summed from the checkpoint's messages
│           ├── _pauses.py       # pending interrupts → classified pauses → the Ask; request ids
│           ├── _decisions.py    # allowed decisions from the schema; answer ↔ graph decision
│           ├── _batch.py        # the decisions of a batched interrupt, in memory, bounded
│           ├── _settle.py       # D9: withdraw a pending approval before a new input
│           ├── _structured.py   # D10: structured_response → input_required
│           └── tools.py         # tool_from_langchain, tools_from_langchain
└── tests/
    ├── langgraph_models.py          # the scripted chat model (stateless, strict, gated, no-stream)
    ├── langgraph_graphs.py          # graph builders for the stories; the SQLite "restart" helper
    ├── langgraph_suite_source.py    # D3(c): the test-only wrapper the shared suite drives
    ├── test_langgraph_spike.py      # phase 1: the library facts the design leans on
    ├── test_langgraph_wrap.py       # US1: wrap checks, card, options, the in-memory warning
    ├── test_langgraph_run.py        # US1: reply chunks, `last`, paragraph break, nostream, hold
    ├── test_langgraph_suite.py      # US1: the shared suite on a real graph
    ├── test_langgraph_doors.py      # US1: real A2A and MCP round trips, PauseLost per door
    ├── test_langgraph_approvals.py  # US2: per_call and batched, every answer, every refusal
    ├── test_langgraph_batch.py      # US2: the batch memory and its bound
    ├── test_langgraph_restart.py    # US3: SQLite restart, ids, lost, answer already applied
    ├── test_langgraph_timeline.py   # US4: tool activity, reasoning, usage, files, options
    ├── test_langgraph_pauses.py     # US5: hand-written interrupts, fallback, order
    ├── test_langgraph_structured.py # US5: input_required on a real response_format
    ├── test_langgraph_settle.py     # US5: a new input on a pause; the mutation check
    ├── test_langgraph_tools.py      # US6: tool_from_langchain
    ├── test_core_pause_lost.py      # D2: the core piece, with no langgraph
    ├── test_agent_source.py         # D3: also runs the shared suite on the real source
    ├── agent_source_suite.py        # D3: structural sequence checks
    ├── fake_sources.py              # D3: the fakes' reply chunk carries last=True
    ├── test_packaging.py            # + the extra's bounds, the bridge import rule, ImportError
    ├── core_only.py                 # + no langgraph module is loaded
    └── langgraph_only.py            # new: the wheel with [langgraph] and no dev group

docs and records:
├── python/README.md             # a LangGraph section (wrap, options, restart, the batched limit)
├── ARCHITECTURE.md              # the bridges/langgraph/ rows (the layout already names the folder)
├── CHANGELOG.md                 # Added
├── WORKSTATE.md
├── .specify/memory/constitution.md   # Technical Constraints line; Sync Impact Report; PATCH
├── .github/workflows/python.yml # a langgraph-only step beside the others
├── docs/design-docs/langgraph-pause-to-ask.md   # ADR: the pause-to-ask rules, finding 2, D9
├── docs/whitepaper.md, docs/research/2026-11-20-r2c-v1-design-brief.md
│                                # dated notes where they name `serve()` or `a2a/langchain`
├── specs/002-python-core/contracts/core-api.md  # dated note: PauseLost; the suite's shape
└── AGENTS.md                    # one row in the Docs table (the ADR); stays under 150 lines
```

**Structure decision:**
- One subpackage per agent framework under `ext_r2c/bridges/`, as `ARCHITECTURE.md` fixes. The
  spec said "in `ext_r2c.bridges.langgraph`"; thirteen small modules keep the pure parts (reply,
  reasoning, decisions, pauses, batch) unit-testable without a graph, and let one AST test say
  "imports only core" for exactly this folder.
- `test_packaging.py` already scans `a2a/` and `mcp/` recursively; phase 1 adds `bridges/` with its
  own allowed set (R18).
- The test helpers stay in `python/tests/` and are not shipped. `Remote` (007) will reuse the
  scripted model and the graph builders.

## Key design decisions

The full reasoning is in [research.md](research.md).

1. **A leg is a producer task, a handler and one queue** (R3). The generator is the only consumer;
   its `finally` cancels and awaits the producer, so a cancel by the door closes the stream.
2. **Tools are `running` only while their body runs, by a per-run callback handler** (R3, R4, D5).
   A pause inside a tool body (`GraphBubbleUp`) is not a failure: the activity stays `running` and
   the restarted body reports `running` again on the next leg.
3. **The reply holds one chunk back** (R5). The held piece leaves `last=False` when the model asks
   for tools, when the leg ends in an `Ask`, or when the graph raises; at the end of a turn it
   leaves `last=True`. `nostream` is honoured by the handler's hidden ids.
4. **A pause is read from the checkpointer and classified by shape** (R8). Order: tool approvals in
   the model's tool-call order, then the others as LangGraph lists them; one `Ask`, then the leg
   ends. Ids are stable (`lg-<interrupt id>`, `…-<n>` for a batched call).
5. **Allowed decisions come from the interrupt, not from a guess** (R9). `per_call`: the
   `response_schema`; `batched`: `allowed_decisions`. A `per_call` payload with no readable decision
   ends `failed` before any ask ([point 5](#needs-the-maintainer)).
6. **Validate before the graph, in both modes** (R9, FR-020). A refused answer ends the run
   `failed`, touches nothing, and the same pause is still pending for the next, correct answer.
7. **A batch in progress is memory** (R10, D8): a bounded map; a restart in the middle asks the
   batch again from its first call.
8. **A new input settles a pending approval by a state update** (R11, D9): the finished tool
   messages plus one "withdrawn" tool message per call with no answer, then the input.
9. **`input_required` is read from the `structured_response` of the leg's own updates** (R12,
   D10); the structured JSON of that turn is not streamed as reply.
10. **A lost pause is `PauseLost`** (R13, D2): raised in `resume` when the checkpointer holds no
    pending interrupt for the answer's id; the driver ends the run `lost`; the graph is not started.
11. **Usage is summed from the checkpoint** (R7, D7): once per turn, the same with or without a
    restart, no cost and no duration.
12. **Tools convert with the model-visible schema and are validated first** (R16): injected
    arguments are refused at conversion; `jsonschema` checks the arguments before the tool runs.
13. **The suite becomes structural where streaming differs** (R17, D3): a wrapper records answers
    and misbehaves on demand; a mutation check shows the changed suite still fails wrong sources.

## Changes outside the new package

- **`core/source.py`, `core/__init__.py`**: `PauseLost` and one `except` branch in `Driver._pump`
  (D2). Additive; every existing test passes unchanged; the core-only check stays green.
- **`tests/agent_source_suite.py`, `tests/test_agent_source.py`, `tests/fake_sources.py`**: the
  sequence checks compare a shape; the fakes' one reply chunk gets `last=True`; the real source is
  run through the wrapper (D3, [contracts/suite-changes.md](contracts/suite-changes.md)).
- **`pyproject.toml`**: the extra and the dev group (R1). **`.specify/memory/constitution.md`**: the
  Technical Constraints line, version 1.1.2, with a Sync Impact Report, in the same commit as the
  extra.
- **`test_packaging.py`, `core_only.py`, `langgraph_only.py`, `.github/workflows/python.yml`**: the
  import rule, the extra, the ImportError that names the extra, the new check.
- **`standard/`**: nothing. No schema, no example, no README rule: the bridge is an SDK piece.
- **`docs/whitepaper.md` and the design brief** name `serve()` and `a2a/langchain` where this spec
  now says `LangGraphAgent` and `bridges/langgraph`; each gets a dated note in the closing phase
  (the body is a record, not rewritten). **`AGENTS.md`** gets one row (the ADR).
- **`specs/002-python-core/contracts/core-api.md`** gets a dated note: `PauseLost`, and the suite's
  structural sequence checks.

## Delivery order (input to `/speckit-tasks`; one phase per go)

| Phase | Content | Done when |
|---|---|---|
| 1. Packaging, vet and spike | OSV vet and lowest-direct check re-run (T001); the extra and dev group; constitution PATCH 1.1.2; the empty `bridges/langgraph/` with its `ImportError`; `test_packaging.py` (bounds, import rule, no `a2a` or `mcp` loaded); the scripted model and graph builders; `test_langgraph_spike.py` pinning the library facts of R3, R5, R9, R11, R12 and R14 | tests on the wheel pass; every pinned fact holds, or the plan is updated first |
| 2. The core piece and the suite (D2, D3a) | `PauseLost` test first, then the code; the suite's structural sequence checks; both fakes pass the changed suite; the mutation check on the suite (scratch run) | core-only green; the fakes pass; every mutant of the suite dies |
| 3. Wrap, run, reply (US1, P1) 🎯 MVP | `agent.py`, `_leg.py`, `_handler.py` (first cut: hidden ids), `_reply.py`, `_blocks.py` (input), `_pauses.py` (first cut: a hand-written valid R2C request), `_usage.py` (first cut: tokens summed from the checkpoint), the wrap checks and the in-memory warning; `langgraph_suite_source.py` | SC-001 (the suite S1–S10 on a real graph), SC-007 |
| 4. Both doors (US1) | real in-process A2A and MCP round trips with a pause and an answer, a reply across the pause, `PauseLost` shown as `lost` by each door, a door refusing a large reply (a large file block is added in phase 7) | SC-002 |
| 5. Approvals (US2, P1) | `_decisions.py`, `_batch.py`, the middleware payloads in `_pauses.py`, the tool schema lookup for `edit`; both modes, every answer, every refusal | SC-004, SC-005, SC-006 |
| 6. A pause survives a restart (US3, P1) | the SQLite restart tests for `per_call`, `batched` and a hand-written interrupt; equal ids; an in-memory saver ends `lost`; an answer applied twice | SC-003 (scenario 6, usage across a restart, closes in phase 7) |
| 7. The timeline (US4, P2) | the handler's tool events, `_reasoning.py`, `_usage.py` completed (model name, a restart in the middle), files in `_blocks.py`, the options | SC-008 |
| 8. Other pauses, and a new input (US5, P2) | the fallback question, sequential and parallel interrupts, `_structured.py` on a real `response_format`, `_settle.py`; the mutation check of D9 | SC-009 |
| 9. LangChain tools (US6, P3) | `tools.py`: conversion, injected arguments refused, arguments checked, a sync tool off the loop | SC-011 |
| 10. Docs and final gate | README, `ARCHITECTURE.md`, `CHANGELOG.md`, `WORKSTATE.md`, the ADR, the dated notes, `AGENTS.md`; the CI step; an outside review by a code reviewer and a security reviewer with no memory of the work; 3.11 / 3.12 / 3.13; core-only, a2a-only, mcp-only, langgraph-only; leak scan | SC-010, SC-012 |

**Order:**
- Phases 1 to 3 first: every later phase uses the scripted model, the builders and the leg.
- Phase 3 is the MVP. Its `_handler.py`, `_pauses.py` and `_usage.py` are **first cuts**: the
  handler reports only the hidden message ids, `_pauses.py` asks only a hand-written valid R2C
  request (what the suite's graph writes), and `_usage.py` sums the tokens (the suite's shape needs
  a `usage` event from the first run). Phases 5, 7 and 8 extend them, each starting with tests that
  fail on the first cut.
- Phase 4 needs phase 3 and `PauseLost` from phase 2.
- Phases 5 and 7 are independent of each other; both need phase 3.
- Phase 6 needs phase 5 (it restarts approvals) and, for scenario 6, phase 7.
- Phase 8 needs phase 5 (the settle reads the middleware payloads).
- Phase 9 needs only phase 1 and the core.
- Phase 10 is last because it covers everything at once.

## Needs the maintainer

**Answered 2026-11-22: the maintainer took the recommendation (A) on all five points.** The text
below is kept as the record of the question. `tasks.md` carries each answer into a task.

Five points the approved spec did not settle. Each has a default the plan already follows; none
blocks `/speckit-tasks`, and any of them can be reversed before its phase.

1. **A `completed` structured reply has no reply text under `ToolStrategy`.**
   - *Example:* `create_agent(..., response_format=ToolStrategy(Reply))` with
     `Reply(status, message)`. The model ends a turn by calling the `Reply` tool with
     `status="completed"`, `message="The report is ready."`. LangChain streams no text for that call.
     The caller sees `done` and no reply text. Under `ProviderStrategy` the JSON is streamed as the
     reply, because only an `input_required` one is held back (R12).
   - *A (default):* leave it. The spec says the reply is the AI messages' text (FR-008, D4). *Cost:*
     a graph written for the A2A sample's response format gets an empty reply on a `completed` turn.
   - *B:* send `message` as the reply when the turn is `completed`. *Cost:* the bridge decides that
     a field named `message` is the reply, which is a convention of one sample, and it must then not
     stream the JSON under `ProviderStrategy` either.
   - *Recommendation:* A now; B, if wanted, as an option the owner turns on in a later spec.
2. **Is a per-run callback handler "a hook" under FR-001?** FR-001 says the graph is not "given a
   hook". The handler is a plain LangChain callback passed in the `config` of each call, so the graph
   object, its nodes and its tools are never touched, and another caller of the same graph sees no
   difference. It is what makes D5 and the `nostream` clause of FR-008 possible.
   - *A (default):* read FR-001 as "the graph object is not edited"; use the handler.
   - *B:* no handler. D5's fallback applies (a tool shows `running` and `done` together, slow tools
     lose live progress), and a model hidden with `nostream` cannot be told from one that does not
     stream, so its finished text would be sent as reply, against FR-008.
   - *Recommendation:* A.
3. **The constitution's Technical Constraints line is stale after this spec.** It says
   `langchain>=1.3` + `langgraph`; R1 shows 1.3 to 1.4.5 fail at the first approval.
   - *A (default):* amend it in phase 1, PATCH 1.1.1 → 1.1.2, with a Sync Impact Report, in the same
     commit as `pyproject.toml`, as Governance requires.
   - *B:* leave the line and let `pyproject.toml` disagree with it. *Cost:* the constitution would
     say something the build contradicts.
   - *Recommendation:* A. The plan does not touch the constitution; phase 1's first task does it
     after the plan is approved.
4. **What happens when the caller declines the `input_required` question?**
   - *Example:* the agent ends a turn with `status="input_required"`, `message="Which region?"`; the
     caller's UI declines. The turn has already ended; there is nothing to resume.
   - *A (default):* the run ends `done` and the graph is not called.
   - *B:* send a human message such as "(no answer)" and run the graph again. *Cost:* tokens spent on
     nothing and a model that may ask again.
   - *Recommendation:* A.
5. **A `per_call` payload with no readable `response_schema`.**
   - *Example:* a future LangChain stops sending the schema. The bridge cannot know which decisions
     the call allows.
   - *A (default):* the run ends `failed` with a reason that says so, before any ask, and the graph
     is not touched (fail closed).
   - *B:* assume the default of all four and offer `allow`, `edit` (only with a known schema), `deny`.
     *Cost:* a decision the call does not allow would reach the graph; in `per_call` that is refused
     without harm, but the caller was promised it.
   - *Recommendation:* A. The pinned fact in phase 1 means this path is defensive only.

## Risks

| Risk | Mitigation |
|---|---|
| The payloads of `HumanInTheLoopMiddleware` and `Interrupt.response_schema` are LangChain's, not a public contract | read by shape; the bounds `<2`; `test_langgraph_spike.py` pins each shape on the newest set and the CI runs it; the oldest set was checked by hand (R1) |
| The callback handler's rules (`on_tool_start` only when the body runs; `GraphBubbleUp` on a pause) change | pinned in the spike; a failing test names the rule |
| A batch's resume is refused and the thread is stuck (finding 2) | the bridge validates first, in both modes, and a test per refusal checks that the same pause still resumes (SC-005) |
| The settle writes to the saved state (D9) | through `aupdate_state` with no `as_node`; pinned in both modes; the mutation check proves it is what makes the strict model work (SC-009) |
| One chunk of reply latency (hold-one) | named in the contract; SC-007's test uses at least three tokens before its gate |
| After a restart the hidden (`nostream`) set is gone, so a hidden message of an earlier leg counts when deciding if the turn had reply text | the effect is an empty closing chunk that may be the first of its artifact; harmless, rare, named in R5 |
| The producer's queue is unbounded, so a slow door buffers tokens in memory | the driver's own queue is unbounded too; named in the README; a bounded queue would stall the model call and is a later choice |
| A restart in the middle of a `batched` interrupt loses the decisions given (D8) | documented; the README says to use `per_call` where it matters; the batch is asked again from its first call (FR-019) |
| `edit` needs the tool's schema, found by looking into the tool node of a `create_agent` graph | if it is not found, `edit` is not offered (R9); a test with a hand-built graph checks the safe direction |
| A pydantic `structured_response` in the checkpoint triggers LangGraph's warning about unregistered types | the owner's setting (`allowed_msgpack_modules`); named in the README |
| A provider's error text reaches the caller as it is (spec, Assumptions) | the bridge does not bound or rewrite it; the README tells the owner to watch it |
| Two parallel hand-written requests with the same own id cannot be told apart | the first in order matches; the contract tells an author to keep them distinct |
| The sync `SqliteSaver` is wrapped by mistake | its own error reaches the caller as a failed run; the README says an async saver is needed |
| `langgraph-checkpoint-sqlite` and `aiosqlite` are new dev dependencies | vetted in T001 like PyYAML was; dev group only, never in the extra |

## Complexity Tracking

None.

## Notes

- Facts about the installed packages were checked on 2026-11-22 with throwaway scripts on the newest
  set (langchain 1.5.2, langgraph 1.2.24) and, for the features the bridge needs, on the lowest
  set the extra allows. Phase 1 turns every fact the design leans on into a test.
- Specs 002 to 004 call this bridge `005` and `Remote` `006`; the spec renumbered them 006 and 007.
  The older records keep their numbers; WORKSTATE.md has the current sequence.
- Phase 3's first cuts are a deliberate order of work, not a design change: the end state is the
  design of research R3, R5 and R8.
- 2026-11-22: `tasks.md` is written (104 tasks, 10 phases). Reading the code to write it changed the
  plan in three small ways, none in the design:
  - `_usage.py` has a first cut in phase 3, because the shared suite's shape needs a `usage` event
    from S1 on (the plan had it in phase 7 only);
  - no `UsageEvent` is sent when no message reported a token count: R2C-USAGE-1 requires at least
    one of `input_tokens`, `output_tokens`, `duration_ms`, `cost`, and a `model` alone does not count;
  - phase 4's size-limit test uses an oversized reply, because file blocks come in phase 7; the file
    variant is added there. `tools.py` is created in phase 5 with `schema_of` (an approval's `edit`
    needs it) and completed in phase 9.
- 2026-11-22, closing note (the body above is not rewritten): all ten phases are built and committed on
  `main`, none pushed. The design above held, with these changes, each recorded where it was decided:
  - the settle (D9) answers every call the last AI message left open, not only a middleware approval
    (R19, F1; a dated note on FR-007 in `spec.md`);
  - a second core change beside `PauseLost`: a pump-local `asked` flag in `core/source.py` (phase 3, a race
    found on Python 3.11);
  - tools refuse undeclared keys and are called through `arun` (R19, S1 and S2); a batched answer for a
    decided position ends `lost` (S4); a declined hand-written approval resumes as a `deny` (S6);
  - the handler hands events to the loop of the run when a sync node calls it from a worker thread (F2);
  - wrapping reads the state class when pydantic cannot describe the state (R19, found on 3.11).
  The five points of the plan were answered as recommended (`tasks.md`, "The five points"). What is left is
  SC-012 read by the maintainer (`tasks.md`, "Phase 10"), the push, and spec 007 (`Remote`).
