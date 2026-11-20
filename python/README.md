# ext-r2c (Python)

Python SDK for **R2C (Remote-to-Caller)**, an extension for A2A and MCP that
lets a remote ask its caller a question, request an approval, and hand back
artifacts.

> Pre-alpha. The standard v1 is written (draft). This package ships its
> identifiers, its JSON Schemas and the protocol-free core (`ext_r2c.core`).
> The A2A and MCP doors are being written.

```python
import ext_r2c

ext_r2c.URI       # A2A extension URI
ext_r2c.MCP_KEY   # MCP _meta key
```

## The core

`ext_r2c.core` needs only `pydantic` and `jsonschema`. It holds the models of
the six kinds, the forms both doors show, the answer check, fallback text, the
run events, `AgentSource` with its `Driver`, and `ToolSpec`.

```python
from ext_r2c.core import answer_from_mcp, answer_schema, check_answer, mcp_form, parse

q = parse({"kind": "question", "id": "q-1", "title": "Which warehouse?",
           "answer_by": {"role": "person"},
           "fields": [{"key": "warehouse", "header": "Warehouse", "text": "Which warehouse?",
                       "type": "one", "options": [{"label": "North"}, {"label": "South"}]}]})

answer_schema(q)              # JSON Schema of the answer's value (A2A)
mcp_form(q).requested_schema  # the flat MCP form, with warehouse_other
a = answer_from_mcp(q, "accept", {"warehouse_other": "East annex"})
a.value                       # {'warehouse': 'East annex'}
check_answer(a, q)            # [] — no problem
check_answer(answer_from_mcp(q, "accept", {}), q)
# [Problem(code='invalid_value', key='warehouse', message='This is needed.')]
```

## Install

| Install | Pulls in | For |
|---|---|---|
| `ext-r2c` | pydantic, jsonschema | the core: models, forms, checks, run events |
| `ext-r2c[a2a]` | a2a-sdk | the A2A door, A2A callers |
| `ext-r2c[mcp]` | mcp | the MCP door, MCP callers |
| `ext-r2c[langgraph]` | langchain, langgraph | agents written with LangChain / LangGraph |

See the [repository](https://github.com/timezlab/ext-r2c) for the standard.
