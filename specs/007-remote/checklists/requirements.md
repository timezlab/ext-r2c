# Specification Quality Checklist: `Remote`, one adapter for A2A, MCP or both (`ext_r2c.Remote`)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-23
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs) — the spec names the two protocol SDKs'
      behaviour and this package's own public names (`Remote`, `SourceTool`, `SkillsExtension`) because
      `Remote` is a composition of them and the feature description asks for what the installed SDKs
      do now; those facts sit in one dated Context section (nine findings, each saying what the spec
      does with it), and the requirements say what an owner and a caller see. How the app is composed
      is left to the plan (D11 is stated as a default the plan may replace if it meets FR-021 to
      FR-024)
- [X] Focused on user value and business needs
- [X] Written for the readers named in the stories (the owner of a remote; the people who write the
      plan); the same register as specs 003 to 006
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain — the open choices are written as defaults D1–D13 in
      "Decisions taken in this draft"; D3 (drop `mcp_server=`, which changes the ADR) and D5 (identity
      and the MCP-owner warning, a safety choice) are the two the maintainer is asked about first
- [X] Requirements are testable and unambiguous (each FR maps to a story scenario or a success
      criterion; the error cases are one table, FR-032)
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic — they name the protocols, the Python versions the
      project supports, the brief's criteria and the extras, and no library API
- [X] All acceptance scenarios are defined
- [X] Edge cases are identified
- [X] Scope is clearly bounded (Out of scope in Assumptions)
- [X] Dependencies and assumptions identified (specs 002–006 as built, the installed `a2a-sdk` 1.3.1,
      `mcp` 2.3.0 and `starlette` 1.10.0, the scripted model, a durable store the owner brings)

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria (FR → story scenarios and SC:
      FR-001–006 → US2, SC-005, SC-010; FR-007–010 → US1, US6, SC-001–SC-003; FR-011–015 → US2, US3,
      SC-004, SC-005; FR-016–019 → US5, SC-008, SC-012; FR-020–027 → US1, US4, US7, SC-006–SC-009;
      FR-028–030 → US1, US7, SC-003; FR-031–034 → US2, SC-005; FR-035–038 → SC-010, SC-011)
- [X] User scenarios cover primary flows (both doors, build-time errors, approvals, restart, MCP
      extras, a hand-written executor, one door and the deployment settings)
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

- Iteration 1 of 3: all items pass. Self-review after the first draft made four changes: the
  argument-to-door table (FR-019) replaced a sentence that pointed at the error table; the error table
  gained the `url` / `a2a` and `mcp` rows and the case of no card information on either door (an MCP
  server needs a name too); D11 now says the MCP app's OAuth routes must reach it; the in-memory
  warning (D13, FR-027) was added because stories 4 and SC-006 said "says so once" with no
  requirement behind it.
- Open for the plan, not for the spec: the exact types of the contract (`A2AOptions`, `MCPOptions`,
  `RemoteError`); how an `AgentSource` is told from an executor without importing the SDK; the
  dispatcher (D11) and the path set it routes to the MCP app; the order the two lifespans start and
  stop in, and what a failed start leaves behind; how the in-process test bed serves one app to an A2A
  client and an MCP client at once; whether any door needs an additive change (none is expected);
  the file layout under `remote/`; whether `ext_r2c/__init__.py` loads `Remote` lazily.
- Verified before this spec (2026-11-23, in the project's test environment, nothing committed): the
  MCP SDK applies extensions only in its constructor; its streamable-HTTP app's lifespan is the
  session manager, started once per manager; its host guard answers `421`; Starlette's `Mount` does
  not run a sub-app's lifespan and answers `/mcp` with `404` when mounted at `/mcp`; lifting both
  apps' routes and entering both lifespans works; the A2A door reads `request.user`, the MCP door the
  SDK's access token, and `R2CExtension(owner=...)` receives the HTTP request.
- Gate: the maintainer approves this spec before `plan.md` is written.
