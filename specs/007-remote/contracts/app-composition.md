# Contract: how `Remote.app()` composes two doors (spec 007)

Status: built (2026-11-23); the dated note at the end says what the build added to the text below,
which is kept as planned. Facts are from [research.md](research.md) R1, R2, R3, R10 and R14.

## The application

```python
parent = Starlette(
    routes=[Mount("/", app=Dispatch(a2a_app, mcp_app))],   # either may be None, not both
    middleware=list(middleware),                           # the owner's, outermost first
    lifespan=both,
)
```

`Dispatch` is a small ASGI callable. For an HTTP request it asks the MCP app's own router:

```python
def _is_mcp(self, scope) -> bool:
    return any(route.matches(scope)[0] != Match.NONE for route in self.mcp.router.routes)
```

A full or partial match goes to the MCP app (a partial match is a wrong method on MCP's path, and MCP
answers it with its own `405`); everything else goes to the A2A app. With one door, the only app gets
everything and answers its own `404`. Each sub-app keeps its own middleware, so A2A's echo of the
activated extensions wraps A2A only and the SDK's authentication wraps MCP only; the owner's
`middleware=` wraps both, outside.

## Routes (both doors, default paths)

| Path | Door | Notes |
|---|---|---|
| `POST /` | A2A | the JSON-RPC endpoint (`A2AOptions.path`) |
| `GET /.well-known/agent-card.json` | A2A | at the root always; the card's address is `url` + `A2AOptions.path` |
| `/mcp` | MCP | exactly this path, no redirect, no trailing slash (`MCPOptions.path`) |
| `/.well-known/oauth-protected-resource…` | MCP | only when the SDK's `auth` is set; found by the router, not listed |

`/mcp/` is not promised. An app mounted by the owner under a prefix must run this app's lifespan, and
puts the prefix in `url`.

## Lifespan

```python
@contextlib.asynccontextmanager
async def both(app):
    async with contextlib.AsyncExitStack() as stack:
        if a2a_app is not None:
            await stack.enter_async_context(a2a_app.router.lifespan_context(a2a_app))
        if mcp_app is not None:
            await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
        yield
```

Start order: A2A, then MCP. Stop order: MCP, then A2A. A failure while MCP starts unwinds the stack: the
A2A handler is closed and the error propagates. A door not exposed is not entered.

## Change to a door: A1 (the only one)

`ext_r2c/a2a/app.py`, the lifespan of `a2a_app`:

```python
# before
yield
await handler.aclose()
# after
try:
    yield
finally:
    await handler.aclose()
```

Why: the handler stays open when an exception is thrown into the lifespan at its `yield`, which is what
`AsyncExitStack` does when a later lifespan fails to start (R2). The clean stop is unchanged and
`aclose` may run twice. Test first, in `tests/test_a2a_serve.py`. Nothing else in a door changes.

## Identity under one outer middleware

An `AuthenticationMiddleware` given in `middleware=` runs before both doors. A2A's default resolver
reads the user it set. MCP's `owner` callable receives `ctx` and may read `ctx.request.user`:

```python
def owner(ctx):
    user = getattr(getattr(ctx, "request", None), "user", None)
    return user.display_name if user is not None and user.is_authenticated else None
```

`Remote` does not write this for the owner (D5).

## Dynamic collision check (in `app()`, after both apps exist)

For `a2a.path` and the card path, `Dispatch._is_mcp` must be false. A match is a `RemoteError`
naming the path. This is what catches the routes the SDK adds with `auth` (the static check covers
only the two configured paths and `/.well-known/`).

## Test bed (`tests/remote_harness.py`)

Serves `remote.app()` inside its own lifespan; gives an A2A client and an MCP client over the same app
(the in-process transports of the doors' suites); builds the card the same way `Remote` does so a test
can compare. Closed-after-stop is observed by spying `R2CRequestHandler.aclose` and
`StreamableHTTPSessionManager.run`; `Remote` offers no accessor for the door apps (FR-026).

> **Note, 2026-11-23 (built).** What the build added to the text above:
> - A probe on the installed Starlette corrected the first draft: `Mount("/mcp", …)` answers `POST /mcp`
>   with a 307 to `/mcp/`, which then answers 404, so the dispatcher takes the path itself and `/mcp` is
>   served exactly (research R3). An owner who mounts the whole app under a prefix runs this app's
>   lifespan, because Starlette's `Mount` does not run the lifespan of what it mounts, and puts the prefix
>   in `url`; the README shows it.
> - An error raised while the app is serving comes out of the lifespan inside an `ExceptionGroup`
>   (the MCP session manager runs in an `anyio` task group; the same without `Remote`), and a door that
>   fails to start raises its error bare. Both doors are unwound either way (A1 closes the A2A handler),
>   and `test_remote_lifecycle.py` reads the leaf.
