# Research: R2C standard, version 1

**Feature**: [spec.md](spec.md) · **Date**: 2026-11-20

Every finding below was checked against installed packages in a scratch environment
(Python 3.11): `a2a-sdk 1.3.1`, `mcp 2.3.0` (wire types in `mcp-types 2.3.0`), `jsonschema
4.26.0`, `protobuf 7.36.2`, `pydantic 2.14.4`, `hatchling` through `uv 0.12`. A prototype
script parsed hand-written A2A and MCP envelopes, including deliberately broken ones.

## R1. Checking A2A envelopes

- **Decision**: parse each A2A body with `google.protobuf.json_format.ParseDict(body,
  a2a_pb2.<Type>())`, then call `a2a.utils.proto_utils.validate_proto_required_fields(msg)`.
  Types used by the examples: `AgentCard`, `SendMessageRequest`, `StreamResponse`,
  `SendMessageResponse`, `Task`, `GetTaskRequest`, `SubscribeToTaskRequest`.
- **Rationale**: `ParseDict` is strict by default: a misspelled field (`messsage`) and a wrong
  enum value (`INPUT_REQUIRED` instead of `TASK_STATE_INPUT_REQUIRED`) both raise `ParseError`.
  The required-field check (from `google.api.field_behavior`) catches what proto3 cannot, for
  example a `Message` without `messageId`, or an `AgentCard` with no `skills` ("Field must contain
  at least one element").
- **Wire spellings confirmed**: `statusUpdate`, `artifactUpdate`, `taskId`, `contextId`,
  `messageId`, `ROLE_AGENT` / `ROLE_USER`, `TASK_STATE_*`, `append`, `lastChunk`, `artifactId`;
  Part fields `text`, `raw`, `url`, `data`, `metadata`, `filename`, `mediaType`; card
  `supportedInterfaces[{url, protocolBinding, protocolVersion}]`,
  `capabilities.extensions[{uri, required}]`.
- **Alternatives**: the A2A JSON Schema published upstream (not shipped in the wheel; would pin
  another file); the a2a-sdk JSON-RPC server in process (that is spec 003's round trip).

## R2. Checking MCP envelopes

- **Decision**: use `mcp_types.methods`, which checks a body against the wire model of one
  `(method, protocol version)` pair, always with version `2026-07-28`:
  - client requests: `parse_client_request(method, version, params)`;
  - server results: `serialize_server_result(method, version, result)`;
  - server notifications: `parse_server_notification(method, version, params)`;
  - JSON-RPC framing: `mcp_types.jsonrpc` (`JSONRPCRequest`, `JSONRPCResponse`,
    `JSONRPCNotification`).
  The per-version wire models use `extra="ignore"`, so on their own they do not catch a
  misspelled field. The check therefore also **diffs** the input against the serialized
  surface. Any key the surface dropped is an unknown field, and the check fails on it. Keys under
  an `_meta` object are exempt, because `_meta` objects are open (`extra="allow"`).
- **Rationale**: the prototype caught a misspelled `inputRequest`, a missing `resultType`, a
  `server/discover` result without `cacheScope` / `ttlMs`, and a `tools/call` request whose
  `_meta` lacks `io.modelcontextprotocol/clientCapabilities`. Every one of these was wrong in the
  white paper's illustrative MCP JSON.
- **`requestedSchema`**: the wire model types its `properties` loosely (`dict[str, Any]`). The
  check validates each property against `PrimitiveSchemaDefinition` of the 2026-07-28 module, so
  a nested or unsupported field type fails.
- **Alternatives**: the monolith models in `mcp.types` (superset of all versions,
  `extra="allow"`: too lenient); the MCP JSON Schema from the spec repository (not shipped).

## R3. Where the R2C object rides on MCP (deviation D1)

- **Finding**: in the 2026-07-28 wire, an elicitation's `ElicitRequestFormParams` has **no
  `_meta`** (`message`, `mode`, `requestedSchema` only). The 2025-11-25 version had one. A
  surface-validating peer drops an R2C object placed there. These do carry `_meta`:
  `InputRequiredResult`, `CallToolResult`, every content block (`text`, `resource_link`,
  `resource`), `ProgressNotificationParams`, and request params. `ElicitResult` does not.
- **Decision**: a `question` or `approval` asked over MCP travels in the **`InputRequiredResult`'s
  `_meta["io.github.timezlab/r2c"]`** as `{"input_requests": {"<key>": <R2C object>}}`. Here
  `<key>` is the key of the matching entry in `inputRequests`, and it SHOULD equal the R2C `id`.
  The elicitation itself stays plain MCP (message plus flat `requestedSchema`), so a client
  without R2C still works.
- **Alternatives**: keep it in the elicitation params (dropped on the 2026-07-28 wire); encode it
  inside `requestedSchema` (abuses the schema); send no R2C object on MCP (a policy could not
  match `subject`, and the client could not tell an approval from a question).

## R4. The answer on MCP (deviation D2)

- **Finding**: `ElicitResult` has only `action` and `content`.
- **Decision**: on MCP the R2C `answer` is **derived, never sent**:
  - `accept` maps to `answered`, and `content` gives `value`;
  - `decline` and `cancel` map to `declined`;
  - `answered_by` is always `person`.
  A policy answer cannot be expressed on MCP in v1. That is consistent with MCP's own rule that
  the user reviews every response. The examples show the retry request with `inputResponses` and
  state the derived `answer` in the example's description.
- **Alternatives**: an R2C answer in the retry request's `_meta`. Rejected for v1: it would let a
  client claim `policy` on a protocol that requires user review. It can be added later, because
  unknown fields are ignored.

## R5. Shipping the schemas in the wheel

- **Finding**: `uv build` builds the sdist first, then the wheel **from the unpacked sdist**.
  A static `force-include` of `../standard/v1/schema` works for the sdist. The wheel build then
  fails, because inside the unpacked sdist that path does not exist.
- **Decision**:
  - Add a ~15-line hatch build hook, `python/hatch_build.py`. It takes the first directory that
    exists among `<project>/../standard/v1/schema` (checkout) and `<project>/standard/v1/schema`
    (unpacked sdist), and force-includes it as `ext_r2c/schema/v1/`.
  - The sdist force-includes `../standard/v1/schema` as `standard/v1/schema` and lists
    `hatch_build.py`.
  - The hook fails the build when neither directory exists.
- **Verified**: the sdist carries `standard/v1/schema/*.json` and `hatch_build.py`. The wheel
  carries `ext_r2c/schema/v1/*.json`, and `cmp` reports them identical to the source.
- **Alternatives**: a copy kept inside `src/` (drifts, and FR-022 forbids it); a symlink
  (hatchling and Windows handle it badly); building the wheel only, without an sdist (CI and
  `uv build` build both).

## R6. JSON Schema validation

- **Decision**: draft 2020-12 through `jsonschema.Draft202012Validator`, with
  `check_schema` on every schema and `FormatChecker()` while validating.
  `jsonschema[format-nongpl]` is a test dependency, so that `date-time` (`expires_at`) is really
  checked.
- **Rationale**: without the format extra, `date-time` silently passes. With it, `"tomorrow"`
  fails. A `$ref` to a remote URL raises a referencing error and is never fetched, which matches
  FR-015 (self-contained) and the README's "no external `$ref`".
- **Schema `$id`**: `https://github.com/timezlab/ext-r2c/tree/main/standard/v1/schema/<file>`.
  It is a name only, never fetched.

## R7. Test-only dependencies

- **Decision**: `[dependency-groups] dev` gains `a2a-sdk>=1.3,<2`, `mcp>=2.3,<3` and
  `jsonschema[format-nongpl]>=4`. CI installs the wheel plus this group into the clean venv.
  `[project.dependencies]` and the extras are unchanged (FR-025). The rename of `[langchain]` to
  `[langgraph]` stays with spec 002.
- **Consequence for the smoke tests**: the test venv now has `a2a` and `mcp` installed, so "no
  extra needed" is proven differently. A subprocess imports `ext_r2c` and asserts that neither
  `a2a` nor `mcp` is in `sys.modules`.

## R8. Rule identifiers and coverage

- **Decision**: each rule in the README is one list item that opens with a tag line,
  `**R2C-<AREA>-<n>** · <LEVEL> · <party> · <wire|prose>[ · schema]` (grammar in
  [contracts/rule-format.md](contracts/rule-format.md)). The test parses these lines with one
  regular expression and checks four things:
  - every `wire` rule is cited by at least one valid example;
  - every `schema` rule is cited by at least one invalid example;
  - every cited identifier exists;
  - no identifier is defined twice.
- **Rationale**: this gives FR-002, FR-017, FR-019 and FR-020, and SC-002 and SC-003, with no
  separate manifest that could drift from the README.

## Deviations from the design brief

D1 (option A of three: `InputRequiredResult` `_meta`, elicitation `_meta`, no R2C object on
MCP) and the plan were approved by the maintainer on 2026-11-20.

| # | Brief said | Standard says | Why |
|---|---|---|---|
| D1 | `question` / `approval` on MCP: R2C object in the elicitation's `_meta[key]` | in the `InputRequiredResult`'s `_meta[key].input_requests[<key>]` | 2026-07-28 elicitation params have no `_meta` (R3) |
| D2 | MCP answer: elicitation result maps to `answer` | the same, stated as derived. No R2C answer object travels on MCP, so `answered_by: policy` cannot be expressed on MCP | `ElicitResult` has no `_meta`; MCP requires user review (R4) |
| D3 | White paper §7 illustrative MCP JSON | complete 2026-07-28 messages: `resultType`, request `_meta` with protocol version and client capabilities, `cacheScope` / `ttlMs` on discover | found by the envelope check (R2); the white paper is corrected in this feature |
| D4 | — | an A2A agent card in the examples lists at least one skill | a2a-sdk rejects a card with no skills (R1) |

## Outside review (SC-005, 2026-11-20)

A fresh-context reviewer read only `standard/v1/README.md` and `standard/v1/schema/`. For each of
the six kinds it stated the required fields (conditional ones included) and the placement on A2A
and on MCP, **with no error**. SC-005 is met.

The reviewer also listed unclear points. The ones the examples or the brief already answered are
now written into the README:
- the subject `type` is open;
- `approver_role` goes with `approver`;
- `kind` is required on an answer;
- how to check an approval's value;
- a declined approval counts as deny;
- a re-ask is not a reuse of its `id`;
- where a refusal travels;
- asking without activation;
- unique option labels;
- optional fields may be left out of the value;
- reasoning has no `state`;
- the reply chunks repeat the metadata and stay open across a pause;
- `live` on A2A versus MCP;
- message roles and part order;
- the shape of the client's `extensions` map.

The schema change is in `args_schema`'s description: the `$ref` duty is the client's
(R2C-SAFETY-7). The rest needs a decision. It is recorded here for the spec that owns it.

| # | Open point | Owner |
|---|---|---|
| O1 | New values of a closed enum (`decisions`, `presentation`, `state`, `outcome`, roles, field `type`): additive (old validators break) or breaking (needs v2)? **Decided 2026-11-20 (maintainer): breaking, needs v2; written as `R2C-VERSION-3`.** | maintainer, before v1 leaves draft |
| O2 | `requestedSchema` details: the `required` list when `other: true` and only `<key>_other` is filled; `many` + `<key>_other` (replace, add one item, or split); `required: true` on `text` accepting `""` and on `many` accepting `[]` **Decided in spec 002 (2026-11-20), now in README §5 and R2C-MCP-2: an `other: true` field is never in `required`; `many` adds `<key>_other` once; required means not empty.** | 002 (form → schema) |
| O3 | Approval over MCP: argument names that collide with `decision` / `reason`; rebuilding `args` from the flat `content`; `decisions: ["edit"]` with a non-flat `args_schema` **Decided in spec 002 (2026-11-20), now in R2C-MCP-3: such names make the schema not flat; left-out arguments keep their value; an approval left with no decision cannot be asked over MCP.** | 002, 004 |
| O4 | MCP: several entries in one `inputRequests` versus one pending request per task; what a "task" is across multi-round-trip calls (also for cumulative `usage`) | 004 |
| O5 | MCP: the elicitation `message` (text fallback); re-ask with `errors` and refusals on MCP; the numeric `progress` of an activity notification | 004 |
| O6 | MCP: `usage` on an `InputRequiredResult`, which already holds the `input_requests` wrapper in the same `_meta[key]` | 004 |
| O7 | MCP: content blocks other than text for `inline` (images) | 004 |
| O8 | A remote receiving an approval answer with `answered_by: caller`, or `policy` for `answer_by: approver`: reject or accept? A `policy` answer to a question: allowed? | 003 |
| O9 | How a remote refuses a second unfinished task in a context (R2C-ID-2): error or text | 003 |
| O10 | Whether an activity's `label` may change between updates; whether `usage` may share a message with a request or an activity | 003 |
| O11 | MB in R2C-SAFETY-4: 10^6 bytes or 2^20 **Decided 2026-11-20 (maintainer): 2^20, written as MiB.** | maintainer (minor) |
