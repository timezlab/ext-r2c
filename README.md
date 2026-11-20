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

> **Status: pre-alpha.** The standard (`standard/v1`) is written and in draft.
> The Python SDK has its core and the A2A door (see [`python/`](python/README.md));
> the MCP door, the LangGraph bridge and `Remote` come next. Names and shapes
> may change until `v1` leaves draft.

## Identifiers

| Binding | Identifier |
|---------|------------|
| A2A extension URI | `https://github.com/timezlab/ext-r2c/tree/main/standard/v1` |
| MCP `_meta` key   | `io.github.timezlab/r2c` |

## Layout

```
standard/v1/   the normative spec, one JSON Schema per kind, wire examples
python/        the Python SDK (package ext-r2c, import ext_r2c)
```

The JSON Schemas are the single source of shape. The wire examples under
`standard/v1/examples/` are the shared test suite every SDK must pass.

The normative text is [`standard/v1/README.md`](standard/v1/README.md). The
[white paper](docs/whitepaper.md) explains R2C end to end, and the
[v1 design brief](docs/research/2026-11-20-r2c-v1-design-brief.md) with the ADRs in
[`docs/design-docs/`](docs/design-docs/) records the reasons behind it.

## Python

```bash
cd python
uv build                       # builds dist/ext_r2c-*.whl
uv venv .wheel-venv && uv pip install --python .wheel-venv dist/*.whl pytest
.wheel-venv/bin/pytest         # tests run against the installed wheel
```

## License

[Apache-2.0](LICENSE)
