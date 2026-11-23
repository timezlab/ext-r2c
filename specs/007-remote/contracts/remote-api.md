# Contract: the public API of `Remote` (spec 007)

Status: built (2026-11-23); the dated note at the end says where the build differs from the text
below, which is kept as planned (FR-038). Four public names, all importable with no extra installed:

```python
from ext_r2c import Remote, RemoteError, A2AOptions, MCPOptions
```

They are exported lazily (`ext_r2c/__init__.py`, module `__getattr__`): `import ext_r2c` does not
load `ext_r2c.remote`.

## `Remote`

```python
class Remote:
    def __init__(
        self,
        *,
        expose: Sequence[Literal["a2a", "mcp"]],
        agent: AgentSource | AgentExecutor | None = None,
        card: CardInfo | None = None,
        url: str | None = None,
        tools: Sequence[ToolSpec | SourceTool | Callable[..., Any]] = (),
        approve: Sequence[str] | Mapping[str, Approve | bool] = (),
        skills: str | PathLike[str] | Sequence[str | PathLike[str]] | SkillsExtension | None = None,
        resources: Sequence[Resource] = (),
        prompts: Sequence[Prompt] = (),
        mcp_tool: bool = False,
        middleware: Sequence[Middleware] = (),
        a2a: A2AOptions | None = None,
        mcp: MCPOptions | None = None,
        limits: Limits = Limits(),
        clock: Callable[[], datetime] | None = None,
    ) -> None: ...

    def app(self) -> ASGIApp: ...
```

The annotations are shown with the SDK types for reading; in the source they sit under
`TYPE_CHECKING` or are `Any`, so the module imports no SDK.

### Arguments and the doors that serve them

| Argument | A2A door | MCP door | If its door is not exposed |
|---|---|---|---|
| `expose` | | | required; one or two of `"a2a"`, `"mcp"`, no repeats; no default |
| `agent` an `AgentSource` | the agent: card, runs, questions, approvals, artifacts | one tool, only with `mcp_tool=True` | with MCP only and no `mcp_tool`: `RemoteError` |
| `agent` an a2a-sdk executor | the agent | never | with MCP only: `RemoteError` |
| `card` | the card | the server's name, version and description | needed when the agent has no `card` |
| `url` | the card's address | not served | `RemoteError` if given with A2A not exposed |
| `tools` | not served | tools | `RemoteError` |
| `approve` | not served | an approval before a direct call | `RemoteError` |
| `skills` | not on the card | MCP skills | `RemoteError` |
| `resources`, `prompts` | not served | served as given | `RemoteError` |
| `mcp_tool` | not served | the agent tool | `RemoteError` |
| `middleware`, `limits`, `clock` | wraps / applies | wraps / applies | |
| `a2a` | its options | not served | `RemoteError` |
| `mcp` | not served | its options | `RemoteError` |

### Semantics

- **Keyword-only.** Every argument is a keyword.
- **`agent` and `card`.** The card information is `card` when given, else `agent.card` of a source.
  An executor or tools only have no card of their own, so `card` is required then, whichever door is
  exposed. The same `CardInfo` names the MCP server and its version.
- **`tools`.** `ToolSpec` and `SourceTool` are kept. A function or method is converted with the core's
  `tool_from_function` (its refusals pass through). Nothing else is accepted: the `TypeError` says a
  LangChain tool is converted in the owner's module with `tools_from_langchain(...)`.
- **`mcp_tool=True`** with an `AgentSource` serves the agent as one MCP tool, `SourceTool(agent)` with
  its defaults (name `agent`, input `{message, context_id?}`). A tool with another name or schema is a
  `SourceTool` the owner builds and passes in `tools=`. Without `mcp_tool` the agent is never an MCP tool.
- **`approve`.** A list of tool names, or `{name: Approve | bool}`. Every name is a tool the MCP door
  serves that is not a `SourceTool`; `answer_by` is `person` or `approver`. A direct MCP call to a
  named tool first asks an approval (spec 004). `Remote` never answers one and never reads the agent
  framework's own approval configuration. The agent's list and this one are separate, on purpose.
- **`skills`.** A folder, a list of folders, or a ready `SkillsExtension` (spec 005; include and exclude
  are its arguments). MCP only. A problem in the folders is the unchanged `SkillsError`, raised by `app()`.
- **`resources`, `prompts`.** The MCP SDK's own `Resource` and `Prompt` objects, served as given.
- **`middleware`.** Starlette `Middleware` objects wrapping both doors, outermost first, as in Starlette.
  It is the one place for authentication that both doors share (see identity, below).
- **`a2a`, `mcp`.** Door options (below). `None` is the default options.
- **`limits`, `clock`.** Passed to both doors (`SourceExecutor`, `R2CExtension`).

### `Remote.app()`

Returns one ASGI application. Callable once per `Remote`; a second call raises `RuntimeError`. It builds
every piece fresh, runs nothing, and starts nothing: the application's own lifespan starts and stops
both doors. See [app-composition.md](app-composition.md).

### Identity

`Remote` adds no authentication and no resolver. Each door reads its owner its own way:

| Door | Owner |
|---|---|
| A2A | `A2AOptions.owner_resolver`; by default the user an authentication middleware set on the request |
| MCP | the SDK's authenticated principal (`MCPOptions.server`'s `auth` / `token_verifier`), or `MCPOptions.owner(ctx)`, which may read `ctx.request.user` |

With `middleware=` given and MCP exposed with neither an `owner` nor SDK authentication, `Remote` warns
once that every MCP caller is one owner (D5, FR-029).

## `A2AOptions`

```python
@dataclass(frozen=True, kw_only=True)
class A2AOptions:
    task_store: TaskStore | None = None        # None: the SDK's in-memory store
    owner_resolver: OwnerResolver | None = None  # None: the SDK's default (the request's user)
    path: str = "/"                            # the JSON-RPC endpoint; the card route stays at the root
```

## `MCPOptions`

```python
@dataclass(frozen=True, kw_only=True)
class MCPOptions:
    path: str = "/mcp"                          # the streamable-HTTP endpoint, exactly this path
    security: RequestStateSecurity | None = None  # request-state keys; None: the SDK's ephemeral policy
    owner: Callable[[Any], str | None] | None = None  # R2CExtension's owner callable
    transport_security: TransportSecuritySettings | None = None  # host rules (the default guard is 127.0.0.1)
    server: Mapping[str, Any] = {}              # the rest of MCPServer's keyword arguments
    http: Mapping[str, Any] = {}                # the rest of streamable_http_app's keyword arguments
```

`Remote` owns these keys and refuses them in the mappings: in `server`: `name`, `description`,
`version`, `extensions`, `tools`, `resources`, `request_state_security`; in `http`:
`streamable_http_path`, `transport_security`. `MCPServer`'s own `middleware` keyword (the SDK's request
middleware) may be given in `server`; it is not the ASGI `middleware=` of `Remote`.

## `RemoteError`

```python
class RemoteError(ValueError):
    problems: tuple[str, ...]   # at least one; "<argument>: <what is wrong>; <what to do>"
```

One error lists every configuration problem found, so the owner fixes them in one pass. `str(error)`
begins `Remote cannot be built:` and lists one problem per line.

## Errors: every case

| Case | Raised | Names |
|---|---|---|
| a door exposed whose extra is missing | `ImportError`, before any other check | `ext-r2c[a2a]` or `ext-r2c[mcp]` |
| `expose` is not a list of strings (a bare string, a non-string item) | `TypeError` | `expose` |
| `agent`, a tool, an option, a `Middleware`, a resource or a prompt of the wrong type | `TypeError`, the first found | the argument |
| a callable the core refuses (`*args`, no type hints, a leading underscore) | the core's own error, unchanged | |
| `expose` missing, empty, unknown or repeated | `RemoteError` | `expose` |
| A2A exposed, no `agent` | `RemoteError` | `agent` |
| no card information (no `card`, no source `card`) | `RemoteError` | `card` |
| A2A exposed, no `url`; or `url` not an absolute `http(s)` address with a host and no query, fragment or user info | `RemoteError` | `url` (never its value) |
| MCP exposed, nothing to serve | `RemoteError` | `tools`, and what is enough |
| an agent no exposed door serves | `RemoteError` | `agent`, and `mcp_tool` where it applies |
| `mcp_tool=True` with an executor, or without an agent | `RemoteError` | `mcp_tool` |
| an argument given whose door is not exposed | `RemoteError` | each argument |
| `approve` names no tool, or the agent's tool, or a `SourceTool` | `RemoteError` | the name |
| an `approve` entry whose `answer_by` is not `person` or `approver` | `RemoteError` | the name |
| two tools with one name (the agent tool included) | `RemoteError` | the name |
| a path does not begin with `/`, is under `/.well-known/`, or the two paths collide | `RemoteError` | `a2a.path`, `mcp.path` |
| `MCPOptions.server` or `.http` names a key `Remote` owns | `RemoteError` | the key |
| a collision found in the built apps (a route the SDK added) | `RemoteError`, from `app()` | the path |
| a skills folder that fails the scan | `SkillsError`, unchanged, from `app()` | |
| a second `app()` | `RuntimeError` | |

Messages carry no secret, no absolute path of this host and no file content, and never echo an argument's
value (a tool name, a door name or a key the owner chose may appear).

## Warnings

`UserWarning`, at construction, only when the configuration is valid, with `stacklevel` at the owner's
`Remote(...)` line:

| When | Says |
|---|---|
| A2A exposed and `A2AOptions.task_store` is `None` | a restart loses a paused task; name `a2a.task_store` |
| MCP exposed, `MCPOptions.security` is `None`, and `approve` is not empty or a checkpoint-style `SourceTool` is served | a restart loses a paused call; name `mcp.security` |
| `middleware` given, MCP exposed, no `MCPOptions.owner` and no SDK authentication in `MCPOptions.server` | every MCP caller is one owner; name `mcp.owner` |

## What `Remote` does not do

No authentication or authorization, no route of its own, no CORS or logging middleware, no protocol
logic (FR-026). No `mcp_server=` argument (D3). No `Skills(...)` helper (D8). No `run()` or command line:
the README shows `uvicorn remote_module:app`. No edit, subclass or attribute set on anything it is given
(FR-005). No import of a bridge (FR-035).

> **Note, 2026-11-23 (built).** Where the build differs from the text above (the reasons are in
> `research.md` and in the phase notes of `tasks.md`; the text above is kept as planned):
> - `expose` missing is Python's own `TypeError` (the argument is keyword-only and has no default),
>   not a `RemoteError`. An empty, unknown or repeated `expose` is a `RemoteError` as written.
> - What the core refuses is not what the "callable the core refuses" row says. The installed core
>   refuses `*args`, `**kwargs`, positional-only parameters, a parameter whose name starts with an
>   underscore and type hints it cannot read; it accepts a function with no hints and one whose own name
>   starts with an underscore. `Remote` passes the core's error through unchanged.
> - The doors are read in starting order, A2A then MCP, whatever order `expose` lists them in. With both
>   extras missing one `ImportError` names both (`ext-r2c[a2a]` and `ext-r2c[mcp]`).
> - The MCP restart warning is given when some `approve` value is not `False` or a checkpoint
>   `SourceTool` is served; an `approve` mapping whose every value is `False` does not warn (narrower
>   than R11 read alone).
> - The `mcp.owner` warning reads an SDK authentication key (`auth`, `token_verifier`,
>   `auth_server_provider`) left as `None` as not set.
> - Each option class checks the types of its own fields, so a wrong type there is a `TypeError`
>   from the option class, before `Remote` reads it.
> - Problems are listed in the order of the checks, not sorted.
> - The skills settings are read by `check_skills`; there is no `normalise_skills`.
>
> **Note, 2026-11-23 (after the outside review, T078).** Changes to the text above, each with a test in
> `python/tests/test_remote_review.py` (the findings are in `research.md` R18):
> - `MCPOptions.owner(ctx)` is asked first: an owner it names wins over the SDK's authenticated
>   principal, and `None` leaves the principal (then `anonymous`). This is what spec 004's
>   `R2CExtension` already did; the table in Identity names the two sources, not the order.
> - `Remote` also owns `security` and `extension` in `server` (the keywords of `mcp_server` itself) and
>   `host` in `http` (a bind address given there turns the SDK's host guard off in silence; name the
>   hosts in `transport_security`). A problem reads `mcp.<field>: names <key>, a keyword Remote does not
>   take from here; <what to do>`.
> - A class given as `agent` is a `TypeError`. A `url` with a space or a control character, or with a
>   port that is not a number from 0 to 65535, is a problem of `url`.
> - A list of skill folders is copied into a tuple when `Remote(...)` is called, as `tools=` is held.
> - `RemoteError` can be pickled and copied.
> - Not built, proposed to the maintainer: a warning when the A2A door has no owner (no `middleware=` and
>   no `owner_resolver`), as D5 does for MCP. The README says it in a sentence instead.
