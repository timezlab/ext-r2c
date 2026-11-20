# ext-r2c (Python)

Python SDK for **R2C (Remote-to-Caller)**, an extension for A2A and MCP that
lets a remote ask its caller a question, request an approval, and hand back
artifacts.

> Pre-alpha. The standard v1 is written (draft); this package so far ships
> only its identifiers and its JSON Schemas. The bindings are being written.

```python
import ext_r2c
from importlib.resources import files

ext_r2c.URI       # A2A extension URI
ext_r2c.MCP_KEY   # MCP _meta key
files("ext_r2c") / "schema" / "v1" / "approval.json"   # one of the six schemas
```

Optional extras: `ext-r2c[a2a]`, `ext-r2c[mcp]`, `ext-r2c[langchain]`.

See the [repository](https://github.com/timezlab/ext-r2c) for the standard.
