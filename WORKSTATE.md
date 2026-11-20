# Work state

Last updated 2026-11-20. Read this first in a new session.

## Done

- **Design approved** (2026-11-20): `docs/research/2026-11-20-r2c-v1-design-brief.md`, with five
  ADRs in `docs/design-docs/`. Every question about the extension itself is settled.
- **Repository skeleton:** license, README, CHANGELOG, `standard/v1/README.md` (placeholder),
  Python package `ext-r2c` 0.0.1 exposing `URI`, `MCP_KEY`, `STANDARD_VERSION`, `__version__`.
- **Wheel builds and tests pass** on Python 3.11, 3.12 and 3.13 (5 smoke tests, run against the
  installed wheel). CI in `.github/workflows/python.yml` does the same.
- **Harness:** Spec Kit 0.13.4 initialised (`specs/` at the root), constitution 1.0.0, rules,
  skills, reviewer agents.

## Not done on purpose

- The PyPI name `ext-r2c` is **not reserved** (maintainer, 2026-11-20). If it is taken by the
  time we publish, rename the distribution; the import name and identifiers stay.
- No normative text, schema or example yet: that is spec 001.

## Next: proposed spec sequence (awaiting the maintainer's approval)

Each is one Spec Kit feature (`/speckit-specify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-implement`, one phase per go).

1. **`001-standard-v1`** — normative text in `standard/v1/README.md`; JSON Schemas for
   `question`, `approval`, `answer`, `artifact-meta`; wire examples (A2A and MCP) covering every
   rule; CI step validating every example; schemas shipped inside the wheel. Done when every
   example validates, the wheel carries byte-identical schemas, and a test fails if one example
   breaks its schema.
2. **`002-python-core`** — `ext_r2c.core`: pydantic models matching the schemas, form → JSON
   Schema and → flat `requestedSchema`, validation with size limits and no external `$ref`,
   text fallback. Done when every example round-trips through the models unchanged.
3. **`003-a2a-binding`** — `ext_r2c.a2a` server wrapper and client; real round trips through
   a2a-sdk 1.3 in process; re-ask with `errors`, expiry, wrong `id`, artifact presentation,
   one unfinished task per context, `thread_id = f(owner, contextId)`.
4. **`004-langchain-bridge`** — `serve(graph, card)`: `HumanInTheLoopMiddleware` in `batched`
   and `per_call` modes, hand-written `interrupt()`, the `status = "input_required"` turn end,
   file content blocks → artifacts. Success criteria 1–5 of the brief.
5. **`005-mcp-binding`** — `ext_r2c.mcp`: elicitation from forms and approvals, answer mapping,
   artifacts as tool-result content, `RequestStateBoundary`. Success criterion 6.
6. Later: `examples/langchain_agent/`, publishing to PyPI, a TypeScript SDK.

## Open, outside this repo

How a particular caller routes `answer_by: caller` to its agent, its "Always allow" scope,
and live-view embedding belong to that caller's own project. The brief's §8 records only the
shapes R2C was designed against.

## Working rules worth repeating

- Public repo: scan every commit's added lines for private tokens before committing (the
  pattern lives in the maintainer's local notes, not in the repo).
- Build the wheel and run the full test suite on it before saying anything is done.
