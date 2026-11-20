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
    # the store (default InMemoryTaskStore(owner_resolver=...)) and the executor
```

## Activation

```python
class R2CContextBuilder(DefaultServerCallContextBuilder): ...  # decides activation (R3)
class EchoExtensions:                                            # pure ASGI middleware
    def __init__(self, app: ASGIApp) -> None
def is_active(context: RequestContext | ServerCallContext) -> bool
```

## Helpers for any executor (story 6)

```python
class R2CTask:
    def __init__(self, context: RequestContext, queue: EventQueue, *,
                 clock: Callable[[], datetime] | None = None, limits: Limits = Limits()) -> None
    active: bool
    task_id: str
    context_id: str
    pending: Question | Approval | None        # read from context.current_task (R2)

    async def open(self, *, store: TaskStore | None = None,
                   owner_resolver: OwnerResolver = resolve_user_scope) -> bool
        # emits the Task when new; with a store, rejects a second unfinished task (R10) and
        # returns False
    async def activity(self, activity: Activity) -> None
    async def reply(self, text: str, *, last: bool = False) -> None
    async def artifact(self, event: ArtifactEvent) -> None
    async def usage(self, usage: Usage) -> None   # held for the next input-required / terminal
    async def ask(self, request: Question | Approval) -> None
    async def take_answer(self) -> Answer | None  # R7–R9; None = re-asked or refused already
    async def complete(self) -> None
    async def fail(self, reason: str) -> None
    async def reject(self, text: str) -> None
    async def cancelled(self) -> None
```

An executor written by hand:
1. builds one `R2CTask` per `execute` call;
2. calls `open()`;
3. on a message to a paused task, calls `take_answer()` and returns at once when it gives
   `None`;
4. otherwise goes on with the answer.

`SourceExecutor` does exactly this, driving a `Run` (FR-027).

## Caller side

```python
class R2CClient:
    @classmethod
    async def connect(cls, url: str, *, httpx_client: httpx.AsyncClient | None = None,
                      limits: Limits = Limits()) -> R2CClient     # reads the agent card
    @classmethod
    def from_card(cls, card: AgentCard, *, httpx_client: httpx.AsyncClient,
                  limits: Limits = Limits()) -> R2CClient
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
