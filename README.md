# R2C: Remote-to-Caller

R2C is an extension for [A2A](https://a2a-protocol.org) and
[MCP](https://modelcontextprotocol.io). It gives a **remote** (an A2A agent or
an MCP server) one standard way to talk back to its **caller** while a task
runs:

| Kind       | What the remote sends                                         |
|------------|---------------------------------------------------------------|
| `question` | A form for the person, an approver, or the caller agent       |
| `approval` | A request to allow, edit, or deny one action                  |
| `answer`   | The reply to a `question` or an `approval`                    |
| `artifact` | A file, inline content (the streamed reply), or a live link handed back to the caller |
| `activity` | What the remote is doing: a tool call, a step, or (if the remote allows) reasoning |
| `usage`    | Tokens, time and cost the remote reports for the task |

One adapter, `Remote`, wraps an existing agent, tools and skills and exposes
them over A2A, MCP, or both (a setting), so the remote's own logic does not
change. Everything travels on the protocol's own stream: A2A status and
artifact updates, MCP progress notifications and tool results.

> **Status: alpha.** The standard (`standard/v1`) is written and in draft.
> The Python SDK has its core, the A2A door, the MCP door, MCP Skills, the
> LangGraph bridge and `Remote` (see [`python/`](python/README.md)); its first
> pre-release, `0.1.0a1`, is a GitHub release and is not on PyPI.
> [`examples/langgraph_agent/`](examples/langgraph_agent/README.md) shows
> it in use. Names and shapes may change until `v1` leaves draft. What this
> release does not do is listed in [`docs/known-limits.md`](docs/known-limits.md).

## Identifiers

| Binding | Identifier |
|---------|------------|
| A2A extension URI | `https://github.com/timezlab/ext-r2c/tree/main/standard/v1` |
| MCP `_meta` key   | `io.github.timezlab/r2c` |

## Layout

```
standard/v1/   the normative spec, one JSON Schema per kind, wire examples
python/        the Python SDK (package ext-r2c, import ext_r2c)
examples/      the SDK in use: two LangGraph agents that call each other
```

The JSON Schemas are the single source of shape. The wire examples under
`standard/v1/examples/` are the shared test suite every SDK must pass.

The normative text is [`standard/v1/README.md`](standard/v1/README.md). The
[white paper](docs/whitepaper.md) explains R2C end to end, and the
[v1 design brief](docs/research/2026-11-20-r2c-v1-design-brief.md) with the ADRs in
[`docs/design-docs/`](docs/design-docs/) records the reasons behind it.

## Install

The first pre-release is a GitHub release, not a PyPI package, and it needs Python 3.11 or newer. Install it by
its full address; no `--pre` is needed:

```bash
pip install "ext-r2c[a2a,mcp,langgraph] @ https://github.com/timezlab/ext-r2c/releases/download/v0.1.0a1/ext_r2c-0.1.0a1-py3-none-any.whl"
```

The bare name `ext-r2c` on PyPI is not this project: PyPI has no package of that name today and anyone may
register it, so never install it by the name alone. It becomes this project's only if the project publishes it
there. Keep only the extras you need (`a2a`, `mcp`, `langgraph`); the table in
[`python/README.md`](python/README.md#install) says what each one brings in. What the release does not do
yet is in [`docs/known-limits.md`](docs/known-limits.md).

## Python

To build and test the package from a checkout:

```bash
cd python
uv build                       # builds dist/ext_r2c-*.whl
uv venv .wheel-venv && uv pip install --python .wheel-venv dist/*.whl pytest
.wheel-venv/bin/pytest         # tests run against the installed wheel
```

## License

[Apache-2.0](LICENSE)
