# Work state

Last updated 2026-11-22. Read this first in a new session.

## Done

- **Design approved** (2026-11-20): `docs/research/2026-11-20-r2c-v1-design-brief.md`, with
  ADRs in `docs/design-docs/`. Every question about the extension itself is settled.
- **Amended the same day:** six kinds (`activity`, `usage` added; reasoning only when the
  remote's owner turns it on), and the reply is one streamed `inline` artifact holding all
  the model's text. ADR `activity-and-usage-kinds.md`; amendment note at the top of the brief.
- **Repository skeleton:** license, README, CHANGELOG, Python package `ext-r2c` 0.0.1 exposing
  `URI`, `MCP_KEY`, `STANDARD_VERSION`, `__version__`.
- **Spec `001-standard-v1`, closed** (2026-11-20, `specs/001-standard-v1/`):
  - `standard/v1/README.md`: the normative text, 84 tagged rules (draft);
  - `standard/v1/schema/`: six JSON Schemas; `standard/v1/examples/`: 37 wire examples
    (29 A2A, 8 MCP) and 20 invalid objects;
  - the tests check every object against its schema, every envelope against the real a2a-sdk
    and MCP 2026-07-28 types, and that every `wire` rule has an example;
  - the wheel ships the schemas as `ext_r2c/schema/v1/` (build hook `python/hatch_build.py`);
  - deviations from the brief (D1–D4) are in `specs/001-standard-v1/research.md`.
- **Spec `002-python-core`, closed** (2026-11-20, `specs/002-python-core/`): `ext_r2c.core`,
  needing only pydantic and jsonschema. Public names in `contracts/core-api.md`:
  - models of the six kinds that round-trip every example object unchanged;
  - forms: `answer_schema`, `mcp_form` (flat `requestedSchema`), `answer_from_mcp`;
  - `check_answer` (readable problems with codes, size limits, no external `$ref`),
    `decision` (fails closed), `fallback_text`;
  - run events, `AgentSource` and one `Driver` for checkpoint and live sources, `thread_id`;
    the `AgentSource` suite (`python/tests/agent_source_suite.py`) passes for a fake of each
    style;
  - `ToolSpec` from a plain function;
  - extras: `[langchain]` → `[langgraph]`, no longer pulling `[a2a]`;
  - the standard records O2 and O3 (R2C-QUESTION-5 required means not empty; R2C-MCP-2,
    R2C-MCP-3 spell out the flat forms), with two new examples (39 valid in all: 30 A2A, 9 MCP).
- **Spec `003-a2a-binding`, closed** (2026-11-20, `specs/003-a2a-binding/`): `ext_r2c.a2a`
  behind the `[a2a]` extra, on a2a-sdk 1.3. Public names in `contracts/a2a-api.md`:
  - `a2a_app` and `SourceExecutor` serve an `AgentSource`; `agent_card` declares the
    extension; activation per request and the echoed header;
  - answers checked, re-asked with `errors`, or refused (wrong `id`, expired); text answers
    without activation;
  - threads per owner and context; one unfinished task per context (a second is rejected);
    paused tasks resumed after a restart through the task store;
  - `R2CTask` and `PendingMemory` for an executor written by hand; `R2CRequestHandler`
    (client messages with the user's role only; no stored R2C content without activation);
  - `R2CClient` for the caller: typed items, answers checked before sending, `reattach`,
    `get_task`, `cancel`, same-origin `fetch`;
  - every A2A example replayed as a real in-process round trip, against the client and
    against the door (`tests/a2a_replay_kit.py`);
  - the standard records O8, O9 and O10 (R2C-ANSWER-6, R2C-ID-2, R2C-ACTIVITY-2, R2C-A2A-4,
    the §11 card note), with two new examples (41 valid in all: 32 A2A, 9 MCP).
- **Spec `004-mcp-binding`, closed** (2026-11-20, `specs/004-mcp-binding/`): `ext_r2c.mcp`
  behind the `[mcp]` extra, on the MCP Python SDK for protocol 2026-07-28. Public names in
  `contracts/mcp-api.md`:
  - `R2CExtension` (an MCP SDK `Extension`) and `mcp_server`; `SourceTool` serves an
    `AgentSource` as one tool across multi-round-trip calls; `ToolSpec`s served as tools;
  - questions and approvals as elicitation forms, one per round, the message rule; answers
    checked, re-asked with `errors`, or refused (wrong key, no response, expired);
  - `approve=`: an approval before a direct tool call, `edit` on flat arguments; the tool runs
    once, and never after a deny, a decline or expiry;
  - activities as `notifications/progress`; usage and artifacts on the result, usage beside
    `input_requests` while waiting;
  - `requestState` sealed by the SDK, each round used once (`RoundLedger`); one call per
    owner and context; a checkpoint source resumed after a restart with fixed keys;
  - `R2CClient` for the caller: typed items, answers checked and turned into elicitation
    responses, several requests gathered, `respond`, `cancel`, same-origin `fetch`;
  - every MCP example replayed as a real in-process round trip, against the client and
    against the door (`tests/mcp_replay_kit.py`);
  - the standard records O3 (MCP side), O4, O5, O6 and O7 (R2C-ASK-5, R2C-MCP-1, -6, -7, -8),
    with five new examples and five corrected (46 valid in all: 32 A2A, 14 MCP).
- **Wheel builds and tests pass** on Python 3.11, 3.12 and 3.13 (898 tests, run against
  the installed wheel; the core alone runs `tests/core_only.py`, the wheel with `[a2a]` alone
  runs `tests/a2a_only.py` and the wheel with `[mcp]` alone runs `tests/mcp_only.py`, all with
  no dev group). CI in `.github/workflows/python.yml` does
  the same.
- **Harness:** Spec Kit 0.13.4 initialised (`specs/` at the root), constitution 1.0.0, rules,
  skills, reviewer agents.

## Not done on purpose

- The PyPI name `ext-r2c` is **not reserved** (maintainer, 2026-11-20). If it is taken by the
  time we publish, rename the distribution; the import name and identifiers stay.
- MCP Tasks (long tool calls) are not supported: an agent tool that runs longer than the
  client's request timeout fails on the client's side.

## Next

- **Spec 001 is closed** (2026-11-20). An outside reviewer got every kind's fields and placement
  right from the README alone (SC-005). Its open points O1–O11 are in
  `specs/001-standard-v1/research.md` ("Outside review"), each with an owner spec. O1 is
  decided (2026-11-20): a new value in a closed enum is breaking and needs v2
  (`R2C-VERSION-3`). O11 is decided the same day: size limits are in MiB (constitution 1.1.1).
- **Spec 002 is closed** (2026-11-20). It settled O2 and O3 (maintainer answers Q1–Q3, all A).
  Its outside review is in `specs/002-python-core/research.md` ("Outside review").
- **Spec 003 is closed** (2026-11-20). It settled O8, O9 and O10. Where it differed from its
  plan is at the end of `specs/003-a2a-binding/tasks.md`; its outside review is in
  `specs/003-a2a-binding/research.md` ("Outside review").
- **Spec 004 is closed** (2026-11-20). It settled O3 (MCP side), O4, O5, O6 and O7 (Q1 A:
  Skills split out to 005; Q2 A: usage beside `input_requests` while waiting). Where it
  differed from its plan is at the end of `specs/004-mcp-binding/tasks.md`; its outside review
  is in `specs/004-mcp-binding/research.md` ("Outside review").
- **In progress: `005-mcp-skills`.** The maintainer approved `spec.md` on 2026-11-21 (D1–D6 as
  written) and told us to implement on 2026-11-22; `plan.md`, research, data model, contracts,
  quickstart and `tasks.md` (80 tasks in 9 phases) are in `specs/005-mcp-skills/`.
  **Phase 1 (T001–T010) is done**: PyYAML `>=6.0.3,<7` in `[mcp]` and the dev group (T001
  re-vetted it, nothing found), the empty `ext_r2c/mcp/skills/` package, the fixture trees and
  ten SDK-fact tests. **Phase 2 (T011–T022, the foundation) is done** (2026-11-22): the
  frontmatter reader, URIs, MIME table, page cursor, immutable catalogue and wire models, with
  347 new unit tests (1257 in all) and a mutation run in which 108 of 108 real mutants died.
  **Phase 3 (T023–T031, serve skills from folders) is done** (2026-11-22): `SkillsExtension` scans
  folders and serves `skills/list`, `skills/get` and every file as an ordinary resource, a real SDK
  client reads every byte back (SC-001); 61 new tests (1318 in all), 67 of 73 real mutants died and
  the six that did not are equivalent (listed in the notes). The maintainer then asked for the whole spec in one run ("implement hết spec"), so phases 3–9 follow
  without a stop between them; where each phase differed from its plan is kept in "Notes: where
  reality differed" at the end of `specs/005-mcp-skills/tasks.md`. Nothing is pushed.

## Spec sequence (001–004 built; 005 onward proposed, awaiting approval)

Each is one Spec Kit feature (`/speckit-specify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-implement`, one phase per go).

1. **`001-standard-v1`** (closed 2026-11-20) — normative text in `standard/v1/README.md`; JSON Schemas for
   `question`, `approval`, `answer`, `artifact-meta`, `activity`, `usage`; wire examples (A2A
   and MCP) covering every rule, including a full streamed run (reply chunks, tool activities,
   a file artifact, usage); CI step validating every example; schemas shipped inside the wheel.
   Done when every example validates, the wheel carries byte-identical schemas, and a test
   fails if one example breaks its schema.
2. **`002-python-core`** (closed 2026-11-20) — `ext_r2c.core`: pydantic models for the six kinds, form → JSON
   Schema and → flat `requestedSchema`, validation with size limits and no external `$ref`,
   text fallback, the neutral run events (reply chunk, activity, ask, answer, artifact, usage,
   done, error), and the extension points `AgentSource` (checkpoint and live pause) and
   `ToolSpec`. Extras reshaped (`[langchain]` → `[langgraph]`, no longer pulling `[a2a]`).
   Done when every example round-trips through the models unchanged, `import ext_r2c` works
   with no extra, and a fake checkpoint-style and a fake live-style source both pass the
   `AgentSource` contract tests.
3. **`003-a2a-binding`** (closed 2026-11-20) — `ext_r2c.a2a`: run events ⇄ A2A wire over a2a-sdk 1.3, and the
   caller-side client; real round trips in process; streamed `response` artifact, `activity`,
   `usage`, re-ask with `errors`, expiry, wrong `id`, artifact presentation, one unfinished
   task per context, `thread_id = f(door, owner, contextId)`; a hand-written `AgentExecutor`.
4. **`004-mcp-binding`** (closed 2026-11-20) — `ext_r2c.mcp`: an MCP SDK `Extension`;
   elicitation from forms and approvals (tool approval through MRTR), answer mapping,
   `activity` through `notifications/progress`, `usage` and artifacts on tool results,
   `RequestStateBoundary`, the caller-side client. Success criterion 6. Settles O4–O7.
5. **`005-mcp-skills`** — MCP Skills (SEP-2640, `io.modelcontextprotocol/skills`) in
   `ext_r2c.mcp`, read from folders with include / exclude, on the SDK's `Extension`. Split out
   of 004 on 2026-11-20 (maintainer, Q1 A): a separate MCP extension, not R2C.
6. **`006-langgraph-bridge`** — `ext_r2c.bridges.langgraph` (`LangGraphAgent`, LangChain
   tools → `ToolSpec`), passing the shared bridge conformance suite: graph → run events;
   `HumanInTheLoopMiddleware` in `batched` and `per_call` modes, hand-written `interrupt()`,
   the `status = "input_required"` turn end, reply tokens, tool activity, reasoning (opt-in),
   usage, file content blocks → artifacts.
7. **`007-remote`** — `Remote`, the only remote-side adapter, configured declaratively:
   `expose` = A2A, MCP or both; one ASGI app; `agent=` (an `AgentSource` or an a2a-sdk
   executor), `tools=`, `approve=`, `skills=` (folders, include / exclude), `resources=`,
   `prompts=`, `mcp_server=`; `mcp_tool=True`; build-time errors for a door with nothing to
   serve, something no door serves, or a missing extra. Success criteria 1–5 of the brief,
   served by `Remote`, plus one agent through both doors in one process.
8. Later: `examples/langgraph_agent/`, bridges for other agent frameworks (Google ADK, OpenAI
   Agents SDK, Claude Agent SDK; the last one is a live-pause source), MCP Tasks for long agent
   runs over MCP, publishing to PyPI, a TypeScript SDK.

**Decided 2026-11-20:** `Remote` is the only remote-side adapter and exposes A2A, MCP or both
by a setting; agent, tools and skills are passed in (no decorators); MCP approvals are
`approve=` on `Remote`, separate from the agent framework's own approval config; skills are
read from folders with include / exclude; card skills and MCP skills stay separate; the agent
is an MCP tool only with `mcp_tool=True`; one thread per door; LangGraph is the first bridge
behind `AgentSource`, and `Remote` imports no bridge; `activity` keeps `type: step`. ADR
`one-remote-two-doors.md`; constitution 1.1.0 (principle VIII import list).

## Open, outside this repo

How a particular caller routes `answer_by: caller` to its agent, its "Always allow" scope,
and live-view embedding belong to that caller's own project. The brief's §8 records only the
shapes R2C was designed against. The first caller's own spec still says "no `plan` / `step`
kind"; it must follow the `activity` / `usage` amendment, and check that a remote's SSE
reaches it while the remote runs (not buffered by a proxy).

## Working rules worth repeating

- Public repo: scan every commit's added lines for private tokens before committing (the
  pattern lives in the maintainer's local notes, not in the repo).
- Build the wheel and run the full test suite on it before saying anything is done.
