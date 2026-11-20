# Quickstart: validate the R2C v1 standard

**Feature**: [spec.md](spec.md)

## Prerequisites

- `uv` installed; Python 3.11, 3.12 or 3.13 available to it.
- A checkout of this repository (the tests read `standard/v1/` from it).

## Build and test, as CI does

```bash
cd python
uv build                                      # sdist, then the wheel built from it
uv venv --python 3.11 ../.ci-venv
uv pip install --python ../.ci-venv dist/*.whl --group dev
../.ci-venv/bin/pytest
```

Expected: every test passes. They cover the smoke tests, the schemas, the examples (R2C objects
and envelopes), rule coverage, and the packaged schemas.

## Scenarios to check by hand

| # | Do | Expect | Proves |
|---|---|---|---|
| 1 | Run the suite as above | all green; the example test reports N valid examples, M invalid examples, K ignored unknown kinds | SC-001, SC-001a |
| 2 | In a copy of an `examples/a2a/` file, delete `title` from the `question` | the example test fails and names the file and `/title` | SC-003, US2 scenario 3 |
| 3 | In an `examples/mcp/` file, rename `inputRequests` to `inputRequest` | the envelope check fails on the dropped key | FR-021a |
| 4 | Add a rule marked `wire` to the README that no example cites | the coverage test fails and names the rule | SC-002 |
| 5 | Add an empty `examples/a2a/unused.txt` | the coverage test fails (unread file) | FR-021 |
| 6 | `unzip -l dist/*.whl \| grep schema/v1` | six files under `ext_r2c/schema/v1/` | SC-004 |
| 7 | Edit one schema in `standard/v1/schema/`, rebuild, rerun | the packaged-schema test still passes (the wheel follows the source) | US3 scenario 2 |
| 8 | Read the README's rule index | every rule has an id, level, party, and wire/prose mark | US1 scenario 4 |

Undo scenarios 2–5 and 7 afterwards (`git checkout -- standard/`).

## Validate one object by hand, any language

Any JSON Schema 2020-12 validator works offline with one schema file:

```bash
uvx --from 'check-jsonschema' check-jsonschema --schemafile standard/v1/schema/approval.json my-approval.json
```

References: the file contract is in [contracts/example-file.md](contracts/example-file.md), the
README rule grammar in [contracts/rule-format.md](contracts/rule-format.md), and the shapes in
[data-model.md](data-model.md).
