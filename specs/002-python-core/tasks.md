---
description: "Task list for 002-python-core"
---

# Tasks: Python core (`ext_r2c.core`)

**Input**: design documents in `specs/002-python-core/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII says test first, against the installed wheel. Every phase
writes its tests first, runs them, and confirms they fail for the expected reason before any
production code is written.

**Organization**: the seven phases of the plan's delivery order. `/speckit-implement` runs
**one phase per go**: finish the phase, verify, commit, report, stop. The stories run in
dependency order, not label order: US6 (packaging) comes first, because the import rule must exist
before the first core module; US3 (forms) comes before US2 (answer check), because the check uses
the answer schema.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US6 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `uv build`;
  2. recreate `../.ci-venv`, then install the wheel and the `dev` group (Python 3.11);
  3. run `../.ci-venv/bin/pytest`;
  4. recreate `../.core-venv`, install the wheel alone, run `../.core-venv/bin/python -I tests/core_only.py` (from phase 1 on);
  5. leak-scan the staged added lines (must be 0);
  6. commit with an explicit pathspec and no co-author trailer.

## Path conventions

- Package: `python/src/ext_r2c/core/`; tests: `python/tests/`
- Standard: `standard/v1/` (README, `examples/{a2a,mcp,invalid}/`)
- CI: `.github/workflows/python.yml`

---

## Phase 1: Packaging (US6, P2; runs first)

**Goal**: extras reshaped; `ext_r2c.core` exists, imports nothing but the standard library,
`pydantic` and `jsonschema`, and works in a wheel-only venv.

**Independent test**: `test_packaging.py` on the wheel; `core_only.py` in `../.core-venv`.

- [X] T001 [P] [US6] Create `python/tests/test_packaging.py` (research R15, R16) with:
  - `test_extras`: reads `importlib.metadata.metadata("ext-r2c")`; asserts `Provides-Extra` is exactly `{"a2a", "mcp", "langgraph"}`, and that no `Requires-Dist` entry marked `extra == "langgraph"` names `a2a-sdk` or `ext-r2c[a2a]`;
  - `test_core_imports_only_allowed_modules`: finds the installed `ext_r2c/core/` with `importlib.resources.files("ext_r2c") / "core"`, parses every `.py` with `ast`, and allows only `sys.stdlib_module_names`, `pydantic`, `pydantic_core`, `jsonschema`, `ext_r2c` and relative imports; the failure lists `file:line module`;
  - `test_core_import_loads_no_protocol_sdk`: a subprocess with `sys.executable -I -c` imports `ext_r2c.core` and prints the loaded top-level modules among `a2a`, `mcp`, `langchain`, `langgraph`; asserts none.
- [X] T002 [P] [US6] Create `python/tests/core_only.py`, a script that is not collected by pytest. It runs with the wheel alone and, in phase 1:
  - imports `ext_r2c` and `ext_r2c.core`;
  - asserts that `importlib.util.find_spec("rfc3339_validator") is None` and that no `a2a`, `mcp`, `langchain` or `langgraph` module is loaded;
  - prints `core only: ok`.

  Leave a `# phase 2:` comment where the model checks go (T014).
- [X] T003 [US6] Build, install, and run `pytest tests/test_packaging.py`. Confirm the failures are the expected ones:
  - `langchain` is still an extra;
  - `ext_r2c/core` does not exist.
- [X] T004 [US6] In `python/pyproject.toml`, replace `langchain = ["ext-r2c[a2a]", "langchain>=1.3", "langgraph"]` with `langgraph = ["langchain>=1.3", "langgraph"]`.
- [X] T005 [US6] Create `python/src/ext_r2c/core/__init__.py` with a module docstring (the protocol-free core; see `ARCHITECTURE.md`) and `__all__: list[str] = []`.
- [X] T006 [P] [US6] In `.github/workflows/python.yml`, add a step after the tests:
  1. `uv venv --python ${{ matrix.python }} ../.core-venv`;
  2. `uv pip install --python ../.core-venv dist/*.whl`;
  3. `../.core-venv/bin/python -I tests/core_only.py`.
- [X] T007 [US6] Verify (all six steps) and commit `build(002): langgraph extra, core package, import rules`.

**Checkpoint**: 125 tests pass (122 + 3); `core only: ok`.

---

## Phase 2: Models (US1, P1)

**Goal**: SC-001, SC-002. Every example object round-trips, every invalid object is rejected
at its `fails_at`, and unknown kinds are skipped.

**Independent test**: `test_models.py` on the wheel; the summary line shows the round-trip count.

- [X] T008 [P] [US1] Create `python/tests/test_models.py` ([data-model.md](data-model.md) "Wire models", research R1–R3):
  - `test_every_example_object_round_trips` (parametrised over `example_files("a2a") + example_files("mcp")`): for each object from `r2c_check.find_r2c_objects` whose kind is one of the six, `to_json(parse(obj)) == obj`;
  - `test_unknown_kind_is_skipped`: the `provenance` object of `a2a/unknown-kind-ignored.json` gives `Unknown(kind="provenance")`, with no exception;
  - `test_invalid_example_is_rejected_at_its_place` (parametrised over `example_files("invalid")`): `parse` raises `InvalidObject`, and the file's `fails_at` is among the error pointers;
  - `test_missing_kind_is_invalid`;
  - `test_duplicate_field_keys` and `test_duplicate_option_labels` (R2C-QUESTION-4);
  - `test_unknown_activity_type_and_field_kept`;
  - `test_defaults_read_not_written`: `other` and `required` read `True` and stay absent on dump;
  - `test_code_built_object_dumps_kind`: `Question(id=..., ...)` built in code dumps `kind: question`;
  - `test_to_json_rejects_what_the_schema_rejects`: an `Approval` built with `decisions=["edit"]` on an `operation` subject raises `InvalidObject`;
  - `test_number_stays_int`: `300` stays `300`;
  - `test_expires_at_kept_as_written`: `Z` stays `Z`, and `expires()` gives an aware `datetime`;
  - `test_own_date_time_check`: the core's format checker rejects `"nope"` and `"2026-11-20"` and accepts `"2026-11-20T10:15:00Z"`, and its `date-time` check is the core's own function, not jsonschema's;
  - `test_schema_kinds_and_copies`: `schema_kinds()` lists the six kinds; mutating `schema("question")` does not change the next call.
- [X] T009 [P] [US1] In `python/tests/conftest.py`, extend `pytest_terminal_summary`: append `; N objects round-tripped`, counting every known-kind object that the valid examples hold (same skips as today).
- [X] T010 [US1] Run the tests and confirm they fail on `ImportError` of the core names, not on test bugs.
- [X] T011 [US1] Create `python/src/ext_r2c/core/_schemas.py`:
  - `schema(kind)` and `schema_kinds()`, loaded once from `importlib.resources.files("ext_r2c") / "schema" / "v1"` and handed out as deep copies;
  - `format_checker()`: a `jsonschema.FormatChecker` whose `date-time` check is an RFC 3339 regex plus `datetime.fromisoformat` (R3);
  - `validator(schema)` (Draft 2020-12 with that checker);
  - `subschema_validator(root, name)` (R5);
  - `external_refs(schema) -> list[str]` (R4);
  - `pointer(path)`.
- [X] T012 [US1] Create `python/src/ext_r2c/core/models.py` per the data-model tables:
  - base class `_Open` (`extra="allow"`), `Literal` enums, `int | float` numbers, string `expires_at` plus `expires()`;
  - `kind` always marked as set;
  - `parse`, `to_json`, `Model.parse`, `Unknown`, `InvalidObject(errors)`;
  - the QUESTION-4 checks.
- [X] T013 [US1] Export the model names from `python/src/ext_r2c/core/__init__.py`, as listed in [contracts/core-api.md](contracts/core-api.md) "Schemas" and "Models".
- [X] T014 [US1] Extend `python/tests/core_only.py`:
  - parse one object of each kind from `standard/v1/examples`, located with `R2C_STANDARD_DIR` or relative to the script;
  - assert that `invalid/question-expires-not-a-date.json` raises `InvalidObject` at `/expires_at`, without `rfc3339_validator`.
- [X] T015 [US1] Verify and commit `feat(002): R2C models that round-trip every example`.

**Checkpoint**: SC-001 and SC-002 are met; the summary line prints the count.

---

## Phase 3: Forms (US3, P1)

**Goal**: SC-003. The generated forms equal the examples, and flat responses map to the derived
answers. The standard records the O2/O3 decisions (FR-031), and the test helper uses the core's
generator (FR-032, first half).

**Independent test**: `test_forms.py`; `test_examples.py` and `test_rules.py` stay green with the
new examples.

- [X] T016 [P] [US3] Create `python/tests/test_forms.py` ([contracts/forms.md](contracts/forms.md)):
  - `test_answer_schema_rows`: one case per row of the answer-schema table, both `required` columns (Q2);
  - `test_every_mcp_form_matches_its_example`: for every `InputRequiredResult` in `example_files("mcp")`, each object of `_meta[MCP_KEY].input_requests` gives `mcp_form(obj).requested_schema == inputRequests[key].params.requestedSchema`;
  - `test_derived_answers`: a table `{file: expected answer}` copied from the descriptions of
    - `mcp/elicitation-question.json`,
    - `mcp/elicitation-question-other.json`,
    - `mcp/elicitation-question-many-other.json`,
    - `mcp/elicitation-approval.json`,
    - `mcp/elicitation-approval-edit-dropped.json`;

    each response step is mapped with `answer_from_mcp` and compared with `to_json`;
  - approval form cases:
    - an argument named `decision` drops `edit`, and so does one named `reason`;
    - a nested object argument drops `edit`;
    - an external `$ref` drops `edit`, and `edit_offered` is false;
    - a local `$ref` keeps `edit_offered` true, but the schema is not flat;
    - an `integer` argument stays flat;
    - a string enum without `type` gets `"type": "string"` and a titled `oneOf`;
    - an argument missing from `args` gets no `default`;
    - `decisions == ["edit"]` with a non-flat schema raises `NotAskableOverMcp`;
  - response mapping cases:
    - `<key>_other` of `""` or `"  "` is ignored;
    - `many` does not add `<key>_other` twice;
    - unknown content keys are dropped;
    - `allow` ignores argument values;
    - a left-out argument keeps its value;
    - an empty `reason` is dropped;
    - `cancel` gives `declined`.
- [X] T017 [US3] Change the standard ([plan.md](plan.md) "Changes to the standard"):
  - `standard/v1/README.md` §5: the R2C-QUESTION-5 table gets `minLength: 1` / `minItems: 1` with `required: true`, and one sentence: "required means present and not empty";
  - `standard/v1/README.md` §12, R2C-MCP-2: titles and descriptions, the `<key>_other` title and description, the `required` list, empty `<key>_other`, `one` replaces and `many` adds once;
  - `standard/v1/README.md` §12, R2C-MCP-3: what flat means, the `decision` / `reason` names, the titled `oneOf` for enums, arguments never required, rebuilding `args`, and no decision left means it cannot be asked over MCP;
  - `standard/v1/examples/mcp/elicitation-question-other.json`: add `"description": "Which warehouse should the report cover?"` to `warehouse`;
  - new `standard/v1/examples/mcp/elicitation-question-many-other.json`, following `elicitation-question-other.json`:
    - a question `q-1` with a `many` field `sections` (options Stock, Orders, Returns; `other` left at its default);
    - the response `{"sections": ["Stock"], "sections_other": "Suppliers"}`;
    - the description states the derived answer `{sections: [Stock, Suppliers]}`;
    - `rules`: R2C-MCP-2, R2C-MCP-4;
  - new `standard/v1/examples/a2a/reask-empty-required.json`, following `a2a/reask-errors.json`:
    - a question with a required `text` field `title`;
    - the answer `{"title": ""}`;
    - a re-ask with `errors: [{"key": "title", "message": "A title is needed."}]`;
    - the answer `{"title": "October stock"}`, then completion;
    - `rules`: R2C-QUESTION-5, R2C-ASK-6 (2026-11-20: was "R2C-ASK-3", a wrong rule number; the re-ask rule is ASK-6);
  - `specs/001-standard-v1/research.md`: dated notes on O2 and O3, "decided in spec 002";
  - `CHANGELOG.md` Changed: the QUESTION-5 table with `required`; the MCP-2 / MCP-3 clarifications.
- [X] T018 [US3] Run the tests and confirm the expected failures:
  - `test_forms.py` fails on `ImportError`;
  - `test_examples.py` fails on `a2a/reask-empty-required.json`, because the old `form_schema` accepts `""`.
- [X] T019 [US3] Create `python/src/ext_r2c/core/forms.py`: `answer_schema`, `edit_offered`, `mcp_form` → `McpForm`, `answer_from_mcp`, `NotAskableOverMcp` (research R7–R9). Export them from `core/__init__.py`.
- [X] T020 [US3] FR-032, first half:
  - delete `field_schema` and `form_schema` from `python/tests/r2c_check.py`;
  - in `python/tests/test_examples.py`, use `ext_r2c.core.answer_schema(Question.parse(request))` instead;
  - delete `test_form_schema_mapping` from `python/tests/test_check_helpers.py` (now covered by `test_answer_schema_rows`).
- [X] T021 [US3] Verify and commit `feat(002): forms for both doors; standard records O2 and O3`. The rule-coverage tests must stay green.

**Checkpoint**: SC-003 is met; 39 valid examples.

---

## Phase 4: Answer check and fallback text (US2, P1)

**Goal**: SC-004 and FR-019. One check is used by every door and by the example pairing test.

**Independent test**: `test_check.py`, `test_fallback.py`; `test_examples.py` pairing through
`check_answer`.

- [X] T022 [P] [US2] Create `python/tests/test_check.py` ([contracts/core-api.md](contracts/core-api.md) "Answer checking", research R6):
  - one bad answer per FR-015 rule, each with its expected `code` and `key`:
    - `too_large`, with a small custom `Limits`;
    - `invalid_answer`;
    - `wrong_id`;
    - `caller_on_approval`;
    - `expired`, with a fixed `now`;
    - `invalid_value` on a question (key `threshold`);
    - `invalid_value` on an approval;
    - `not_offered`, for an `edit` that is not offered;
    - `not_offered`, for an `edit` with an external `$ref`;
    - `invalid_args`, with key `quantity` (5000 over the maximum 1000);
  - a `required` error yields one problem per missing key;
  - messages are short sentences that do not quote JSON Schema keywords;
  - `as_error_item()` validates as a question's `errors` item;
  - `decision`:
    - answered gives the decision;
    - declined gives `deny`;
    - expired gives `deny`;
    - a question raises `TypeError`;
  - `check_size`:
    - text is counted in UTF-8 bytes;
    - `raw_base64` is counted by its decoded size, without decoding;
    - a custom threshold applies;
  - an external `$ref` to `https://example.invalid/args.json` opens no socket (a fixture patches `socket.socket.connect` to fail).
- [X] T023 [P] [US2] Create `python/tests/test_fallback.py` ([contracts/forms.md](contracts/forms.md#fallback-text)):
  - exact strings for hand-built cases:
    - a question with every field type;
    - an optional field;
    - `other: true` and `other: false`;
    - origin;
    - a re-ask with errors;
    - an approval with `approver_role`, `expires_at` and an `edit`;
    - an activity with and without `detail`;
  - for every request and activity in the examples, the text is not empty, and it holds the `title` (or `label`) and every option label.
- [X] T024 [US2] Run the tests and confirm that both files fail on `ImportError`.
- [X] T025 [US2] Create `python/src/ext_r2c/core/check.py`: `Problem`, `Limits` (5 × 2^20, 50 × 2^20), `check_answer` in the documented order, `decision`, `check_size`. Export them.
- [X] T026 [P] [US2] Create `python/src/ext_r2c/core/fallback.py`: `fallback_text` (research R13). Export it.
- [X] T027 [US2] FR-032, second half: in `python/tests/test_examples.py`, replace `_answer_problems` with `check_answer(Answer.parse(answer), parse(request))`. Ignore problems with code `expired`: expiry depends on the clock, and `a2a/refuse-expired.json` shows the refusal in text. Keep the re-ask pairing rule.
- [X] T028 [US2] Verify and commit `feat(002): answer check and fallback text`.

**Checkpoint**: SC-004 is met.

---

## Phase 5: Run events and agent sources (US4, P1)

**Goal**: SC-005. Both fakes pass the same suite through one `Driver`.

**Independent test**: `test_agent_source.py`.

- [ ] T029 [P] [US4] Create `python/tests/fake_sources.py`: `CheckpointFake(store: dict)` and `LiveFake()`, running the script of [contracts/agent-source-suite.md](contracts/agent-source-suite.md) "The fakes". Both take an optional `fail_after_ask=True` (for S8) and `double_ask=True` (for S9).
- [ ] T030 [P] [US4] Create `python/tests/agent_source_suite.py`:
  - scenarios S1–S10 as functions `scenario_<name>(make_source)`;
  - each drives `Driver` with `asyncio.run` and returns nothing on success;
  - S7 reads `source.pause` (the only style-dependent expectation);
  - every scenario also checks S10 (one terminal event, nothing after it).
- [ ] T031 [US4] Create `python/tests/test_agent_source.py`:
  - parametrise every suite scenario over `[CheckpointFake, LiveFake]`;
  - `test_thread_id`: the same inputs give the same id; a different door, owner or context gives a different id; it starts with the door; `"a:b"`/`"c"` and `"a"`/`"b:c"` differ;
  - `test_driver_refuses_a_source_without_a_style` (`TypeError`);
  - `test_events_are_frozen`.
- [ ] T032 [US4] Run the tests and confirm they fail on `ImportError` of `ext_r2c.core.events` / `source`.
- [ ] T033 [US4] Create `python/src/ext_r2c/core/events.py`:
  - `ReplyChunk`, `ActivityEvent`, `Ask`, `AnswerEvent`, `ArtifactEvent`, `UsageEvent`, `Done`, `Error`;
  - `TextContent`, `BytesContent`, `UrlContent`;
  - the `RunEvent` and `Content` unions;
  - all as frozen dataclasses with slots.
- [ ] T034 [US4] Create `python/src/ext_r2c/core/source.py` ([data-model.md](data-model.md) "Driver", research R10, R11):
  - `CardInfo`, `CardSkill`, `RunInput`, `RunContext`, `AgentSource` (a `Protocol`), `Driver`, `Run`, `thread_id`;
  - one task per run feeding one `asyncio.Queue`;
  - `ctx.ask` resolves through a future;
  - the driver emits `AnswerEvent` and the terminal event;
  - the sequence rules end the run with `Error(protocol)`;
  - `Driver.resume` gives `Error(lost)` for a live source it does not hold.

  Export the names.
- [ ] T035 [US4] Verify and commit `feat(002): run events, AgentSource and one driver for both pause styles`.

**Checkpoint**: SC-005 is met.

---

## Phase 6: Tools (US5, P2)

**Goal**: story 5. A plain function becomes a `ToolSpec` whose schema can back an approval.

**Independent test**: `test_tools.py`.

- [ ] T036 [P] [US5] Create `python/tests/test_tools.py`:
  - the three story 5 scenarios;
  - an async function;
  - a sync function runs off the event loop (it records `threading.get_ident()`, which differs from the loop's thread);
  - `name=` and `description=` overrides;
  - a docstring of two paragraphs gives the first;
  - `*args` and `**kwargs` are refused with `TypeError`;
  - `InvalidArguments` lists the keys, and the function was not called;
  - the input schema has no top-level `title`;
  - an approval built with `args_schema=tool.input_schema` keeps `edit` in `mcp_form`.
- [ ] T037 [US5] Run the tests and confirm they fail on `ImportError`.
- [ ] T038 [US5] Create `python/src/ext_r2c/core/tools.py`: `ToolSpec`, `tool_from_function`, `InvalidArguments` (research R12). Export them.
- [ ] T039 [US5] Verify and commit `feat(002): ToolSpec from plain functions`.

---

## Phase 7: Docs and final gate

**Purpose**: SC-006, SC-007 and SC-008; no stale docs.

- [ ] T040 [P] In `ARCHITECTURE.md`, list the core modules. Replace "A test enforcing this belongs to the first spec that adds a second module" with a pointer to `test_packaging.py` and the core-only CI step.
- [ ] T041 [P] In `python/README.md`, add a core example: parse, `answer_schema`, `mcp_form`, `check_answer` (as quickstart §4), and the install table with `[langgraph]`.
- [ ] T042 [P] In `docs/whitepaper.md` §10–11, align the names with [contracts/core-api.md](contracts/core-api.md) (`Driver`, `pause`, `resume(answer, ctx)`) and add a dated note at the top.
- [ ] T043 [P] Update `CHANGELOG.md`:
  - Added: `ext_r2c.core` (models, forms, answer check, fallback text, run events, `AgentSource` and `Driver`, `ToolSpec`);
  - Changed: extras `[langchain]` → `[langgraph]`, which no longer pulls `[a2a]`.
- [ ] T044 Grep for stale names across `docs/`, `ARCHITECTURE.md`, `README.md`, `python/` and `WORKSTATE.md` (`[langchain]`, `ext-r2c[langchain]`, `form_schema`), until only the intentional hits in historical records remain.
- [ ] T045 Run the final gate:
  - build once;
  - run the full suite in fresh venvs on Python 3.11, 3.12 and 3.13;
  - run the core-only check on each;
  - run the quickstart §5 mutations on a copy through `R2C_STANDARD_DIR`, and confirm each fails where the table says and the repository is untouched;
  - leak-scan `5a28998..HEAD`.
- [ ] T046 SC-008: give a fresh-context reviewer only the installed core's docstrings (`help()` output) and `docs/design-docs/one-remote-two-doors.md`. Ask it to write one fake source of each style, and run its two sources through `agent_source_suite.py`. Record the result and any unclear points in `specs/002-python-core/research.md` "Outside review".
- [ ] T047 In `WORKSTATE.md`, mark 002 closed and set the next step to `003-a2a-binding`. Tick every task here, with dated notes where reality differed. Commit `chore(002): close python core`.

---

## Dependencies

```
Phase 1 (US6) ─▶ Phase 2 (US1) ─▶ Phase 3 (US3) ─▶ Phase 4 (US2) ─┐
                         │                                         ├─▶ Phase 7
                         ├──────▶ Phase 5 (US4) ───────────────────┤
                         └──────────────────────▶ Phase 6 (US5) ───┘   (US5 also needs Problem from phase 4)
```

- Phase 5 needs only the models (phase 2). It is kept after phase 4 so that one phase runs per go.
- Phase 6 needs `Problem` (phase 4) and `mcp_form` (phase 3).

## Parallel opportunities

- Within a phase, the test files marked [P] are written together. In phase 1 that is T001, T002
  and T006; in phase 2, T008 and T009; in phase 4, T022 and T023; in phase 5, T029 and T030.
- T025 and T026 touch different modules and can be written in parallel once T024 has failed as
  expected.
- Across phases, nothing runs in parallel: one phase per go, each verified and committed.

## Implementation strategy

- **MVP**: phases 1–2 (US6 and US1). The models alone already let 003 and 004 read and write R2C
  objects.
- **Then**: forms and the check (phases 3–4), which the MCP door needs; sources (phase 5), which
  the A2A door needs; tools (phase 6), which the MCP door needs.
- Every phase ends green on the installed wheel and the core-only venv, and is committed. Nothing
  is pushed without the maintainer's go.
