# Quickstart: validating the Python core

Commands run from `python/` unless said otherwise. They are the same as CI
(`.github/workflows/python.yml`).

## 1. Build and install

```sh
uv build
uv venv --python 3.11 ../.ci-venv
uv pip install --python ../.ci-venv dist/*.whl --group dev
```

Repeat with 3.12 and 3.13 before claiming done (SC-007).

## 2. Full suite on the installed wheel

```sh
../.ci-venv/bin/pytest
```

Expected:
- every test passes;
- the summary line also reports the round trip, as
  `R2C examples: N valid, M invalid, K unknown kinds ignored; R objects round-tripped` (SC-001).

| Spec check | Tests that show it |
|---|---|
| SC-001, SC-002 | `test_models.py` (every example object, every invalid file at its `fails_at`) |
| SC-003 | `test_forms.py` (the three MCP examples' `requestedSchema` and derived answers) |
| SC-004 | `test_examples.py` (pairing through `check_answer`) and `test_check.py` (one bad answer per FR-015 rule) |
| SC-005 | `test_agent_source.py` (both fakes through [the suite](contracts/agent-source-suite.md)) |
| FR-027, FR-028 | `test_tools.py` |
| FR-029, FR-030 | `test_packaging.py` (import rules, extras) |

## 3. Core alone (SC-006)

```sh
uv venv --python 3.11 ../.core-venv
uv pip install --python ../.core-venv dist/*.whl          # no dev group, no extra
../.core-venv/bin/python -I tests/core_only.py
```

Expected: `core only: ok`. The script checks four things:
- the imports work;
- no `a2a`, `mcp`, `langchain` or `langgraph` module is loaded;
- `rfc3339_validator` is absent;
- `invalid/question-expires-not-a-date.json` is still rejected.

## 4. By hand: one question through both forms

```sh
../.ci-venv/bin/python -I - <<'EOF'
import json
from ext_r2c.core import parse, answer_schema, mcp_form, answer_from_mcp, check_answer
q = parse({"kind": "question", "id": "q-1", "title": "Which warehouse?",
           "answer_by": {"role": "person"},
           "fields": [{"key": "warehouse", "header": "Warehouse", "text": "Which warehouse?",
                       "type": "one", "options": [{"label": "North"}, {"label": "South"}]}]})
print(json.dumps(answer_schema(q)))
print(json.dumps(mcp_form(q).requested_schema))
a = answer_from_mcp(q, "accept", {"warehouse_other": "East annex"})
print(a.value, check_answer(a, q))
EOF
```

Expected:
- the answer schema;
- the flat form with `warehouse_other`;
- `{'warehouse': 'East annex'} []`.

## 5. Mutations that must fail (run on a copy through `R2C_STANDARD_DIR`)

| Change to the copy | Test that must fail |
|---|---|
| drop `warehouse_other` from `mcp/elicitation-question-other.json`'s `requestedSchema` | `test_forms.py` (generated form differs) |
| change `quantity` in the edit response of `mcp/elicitation-approval.json` | `test_forms.py` (derived answers are a table in the test, copied from each example's description) |
| make an example answer `{"title": ""}` for a required text field, with no re-ask after it | `test_examples.py` (Q2: empty required text) |
| add an unknown field to a question in an example | nothing fails (round trip keeps it) |
