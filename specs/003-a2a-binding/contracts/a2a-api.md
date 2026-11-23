# Contract: the public API of `ext_r2c.a2a`

Everything below is importable from `ext_r2c.a2a` with the `[a2a]` extra installed. Names not
listed are private. Types are in [../data-model.md](../data-model.md). The wire is in
[wire-mapping.md](wire-mapping.md).

## Modules

```
python/src/ext_r2c/a2a/
  __init__.py      re-exports the names below
  _codec.py        R2C objects ⇄ A2A Parts and Artifacts, Value number fix, reading a Task
  activation.py    R2CContextBuilder, EchoExtensions, is_active
  card.py          agent_card
  task.py          R2CTask (helpers for any executor)
  executor.py      SourceExecutor
  app.py           a2a_app
  client.py        R2CClient, the Item types, Link, TooLarge, answer_text
```

`ext_r2c.a2a` imports only `ext_r2c.core`, the standard library, and what `a2a-sdk[http-server]`
brings (`a2a`, `google.protobuf`, `httpx`, `starlette`). It never imports `ext_r2c.mcp` or a
bridge (constitution VIII).

## Serving

```python
def agent_card(info: CardInfo, url: str, *, streaming: bool = True,
               input_modes: Sequence[str] = ("text/plain",),
               output_modes: Sequence[str] = ("text/plain",)) -> AgentCard
    # capabilities.extensions = [AgentExtension(uri=URI, required=False, description=...)]

class SourceExecutor(AgentExecutor):
    def __init__(self, source: AgentSource, *, clock: Callable[[], datetime] | None = None,
                 limits: Limits = Limits()) -> None
    def bind(self, task_store: TaskStore, owner_resolver: OwnerResolver) -> None
        # a2a_app calls it, so the store and the resolver are the handler's; execute raises
        # RuntimeError when it was never called
    # execute / cancel per a2a-sdk

def a2a_app(executor: AgentExecutor, card: AgentCard, *, task_store: TaskStore | None = None,
            owner_resolver: OwnerResolver = resolve_user_scope, rpc_url: str = "/",
            middleware: Sequence[Middleware] = ()) -> Starlette
    # card route + JSON-RPC route + R2CContextBuilder + EchoExtensions; the same resolver for
    # the store (default InMemoryTaskStore(owner_resolver=...)) and the executor; `middleware`
    # goes outside (authentication there sets the owner); the handler is an R2CRequestHandler
    # at `app.state.request_handler`, closed on shutdown

class R2CRequestHandler(DefaultRequestHandlerV2):
    # refuses a client message whose role is not ROLE_USER (InvalidParamsError) before it is
    # stored; without activation, leaves R2C Parts and artifact metadata out of every task,
    # message and event it returns (send, stream, get, list, cancel, subscribe; R2C-ACT-3)
```

*Note (2026-11-20, outside review):* `R2CRequestHandler` was added. Without it, a client message
with the agent's role was stored as an agent message, so it could put a request of its own in
the history the door reads the pending request from. And a task paused while R2C was active
showed its R2C Parts to a caller that read it back without activation. An app that builds its
own handler uses `R2CRequestHandler`.

> **Note, 2026-11-23 (spec 007, A1).** The lifespan of `a2a_app` now closes the request handler in a
> `finally`: `try: yield` / `finally: await handler.aclose()`. Before, an exception thrown into the
> lifespan at its `yield` left the handler open; `AsyncExitStack` does that when a later lifespan
> fails to start, which `Remote` does under both doors. The clean stop is unchanged, `aclose` may run
> twice, and nothing else in the signature or on the wire changed. See
> [specs/007-remote/contracts/app-composition.md](../../007-remote/contracts/app-composition.md).

## Activation

```python
class R2CContextBuilder(DefaultServerCallContextBuilder): ...  # decides activation (R3)
class EchoExtensions:                                            # pure ASGI middleware
    def __init__(self, app: ASGIApp) -> None
def is_active(context: RequestContext | ServerCallContext) -> bool
```

## Helpers for any executor (story 6)

```python
class PendingMemory:                          # task id → request, for tasks without activation
    def __init__(self) -> None

class R2CTask:
    def __init__(self, context: RequestContext, queue: EventQueue, *,
                 memory: PendingMemory | None = None,
                 clock: Callable[[], datetime] | None = None, limits: Limits = Limits()) -> None
    active: bool
    task_id: str
    context_id: str
    pending: Question | Approval | None        # read from context.current_task (R2), else memory

    async def open(self, *, store: TaskStore | None = None,
                   owner_resolver: OwnerResolver = resolve_user_scope) -> bool
        # emits the Task when new; with a store, rejects a second unfinished task (R10) and
        # returns False
    async def activity(self, activity: Activity) -> None
    async def reply(self, text: str, *, last: bool = False) -> None
    async def artifact(self, event: ArtifactEvent) -> None   # a live artifact: last_chunk false
    async def usage(self, usage: Usage) -> None
        # held for the next activity, input-required or terminal status (R2C-A2A-4)
    async def ask(self, request: Question | Approval) -> None
    async def take_answer(self) -> Answer | None  # R7–R9; None = re-asked or refused already
    async def complete(self) -> None
    async def fail(self, reason: str) -> None
    async def reject(self, text: str) -> None
    async def cancelled(self) -> None

class ContentTooLarge(Exception):   # raised by reply / artifact over Limits.message_bytes,
    problem: Problem                # after the task has ended failed (R2C-SAFETY-4)
```

An executor written by hand:
1. keeps one `PendingMemory` and builds one `R2CTask` per `execute` call with it (without it,
   a caller that did not activate R2C cannot answer by text);
2. calls `open(store=..., owner_resolver=...)`. `a2a_app` binds only a `SourceExecutor`, so a
   hand-written executor that wants the R2C-ID-2 check gives the same store to `a2a_app` and to
   `open`. It is served by `a2a_app`, or by an app whose handler is an `R2CRequestHandler`:
   `R2CTask` reads the pending request from the task's agent messages, so a client message
   with the agent's role must never be stored;
3. on a message to a paused task, calls `take_answer()` and returns at once when it gives
   `None`;
4. otherwise goes on with the answer.

`SourceExecutor` does exactly this, driving a `Run` (FR-027).

## Caller side

```python
class R2CClient:
    @classmethod
    async def connect(cls, url: str, *, httpx_client: httpx.AsyncClient | None = None,
                      limits: Limits = Limits(),
                      clock: Callable[[], datetime] | None = None) -> R2CClient  # reads the card
    @classmethod
    def from_card(cls, card: AgentCard, *, httpx_client: httpx.AsyncClient,
                  limits: Limits = Limits(),
                  clock: Callable[[], datetime] | None = None) -> R2CClient
        # clock: the time `answer` checks `expires_at` against (default: now, UTC)
    active: bool                  # the last response echoed the R2C URI
    task_id: str | None
    context_id: str | None
    pending: Question | Approval | None
    skipped: int                  # unknown or invalid R2C Parts skipped

    def send(self, text: str, *, context_id: str | None = None,
             task_id: str | None = None) -> AsyncIterator[Item]
    def answer(self, answer: Answer) -> AsyncIterator[Item]
        # checks against `pending` with check_answer (caller_on_approval kept); raises
        # AnswerRejected(problems) before sending anything
    def reattach(self, task_id: str | None = None) -> AsyncIterator[Item]
        # SubscribeToTask; the first item is the TaskItem snapshot; ends at input-required or a
        # terminal state
    async def get_task(self, task_id: str | None = None) -> list[Item]
    async def cancel(self, task_id: str | None = None) -> StatusItem
    async def fetch(self, item: ArtifactItem) -> bytes | Link | TooLarge   # same-origin only
    async def aclose(self) -> None

Item = TaskItem | StatusItem | ActivityItem | RequestItem | UsageItem | ReplyItem | ArtifactItem
class AnswerRejected(ValueError):  problems: list[Problem]
def answer_text(answer: Answer, request: Question | Approval) -> str
```

`send`, `answer` and `reattach` always ask for R2C (the `A2A-Extensions` header). A remote that
does not echo it still works: the client then reads text and standard artifacts only.

- `connect` and `from_card` add a response hook to the httpx client, to see the echoed header
  of the JSON-RPC responses. `aclose` closes the httpx client only when `connect` made it.
- An `activity` whose `type` is not `tool`, `step` or `reasoning` is skipped and counted, like
  an unknown kind (R2C-CORE-6).
- `fetch` never follows a redirect, so a same-origin `url` cannot lead to another origin. It
  asks for no compression (`Accept-Encoding: identity`), so the limit counts the bytes as they
  arrive. A `live` artifact, or one guessed a `link`, comes back as a `Link`, never fetched.
- `answer` also refuses a `policy` answer to an approval with `answer_by.role = approver`
  (`policy_on_approver`, R2C-ANSWER-5); the door takes it as given, like `caller`.
- `get_task(other_id)` leaves `task_id`, `context_id` and `pending` alone; `aclose` removes
  the response hook. One `R2CClient` is one conversation: `active` is that of its last
  response.
- `ArtifactItem.presentation` is the metadata's presentation. Without R2C metadata the client
  guesses it (R2C-ARTIFACT-7): an html `url` → `link`; raw bytes, or a `url` with a filename →
  `file`; text or data → `inline`; anything else → `link`. `ArtifactItem.data` holds the data
  Parts as plain dicts.
- `Link(url, media_type, name)` and `TooLarge(size)` are frozen dataclasses; `size` is `None`
  when the remote did not declare a length.
