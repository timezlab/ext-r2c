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
- **Spec `005-mcp-skills`, closed** (2026-11-22, `specs/005-mcp-skills/`, pushed):
  `ext_r2c.mcp.skills` (extra `[mcp]`, brings PyYAML): `SkillsExtension` and `SkillsClient`, a
  second MCP extension that is not R2C; `mcp_server(..., extensions=[...])`. Public names in
  `specs/005-mcp-skills/contracts/skills-api.md`; ADR
  `docs/design-docs/skills-frontmatter-and-nesting.md`:
  - the server scans folders for `SKILL.md` (include / exclude, 512 files and 16 MiB per skill, a
    bounded walk, what is left out reported) and serves `skills/list`, `skills/get`, every file as
    an ordinary resource and `resources/directory/read`; nothing outside the folder is served;
  - the client lists, gets and reads on demand, verifies each file's size, digest and frontmatter
    against the entry, and refuses what it cannot verify;
  - it works beside R2C, or alone, on any `MCPServer`;
  - its outside review is in `specs/005-mcp-skills/research.md` (R17), with what was left on
    purpose.
- **Wheel builds and tests pass** on Python 3.11, 3.12 and 3.13 (2034 tests, run against
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
- **Spec 005 is closed** (2026-11-22). The maintainer approved `spec.md` on 2026-11-21 (D1–D6 as
  written) and told us to implement on 2026-11-22 ("implement hết spec": all nine phases in one
  run); `plan.md`, research, data model, contracts, quickstart and `tasks.md` (80 tasks in 9
  phases, all done) are in `specs/005-mcp-skills/`. Where each phase differed from its plan is at
  the end of `tasks.md` ("Notes: where reality differed"); the outside review is R17 in
  `research.md`. **Pushed** on the maintainer's go (2026-11-22, `main` at `08b7cea`); after the close
  the generic names became `RefusedEntry`, `LeftOutPath` and `SkillDirectoryEntry`. The phases, as built:
  **Phase 1 (T001–T010) is done**: PyYAML `>=6.0.3,<7` in `[mcp]` and the dev group (T001
  re-vetted it, nothing found), the empty `ext_r2c/mcp/skills/` package, the fixture trees and
  ten SDK-fact tests. **Phase 2 (T011–T022, the foundation) is done** (2026-11-22): the
  frontmatter reader, URIs, MIME table, page cursor, immutable catalogue and wire models, with
  347 new unit tests (1257 in all) and a mutation run in which 108 of 108 real mutants died.
  **Phase 3 (T023–T031, serve skills from folders) is done** (2026-11-22): `SkillsExtension` scans
  folders and serves `skills/list`, `skills/get` and every file as an ordinary resource, a real SDK
  client reads every byte back (SC-001); 61 new tests (1318 in all), 67 of 73 real mutants died and
  the six that did not are equivalent (listed in the notes). **Phase 4 (T032–T041, the client
  verifies what it loads) is done** (2026-11-22): `SkillsClient` lists, gets and reads, refuses on
  size, digest, frontmatter, an unlisted URI or an undeclared extension, and reads with the SDK's
  cache bypassed; 136 new tests (1454 in all), 114 of 115 mutants died (the survivor is the
  control). **Phase 5 (T042–T048, nothing outside is served) is done** (2026-11-22): the read opens
  every name from `/` with `O_NOFOLLOW`, refuses anything that is not a regular file and never reads
  past the entry's size; the scan reports what it left out (`left_out`) and logs it; 131 new tests
  (1585 in all), 54 of 59 mutants died (the five are the control and four equivalents). **Phase 6
  (T049–T057, filters, build errors and refresh) is done** (2026-11-22): `include` / `exclude` are matched
  before a skill is read, every fault of the folders is a `SkillsError(folder, reason)` that quotes no file
  text and no host path, the 512-file and 16 MiB limits are refused at the first file past them, bad
  settings are a `ValueError`, and `refresh()` swaps a whole new catalogue in with one assignment; 118 new
  tests (1703 in all), 68 of 68 mutants died. **Phase 7 (T058–T063, beside R2C, or alone) is done**
  (2026-11-22): `mcp_server(name, r2c, extensions=[...])` serves other MCP extensions after R2C's, a
  skills-only `MCPServer` and a hand-built one with its own tools work too, R2C's wire on `tools/call`
  is the same with skills on the server; 15 new tests (1718 in all), 11 of 11 mutants died. **Phase 8
  (T064–T071, many skills and directories) is done** (2026-11-22): `skills/list` and directory reads
  page by an opaque cursor that is good for one listing of one catalogue, `resources/directory/read`
  answers from the catalogue (empty folders included) and is not bound when `directory_read=False`,
  `SkillsClient.list_directory` refuses a URI outside the skill before sending anything, and the client
  stops on a repeated cursor; 170 new tests (1888 in all), 46 of 46 mutants died. **Phase 9
  (T072–T080, docs, the outside review, the final gate) is done** (2026-11-22): a code reviewer and a
  security reviewer with no memory of the work read phases 1 to 8, and the findings acted on are
  fixed test-first: the scan is bounded (32 folders deep, 1024 folders in a skill, 1024 searched
  per root), a name with a control, separator, bidi control or backslash is left out as `unsafe
  name`, a failing disk is `FileUnreadable` and not "changed on disk", and the client refuses an
  entry no server could have served and no longer requires the `skill://` scheme; 146 new tests
  (2034 in all, green on 3.11, 3.12 and 3.13), 70 of 70 mutants of the fixes died.
- **Waiting for the maintainer** (nothing is blocked on these):
  - **Spec 006** (`006-langgraph-bridge`): the maintainer approved `spec.md` on 2026-11-22 (D1–D11 as
    written, D2 and D3 included). `plan.md`, `research.md` (R1–R18), `data-model.md`,
    `contracts/` (API, pause mapping, suite changes) and `quickstart.md` are written (2026-11-22). The
    maintainer took the recommendation (A) on the plan's five points the same day: a `completed`
    structured reply under `ToolStrategy` has no reply text; a per-run callback handler is not "a hook"
    under FR-001; the constitution goes PATCH 1.1.1 → 1.1.2 for the extra's bounds (task T009); a
    declined `input_required` question ends `done`; a `per_call` payload with no schema ends `failed`.
    **`tasks.md` is written** (2026-11-22): 104 tasks in 10 phases (US1 24, US2 11, US3 5, US4 14,
    US5 12, US6 6; 32 in the setup, foundation and closing phases). **The maintainer said "implement hết
    các phase" (2026-11-22): all ten phases run in one go, each committed on its own, none pushed.
    Phase 1 (T001–T012) is done** (2026-11-22): the vet moved the `langgraph` floor to 1.2.14, the extra
    is `langchain>=1.4.6,<2`, `langchain-core>=1.6.10,<2`, `langgraph>=1.2.14,<2` (constitution 1.1.2), the
    bridge skeleton imports with the extra and names it without it, and 31 library-fact tests pass on
    Python 3.11, 3.12 and 3.13 (2071 tests in all). Findings that shaped it: a `batched` resume with a wrong decision leaves
    the thread unable to continue (so the bridge validates first); the `tasks` stream cannot tell a
    running tool from a paused one (so a callback handler does); `nostream` hides tokens only.
    **Phase 2 (T013–T020) is done** (2026-11-22): `PauseLost` is in `ext_r2c.core` (a checkpoint source
    raises it in `resume`; the driver ends the run `lost`), and the shared suite compares a structural
    `shape` (no `activity`, consecutive replies merged) and checks that the last reply chunk is `last`;
    both fakes pass it as changed (2079 tests); 12 of 12 mutants of the suite died.
    **Phase 3 (T021–T036) is done** (2026-11-22): `LangGraphAgent(graph)` wraps a real graph, streams its
    reply (hold-one, `last` at the end of the turn, a paragraph break between messages, hidden `nostream`
    calls skipped), usage once per turn, and answers a hand-written pause; the graph passes S1–S10 of the
    shared suite; 17 of 17 mutants died (two test holes found and filled); 2164 tests on 3.11, 3.12 and
    3.13. **Python 3.11 found a race in the core** (the driver could end a run `done` when an answer came
    while the source was still ending); fixed in `core/source.py` with three tests (a second core change
    beside `PauseLost`, noted for the maintainer).
  - **Push** the local commits `a6929a7` (the rename of the three generic names of spec 005), `643f4d3`
    (spec 006), `3b26285` (its plan) and the tasks commit after it.
  - **Revisit, not scheduled:** a descriptor-based walk (`scandir(fd)`) of the skills folders, which
    closes a race that can show a folder's names (no file outside is served either way). Decided
    2026-11-22 to wait for `Remote(skills=...)` (spec 007); the reason is in `research.md` R17.

## Spec sequence (001–005 built; 006 under way, phase 3 of 10 done; 007 onward proposed)

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
5. **`005-mcp-skills`** (closed 2026-11-22) — MCP Skills (SEP-2640, `io.modelcontextprotocol/skills`)
   in `ext_r2c.mcp.skills`, read from folders with include / exclude, on the SDK's `Extension`. Split
   out of 004 on 2026-11-20 (maintainer, Q1 A): a separate MCP extension, not R2C. `Remote(skills=...)`
   is spec 007.
6. **`006-langgraph-bridge`** (spec approved, plan and 104 tasks written 2026-11-22; implementing, phases 1–3 done) —
   `ext_r2c.bridges.langgraph` (`LangGraphAgent`, LangChain tools → `ToolSpec`), passing the shared
   bridge conformance suite: graph → run events; `HumanInTheLoopMiddleware` in `batched` and
   `per_call` modes, hand-written `interrupt()`, the `status = "input_required"` turn end, reply
   tokens, tool activity, reasoning (opt-in), usage, file content blocks → artifacts. Checked
   against langchain 1.5.2 / langgraph 1.2.24 (the findings are in the spec's Context) and the lowest
   set the extra allows (`langchain>=1.4.6`, the first with the `per_call` mode; `langgraph>=1.2.14`
   after the advisory vet). One additive core
   piece (`PauseLost`), one core race fix (found in phase 3) and a structural change to the shared suite;
   ten delivery phases in the plan.
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
