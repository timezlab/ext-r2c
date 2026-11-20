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
| `artifact` | A file, inline content, or a live link handed back to the caller |

Adapters wrap an existing agent or server, so the remote's own logic does not
change. Progress is not part of R2C: it stays in the protocol's own status
stream.

> **Status: pre-alpha.** The standard (`standard/v1`) is being written. Names
> and shapes may change until `v1` is tagged.

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

Until the normative text is written, the
[v1 design brief](docs/research/2026-11-20-r2c-v1-design-brief.md) describes every kind, both
bindings and the reasons behind them; the decisions are in [`docs/design-docs/`](docs/design-docs/).

## Python

```bash
cd python
uv build                       # builds dist/ext_r2c-*.whl
uv venv .wheel-venv && uv pip install --python .wheel-venv dist/*.whl pytest
.wheel-venv/bin/pytest         # tests run against the installed wheel
```

## License

[Apache-2.0](LICENSE)
