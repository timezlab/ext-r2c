# Quickstart: validating the MCP binding

Run commands from `python/` unless a step says otherwise. They are the same commands CI runs
(`.github/workflows/python.yml`).

## 1. Build and install

```sh
rm -rf dist && uv build
uv venv --python 3.11 ../.ci-venv
uv pip install --python ../.ci-venv dist/*.whl --group dev
```

The dev group already brings `mcp>=2.3,<3`. Repeat with Python 3.12 and 3.13 before claiming
done (SC-010).

## 2. Full suite on the installed wheel

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider
```

Expected:
- every test passes;
- the summary shows both replays, with each count matching the files at that time:
  - `A2A replay: … files …`, unchanged from spec 003;
  - `MCP replay: N files in client mode, M in door mode (x2 pause styles), 1 exempt` (SC-001).

## 3. Core only, A2A only, MCP only

```sh
uv venv --python 3.11 ../.core-venv && uv pip install --python ../.core-venv dist/*.whl
../.core-venv/bin/python -I tests/core_only.py        # core only: ok

uv venv --python 3.11 ../.a2a-venv && uv pip install --python ../.a2a-venv "$(ls dist/*.whl)[a2a]"
../.a2a-venv/bin/python -I tests/a2a_only.py          # a2a only: ok

uv venv --python 3.11 ../.mcp-venv && uv pip install --python ../.mcp-venv "$(ls dist/*.whl)[mcp]"
../.mcp-venv/bin/python -I tests/mcp_only.py          # mcp only: ok
```

`mcp_only.py` imports `ext_r2c.mcp`, then builds a server with one tool and one source tool. It
checks that `server/discover` declares the key, and that no `a2a`, `langchain` or `langgraph`
module was loaded (constitution VIII).

## 4. Scenarios to check by hand

| Scenario | Test | What to look for |
|---|---|---|
| A question answered, both pause styles | `test_mcp_serve.py` | a flat `requestedSchema` and the R2C object in `_meta`; the derived answer (SC-002, SC-003) |
| Approval of a direct call | `test_mcp_approve.py` | the tool's counter is 1 after allow or edit, and 0 otherwise (SC-004) |
| Bad responses, replayed round, forged state | `test_mcp_answers.py` | the source received 0 answers; the next result is the one the standard names (SC-005) |
| Not activated, no form support | `test_mcp_activation.py` | 0 R2C `_meta` entries; `declined` without forms (SC-006) |
| Two owners, one context; a busy context | `test_mcp_threads.py` | two thread ids; the second call refused (SC-007) |
| Server rebuilt on fixed keys | `test_mcp_restart.py` | checkpoint completes; live ends with "lost" (SC-008) |
| Client fetch | `test_mcp_client.py` | 0 requests to another host (SC-009) |
| Every example | `test_mcp_replay.py` | one test per file and mode |

## 5. Lint and leak scan

```sh
uvx ruff check --select F src tests
```

Before every commit, run the leak scan on the staged added lines. It must report 0 hits.
