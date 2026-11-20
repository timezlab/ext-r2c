# Implementation Plan: Python core (`ext_r2c.core`)

**Branch**: `main` (folder `specs/002-python-core`) | **Date**: 2026-11-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-python-core/spec.md`

## Summary

Build `ext_r2c.core`, the protocol-free part of the SDK that every door and bridge uses. It has:
- open pydantic models for the six kinds, judged by the packaged schemas, that round-trip every
  example object unchanged;
- generators for the answer schema and the flat MCP forms, plus the mapping of a flat response
  back to an answer;
- `check_answer`, which returns re-askable problems, with size limits and no external `$ref`;
- deterministic fallback text;
- neutral run events, `AgentSource` with one `Driver` that hides the pause style, and
  `thread_id`;
- `ToolSpec` from plain functions.

The extras become `[a2a]`, `[mcp]`, `[langgraph]`. The standard follows the O2/O3 decisions in
README §5 and §12, with two new examples and one corrected example. Research found one trap: the
`date-time` format check is silently skipped without an optional package
([R3](research.md#r3-date-time-needs-a-checker-of-our-own)). The core therefore brings its own
checker, and a core-only CI step proves it.

## Technical Context

**Language/Version**: Python ≥ 3.11 (CI: 3.11, 3.12, 3.13)

**Primary Dependencies**:
- runtime: `pydantic>=2`, `jsonschema>=4` (unchanged);
- dev group: unchanged (`pytest>=8`, `a2a-sdk`, `mcp`, `jsonschema[format-nongpl]`);
- extras: `[a2a]`, `[mcp]`, `[langgraph]` (`langchain>=1.3`, `langgraph`).

**Storage**: none. The core keeps no durable state; live runs are held in memory by the driver.

**Testing**: pytest on the installed wheel in a clean venv. A second venv holds the wheel alone
for the core-only check. Async code is tested with `asyncio.run` (R14).

**Target Platform**: CPython on any OS; CI on Linux

**Project Type**: library (the core subpackage of `ext-r2c`)

**Performance Goals**:
- loading the six schemas once per process;
- `check_answer` and the form generators well under 1 ms for a form of 20 fields (no I/O);
- the full suite under a minute in CI.

**Constraints**:
- imports only the standard library, `pydantic`, `jsonschema` (constitution VIII);
- no network or file access outside the package (R4);
- public repository: invented data, `example.com`.

**Scale/Scope**:
- 8 modules in `core/`, about 30 public names ([contracts/core-api.md](contracts/core-api.md));
- 37 → 39 valid examples, 20 invalid;
- about 8 new test files.

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | models are judged by the packaged schemas (R2); the README's QUESTION-5 / MCP-2 / MCP-3 text and examples change in the same commit as the generators | pass |
| II. Wire examples are the shared test suite | every example object round-trips; every MCP form is regenerated and compared; pairing uses `check_answer`; two new examples cover Q1 and Q2 | pass |
| III. Remote's logic unchanged | `AgentSource` and `ToolSpec` wrap existing agents and plain functions; nothing asks a remote to restructure | pass |
| IV. An extension, never a protocol | the core has no protocol types; unknown kinds and fields are kept or skipped, never errors | pass |
| V. Approval never answered by a model | `check_answer` reports `caller_on_approval`; `decision` gives `deny` for declined or expired | pass |
| VI. Public, neutral data | new examples use the existing invented report/warehouse data; leak scan before each commit | pass |
| VII. Test first, against the built artifact | each phase starts with failing tests on the installed wheel; the core-only check runs on a wheel-only venv | pass |
| VIII. Small core, bindings behind extras | AST import-rule test and core-only CI step; `[langgraph]` no longer pulls `[a2a]` | pass |
| IX. Versioned by URI | v1 is draft; the Q2 change of the QUESTION-5 table is allowed (R2C-VERSION-2) and noted in CHANGELOG | pass |

Re-check after Phase 1 design: still pass. The driver stays in `core` (no door type), and no new
runtime dependency was needed. No Complexity Tracking entry.

## Project Structure

### Documentation (this feature)

```text
specs/002-python-core/
├── spec.md
├── plan.md                      # this file
├── research.md                  # R1–R16
├── data-model.md                # models, core types, driver states
├── quickstart.md                # validation guide
├── contracts/
│   ├── core-api.md              # public names and signatures
│   ├── forms.md                 # answer schema, flat forms, response mapping, fallback text
│   └── agent-source-suite.md    # the AgentSource contract suite and its fakes
├── checklists/requirements.md
└── tasks.md                     # from /speckit-tasks
```

### Source code

```text
python/
├── pyproject.toml               # extras: a2a, mcp, langgraph
├── src/ext_r2c/
│   ├── __init__.py              # unchanged surface
│   └── core/
│       ├── __init__.py
│       ├── _schemas.py
│       ├── models.py
│       ├── forms.py
│       ├── check.py
│       ├── fallback.py
│       ├── events.py
│       ├── source.py
│       └── tools.py
└── tests/
    ├── r2c_check.py             # form_schema removed; uses ext_r2c.core (FR-032)
    ├── test_examples.py         # pairing through check_answer
    ├── conftest.py              # summary line adds the round-trip count
    ├── test_models.py
    ├── test_forms.py
    ├── test_check.py
    ├── test_fallback.py
    ├── test_agent_source.py
    ├── agent_source_suite.py
    ├── fake_sources.py
    ├── test_tools.py
    ├── test_packaging.py        # import rules (AST + subprocess), extras metadata
    └── core_only.py             # run by CI in a wheel-only venv (not collected by pytest)

standard/v1/
├── README.md                    # §5 QUESTION-5 table (Q2), §12 MCP-2 / MCP-3 (O2, O3, Q1)
└── examples/
    ├── mcp/elicitation-question-other.json         # add the missing `description`
    ├── mcp/elicitation-question-many-other.json    # new: many + options + <key>_other
    └── a2a/reask-empty-required.json               # new: "" for a required text, re-asked

.github/workflows/python.yml     # + core-only step
```

**Structure Decision:** one subpackage `ext_r2c/core/` as fixed by `ARCHITECTURE.md` and the ADR.
- Test helpers stay in `python/tests/` and are not shipped. The `AgentSource` suite is
  importable from there so that the bridges in this repository reuse it.
- `core_only.py` is a script, not a test module. Its name has no `test_` prefix, so pytest does
  not collect it.

## Key design decisions

The full reasoning is in [research.md](research.md).

1. **Schema first, then model** (R1, R2). Parse = schema check + QUESTION-4 + model;
   `to_json` validates what it writes. Defaults are read, never written; `kind` is always
   written.
2. **Own `date-time` checker** (R3). It means the same thing with or without the optional
   package.
3. **`$ref` scan before use** (R4). An external `$ref` means `edit` is not offered and the
   schema is never validated against; a local `$ref` is fine.
4. **Problems with codes** (R6). The door decides re-ask or refuse from `code`; `as_error_item`
   feeds `errors`.
5. **Forms reproduce the examples exactly** (R7). There is one fix: the `-other` example gets its
   `description`.
6. **One driver for both pause styles** (R10). It uses one queue and one future, and the driver
   emits `AnswerEvent` and the terminal event. Restart goes through `Driver.resume` with the
   request the door kept.
7. **Hashed, door-prefixed thread id** (R11).
8. **`ToolSpec` via pydantic `create_model`** (R12). A sync function runs in a thread.

## Changes to the standard (FR-031)

- **§5, R2C-QUESTION-5 table:** `text` and `many` with `required: true` gain `minLength: 1` and
  `minItems: 1`. The sentence after the table says that `required` means present and not empty.
- **§12, R2C-MCP-2:**
  - each property's `title` is `header` and its `description` is `text`;
  - the title and description of `<key>_other`;
  - a field with `other: true` is never in `required`;
  - `<key>_other` counts only when it is not empty after stripping;
  - for `one` it replaces the value, for `many` it is added once (Q1).
- **§12, R2C-MCP-3:**
  - what "flat" means, with `integer` and string enums allowed;
  - an argument named `decision` or `reason` makes the schema not flat;
  - arguments are never required, and the enum becomes a titled `oneOf`;
  - rebuilding `args` (left-out arguments keep their value; ignored unless `edit`);
  - an approval left with no decision cannot be asked over MCP.
- **Examples:**
  - `mcp/elicitation-question-many-other.json` is new (rules R2C-MCP-2, R2C-MCP-4);
  - `a2a/reask-empty-required.json` is new (R2C-QUESTION-5, R2C-ASK-6);
  - `mcp/elicitation-question-other.json` gets its `description`.
- **Records:** `CHANGELOG.md` gets a Changed entry for the QUESTION-5 table. In
  `specs/001-standard-v1/research.md`, O2 and O3 get a dated "decided in 002" note.

## Delivery order (input to `/speckit-tasks`; one phase per go)

| Phase | Content | Done when |
|---|---|---|
| 1. Packaging | extras; `core/` skeleton; import-rule and extras tests; `core_only.py`; CI step | tests on the wheel pass; the core-only venv prints `core only: ok` |
| 2. Models (US1, P1) | `_schemas.py`, `models.py`; round-trip and invalid tests; summary count | SC-001, SC-002 |
| 3. Forms (US3, P1) | `forms.py`; README §5/§12; the three example changes | SC-003; every `wire` rule still has an example |
| 4. Answer check and fallback (US2, P1) | `check.py`, `fallback.py`; `r2c_check.form_schema` and `_answer_problems` replaced by the core (FR-032) | SC-004; fallback tests |
| 5. Run events and sources (US4, P1) | `events.py`, `source.py`; the suite, both fakes | SC-005 |
| 6. Tools (US5, P2) | `tools.py` | story 5 scenarios |
| 7. Docs and final gate | `ARCHITECTURE.md`, `python/README.md`, `WORKSTATE.md`, `CHANGELOG.md`, `docs/whitepaper.md` §10–11 where names changed; 3.11 / 3.12 / 3.13; leak scan; outside reviewer for SC-008 | SC-006, SC-007, SC-008 |

Phase 1 comes first because the import-rule test must exist before the first core module.
Phases 2–4 are serial (each uses the previous one). Phase 5 needs only the models, and phase 6
only `Problem`.

## Risks

| Risk | Mitigation |
|---|---|
| pydantic changes how `exclude_unset` treats defaults in nested models | the round-trip test covers every example object; pin nothing, the CI matrix catches it |
| a door needs an event field not foreseen here (for example, artifact versions) | run events are dataclasses in a v0.x package; 003 may add fields, and the README is not affected |
| the live-pause model fails against a real framework later | the contract suite and the fake reproduce the Claude Agent SDK shape (`await` inside a callback); the bridge spec re-runs the suite |
| changing QUESTION-5 surprises an early reader | v1 is draft, and the change is noted in CHANGELOG and the README |

## Complexity Tracking

None.
