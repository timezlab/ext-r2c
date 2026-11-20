# Architecture

Two halves: the **standard** (what goes on the wire) and the **SDKs** (code that puts it there).
The standard is the source; the SDKs follow it.

```
standard/v1/
  README.md          normative text
  schema/*.json      one JSON Schema per kind      ← single source of shape
  examples/a2a/      wire examples (A2A binding)   ← shared test suite
  examples/mcp/      wire examples (MCP binding)

python/src/ext_r2c/
  __init__.py        URI, MCP_KEY, STANDARD_VERSION, __version__
  core/              models, forms (form → JSON Schema / flat requestedSchema),
                     validate, fallback text                       deps: pydantic, jsonschema
  a2a/               server (wraps an a2a-sdk AgentExecutor), client       extra: [a2a]
  a2a/langchain      serve(graph, card): HITL middleware ⇄ R2C            extra: [langchain]
  mcp/               server (elicitation from forms, _meta on artifacts),  extra: [mcp]
                     client (input_required ⇄ inputResponses + requestState)
```

Only `__init__.py` exists today; the rest is the planned shape from the design brief.

## Import direction

```
core  ←  a2a  ←  a2a.langchain
core  ←  mcp
```

`core` imports no binding and no protocol SDK. `a2a` and `mcp` never import each other. Importing
`ext_r2c` or `ext_r2c.core` must work with no extra installed. A test enforcing this belongs to
the first spec that adds a second module.

## How the schemas reach the wheel

The schemas live in `standard/`, outside `python/`, but the installed package needs them at
runtime. How they are copied into the wheel (and kept identical to the source) is a decision for
the plan of `specs/001-standard-v1`. Constraint: `uv build` builds the wheel from the sdist, so
the sdist must carry them too.

## Testing shape

- Tests run against the installed wheel in a clean venv (`test_smoke.py` asserts this).
- Binding tests are round trips: a real a2a-sdk or MCP SDK client talks to a real server in
  process. Models are faked; protocols are not.
- Every file in `standard/v1/examples/` is validated against its schema and replayed.
