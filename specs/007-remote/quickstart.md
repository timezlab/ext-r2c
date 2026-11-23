# Quickstart: validating `Remote`

Run commands from `python/` unless a step says otherwise. They are the commands CI runs
(`.github/workflows/python.yml`). Nothing here starts a network port or needs a key: the model is a
scripted chat model, the round trips run over the in-process transports of the doors' suites, one app
served with its own lifespan, and the restart tests use SQLite files in a temporary folder.

## 1. Build and install

```sh
rm -rf dist && uv build
uv venv --python 3.11 ../.ci-venv
uv pip install --python ../.ci-venv dist/*.whl --group dev
```

The dev group brings both doors' SDKs, `langchain`, `langgraph` and the SQLite saver. `pyproject.toml`
does not change for this spec (FR-036). Repeat with Python 3.12 and 3.13 before claiming done.

## 2. The facts the design leans on

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider tests/test_remote_spike.py
```

Expected: every test passes. They pin the facts of research R1 to R5, R8 and R9 on the installed set:
the MCP router's own matching decides MCP's paths (with and without `auth`); `/mcp` is MCP's exactly; an
outer authentication middleware reaches both doors; an MCP server with no tools but skills, a resource
and a prompt starts and lists; `AgentSource` is not runtime-checkable; a LangChain-like object is not a
routine; `Approve(answer_by="caller")` constructs. A failing one means the plan changes before code does.

## 3. The one door change (A1)

```sh
../.ci-venv/bin/pytest -q -p no:cacheprovider tests/test_a2a_serve.py
```

Expected: an exception thrown into the A2A app's lifespan at its `yield` still closes the request
handler. (Before the fix this test fails: the handler stays open.)

## 4. `Remote`, story by story

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider tests/test_remote_*.py
```

Expected: every test passes. In particular:

- one `Remote` over a real LangGraph graph with a scripted model, a real checkpointer, two tools and
  `mcp_tool=True`, served as one app: an A2A caller and an MCP caller each get a pause, answer it and get
  the reply; the two threads differ; one context id over both doors shares nothing (SC-003);
- both doors answer at their paths, `/mcp` with no redirect; start and stop close both doors; a failing
  door start leaves neither running; a second `app()` raises (SC-007, SC-008);
- one test per row of the build-problem table: the error type, a message that names the argument, no app,
  several mistakes in one error (SC-005);
- on A2A: an approval with the tool's `title` and `subject`; `allow` runs the tool once; `deny` with a
  reason does not run it and the model gets the reason; a wrong answer is asked again with the same id
  and `errors` (SC-001);
- on MCP: `approve=["publish_page"]` asks before a direct call and runs the tool once after `allow`;
  no approval `Remote` serves is `answer_by: caller` (SC-004);
- a paused A2A task and a paused MCP call survive a rebuild over the same SQLite files and the same
  request-state keys; without them one warning per door says a restart loses the pause (SC-001, SC-006);
- skills, a resource, a prompt and the agent tool on MCP, with the A2A card unchanged by them;
- an executor in the shape of the official Currency sample, served unchanged on A2A: an activated
  `R2CClient` gets the text-only `input-required` and continues in text (SC-002);
- `expose=["a2a"]` and `expose=["mcp"]` serve only their door; the other's module is not in
  `sys.modules`; a task store, an owner resolver, a request-state policy and an allowed host each take
  effect on their door; `middleware=` wraps both (SC-008).

## 5. The import rules and the single-extra checks

```sh
../.ci-venv/bin/pytest -q -p no:cacheprovider tests/test_packaging.py
../.core-venv/bin/python -I tests/core_only.py
../.a2a-venv/bin/python -I tests/a2a_only.py
../.mcp-venv/bin/python -I tests/mcp_only.py
../.lg-venv/bin/python -I tests/langgraph_only.py
```

Expected: `ext_r2c.remote` imports no bridge and loads a door only inside a function; `import ext_r2c` does
not load it; `from ext_r2c import Remote` works with no extra, and `Remote(expose=["a2a"], ...)` without
`[a2a]` raises an `ImportError` that names `ext-r2c[a2a]` (SC-010). Venvs are built as CI builds them (see
the workflow); each script runs with `-I`.

## 6. A mutation check on the safety rows

Not a committed test: a scratch script changes one thing in the installed `Remote` (or in `a2a/app.py`),
runs the tests of that area, and puts the file back. Each mutant must die: skip the `approve` name check;
skip the `answer_by` check; drop the `finally` of A1; route `/mcp` to A2A; run the A2A lifespan only; let
`app()` run twice. Put a file back from a copy made before, **not** by reinstalling: `uv` hard-links
installed files from its cache, so an edit of an installed file also edits the cached wheel (use
`UV_LINK_MODE=copy` for the venv, or restore from the copy and `diff -r src/ext_r2c
../.ci-venv/lib/python3.*/site-packages/ext_r2c`). The result ("N of N mutants died") goes into
`research.md`.

## 7. The whole suite, and the docs

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider
```

Expected: everything passes on 3.11, 3.12 and 3.13; every replay is unchanged; `git diff --stat d07f9c6
-- ../standard` is empty (`d07f9c6` is the commit that opened this spec; work goes straight to `main`, so
`main` itself is no base to compare with). Then the leak scan of the commit (the maintainer's pattern, run by the commit script)
and the docs of FR-038. SC-012 is read by the maintainer: from the spec, this plan and the ADR, say for each
argument of `Remote` which door serves it, what happens when none does, and which identity each door reads.
