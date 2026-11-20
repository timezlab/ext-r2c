# Contract: the A2A example replay

Every file in `standard/v1/examples/a2a/` is played as a real in-process round trip: a real
a2a-sdk client talks to a real a2a-sdk server through the streaming test transport (research
R14). There are two modes, and the test ids are `client:<file>` and `door:<file>:<pause>`.

## Client mode (every file)

1. A **wire executor**, an a2a-sdk executor written for the test, emits the file's remote steps
   as they are. Ids are the file's, except where a2a-sdk issues them.
2. The **door's client** (`R2CClient`) runs the file's client steps:
   - each `SendMessageRequest` with an answer Part is rebuilt from the answer through
     `R2CClient.answer`;
   - `SubscribeToTaskRequest` → `reattach`;
   - `GetTaskRequest` → `get_task`.
3. **Passes when:**
   - every message the client sends equals the file's client step after normalising;
   - every R2C object in the remote steps comes out as exactly one typed item, equal to the
     object;
   - unknown kinds are skipped and counted.

## Door mode (every file except the exemptions)

1. **Converter.** The file's remote steps become a **scripted source**:
   - activity Parts → `ActivityEvent`;
   - the first occurrence of each request `id` → `Ask`;
   - `response` artifact chunks → `ReplyChunk(text, last)`;
   - other artifacts → `ArtifactEvent`;
   - usage Parts → `UsageEvent` (only the last before each status);
   - completed → end; failed → raise.
   - Steps the door makes itself are skipped: a re-ask (a request `id` seen before), a text-only
     input-required status after a client step (a refusal), and the `Task` event.
2. **Pause styles.** The scripted source runs once as `checkpoint` and once as `live`.
3. **Driving the run:**
   - The harness sends the file's client steps.
   - When the file starts with a remote step, it first sends a message `"Start."`.
   - When a request is followed by a remote step with no client step between, it sends a valid
     answer made by the test (the first option, a sample text).
   - The door's clock is set to the timestamp of the first remote step after the client's
     answer, or to the file's first timestamp.
4. **Passes when:** the remote events on the wire, minus a leading `Task` event the file does not
   show, equal the file's remote steps after normalising, in order.

## Normalising (both modes)

- Ids that a2a-sdk or the door issues (`id`, `taskId`, `contextId` of a new task, `messageId`,
  `artifactId` of the reply) are mapped to the file's on first sight. After that they must stay
  consistent.
- `timestamp` is dropped.
- A field at its protobuf default (`false`, `0`, `""`, empty list) equals an absent field.
- A float with no fractional part equals the int.
- A text Part is compared for presence and position only, never for its words. Every message that
  carries a request or an activity must have one (R2C-CORE-4).
- Headers: `A2A-Extensions` on a remote step must be echoed; on a client step it must be sent.

## Exemptions from door mode

The list is a constant in the test. A test fails when the converter accepts an exempt file or
rejects a file that is not exempt.

| File | Reason |
|---|---|
| `agent-card.json` | not a flow: `agent_card(...)` from the file's `CardInfo` must equal the file (card mode) |
| `unknown-kind-ignored.json` | a source cannot emit an unknown kind; the file tests the client |
| `artifact-no-metadata.json` | a data Part and no R2C metadata; no run event makes it; the file tests the client |

## Special flows

- **`question-forwarded.json`:** two in-process remotes. The second serves a scripted source that
  asks `q-inv-1`. The front remote's source calls it through `R2CClient` and forwards the
  request with `origin`. It then passes the caller's answer back. Both wires are compared.
- **`resubscribe.json`:** the harness cuts the first stream after the event before the file's
  first step, then reattaches and calls `get_task`.
- **`follow-up-context.json`:** the first task is completed by a scripted run, then the file's
  follow-up message opens the second task.
- **The new examples from FR-030** (a rejected second task; a usage beside an activity whose label
  changes) are played like any other file.
