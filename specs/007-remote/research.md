# Research: `Remote` (spec 007)

Facts below were checked on 2026-11-23 against the installed packages (`a2a-sdk` 1.3.1, `mcp` 2.3.0,
`starlette` 1.10.0, `httpx` 0.28.1 for A2A tests, `httpx2` 2.16.2 for MCP tests, `langchain` 1.5.2,
`langgraph` 1.2.24) with throwaway scripts that are not committed. Phase 1 of `tasks.md` turns
every fact the design leans on into a test, so a change in an SDK shows up as a failing test that
names the fact.

Each item has a **Decision**, the **Why**, and the **Alternatives** that were weighed. "Spec" means
[spec.md](spec.md); `D1`–`D13` and `FR-nnn` are its numbers.

## R1. One app from two door apps: a dispatcher inside a parent Starlette (D11)

**Facts.**
- The MCP app (`MCPServer.streamable_http_app()`) is a Starlette whose routes are the endpoint
  (`/mcp` by default) and, when the SDK's `auth` is set, the OAuth metadata routes under
  `/.well-known/`. The A2A app (`a2a_app`) serves the card at `/.well-known/agent-card.json` and the
  JSON-RPC endpoint at its `rpc_url` (default `/`).
- Each app carries its own middleware: A2A's echo of the activated extensions and, for MCP, the
  SDK's authentication. Lifting the routes of both apps into one parent drops that middleware. A
  probe of the MCP side showed the effect: no bearer check runs, so every caller is silently the
  anonymous owner.
- `Mount("/mcp", mcp_app)` answers `/mcp` with `404` (only `/mcp/` matches), and a mounted
  sub-app's lifespan never runs (spec finding 2).
- A small ASGI callable can ask the MCP app's own router whether a request is MCP's:
  `any(route.matches(scope)[0] != Match.NONE for route in mcp.router.routes)`. A probe with the
  real apps showed: `/mcp` is MCP's exactly (no redirect, no trailing slash); the card path, `/` and
  unknown paths are A2A's; with `auth` set, `/.well-known/oauth-protected-resource/mcp` is MCP's by
  the same test, with no path list written down.

> **Note, 2026-11-23 (phase 1, the spike).** Two details above were imprecise and are pinned as they
> are in `tests/test_remote_spike.py`; neither changes the decision. (1) `Mount("/mcp", mcp_app)` answers
> `POST /mcp` with a `307` to `/mcp/`, and `/mcp/` then answers `404`: a redirect and then nothing, not
> a `404` at once. (2) The MCP route has no method list, so every method on `/mcp` is a *full* match and
> the MCP app itself answers a wrong method; there is no partial match to speak of.

**Decision.** `app()` returns `Starlette(routes=[Mount("/", app=Dispatch(a2a, mcp))],
middleware=list(middleware), lifespan=both)`. `Dispatch` sends a request to the MCP app when the MCP
router matches it (full or partial: a `GET /mcp` gets MCP's own `405`), else to the A2A app. Each
sub-app stays whole, so its own middleware wraps it alone and the user's `middleware=` wraps both,
outside. With one door, the dispatcher holds one app and the other door's paths answer that app's
own `404`. One code path serves one door or two; the parent is also where the lifespans meet (R2).

**Reading of FR-020.** "A `Remote` with one door MUST serve exactly that door's app" is read as
"serves that door's routes and no route of the other door". The parent adds no route. Passing the
door's app through unwrapped would need `middleware=` applied two ways (A2A takes it as an argument,
MCP has no such argument and would need `add_middleware`), and two mechanisms for one setting is the
divergence this decision avoids. Flagged in the plan.

**Alternatives.**
- `Mount` the MCP app under `/mcp`: rejected, finding 2 (404 on `/mcp`, no lifespan).
- Lift both route lists into one Starlette: rejected, loses each app's middleware.
- A hard-coded list of MCP paths: rejected, misses the routes `auth` adds and breaks on the next SDK
  change; the router already knows.
- One server per door, run by the owner: that is today's two programs' worth of glue, the thing
  `Remote` exists to remove.

## R2. Start, stop and failure of the two doors (FR-022) and door change A1

**Facts.**
- The MCP app's lifespan runs the streamable-HTTP session manager, once per manager (a second run
  raises). The A2A app's lifespan is
  `yield` then `await handler.aclose()`, with no `try`/`finally` (`a2a/app.py`).
- A probe with the real A2A app: stopping it normally closes the handler; throwing an exception
  into its lifespan at the `yield` (what an enclosing `AsyncExitStack` does when a later lifespan
  fails to start, or the parent fails while serving) leaves the handler **open**. `aclose` called
  twice is harmless (idempotent).

**Decision.** The parent's lifespan is an `AsyncExitStack` that enters the A2A lifespan, then the MCP
lifespan, then yields; it unwinds in the reverse order. A door that is not exposed is not entered.
To make "a failure in one door's start stops the other" true (FR-022), `a2a_app`'s lifespan gets
`try: yield` / `finally: await handler.aclose()`.

**Door change A1** (the only change to a door; additive, behaviour of a clean stop unchanged):
test first in `tests/test_a2a_serve.py` (an exception thrown at the lifespan's `yield` still closes
the handler; fails today), then the two-line fix in `a2a/app.py`. The spec's Assumptions already
allow this ("if the plan finds a door needs an additive change ... it is listed in the plan and made
test first, as `PauseLost` was for 006").

**Alternatives.**
- Close the handler from `Remote` by reaching `app.state.request_handler`: rejected, it works around
  a bug in the door that every other user of `a2a_app` shares.
- Catch the failure in the parent and close by hand: same objection; and the parent would need to
  know which door had started.

## R3. Identity: what each door reads, and what `Remote` does about it (D5)

**Facts.** A2A's owner is its `OwnerResolver` (default `resolve_user_scope`: the user a Starlette
authentication middleware put on the request). MCP's owner is the SDK's authenticated principal, or
the `owner` callable of `R2CExtension`, which receives the request context. A probe with one outer
`AuthenticationMiddleware` wrapping the dispatcher: A2A sees `request.user`; the MCP extension's
`owner` callable sees the same `request.user` through `ctx.request.user`.

**Decision.** `Remote` adds no resolver and derives nothing (FR-026, FR-028). `middleware=` is the one
place outside both doors; `A2AOptions.owner_resolver` and `MCPOptions.owner` say what each door
reads. The README gives the one-line recipe (`owner=` that returns the user's name when the request
is authenticated). The D5 warning rule is in R11.

**Alternatives.** Derive the MCP owner from the middleware's user by default: rejected in D5 (magic
across two mechanisms). Make "no MCP owner source" an error: rejected in D5 (a gateway may
authenticate in front).

## R4. Classifying `agent=` by shape, without importing an SDK (FR-004, FR-010)

**Facts.** `AgentSource` is a `Protocol` and is not runtime-checkable: `isinstance(x, AgentSource)`
raises `TypeError`. An a2a-sdk `AgentExecutor` has `execute` and `cancel`, and none of `card`,
`pause`, `run`, `resume`. Checking `isinstance(x, AgentExecutor)` needs `a2a` imported, which must not
happen when only MCP is exposed (and `a2a` may not be installed).

**Decision.** Two shapes, tested in this order:
1. *source*: has `card`, `pause`, and callable `run` and `resume`;
2. *executor*: has callable `execute` and `cancel`.

Anything else is a `TypeError` that names both kinds. An object with both shapes is a source (a
source never has `execute`; an executor that also grew `card`, `pause`, `run` and `resume` is a
source). `SourceExecutor(source)` handed in as `agent=` is an executor and is served as one, with
`card=` required (R5, FR-003). No door is loaded to decide the kind.

**Alternatives.** `isinstance` against the SDK class once A2A is loaded: rejected, a second rule for
the same question and wrong when only MCP is exposed. Duck-typing on `__call__`: rejected, a
`Runnable` or a LangChain tool is callable-looking and wrongly accepted.

## R5. Classifying `tools=`, the agent tool and the card (FR-003, FR-008, FR-011, FR-012, D6)

**Facts.** `tool_from_function` raises `AttributeError` for an object that is not a function (a
LangChain `BaseTool` has no `__name__`), which says nothing about what to do; a LangChain tool is
not callable at all (`callable()` is false). `R2CExtension` itself accepts `ToolSpec` and
`SourceTool` only and raises `ValueError` for a duplicate name or for `approve` naming a
`SourceTool`.

**Decision.** In `Remote.__init__`, after the extra's door is loaded (R6), each entry of `tools=` is:
- a `ToolSpec` or a `SourceTool`: kept;
- a routine (`inspect.isroutine`: a function, a method, a builtin): converted with the core's
  `tool_from_function`; the core's own refusals (`*args`, no type hints, a leading underscore) pass
  through unchanged (spec edge case);
- anything else (including a `functools.partial`, a callable instance, a LangChain tool): `TypeError`
  whose fixed text names the accepted kinds and says "a LangChain tool is converted in your module
  with `tools_from_langchain(...)`, from `ext_r2c.bridges.langgraph`". The text is static; `Remote`
  recognises nothing and imports nothing from the bridge (FR-011, principle VIII). A partial is
  refused because `Remote` has no way to give it a name; `tool_from_function(fn, name=...)` does.

With `mcp_tool=True` and an `AgentSource`, `Remote` builds `SourceTool(agent)` and reads its `.name`
for the collision check, so the name `agent` is not written down twice. The card information is
`card=` if given, else `agent.card` for a source; neither exists for an executor or for tools only,
which is an error whichever door is exposed (FR-003). A `card=` given together with a source that has
its own card wins: the owner said it, and it needs no warning.

**Alternatives.** Accept partials by deriving a name: rejected, a guess. Let the core raise
`AttributeError` for a non-routine: rejected (unhelpful, and not a `TypeError` as FR-011 says).

## R6. Order of checks, and the three error kinds (D10, FR-006, FR-031, FR-032, FR-034)

**Decision.** `Remote.__init__` runs in this order and nothing is built before it ends:

1. **Read `expose`** only far enough to know which doors to probe: it must be a list, tuple or set
   of `str`. A bare `str` (a typo for a one-item list that would iterate letters), or an item that
   is not a `str`, is a `TypeError`. Door names that are unknown or repeated are *not* raised here:
   they are collected (step 4); the valid names are probed.
2. **Load each valid exposed door** (`ext_r2c.a2a`, `ext_r2c.mcp`) inside a `try`. An
   `ImportError` whose `name` is the door's SDK (`a2a`, or `mcp` / `yaml` for MCP) is re-raised as an
   `ImportError` that names `ext-r2c[a2a]` or `ext-r2c[mcp]` (both, in one message, when both are
   missing). Any other `ImportError` is a bug and propagates unchanged. This is before every
   other check (FR-006). `import ext_r2c` and `from ext_r2c import Remote` never reach this step.
3. **Type checks**, first one found, `TypeError`: `agent` (R4), each of `tools` (R5), `approve`
   (a name list or a name → `Approve` | `bool` mapping; a bare `str` is refused), `skills`,
   `resources`, `prompts`, `middleware` (`starlette` `Middleware` instances), `a2a`
   (`A2AOptions`), `mcp` (`MCPOptions`), `limits`, `clock`, `card` (`CardInfo`), `url` (`str`),
   `mcp_tool` (`bool`). Entries of `resources` and `prompts` are the MCP SDK's `Resource` and
   `Prompt`. A check that needs a door's class runs only when that door is exposed.
4. **Collected problems** (R7), every one, raised as one `RemoteError`.
5. **Warnings** (R11), only when there are no problems.

Nothing is built, started or imported beyond the door packages before step 5 ends, so an error
never half-builds anything and never waits for a request (FR-031, FR-034).

**Why the ImportError first.** FR-006 says so, and an owner without the extra should hear that
before hearing about anything else they typed.

**Alternatives.** Collect type errors too: rejected, a wrong type is one slip with one cause, and
later checks would run on an object of unknown shape. Detect a missing extra with `find_spec`:
rejected, it says "present", not "importable", and misses a broken install; catching the real import
is the check that matters.

## R7. The table of build problems, completed (FR-032 and what the plan adds)

Rows 1–13 and 15 are the spec's table (FR-032); rows 14 and 16–19 are additions the plan found
while reading the SDKs (flagged in the plan). Each of these is one collected `problems` item of a
`RemoteError`, except rows 15, 20 and 21, whose kinds are said in the text under the table.

| # | Problem | Names |
|---|---|---|
| 1 | `expose` missing, empty, unknown door, or a door repeated | `expose` |
| 2 | A2A exposed, no `agent` | `agent` |
| 3 | no card information (no `card=`, no source `card`), whichever door | `card` |
| 4 | A2A exposed, no `url` | `url` |
| 5 | MCP exposed with nothing to serve (no tool, no agent tool, no skills, no resources, no prompts) | `tools` |
| 6 | an agent no exposed door serves (a source with MCP only and no `mcp_tool`; an executor with MCP only) | `agent`, and `mcp_tool` where it applies |
| 7 | `mcp_tool=True` with an executor | `mcp_tool` |
| 8 | `tools`, `approve`, `skills`, `resources`, `prompts`, `mcp_tool` or `mcp` given, MCP not exposed | each one |
| 9 | `url` or `a2a` given, A2A not exposed | each one |
| 10 | `approve` names a name that is not a tool of the MCP door | the name |
| 11 | `approve` names the agent's tool, or any `SourceTool` | the name |
| 12 | two tools with one name (the agent tool included) | the name |
| 13 | the two door paths, or a path and a well-known path, collide | `a2a.path`, `mcp.path` |
| 14 | `mcp_tool=True` and `agent` is absent | `mcp_tool` |
| 15 | a skills folder that fails the scan | `SkillsError`, unchanged, raised by `app()` (R9) |
| 16 | an `approve` entry whose `answer_by` is not `person` or `approver` (`Approve` does not check it today, so it would be served as is; principle V) | the name |
| 17 | `url` is not an absolute `http` or `https` address with a host, with no query, fragment or user info | `url` (never the value) |
| 18 | `a2a.path` or `mcp.path` does not start with `/`, or a path sits under `/.well-known/` | the option |
| 19 | `MCPOptions.server` or `.http` names a keyword `Remote` owns (R8) | the key |
| 20 | an `approve` mapping value that is neither `Approve` nor `bool` (a `TypeError`, listed for completeness) | the name |
| 21 | a skills value that is none of: a folder, a sequence of folders, a `SkillsExtension` (a `TypeError`) | `skills` |

Row 15 is the unchanged `SkillsError`, raised by `app()` because scanning the folders is what
building `SkillsExtension` does (R9). Rows 20 and 21 are `TypeError`s (step 3 of R6) and sit here
so the table shows every case.

Messages follow one convention (data-model): `"<argument>: <what is wrong>; <what to do>"`. They name
arguments, door names and tool names, and never echo a value an owner typed (a URL can carry a
credential; a path is this host's) (FR-033).

## R8. Door options and the keywords `Remote` owns (D12, FR-027)

**Facts.** `a2a_app(executor, card, *, task_store, owner_resolver, rpc_url, middleware)`.
`mcp_server(name, extension, *, security, extensions, **kwargs)` forwards `kwargs` to
`MCPServer`, whose keywords are: `name`, `title`, `description`, `instructions`, `website_url`,
`icons`, `version`, `auth_server_provider`, `token_verifier`, `tools`, `resources`, `extensions`,
`debug`, `log_level`, `warn_on_duplicate_resources`, `warn_on_duplicate_tools`,
`warn_on_duplicate_prompts`, `dependencies`, `lifespan`, `auth`, `resource_security`,
`request_state_security`, `cache_hints`, `subscriptions`, `middleware` (the SDK's request
middleware, not the ASGI middleware of `Remote`). `streamable_http_app` takes:
`streamable_http_path`, `json_response`, `stateless_http`, `event_store`, `retry_interval`,
`max_request_body_size`, `session_idle_timeout`, `max_sessions`, `transport_security`, `host`.

**Decision.** Two frozen, keyword-only dataclasses; fields are typed as `Any` or under
`TYPE_CHECKING`, so importing them needs no SDK.

| | field | default | goes to |
|---|---|---|---|
| `A2AOptions` | `task_store` | `None` | `a2a_app(task_store=)` (the SDK's in-memory store when `None`) |
| | `owner_resolver` | `None` | `a2a_app(owner_resolver=)` (the SDK's default when `None`) |
| | `path` | `"/"` | `a2a_app(rpc_url=)`, and the card's interface URL (R10) |
| `MCPOptions` | `path` | `"/mcp"` | `streamable_http_app(streamable_http_path=)` |
| | `security` | `None` | `mcp_server(security=)` (request-state keys; ephemeral when `None`) |
| | `owner` | `None` | `R2CExtension(owner=)` |
| | `transport_security` | `None` | `streamable_http_app(transport_security=)` (host rules) |
| | `server` | `{}` | the rest of `MCPServer`'s keywords (`instructions`, `auth`, `token_verifier`, `auth_server_provider`, `lifespan`, `middleware`, ...) |
| | `http` | `{}` | the rest of `streamable_http_app`'s keywords (`json_response`, `stateless_http`, `host`, ...) |

`Remote` owns, and refuses in `server`: `name`, `description`, `version` (from the card), `extensions`,
`tools`, `resources` (its own arguments), `request_state_security` (use `security`). It refuses in
`http`: `streamable_http_path` (use `path`) and `transport_security` (use the field). Everything else
passes through unchecked: the SDK's own errors speak for themselves. A test compares the owned keys
to the SDK's keyword sets so a rename in the SDK fails a test, not a deployment.

**Why `auth` and `token_verifier` sit in `server`.** One place for the SDK's own settings; D5's "an
MCP owner source exists" reads three keys there (`auth`, `token_verifier`, `auth_server_provider`) and
`owner`. First-class fields for them would be a second way to say the same thing.

**The host guard.** The MCP app answers `421` to a `Host` that is not its default `127.0.0.1` until
`transport_security` names the host (finding 8). `Remote` neither defaults nor guesses it: a wrong
default either opens a rebinding hole or hides the guard. The README's deployment section says so
and shows the setting. (Docs only; no code.)

**Alternatives.** Flat keywords on `Remote`: rejected in D12. Pass `**kwargs`: rejected, no type, no
reserved-key check, no help for the IDE.

## R9. What the MCP side is built from (FR-008, FR-016, FR-017, D8, D9)

**Facts (probe).** An MCP server built with `R2CExtension(tools=())`, a `SkillsExtension`, one
resource added with `add_resource` and one prompt added with `add_prompt` starts, lists the skills,
the resource and the prompt, answers `tools/list` with an empty list, and carries the R2C key. The
server has no `prompts=` keyword, so `add_prompt` is the one way for prompts; `add_resource` is used
for resources too so the two behave alike.

**Decision.** When MCP is exposed `app()` builds, in this order: the tool table (R5, kept from
`__init__`); `R2CExtension(tools=..., approve=..., clock=, limits=, owner=)`; the skills extension
(`SkillsExtension(folders)` when a folder or a list is given, the given one as is); then
`mcp_server(card.name, extension, security=, extensions=[skills]?, version=card.version,
description=card.description, **options.server)`; then `add_resource` and `add_prompt` for each
object given; then `streamable_http_app(...)`. The R2C extension is always served, even with no
tools: the standard's activation is uniform and a server with skills only still declares it.
`approve=` as a name list becomes `{name: True}`; a mapping is used as it is.

**A bad skills folder** fails when `SkillsExtension` is built, which is in `app()`, as the unchanged
`SkillsError`. The owner's module sees it on the line that builds the app (R12).

**Alternatives.** Build the skills extension in `__init__` so the error comes earlier: rejected,
it would keep a built object that serves one server inside a `Remote` that may never call `app()`;
the owner's two lines (`Remote(...)`, `.app()`) are adjacent. Pass `resources` through `MCPServer(resources=)`:
rejected, prompts have no such keyword, and one mechanism is clearer.

## R10. The card address, and the paths (D2, FR-021, FR-024)

**Decision.** `url` is the public base of the app, such as `https://remote.example.com` or
`https://remote.example.com/api`. The card's JSON-RPC address is `url.rstrip("/") + a2a.path`
(`https://remote.example.com/` by default) and is passed to `agent_card(info, address)`. The card
route stays at the app's root (`/.well-known/agent-card.json`); an owner who mounts the app under a
prefix puts the prefix in `url` and the README says so. The card advertises R2C `required: false`
exactly as `agent_card` does; `Remote` adds nothing to it (FR-007).

**Collisions** are checked twice. Statically at construction (R7 rows 13 and 18): the two paths are
not equal, begin with `/`, and neither sits under `/.well-known/`. Dynamically in `app()`, after both
apps exist: each A2A path (`a2a.path` and the card path) is tested against the MCP router
(`Dispatch._is_mcp`); a match is a `RemoteError`, which catches the routes the SDK adds when `auth`
is on (the spec's D11 asks for one such test).

**Alternatives.** Hard-coded list of MCP paths for the static check: rejected (R1). `url` as the full
JSON-RPC address: rejected, the owner would repeat `a2a.path` in two places.

## R11. The two warnings (D5, D13, FR-027, FR-029)

Both are `UserWarning`s, raised in `__init__` after the checks pass (so a refused `Remote` warns
nothing), with `stacklevel` pointing at the owner's `Remote(...)` line.

- **D13, per door, once.** *A2A:* exposed and `A2AOptions.task_store is None`. A paused task then
  lives in memory and a restart loses it. *MCP:* exposed, `MCPOptions.security is None`, and
  something on MCP can pause across a retry: a non-empty `approve=`, or a `SourceTool` whose source is
  of the checkpoint style (`source.pause == "checkpoint"`, including the agent tool). A plain
  `ToolSpec` never pauses, and a live source needs the same process rather than keys (spec 004), so
  neither warns. Text: names the door, says a restart loses a paused call, and names the setting
  (`task_store` or `security`).
- **D5, once.** `middleware` is not empty, MCP is exposed, and MCP has no owner source: no
  `MCPOptions.owner`, and none of `auth`, `token_verifier`, `auth_server_provider` in
  `MCPOptions.server`. Text: every MCP caller is one owner and one thread namespace; give `owner=` or
  authenticate in front.

Tests silence or satisfy them as spec 006's tests do (a store and keys, or `pytest.warns`). The suite
runs with `-W error::UserWarning`, so a warning nobody expected fails a test.

**Alternatives.** Silent defaults (as `a2a_app` and `mcp_server` are today): rejected in D13. Raise an
error for D5: rejected in D5.

## R12. One app per `Remote`, and a failed build (D4, FR-025)

**Decision.** The first call of `app()` sets a flag at entry; a second call raises `RuntimeError`
("one `Remote` builds one app; build a new `Remote`"). The flag is set even when the first call
fails (a bad skills folder, a dynamic collision): objects the owner supplied (a ready
`SkillsExtension`, a `SourceTool`) may have been partly used by the SDK, and "build a new one" is
the one path. `Remote` builds nothing in `__init__` except the tool table and, for the agent tool,
the `SourceTool` (cheap, no I/O), so a `Remote` that never calls `app()` holds nothing to close.

**Alternatives.** Allow a retry after a failed build: rejected, it would need to know what the SDK
mutated. Build everything in `__init__`: rejected (R9).

## R13. Export, packaging and the single-extra checks (FR-001, FR-035, FR-036, SC-010)

**Decision.**
- **Export.** `ext_r2c/__init__.py` exposes `Remote`, `RemoteError`, `A2AOptions` and `MCPOptions` by
  a module-level `__getattr__` (PEP 562), with a `TYPE_CHECKING` import for type checkers, and
  adds them to `__all__`. `import ext_r2c` does not load `ext_r2c.remote`; `import ext_r2c.core` does
  not either (so the core-only check stays as it is). `from ext_r2c import Remote` loads the
  `remote` package, which imports `ext_r2c.core` and the standard library at module level and loads
  a door **inside a function**, when that door is exposed.
- **Import rule** (extends `test_packaging.py`): at module level `ext_r2c/remote/` imports the standard
  library, `ext_r2c.core` and its own modules; inside functions it may also import `ext_r2c.a2a`,
  `ext_r2c.mcp`, `starlette` and the two SDKs; no module of it names `ext_r2c.bridges`, `langgraph`
  or `langchain`; no module outside `ext_r2c/__init__.py` imports `ext_r2c.remote`.
- **Single-extra scripts.** `core_only.py`: `from ext_r2c import Remote` works, no `a2a` or `mcp` module
  is loaded, `expose=["a2a"]` raises an `ImportError` naming `ext-r2c[a2a]` and `["mcp"]` one naming
  `[mcp]`. `a2a_only.py`: a real A2A-only `Remote` serves a card; `expose=["mcp"]` names `[mcp]`;
  `mcp` is not in `sys.modules`. `mcp_only.py`: the mirror. `langgraph_only.py`: `Remote` composes
  with `LangGraphAgent` and the other extras are absent, so `expose` can only be one door.
- **No new dependency, no new extra** (FR-036): `pyproject.toml` does not change.

**Alternatives.** Eager import in `ext_r2c/__init__.py`: rejected, every `import ext_r2c.core` would
pay for `remote` and the core-only check would have to allow it. A `remote` extra: rejected, `Remote`
needs the extras of the doors it opens and nothing else.

## R14. The test bed: one app, one lifespan, both clients (FR-037)

**Facts.** The A2A harness takes `Served(app, card)` and sends the owner as a bearer header through
`StreamingASGITransport`; the MCP harness takes `Served(server, app, record)` and does the same;
both start only their own door. The in-process transports do not run an app's lifespan, so the harness
must.

**Decision.** `tests/remote_harness.py` serves `remote.app()` inside
`app.router.lifespan_context(app)` and hands out (a) an A2A client over the same app, with the card
built by the same `agent_card` call `Remote` makes (and a test that the served card equals it) and
(b) an MCP client over the same app. It passes `Remote(middleware=[Middleware(AuthenticationMiddleware,
backend=BearerAuth())], mcp=MCPOptions(owner=<reads request.user>))`, which is the recommended
identity recipe, so one bearer header names the owner on both doors. Phase 1's spike checks that the
MCP client needs nothing from `Served.server` (it uses `Served.app`); if it does, the harness passes a
thin stand-in. Agents: `fake_sources.CheckpointFake` / `LiveFake` for the door mechanics, and the
LangGraph builders of 006 (`langgraph_graphs.py`, `langgraph_models.py`: scripted model, real
checkpointer) for the real-graph stories. `tests/remote_executor.py` holds a hand-written executor in
the shape of the official Currency sample (a scripted model, no import of `ext_r2c`).

**Closed-after-stop checks** spy on the two real objects: `R2CRequestHandler.aclose` (the A2A handler)
and `StreamableHTTPSessionManager.run` (enter and exit around the real one), so the harness needs no
handle to a door's internals and `Remote` offers none (FR-026).

**Alternatives.** An accessor on `Remote` for the door apps: rejected, public surface for tests only.
Run `uvicorn` in tests: rejected, no network; the in-process transports are what the doors' own suites use.

## R15. What the docs say at close (FR-038)

- `python/README.md`: a `Remote` section: the one-line form; the argument table (which door serves
  each); identity per door and the `owner=` recipe; the host guard; durable state for each door;
  mounting inside a larger ASGI app (run this app's lifespan); `uvicorn` as the deployment's choice.
- ADR `docs/design-docs/one-remote-two-doors.md`: three dated notes, the body unchanged: `mcp_server=`
  is not in v1 and why (finding 1, D3); `Skills(...)` is `skills=` with a folder or a
  `SkillsExtension` (D8); `url` is required for A2A (D2).
- `docs/research/2026-11-20-r2c-v1-design-brief.md`: amendment 4 (what `Remote` serves, criteria 1–5).
- `WORKSTATE.md`, `ARCHITECTURE.md` (the `remote/` rows), `AGENTS.md` (stays under 150 lines),
  `CHANGELOG.md` (Added: `Remote`; Fixed: the A2A lifespan), and `contracts/remote-api.md` marked as built.
- No new ADR: D3 amends the existing one by a dated note, and the composition mechanism is recorded in
  [contracts/app-composition.md](contracts/app-composition.md).

## R16. What was checked and needs no change

- `mcp_server`, `R2CExtension`, `SourceTool`, `SkillsExtension`, `agent_card`, `SourceExecutor` and
  `a2a_app` are used through their public signatures only. The one change to a door is A1 (R2).
- `thread_id("a2a" | "mcp", owner, context_id)` already keys each door apart; one source object
  feeding two drivers is safe for `LangGraphAgent` (spec 006) and is a contract of the source for any
  other (FR-009). A source that is not safe says so in its own contract.
- `Approve` does not validate `answer_by` (a probe built `Approve(answer_by="caller")` and
  `mcp_server` would serve it as `{"role": "caller"}`). `Remote` refuses it (R7 row 16). Hardening
  `Approve` itself is a spec 004 follow-up, not done here ([plan](plan.md#needs-the-maintainer)).
- The standard (`standard/`) is untouched: `Remote` is an SDK piece.

## R17. Mutation check of the safety rows (T077, run 2026-11-23)

A mutant changes one thing in the installed package, the named test files must then fail, and the
package is restored from its own text right after. Baseline first: `test_remote_errors.py`,
`test_remote_approvals.py`, `test_remote_lifecycle.py`, `test_remote_compose.py`,
`test_remote_options.py` and `test_remote_serve.py` are green (215 tests). **12 of 12 mutants died**,
and the installed package equalled the source again at the end. The runner stops at the first failing
test (`-x`), so the table names that one; other tests may fail as well.

| Mutant | First test to fail |
|---|---|
| `approve` accepts a name that is no tool | `test_one_mistake_is_one_problem_that_names_its_argument`, the row for it |
| `approve` accepts the agent's own tool | the same test, the row for the agent's tool |
| `approve` accepts any `answer_by` | the same test, the row for `answer_by` |
| A1: the A2A handler is closed only on a clean stop | `test_an_mcp_door_that_fails_to_start_leaves_the_a2a_door_closed` |
| `/mcp` is routed to the A2A app | `test_a_card_that_is_given_wins_over_the_one_an_agent_brings` |
| only the A2A lifespan runs | `test_a_card_that_is_given_wins_over_the_one_an_agent_brings` |
| only the MCP lifespan runs | `test_app_starts_nothing_and_its_lifespan_starts_and_stops_both_doors` |
| `app()` may run twice | `test_one_remote_builds_one_app` |
| a failed `app()` may be tried again | `test_one_remote_builds_one_app` |
| `auth`, `token_verifier`, `auth_server_provider` each dropped from the owner sources | `test_an_mcp_door_that_can_name_the_owner_or_has_no_middleware_does_not_warn`, one mutant for each key |

The three owner-source mutants were re-pointed at `OWNER_SOURCES` in `remote/_options.py`, where the
phase 10 de-duplication put the tuple that the check and the warning both read.

## R18. The outside review of phases 1 to 10 (T078, run 2026-11-23)

Two reviewers read the whole range since `d07f9c6` with fresh context and no knowledge of the plan's
reasoning: a code reviewer and a security reviewer. Their findings are numbered below per reviewer. For
each one acted on, a test was written first and seen to fail for the stated reason on the old wheel
(20 failures in `test_remote_review.py` and `test_remote_errors.py`), then the fix was made. After the
fixes the full suite passes (2841 tests on 3.11, 3.12 and 3.13), the four single-extra scripts and
`ruff --select F` are clean, and **19 of 19 mutants of the fixes died** (below).

**Acted on**

| Finding | What was wrong | What was done | Pinned by |
|---|---|---|---|
| code 1 | `SERVER_OWNED` missed `security` and `extension`, the keywords of `mcp_server` itself: giving one in `mcp.server` was a raw `TypeError` from `app()`, not a problem at `Remote(...)` | both are owned, with what to do instead | `test_a_keyword_of_mcp_server_itself_is_a_problem_when_remote_is_built`, `test_the_security_field_is_the_one_way_to_give_the_request_state_policy` |
| security 2 | `http={"host": ...}` is no collision, but the SDK keeps its host guard only for a loopback `host`, so a bind address there turned the guard off in silence | `host` is owned, and the message points at `transport_security` | `test_the_bind_address_is_not_an_http_keyword_because_it_turns_the_host_guard_off` |
| code 2 | the `MCPOptions.owner` docstring said the reverse of the code: spec 004's `R2CExtension` asks the callable first and falls back to the SDK's principal | the code stays (it is built, tested and the recipe in the README relies on it); the docstring, the README and the contract say what the code does | `test_an_owner_callable_that_names_an_owner_wins_over_the_verified_principal`, `..._that_answers_none_leaves_the_verified_principal`, `test_the_documentation_of_the_owner_field_says_the_order_the_code_has` |
| code 3 | a `skills=` list was held by reference, so a list changed after `Remote(...)` was read again, unchecked, by `app()` | a list of folders is copied into a tuple when it passes the check, as `tools=` is held | `test_a_list_of_skill_folders_changed_after_the_build_is_not_read_again` |
| code 4, security 5 | a `url` with a line break, a tab or a space reached the card (`urlsplit` drops tabs and line breaks before it reads), and so did a port that is no number | a space or control character and a bad port are problems of `url`, in the same one `RemoteError` | `test_a_url_the_card_could_not_say_as_it_is_is_a_problem` (newline, space, tab, NUL, bad port, port above 65535, `[::1`) and `test_the_addresses_an_owner_means_still_build` |
| code 5 | a class passed `agent_kind` (its `run` and `execute` are plain functions) and failed at the first request | a class given as `agent` is a `TypeError` at `Remote(...)`, naming the class | `test_a_class_given_as_the_agent_is_refused_when_remote_is_built`, `test_an_instance_of_each_is_still_taken` |
| code 6 | a `RemoteError` could not be pickled or copied (`args` holds the formatted text, which `__init__` refuses as a bare string) | `__reduce__` rebuilds it from `problems` | `test_a_remote_error_survives_pickle_and_copy_with_its_problems_in_order` |
| code 7 | nothing showed that `limits=` and `clock=` reach each door | tests spy on `SourceExecutor` and `R2CExtension`; the reviewer's four mutants (drop `limits` or `clock` from either door) are in the mutation run | `test_the_limits_and_the_clock_given_reach_the_a2a_door`, `..._the_mcp_door`, `test_without_them_each_door_gets_the_defaults` |
| code 8, 10, 11 | the `app()` docstring did not say the app starts once; two docstrings were loose | reworded; a README sentence says the app starts once | read, no test |
| code 12 | test gaps: the `urlsplit` `ValueError` branch and the exact path `/.well-known` | tests added | `test_the_well_known_folder_itself_is_not_a_path_for_a_door`, the `[::1` row above |
| security 6 | a message echoes the `approve` key the owner typed | this is the contract's carve-out (a tool, door or keyword name the owner chose may appear); the `RemoteError` docstring now says so | read, no test |

**Left on purpose**

- security 1: the D5 warning covers MCP only. With no `middleware=` and no `owner_resolver` every A2A
  caller is one owner, and the SDK's authentication in `MCPOptions.server` does not protect the A2A door.
  A warning is a change of the spec (FR-029), so it is **not built**; the README says it in a sentence
  and the proposal is for the maintainer.
- security 3: the host guard covers `/mcp` only; the A2A door answers any `Host`. README sentence.
- security 4: an A2A `task_store` and an `owner_resolver` must agree on who owns a task, and nothing
  compares them. README sentence.
- security 7: `approve=` beside `mcp_tool=True` leaves the agent tool without an approval. The README
  already says the two lists are separate on purpose; the agent's own approvals stay with the agent.
- security 8: the A2A door holds paused work and reads a request body with no age limit or size cap.
  This is spec 003's door, unchanged by `Remote`, so it is a follow-up of that spec.
- code 9: `SkillsError` echoes the folder path the owner gave. It is the unchanged error of spec 005,
  carved out by the contract and documented in the README.
- `http` on a non-loopback host in `url` is accepted: a service behind a proxy that ends TLS is
  reached by `http` inside and `https` outside, and the contract says `http(s)`.

**Mutation check of the fixes (T079).** Baseline first: `test_remote_review.py`, `test_remote_errors.py`
and `test_remote_options.py` green (207 tests). 19 mutants, all died: `security`, `extension` and
`host` dropped from the owned keys; the owner order reversed (the principal wins); the owner docstring
saying "last"; the skills list held by reference; the `url` check dropped whole, or only for a space, or
only for a NUL; the port check dropped; the `ValueError` of an unparsable address raised; a class
accepted as an agent; `__reduce__` removed; `limits` and `clock` each dropped from each door;
`/.well-known` and `/.well-known/` each allowed as a path. The installed package equalled the source
again at the end.

**Areas the reviewers read and found clean.** The dispatcher and mount (the exact `/mcp` match, the
lifespan stop order and its unwinding when a door fails), the once-flag of `app()`, an argument fuzz
(15 arguments, about 34 values each, three `expose` sets: every failure is a `TypeError` or one
`RemoteError`, never a raw SDK error), the import rule of `remote/`, cross-owner isolation, principle V
(nothing in `Remote` answers an approval) and the compile on 3.11 and 3.12.
