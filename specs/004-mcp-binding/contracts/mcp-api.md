# Contract: the public API of `ext_r2c.mcp`

Everything below can be imported from `ext_r2c.mcp` once the `[mcp]` extra is installed. Names
not listed here are private. Types are in [../data-model.md](../data-model.md), and the wire is
in [wire-mapping.md](wire-mapping.md).

## Modules

```
python/src/ext_r2c/mcp/
  __init__.py      re-exports the names below
  _codec.py        R2C ⇄ MCP: input-required results, the message, progress, content blocks,
                   mcp_response (an answer → an elicitation response), reading results
  _state.py        the stopping point (JSON in, JSON out), RoundLedger, MemoryLedger
  activation.py    is_active, form_supported, owner_of
  tools.py         Approve, serving ToolSpecs and approve= (the interceptor's tool half)
  source_tool.py   SourceTool: one AgentSource as one tool, across rounds
  extension.py     R2CExtension
  server.py        mcp_server
  client.py        R2CClient, the item types, Link, TooLarge
```

`ext_r2c.mcp` imports only `ext_r2c.core`, the standard library, and what `mcp` brings (`mcp`,
`mcp_types`, `anyio`, `httpx2`, `starlette`). It never imports `ext_r2c.a2a` or a bridge
(constitution VIII).

## Serving

```python
@dataclass(frozen=True)
class Approve:
    answer_by: Literal["person", "approver"] = "person"
    expires_in: timedelta | None = None        # sets expires_at from the door's clock
    title: str | None = None                    # default "Run <tool>"

class SourceTool:
    def __init__(self, source: AgentSource, *, name: str = "agent", title: str | None = None,
                 description: str | None = None, input_schema: dict[str, Any] | None = None,
                 to_input: Callable[[Mapping[str, Any]], tuple[RunInput, str | None]] | None = None
                 ) -> None
        # default input_schema {message: string (required), context_id: string}; default
        # to_input: (RunInput(text=message), context_id); description defaults to
        # source.card.description

class RoundLedger(Protocol):
    async def claim(self, nonce: str, until: float) -> bool   # True the first time only
class MemoryLedger(RoundLedger): ...

class R2CExtension(Extension):
    identifier = "io.github.timezlab/r2c"
    def __init__(self, *, tools: Sequence[ToolSpec | SourceTool] = (),
                 approve: Mapping[str, Approve | bool] = {},
                 clock: Callable[[], datetime] | None = None, limits: Limits = Limits(),
                 ledger: RoundLedger | None = None,
                 owner: Callable[[ServerRequestContext], str | None] | None = None) -> None
        # ValueError at construction: two tools with one name, or an approve= name that is a
        # SourceTool (a source asks its own approvals)
    def settings(self) -> dict[str, Any]          # {"revision": 1}
    def middleware(self) -> list[ServerMiddleware] # puts each ToolSpec's inputSchema in tools/list
    # tools() and intercept_tool_call() per the SDK

def mcp_server(name: str, extension: R2CExtension, *,
               security: RequestStateSecurity | None = None, **mcp_server_kwargs: Any) -> MCPServer
    # MCPServer(name, extensions=[extension], middleware=extension.middleware(),
    #           request_state_security=security, ...); without security, the SDK's ephemeral
    #           policy (a restart then invalidates every paused call)
```

- `approve=` may name a tool registered elsewhere on the same server. Such a tool gets `allow`
  and `deny` only (research R2). It must not ask through multi-round-trip results itself.
- A ToolSpec's call may return:
  - a `str` (one `text` block);
  - `ToolOutput(text=None, data=None, artifacts=(), usage=None)`, to return structured content,
    artifacts (core `ArtifactEvent`) and usage;
  - any other JSON value (as `structuredContent` plus its JSON as text).

```python
@dataclass(frozen=True)
class ToolOutput:
    text: str | None = None
    data: Any = None                            # structuredContent
    artifacts: tuple[ArtifactEvent, ...] = ()
    usage: Usage | None = None
```

## Activation helpers

```python
def is_active(ctx: ServerRequestContext) -> bool       # MCP_KEY in this request's extensions
def form_supported(ctx: ServerRequestContext) -> bool
def owner_of(ctx: ServerRequestContext) -> str          # authenticated principal or "anonymous"
```

## Caller side

```python
class R2CClient:
    @classmethod
    async def connect(cls, url: str, *, http_client: httpx2.AsyncClient | None = None,
                      limits: Limits = Limits(), clock: Callable[[], datetime] | None = None,
                      client_info: Implementation | None = None) -> R2CClient
        # streamable HTTP; checks that the negotiated version is 2026-07-28
    active: bool                                 # the server declared MCP_KEY
    pending: Mapping[str, RequestItem]           # by inputRequests key, empty when none
    context_id: str | None
    skipped: int

    def call(self, name: str, arguments: Mapping[str, Any] | None = None,
             *, progress: bool = True) -> AsyncIterator[Item]
        # one round; ends with RequestItem(s) or a ResultItem; raises RuntimeError while a call
        # is paused (answer or cancel it first)
    def answer(self, *answers: Answer) -> AsyncIterator[Item]
        # one Answer per pending R2C request, matched by id; checked with check_answer (role
        # problems kept); raises AnswerRejected(problems) before sending; refuses caller on an
        # approval and policy anywhere
    def respond(self, key: str, action: Literal["accept", "decline", "cancel"],
                content: Mapping[str, Any] | None = None) -> AsyncIterator[Item]
        # for a plain elicitation (no R2C object); content checked against requestedSchema
    async def cancel(self) -> None               # cancels the running round
    async def fetch(self, item: ArtifactItem) -> bytes | str | Link | TooLarge
    async def aclose(self) -> None

Item = ActivityItem | ProgressItem | RequestItem | UsageItem | ReplyItem | ArtifactItem | ResultItem
class AnswerRejected(ValueError):  problems: list[Problem]
def mcp_response(request: Question | Approval, answer: Answer) -> ElicitResult
    # the inverse of answer_from_mcp: declined → decline; a `one` value not among the options →
    # <key>_other; `many` values not among the options → joined into <key>_other
```

- When several requests are pending, `answer` and `respond` gather the responses. The next round
  is sent once every pending key has one; until then they yield nothing.
- `Link(uri, media_type, name)` and `TooLarge(size)` are frozen dataclasses.
