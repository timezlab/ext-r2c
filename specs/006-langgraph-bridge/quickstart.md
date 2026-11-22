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

The dev group brings `langchain>=1.4.6,<2`, `langchain-core>=1.6.10,<2`, `langgraph>=1.2.12,<2` and
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

```sh
../.ci-venv/bin/pytest -q -p no:cacheprovider tests/test_langgraph_settle.py -k mutation
```

Expected: the test removes the settle step in a copy of the module under test and shows the strict
model's test fails without it. The suite's mutation list ([contracts/suite-changes.md](contracts/suite-changes.md))
is a scratch run whose result ("N of N mutants died") is recorded in `research.md`.

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

A reader can see the one-line promise (FR-001) in a Python session on the langgraph-only venv, with
the scripted model of `tests/langgraph_models.py`:

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
