<!--
Sync Impact Report
- Version: template → 1.0.0 (first ratification)
- Principles added: I–IX (all new)
- Sections added: Technical Constraints, Development Workflow, Governance
- Templates: plan-template.md "Constitution Check" reads this file as is; no template edits needed
- Deferred: none
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
(`[a2a]`, `[mcp]`, `[langchain]`). Imports run one way: `core` ← `a2a`, `core` ← `mcp`,
`a2a` ← `a2a.langchain`. `core` imports no binding, and `a2a` and `mcp` never import each other.

### IX. Versioned by URI

The major version of the standard is in its URI (`standard/v1`). A breaking change opens
`standard/v2/` with a new URI (A2A) and a `revision` bump (MCP). v1 is *draft* until the first
remote outside timezlab adopts it and may change until then; afterwards v1 takes additive
changes only. The package version (SemVer) is separate from the standard's version.

## Technical Constraints

- Python ≥ 3.11; `a2a-sdk>=1.3`, `mcp>=2.3`, `langchain>=1.3` + `langgraph` in their extras.
- Build with hatchling through `uv build`; tests with pytest.
- License Apache-2.0.
- Everything committed is written in English (specs, docs, code, commit messages).
- Identity, tokens and transport belong to A2A, MCP and the deployment; the SDK never reads or
  issues credentials.
- Size limits: content inside a message ≤ 5 MB; files fetched by `url` ≤ 50 MB (SHOULD for the
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

**Version**: 1.0.0 | **Ratified**: 2026-11-20 | **Last Amended**: 2026-11-20
