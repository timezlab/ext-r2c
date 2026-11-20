# Contract: run events and approvals ⇄ the MCP wire

`key` is `io.github.timezlab/r2c`. "Active" means this round's client capabilities list the
key (research R5). Without activation, a row's `_meta` is left out and everything else stays
the same.

## Asking

| Door has | Wire |
|---|---|
| a `question` or `approval` to ask, form supported | `InputRequiredResult`: `inputRequests = {<id>: {"method": "elicitation/create", "params": {"mode": "form", "message": <R7 message>, "requestedSchema": mcp_form(request).requested_schema}}}`; `requestState` = the stopping point (sealed by the SDK); active: `_meta[key] = {"input_requests": {<id>: <request>}, "usage"?: <usage so far>}` |
| the same, form not supported | no wire: the door delivers `declined`; an `approve=` tool returns `Not run: approval could not be asked (the client does not support forms).`, `isError: true` |
| an approval `mcp_form` refuses (`NotAskableOverMcp`) | no wire: `declined` (O3) |
| a re-ask | the same, with the same key and `id`; the R2C object carries `errors`, and the message has one line per error |
| a refusal (missing response, late) | the next result: an input-required `message`, or the final result's first `text` block, starts with the refusal sentence (research R10) |

## While the run goes on

| Run event | Wire |
|---|---|
| `ActivityEvent`, request has a `progressToken` | `notifications/progress` on the request's stream: `{"progressToken": <token>, "progress": n (1, 2, …), "message": label}`; active: `_meta[key] = <activity>`; a reasoning activity only when active |
| `ActivityEvent`, no token | nothing |
| `ReplyChunk` | gathered; size-checked as a whole |
| `ArtifactEvent` | gathered for the final result |
| `UsageEvent` | kept (the latest); sent beside the next request and in the final result |

## The final result

| Door has | Content block (in this order) |
|---|---|
| refusal sentence (late answer) | `text`, no `_meta` |
| reply text | `text`; active: `_meta[key] = {"kind": "artifact", "presentation": "inline", "response": true}` |
| artifact `file`, `UrlContent` | `resource_link {uri, name, mimeType}` |
| artifact `file`, `BytesContent` | `resource {uri: url or urn:r2c:artifact:<id>, mimeType, blob}` |
| artifact `file`, `TextContent` | `resource {uri, mimeType, text}` |
| artifact `inline`, `TextContent` | `text` |
| artifact `inline`, `BytesContent` `image/*` / `audio/*` | `image` / `audio {data, mimeType}` (O7) |
| artifact `inline`, other bytes | `resource {uri, mimeType, blob}` (O7) |
| artifact `live` | `resource_link {uri, name, mimeType}` |

- Every artifact block, when active: `_meta[key] = <the artifact metadata>`.
- The result's `_meta[key]` holds `<usage>`, when active and known (R2C-MCP-8).
- `structuredContent`:
  - the default agent tool: `{"context_id": …}`;
  - a ToolSpec: `ToolOutput.data`, or a JSON return value.
- `isError: true` for:
  - a source `Error` (its reason as text);
  - a tool that raised;
  - `Not run: …`;
  - a busy context;
  - a lost run;
  - a claimed round;
  - content over the size limit.

## Retry (client → door)

| Client sends | Door derives |
|---|---|
| `inputResponses[<id>] = {"action": "accept", "content": {...}}` | `answer_from_mcp(request, "accept", content)`: `answered`, `answered_by.role = person` |
| `{"action": "decline"}` or `{"action": "cancel"}` | `declined` |
| no entry for `<id>` | the `missing` outcome |
| other keys | ignored |

The client sends the same tool name and arguments, and `requestState` as received. The SDK's
boundary refuses anything else with `-32602`.
