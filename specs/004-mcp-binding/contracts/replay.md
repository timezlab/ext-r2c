# Contract: the MCP example replay

Every file in `standard/v1/examples/mcp/` is played as a real in-process round trip: a real MCP
SDK client talks to a real `MCPServer` over streamable HTTP, through the recording streaming
transport (research R15). Test ids are `client:<file>` and `door:<file>:<pause>`, as on A2A.

## Client mode (every file)

1. **Wire server.** A lowlevel MCP `Server` written for the test answers each client step with
   the file's next remote steps, as they are: notifications first, then the result. Its
   `server/discover` result is the file's, when the file has one. Otherwise it declares the key
   when the file is activated.
2. **The door's client** (`R2CClient`) plays the file's client steps:
   - a first `tools/call` → `call(name, arguments)`;
   - a retry with `inputResponses` → `answer(<derived answer>)`, where the answer is the one the
     file's description names (`Derived answer: …`). A file with no derived answer is retried
     through `respond(key, action, content)`.
3. **Passes when:**
   - every request the client sends equals the file's client step after normalising;
   - every R2C object in the remote steps comes out as exactly one typed item, equal to the
     object;
   - plain elicitations come out as `RequestItem`s with `request = None`.

## Door mode (every file except the exemptions)

1. **Converter.** The file's remote steps become a scripted source behind a `SourceTool` with
   the file's tool name, a permissive input schema, and `to_input` = the arguments as JSON:
   - progress notifications with R2C `_meta` → `ActivityEvent` (without `_meta`: a step
     activity with the message as label);
   - an R2C request in `input_requests` (first sight of its `id`) → `Ask`;
   - without R2C `_meta` (`not-activated.json`), the request is rebuilt from the elicitation by
     the test: a question with the form's fields;
   - the final result's `text` block with `response: true` (or the only text block) →
     `ReplyChunk(text, last=True)`;
   - other blocks → `ArtifactEvent`;
   - usage → `UsageEvent` before the result it sits in.
2. **Pause styles.** The scripted source runs once as `checkpoint` and once as `live`.
3. **Driving.** The harness sends the file's client steps through a plain MCP SDK session, raw,
   with the file's `inputResponses`. The state is taken from the door's last result, not from the
   file.
4. **Passes when:** the messages the door sends, recorded on the wire, equal the file's remote
   steps after normalising, in order.

## Normalising (both modes)

- `requestState`: the file's placeholder is mapped to the sealed value on first sight. After
  that it must stay consistent. The door's must be a sealed token (it starts with `v1.`).
- JSON-RPC `id` and `progressToken` are mapped the same way.
- `_meta` keys under `io.modelcontextprotocol/` that the SDK adds (client info, server info) are
  dropped, as are discover's `cacheScope` and `ttlMs` when the file leaves them out.
- A float with no fractional part equals the int.
- `message` and `text` are compared exactly, now that the message rule is fixed (O5).
  `errors[].message` is compared for presence only.

## Exemptions from door mode

The list is a constant, checked both ways as on A2A.

| File | Reason |
|---|---|
| `discover.json` | not a tool call: `server/discover` of `mcp_server(...)` must equal the file (discover mode) |

## Files this spec adds (FR-023)

- `elicitation-two-rounds.json`: two questions one after the other in one tool call, with the
  usage so far beside the second (O4, O6).
- `elicitation-reask.json`: a response missing a required field, re-asked with `errors`; the
  message lists the error (O5).
- `elicitation-no-response.json`: a retry without an entry for the pending key, re-asked with
  the refusal sentence (O5).
- `tool-result-inline-image.json`: an inline image as an `image` block with its metadata (O7).
- `approval-tool-call.json`: a direct call to a tool behind `approve=`, denied with a reason,
  `Not run: …` with `isError: true`.

The two approval examples are corrected to the message rule (O5).

## As built (2026-11-20, phase 8)

- The derived answer is computed from the file's response with `answer_from_mcp`;
  `test_forms.py` pins that it equals the description's `Derived answer`.
- A retry the client will not send (no response for the pending key, or a response its check
  refuses) goes through the client's session as is, with the state the client holds.
- In client mode, `requestState` is named across the whole exchange, so an echo must equal what
  was received.
- Door mode maps the file's request keys to the door's, and the normaliser maps request ids: the
  door chooses an approval's id.
- Discover mode compares `capabilities.extensions` exactly. The file's other capabilities and the
  cache hints (`cacheScope` and `ttlMs`, which MCP requires) are compared for presence only.
- Three examples were corrected besides the two approvals; see tasks.md "Notes".
