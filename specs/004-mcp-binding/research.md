# Research: MCP binding (`ext_r2c.mcp`)

Phase 0 of [plan.md](plan.md). Facts about the MCP Python SDK were read from the installed
`mcp-2.3.0` and `mcp_types-2.3.0` wheels on 2026-11-20 and checked with throwaway scripts (not
committed). Paths are inside the installed `mcp` package.

## R1. The extension and what it may contribute

- **Finding**: `Extension` (`server/extension.py`, SEP-2133) has `identifier`, `settings()`,
  `tools()`, `resources()`, `methods()` and `intercept_tool_call(params, ctx, call_next)`.
  - `MCPServer(name, extensions=[...])` applies them at construction. `settings()` appears at
    `capabilities.extensions[identifier]` in `server/discover`, checked.
  - An extension cannot be added to a server already built, except through private methods.
  - The lowlevel `Server` has no extension wiring.
  - `ToolBinding` tools go through `add_tool(fn, ...)`. The input schema is derived from `fn`'s
    signature, and there is no way to pass a JSON Schema.
  - Interceptors run inside `RequestStateBoundary`, so they see plaintext `requestState` and
    their own `requestState` is sealed. The first extension listed is the outermost.
- **Decision**:
  - `R2CExtension` is an `Extension` with the identifier `io.github.timezlab/r2c` and settings
    `{"revision": 1}`.
  - It serves its own tools (the `ToolSpec`s and the source tools) by name, in
    `intercept_tool_call`. It does not call `call_next` for them, so each one owns its
    `requestState`.
  - It contributes one `ToolBinding` per tool so the tool is listed, with the name, title and
    description.
  - The listed `inputSchema` is the `ToolSpec`'s schema. A server middleware from
    `R2CExtension.middleware()` puts it in the `tools/list` result.
  - `mcp_server(name, extension, ...)` builds the `MCPServer` with the extension, that
    middleware and the request-state policy, like `a2a_app` on the A2A side. An owner who builds
    the server by hand passes `extensions=[ext]` and `middleware=ext.middleware()`.
- **To verify first** (phase 1 spike): `tools/list` rewritten by the middleware, and a call to a
  bound tool short-circuited by the interceptor before the SDK validates its arguments. Fallback
  if the middleware cannot rewrite the list: give each binding a generated function whose
  pydantic model has the schema's top-level properties, and validate the full schema in the door.
- **Alternatives**:
  - lowlevel `Server` only: loses `MCPServer`'s boundary, tools and resources, which `Remote`
    (007) wants to pass through;
  - patching `_tool_manager`: private.

## R2. Approval of a tool call (`approve=`)

- **Finding**: an interceptor sees `params.name` and `params.arguments` for any tool on the
  server. `call_next(ctx)` runs the tool with the **original** params. A rewritten context changes
  what the handler sees on `ctx`, never the arguments. On the approved retry, the wrapped tool
  also sees the interceptor's `request_state` and `input_responses`.
- **Decision**:
  - `approve=` maps a tool name to `Approve(answer_by="person", expires_in=None)` (or `True` for
    the default).
  - **A tool of the door** (`ToolSpec`) offers `allow`, `edit` (when its input schema is flat,
    R2C-MCP-3) and `deny`. The door calls `ToolSpec.call` itself with the arguments, or the
    edited arguments after they pass the schema (the core's `InvalidArguments`).
  - **A tool registered elsewhere on the same server** offers `allow` and `deny` only. `edit`
    cannot be carried through `call_next`.
  - Such a tool that itself asks through multi-round-trip results (`Resolve`/`Elicit`) cannot be
    put behind `approve=`, because the two would share one `requestState`. This is documented,
    not detected.
  - The approval's `subject` is `{"type": "tool_call", "name": <tool>, "args": <arguments>,
    "args_schema": <listed input schema>}`. Its `id` is `ap-<8 hex>`, and its `title` is
    `Run <tool>`, or the `title` set in `Approve`.
  - A denied, declined or expired approval gives a complete result with `isError: true` and a
    text: `Not run: denied.`, plus ` Reason: <reason>` when one was given, or `Not run: the
    approval expired.` The model then does not mistake it for success.

## R3. `requestState`: what the door seals, and single use

- **Finding**: `RequestStateBoundary` seals every outgoing `requestState`. The envelope binds
  the method, the tool name, a digest of the arguments, a salted principal tag, the audience
  (the server name), `iat` and `exp`. Defaults: TTL 600 s, a process-local key, AES-256-GCM.
  - Every failure gets the same `-32602 "Invalid or expired requestState"`.
  - There is no size limit, apart from the 4 MiB HTTP body.
  - **A sealed state replayed with the same responses runs the tool again** until it expires;
    checked: a second retry ran the tool a second time.
- **Decision**:
  - The door mints the plaintext `requestState` as compact JSON, the **stopping point**
    ([data-model.md](data-model.md#stopping-point)). It holds:
    - `v`, `call` (the call id, kept across rounds), `round` (a fresh nonce per round), `kind`
      (`source` or `approve`);
    - the pending request as its R2C JSON;
    - for a source: `thread`, `context`, `pause`, the usage so far, and the output gathered
      before the ask (R6).
  - The door never seals, signs or encrypts it (R2C-MCP-5): that is the boundary's job.
  - **Single use**: a `RoundLedger` claims a round's nonce once, until the state's expiry. A
    second retry of the same round gets a tool error, `This request was already answered.`,
    and the tool does not run.
  - The default ledger is in memory. It is a small protocol (`claim(nonce, until) -> bool`), so
    a deployment with several processes can give a shared one.
  - After a restart with fixed keys, the in-memory ledger is empty, so a round can be replayed
    within its TTL. This is documented with the fix (a durable ledger).
- **Alternatives**:
  - trust the boundary alone: a replayed `allow` runs a payment twice;
  - keep the whole stopping point server side and put only an id in `requestState`: then every
    paused call depends on server memory, and a checkpoint source would no longer resume after
    a restart.

## R4. One run per tool call, across rounds

- **Finding**: each round is a separate `tools/call`, often on a separate HTTP request. The
  core's `Run` is an async iterator. A live source's run waits on an `await` in memory.
- **Decision**:
  - `SourceTool` keeps a map from call id to `Run` in memory, as the A2A door does per task.
  - Each round reads the run until an `Ask`, `Done` or `Error`. An `Ask` gives an input-required
    result; `Done` or `Error` gives the final result.
  - On the retry:
    - run held: `deliver` the answer;
    - not held and `pause == "checkpoint"`: `Driver.resume(thread, request, answer)`;
    - not held and `pause == "live"`: a tool error, `The paused run was lost (the server
      restarted); call the tool again.` (FR-018).
  - A held live run whose `requestState` expires gets `declined` from a timer task. The context
    is then freed.
  - A held checkpoint run past expiry is dropped from the map; its source keeps its own
    checkpoint.
  - The timer is the state's TTL plus 1 s, read from the server's `RequestStateSecurity`.

## R5. Activation, the form capability, and owners

- **Finding**:
  - `ctx.session.client_capabilities` gives the request's `ClientCapabilities`, with
    `.extensions` (a dict) and `.elicitation`. A bare `elicitation: {}` counts as form.
  - `ctx.meta` holds the request's `_meta`, with the token under the Python key
    `progress_token`.
  - `authenticated_principal(ctx)` is the string the boundary binds, or `None` without
    authentication.
- **Decision**:
  - **Active** means the key is in this round's `extensions`. It is decided per round, so a retry
    without the key gets no R2C `_meta`.
  - **Form**: `elicitation` is present and is not URL-only.
  - **Owner**: `authenticated_principal(ctx)`, or `anonymous` when it is `None`.
  - The owner function can be replaced (`owner=`), and the docs say it must match the
    boundary's principal.
  - Thread id: `thread_id("mcp", owner, context)`.
- **Without form support**:
  - a source's question or approval is answered `declined` at once by the door, and the run
    goes on;
  - an `approve=` tool is not run, and gets the result `Not run: approval could not be asked
    (the client does not support forms).`
  - Checked against the brief §8 (a headless turn gets `declined`).

## R6. What is gathered while the call runs

- **Finding**: an `InputRequiredResult` has no `content`. MCP returns content only in the final
  result.
- **Decision**:
  - Reply chunks and artifacts that come before an ask are carried to the final result. While
    the run is held, they stay in memory. They are also written into the stopping point, so a
    checkpoint source resumed after a restart still returns them.
  - Their encoded size counts against `Limits.message_bytes` (5 MiB). Over it, the call ends with
    a tool error naming the size (R2C-SAFETY-4, FR-014).
  - The same check applies to the gathered reply text at the end of any call.
  - On A2A, the reply of a client without R2C is gathered into the next status text (spec 003,
    R5). It gets the same whole-text check there (`ContentTooLarge`), which closes the follow-up
    left open by spec 003's outside review.
- **Alternatives**: drop pre-ask output (the person never sees what the agent said before
  asking); stream it as progress messages (progress `message` is for activity).

## R7. The elicitation `message` (O5)

- **Decision**: lines joined with `\n`:
  1. a refusal sentence, when the round refuses (R10);
  2. `[<origin.name> asks: ]<title>`;
  3. `<description>`, when present;
  4. one line per item of `errors`, on a re-ask.
  - This is the core's `fallback_text` without the field lines, which the form already shows.
    One helper in `_codec.py` builds it.
  - The two approval examples (`elicitation-approval.json`, `…-edit-dropped.json`) carry a
    message that adds words to the title. They are corrected to the rule.
- **Alternatives**:
  - the full fallback text: repeats every field in the message;
  - the title only: a re-ask would not say what was wrong to a client without R2C.

## R8. Activity as progress

- **Finding**: `ctx.report_progress` cannot carry `_meta`, and does nothing without a token. A
  `ProgressNotification` built by hand with `_meta` and sent with
  `ctx.session.send_notification(..., related_request_id=ctx.request_id)` arrives on the
  request's own stream, `_meta` intact (checked over the stream harness and over streamable
  HTTP).
- **Decision**:
  - The door builds the notification itself. `progress` counts 1, 2, 3, … per round, with no
    `total`. `message` is the activity's `label`.
  - `_meta[key]` is the activity, only when active.
  - With no token, nothing is sent. Reasoning activities are sent only when active.
  - Each round has its own token, chosen by the client.

## R9. Reply, artifacts and usage on the final result (O6, O7)

- **Decision** (the full table is in [contracts/wire-mapping.md](contracts/wire-mapping.md)):
  - **Reply**: the reply is the first `text` block, with `_meta[key] = {"kind": "artifact",
    "presentation": "inline", "response": true}` when active.
  - **`file`**:
    - `UrlContent` becomes a `resource_link` (`uri`, `name`, `mimeType`);
    - `BytesContent` becomes an embedded `resource` with a `blob`;
    - `TextContent` becomes an embedded `resource` with `text`.
    - An embedded resource without a url gets the uri `urn:r2c:artifact:<id>`.
  - **`inline`**:
    - `TextContent` becomes `text`;
    - `BytesContent` whose media type is `image/*` or `audio/*` becomes an `image` or `audio`
      block;
    - other bytes become an embedded `resource` with `blob` (O7).
  - **`live`**: a `resource_link`.
  - **Usage**: in the final result, `usage` is the whole of `_meta[key]` (R2C-MCP-8). In an
    input-required result, it is `_meta[key].usage`, beside `input_requests`, when the source
    has reported any (O6, Q2 A).
  - **Errors**: a source error is `isError: true`, with the reason as text and the last usage.
  - **Context**: the agent tool's default schema returns `structuredContent: {"context_id": …}`.
    A source tool with its own schema has no `context_id` input, so it returns none and each
    call is its own context.

## R10. Answers, re-asks and refusals on MCP (O4, O5)

- **Finding**:
  - The SDK rejects a malformed `inputResponses` entry (nested `content`, no `action`) with
    `-32602` before any extension code runs.
  - `ElicitResult` has `action`, `content` and `meta`.
- **Decision**, in this order on a retry:
  1. **Round already claimed** (R3): a tool error.
  2. **No entry for the pending key**: re-ask the same request, with the refusal sentence `No
     response was received for "<title>".` (R2C-ASK-5). Entries for other keys are ignored.
  3. **Expired** (`expires_at` before the door's clock):
     - a question counts as declined, an approval as deny;
     - the run goes on;
     - the final result, or the next input-required `message`, starts with `The response came
       too late; the request had expired.` (R2C-ASK-4, R2C-ASK-5).
  4. **Derive and check**: derive with `answer_from_mcp`, then check with `check_answer`,
     without the role problems, as in spec 003, FR-012.
     - On `too_large` or `invalid_*`, re-ask the same request (same key, same `id`) with
       `errors` (R2C-ASK-6).
     - `not_offered` cannot come from a form whose `oneOf` lists the offered decisions; if it
       does, it is re-asked the same way.
  5. **Hand over**: deliver the answer, or resume.
  - Every re-ask and refusal is a new round with a new nonce.
  - **One request per round** (O4): the door always sends exactly one entry. A tool call is the
    unit a task is on A2A, so R2C-ASK-3 holds per call. Usage is cumulative across its rounds.

## R11. One unfinished call per context (R2C-ID-2)

- **Decision**:
  - `SourceTool` keeps, in memory, `(owner, context) → (call id, expiry)`.
  - A new call (no `requestState`) on a held context gets a tool error: `This conversation has
    an unfinished call; answer it or wait until it expires.`
  - The entry is freed when the call completes, fails or expires. A retry of the held call
    passes.
  - Across several processes it is not shared (documented).
- **Alternatives**: a store protocol now (no second process to test it against; can be added).

## R12. The agent as a tool

- **Decision**: `SourceTool(source, *, name="agent", title=None, description=None,
  input_schema=None, to_input=None)`.
  - **Default** input schema: `{message: string (required), context_id: string}`. The default
    `to_input` gives `RunInput(text=message)` and the `context_id`. When `context_id` is absent,
    the door chooses one (a uuid4 hex) and returns it.
  - **Own schema and `to_input(arguments) -> (RunInput, context_id | None)`**: exposes an agent
    as a domain tool. The replay uses this, since the examples call `monthly_report(month)` and
    `reorder_low_stock()`.
  - `Remote` (007) passes the default for `mcp_tool=True`.
  - The description defaults to the source's `card.description`.

## R13. The caller's client

- **Finding**:
  - `mcp.client.Client` answers input-required results by itself, through callbacks, for up to
    10 rounds. `client.session.call_tool(name, args, meta=..., input_responses=...,
    request_state=..., allow_input_required=True)` returns the raw `InputRequiredResult` and
    sends `requestState` unchanged (checked byte for byte).
  - `advertise(key, {})` declares an extension.
  - Any `elicitation_callback` declares both `form` and `url`. There is no public way to declare
    form only.
  - `progress_callback` never sees `_meta`. `message_handler` gets every `ProgressNotification`
    with `params.meta`.
  - `mode="auto"` falls back to the legacy handshake on any discover error.
  - The client does not check `content` against `requestedSchema`.
  - Typed results keep `_meta` on the result and on content blocks, and `structuredContent`.
  - Cancel is the caller's cancel scope.
- **Decision**: `R2CClient` in `ext_r2c.mcp` wraps one `mcp.client.Client`:
  - **Capabilities**: `extensions=[advertise(MCP_KEY, {})]`, and an `elicitation_callback` that
    raises. It only declares the capability and must never run: the client drives the rounds
    itself.
  - It declares `url` too, unavoidably. A URL-mode elicitation from another server is yielded as
    a plain request item, answered with `respond`.
  - **Version**: after connecting, it checks that the negotiated version is `2026-07-28`, and
    fails otherwise. It reads `server_capabilities.extensions` for `active`.
  - **Rounds**: `call(name, arguments)` runs one round with its own progress token, routed by
    token from one `message_handler`. `answer(...)` and `respond(...)` run the next round with the
    same name and arguments and the unchanged `requestState`.
  - **Answers**: the client turns an R2C answer into the elicitation response with
    `mcp_response(request, answer)` in `_codec.py`, the inverse of `answer_from_mcp` (in the
    door's package, so the core does not change; it may move to core later).
  - It refuses an approval answered as `caller` and any answer by `policy` (R2C-ANSWER-4,
    R2C-MCP-4). It also refuses a `person` answer the core check rejects.
  - It validates plain-elicitation content against `requestedSchema` with `jsonschema`.
  - **Cancel**: `cancel()` cancels the running round's scope.

## R14. `fetch` on MCP

- **Decision**: `fetch(item)`:
  - a `resource_link` or embedded resource whose uri is not `http(s)` is read with
    `resources/read` on the same connection;
  - an `http(s)` uri on the connection's origin is fetched with the connection's `httpx2`
    client, no redirect followed, `Accept-Encoding: identity`, size-limited;
  - any other uri, and every `live` artifact, comes back as a `Link`;
  - an embedded resource is returned from its own bytes, size-limited (R2C-SAFETY-1, -5).

## R15. In-process transport for tests

- **Finding**:
  - The SDK speaks HTTP through `httpx2`, not `httpx`. `httpx2.ASGITransport` buffers a whole
    response, so progress arrives together with the result, and it never reports a disconnect.
  - In-process `Client(server)` uses a direct dispatcher: no headers, no `progressToken`.
  - Streamable HTTP needs `async with server.session_manager.run()` (no lifespan under a
    transport) and a `base_url` with a port (the DNS-rebinding guard).
- **Decision**:
  - `tests/mcp_transport.py`, about 70 lines: a streaming ASGI transport for `httpx2`. It runs
    the app in a task group, sends body chunks as they come, reports `http.disconnect` on close,
    and records every JSON-RPC message in both directions, which the replay compares.
  - `tests/mcp_harness.py`: build a server, a client per owner, and a scripted source.
- **Owners in tests**: the SDK's own bearer path (`AuthSettings` with a stub `TokenVerifier`
  that maps `Bearer <name>` to an `AccessToken` with that subject) is tried first in the phase 1
  spike. The fallback is a test ASGI middleware that sets `auth_context_var`.

## R16. The example replay

- **Decision**: as in spec 003. There are two modes, test ids `client:<file>` and
  `door:<file>:<pause>`, and a fixed exemption list checked both ways. Details are in
  [contracts/replay.md](contracts/replay.md).
  - The door side is played by a scripted `SourceTool` named and shaped like the file's tool, or
    by an `approve=` tool for a direct approval.
  - The client side is played by `R2CClient`.
  - Both are compared with the recorded JSON-RPC messages after normalising:
    - the sealed `requestState`, JSON-RPC ids and progress tokens are mapped;
    - SDK-added `_meta` keys (`io.modelcontextprotocol/*`) and discover's `cacheScope`/`ttlMs`
      are ignored.

## R17. Dependencies

- **Finding**: `mcp` 2.3.0 brings `httpx2`, `anyio`, `starlette`, `sse-starlette`, `uvicorn`,
  `pyjwt[crypto]` (thus `cryptography`), `opentelemetry-api`, `python-multipart` and
  `mcp-types`.
- **Decision**:
  - `[mcp]` becomes `mcp>=2.3,<3`, the same bound as the dev group.
  - `ext_r2c.mcp` may import `mcp`, `mcp_types`, `anyio`, `httpx2`, `starlette` and the standard
    library.
  - A CI step installs the wheel with `[mcp]` alone and runs `tests/mcp_only.py`.
