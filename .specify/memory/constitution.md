<!--
Sync Impact Report
- Version: 1.1.0 → 1.1.1 (2026-11-20)
- Wording: Technical Constraints size limits read MiB (2^20 bytes), not MB (maintainer, open
  point O11 of specs/001-standard-v1/research.md). PATCH.
- Docs updated in the same change: standard/v1/README.md (R2C-SAFETY-4), docs/whitepaper.md,
  example a2a/artifact-file-raw.json. Historical records (brief, spec 001) keep "MB".
- Templates: no edits needed

Previous: 1.0.0 → 1.1.0 (2026-11-20)
- Modified principle: VIII. A small core, bindings behind extras — the import list now reads
  core ← a2a, core ← mcp, core ← bridges.*, core ← remote (the LangGraph bridge no longer sits
  under a2a; one bridge and one extra per agent framework; remote is the only remote-side
  adapter and imports no bridge). The principle itself is unchanged, so MINOR.
- Modified section: Technical Constraints — extra [langgraph] replaces [langchain].
- Source: ADR docs/design-docs/one-remote-two-doors.md
- Docs updated in the same change: ARCHITECTURE.md, design brief amendment, WORKSTATE.md
- Templates: plan-template.md "Constitution Check" reads this file as is; no template edits needed
- Deferred: pyproject.toml extras ([langchain] → [langgraph], no longer pulling [a2a]) change
  with spec 002

Previous: template → 1.0.0 (first ratification): principles I–IX, Technical Constraints,
Development Workflow, Governance.
-->

# ext-r2c Constitution

R2C (Remote-to-Caller) is an extension for A2A and MCP. This repository holds the standard
(`standard/`) and its SDKs (`python/`, later `typescript/`). Every spec in `specs/` inherits
these principles.

## Core Principles

### I. The schema is the single source of shape

Every R2C kind has one JSON Schema under `standard/vN/schema/`. SDK models follow the schemas
and are tested against them; the normative text never contradicts them. A change of shape
changes the schema first, in the same commit as the prose, examples and SDK that follow it.

### II. Wire examples are the shared test suite

Every rule that can be shown on the wire has an example under `standard/vN/examples/`. CI
validates every example against its schema, and every SDK replays every example in its
round-trip tests. An example that no test reads is a bug.

### III. The remote's own logic stays unchanged

Adoption costs a remote's owner one install and one wrapping line. No feature may require a
remote to restructure its agent or server. A remote that adopts nothing still works with an
R2C caller in plain text.

### IV. An extension, never a new protocol

R2C uses only the extension points of A2A (`metadata[URI]`, `capabilities.extensions`,
`A2A-Extensions`) and MCP (`_meta[key]`, core elicitation). It never adds enums or changes core
structures. It is always optional (`required: false`); without activation a remote sends text
and standard artifacts. Implementations MUST ignore an unknown kind or field.

### V. An approval is answered by a human or a policy, never a model

`approval` never has `answer_by: caller` and its `answer` never has `answered_by: caller`;
clients MUST enforce this. Remembered consent is a client-held policy applied by code
(`answered_by: policy`) and never applies to `answer_by: approver`. Agent-to-agent exchange
through `question` (`answer_by: caller`) and plain A2A text is never blocked.

### VI. Public by default, neutral data only

This repository is public. No file, commit message or example may carry a private
organisation's names, people, hosts, figures, workspace ids or absolute local paths. Examples
use invented data and `example.com` hosts. Every commit is scanned for private tokens before it
is made.

### VII. Test first, against the built artifact

Behaviour starts with a failing test that fails for the expected reason. Python tests run
against the **installed wheel**, not the source tree. Bindings are tested by real client ⇄
server round trips through the real protocol SDKs, in process; mocks stand in only for models
and the network edge.

### VIII. A small core, bindings behind extras

The core depends only on `pydantic` and `jsonschema`. Protocol SDKs come in through extras
(`[a2a]`, `[mcp]`) and agent frameworks through one extra per bridge (`[langgraph]`, later
others). Imports run one way: `core` ← `a2a`, `core` ← `mcp`, `core` ← `bridges.*`, `core` ←
`remote`. `core` imports no door and no bridge; `a2a`, `mcp` and the bridges never import each
other; `remote` (the only remote-side adapter) imports no bridge and loads a door only when it
is enabled.

### IX. Versioned by URI

The major version of the standard is in its URI (`standard/v1`). A breaking change opens
`standard/v2/` with a new URI (A2A) and a `revision` bump (MCP). v1 is *draft* until the first
remote outside timezlab adopts it and may change until then; afterwards v1 takes additive
changes only. The package version (SemVer) is separate from the standard's version.

## Technical Constraints

- Python ≥ 3.11; `a2a-sdk>=1.3` in `[a2a]`, `mcp>=2.3` in `[mcp]`, `langchain>=1.3` +
  `langgraph` in `[langgraph]`.
- Build with hatchling through `uv build`; tests with pytest.
- License Apache-2.0.
- Everything committed is written in English (specs, docs, code, commit messages).
- Identity, tokens and transport belong to A2A, MCP and the deployment; the SDK never reads or
  issues credentials.
- Size limits: content inside a message ≤ 5 MiB; files fetched by `url` ≤ 50 MiB (SHOULD for the
  remote, enforced by the client).

## Development Workflow

- Spec Kit: `specs/NNN-<short-name>/` holds `spec.md` → `plan.md` → `tasks.md`. No behaviour
  code before `spec.md` and `plan.md` exist and the maintainer approved them. A mechanical
  change may skip the spec if that is said explicitly.
- Architectural decisions worth disagreeing about get an ADR in `docs/design-docs/` (Context,
  Decision, Alternatives, Consequences). Research that precedes a spec goes in
  `docs/research/<date>-<topic>.md`.
- `/speckit-implement` runs one phase per go: finish the phase, verify, report, stop.
- Before claiming done: a fresh build of the wheel and a full test run on it.
- Commits go straight to `main` with an explicit pathspec; pushing needs the maintainer's go.

## Governance

This constitution overrides other practice in this repository. An amendment updates this file
with a Sync Impact Report, bumps the version (MAJOR: a principle removed or redefined; MINOR: a
principle or section added; PATCH: wording), and fixes any template or doc it makes stale in
the same commit. Reviews check new specs and plans against the principles above; an exception
is written into the plan's Complexity Tracking with its reason.

**Version**: 1.1.1 | **Ratified**: 2026-11-20 | **Last Amended**: 2026-11-20
