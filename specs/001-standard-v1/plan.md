# Implementation Plan: R2C standard, version 1

**Branch**: `main` (folder `specs/001-standard-v1`) | **Date**: 2026-11-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-standard-v1/spec.md`

## Summary

Write the R2C v1 standard: normative text with tagged rules, six self-contained JSON Schemas,
and complete A2A and MCP wire examples. Add a test suite, run against the installed wheel, that
checks three things:

- every R2C object in the examples against its schema;
- every example's envelope against the real a2a-sdk 1.3 and MCP 2026-07-28 wire types;
- that the rules and examples cover each other.

Ship the schemas inside the wheel, byte-identical, through a small hatch build hook. No SDK
behaviour is added. Research found two things the brief got wrong for MCP 2026-07-28 (an
elicitation has no `_meta`; an elicitation result has no `_meta`). The standard records them as
deviations D1–D4 ([research.md](research.md#deviations-from-the-design-brief)).

## Technical Context

**Language/Version**: JSON (standard), Markdown (normative text), Python ≥ 3.11 (tests, build
hook)

**Primary Dependencies**:
- runtime: unchanged (`pydantic>=2`, `jsonschema>=4`);
- test-only (`dev` group): `pytest>=8`, `a2a-sdk>=1.3,<2`, `mcp>=2.3,<3`,
  `jsonschema[format-nongpl]>=4`;
- build: `hatchling>=1.25` plus a custom build hook.

**Storage**: files in the repository (`standard/v1/`)

**Testing**: pytest against the installed wheel in a clean venv; CI matrix 3.11, 3.12, 3.13

**Target Platform**: any JSON Schema 2020-12 validator (standard); CPython on Linux in CI

**Project Type**: specification plus a library's packaging and test suite

**Performance Goals**: the full check runs in well under a minute in CI (about 50 example files)

**Constraints**:
- schemas self-contained, with no network access while validating;
- public repository: invented data only, `example.com` hosts;
- no change to the package's runtime dependencies or import surface.

**Scale/Scope**: 6 schemas; about 40 rules; about 35 valid examples (including one full streamed
run) and about 12 invalid ones

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | six schemas under `standard/v1/schema/`; the README cites them; the wheel copies them at build time | pass |
| II. Wire examples are the shared test suite | every wire rule cited by an example; an unread example fails the check | pass |
| III. Remote's logic unchanged | no SDK code in this feature; the standard keeps `required: false` and the text fallback | pass |
| IV. An extension, never a protocol | examples use only `metadata[uri]`, `capabilities.extensions`, `A2A-Extensions`, `_meta[key]`, core elicitation; the envelope check proves no core field is invented | pass |
| V. Approval never answered by a model | `approval.json` rejects `answer_by.role = caller`; an invalid example proves it; the client MUST is a rule | pass |
| VI. Public, neutral data | invented data, `example.com`; leak scan before every commit | pass |
| VII. Test first, against the built artifact | each phase writes its failing test first (for example the coverage test before the README rules); every test runs against the installed wheel | pass |
| VIII. Small core, bindings behind extras | protocol SDKs are test-only dependencies; a subprocess test proves `import ext_r2c` loads neither `a2a` nor `mcp` | pass |
| IX. Versioned by URI | schemas and `$id` under `standard/v1`; the packaged path is `schema/v1` | pass |

No violations. Re-check after Phase 1: unchanged. Deviations D1 and D2 move where an R2C object
rides on MCP and stay within principle IV, because `_meta` is MCP's extension point.

## Project Structure

### Documentation (this feature)

```text
specs/001-standard-v1/
├── spec.md
├── plan.md              # this file
├── research.md          # findings R1–R8, deviations D1–D4
├── data-model.md        # the six kinds, field by field; form → schema mapping
├── quickstart.md        # how to run and probe the checks
├── contracts/
│   ├── example-file.md      # format of every example file
│   ├── rule-format.md       # tag line grammar for README rules
│   └── packaged-schemas.md  # where the wheel puts the schemas
├── checklists/requirements.md
└── tasks.md             # next: /speckit-tasks
```

### Source (repository root)

```text
standard/v1/
├── README.md                  # normative text, tagged rules (replaces the placeholder)
├── schema/
│   ├── question.json  approval.json  answer.json
│   └── artifact-meta.json  activity.json  usage.json
└── examples/
    ├── a2a/                   # agent card, questions, approvals, answers, artifacts,
    │                          # activities, usage, re-ask, refusal, not-activated,
    │                          # unknown kind, full-streamed-run, queued approvals
    ├── mcp/                   # discover, elicitation (question, other, approval, edit
    │                          # dropped), retry with inputResponses, progress activity,
    │                          # tool result artifacts + usage
    └── invalid/               # one schema rule broken per file

python/
├── hatch_build.py             # new: copies standard/v1/schema into ext_r2c/schema/v1
├── pyproject.toml             # hook, sdist force-include, dev group (test-only SDKs)
└── tests/
    ├── test_smoke.py          # + subprocess: import loads neither a2a nor mcp
    ├── conftest.py            # new: locate standard/v1 (repo checkout, or R2C_STANDARD_DIR)
    ├── test_schemas.py        # new: each schema valid 2020-12, $id, self-contained, open objects
    ├── test_examples.py       # new: R2C objects, envelopes, pairing, invalid examples
    ├── test_rules.py          # new: README tag lines, rule ↔ example coverage, unread files
    └── test_packaged_schemas.py  # new: wheel files == standard/v1/schema, byte for byte

.github/workflows/python.yml   # install the wheel + dev group into the clean venv
```

**Structure Decision**:
- **The standard stays language-neutral.** `standard/v1/` holds no code, and any SDK can replay
  the examples.
- **The checks live in the Python test suite**, because that is the only runner in the repo and
  it already tests the installed wheel. This is the "CI step" of FR-024, with no second toolchain.
- **Test helpers stay inside `python/tests/`.** That covers the envelope walker and the form →
  schema generator used for pairing. Spec 002 implements the public form → schema mapping in
  `ext_r2c.core`, and its tests must then agree with these examples.

## Phases (each ends verified and committed; one phase per go)

1. **Harness first.**
   - Add `conftest.py`, and `test_rules.py`, `test_examples.py`, `test_schemas.py` against an
     empty standard. They fail for the expected reasons ("no rules found", "no schema files").
   - Add `hatch_build.py`, `pyproject.toml` changes, the CI change and the smoke-test addition.
   - `test_packaged_schemas.py` fails until the schemas exist.
2. **Schemas and invalid examples.**
   - Write the six schemas from [data-model.md](data-model.md).
   - Write one invalid example per schema rule.
   - Green: the schema tests, the invalid examples, the packaged schemas.
3. **Normative text.**
   - Write `standard/v1/README.md` with tagged rules, covering FR-001 to FR-013 and
     FR-017.
   - The coverage test then fails, listing every `wire` rule with no example yet: the to-do list
     for phases 4–5.
4. **A2A examples.**
   - Agent card and activation, then each kind, then the sequences (queued approvals, the full
     streamed run).
   - Green: every A2A rule is covered.
5. **MCP examples.**
   - Discover, elicitation for each form type, approval with and without a flat `args_schema`,
     the retry, progress, the tool result.
   - Green: full coverage.
6. **Docs and close.**
   - Dated notes in the brief and the white paper, and a fix to the white paper's §7 MCP JSON
     (D3).
   - Update `standard/v1/README.md` status, `AGENTS.md`, `WORKSTATE.md` and `CHANGELOG.md`.
   - Fresh build and full run on 3.11, 3.12 and 3.13, then the leak scan.
   - A reviewer pass for SC-005, by a fresh-context agent that has only the README and the
     schemas.

## Complexity Tracking

No constitution violations. One deliberate addition, recorded for review:

| Addition | Why needed | Simpler alternative rejected because |
|---|---|---|
| `python/hatch_build.py` (custom build hook, ~15 lines) | `uv build` builds the wheel from the sdist, where `../standard` does not exist (research R5) | a static `force-include` breaks the wheel build; a committed copy drifts and breaks FR-022 |
