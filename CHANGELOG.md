# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Repository skeleton: Python package `ext-r2c` exposing `URI`, `MCP_KEY` and
  `STANDARD_VERSION`, CI that tests the built wheel.
- The R2C standard v1 (draft): the normative text in `standard/v1/README.md`,
  with tagged rules for activation, placement, the six kinds, the A2A and MCP
  bindings, identifiers, safety and versioning.
- JSON Schemas for `question`, `approval`, `answer`, `artifact` metadata,
  `activity` and `usage` in `standard/v1/schema/`.
- Wire examples for A2A and MCP in `standard/v1/examples/`, including a full
  streamed run, and objects each schema must reject.
- Checks that validate every example's objects and envelopes (against the
  a2a-sdk and MCP SDK types) and that every wire rule has an example.
- The wheel ships the schemas as `ext_r2c/schema/v1/`.
- `R2C-VERSION-3`: a new value in a closed enum is a breaking change and needs
  a new major version.
- `ext_r2c.core`, the protocol-free core (needs only pydantic and jsonschema):
  models of the six kinds that round-trip every example; forms (the answer
  schema, the flat MCP `requestedSchema`, a flat response back to an answer);
  the answer check with readable problems, size limits and no external `$ref`;
  fallback text; neutral run events; `AgentSource` with one `Driver` for
  checkpoint and live sources; `ToolSpec` from a plain function.
- Examples: `mcp/elicitation-question-many-other.json` and
  `a2a/reask-empty-required.json`.
- `ext_r2c.a2a`, the A2A door on a2a-sdk (the `[a2a]` extra): `a2a_app` and
  `SourceExecutor` serve an `AgentSource`; activation and the echoed header;
  `agent_card` with the extension declared; answers checked, re-asked with
  `errors` or refused; one unfinished task per owner and context; paused tasks
  resumed after a restart through the task store; `R2CTask` and
  `PendingMemory` for an executor written by hand; `R2CRequestHandler`, which
  refuses a client message without the user's role and shows a caller that did
  not activate R2C no stored R2C content.
- `R2CClient`, the caller's A2A client: typed items for every R2C object,
  answers checked before they are sent, `reattach` after a cut, `get_task`,
  `cancel`, and a same-origin `fetch` with a size limit.
- `ReplyChunk.last`: the source marks the reply's final chunk.
- `check_answer` gives `policy_on_approver` for a `policy` answer to an
  approval that asks an approver every time (R2C-ANSWER-5).
- Every A2A example is replayed as a real in-process round trip, against the
  client and against the door.
- Examples: `a2a/second-task-rejected.json` and `a2a/usage-with-activity.json`.
- `ext_r2c.mcp`, the MCP door on the MCP Python SDK for protocol 2026-07-28
  (the `[mcp]` extra): `R2CExtension`, an MCP SDK `Extension`, and
  `mcp_server`; `SourceTool` serves an `AgentSource` as one tool across
  multi-round-trip calls, and `ToolSpec`s are served as plain tools
  (`ToolOutput` for structured content, artifacts and usage); `approve=` asks
  an approval before a direct tool call, with the arguments in its description
  and `edit` on flat arguments;
  questions and approvals as elicitation forms, answers checked, re-asked with
  `errors` or refused; activities as `notifications/progress`; usage and
  artifacts on the tool result; the stopping point in `requestState`, sealed by
  the SDK, each round used once through a `RoundLedger`; one call per owner and
  context; a paused checkpoint source resumed after a restart with fixed keys.
- `R2CClient`, the caller's MCP client: typed items for every R2C object,
  answers checked before they are sent (`mcp_response` builds the elicitation
  response), several pending requests gathered into one retry, `respond` for a
  plain elicitation, `cancel`, and a `fetch` that reads only the server's own
  origin, with a size limit.
- Every MCP example is replayed as a real in-process round trip, against the
  client and against the door; `discover.json` is compared with the door's
  `server/discover`.
- Examples: `mcp/elicitation-two-rounds.json`, `mcp/elicitation-reask.json`,
  `mcp/elicitation-no-response.json`, `mcp/tool-result-inline-image.json` and
  `mcp/approval-tool-call.json`.
- MCP Skills (SEP-2640, Beta, extension `io.modelcontextprotocol/skills`) in
  `ext_r2c.mcp`, a second MCP SDK `Extension` that is not R2C: `SkillsExtension`
  serves folders of `SKILL.md` as `skills/list` (paged by an opaque cursor),
  `skills/get`, every file as an ordinary resource, and `resources/directory/read`
  (on by default, `directory_read=False` turns it off); `include` / `exclude`,
  the 512-file and 16 MiB limits, `refresh()`, and what is left out reported
  (`left_out`). A file outside the skill's folder, or a link, is never served,
  and a file changed on disk since the scan is refused. A scan is bounded
  whatever the tree (32 folders deep, 1024 folders in a skill, 1024 folders
  that are not skills under a root); a name with a control character, a line
  break, a bidi control or a backslash is left out (`unsafe name`) and shown
  escaped; a file the system cannot read is `-32603` "The server could not read
  the file.", not "changed on disk".
- `SkillsClient`, the caller's Skills client: `list`, `get`, `load`, `read` and
  `list_directory`, which verify each file's size, digest and frontmatter against
  the entry and refuse what they cannot verify, read nothing ahead of need, and
  stop on a repeated cursor. An entry is refused unless its name and description
  have the allowed lengths, its URI (of any scheme) is `…/<name>/SKILL.md`, every
  listed file is strictly inside the skill's folder, and it is listed once.
- `mcp_server(name, extension, extensions=[...])` serves other MCP extensions
  after R2C's.
- `[mcp]` brings PyYAML (`>=6.0.3,<7`), which reads the frontmatter. The core
  and the `[a2a]` extra do not need it.
- `ext_r2c.bridges.langgraph`, the first bridge (the `[langgraph]` extra):
  `LangGraphAgent` serves a compiled LangGraph graph, such as a LangChain agent,
  as an `AgentSource` of the checkpoint style, so both doors serve it with no
  change to the graph. A wrap with no checkpointer, an uncompiled graph or an
  input with no `messages` fails at once and says what is missing.
  - Pauses become asks: `HumanInTheLoopMiddleware` in `per_call` and `batched`
    mode (an approval per call, one at a time, in the model's order; `allow`,
    `edit` and `deny`, only what the call allows), a call that allows only a
    reply (a question), a hand-written `interrupt()` (a valid R2C question or
    approval as it is, anything else a question for a person) and a turn that ends
    with a structured reply `status = "input_required"` (a question for the
    caller; its answer is the next message of the thread). An approval is never
    addressed to the caller. A pause is read from the checkpointer, so it is
    answered after a restart, with the same request ids, over a durable async
    checkpointer.
  - An answer the graph would refuse is refused first, with the problems, and the
    pause stays pending (the middleware would leave the thread stuck). An answer for
    a pause the checkpointer no longer holds ends the run `lost`. A declined approval
    is a `deny` for the graph, and in `batched` mode a call already decided is not
    decided again (`lost`). A new message on a thread with a tool call nothing answered
    (an approval waiting, a tool that raised, a run cancelled in a tool) first answers
    that call by a state update, as withdrawn or as not finished, so a provider that
    checks the history never sees a call with no answer.
  - The stream becomes run events: the reply as chunks (the last one marked), tool
    activity (`running`, `done`, `failed`; arguments and results only for
    `expose_tools`), `reasoning` (opt-in), cumulative `usage` read from the
    checkpoint, and file blocks as artifacts.
  - `tool_from_langchain` and `tools_from_langchain` turn LangChain tools into
    `ToolSpec`s; a tool that takes an injected argument is refused. A call runs the
    tool only with the keys its schema declares, checked as the tool will receive them.
  - Activity of a tool that a sync node runs on a worker thread is seen while the node
    goes on, and a run no longer hangs in asyncio debug mode.
- `PauseLost` in `ext_r2c.core`: a checkpoint source raises it in `resume` when it
  holds no stopping point for the answer; the driver ends the run `lost`.
- The shared `AgentSource` suite runs on a real graph, and its sequence checks are
  structural (an `Ask` is last, one request at a time) so a real source can pass them.
- A race in the core's `Driver` is fixed (found on Python 3.11 by the bridge): the run
  pump read the run's pending ask to decide it was done, so an answer delivered while
  the source was still ending its stream could be lost. The pump now keeps its own
  `asked` flag.
- `ext_r2c.Remote`, the one adapter on the remote side (needs no extra of its own; a door
  loads only when exposed): `Remote(expose=["a2a", "mcp"], agent=..., tools=[...], ...)`
  wraps an existing remote and `.app()` returns one ASGI app that serves it over A2A, MCP or
  both, with `A2AOptions`, `MCPOptions` and `RemoteError` beside it. The remote's own logic
  does not change.
  - What goes through which door: an `AgentSource` (such as `LangGraphAgent`) or a hand-written
    a2a-sdk executor on A2A (an executor is served as it is, and never over MCP); `tools=`,
    `approve=`, `skills=`, `resources=` and `prompts=` on MCP; `mcp_tool=True` serves the agent
    as one MCP tool. The agent card says the owner's `url` and one `CardInfo` names both doors.
  - Settings are checked when `Remote(...)` is built, and `app()` builds the app once: one
    `RemoteError` lists every problem (a door with nothing to serve, something no door serves,
    a tool name used twice or the agent tool's own name, an option key that `Remote` owns, an
    `approve` name that is not a plain tool of the MCP door, an approval nobody can answer); a
    missing extra is an `ImportError` that names `ext-r2c[<extra>]`.
  - The owner's own `middleware=` goes outermost, around both doors, and authentication there
    sets the owner of a call. One lifespan starts and stops both doors, in order.
  - A door left on its in-memory defaults gives a `UserWarning` at the `Remote(...)` line, once
    per cause: the A2A task store, the MCP request-state keys when something can pause, and an
    MCP door behind a middleware with nothing that names the owner of a call.
  - One agent through both doors in one process, with a thread per owner and context for each
    door; success criteria 1 to 5 of the design brief hold through `Remote`, a restart included
    (durable checkpointer, task store and request-state keys).
  - No `mcp_server=` and no `Skills(...)` class (`skills=` takes folders or a ready
    `SkillsExtension`), and `url=` is required when A2A is exposed: the ADR
    [one remote, two doors](docs/design-docs/one-remote-two-doors.md) has the reasons.
- `python/README.md` has a `Remote` section (a runnable example, what goes through which door,
  the warnings, running the app under a prefix) and the single-extra scripts check a `Remote`.

### Changed

- Size limits (`R2C-SAFETY-4`) are in MiB (2^20 bytes): 5 MiB inside a message,
  50 MiB for a file by `url`.
- `R2C-QUESTION-5`: a field with `required: true` must also be not empty
  (`minLength: 1` on `text`, `minItems: 1` on `many`).
- `R2C-MCP-2` and `R2C-MCP-3` spell out the flat forms: titles and descriptions,
  the `required` list, how `<key>_other` merges (`many` adds it once), what a
  flat `args_schema` is, and how edited `args` are rebuilt.
- Extras: `[langchain]` is now `[langgraph]` (`langchain>=1.3`, `langgraph`),
  and no longer pulls `[a2a]`.
- `[langgraph]` names the bounds the bridge's tests prove: `langchain>=1.4.6,<2`,
  `langchain-core>=1.6.10,<2` and `langgraph>=1.2.14,<2` (the first `langgraph` past
  an advisory). It brings no checkpointer: the owner brings theirs.
- `R2C-ANSWER-6`: the remote takes `answered_by.role` as given and need not
  refuse an answer for it; `R2C-ANSWER-4` and `R2C-ANSWER-5` are enforced by
  the client.
- `R2C-ID-2`: over A2A a second task is opened and ended in
  `TASK_STATE_REJECTED`, naming the unfinished task; another owner's task does
  not count.
- `R2C-ACTIVITY-2`: an update may change an activity's `label`.
- `R2C-A2A-4`: a usage may travel in any status message, at most one per
  message, beside a request or an activity.
- §11 (A2A binding): an SDK may leave out `required: false` in an agent card;
  absent means the same.
- `R2C-MCP-1`: a remote sends one `inputRequests` entry per round, and a client
  accepts several. The elicitation `message` is the title (with
  `<origin.name> asks: ` when forwarded), the description, and one line per
  error on a re-ask.
- `R2C-ASK-5`: over MCP the refusal is the first line of the next result (the
  elicitation `message` when the request is asked again, otherwise the text),
  and a retry with no response for the pending key is asked again with it.
- `R2C-MCP-6`: `progress` counts up from 1 for each request, with no `total`.
- `R2C-MCP-7`: an inline image or audio is an `image` or `audio` block; other
  inline bytes are an embedded `resource`.
- `R2C-MCP-8`: usage may also sit in an input-required result, beside
  `input_requests`.
- Corrected MCP examples: the messages of `elicitation-approval.json` and
  `elicitation-approval-edit-dropped.json` now follow the message rule; the
  form in `not-activated.json` has its `description`; the reply block of
  `progress-activity.json` has `response: true`; `tool-result.json` names its
  embedded resource `urn:r2c:artifact:<id>`.

### Fixed

- The lifespan of `a2a_app` closes its request handler in a `finally`. Before, an exception
  thrown into the lifespan left the handler open; `Remote` meets that when the second door fails
  to start.
