# Implementation Plan: MCP binding (`ext_r2c.mcp`)

**Branch**: `main` (folder `specs/004-mcp-binding`) | **Date**: 2026-11-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-mcp-binding/spec.md`

## Summary

Build `ext_r2c.mcp`, the MCP door, on the MCP Python SDK 2.3 behind `[mcp]`. It has these parts.

**Remote side**
- `R2CExtension` is an MCP SDK `Extension`. It declares the key, serves the door's tools and
  source tools by intercepting `tools/call`, and asks an approval before any tool named in
  `approve=`.
- `SourceTool` runs an `AgentSource` across the rounds of one tool call. It holds one `Run` per
  call, like the A2A door holds one per task, and resumes a checkpoint source from the stopping
  point after a restart.
- `mcp_server` builds an `MCPServer` with the extension, its `tools/list` middleware and the
  request-state policy.

**Caller side**
- `R2CClient` drives the rounds itself: it reads typed items, checks and sends answers, sends
  `requestState` back unchanged, and fetches only from the connection's origin.

**Tests and standard**
- Every MCP example is replayed in client mode and in door mode, for both pause styles.
- The standard records O4–O7, with five new examples and two corrected ones.

Research found these gaps in the MCP SDK 2.3:
- No JSON Schema can be given for a bound tool ([R1](research.md#r1-the-extension-and-what-it-may-contribute)).
- `edit` cannot reach a tool registered elsewhere ([R2](research.md#r2-approval-of-a-tool-call-approve)).
- **A sealed `requestState` can be replayed until it expires**, so a replay runs an approved
  tool again ([R3](research.md#r3-requeststate-what-the-door-seals-and-single-use)). The door
  claims each round once.
- Progress has no `_meta` API ([R8](research.md#r8-activity-as-progress)).
- The client answers input requests by itself, cannot declare form-only elicitation, and loses
  progress `_meta` in its callback ([R13](research.md#r13-the-callers-client)).
- `httpx2.ASGITransport` buffers a whole response ([R15](research.md#r15-in-process-transport-for-tests)).

## Technical Context

**Language/Version**: Python ≥ 3.11 (CI: 3.11, 3.12, 3.13)

**Primary Dependencies**:
- runtime core: `pydantic>=2` and `jsonschema>=4`, unchanged;
- extra: `[mcp]` = `mcp>=2.3,<3`, which brings `mcp-types`, `httpx2`, `anyio`, `starlette`,
  `sse-starlette`, `pyjwt[crypto]` and the rest (research R17);
- dev group: unchanged (`mcp>=2.3,<3` is already in it).

**Storage**:
- The door keeps runs, open contexts and claimed rounds in memory.
- Durable state is the stopping point inside the sealed `requestState`, and the source's own
  storage.
- Resuming after a restart needs fixed request-state keys.

**Testing**:
- pytest on the installed wheel. Async tests use `asyncio.run`, as in 002 and 003; the SDK runs
  on anyio's asyncio backend.
- Round trips use the MCP SDK client and `MCPServer` over streamable HTTP through
  `tests/mcp_transport.py` (streaming, recording; not shipped).
- Owners come from bearer tokens through the SDK's auth path with a stub verifier, or from the
  fallback middleware (R15).

**Target Platform**: CPython on any OS; CI on Linux

**Project Type**: library (the `mcp` subpackage of `ext-r2c`)

**Performance Goals**:
- The door adds no I/O beyond the SDK's own.
- A round costs one seal and one unseal, both done by the SDK.
- The MCP replay suite finishes in under 30 s in CI.

**Constraints**:
- the import rules (constitution VIII; AST test plus an MCP-only venv);
- no network port in tests;
- a public repository: invented data and `example.com`;
- the door never seals anything itself (R2C-MCP-5);
- R2C text is never parsed for instructions.

**Scale/Scope**:
- 9 modules in `mcp/`, about 25 public names ([contracts/mcp-api.md](contracts/mcp-api.md));
- MCP examples go from 9 to 14, with 2 corrected;
- about 10 new test files;
- one small change in `ext_r2c.a2a` (FR-014).

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | every R2C object on the wire is written and parsed by the core models; `usage` beside `input_requests` is a placement, not a new shape | pass |
| II. Wire examples are the shared test suite | every MCP example is replayed in client and door mode, with a one-file exemption list checked both ways; 5 new examples for O4–O7 | pass |
| III. Remote's logic unchanged | a `ToolSpec` and an `AgentSource` are served as they are; `approve=` wraps a tool without touching it, even one registered elsewhere on the server | pass |
| IV. An extension, never a protocol | only `capabilities.extensions`, `_meta[key]` and core elicitation; without activation, plain MCP with the same forms and messages | pass |
| V. Approval never answered by a model | the derived answer is always `person` (R2C-MCP-4); the client refuses `caller` on an approval and `policy` anywhere; a replayed round never runs a tool twice (R3) | pass |
| VI. Public, neutral data | new examples reuse the invented report data; leak scan per commit | pass |
| VII. Test first, against the built artifact | each phase starts with failing tests on the installed wheel; round trips through the real MCP SDK client and server, with only the network edge replaced | pass |
| VIII. Small core, bindings behind extras | `mcp` imports core and the `mcp` packages only; MCP-only venv step; no core change | pass |
| IX. Versioned by URI | v1 is draft; O4–O7 are additive prose on existing rules; `revision` stays 1 | pass |

Re-check after the Phase 1 design: still a pass. There is no core change, and no Complexity
Tracking entry.

## Project Structure

### Documentation (this feature)

```text
specs/004-mcp-binding/
├── spec.md
├── plan.md                      # this file
├── research.md                  # R1–R17
├── data-model.md                # stopping point, memory, retry outcomes, client items
├── quickstart.md                # validation guide
├── contracts/
│   ├── mcp-api.md               # public names and signatures
│   ├── wire-mapping.md          # run events and approvals ⇄ MCP, active and not
│   └── replay.md                # the example replay: modes, normalising, exemptions, new files
├── checklists/requirements.md
└── tasks.md                     # from /speckit-tasks
```

### Source code

```text
python/
├── pyproject.toml               # [mcp] = mcp>=2.3,<3
├── src/ext_r2c/
│   ├── a2a/task.py              # FR-014: the gathered reply text size-checked as a whole
│   └── mcp/
│       ├── __init__.py
│       ├── _codec.py
│       ├── _state.py
│       ├── activation.py
│       ├── tools.py
│       ├── source_tool.py
│       ├── extension.py
│       ├── server.py
│       └── client.py
└── tests/
    ├── mcp_transport.py         # streaming, recording ASGI transport for httpx2 (R15)
    ├── mcp_harness.py           # server/client factories, test auth, scripted source
    ├── mcp_replay_kit.py        # the replay's converter, wire server, normaliser
    ├── test_mcp_spike.py        # phase 1: the SDK facts the design leans on
    ├── test_mcp_codec.py
    ├── test_mcp_serve.py        # US1, both fakes of 002
    ├── test_mcp_approve.py      # US2
    ├── test_mcp_answers.py      # US3
    ├── test_mcp_activation.py   # US4
    ├── test_mcp_threads.py      # US5: owners, busy context, context_id
    ├── test_mcp_restart.py      # US5: rebuilt server on fixed keys
    ├── test_mcp_client.py       # US6
    ├── test_mcp_replay.py       # US7
    ├── test_packaging.py        # + mcp import rules
    └── mcp_only.py              # run by CI in a wheel[mcp] venv (not collected)

standard/v1/
├── README.md                    # R2C-MCP-1, -6, -7, -8 and R2C-ASK-5 prose (O4–O7)
└── examples/mcp/
    ├── elicitation-two-rounds.json      # new (O4, O6)
    ├── elicitation-reask.json           # new (O5)
    ├── elicitation-no-response.json     # new (O5)
    ├── tool-result-inline-image.json    # new (O7)
    ├── approval-tool-call.json          # new (approve=, deny)
    ├── elicitation-approval.json        # message corrected (O5)
    └── elicitation-approval-edit-dropped.json  # message corrected (O5)

.github/workflows/python.yml     # + MCP-only step
```

**Structure decision:** one subpackage, `ext_r2c/mcp/`, as fixed by `ARCHITECTURE.md`.
- Test helpers stay in `python/tests/` and are not shipped. `Remote` (007) reuses the transport
  and the harness.
- `mcp_only.py` is a script, like `a2a_only.py`.

## Key design decisions

The full reasoning is in [research.md](research.md).

1. **The door serves its own tools in the interceptor** (R1). Bindings only list them, and a
   middleware puts each `ToolSpec`'s schema in `tools/list`. `mcp_server` assembles it all.
2. **`approve=` covers any tool on the server** (R2). `edit` is offered only for the door's own
   tools.
3. **The stopping point travels in `requestState`, sealed by the SDK; each round is claimed
   once** (R3).
4. **One run per tool call, across rounds** (R4). The door delivers to a held run, or resumes a
   checkpoint source from the stopping point. A live run is lost after a restart, and gets
   `declined` when its state expires.
5. **Activation, the form capability and the owner are decided per round** (R5). With no form
   support, a request is `declined`.
6. **Output before an ask is carried to the final result** (R6). It is size-checked as a whole,
   on both doors.
7. **The message rule, refusals and re-asks** (R7, R10). There is one request per round, and the
   tool call is the unit (O4).
8. **Progress built by hand, with `_meta`** (R8).
9. **The client drives the rounds** through the session's raw `call_tool` (R13), and `fetch`
   follows the origin rule (R14).
10. **A streaming, recording transport and a two-mode replay** (R15, R16).

## Changes to the standard (FR-023)

- **R2C-MCP-1:**
  - A tool call has at most one pending request (R2C-ASK-3 per call). A server sends one
    `inputRequests` entry per round, and a client accepts several.
  - The elicitation `message` is the request's title (prefixed with `<origin.name> asks: ` when
    forwarded), its description, and one line per error on a re-ask.
  - The usage so far MAY ride beside `input_requests` as `_meta[key].usage`.
  - New examples: `elicitation-two-rounds.json`, `elicitation-reask.json`.
- **R2C-ASK-5, an MCP sentence:** the refusal is the first line of the next result's message or
  text. A retry without a response for the pending key is re-asked with that line. New example:
  `elicitation-no-response.json`.
- **R2C-MCP-6:** `progress` counts up from 1 per request, and no `total` is sent.
- **R2C-MCP-7:** an `inline` image or audio is an `image` or `audio` block. Other inline bytes
  are an embedded `resource`. New example: `tool-result-inline-image.json`.
- **R2C-MCP-8:** in an input-required result, the usage sits beside `input_requests`.
- **Approval of a direct tool call:** shown by `approval-tool-call.json`. This adds no new rule,
  since R2C-MCP-3 covers it.
- **Messages corrected** in `elicitation-approval.json` and `elicitation-approval-edit-dropped.json`.
- **Records:**
  - `CHANGELOG.md`: an Added entry for the door and a Changed entry for the rules.
  - `specs/001-standard-v1/research.md`: the O4–O7 notes say where the text went.
  - The rule count stays 84.

## Delivery order (input to `/speckit-tasks`; one phase per go)

| Phase | Content | Done when |
|---|---|---|
| 1. Packaging, test bed and spike | `[mcp]` pin; `mcp/` skeleton; import rules and `mcp_only.py` with its CI step; `mcp_transport.py`, test auth, server and client factories; `test_mcp_spike.py` pinning the SDK facts of R1, R3, R5, R8, R13 (tools/list rewrite, interceptor short-circuit, replayed state, principal per bearer, progress `_meta`, raw input-required) | tests on the wheel pass; `mcp only: ok`; progress arrives before the result in process; every spike fact holds, or the plan is updated first |
| 2. Codec (foundational) | `_codec.py`: input-required results, the message rule, progress notifications, content blocks both ways, `mcp_response`, reading results; `_state.py`: the stopping point and `MemoryLedger` | every R2C object in the MCP examples decodes and encodes back equal; `mcp_response` inverts `answer_from_mcp` on every example's derived answer |
| 3. Serve a source as a tool (US1 and US4, P1) | `activation.py`, `source_tool.py`, `extension.py`, `server.py`; question, approval, decline, two rounds, output before an ask, cancel; both fakes; with and without activation, without form support; `server/discover` | SC-002, SC-003, SC-006 |
| 4. Approve a direct tool call (US2, P1) | `tools.py`: ToolSpecs listed and served, `ToolOutput`, `Approve`, the interceptor's approval half; allow, edit, deny, decline; a tool registered elsewhere (allow and deny only); the claimed round | SC-004 |
| 5. Refuse and re-ask (US3, P1) | the retry outcome table: missing, expired (with a clock), re-ask with `errors`, too large, claimed; forged, other-tool, other-argument, other-principal and expired state; the gathered reply size check on both doors (FR-014) | SC-005 |
| 6. Threads and restart (US5, P1) | owner per round; the busy-context refusal; `context_id` chosen and returned; the server rebuilt on fixed keys (checkpoint resumes, live lost); a live run declined at expiry | SC-007, SC-008 |
| 7. Client (US6, P2) | `client.py`: connect, items, `call`, `answer`, `respond`, `cancel`, `fetch` with the origin rule and limits; refusals of `caller` and `policy` | the story 6 scenarios; SC-009 |
| 8. Replay and the standard (US7, P1) | `mcp_replay_kit.py`, `test_mcp_replay.py`; the README prose of O4–O7; 5 new examples, 2 corrected; the O4–O7 notes in spec 001's research | SC-001; every `wire` rule still has an example |
| 9. Docs and final gate | `ARCHITECTURE.md`, `python/README.md`, `WORKSTATE.md`, `CHANGELOG.md`, `docs/whitepaper.md` where names changed; 3.11 / 3.12 / 3.13; core-only, A2A-only and MCP-only steps; leak scan; outside review of the diff | SC-010 |

**Order:**
- Phases 1 and 2 come first: every later phase uses the transport, the codec and the facts the
  spike pins.
- Phases 3, 4 and 5 are serial. Each extends `extension.py`, and 4 and 5 share the retry
  outcome table.
- Phase 6 needs phase 3. Phase 7 needs phase 2 for its unit parts and phase 3 for round trips.
- Phase 8 needs all of them, and is last because it covers every example at once.

## Risks

| Risk | Mitigation |
|---|---|
| The spike shows that `tools/list` cannot be rewritten by middleware, or that the interceptor does not run before argument validation | the fallback in R1 (a generated function per tool, the full schema checked by the door); the plan is updated before phase 3 |
| The MCP SDK changes the pieces we lean on (interceptor ordering inside the boundary, `send_notification` with `related_request_id`, `session.call_tool(allow_input_required=True)`) in a 2.x release | `mcp>=2.3,<3`; the spike tests pin each fact and fail loudly |
| A replay of a round after a restart (in-memory ledger) | documented, with a durable `RoundLedger` as the fix; the default deployment (ephemeral keys) cannot replay across a restart at all |
| A live run held for a whole TTL keeps memory per paused call | the timer frees it at expiry; the TTL is the owner's setting |
| An agent tool that runs longer than the client's request timeout | out of scope (MCP Tasks); documented in the README |
| The client declares URL elicitation it does not ask for (SDK limit) | URL requests are yielded as plain items; documented |
| Anonymous callers share an owner and their contexts | documented; authentication is the deployment's |

## Complexity Tracking

None.
