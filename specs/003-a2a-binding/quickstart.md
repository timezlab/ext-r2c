# Quickstart: validating the A2A binding

Commands run from `python/` unless said otherwise. They are the same as CI
(`.github/workflows/python.yml`).

## 1. Build and install

```sh
rm -rf dist && uv build
uv venv --python 3.11 ../.ci-venv
uv pip install --python ../.ci-venv dist/*.whl --group dev
```

The dev group now brings `a2a-sdk[http-server,sqlite]`. Repeat with 3.12 and 3.13 before
claiming done (SC-009).

## 2. Full suite on the installed wheel

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning
```

Expected:
- every test passes;
- the summary line reports the replay as
  `A2A replay: N files in client mode, M in door mode (x2 pause styles), 3 exempt` (SC-001).

## 3. Core only, and A2A only

```sh
uv venv --python 3.11 ../.core-venv && uv pip install --python ../.core-venv dist/*.whl
../.core-venv/bin/python -I tests/core_only.py        # core only: ok

uv venv --python 3.11 ../.a2a-venv && uv pip install --python ../.a2a-venv "$(ls dist/*.whl)[a2a]"
../.a2a-venv/bin/python -I tests/a2a_only.py          # a2a only: ok
```

`a2a_only.py` imports `ext_r2c.a2a`, builds an app and a card, and checks that no `mcp`,
`langchain` or `langgraph` module was loaded (constitution VIII).

## 4. Scenarios to see by hand

| Scenario | Test | What to look for |
|---|---|---|
| Question answered, both pause styles | `test_a2a_serve.py` | the same wire for `checkpoint` and `live` (SC-002) |
| Bad answers | `test_a2a_answers.py` | the source received 0 answers; the next status per the standard (SC-003) |
| Not activated | `test_a2a_activation.py` | 0 R2C Parts, 0 R2C metadata; no echoed header (SC-004) |
| Two owners, one context; a second task | `test_a2a_threads.py` | two thread ids; the second task REJECTED (SC-005) |
| Restart on SQLite | `test_a2a_restart.py` | checkpoint completes; live ends FAILED with "lost" (SC-006) |
| Hand-written executor | `test_a2a_helpers.py` | the same R2C wire as the door (SC-007) |
| Client fetch | `test_a2a_client.py` | 0 requests to another host (SC-008) |
| Every example | `test_a2a_replay.py` | one test per file and mode |

## 5. Lint, leak scan

```sh
uvx ruff check --select F src tests
```

Run the leak scan of the staged added lines before every commit (0 hits).
