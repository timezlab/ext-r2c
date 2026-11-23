# Data model: `Remote` (spec 007)

`Remote` has no wire shape of its own and stores nothing durable (the standard is untouched). This
file lists what it holds in memory, what it derives, what it builds, and the states it goes through.
Public names and signatures are in [contracts/remote-api.md](contracts/remote-api.md); the app's
construction is in [contracts/app-composition.md](contracts/app-composition.md).

## 1. What a `Remote` holds (after `__init__` succeeds)

| Field | Type | Origin | Notes |
|---|---|---|---|
| `doors` | `tuple[str, ...]`, a subset of `("a2a", "mcp")` in the order given | `expose` | at least one, no repeats |
| `agent` | `AgentSource` or an executor, or `None` | `agent` | kind decided by shape (R4) |
| `card_info` | `CardInfo` or `None` | `card`, else `agent.card` for a source | `None` only when no door needs it (never: see problem 3) |
| `url` | `str` or `None` | `url` | required when A2A is exposed |
| `tools` | `dict[str, ToolSpec \| SourceTool]`, insertion ordered | `tools`, plus the agent tool when `mcp_tool` | names are unique; plain callables already converted |
| `agent_tool_name` | `str` or `None` | the `SourceTool` built for `mcp_tool` | read from the object, not written down |
| `approve` | `dict[str, Approve \| bool]` | `approve` | a name list is `{name: True}`; every key is a tool of `tools` that is not a `SourceTool` |
| `skills` | folder(s) or a `SkillsExtension` or `None` | `skills` | scanned only in `app()` |
| `resources`, `prompts` | `tuple` of the SDK's `Resource`, `Prompt` | same | served as given |
| `middleware` | `tuple[Middleware, ...]` | `middleware` | the ASGI middleware around both doors |
| `a2a`, `mcp` | `A2AOptions`, `MCPOptions` | same | defaults when `None` |
| `limits`, `clock` | `Limits`, `Callable[[], datetime] \| None` | same | passed to both doors |
| `_built` | `bool` | | set at entry of the first `app()` (R12) |

`Remote` sets no attribute on `agent`, a tool, a graph or any object it was given (FR-005); a test
snapshots them before and after `app()` and a served round trip.

## 2. The doors

| Door | Name in `expose` | Extra | Package loaded when exposed | SDK names that, when missing, mean "the extra is missing" |
|---|---|---|---|---|
| A2A | `"a2a"` | `ext-r2c[a2a]` | `ext_r2c.a2a` | `a2a` |
| MCP | `"mcp"` | `ext-r2c[mcp]` | `ext_r2c.mcp` | `mcp`, `yaml` |

## 3. Options (no SDK import at module level)

`A2AOptions` (frozen, keyword-only): `task_store=None`, `owner_resolver=None`, `path="/"`.

`MCPOptions` (frozen, keyword-only): `path="/mcp"`, `security=None`, `owner=None`,
`transport_security=None`, `server={}`, `http={}`.

Validation (collected problems, R7): `path` begins with `/` and is not under `/.well-known/`; the two
paths differ; `server` and `http` do not name a keyword `Remote` owns:

| Mapping | Refused keys |
|---|---|
| `MCPOptions.server` | `name`, `description`, `version`, `extensions`, `tools`, `resources`, `request_state_security` |
| `MCPOptions.http` | `streamable_http_path`, `transport_security` |

The default mappings are shared empty mappings that nothing mutates (`types.MappingProxyType({})`),
so a frozen dataclass has no mutable default.

## 4. `RemoteError` and a problem

`RemoteError(ValueError)`: `problems: tuple[str, ...]` (at least one). `str(error)` is
`"Remote cannot be built: <n> problem(s)\n- <problem 1>\n- <problem 2>..."`. One problem is
`"<argument>: <what is wrong>; <what to do>"`: it starts with the argument's name, or with a dotted
option name (`mcp.path`, `a2a.path`, `mcp.server`). A problem may name a tool, a door or a key the
owner chose; it never carries a value the owner typed (a URL, a path), a secret or a file content
(FR-033).

Other errors are not collected: `TypeError` (first found), `ImportError` (names the extra),
`SkillsError` (unchanged, from `app()`), `RuntimeError` (a second `app()`).

## 5. Derived values

| Value | Rule |
|---|---|
| card information | `card` if given, else `agent.card` for a source; else problem 3 |
| the card's JSON-RPC address | `url.rstrip("/") + a2a.path` (`https://remote.example.com/` by default) |
| MCP server name, version, description | `card_info.name`, `.version`, `.description` |
| the agent is served on A2A | when A2A is exposed (a source or an executor) |
| the agent is served on MCP | only when `mcp_tool` and the agent is a source |
| a door is "unserved" | it is exposed but has nothing to serve (A2A: no agent; MCP: no tool, agent tool, skills, resource or prompt) |
| an argument is "unserved" | it is given, and the door that serves it is not exposed (FR-019) |
| "MCP can pause" (D13) | `approve` is not empty, or a `SourceTool` in `tools` has `source.pause == "checkpoint"` |
| "MCP has an owner source" (D5) | `mcp.owner` is set, or `mcp.server` has one of `auth`, `token_verifier`, `auth_server_provider` |

## 6. What `app()` builds, per door (fresh each time; nothing is cached on the `Remote` but the flag)

A2A, when exposed:
`executor` (`SourceExecutor(agent, clock, limits)` for a source; the given executor as it is) →
`card = agent_card(card_info, address)` → `a2a_app(executor, card, task_store?, owner_resolver?,
rpc_url=a2a.path)`. `task_store` and `owner_resolver` are passed only when set, so the SDK's defaults
stay the SDK's.

MCP, when exposed:
`extension = R2CExtension(tools, approve, clock, limits, owner)` → `skills = SkillsExtension(...)` or
the given one, when `skills` → `server = mcp_server(card_info.name, extension, security=mcp.security,
extensions=[skills]?, version=, description=, **mcp.server)` → `add_resource` and `add_prompt` per
object → `mcp_app = server.streamable_http_app(streamable_http_path=mcp.path,
transport_security=mcp.transport_security, **mcp.http)`.

Both: `Dispatch(a2a_app?, mcp_app?)` → the parent `Starlette(routes=[Mount("/", Dispatch)],
middleware=list(middleware), lifespan=both)`. After both apps exist, the dynamic collision test runs
(R10).

## 7. Threads and owners (no new rule; the table of what `Remote` composes)

| Door | Owner is read from | Thread id |
|---|---|---|
| A2A | `A2AOptions.owner_resolver` (default: the user an authentication middleware set) | `thread_id("a2a", owner, context_id)` |
| MCP | the SDK's authenticated principal, or `MCPOptions.owner(ctx)` | `thread_id("mcp", owner, context_id)` |

One source object feeds both doors, each through its own `Driver`; the two thread ids differ by door
(FR-009, FR-030). Nothing in `Remote` maps one onto the other.

## 8. States

`Remote`:

```text
configured --app()--> built      (the flag is set at entry, also when app() then fails)
configured --app() fails--> built (unusable; construct a new Remote)
built --app()--> RuntimeError
```

The app (the parent Starlette), by its lifespan:

```text
stopped -> A2A starting -> A2A up -> MCP starting -> serving
                                  \-> MCP start fails -> unwind: A2A closed -> stopped (the error propagates)
serving -> stop -> MCP stopped -> A2A stopped -> stopped
```

A door that is not exposed is skipped. With the A1 fix, "A2A closed" also happens when the lifespan
is left by an exception.

## 9. Check order (R6) and warnings (R11)

1. read `expose` (TypeError for a bad type);
2. load exposed doors (ImportError naming the extra(s));
3. type checks (TypeError, first found);
4. collected problems (one `RemoteError`);
5. warnings (D13 once per door, D5 once), only when 1 to 4 passed.

## 10. Limits that apply

`Limits(message_bytes=5 MiB, file_bytes=50 MiB)` is the one `limits` the owner gives, passed to
`SourceExecutor` and `R2CExtension`. `Remote` adds no other bound: sessions, request bodies and the
idle time of the MCP transport are the SDK's own settings, reached through `MCPOptions.http`.
