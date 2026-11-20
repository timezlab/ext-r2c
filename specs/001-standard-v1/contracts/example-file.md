# Contract: wire example files

Applies to every file under `standard/v1/examples/`. Any SDK may read these files; nothing in
them is specific to Python.

## Valid examples (`examples/a2a/*.json`, `examples/mcp/*.json`)

One JSON object per file. Names are kebab-case, with a binding prefix where it helps
(`a2a/approval-four-eyes.json`, `mcp/elicitation-question-other.json`).

```jsonc
{
  "title": "Four-eyes approval of a tool call",       // required, one line
  "description": "…",                                  // optional; derived answers on MCP are stated here
  "binding": "a2a",                                    // required: "a2a" | "mcp"; must match the folder
  "rules": ["R2C-APPROVAL-1", "R2C-APPROVAL-4"],       // required, ≥ 1, each must exist in the README
  "steps": [                                           // required, ≥ 1, in wire order
    {
      "from": "remote",                                // required: "remote" | "client"
      "type": "StreamResponse",                        // required; see the envelope types below
      "method": "tools/call",                          // MCP results only: the method being answered
      "headers": { "A2A-Extensions": "https://github.com/timezlab/ext-r2c/tree/main/standard/v1" },
                                                       // optional, A2A only; HTTP headers of this step
      "body": { … }                                    // required: the protocol message, exactly as sent
    }
  ]
}
```

### Envelope types

| Binding | `type` | `body` is | Checked with |
|---|---|---|---|
| a2a | `AgentCard`, `SendMessageRequest`, `SendMessageResponse`, `StreamResponse`, `Task`, `GetTaskRequest`, `SubscribeToTaskRequest` | the A2A 1.0 object in proto JSON (transport-neutral: no JSON-RPC wrapper) | `ParseDict` into `a2a_pb2.<type>` + `validate_proto_required_fields` |
| mcp | `request` | a JSON-RPC 2.0 request (`jsonrpc`, `id`, `method`, `params`) | `JSONRPCRequest`, then `parse_client_request(method, "2026-07-28", params)` |
| mcp | `result` | a JSON-RPC 2.0 response (`jsonrpc`, `id`, `result`) | `JSONRPCResponse`, then `serialize_server_result(step.method, "2026-07-28", result)` plus the dropped-key diff |
| mcp | `notification` | a JSON-RPC 2.0 notification (`jsonrpc`, `method`, `params`) | `JSONRPCNotification`, then `parse_server_notification(method, "2026-07-28", params)` |
| mcp | `discover` | a `server/discover` result (JSON-RPC response) | as `result` with `method = "server/discover"` |

For every MCP step, every key dropped by the surface model is an error, except keys inside an
`_meta` object. Every `requestedSchema` property must validate as a `PrimitiveSchemaDefinition`.

### Finding the R2C objects in a body

The check walks the whole body and validates each object found below against the schema of its
`kind`.

- **A2A, part form**: a Part whose `metadata` has the key URI with value `{}`, and whose `data`
  is an object with `kind`.
- **A2A, annotation form**: any object whose `metadata[URI]` is an object with `kind` (for
  example an `Artifact`).
- **MCP**: any `_meta["io.github.timezlab/r2c"]` value that has a `kind`. On an
  `InputRequiredResult`, it can instead be `{"input_requests": {"<key>": <object>}}`; each
  `<key>` must also be a key of `inputRequests`.
- **Unknown kind**: skipped and listed as ignored. It is not an error, and it is how the
  "ignore unknown" example passes.
- **Known kind with an unknown `activity.type`**: validated against the open `activity` schema.

### Pairing (question answers)

An `answer` whose `id` matches a `question` earlier in the same file is also checked against the
schema generated from that question's form. One matching an `approval` is checked against
`answer.json#/$defs/approval_value`, and `decision` must be one of the approval's `decisions`.

When the same request is sent again later in the file with `errors` (a re-ask), the answer
before it must **fail** this check instead: the re-ask has to be justified.

## Invalid examples (`examples/invalid/*.json`)

```jsonc
{
  "title": "Approval addressed to the caller agent",
  "rules": ["R2C-APPROVAL-2"],              // required, ≥ 1; each must be a rule marked "schema"
  "kind": "approval",                       // required: the schema to validate against
  "object": { … },                          // required: the R2C object itself, no envelope
  "fails_at": "/answer_by/role"             // required: JSON Pointer where validation must fail
}
```

The check expects validation to fail, and at least one error's instance path must equal
`fails_at`. An invalid example that passes, or that fails somewhere else, fails the check.

## Coverage

- Every file in `examples/` is read by the check; an unknown folder or extension fails it.
- Every `rules` entry exists in the README.
- Every README rule marked `wire` is cited by at least one valid example.
- Every README rule marked `schema` is cited by at least one invalid example.
- Data is invented; hosts are `example.com` or its subdomains; no real names (constitution VI).
