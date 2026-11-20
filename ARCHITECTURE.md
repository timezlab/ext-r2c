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
  __init__.py        URI, MCP_KEY, STANDARD_VERSION, __version__, Remote
  core/              models (six kinds), forms (form → JSON Schema / flat requestedSchema),
                     validate, fallback text, run events, AgentSource, ToolSpec
                                                                   deps: pydantic, jsonschema
  a2a/               A2A door: run events ⇄ A2A wire (a2a-sdk), caller-side client  extra: [a2a]
  mcp/               MCP door: run events ⇄ MCP wire (an MCP SDK Extension), MCP Skills,
                     caller-side client (input_required ⇄ inputResponses + requestState)  [mcp]
  bridges/langgraph/ LangGraphAgent (graph → run events: HITL interrupts, reply tokens, tool
                     activity, reasoning opt-in, usage); LangChain tools → ToolSpec  [langgraph]
  bridges/<other>/   later: one bridge and one extra per agent framework
  remote/            Remote: the only remote-side adapter; exposes A2A, MCP or both
                     (a setting) as one ASGI app; agent, tools and skills are passed in
```

Three extension points live in `core`: `AgentSource` (an agent framework; supports a
checkpoint pause and a live pause), `ToolSpec` (a tool), and the run events both doors read.
A new framework adds a bridge; `Remote` and the doors do not change.

Only `__init__.py` exists today; the rest is the planned shape from the design brief and the
ADR [one remote, two doors](docs/design-docs/one-remote-two-doors.md).

## Import direction

```
core  ←  a2a
core  ←  mcp
core  ←  bridges.*
core  ←  remote   (loads a2a or mcp only when that door is enabled; imports no bridge)
```

`core` imports no door, no bridge and no protocol SDK. `a2a`, `mcp` and the bridges never import
each other. Importing `ext_r2c` or `ext_r2c.core` must work with no extra installed; opening a door
whose extra is missing fails with a message naming the extra. A test enforcing this belongs to
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
- `Remote` is tested with one agent source served through both doors in one process, and with
  each door alone.
- Every bridge passes one shared conformance suite; `AgentSource` is also tested with a fake
  checkpoint-style source and a fake live-style source.
- Every file in `standard/v1/examples/` is validated against its schema and replayed.
