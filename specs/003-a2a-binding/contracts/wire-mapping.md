# Contract: run events ⇄ A2A wire

What the door writes for each run event, and what it reads back. The standard's rules are in
`standard/v1/README.md` §3 and §11; this table is how `ext_r2c.a2a` meets them. "R2C Part"
means a Part with `data` = the R2C object and `metadata` = `{"<uri>": {}}` (R2C-CORE-1).

## Remote → caller

| Run event | Active (R2C URI requested) | Not active |
|---|---|---|
| (new task) | `Task` (submitted), with the client's message in history | same |
| `ActivityEvent` | working status: text Part = `fallback_text(activity)`, then the activity R2C Part (one per status, R2C-A2A-3) | working status: the text Part only; a `reasoning` activity is dropped (R2C-ACT-3) |
| `ReplyChunk` | artifact update on artifact id `reply`: one text Part, metadata `{"<uri>": {"kind": "artifact", "presentation": "inline", "response": true}}`; `append` false on the first chunk, true after; `lastChunk` = `chunk.last` | the text is gathered and sent at the head of the next status message's text |
| `ArtifactEvent` | artifact update: the parts as A2A Parts (`TextContent` → `text`, `BytesContent` → `raw` + `mediaType` + `filename`, `UrlContent` → `url` + `mediaType` + `filename`), metadata `{"<uri>": to_json(meta)}`; `lastChunk` true; the same id again replaces it (`append` false) | the same update without the R2C metadata |
| `UsageEvent` | held; replaces the held usage (R2C-USAGE-2) | dropped |
| `Ask` | input-required status: text Part = [refusal note] + [gathered reply] + `fallback_text(request)`, then the request R2C Part, then the held usage R2C Part if any | input-required status: the text Part only |
| `Done` | completed status: text Part (`Done.`, after any refusal note), then the held usage R2C Part if any | completed status: text Part = the gathered reply, or `Done.` |
| `Error("failed" / "lost" / "protocol")` | failed status: text Part = the reason, then the held usage | failed status: the reason |
| `Error("cancelled")` | canceled status: text Part, then the held usage | canceled status: the text |
| (second unfinished task in the context, R10) | `Task`, then rejected status: text Part naming the unfinished task | same |

- **Content over 5 MiB** (`check_size` with the door's `Limits`): the run is cancelled and the
  task ends failed with a reason naming the size (R2C-SAFETY-4).
- **An `ArtifactEvent` whose meta is `live` or `file` with a `url`:** sent as given; the door
  never fetches it.

## Caller → remote, at input-required

| Message content | Active | Not active |
|---|---|---|
| R2C answer Part(s) | routed by research R7 | routed by research R7 (a client may send an answer Part without the header; the door reads it) |
| text only | refused in text (no answer for the pending request) | research R9: taken as the answer when the form allows, else asked again in text |
| nothing usable | refused in text | asked again in text |

A re-ask is the same request, the same `id`, with `errors`, sent in a new input-required status
with its fallback text (which lists the errors first). A refusal is an input-required status
with only a text Part; the request stays pending (R2).

## Answer message from the client (R2C-A2A-2)

`R2CClient.answer(...)` sends:

```
message: role ROLE_USER, taskId, contextId,
  parts: [ {text: answer_text(answer, request)},
           {data: to_json(answer), metadata: {"<uri>": {}}} ]
```

`answer_text` gives the following:
- question: `"<header>: <value>"` per answered field, in form order, joined by `"; "`. A list
  is joined by `", "`, a bool is `yes` or `no`, and an integral number has no `.0`;
- approval: `"Allow"`, `"Deny"`, `"Deny: <reason>"` or `"Edited: <args as JSON>"`;
- declined: `"Declined"`.
