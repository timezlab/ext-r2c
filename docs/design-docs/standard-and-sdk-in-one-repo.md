# The standard and the SDK in one repo, under `standard/`

**Status:** accepted, 2026-11-20.

## Context

An extension needs a normative text and a URI; adopters need a library. They can live in one
repository or two. The folder name also matters: this repo uses Spec Kit, which owns `specs/`
and generates `contracts/` folders.

## Decision

- One public repo, `timezlab/ext-r2c` (precedent: `modelcontextprotocol/ext-apps`), Apache-2.0.
- The standard lives in **`standard/v1/`**: normative `README.md`, one JSON Schema per kind in
  `schema/`, wire examples in `examples/a2a/` and `examples/mcp/`.
- The A2A URI is that folder's URL: `https://github.com/timezlab/ext-r2c/tree/main/standard/v1`.
  The MCP `_meta` key is `io.github.timezlab/r2c`.
- **The JSON Schemas are the single source of shape.** SDK models follow them; prose never
  contradicts them.
- **The wire examples are the shared test suite.** Every example validates in CI, and every SDK
  replays all of them.
- The Python SDK lives in `python/` (PyPI `ext-r2c`, import `ext_r2c`, extras `[a2a]`, `[mcp]`,
  `[langgraph]`, later one per agent framework). A TypeScript SDK would sit beside it as `typescript/` (npm `@timezlab/ext-r2c`).

## Alternatives

- **`spec/` or `contracts/`.** Both clash with Spec Kit (`specs/`, generated `contracts/`).
- **Spec repo plus one repo per SDK.** Schema and code drift apart, and an example change needs
  coordinated releases.
- **A protocol of our own.** R2C changes no core structure of A2A or MCP; it is an extension.

## Consequences

- **Better:** a change to shape, examples and SDK lands in one commit and one CI run.
- **Worse:** the Python package must ship schemas that live outside `python/`; the build has to
  copy them (decided in the plan of spec 001).
- **Must now be true:** a breaking change opens `standard/v2/` and a new URI; v1 stays *draft*,
  and may still change, until the first remote outside timezlab uses it. The PyPI name is not
  reserved yet and may change if taken.
