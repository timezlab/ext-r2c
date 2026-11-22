---
description: "Task list for 006-langgraph-bridge"
---

# Tasks: LangGraph bridge (`ext_r2c.bridges.langgraph`)

**Input**: design documents in `specs/006-langgraph-bridge/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII asks for tests first, run against the installed wheel, with real
`langgraph` and `langchain` and a scripted chat model as the only fake. In every phase:
1. write the phase's tests first;
2. run them and confirm they fail for the expected reason;
3. only then write production code.

If a test passes on its first run, say so in the phase's report and prove it is not vacuous by a
**mutation check**: break the line of production code it guards, watch the test fail, restore.

**Organization**: the ten phases of the plan's delivery order. `/speckit-implement` runs **one phase
per go**: finish the phase, verify, commit, report in Vietnamese, stop.
- Phases 1 and 2 have no story label: the setup and the foundation every story uses.
- Phase 3 is the MVP (US1). Phase 4 finishes US1 through the two doors.
- Then US2 → US3 (P1), US4 → US5 (P2), US6 (P3); phase 10 closes everything.
- Phases 3, 5, 7 and 8 build **first cuts** of `_handler.py`, `_pauses.py` and `_usage.py` on purpose
  (plan, "Order"); a later phase replaces each first cut, test first.

## The five points of the plan, answered (2026-11-22)

The maintainer answered "follow the recommendations" for all five. They are settled; the tasks below
rely on them.

| Point | Settled as | Where it shows |
|---|---|---|
| 1. `completed` structured reply under `ToolStrategy` has no reply text | **A**: leave it; the reply is the AI messages' text | T076 pins it; T094 says it in the README |
| 2. A per-run callback handler is not "a hook" (FR-001) | **A**: use the handler; the graph object is never touched | T030, T070; T093 says it in the ADR |
| 3. The constitution's Technical Constraints line | **A**: PATCH 1.1.1 → 1.1.2 with the extra | T009 |
| 4. The caller declines the `input_required` question | **A**: the run ends `done`, the graph is not called | T076, T083 |
| 5. A `per_call` payload with no readable `response_schema` | **A**: the run ends `failed` before any ask | T045, T051 |

## Adjustments this task list makes to the plan

Each is small, each is recorded as a dated note in [plan.md](plan.md); none changes the design.

1. **`_usage.py` has a first cut in phase 3, not phase 7.** The shared suite's shape is
   `["ask", "answer", "reply", "usage", "done"]`, so S1 needs a `UsageEvent` in phase 3. The first cut
   sums tokens from the checkpoint; phase 7 adds the model name, the restart proof (SC-008) and the
   edge cases.
2. **An all-absent usage is not sent.** R2C-USAGE-1 says a usage has at least one of `input_tokens`,
   `output_tokens`, `duration_ms`, `cost`; a `model` alone does not count. When no message reported a
   token count, no `UsageEvent` is yielded (the plan says "a total no message reported is absent").
3. **`tools.py` is created in phase 5** with one private helper (`schema_of`), because an approval's
   `edit` needs the tool's schema; phase 9 adds the public names to the same file.
4. **The doors' size-limit test uses reply text in phase 4 and a file block in phase 7**, because file
   blocks are phase 7's work.
5. **The shared suite runs on an `InMemorySaver` store in phase 3.** SQLite is exercised by the restart
   tests (phase 6), which drive the `Driver` directly.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US6 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `rm -rf dist && uv build`;
  2. recreate `../.ci-venv`, install the wheel and the `dev` group (Python 3.11);
  3. `../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider` (the whole suite: the tests
     of specs 001–005 must still pass unchanged);
  4. `../.core-venv` with the wheel alone: `python -I tests/core_only.py`;
  5. `../.a2a-venv` with `wheel[a2a]`: `python -I tests/a2a_only.py`;
  6. `../.mcp-venv` with `wheel[mcp]`: `python -I tests/mcp_only.py`;
  7. from phase 3 on, `../.lg-venv` with `wheel[langgraph]` and no dev group:
     `python -I tests/langgraph_only.py`;
  8. `uvx ruff check --select F src tests`;
  9. repeat 1–3 on Python 3.12 and 3.13 at the end of phases 1, 3 and 10 (and when a task says so);
  10. leak-scan the staged added lines (must be 0);
  11. commit with an explicit pathspec and no co-author trailer. **Never push.**

## Path conventions

- Package: `python/src/ext_r2c/bridges/langgraph/`; tests: `python/tests/`.
- Test modules may import the package's private modules (`ext_r2c.bridges.langgraph._reply`, …): they
  test the installed wheel.
- Async tests use `asyncio.run(asyncio.wait_for(coro, 10))`, as `agent_source_suite._run` does. A
  checkpoint test that restarts a "process" builds a **new graph, a new agent and (for SQLite) a new
  saver** over the same store, and shares only the counters the test passes in.
- **Warnings.** `-W error::UserWarning` is on. A test that wraps a graph on an `InMemorySaver` expects the
  D11 warning (`pytest.warns(UserWarning)`) or uses `wrap(graph, **options)` of `langgraph_graphs.py`,
  which ignores that one warning and nothing else. If a LangChain or LangGraph call raises another
  warning, handle it in the builder where it is raised and record its category in `research.md`; never
  relax the flag.
- All fixture content is invented (constitution VI): tools such as `deploy_release`, `send_notice`,
  `publish_page`; owners `owner-1`; `example.com` only; no real people, hosts or local paths. Files go
  in `tmp_path`.
- The scratch probes of the plan's research stay out of the repo.
- The scripted model (`tests/langgraph_models.py`, T004) is a **pure function of the message history**:
  a new model object after a "restart" must say the same thing (R17). Counters live in objects the test
  passes in, never in the model.

---

## Phase 1: Packaging, vet and spike

**Goal**:
- The `[langgraph]` extra is vetted on the day it changes, and has the bounds R1 chose; the dev group
  carries what the tests need; the constitution says the same (PATCH 1.1.2).
- `ext_r2c/bridges/langgraph/` exists, is scanned by the import rules, and raises an `ImportError` that
  names the extra.
- The scripted model and the graph builders exist.
- Every library fact the design leans on is pinned by a test.

**Independent test**: `test_packaging.py`; `core_only.py`; `test_langgraph_spike.py`.

- [ ] T001 Repeat the vet of R1 with the `security-audit` skill, on the day the dependencies change, and
  write the result under R1 of `specs/006-langgraph-bridge/research.md` ("Vet repeated on <date> by
  T001"):
  - OSV query for `langchain`, `langchain-core`, `langgraph`, `langgraph-checkpoint`,
    `langgraph-prebuilt`, `langgraph-checkpoint-sqlite` and `aiosqlite` (`MAL-` advisories: must be none;
    list the advisories that apply to the ranges);
  - upload dates of the lowest versions (`langchain` 1.4.6, `langchain-core` 1.6.10, `langgraph` 1.2.12,
    `langgraph-checkpoint-sqlite` 3.1.3: each older than two weeks), yanked files, wheels for CPython
    3.11, 3.12, 3.13, no install script;
  - the lowest-direct check again, in a scratch venv: `uv pip install --resolution lowest-direct` for the
    three pins resolves; `HumanInTheLoopMiddleware(interrupt_mode="per_call")` and `"batched"` are
    accepted on that set; `langchain` 1.4.5 raises `TypeError` on the keyword (this is why 1.4.6 is the
    floor);
  - **stop and tell the maintainer** if a `MAL-` advisory, a yanked release, a changed maintainer or a
    changed dependency list shows up. If the floor moved, use the new one in T008.
- [ ] T002 [P] Extend `python/tests/test_packaging.py` (test first):
  - `FORBIDDEN` gains `langchain_core`.
  - **`test_extras`**: the `langgraph` extra has exactly three requirements, `langchain`, `langchain-core`
    and `langgraph`, with `>=1.4.6`, `>=1.6.10` and `>=1.2.12` and each with `<2` (the wheel writes the
    names in lower case; compare as the `mcp` check does); none starts with `langgraph-checkpoint`,
    `a2a-sdk` or `ext-r2c` (no checkpointer: FR-027). The old "requires something" assertion goes.
  - **`LANGGRAPH_ALLOWED_TOP_LEVEL`** = `ALLOWED_TOP_LEVEL | {"langgraph", "langchain_core"}`; generalise
    `_imports` to take the folder's segments (`"bridges", "langgraph"`, not a slash path) and add
    **`test_langgraph_bridge_imports_only_allowed_modules`**: every absolute import under
    `ext_r2c/bridges/` is stdlib or allowed, and an `ext_r2c` import starts with `ext_r2c.core` (the
    existing `_bad_imports` rule). The test asserts the folder exists
    (`ext_r2c/bridges/langgraph is not in the installed wheel`).
  - **`test_bridges_package_imports_nothing`**: `ext_r2c/bridges/__init__.py` has no import at all.
  - **`test_no_other_module_imports_a_bridge`**: every file of `ext_r2c/core`, `a2a` and `mcp` has no
    import of `ext_r2c.bridges` (FR-004; the existing scans already refuse it, this names the rule).
  - **`test_langgraph_import_loads_no_door`**: a subprocess (`python -I`) that imports
    `ext_r2c.bridges.langgraph` has no `a2a` and no `mcp` module in `sys.modules` (SC-010).
  - **`test_langgraph_import_without_the_extra_names_it`**: a subprocess that sets
    `sys.modules["langgraph"] = None` and `sys.modules["langchain_core"] = None` before the import gets
    an `ImportError` whose message contains `ext-r2c[langgraph]`.
- [ ] T003 [P] Extend `python/tests/core_only.py`: add `langchain_core` to its `FORBIDDEN` tuple (it
  already lists `langchain` and `langgraph`); the comment says why. No other change: `a2a_only.py` and
  `mcp_only.py` stay as they are.
- [ ] T004 [P] Create `python/tests/langgraph_models.py`, the scripted chat model (R17):
  - `Scripted(BaseChatModel)`: `script` is a function from the message history to a turn
    (`Say(text)` or `Call(("tool", {args}), ...)`, with optional `text` before the calls); it must be a
    pure function of the history. `_generate` and `_astream` agree (a `updates`-only stream calls
    `_generate`); `bind_tools` returns the model itself.
  - **streaming**: the text goes word by word, as `AIMessageChunk`s; tool calls and `usage_metadata`
    come on a last chunk; `stream=False` makes it a model that gives one whole message.
  - **`strict=True`**: raises when the history holds an AI message with a tool call that has no
    `ToolMessage` after it (what real providers do: finding 6).
  - **`gate`**: an object holding an `asyncio.Event` and a token count `k`; the model waits for the event
    after `k` tokens of a turn (for SC-007). A `closed` flag is set in the `finally` of `_astream`, so a
    test can see the stream was closed.
  - **`tags`**: the model can be returned `with_config(tags=["nostream"])`.
  - **`usage`**: each AI message carries `usage_metadata` with numbers the test sets
    (`Say(text, tokens=(input, output))`), and `response_metadata["model_name"]` when a name is set.
  - **`calls`**: a counter object the test passes in, counting model calls (never kept in the model).
  - Later phases extend it, test first (reasoning blocks, file blocks, a structured reply).
- [ ] T005 [P] Create `python/tests/langgraph_graphs.py`, the builders:
  - `agent(model, tools, saver, *, middleware=(), response_format=None, name="agent")` over
    `langchain.agents.create_agent`.
  - Counted tools with invented names (`deploy_release`, `send_notice`, `publish_page`) whose bodies add
    to a `Counter` the test passes in.
  - `memory_saver()` (an `InMemorySaver`), `sqlite_saver(path)` (an async context manager yielding an
    `AsyncSqliteSaver` on a file in `tmp_path`), and `restart(path)` (a new saver, so a new graph and a
    new agent can be built over the same file).
  - `wrap(graph, **options)` is added in phase 3, when `LangGraphAgent` exists.
- [ ] T006 Write `python/tests/test_langgraph_spike.py`. Each test pins one library fact the design leans
  on, with the scripted model and `create_agent`; a failing one stops the phase, and `research.md` and
  `plan.md` are updated before anything else. Test 2 pins a fact whose failure would be good news
  (the design could be simpler): record it and tell the maintainer, do not just fix the test.
  1. `test_interrupt_mode_is_accepted_and_both_modes_pause` (R1): `HumanInTheLoopMiddleware(interrupt_on=
     {...}, interrupt_mode="per_call")` and `"batched"` build, and a gated call pauses in each.
  2. `test_tasks_stream_cannot_tell_a_paused_tool_from_a_running_one` (R3): in `per_call`, the `tasks`
     stream starts a `tools` task for every call of the turn, those the middleware then pauses included.
  3. `test_stream_parts_are_typed` (R3): `astream(stream_mode=["messages", "updates"], version="v2")`
     yields dicts with `type`, `ns`, `data`; `messages` data is `(message_or_chunk, metadata)`, `updates`
     data is `{node: update}`.
  4. `test_pending_interrupts_are_read_from_the_state` (R8): after a pause, `aget_state(config).interrupts`
     lists `Interrupt(id, value)` and `Interrupt.response_schema` (a plain dict) is readable.
  5. `test_handler_sees_a_tool_start_only_when_the_body_runs` (R3, R4): an `AsyncCallbackHandler` with
     `run_inline = True` in `config["callbacks"]`: a call paused by the middleware and a denied call fire
     nothing; an approved one fires `on_tool_start` (with `tool_call_id` and `inputs`) then `on_tool_end`
     with the `ToolMessage`; a handled `ToolException` ends with `status="error"`; a raising tool fires
     `on_tool_error` and the stream raises.
  6. `test_a_pause_inside_a_tool_is_a_graph_bubble_up` (R3): a tool whose body calls `interrupt()` gives
     `on_tool_start`, then `on_tool_error` with an error that `isinstance(..., GraphBubbleUp)`; after the
     resume the body restarts from its top: `on_tool_start`, `on_tool_end` with `status="success"`; the
     body ran twice.
  7. `test_nostream_hides_tokens_only` (R5): a model returned with the tag `nostream` gives no chunk, then
     one whole `AIMessage` at the node's end whose part metadata carries no tag; the handler's
     `on_chat_model_start` receives the tags and `on_llm_end` the message, whose `id` equals the id of
     the whole message that arrives.
  8. `test_a_model_that_does_not_stream_gives_one_whole_message` (R5): not both chunks and the whole
     message; chunks of one call share an id.
  9. `test_per_call_interrupt_carries_a_response_schema` (R9): the payload keys (`type: "tool_approval"`,
     `tool_call_id`, `name`, `args`, `description`); the schema lists each allowed decision as
     `properties.type.const`; with several decisions it has `$defs` and `oneOf`, with one it is that
     decision's schema; the `edit` schema's `edited_action.name` is a `const` equal to the tool.
  10. `test_batched_interrupt_payload` (R9): `action_requests` and `review_configs` with
      `allowed_decisions`; `response_schema` is `None`.
  11. `test_resume_shapes` (R9): `Command(resume={interrupt id: value})` for `per_call` with
      `{"type": "approve"}`, `{"type": "reject", "message": ...}` (and without a message),
      `{"type": "edit", "edited_action": {"name", "args"}}`, `{"type": "respond", "message": ...}`; for
      `batched`, `{"decisions": [...]}` in position order; the tool result in each case.
  12. `test_a_refused_decision_per_mode` (spec findings 2 and 3): a `per_call` decision the call does not
      accept raises and **leaves the thread intact** (a retry works); a `batched` resume with the wrong
      count or a disallowed type raises `ValueError` and **leaves the thread unable to continue** (a
      later correct resume fails the same way). This is why FR-020 exists.
  13. `test_a_state_update_settles_a_pending_approval_in_both_modes` (R11): with `strict=True`, a new
      input on a paused thread fails with the dangling-call error (the baseline); after
      `aupdate_state(config, {"messages": [...]})` with no `as_node` the new input reaches a reply, in
      both modes; in `per_call`, a tool task that finished inside the unfinished step has its
      `ToolMessage` in `state.tasks[i].result["messages"]`; only the ungated tool ran, in `per_call`,
      and none in `batched`.
  14. `test_the_model_update_carries_structured_response` (R12): with `ToolStrategy(Schema)` and
      `ProviderStrategy(Schema)`, the model node's `updates` part holds `structured_response` and the
      messages; the graph has a `structured_response` channel; `ToolStrategy` streams no text,
      `ProviderStrategy` streams the JSON as text chunks. Record the category of any warning raised
      when a pydantic `structured_response` is read back from a SQLite checkpoint.
  15. `test_parallel_interrupts_list_in_a_stable_order` (R14): three parallel nodes that each call
      `interrupt()` list in node order in three runs, with one interrupt per task; two `interrupt()`
      calls in a row in one node appear one after the other, the node restarting from its top each time.
  16. `test_a_sqlite_restart_keeps_interrupt_ids` (R8): a new graph over the same SQLite file lists the
      same pending interrupt ids and the same `response_schema`; each tool body ran once; ids differ
      between two graphs on different files.
  17. `test_content_blocks_and_usage` (R6, R7): a completed message's `content_blocks` gives `text`,
      `reasoning`, `image`, `audio`, `video`, `file` (with `base64` or `url`, and `mime_type`) and
      `non_standard`; a streaming chunk's `reasoning` block has the text in its `reasoning` field while
      `chunk.text` is empty; an `image` with only an `id` has no data; `usage_metadata` holds
      `input_tokens`, `output_tokens`; `response_metadata["model_name"]` names the model.
  18. `test_a_human_message_takes_standard_blocks` (R18): `HumanMessage(content_blocks=[...])` with a
      `text` block and an `image`, an `audio`, a `video` and a `file` block (`base64` and `url`, each with
      `mime_type`) reaches the model as given.
  19. `test_langchain_tool_facts` (R16): `tool.tool_call_schema` is the model-visible schema (a pydantic
      class or the dict itself); for a pydantic `args_schema`, `get_input_schema().model_fields` also
      lists `InjectedState`, `InjectedStore`, `ToolRuntime`, `InjectedToolCallId` and `InjectedToolArg`
      arguments, and `tool.args` does not; for a dict `args_schema` `get_input_schema()` is a wrapper
      around a tool call, not the schema; `ainvoke` runs a sync tool off the loop (a ticking task keeps
      ticking); a dict-schema tool is not validated by LangChain (a wrong key fails as `TypeError`).
  20. `test_the_scripted_model` (R17): `GenericFakeChatModel` cannot stream a tool-call turn with empty
      text (`No generations found in stream`) and `Scripted` can; the same history gives the same
      answer from a second model object (pure); `strict=True` rejects a dangling tool call; the gate
      holds the stream after `k` tokens; the `closed` flag is set when the stream is closed early.
- [ ] T007 Build, install, and run T002, T003 and T006. Confirm the expected failures: the extra has the
  old two requirements, `ext_r2c/bridges/langgraph` is missing, `langgraph-checkpoint-sqlite` is not a
  dev dependency. The spike tests that need only the installed packages pass or fail by the facts alone.
- [ ] T008 Change `python/pyproject.toml`: `langgraph = ["langchain>=1.4.6,<2",
  "langchain-core>=1.6.10,<2", "langgraph>=1.2.12,<2"]`; the `dev` group gains the same three lines and
  `langgraph-checkpoint-sqlite>=3.1.3,<4`, under the existing comment that the group lists what the
  extras bring (a line says the SQLite saver is the tests' durable checkpointer and is never in the
  extra).
- [ ] T009 Amend `.specify/memory/constitution.md` (point 3, answered A): Technical Constraints line 98–99
  reads `langchain>=1.4.6,<2`, `langchain-core>=1.6.10,<2` and `langgraph>=1.2.12,<2` in `[langgraph]`
  (and no checkpointer); version 1.1.2, `Last Amended` today; a Sync Impact Report on top with the
  reason (R1: 1.3 to 1.4.5 pass the wrap and fail at the first approval), "Templates: no edits needed",
  and the previous report kept below it. This goes in the same commit as T008 (Governance).
- [ ] T010 Create `python/src/ext_r2c/bridges/__init__.py` (a docstring only: one subpackage per agent
  framework) and `python/src/ext_r2c/bridges/langgraph/__init__.py`: a module docstring that says what it
  is and that it imports only `ext_r2c.core` and the extra's packages; a `try:` that imports `langgraph`
  and `langchain_core` and an `except ImportError as exc: raise ImportError("... pip install
  \"ext-r2c[langgraph]\"") from exc`; an empty `__all__`.
- [ ] T011 Run T002, T003 and T006 on the wheel until green. Fix the harness, not the facts. If a fact
  does not hold, stop and update `research.md` and `plan.md` before going on. Run `core_only.py`.
  Confirm tests that passed on their first run are not vacuous (a changed premise: a wrong bound, a
  forbidden import added by hand, then restored).
- [ ] T012 Verify (3.11, 3.12 and 3.13), then commit `feat(006): the [langgraph] extra, the bridge
  skeleton and a library spike`.

**Checkpoint**: the extra and the import rules are in place, and every library fact the design leans on
is a passing test.

---

## Phase 2: The core piece and the suite (D2, D3a)

**Goal**:
- `PauseLost` is in the core, test first, with no `langgraph` installed.
- The shared suite compares a shape where a streaming source differs, and both fakes pass it.

**Independent test**: `test_core_pause_lost.py`, `test_agent_source.py`, `core_only.py`.

- [ ] T013 [P] Write `python/tests/test_core_pause_lost.py` (no `langgraph` import; contract
  `langgraph-api.md`, "The core's one addition"):
  - a checkpoint source whose `resume` raises `PauseLost("The pause for q-1 was lost; ask again.")` ends
    the run with `AnswerEvent` then `Error("lost", <that message>)`, nothing after, the thread free
    (a new `start` on it works);
  - an empty message gives the reason "The paused run was lost; ask again.";
  - a source that raises a plain `RuntimeError` still ends `Error("failed", ...)` (unchanged);
  - `PauseLost` is an `Exception`, is exported from `ext_r2c.core`, and is in `ext_r2c.core.__all__`;
  - a live source that raises it also ends `lost` (the driver does not look at the style).
- [ ] T014 [P] Change `python/tests/agent_source_suite.py` per `contracts/suite-changes.md` (a), tests
  first (the suite is the test):
  - add `shape(events)`: drop `activity`, merge consecutive `reply` into one `reply`, keep the other
    names; `SHAPE = ["ask", "answer", "reply", "usage", "done"]` replaces `FULL`; `reply_text(events)`
    joins the chunks and replaces `_replies`;
  - S1 to S4 and S6 compare `shape(...)` to `SHAPE` and `reply_text(...)` to one string; S1 to S4 and S6
    also assert the last reply chunk has `last=True` and no earlier one does (new check, FR-008);
  - S5: `["ask", "error:cancelled"]`; S7: checkpoint `["answer", "reply", "usage", "done"]`, live
    `["error:lost"]`; S8: `["ask", "answer", "error:failed"]`; S9: `["ask", "error:protocol"]`; S10
    unchanged. The per-scenario table of the contract is the checklist;
  - a unit test of the two helpers, in `tests/test_agent_source.py` (the fakes emit one reply chunk, so
    only this test can show a streaming shape before phase 3): `shape` drops `activity`, merges
    **consecutive** `reply` events into one, keeps a `reply`, `ask`, `reply` run as two replies and keeps
    `usage`; `reply_text` joins the chunks in order.
- [ ] T015 Build, install, and run T013 and `tests/test_agent_source.py`. Confirm the expected failures:
  `ImportError: cannot import name 'PauseLost'`, and for both fakes the new `last` check (each fake's
  one reply chunk has `last=False`). The structural parts of the suite and the unit test of `shape` pass
  at once: T019 proves the unit test is not vacuous.
- [ ] T016 Change `python/tests/fake_sources.py`: `_after` builds `ReplyChunk(_reply(request, answer),
  last=True)`. Nothing else changes: the fakes still emit their activity, which their own tests check.
- [ ] T017 Add `PauseLost` to the core: in `python/src/ext_r2c/core/source.py` the class (docstring from
  the contract) and, in `Driver._pump`, an `except PauseLost as exc:` branch **before** `except
  Exception`, calling `self._finish(Error("lost", str(exc) or "The paused run was lost; ask again."))`
  and returning; export it from `python/src/ext_r2c/core/__init__.py` (import and `__all__`).
- [ ] T018 Run T013 and `test_agent_source.py` until green; run `core_only.py` in the core-only venv.
- [ ] T019 Mutation check of the suite (scratch run, nothing committed), recording **"N of N mutants
  died"** under a new "Mutation check of the suite" heading in `research.md` R17: each mutant is a
  one-line change to a scratch copy of a fake, of the suite or of the driver, and the changed suite must
  fail it. The 12 that apply now (the 13th, "the wrapper never yields the second ask", needs the wrapper
  and runs in T035): the source drops its reply (S1–S4); the reply comes before the answer (S1); `usage`
  is missing (S1–S4); `usage` comes before the reply (S1); a second `usage` at the pause (S1); the
  source yields `Done` itself (S10 / protocol); the last reply chunk has `last=False` (S1); the driver
  calls `resume` on a cancelled run (S5); the source never records the answer it got (S3); the source
  swallows its exception after the ask (S8); the shape check merges non-consecutive replies (the
  unit test of `shape`); the shape check drops `usage` (S1 and the unit test). A survivor is either fixed or named as
  equivalent, with the reason.
- [ ] T020 Verify, then commit `feat(006): PauseLost in the core and a structural shape for the suite`.

**Checkpoint**: the core ends a lost pause `lost`; the fakes pass the changed suite; every mutant of the
suite died.

---

## Phase 3: Wrap, run and reply (US1, P1) 🎯 MVP

**Goal**:
- `LangGraphAgent(graph)` is an `AgentSource` (checkpoint style) that runs a real graph and streams its
  reply, with the wrap checks and the in-memory warning.
- The shared suite, S1 to S10, passes on a real graph (SC-001), and the first reply chunk is read before
  the model's last token (SC-007).

**Independent test**: `test_langgraph_wrap.py`, `test_langgraph_run.py`, `test_langgraph_suite.py`,
`test_agent_source.py`, `langgraph_only.py`.

**First cuts, on purpose** (plan, "Order"):
- `_handler.py` reports only the hidden message ids (phase 7 adds the tool events).
- `_pauses.py` asks only a hand-written valid R2C question or approval (the suite's graph); a payload of
  any other shape ends the run `failed` with "this kind of pause is not supported yet" (phases 5 and 8
  replace it).
- `_usage.py` sums the tokens (phase 7 completes it).

### Tests for User Story 1 ⚠️ (write first, watch them fail)

- [ ] T021 [P] [US1] Create `python/tests/langgraph_suite_source.py` and the suite's graph in
  `langgraph_graphs.py` (D3 b and c; `contracts/suite-changes.md`):
  - the graph: a scripted model reading the last human message. `"Write the report"` calls the tool
    `ask_question`, whose body is `interrupt(<a valid R2C question, id "q-1", one text field "title">)`
    and returns `"Got: <title>"`, or `"Declined"` when the resume value is `None`;
    `"Write the report and publish it"` calls `ask_approval`, whose body is `interrupt(<a valid R2C
    approval, id "ap-1", decisions allow and deny, subject tool_call>)` and returns `"Done"` on `allow`
    and `"Not done: <reason>"` on `deny`; after a tool result the model says that result's text, streamed
    in words, once. The model reports usage tokens, so S1 has a `usage`.
  - `SuiteSource(saver, **options)` wraps a `LangGraphAgent` over a graph built for the options: it
    records every answer that reaches `resume` in `answers`, exposes `pause` and `card`; with
    `fail_after_ask=True` the graph's tool raises after its `interrupt()` returns (S8); with
    `double_ask=True` it yields a second `Ask` right after the first one the agent yields (S9); a
    "restart" is a new graph and a new agent over the **same** saver.
  - `wrap(graph, **options)`: builds a `LangGraphAgent`, ignoring only the D11 `UserWarning`.
- [ ] T022 [P] [US1] Write `python/tests/test_langgraph_wrap.py` (R2, FR-001 to FR-004, FR-026, D11):
  - not a compiled graph: an object, and an uncompiled `StateGraph` (the message says to call
    `.compile(checkpointer=...)`): `TypeError`;
  - no checkpointer: `None`, `True`, `False`, and an object that is not a `BaseCheckpointSaver`:
    `ValueError` that says "checkpointer";
  - a state with no `messages` (`{x: int}`): `ValueError` that names the `messages` input (D1);
  - `expose_tools` holding a non-string: `TypeError`; options are keyword-only (a positional card is a
    `TypeError`);
  - the card: the argument as given; none gives `CardInfo(graph.name, "A LangGraph agent served through
    R2C.", "0.0.0")`; `pause == "checkpoint"`; a `Driver` accepts the agent;
  - an `InMemorySaver` gives exactly one `UserWarning` per construction, and the text says a pause will
    not survive a restart; an `AsyncSqliteSaver` gives none;
  - FR-001: after a run the graph is the same object, with the same checkpointer, name and nodes.
- [ ] T023 [P] [US1] Write `python/tests/test_langgraph_run.py` (R3, R5, R18; FR-005, FR-006, FR-008,
  FR-013, FR-023). Real graph and scripted model, through the `Driver`:
  - **reply**: the text equals the script's; chunks arrive as the model streams (at least three);
    exactly one chunk has `last=True` and it is the last; a one-token reply is one chunk with
    `last=True`; a turn of tool calls only has no reply chunk, no error, and ends `done`;
  - **SC-007**: with a gate after three tokens, the first reply chunk is read (with a timeout) before
    the gate is released; then the rest arrives;
  - **hold-one and `last`**: text, then a tool call, then text → one chunk set whose only `last=True` is
    the final one; text, then tools, then a final message with no text → the closing
    `ReplyChunk("", last=True)`; the leg that ends in an `Ask` leaves the held piece with `last=False`;
  - **paragraph break**: two AI messages that both have text get `"\n\n"` between them; a message with
    no text between adds nothing; `ToolMessage` and `HumanMessage` text is never reply;
  - **`nostream`**: a hidden model call's tokens and its finished message never reach the reply, while a
    non-streaming model's whole message arrives as one chunk (a two-node graph, one node tagged);
  - **threads**: the graph's `thread_id` is `ctx.thread_id`; the same thread continues (the script
    counts human messages), another thread shares nothing (FR-005);
  - **input**: a text-only `RunInput` reaches the model as `HumanMessage(content=text)`; with parts, as
    `content_blocks` (a `text` block, then `image`, `audio`, `video` by the media type's top level and
    other types as `file`; bytes as `base64`, a URL as `url`, always with `mime_type`); nothing is read,
    converted or dropped (a recording model sees it);
  - **an exception** in a tool ends the run `Error("failed", <message>)`;
  - **cancel**: cancelling the run while the model is gated closes the stream (the model's `closed` flag
    within one second) and leaves no task of the bridge running;
  - **an answer for an id nothing waits for** raises `PauseLost` in `resume` and the graph is not
    started (the model's call counter does not move) (FR-023);
  - **pure units** of `_reply` (a state machine fed with pieces, no graph): hold-one, `last`, the
    paragraph break, chunks with no id count as one message while consecutive, a hidden id is skipped.
- [ ] T024 [P] [US1] Write `python/tests/test_langgraph_suite.py`: the wrapper's own behaviour (T021) and
  the suite on a real graph. `answers` records what reached `resume` (and is empty after a cancel);
  `double_ask` makes the driver end `error:protocol` with `run.pending is None`; `fail_after_ask` ends
  `error:failed` with a reason; a restart keeps the pause (same saver); every `SCENARIOS` entry passes
  over an `InMemorySaver` store.
- [ ] T025 [US1] Change `python/tests/test_agent_source.py`: `FAKES` gains `"langgraph"`
  (`lambda **options: SuiteSource(saver, **options)` over one saver per test), so the same parametrised
  scenarios run on both fakes and the real source through the same `Driver` (SC-001).
- [ ] T026 [P] [US1] Write `python/tests/langgraph_only.py` (not collected by pytest, like
  `core_only.py`; run as `python -I tests/langgraph_only.py` in a venv with the wheel and `[langgraph]`
  only). It must be **self-contained** (`-I` removes the script's folder from the path): a hand-built
  `StateGraph` over `MessagesState` with one node that calls `interrupt(<a valid R2C question>)` and then
  returns an AI message, an `InMemorySaver`, `LangGraphAgent` through the `Driver`: a run reaches the
  `Ask`, the answer resumes it, the reply is read, `Done`. Then it asserts no `a2a` and no `mcp` module
  was imported (SC-010), and that blocking `langgraph` gives an `ImportError` that names
  `ext-r2c[langgraph]`. It prints `langgraph only: ok`.
- [ ] T027 [US1] Build, install, and run T022 to T025. Confirm the expected failures: `ImportError: cannot
  import name 'LangGraphAgent' from 'ext_r2c.bridges.langgraph'`; the two fakes still pass the suite.

### Implementation for User Story 1

- [ ] T028 [P] [US1] `python/src/ext_r2c/bridges/langgraph/_blocks.py` (input): `to_message(input)` makes
  one `HumanMessage` from a `RunInput` (R18, FR-006): text only → `content=text`; with parts →
  `content_blocks` as in the data model's "Run input → message" table.
- [ ] T029 [P] [US1] `_reply.py` (R5): the pure state machine, no graph import. `Reply.feed(piece)` takes
  a piece of text with its message id and returns the chunks to send now; `flush(last)` leaves the held
  piece; `end_turn(had_text)` returns the held piece with `last=True`, or the closing
  `ReplyChunk("", last=True)` when nothing is held but the turn had reply text, or nothing. The paragraph
  break goes before the first piece of a different message when both have text. A hidden id is skipped.
  (No JSON hold yet: phase 8.)
- [ ] T030 [P] [US1] `_handler.py`, first cut (R3, R5): `Handler(AsyncCallbackHandler)` with `run_inline =
  True`; `on_chat_model_start` notes the run's tags, and `on_llm_end` puts the message's id on the leg's
  queue as `Hidden(id)` when the tags held `nostream`. Nothing about tools yet.
- [ ] T031 [P] [US1] `_usage.py`, first cut (R7, adjustment 1 and 2): `usage_of(messages)` takes the
  checkpoint's messages after the last `HumanMessage` and sums `input_tokens` and `output_tokens` of the AI
  messages that report them; a total no message reported stays absent; returns a `Usage` or `None` when
  neither total is known (R2C-USAGE-1). No cost, no duration.
- [ ] T032 [P] [US1] `_pauses.py`, first cut (R8): read `aget_state(config).interrupts`; for each, a valid
  hand-written R2C `question` or `approval` (the core's `parse`; an approval is accepted only for a person
  or an approver) becomes a `Pause` of kind `own_request` whose request id is the object's own id; any
  other shape raises a `RuntimeError("this kind of pause is not supported yet")`. The answer maps to the
  resume value: the answer's `value` mapping, or `None` when declined.
- [ ] T033 [US1] `_leg.py` (R3, R5; decision 1 and 3 of the plan): one leg = a producer task iterating
  `astream(input, config, stream_mode=["messages", "updates"], version="v2")` into one unbounded
  `asyncio.Queue` that also receives the handler's items, and the consumer generator, the only reader,
  whose `finally` cancels the producer and awaits it. The config carries
  `{"configurable": {"thread_id": ctx.thread_id}, "callbacks": [handler]}`; the graph object is never
  touched. The consumer turns text parts into `Reply` pieces, flushes with `last=False` on a tool-call
  update, a pause or an exception, and ends a turn with `Reply.end_turn`, then `UsageEvent`
  (`usage_of`) when it is not `None`; when the stream ends with a pending interrupt it reads the pause,
  flushes, yields the `Ask` and ends. A producer exception is put on the queue and raised in the consumer.
- [ ] T034 [US1] `agent.py` (R2; FR-001 to FR-003, FR-005, FR-023, FR-026, D11): `LangGraphAgent` with the
  three wrap checks and the messages from the contract's table, the card, the options (keyword-only), and
  the `UserWarning` for an `InMemorySaver`; `run(input, ctx)` builds the message (`_blocks`) and runs a
  leg; `resume(answer, ctx)` rebuilds the pending set, matches `answer.id` (no match: `PauseLost` naming
  the id, before the graph is touched), checks the answer with the core's `check_answer` against the
  request the bridge would have asked, and runs a leg with `Command(resume={interrupt id: value})`. Export
  `LangGraphAgent` from `__init__.py`.
- [ ] T035 [US1] Run T022 to T026 on the wheel until green (T026 in `../.lg-venv`). Then the one mutant of T019
  that needed the wrapper ("the wrapper never yields the second ask": S9 must fail) and, as a scratch
  run recorded under R17 in `research.md`, these bridge mutants, each of which must make at least one
  test fail: the last chunk's `last` is `False`; a pause flushes with `last=True`; the paragraph break
  is removed; the `finally` no longer cancels the producer; `thread_id` is a constant; a hidden id is not
  skipped; `PauseLost` is replaced by `RuntimeError`; the pending-set match is skipped.
- [ ] T036 [US1] Verify (3.11, 3.12 and 3.13, with `langgraph_only.py`), then commit `feat(006): LangGraphAgent
  runs a graph and streams its reply`.

**Checkpoint**: a real graph passes S1–S10 (SC-001) and streams before its last token (SC-007).

---

## Phase 4: Both doors (US1, P1)

**Goal**: one wrapped real graph is served through a real in-process A2A round trip and a real MCP round
trip, each with a pause and an answer (SC-002); a lost pause is shown as `lost` by each door.

**Independent test**: `test_langgraph_doors.py`.

- [ ] T037 [P] [US1] Write `python/tests/test_langgraph_doors.py`, A2A half (`a2a_harness`:
  `serve`, `a2a_client`, `send`, `answer`, `kinds`; the style of `test_a2a_restart.py`). Serve
  `SourceExecutor(LangGraphAgent(graph))` with `agent_card(card, url)`, the graph being the suite's with
  one more reply before the tool call ("I will ask."):
  - the task reaches `input-required` with the question (id, title) and the first reply text;
  - the caller's answer continues the **same task**; it completes; the reply artifact is one artifact
    that continues across the pause, and its text equals the script's (`last` on its final chunk);
  - the usage appears; no event follows the terminal one.
- [ ] T038 [P] [US1] Same file, MCP half (`mcp_harness`: `serve`, `mcp_client`, `call`, `accept`; the style
  of `test_mcp_restart.py`): `mcp_server("test", R2CExtension(tools=[SourceTool(agent)]),
  security=RequestStateSecurity(keys=KEYS))`; the first call returns `InputRequiredResult` with the
  question; the retry with the answer returns the final result whose text equals the script's (the door
  gathers the text across the pause and ignores `last`).
- [ ] T039 [P] [US1] Same file, `PauseLost` per door (D2, R13): a graph on an `InMemorySaver`, a pause, a
  "restart" (a new graph and agent over a **new** `InMemorySaver`), then the answer. A2A: the task ends in
  the state the door gives a live source's lost run (read `test_a2a_restart.py`'s live case); MCP: the
  call returns the door's `LOST` text; in both, the model's call counter did not move (the graph was not
  started).
- [ ] T040 [P] [US1] Same file, size limits (R15): the A2A `SourceExecutor(agent, limits=Limits(message_bytes=
  32))` fails the task cleanly on a reply over the limit, and the MCP door with a small `Limits` returns
  `output_too_large`; the bridge itself checks no size. (A file block version is added in T065.)
- [ ] T041 [US1] Build, install, and run T037 to T040. Most should pass on their first run, because phase 3
  made the agent a real source: say so in the report, and for each test that passes at once run the
  mutation of T043 (a passing test is not yet proof). Any failure is a gap in the bridge (T042), **not**
  in the doors: if a door needs a change, stop and tell the maintainer.
- [ ] T042 [US1] Fix what T041 shows in `bridges/langgraph/` (for example how `last` and the held piece behave
  across a pause, the `Ask` after a flush), test first where a gap is found.
- [ ] T043 [US1] Mutation check, recorded under R17: with the door tests green, each of these mutants must make
  a test fail: `PauseLost` raised as `RuntimeError` (T039, both doors); the reply's held piece dropped at
  a pause (T037 text); `last=True` sent at a pause (T037, the reply would end early); the answer's id
  not forwarded to the interrupt (T037/T038 do not complete).
- [ ] T044 [US1] Verify, then commit `test(006): serve a wrapped graph through the A2A and MCP doors`.

**Checkpoint**: SC-002 holds on both doors, and a lost pause reads as `lost`.

---

## Phase 5: Approve, edit or deny tool calls (US2, P1)

**Goal**: `HumanInTheLoopMiddleware` in `per_call` and `batched` becomes one approval at a time, in the
model's order; every answer maps to the graph's decision; every answer the graph would refuse is refused
by the bridge first (SC-004, SC-005, SC-006).

**Independent test**: `test_langgraph_approvals.py`, `test_langgraph_batch.py`.

### Tests for User Story 2 ⚠️ (write first, watch them fail on the first cut)

- [ ] T045 [P] [US2] Write `python/tests/test_langgraph_approvals.py` (R8, R9; FR-014 to FR-018, FR-020).
  Two graphs on one script, `per_call` and `batched` (parametrise every test over both unless it says
  otherwise); two gated tools `deploy_release` and `send_notice` that count their calls:
  - **SC-004**: a turn with two gated calls: the caller is asked exactly twice, one at a time, in the
    model's tool-call order (try the order `send_notice`, `deploy_release`, so a sort would fail);
    allow the first and deny the second with a reason: the first body ran once, the second never; the
    model's final reply mentions the reason; no two are pending at once (`per_call`: the others stay
    pending in `aget_state`; `batched`: nothing runs until both are decided);
  - **the approval's shape**: `Subject(type="tool_call", name=<tool>, args=<the model's args>)`, title
    `Approve <tool>?`, the middleware's `description`, `answer_by` person, `decisions` in the order
    `allow`, `edit`, `deny` restricted to what the call allows; a tool allowing only `approve` and
    `reject` offers `["allow", "deny"]`; `args_schema` is set only when `edit` is offered;
  - **edit**: a tool that allows `edit`, built by `create_agent` so its schema is found: the caller edits
    the arguments and the tool runs with them, and the graph's decision names the call's own tool; a
    hand-built graph whose tool node hides the tool: `edit` is not offered; a call allowing only `edit`
    with no schema: the run ends `failed` before any ask, with a reason that says so;
  - **respond-only**: a tool allowing only `respond` is asked as a `Question` with one text field
    (`reply`, `answer_by` person); the answer text becomes the tool's result;
  - **declined**: a declined approval is `reject` with the answer's `note` as the message; a declined
    approval for a call that does not allow `reject` ends `failed` with a reason that says so, the call
    does not run, and the pause is still pending; a declined respond-only question ends `failed` the
    same way;
  - **SC-005, refusals**: a decision the call does not allow, an `edit` that renames the tool, a wrong
    count (`batched`) each end the run `failed` with readable problems, **with no call into the graph**
    (the model's counter and the saved state do not move), and **the same thread then resumes with a
    correct answer** (deliver the wrong answer through `Driver.resume`, then the right one through a new
    `Driver.resume` on the same pending request); for `per_call` and for `batched`;
  - **point 5**: a `per_call`-shaped interrupt with no readable `response_schema` (a hand-written node
    that interrupts with the four keys) ends `failed` before any ask, and the graph is not touched;
  - **order**: three gated calls in `batched` with the middle one denied: results stay in the model's
    order; in `per_call` each answer resumes only its own interrupt, by id;
  - **SC-006, the paths that exist now**: `per_call`, `batched` and a hand-written valid approval for a
    person and for an approver never yield `answer_by` of `caller`, and the bridge never answers one
    (the caller's answers are the test's); the closing walk over every path is T075.
- [ ] T046 [P] [US2] Write `python/tests/test_langgraph_batch.py` (R10, FR-019, D8). Pure units of
  `_batch.py` (record a decision, `complete()`, `next_open()`, `drop()`; the map keeps at most 1024
  records and drops the oldest first) and behaviour:
  - a batch of two: the first answer records and asks the second, with **no graph call** (counter and
    saved state unchanged); the second completes it: one resume `{"decisions": [d0, d1]}` in position
    order and the record is dropped;
  - an answer for a position when the bridge has no record (a new agent over the same saver, the restart
    in the middle) is **kept**, and the first undecided position is asked: the batch is asked again from
    its first call;
  - the record is dropped on completion, on a lost pause, and (T080) on a settle.
- [ ] T047 [US2] Build, install, and run T045 and T046. Confirm the expected failures: the first cut ends every
  middleware pause with "this kind of pause is not supported yet"; `_batch` and `_decisions` do not exist.

### Implementation for User Story 2

- [ ] T048 [P] [US2] `python/src/ext_r2c/bridges/langgraph/tools.py`, created here with one private
  helper (adjustment 3): `schema_of(tool)` returns a copy of `tool.tool_call_schema` as JSON Schema
  without `title` (R16); `tools_by_name(graph)` finds the tools of a `create_agent` graph by looking for
  a node whose `bound` has `tools_by_name`, or `None`. The public names come in phase 9.
- [ ] T049 [P] [US2] `_batch.py` (R10, D8): the bounded map and its operations, keyed by `(thread id,
  interrupt id)`, at most 1024 records.
- [ ] T050 [US2] `_decisions.py` (R9): `allowed(pause)` reads `per_call` decisions from every
  `properties.type.const` of the `response_schema` (`$defs` and `oneOf` included) and `batched` ones from
  `review_configs[i].allowed_decisions`; `offered(pause)` maps to `allow`, `edit` (only with a schema),
  `deny` and drops `respond`; `to_graph(answer, pause)` makes `{"type": "approve"}`, `{"type": "reject",
  "message"?}`, `{"type": "edit", "edited_action": {"name": <the call's tool>, "args"}}` or `{"type":
  "respond", "message"}`; `check(answer, pause)` raises `ValueError` with the readable problems for a
  decision not allowed, an `edit` the call cannot take, a batch decision with a wrong count, a declined
  answer when `reject` is not allowed.
- [ ] T051 [US2] `_pauses.py`, extended (R8; pause-mapping rows 1, 2, 3): classify in this order: a
  `per_call` approval (all four keys), a `batched` interrupt (both lists), then the hand-written kinds of
  the first cut. Build the `Approval` or, for a respond-only call, the `Question`; request ids
  `lg-<interrupt id>` and `lg-<interrupt id>-<n>`; order tool approvals by the position of the call in
  the last AI message's `tool_calls`; a `per_call` payload with no readable decision, or nothing left to
  offer, ends the run `failed` before any ask (point 5).
- [ ] T052 [US2] `agent.py`, extended: `resume` runs the checks in this order (the id is pending; the
  core's `check_answer`; the graph-side rules of `_decisions.check`); a `per_call` answer resumes only
  its interrupt, by id; a `batched` answer is recorded in `_batch`, the next undecided call is asked
  with no graph call, and the complete batch is sent in one resume in position order; a refusal raises
  `ValueError` and the pause stays pending.
- [ ] T053 [US2] Run T045 and T046 until green. Fix the bridge, not the tests; if a test is wrong, say why
  before changing it.
- [ ] T054 [US2] Mutation check, recorded under R17: each of these must make a test fail: `allow` and `deny`
  swapped; the reason is not sent as the message; the allowed set is ignored; the pre-graph validation is
  removed (the stuck-thread test); the batch is sent before it is complete; positions sent out of order;
  the `edit` name taken from the answer; tool approvals sorted instead of in the model's order; an
  approval built with `answer_by` of `caller` (SC-006).
- [ ] T055 [US2] Verify, then commit `feat(006): approvals from HumanInTheLoopMiddleware, per call and batched`.

**Checkpoint**: SC-004 and SC-005 hold in both modes; SC-006 holds for every path that exists.

---

## Phase 6: A pause survives a restart (US3, P1)

**Goal**: a pause made by one process is answered by another over the same SQLite file: each tool ran
once, the request ids are equal, a lost pause ends `lost` (SC-003).

**Independent test**: `test_langgraph_restart.py`.

- [ ] T056 [P] [US3] Write `python/tests/test_langgraph_restart.py` on a real SQLite file in `tmp_path`
  (`sqlite_saver`, `restart`): "process A" runs to the ask and is dropped (its saver closed); "process B"
  builds a new saver, graph and agent over the same file and resumes with `Driver.resume(thread, request,
  answer)` using the request saved from process A. Counters are shared:
  - **`per_call`**: the run continues with `answer`, the rest of the work, `usage`, `done`; each tool body
    ran once; the request ids before and after are equal (FR-015);
  - **`batched`**, nothing answered: the same; with the **first of two answered** before the restart:
    nothing has run, and after the restart the batch is asked again from its first call (FR-019,
    scenario 3);
  - **a hand-written `interrupt()`** (the suite's question): the same;
  - **parallel approvals**: the order of the asks is the same before and after the restart;
  - **an in-memory saver** after a "restart": the answer ends `Error("lost")` with a reason that says the
    pause was lost, and the model's counter did not move (scenario 4);
  - **an answer already applied** (delivered twice, the second through a new `Driver.resume`) and **a
    thread pruned** (`adelete_thread`): `lost`, the graph not started (scenario 5).
- [ ] T057 [US3] Build, install, and run T056. Most should pass on their first run (phases 3 and 5 built the
  pieces). Say so in the report; for each, the mutation check of T059 proves it is not vacuous. A failure
  is a gap in the bridge: test first, then fix in `bridges/langgraph/`.
- [ ] T058 [US3] Fix what T057 shows, if anything (for example a request id that depends on something that does
  not survive a restart), test first.
- [ ] T059 [US3] Mutation check, recorded under R17: each of these must make a test fail: the request id built
  from a counter or a `uuid` instead of the interrupt id; the batch record read from outside the leg; the
  pause match skipped; `PauseLost` swallowed and the graph started anyway; a tool body run twice because
  `resume` re-sends the input.
- [ ] T060 [US3] Verify, then commit `test(006): a paused graph survives a restart`.

**Checkpoint**: SC-003 holds (scenario 6, usage across a restart, closes in phase 7, T064).

---

## Phase 7: The timeline: activity, reasoning, usage, files (US4, P2)

**Goal**: the caller's UI gets tool activity, optional reasoning, cumulative usage and file artifacts, and
no more than the owner allows (SC-008).

**Independent test**: `test_langgraph_timeline.py`.

### Tests for User Story 4 ⚠️ (write first)

- [ ] T061 [P] [US4] Extend `python/tests/langgraph_models.py`, test first (its own checks go in
  `test_langgraph_timeline.py`): turns that carry **reasoning** blocks (standard `reasoning` text, plus a
  signature and an encrypted block that must never leave), **file blocks** (`image`, `file`, `audio`,
  `video` with `base64` or `url`; one with only an `id`; one invalid base64; one `non_standard`), and
  settable `model_name` and token numbers.
- [ ] T062 [P] [US4] Write `python/tests/test_langgraph_timeline.py`, tool activity (R3, R4; FR-009,
  FR-013, D5):
  - a tool call is one `tool` activity: id = the tool call's id, `name`, `label`, `running` then `done`,
    with `duration_ms`; a tool that returns `status="error"` or raises ends `failed`;
  - `running` is visible **while the tool runs**: the body awaits an event the test sets after reading
    `running` (so `running` and `done` do not arrive together);
  - a call waiting for approval has **no `running`**, in both modes; a denied call has no activity at
    all; an approved one shows `running` then `done` after the resume;
  - a tool whose body calls `interrupt()`: `running` stays across the pause, the restarted body reports
    `running` again, then `done` (a `GraphBubbleUp` is not a failure);
  - **default options**: no `args` and no `detail`; with `expose_tools={"deploy_release"}` that tool's
    activity has `args` (the call's input) and `detail` (the result text, or a failure's message, cut at
    2000 characters) and another tool's does not;
  - **an exception**: every activity still `running` is closed `failed`, then the run ends
    `Error("failed")`; a cancel emits nothing after the driver ended the run;
  - a node that calls `tool.ainvoke(...)` without passing its config shows no activity (R4: a named
    limit, pinned).
- [ ] T063 [P] [US4] Same file, reasoning (R6; FR-010): default off, no reasoning activity at all, even
  though the model reasons; `reasoning=True`: one activity per message, id `reasoning-<message id>`, type
  `reasoning`, label `Thinking`, `delta` pieces and **no `state`**; deterministic coalescing, **no
  timers**: a buffer leaves at a sentence end or a newline once it holds 40 characters, at a space near
  400, always at the message's end, at a pause, at the turn's end and just before the message's first
  reply text; a whole non-streamed message's reasoning goes out the same way; a signature, an encrypted
  block and a `non_standard` block **never** leave (R2C-ACTIVITY-5). Pure units of `_reasoning` (the
  buffer, fed with deltas) beside the graph tests.
- [ ] T064 [P] [US4] Same file, usage (R7; FR-011, SC-008): a turn with several model calls sends **one**
  cumulative `usage` of all of them, once, after the last reply chunk and before `done`; **not** at a
  pause; `model` from `response_metadata`; no `cost` and no `duration_ms`; a field the model did not
  report is absent, not zero; a turn where no message reported tokens sends **no** `UsageEvent` (R2C-USAGE-1);
  a hidden (`nostream`) message and a structured-reply message count (the tokens were spent); **with a
  restart in the middle** (SQLite, a pause between two model calls) the total equals the sum of every
  model call of the turn (SC-008, scenario 6); the turn is the messages since the last human message.
- [ ] T065 [P] [US4] Same file, files (R6; FR-012, D6): an AI message with a `file`, an `image`, an
  `audio` and a `video` block with bytes becomes an `ArtifactEvent` each, `presentation="file"`, id
  `<message id>-<block index>`, `BytesContent` with the media type, `UrlContent` for a URL, `name` from
  `extras` `filename` or `name` when it is a string; a block with no data (hosted by id), invalid base64
  or `non_standard` is **skipped** and the run goes on; blocks are read from the **completed** message in
  the `updates` part, never from chunks (a streamed model gives each file once); the A2A door with a small
  file limit fails a file artifact cleanly (the door refuses, not the bridge: R15).
- [ ] T066 [US4] Build, install, and run T061 to T065. Confirm the expected failures: no tool activity (the
  first cut's handler reports hidden ids only), no reasoning, usage only the first cut's, no artifacts.

### Implementation for User Story 4

- [ ] T067 [P] [US4] `_reasoning.py` (R6): the buffer per message id and the coalescing rules; only the
  standard `reasoning` field is read.
- [ ] T068 [P] [US4] `_blocks.py`, extended (R6): completed message → `ArtifactEvent`s per the data model's
  "Content block → artifact" table; skipped blocks logged at debug.
- [ ] T069 [US4] `_usage.py` completed (R7): the model's name (the last non-empty
  `response_metadata["model_name"]`), the restart proof, hidden and structured messages counted.
- [ ] T070 [US4] `_handler.py` completed (R3, R4; point 2, answered A): `on_tool_start` puts a `ToolStarted`
  item (id = `tool_call_id`, or the run id for a tool a node calls itself), `on_tool_end` a `ToolEnded`
  (`failed` when the message's `status` is `error`), `on_tool_error` a `ToolFailed` **unless** the error is
  a `GraphBubbleUp`; `time.monotonic()` for the duration. `expose_tools` decides `args` and `detail`
  (2000-character cut).
- [ ] T071 [US4] `_leg.py` and `agent.py` extended: the consumer turns the handler's items into
  `ActivityEvent`s; reasoning deltas go out when the option is on; completed-message blocks become
  artifacts; on an exception each still-`running` activity is closed `failed` before the exception goes on.
- [ ] T072 [US4] Run T062 to T065 until green; the A2A file-limit test too.
- [ ] T073 [US4] Mutation check, recorded under R17: each of these must make a test fail: `GraphBubbleUp`
  treated as a failure; `running` emitted at the model's request; `args` shown for an unexposed tool; the
  reasoning option ignored; a signature block sent; the coalescing threshold changed by one; `usage`
  sent at a pause; usage taken from the handler instead of the checkpoint (the restart test); a skipped
  block raising; files read from chunks (a duplicate).
- [ ] T074 [US4] Verify, then commit `feat(006): tool activity, reasoning, usage and files`.

**Checkpoint**: SC-008 holds; US4's scenarios 1 to 6 pass.

---

## Phase 8: Other pauses, and a new input (US5, P2)

**Goal**: a hand-written `interrupt()`, parallel interrupts, a structured `input_required` turn end, and a
new message on a pending approval all behave (SC-006 closed, SC-009).

**Independent test**: `test_langgraph_pauses.py`, `test_langgraph_structured.py`,
`test_langgraph_settle.py`.

### Tests for User Story 5 ⚠️ (write first)

- [ ] T075 [P] [US5] Write `python/tests/test_langgraph_pauses.py` (R8, R14; FR-014, FR-021;
  pause-mapping rows 4 to 7, 9, 10):
  - `interrupt(<a valid R2C question>)` and `interrupt(<a valid approval for a person or an approver>)`
    are asked **as they are**, with their own id, and `interrupt()` returns the answer's `value` mapping;
  - `interrupt("Which region?")`: a `Question` for a person, one `text` field (`answer`), the string as
    the title (cut at 200 characters; an empty string becomes "The agent needs input"); a mapping, a
    list and a number: that title with the value as bounded JSON (`default=str`, 2000 characters) in the
    description; the resume value is the answered text, and `None` when declined;
  - **an approval addressed to the caller** (`answer_by.role` `caller`) is **never** asked as an
    approval: it falls back to a question for a person (V);
  - **sequential** `interrupt()` calls in one node: each is asked and answered in order;
  - **parallel** interrupts (three nodes): one at a time, in the order LangGraph lists them, the same
    order after a SQLite restart; each answer resumes only its own interrupt by id; two requests with the
    same own id are not told apart, the first in order matches (pinned, and named in the contract);
  - **SC-006 closed**: a test walks **every** path that yields an approval (`per_call`, `batched`, a valid
    hand-written approval for a person and for an approver, the caller-addressed one) and asserts no
    `Approval` has `answer_by.role == "caller"` and that nothing in the bridge answers one.
- [ ] T076 [P] [US5] Write `python/tests/test_langgraph_structured.py` (R12; FR-022, D10; points 1 and 4)
  on a real `create_agent` with `response_format` (`ToolStrategy` and `ProviderStrategy`), a schema
  `Reply(status, message)`:
  - a turn ending with `status="input_required"` is asked as a `Question` for the caller (`answer_by`
    `caller`), one `text` field (`answer`), the message's first line cut at 200 characters as the title
    (the whole message in the description when longer), id `lg-ir-<id of the last AI message>`, after the
    `UsageEvent`; the structured JSON is **not** streamed as reply (under `ProviderStrategy` a text that
    starts with `{` is held until the node's update, then dropped; prose streams at once);
  - the answer is sent as the **next human message of the same thread**, not as a resume (the model sees
    a new human message) and its turn counts usage from zero (D7's limit);
  - **point 1, pinned**: a `completed` reply under `ToolStrategy` has **no reply text** (the caller sees
    `done` and nothing else); under `ProviderStrategy` the JSON is released as ordinary reply text;
  - a `structured_response` left from an earlier turn is never read (only the leg's own `updates`);
  - `resume` checks the request is still pending (the last AI message's id matches, no human message
    follows it, the structured reply still says `input_required`); otherwise `PauseLost`;
  - **point 4**: a declined `input_required` question ends the run `done` and the graph is not called (the
    model's counter does not move).
- [ ] T077 [P] [US5] Write `python/tests/test_langgraph_settle.py` (R11; FR-007, D9, SC-009), with the
  strict model:
  - a new input while an approval is pending, in `per_call` and in `batched`, reaches a **normal reply**;
    the model saw a "withdrawn" `ToolMessage` (`status="error"`, the call's name and id) for every call
    with no answer, in the model's order; a `ToolMessage` a finished `per_call` task already produced is
    **kept once**, not duplicated; the batch record of the thread is dropped; a thread with no pending
    approval gets no state update (a recording saver sees no `aupdate_state`);
  - another kind of pending interrupt (a hand-written one) is left as LangGraph leaves it: the node starts
    again, no settle write;
  - a cancelled task leaves the thread paused, and the next input settles it (the S5 edge case);
  - **the mutation check (SC-009)**, `-k mutation`: with the settle replaced by a no-op (a patched copy of
    `_settle.py`, or a monkeypatch of its one function), the strict-model test **fails**; with it, it
    passes.
- [ ] T078 [US5] Build, install, and run T075 to T077. Confirm the expected failures: the fallback and caller
  addressed cases end `failed` ("not supported yet"), no `input_required` question, the dangling-call error
  of finding 6.

### Implementation for User Story 5

- [ ] T079 [P] [US5] `_structured.py` (R12): normalise the leg's own `structured_response` (pydantic by
  `model_dump()`, a dataclass by `asdict`, a mapping as it is, an `Enum` by its value; anything else is
  ignored), read `status` and `message`, and build the `input_required` question with id
  `lg-ir-<last AI message id>`; `still_pending(state, request_id)` for `resume`.
- [ ] T080 [P] [US5] `_settle.py` (R11, D9): when a run starts and `aget_state` shows a pending middleware
  approval, one `aupdate_state(config, {"messages": [...]})` with **no `as_node`**: the `ToolMessage`s of
  finished `per_call` tasks (from `state.tasks[i].result`), then, for each tool call of the last AI message
  with no `ToolMessage`, a `ToolMessage(content="The call was withdrawn: a new message came before it was
  approved.", name=<tool>, tool_call_id=<id>, status="error")`; the batch record is dropped.
- [ ] T081 [US5] `_pauses.py` completed (R8, R14): the fallback question (pause-mapping rows 6 and 7), the
  order of several interrupts (tool approvals first, in the model's order, then the others as LangGraph
  lists them), and the `input_required` pause; the resume value for a fallback is the answered text, and
  `None` when declined.
- [ ] T082 [US5] `_reply.py`, the JSON hold (R12): only in a graph with a `structured_response` channel,
  the text of an AI message whose first non-blank character is `{` is held until that message's node
  update, then dropped when the update's structured reply is `input_required` and released otherwise.
- [ ] T083 [US5] `_leg.py` and `agent.py` extended: `run` settles before it sends the input; an
  `input_required` turn yields `UsageEvent` then the `Ask`; `resume` of that request checks it is still
  pending (`PauseLost` if not), a declined answer ends the run `done` without calling the graph, and an
  answer is sent as the next human message through the `run` path.
- [ ] T084 [US5] Run T075 to T077 until green, the settle mutation test included.
- [ ] T085 [US5] Mutation check, recorded under R17: each of these must make a test fail: a caller-addressed
  approval asked as an approval; the fallback's string cut removed; sequential interrupts both asked at
  once; the JSON hold removed; `input_required` read from a value of an earlier turn; the answer sent as a
  resume; the settle's `as_node` set; the withdrawn message's `status` not `error`; a finished tool
  message dropped by the settle.
- [ ] T086 [US5] Verify, then commit `feat(006): other pauses, input_required and a new message on a pause`.

**Checkpoint**: SC-006 and SC-009 hold; US5's scenarios 1 to 6 pass.

---

## Phase 9: LangChain tools as R2C tools (US6, P3)

**Goal**: `tool_from_langchain` and `tools_from_langchain` turn LangChain tools into `ToolSpec`s with the
model-visible schema, checked arguments, and a refusal at conversion for an injected argument (SC-011).

**Independent test**: `test_langgraph_tools.py`.

- [ ] T087 [P] [US6] Write `python/tests/test_langgraph_tools.py` (R16; FR-024, FR-025):
  - a tool made with `@tool`, one with a pydantic `args_schema`, one with a plain JSON Schema
    `args_schema`, an async-only tool (`StructuredTool.from_function(coroutine=...)`) and a `BaseTool`
    subclass: the `ToolSpec` has the tool's name, its description and the model-visible schema (`title`
    removed, a copy: changing it does not change the tool);
  - a call with valid arguments runs the tool and returns its result; a **sync** tool does not block the
    loop (a ticking task keeps ticking);
  - arguments that break the schema (a missing key, a wrong type, an extra key if the schema forbids it)
    never run the tool (its counter stays at 0), and the caller gets `InvalidArguments` with one
    `Problem("invalid_args", <key>, <message>)` per breaking key, also for a plain JSON Schema tool
    (which LangChain does not validate itself);
  - an injected argument (`InjectedState`, `InjectedStore`, `ToolRuntime`, `InjectedToolCallId`,
    `InjectedToolArg`) is refused **at conversion** with a `TypeError` that names the tool and the
    argument;
  - `tools_from_langchain` keeps the order, refuses the **whole list** when one is refused, and accepts an
    empty one; the result has the same fields as a `tool_from_function` spec for an equivalent function.
- [ ] T088 [US6] Build, install, and run T087. Confirm the expected failures: `ImportError` for the two names.
- [ ] T089 [US6] Complete `tools.py` (R16): `tool_from_langchain(tool)` and `tools_from_langchain(tools)`
  per the contract, built on `schema_of` (T048); the call checks the arguments with `jsonschema` and then
  awaits `tool.ainvoke(dict(args))`; the injected-argument check compares `tool.args` with
  `tool.get_input_schema().model_fields` for a pydantic schema and finds nothing to refuse for a dict
  schema. Export both from `__init__.py` and add them to `__all__`.
- [ ] T090 [US6] Run T087 until green. Run `test_packaging.py`: the import rules still hold.
- [ ] T091 [US6] Mutation check, recorded under R17: each of these must make a test fail: arguments not checked;
  an injected argument not refused; `title` left in; a sync tool run on the loop; one refusal not
  refusing the list; a list reordered.
- [ ] T092 [US6] Verify, then commit `feat(006): LangChain tools as ToolSpecs`.

**Checkpoint**: SC-011 holds; US6's scenarios 1 to 4 pass.

---

## Phase 10: Docs and the final gate

**Goal**: the docs say what the code does, an outside review has read all of it, and every success
criterion is checked on the three Pythons.

**Independent test**: the whole suite and `quickstart.md`, end to end.

- [ ] T093 [P] Write the ADR `docs/design-docs/langgraph-pause-to-ask.md` (Context, Decision,
  Alternatives, Consequences: Better / Worse / Must now be true): finding 2 (a refused `batched` resume
  leaves the thread unable to continue), the pause-to-ask rules by kind, D5 and the per-run handler
  (point 2: "the graph object is not edited"), D9 (the settle by a state update, and why not a rejecting
  resume), D10. It ends with the **SC-012 table**: each row of `contracts/pause-mapping.md` with the test
  that proves it; a row with no test is a gap, so write the test first.
- [ ] T094 [P] `python/README.md`: a LangGraph section that says everything in `contracts/langgraph-api.md`
  "What the README must say": the one-line wrap and the three wrap checks; a durable **async**
  checkpointer is needed for a pause to survive a restart, and the in-memory one warns; `batched` keeps a
  batch in progress in memory only (use `per_call` where a restart in the middle matters); one chunk of
  reply latency; `reasoning` and `expose_tools` are off by default and why; a provider's exception text
  reaches the caller as it is; a pydantic structured reply in the checkpoint needs the owner's
  `allowed_msgpack_modules`; the queue between the graph and the door is unbounded; a `completed`
  structured reply under `ToolStrategy` has no reply text (point 1); two parallel requests need distinct
  ids.
- [ ] T095 [P] `ARCHITECTURE.md` (the `bridges/langgraph/` rows and its import rule), `CHANGELOG.md`
  (Added), and `AGENTS.md` (one row in the Docs table for the ADR; the file stays under 150 lines, it is 67
  now).
- [ ] T096 [P] Dated notes (never rewrite a body): `docs/whitepaper.md` and
  `docs/research/2026-11-20-r2c-v1-design-brief.md` where they name `serve()` or `a2a/langchain`; the 002
  contract `specs/002-python-core/contracts/core-api.md` (`PauseLost`, and the suite's structural
  sequence checks: D3); `docs/design-docs/one-remote-two-doors.md` if it names the bridge by the old
  number. Then grep the old names across docs and code until only intentional hits remain.
- [ ] T097 [P] `.github/workflows/python.yml`: a step "The LangGraph bridge works with only its extra
  (wheel + [langgraph], no dev group)" beside the others, running `tests/langgraph_only.py` in
  `../.lg-venv`.
- [ ] T098 Run `quickstart.md` end to end, step by step, on 3.11, 3.12 and 3.13; fix the guide where it
  and the code disagree (the guide is the one that moves, unless the code is wrong). Include its step 7,
  the one-line wrap, by hand.
- [ ] T099 Outside review: dispatch a **code reviewer** and a **security reviewer** (the
  `.claude/agents/` ones), each with no memory of the work, on the range from the commit that adds this
  file to HEAD, briefed with what the bridge does and the plan's risks. Check every finding against the code. For
  each one acted on, write a test that **fails first**, then fix. Record the review, with what was **left
  on purpose** and why, as R19 in `research.md`.
- [ ] T100 Mutation check of the review fixes (a list from T099), recorded in R19: confirm the baseline
  is **green** before the run (a red baseline kills mutants for the wrong reason).
- [ ] T101 The closing numbers, recorded here under "Phase 10 (date)": the suite's count on 3.11, 3.12 and
  3.13 against the installed wheel; core only, a2a only, mcp only and langgraph only ok;
  `ruff check --select F` clean; the replays unchanged (R2C examples 46 valid, 20 invalid, 1 unknown kind
  ignored, 102 objects round-tripped; A2A 31/29/3; MCP 14/13/1); the bridge adds no example to
  `standard/`.
- [ ] T102 Walk SC-001 to SC-012 and write the result against each in this file ("met by T0xx, run
  <date>"); name any not fully met, and what is left.
- [ ] T103 Update `WORKSTATE.md` (006 closed locally, what is next: spec 007, `Remote`; the push waits for
  the maintainer's go) and `specs/006-langgraph-bridge/plan.md` (a dated closing note; the body stays).
- [ ] T104 Final leak scan of the whole range since `3b26285` (must be 0), then commit
  `docs(006): ADR, README, notes, CI step and close the LangGraph bridge`. **Do not push.**

**Checkpoint**: the maintainer decides on the push.

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1** has no dependency. **Phase 2** depends on phase 1 only for the packaging checks (it is
  core-only work).
- **Phase 3** depends on 1 and 2: it uses the scripted model, the builders and `PauseLost`.
- **Phase 4** depends on 3 and on `PauseLost` from 2.
- **Phases 5 and 7** are independent of each other; both depend on 3. (Phase 7's SC-008 restart test
  also needs phase 6's SQLite helpers.)
- **Phase 6** depends on 5 (it restarts approvals) and, for scenario 6, on 7 (T064).
- **Phase 8** depends on 5 (the settle reads the middleware payloads) and 3.
- **Phase 9** depends on phase 1 and the core only, but its `schema_of` is created in phase 5 (T048).
- **Phase 10** is last: it covers everything at once.

### Within each phase

- Tests are written first and must fail for the expected reason (or be shown non-vacuous by mutation).
- Helpers before the tests that use them (T004, T005 before T006; T021 before T024).
- Pure modules (`_blocks`, `_reply`, `_usage`, `_batch`, `_reasoning`, `_structured`, `_settle`) before
  `_leg.py` and `agent.py`, which glue them.
- Each phase ends with its verify and its commit; the next phase starts only on the maintainer's go,
  unless the maintainer says "all phases".

### Parallel opportunities

- Phase 1: T002, T003, T004, T005 (different files). Phase 2: T013, T014.
- Phase 3 tests: T021 to T024 and T026 (T025 waits for T021). Phase 3 modules: T028 to T032 (T033 and
  T034 wait for them).
- Phase 5: T045 and T046; T048 and T049. Phase 7: T061 to T065 (T062 to T065 share one file, so write them
  one after the other, or split the file); T067 and T068.
- Phase 8: T075 to T077; T079 and T080. Phase 10: T093 to T097.
- Subagents, if used (the `parallel-agents` rule), take whole phases' independent test files with a
  self-contained brief and an output contract; never the shared `agent.py`, `_leg.py` or `_pauses.py`.

## Implementation strategy

### MVP first (US1)

1. Phase 1 (extra, skeleton, spike) and phase 2 (core piece, suite).
2. Phase 3: **stop and validate**: the suite S1–S10 on a real graph and the first chunk before the last
   token.
3. Phase 4: the two doors. After it, a wrapped graph is servable end to end.

### Incremental delivery

1. Phase 5 (approvals) then phase 6 (restart): the P1 stories are done.
2. Phase 7 (timeline) and phase 8 (other pauses, a new input): the P2 stories.
3. Phase 9 (tools): P3.
4. Phase 10: docs, the outside review and the final gate.

## Notes

- Each phase is one commit, with an explicit pathspec and no co-author trailer; none is pushed.
- If reality diverges from the plan (a pinned fact fails, a door needs a change), stop, update `research.md`
  and `plan.md` first, and tell the maintainer; do not force the code through.
- `spec.md` keeps its status "Draft", as the spec of 005 did.
- Out of scope, as the spec says: `Remote` and the approval policy (007), other agent frameworks, a
  `messages`-less graph, the LangGraph server, forking or time travel, a `step` activity per node, a cost
  figure, the caller side, publishing to PyPI.
