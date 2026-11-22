# Quickstart: validating the LangGraph bridge

Run commands from `python/` unless a step says otherwise. They are the same commands CI runs
(`.github/workflows/python.yml`). Nothing here starts a network port or needs a key: the model is a
scripted chat model, the round trips run over the in-process transports of the replay kits, and the
restart tests use a SQLite file in a temporary folder.

## 1. Build and install

```sh
rm -rf dist && uv build
uv venv --python 3.11 ../.ci-venv
uv pip install --python ../.ci-venv dist/*.whl --group dev
```

The dev group brings `langchain>=1.4.6,<2`, `langchain-core>=1.6.10,<2`, `langgraph>=1.2.14,<2` and
`langgraph-checkpoint-sqlite>=3.1.3,<4`, besides the doors' packages. Repeat with Python 3.12 and 3.13
before claiming done.

## 2. The library facts the design leans on

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider tests/test_langgraph_spike.py
```

Expected: every test passes. They pin the facts of research R3, R5, R9, R11, R12 and R14 on the
installed set: a callback handler sees a tool start only when its body runs; `nostream` hides tokens
only; a `per_call` interrupt's response schema lists its decisions; a state update settles a pending
approval in both modes; the model node's update carries `structured_response`; parallel interrupts
list in a stable order. A failing one means the plan must change before code does.

## 3. The bridge, story by story

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider tests/test_langgraph_*.py tests/test_core_pause_lost.py tests/test_agent_source.py
```

Expected: every test passes. In particular:
- the shared suite S1 to S10 passes for the real source and still passes for both fakes (SC-001);
- a real in-process A2A round trip and a real in-process MCP round trip each serve one wrapped graph
  with a pause and an answer, and the reply text equals the script's (SC-002);
- the SQLite restart tests answer a pause in a new graph over the same file, in `per_call`,
  `batched` (asked again from its first call) and for a hand-written `interrupt()`, each tool body
  counted once and the request ids equal (SC-003);
- two gated calls in one turn, in both modes: two asks, one at a time, in the model's order; the
  allowed call ran once and the denied one never (SC-004);
- a decision the graph would refuse is refused by the bridge with no graph call, and the same thread
  then resumes with a correct answer, in both modes (SC-005);
- no path that yields an approval addresses the caller (SC-006);
- the first reply chunk is read before the gated model produces its last token (SC-007);
- cumulative usage equals the sum of the model calls with a restart in the middle, and carries no
  `cost` or `duration_ms` (SC-008);
- a new input on a paused thread reaches a normal reply against the strict model (SC-009).

## 4. The mutation check on the settle and on the suite

There is no test for this step: a mutation run is a scratch script that is not committed. It changes one
thing in the installed bridge (or in a copy of the suite), runs the tests of that area, and puts the file
back; a mutant that is not caught is a hole in a test, or an equivalent change that is named. The result
("N of N mutants died") of each phase is recorded in `research.md` (R17, and R19 for the review fixes); the
suite's mutation list is in [contracts/suite-changes.md](contracts/suite-changes.md).

To see SC-009 by hand: in the installed copy of `ext_r2c/bridges/langgraph/_settle.py` make `settle` return
`False` on its first line, and run

```sh
../.ci-venv/bin/pytest -q -p no:cacheprovider tests/test_langgraph_settle.py
```

Expected (checked 2026-11-22 on 3.13): 20 of the 31 tests fail, those that send a new message to a thread with
a call nothing answered (the strict model refuses a history with such a call). Put the file back from a copy
you made before, **not** by reinstalling: `uv` hard-links the files it installs from its cache, so an edit of
the installed file edits the cached wheel as well, and a reinstall then brings the edited file back. (Install
the venv with `UV_LINK_MODE=copy` and a reinstall does restore it.) Check with
`diff -r src/ext_r2c ../.ci-venv/lib/python3.*/site-packages/ext_r2c`.

## 5. The whole suite

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider
```

Expected: everything of specs 001 to 005 still passes, with the replays of 003 and 004 reporting the
same counts as before (the bridge adds no example to `standard/`).

## 6. Core only, A2A only, MCP only, LangGraph only

```sh
uv venv --python 3.11 ../.core-venv && uv pip install --python ../.core-venv dist/*.whl
../.core-venv/bin/python -I tests/core_only.py        # core only: ok, and no langgraph module loaded

uv venv --python 3.11 ../.lg-venv && uv pip install --python ../.lg-venv "$(ls dist/*.whl)[langgraph]"
../.lg-venv/bin/python -I tests/langgraph_only.py     # langgraph only: ok
```

`langgraph_only.py` builds a graph, runs it through the `Driver`, answers a pause, and checks that no
`a2a` and no `mcp` module was imported (SC-010). The a2a-only and mcp-only runs stay as they are. A
last check blocks the `langgraph` import and expects the `ImportError` to name `ext-r2c[langgraph]`.

## 7. The wrap, by hand

A reader can see the one-line promise (FR-001) in a Python session on any venv that has the extra (run it
from `tests/`, for the scripted model of `tests/langgraph_models.py`, which needs only `langchain_core`):

```python
from ext_r2c.bridges.langgraph import LangGraphAgent
agent = LangGraphAgent(graph)   # graph: a compiled agent with a checkpointer
```

Expected: `agent.pause == "checkpoint"`, `agent.card.name == graph.name`, and a `Driver(agent)` runs
it. Wrapping a graph with no checkpointer fails at once with a message that names the missing piece;
wrapping one on an in-memory saver warns once.

## 8. Imports and the leak scan

```sh
../.ci-venv/bin/pytest -q -p no:cacheprovider tests/test_packaging.py
git diff --cached -U0 | grep -n '^+' | grep -iE '<the private-token pattern>' || echo clean
```

Expected: the import rules hold (`bridges/langgraph/` imports `ext_r2c.core` and the extra's packages
only; no other module imports it) and the scan finds nothing in the added lines (constitution VI).
