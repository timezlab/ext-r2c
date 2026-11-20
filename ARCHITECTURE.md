# Architecture

Two halves: the **standard** (what goes on the wire) and the **SDKs** (code that puts it there).
The standard is the source; the SDKs follow it.

```
standard/v1/
  README.md          normative text
  schema/*.json      one JSON Schema per kind      ← single source of shape
  examples/a2a/      wire examples (A2A binding)   ← shared test suite
  examples/mcp/      wire examples (MCP binding)
  examples/invalid/  objects each schema must reject

python/src/ext_r2c/
  __init__.py        URI, MCP_KEY, STANDARD_VERSION, __version__, Remote
  core/                                                            deps: pydantic, jsonschema
    _schemas.py      packaged schema loader, date-time check, $ref scan
    models.py        the six kinds and their parts; parse, to_json
    forms.py         answer_schema, mcp_form (flat requestedSchema), answer_from_mcp
    check.py         check_answer, decision, check_size, Limits, Problem
    fallback.py      fallback_text
    events.py        run events (reply chunk, activity, ask, answer, artifact, usage, done, error)
    source.py        AgentSource, RunContext, Driver, Run, thread_id
    tools.py         ToolSpec, tool_from_function
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

`__init__.py` and `core/` exist today; the rest is the planned shape from the design brief and
the ADR [one remote, two doors](docs/design-docs/one-remote-two-doors.md). The public names of
`core` are in [specs/002-python-core/contracts/core-api.md](specs/002-python-core/contracts/core-api.md).

## Import direction

```
core  ←  a2a
core  ←  mcp
core  ←  bridges.*
core  ←  remote   (loads a2a or mcp only when that door is enabled; imports no bridge)
```

`core` imports no door, no bridge and no protocol SDK. `a2a`, `mcp` and the bridges never import
each other. Importing `ext_r2c` or `ext_r2c.core` must work with no extra installed; opening a door
whose extra is missing fails with a message naming the extra. `test_packaging.py` enforces the
core's side (an `ast` scan of its imports, and a subprocess that imports it and loads no protocol
SDK), and a CI step installs the wheel alone and runs `tests/core_only.py`.

## How the schemas reach the wheel

The schemas live in `standard/`, outside `python/`, but the installed package needs them at
runtime, as `ext_r2c/schema/v1/*.json`. `uv build` builds the wheel from the sdist, so:

- the sdist carries `standard/v1/schema/` (a `force-include` in `pyproject.toml`);
- the build hook `python/hatch_build.py` puts that folder into the wheel, from the checkout or
  from the unpacked sdist, and fails the build when it finds neither;
- `test_packaged_schemas.py` checks that the installed files are byte for byte the source.

No copy is committed under `python/src/`.

## Testing shape

- Tests run against the installed wheel in a clean venv (`test_smoke.py` asserts this).
- Binding tests are round trips: a real a2a-sdk or MCP SDK client talks to a real server in
  process. Models are faked; protocols are not.
- `Remote` is tested with one agent source served through both doors in one process, and with
  each door alone.
- Every bridge passes one shared conformance suite; `AgentSource` is also tested with a fake
  checkpoint-style source and a fake live-style source (`tests/agent_source_suite.py`, run by
  `test_agent_source.py`).
- Every file in `standard/v1/examples/` is read by the tests: each R2C object is validated
  against its schema, each envelope against the real a2a-sdk or MCP types, each invalid object
  must fail where it says, and every `wire` rule of the standard must be shown by an example.
  The SDK bindings will also replay them.
