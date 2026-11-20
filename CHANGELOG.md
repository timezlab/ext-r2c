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
