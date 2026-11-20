# Work state

Last updated 2026-11-20. Read this first in a new session.

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
- **Wheel builds and tests pass** on Python 3.11, 3.12 and 3.13 (122 tests, run against the
  installed wheel). CI in `.github/workflows/python.yml` does the same.
- **Harness:** Spec Kit 0.13.4 initialised (`specs/` at the root), constitution 1.0.0, rules,
  skills, reviewer agents.

## Not done on purpose

- The PyPI name `ext-r2c` is **not reserved** (maintainer, 2026-11-20). If it is taken by the
  time we publish, rename the distribution; the import name and identifiers stay.
- The Python SDK does nothing yet beyond its constants and the packaged schemas: that starts
  with spec 002.

## Next

- **Spec 001 is closed** (2026-11-20). An outside reviewer got every kind's fields and placement
  right from the README alone (SC-005). Its open points O1–O11 are in
  `specs/001-standard-v1/research.md` ("Outside review"), each with an owner spec. O1 is
  decided (2026-11-20): a new value in a closed enum is breaking and needs v2
  (`R2C-VERSION-3`). O11 is decided the same day: size limits are in MiB (constitution 1.1.1).
- **Next:** spec `002-python-core`, from `/speckit-specify`; it owns O2 and O3.

## Spec sequence (001 approved and built; 002 onward proposed, awaiting the maintainer's approval)

Each is one Spec Kit feature (`/speckit-specify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-implement`, one phase per go).

1. **`001-standard-v1`** (closed 2026-11-20) — normative text in `standard/v1/README.md`; JSON Schemas for
   `question`, `approval`, `answer`, `artifact-meta`, `activity`, `usage`; wire examples (A2A
   and MCP) covering every rule, including a full streamed run (reply chunks, tool activities,
   a file artifact, usage); CI step validating every example; schemas shipped inside the wheel.
   Done when every example validates, the wheel carries byte-identical schemas, and a test
   fails if one example breaks its schema.
2. **`002-python-core`** — `ext_r2c.core`: pydantic models for the six kinds, form → JSON
   Schema and → flat `requestedSchema`, validation with size limits and no external `$ref`,
   text fallback, the neutral run events (reply chunk, activity, ask, answer, artifact, usage,
   done, error), and the extension points `AgentSource` (checkpoint and live pause) and
   `ToolSpec`. Extras reshaped (`[langchain]` → `[langgraph]`, no longer pulling `[a2a]`).
   Done when every example round-trips through the models unchanged, `import ext_r2c` works
   with no extra, and a fake checkpoint-style and a fake live-style source both pass the
   `AgentSource` contract tests.
3. **`003-a2a-binding`** — `ext_r2c.a2a`: run events ⇄ A2A wire over a2a-sdk 1.3, and the
   caller-side client; real round trips in process; streamed `response` artifact, `activity`,
   `usage`, re-ask with `errors`, expiry, wrong `id`, artifact presentation, one unfinished
   task per context, `thread_id = f(door, owner, contextId)`; a hand-written `AgentExecutor`.
4. **`004-mcp-binding`** — `ext_r2c.mcp`: an MCP SDK `Extension`; elicitation from forms and
   approvals (tool approval through MRTR), answer mapping, `activity` through
   `notifications/progress`, `usage` and artifacts on tool results, `RequestStateBoundary`,
   MCP Skills (SEP-2640), the caller-side client. Success criterion 6.
5. **`005-langgraph-bridge`** — `ext_r2c.bridges.langgraph` (`LangGraphAgent`, LangChain
   tools → `ToolSpec`), passing the shared bridge conformance suite: graph → run events;
   `HumanInTheLoopMiddleware` in `batched` and `per_call` modes, hand-written `interrupt()`,
   the `status = "input_required"` turn end, reply tokens, tool activity, reasoning (opt-in),
   usage, file content blocks → artifacts.
6. **`006-remote`** — `Remote`, the only remote-side adapter, configured declaratively:
   `expose` = A2A, MCP or both; one ASGI app; `agent=` (an `AgentSource` or an a2a-sdk
   executor), `tools=`, `approve=`, `skills=` (folders, include / exclude), `resources=`,
   `prompts=`, `mcp_server=`; `mcp_tool=True`; build-time errors for a door with nothing to
   serve, something no door serves, or a missing extra. Success criteria 1–5 of the brief,
   served by `Remote`, plus one agent through both doors in one process.
7. Later: `examples/langgraph_agent/`, bridges for other agent frameworks (Google ADK, OpenAI
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
