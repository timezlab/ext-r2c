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

examples/langgraph_agent/   the SDK in use: two LangChain agents served by `Remote` that call each
                            other. Documentation: not in the wheel, run by
                            python/tests/test_example_langgraph.py against the installed wheel

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
    skills/          MCP Skills (SEP-2640), a second Extension that is NOT R2C  extra: [mcp], PyYAML
      extension.py   SkillsExtension: skills/list, skills/get, resources/directory/read, every
                     file as a resource; refresh()
      client.py      SkillsClient: list, get, load, read, list_directory; verifies size, digest
                     and frontmatter, refuses what it cannot verify
      _scan.py       the folder walk: filters, limits, what is left out, every directory
      _catalogue.py  the immutable snapshot a handler answers from (URI-keyed dictionaries)
      _read.py       the safe read: each name opened from "/" with O_NOFOLLOW, regular files
                     only, never past the entry's size   (_content.py: the bytes to the wire)
      _frontmatter.py, _uris.py, _cursor.py, _settings.py, _limits.py, _wire.py
  bridges/           one subpackage per agent framework; imports nothing itself
    langgraph/       LangGraphAgent: a compiled graph as a checkpoint AgentSource;
                     LangChain tools → ToolSpec                                extra: [langgraph]
      agent.py       LangGraphAgent: run, resume, the wrap checks; one leg per astream
      _leg.py        one leg: a producer task reads astream, a queue merges stream and handler,
                     the generator yields run events and ends right after an Ask
      _handler.py    the per-run callback handler (tool start/end/error, hidden model calls)
      _pauses.py     a pause read from the checkpointer's pending list, never from the stream:
                     request ids, the order, what the graph gets back for a value
      _decisions.py  a tool call's decisions both ways (graph ⇄ R2C); the checks before the graph
      _batch.py      Batches: the answers of a `batched` pause in progress (in memory)
      _settle.py     a new message on a pending approval: one state update, no resume
      _structured.py `input_required`: a turn that ends asking the caller
      _reply.py      hold-one, the blank line between messages, the JSON hold
      _reasoning.py, _usage.py, _blocks.py   reasoning pieces, usage from the checkpoint,
                     content blocks both ways (human input; file artifacts)
      tools.py       tool_from_langchain, tools_from_langchain
  bridges/<other>/   later: one bridge and one extra per agent framework
  remote/            Remote: the only remote-side adapter; exposes A2A, MCP or both
                     (a setting) as one ASGI app; agent, tools and skills are passed in
    _remote.py       Remote: the constructor, app() once, the lifespans of both doors
    _check.py        every check of the settings at build time (one RemoteError listing all
                     problems) and the warnings for a door left on its in-memory defaults
    _classify.py     what an agent is by shape: a source, an a2a-sdk executor, or neither
    _options.py      A2AOptions, MCPOptions and the keys Remote owns (a clash is a problem)
    _doors.py        builds the A2A app and the MCP server; loads a door's package only then
    _compose.py      the parent Starlette app, the dispatcher (/mcp to MCP, the rest to A2A),
                     the owner's middleware outermost
    _errors.py       RemoteError
```

Three extension points live in `core`: `AgentSource` (an agent framework; supports a
checkpoint pause and a live pause), `ToolSpec` (a tool), and the run events both doors read.
A new framework adds a bridge; `Remote` and the doors do not change.

`__init__.py`, `core/`, `a2a/`, `mcp/`, `bridges/langgraph/` and `remote/` exist today; the rest
is the planned shape from the design brief and the ADR
[one remote, two doors](docs/design-docs/one-remote-two-doors.md). `Remote` is spec
`007-remote` (names in
[specs/007-remote/contracts/remote-api.md](specs/007-remote/contracts/remote-api.md), the app in
[specs/007-remote/contracts/app-composition.md](specs/007-remote/contracts/app-composition.md)). MCP
Skills (SEP-2640) is its own spec, `005-mcp-skills`, built under `mcp/skills/`. The LangGraph
bridge is spec `006-langgraph-bridge` (names in
[specs/006-langgraph-bridge/contracts/langgraph-api.md](specs/006-langgraph-bridge/contracts/langgraph-api.md);
why in the ADR [a pause becomes an ask](docs/design-docs/langgraph-pause-to-ask.md)). The public names of
`core` are in
[specs/002-python-core/contracts/core-api.md](specs/002-python-core/contracts/core-api.md), those
of `a2a` in [specs/003-a2a-binding/contracts/a2a-api.md](specs/003-a2a-binding/contracts/a2a-api.md),
those of `mcp` in [specs/004-mcp-binding/contracts/mcp-api.md](specs/004-mcp-binding/contracts/mcp-api.md),
and those of `mcp/skills` in
[specs/005-mcp-skills/contracts/skills-api.md](specs/005-mcp-skills/contracts/skills-api.md).

## Import direction

```
core  ←  a2a
core  ←  mcp
core  ←  bridges.*
core  ←  remote   (loads a2a or mcp only when that door is enabled; imports no bridge)
```

`core` imports no door, no bridge and no protocol SDK. `a2a`, `mcp` and the bridges never import
each other. `mcp/skills/` is not R2C: it imports nothing of `ext_r2c` at all (not even `core`), so
it can be lifted out whole; `mcp/__init__.py` re-exports its names and `mcp/server.py` only takes
any `Extension` beside R2C's. `test_packaging.py::test_mcp_skills_imports_no_ext_r2c` enforces the
rule on the installed wheel, and `test_skills_compose.py` shows R2C's wire is unchanged beside it.

`bridges/langgraph/` imports `ext_r2c.core`, `langgraph`, `langchain_core`, `jsonschema` and
`pydantic` and nothing else of `ext_r2c`, and no other module of `ext_r2c` imports it (a bridge
is the end of a line: `Remote` takes the agent it is given and imports no bridge).
`test_packaging.py::test_langgraph_bridge_imports_only_allowed_modules` is an `ast` scan of that on
the installed wheel; a CI step installs the wheel with only `[langgraph]` and runs
`tests/langgraph_only.py`, which also proves no `a2a` or `mcp` module is loaded.

`remote/` imports at module level only the standard library, `ext_r2c.core*` and its own
modules. A door's package (`ext_r2c.a2a`, `ext_r2c.mcp`), `starlette`, `a2a` and `mcp` are
imported inside a function, or under `TYPE_CHECKING`, so `from ext_r2c import Remote` works with
no extra installed and a door is loaded only when it is exposed. `test_packaging.py` scans it on
the installed wheel, and each single-extra script checks a `Remote` in its own venv:
`core_only.py` and `langgraph_only.py` show that a door whose extra is missing is refused with the
extra's name and that nothing of a door is loaded; `a2a_only.py` and `mcp_only.py` serve their one
door and show that the other door's paths answer 404 and its package is not loaded.

Importing `ext_r2c` or `ext_r2c.core` must work with no extra installed; opening a door
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
