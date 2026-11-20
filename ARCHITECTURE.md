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
    _codec.py        R2C objects ⇄ A2A Parts and Artifacts; what a stored Task says
    activation.py    activation per request, the echoed header
    card.py          agent_card: the card with the extension declared
    task.py          R2CTask, PendingMemory: R2C on one task, for any executor
    executor.py      SourceExecutor: serves an AgentSource through Driver
    app.py           a2a_app: the Starlette app; R2CRequestHandler (user-role messages only,
                     no stored R2C content without activation)
    client.py        R2CClient and its typed items, for the caller
  mcp/               MCP door: run events ⇄ MCP wire (an MCP SDK Extension), caller-side
                     client (input_required ⇄ inputResponses + requestState)  extra: [mcp]
    _codec.py        R2C ⇄ MCP: input-required results, the elicitation message, progress,
                     content blocks; mcp_response (an answer → an elicitation response)
    _state.py        the stopping point in requestState (sealed by the SDK); the retry
                     outcome; RoundLedger, MemoryLedger: each round is used once
    activation.py    is_active, form_supported, owner_of
    tools.py         ToolSpecs served as tools; Approve: an approval before a direct call
    source_tool.py   SourceTool: one AgentSource as one tool, across rounds, one call per
                     owner and context
    extension.py     R2CExtension: the MCP SDK Extension (tools, approve=, the interceptor)
    server.py        mcp_server: an MCPServer with the extension wired in
    client.py        R2CClient and its typed items, for the caller
  bridges/langgraph/ LangGraphAgent (graph → run events: HITL interrupts, reply tokens, tool
                     activity, reasoning opt-in, usage); LangChain tools → ToolSpec  [langgraph]
  bridges/<other>/   later: one bridge and one extra per agent framework
  remote/            Remote: the only remote-side adapter; exposes A2A, MCP or both
                     (a setting) as one ASGI app; agent, tools and skills are passed in
```

Three extension points live in `core`: `AgentSource` (an agent framework; supports a
checkpoint pause and a live pause), `ToolSpec` (a tool), and the run events both doors read.
A new framework adds a bridge; `Remote` and the doors do not change.

`__init__.py`, `core/`, `a2a/` and `mcp/` exist today; the rest is the planned shape from the
design brief and the ADR [one remote, two doors](docs/design-docs/one-remote-two-doors.md). MCP
Skills (SEP-2640) is its own spec, `005-mcp-skills`. The public names of `core` are in
[specs/002-python-core/contracts/core-api.md](specs/002-python-core/contracts/core-api.md), those
of `a2a` in [specs/003-a2a-binding/contracts/a2a-api.md](specs/003-a2a-binding/contracts/a2a-api.md),
and those of `mcp` in [specs/004-mcp-binding/contracts/mcp-api.md](specs/004-mcp-binding/contracts/mcp-api.md).

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
  process. Models are faked; protocols are not. For A2A the test bed is
  `tests/a2a_transport.py` (an httpx transport that streams SSE from the ASGI app) and
  `tests/a2a_harness.py` (serve an executor, a client per user, drive a task). A CI step
  installs the wheel with `[a2a]` alone and runs `tests/a2a_only.py`. For MCP the test bed is
  `tests/mcp_transport.py` (a streaming, recording httpx2 transport over the ASGI app) and
  `tests/mcp_harness.py` (serve an `MCPServer`, a client per principal, drive a tool call
  round by round); a CI step installs the wheel with `[mcp]` alone and runs
  `tests/mcp_only.py`.
- `Remote` is tested with one agent source served through both doors in one process, and with
  each door alone.
- Every bridge passes one shared conformance suite; `AgentSource` is also tested with a fake
  checkpoint-style source and a fake live-style source (`tests/agent_source_suite.py`, run by
  `test_agent_source.py`).
- Every file in `standard/v1/examples/` is read by the tests: each R2C object is validated
  against its schema, each envelope against the real a2a-sdk or MCP types, each invalid object
  must fail where it says, and every `wire` rule of the standard must be shown by an example.
  Every A2A example is also replayed as a real round trip, against the client and against the
  door (`tests/a2a_replay_kit.py`, `test_a2a_replay.py`), and so is every MCP example
  (`tests/mcp_replay_kit.py`, `test_mcp_replay.py`; `discover.json` is compared with
  `server/discover`).
