# ext-r2c (Python)

Python SDK for **R2C (Remote-to-Caller)**, an extension for A2A and MCP that
lets a remote ask its caller a question, request an approval, and hand back
artifacts.

> Pre-alpha. Only the identifiers below are published so far; the standard
> and the bindings are being written.

```python
import ext_r2c

ext_r2c.URI       # A2A extension URI
ext_r2c.MCP_KEY   # MCP _meta key
```

Optional extras: `ext-r2c[a2a]`, `ext-r2c[mcp]`, `ext-r2c[langchain]`.

See the [repository](https://github.com/timezlab/ext-r2c) for the standard.
