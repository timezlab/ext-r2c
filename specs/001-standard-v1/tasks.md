---
description: "Task list for 001-standard-v1"
---

# Tasks: R2C standard, version 1

**Input**: design documents in `specs/001-standard-v1/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII asks for test first against the installed wheel, and the
checks are the feature's own deliverable (FR-021, FR-021a, FR-023).

**Organization**: one phase per user story, in priority order. `/speckit-implement` runs **one
phase per go**: finish it, verify, commit, report, stop.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `uv build`;
  2. install the wheel and the `dev` group into a fresh venv;
  3. run `pytest` in that venv;
  4. leak-scan the staged added lines;
  5. commit with an explicit pathspec.

## Path conventions

- Standard: `standard/v1/` (README, `schema/`, `examples/{a2a,mcp,invalid}/`)
- Python package and tests: `python/` (`hatch_build.py`, `pyproject.toml`, `tests/`)
- CI: `.github/workflows/python.yml`

---

## Phase 1: Setup (shared infrastructure)

**Purpose**: test-only dependencies, a way for the tests to find `standard/v1`, and CI installing
both.

- [ ] T001 Add `a2a-sdk>=1.3,<2`, `mcp>=2.3,<3` and `jsonschema[format-nongpl]>=4` to `[dependency-groups] dev` in `python/pyproject.toml`. Leave `[project.dependencies]` and the extras unchanged (FR-025; research R7).
- [ ] T002 [P] Change `.github/workflows/python.yml`: replace `uv pip install --python ../.ci-venv dist/*.whl pytest` with `uv pip install --python ../.ci-venv dist/*.whl --group dev`.
- [ ] T003 [P] Create `python/tests/conftest.py` with a session fixture `standard_dir`:
  - it returns `Path(os.environ["R2C_STANDARD_DIR"])` when that variable is set, else `Path(__file__).resolve().parents[2] / "standard" / "v1"`;
  - it fails with a clear message when the directory does not exist.
- [ ] T004 [P] Add a test to `python/tests/test_smoke.py`:
  - a subprocess runs `python -c "import ext_r2c, sys; print('a2a' in sys.modules or 'mcp' in sys.modules)"` with `sys.executable`;
  - it asserts the output is `False` (research R7: the test venv now has both SDKs installed).
- [ ] T005 Verify (see Format) and commit `chore(001): test-only protocol SDKs and standard_dir fixture`.

**Checkpoint**: the 5 existing tests plus the new smoke test pass against the installed wheel.

---

## Phase 2: Foundational (the checks, before anything they check)

**Purpose**: the test harness of FR-021 and FR-021a. Each test is written first and **fails for
the expected reason** while `standard/v1/` is still empty.

- [ ] T006 Create the helper module `python/tests/r2c_check.py` (test code, not shipped), following [contracts/example-file.md](contracts/example-file.md):
  - `load_schemas(standard_dir)` returns a `{kind: schema}` map; the file `artifact-meta.json` gives kind `artifact`;
  - `validator(schema)` returns a `Draft202012Validator` with `FormatChecker()`;
  - `find_r2c_objects(binding, body)` yields `(json_pointer, obj)` using the three placement forms, including the MCP `{"input_requests": {...}}` form;
  - `check_a2a(type_name, body)` runs `ParseDict` into `a2a_pb2.<type>` and then `validate_proto_required_fields` (research R1);
  - `check_mcp(step)` handles `request`, `result`, `notification` and `discover` through `mcp_types.jsonrpc` and `mcp_types.methods` at `"2026-07-28"`. It runs the dropped-key diff (keys inside `_meta` exempt) and checks every `requestedSchema` property against `PrimitiveSchemaDefinition` (research R2);
  - `form_schema(question)` implements the data-model "Form → schema mapping" (A2A column);
  - `parse_rules(readme_text)` returns rule records parsed with the regular expression in [contracts/rule-format.md](contracts/rule-format.md), and raises on a duplicate id.
- [ ] T007 [P] Create `python/tests/test_check_helpers.py`. It proves that the helpers reject bad input, using inline fixtures (taken from the research prototype):
  - A2A: a misspelled field `messsage`; enum `INPUT_REQUIRED`; a `Message` without `messageId`; an `AgentCard` without skills.
  - MCP: `inputRequest` instead of `inputRequests`; a `tools/call` result without `resultType`; `server/discover` without `cacheScope` / `ttlMs`; a `tools/call` request whose `_meta` lacks `io.modelcontextprotocol/clientCapabilities`; a nested `requestedSchema` property.
  - Rules: a duplicate rule id, and a malformed tag line.
  - It also proves that each correct counterpart passes.
- [ ] T008 [P] Create `python/tests/test_schemas.py`:
  - exactly six files exist in `standard/v1/schema/`;
  - each passes `Draft202012Validator.check_schema` and has `$id` equal to `https://github.com/timezlab/ext-r2c/tree/main/standard/v1/schema/<file>`;
  - each contains no `$ref` that does not start with `#` (FR-015);
  - no object schema sets `additionalProperties: false` or `unevaluatedProperties: false` (FR-016).
- [ ] T009 [P] Create `python/tests/test_examples.py`:
  - it is parametrised over every file in `examples/a2a/` and `examples/mcp/`;
  - it checks the top-level example format (title, binding equal to the folder name, rules, steps);
  - it checks each step's envelope with `check_a2a` or `check_mcp`;
  - it validates every R2C object found against its kind's schema and skips unknown kinds, collecting them;
  - it pairs answers with earlier questions and approvals, using `form_schema(question)`, `answer.json#/$defs/approval_value`, and `decision ∈ decisions`;
  - a second parametrised test over `examples/invalid/` asserts that validation fails with an error whose path equals `fails_at`.
- [ ] T010 [P] Create `python/tests/test_rules.py`:
  - the README has at least one rule;
  - every cited rule id exists;
  - every `wire` rule is cited by at least one valid example;
  - every `schema` rule is cited by at least one invalid example;
  - every rule cited by an invalid example is marked `schema`;
  - every file under `standard/v1/examples/` is a `.json` file in `a2a/`, `mcp/` or `invalid/` (no unread file).
- [ ] T011 Run the suite on the wheel. Confirm `test_check_helpers.py` passes, and that `test_schemas.py`, `test_examples.py` and `test_rules.py` fail **only** with "no schema files", "no examples" and "no rules found". Then commit `test(001): example, schema and rule checks (failing: standard not written yet)`.

**Checkpoint**: the harness exists and proves it can fail. No standard content yet.

---

## Phase 3: User Story 1 — implement R2C from the standard alone (P1) 🎯 MVP

**Goal**: normative text with tagged rules, and six schemas a stock validator can use alone.

**Independent test**:
- `test_schemas.py` passes, and every invalid example fails at its `fails_at`;
- the README parses into rules with ids, levels, parties and wire/prose marks (US1 scenarios 1–4).

### Schemas (from [data-model.md](data-model.md))

- [ ] T012 [P] [US1] Write `standard/v1/schema/question.json`:
  - `kind` const; `answer_by.role` ∈ {person, caller}; field `key` pattern `^[a-z][a-z0-9_]*$` and not ending in `_other`;
  - `options` required for `one`/`many` and forbidden for the others; defaults for `other` and `required`;
  - `expires_at` `format: date-time`.
- [ ] T013 [P] [US1] Write `standard/v1/schema/approval.json`:
  - `answer_by.role` ∈ {person, approver};
  - `subject` is `tool_call` (`name`, `args`) or `operation` (`name`), with other types allowed and open;
  - `decisions` is a non-empty, unique subset of allow/edit/deny;
  - `edit` requires `subject.type = tool_call` with `args_schema`.
- [ ] T014 [P] [US1] Write `standard/v1/schema/answer.json`:
  - `outcome` ∈ {answered, declined}; `value` required when `answered` and absent when `declined`;
  - `answered_by.role` ∈ {person, approver, policy, caller};
  - `$defs/approval_value`, with `args` required when `decision = edit`.
- [ ] T015 [P] [US1] Write `standard/v1/schema/artifact-meta.json`:
  - `presentation` ∈ {file, inline, live};
  - `state` only with `live`;
  - `response: true` only with `inline`.
- [ ] T016 [P] [US1] Write `standard/v1/schema/activity.json`:
  - `type` is an open string;
  - `state` is required for known types `tool`/`step`; `name` is required for `tool`;
  - `delta` only for `reasoning`; `duration_ms` is an integer ≥ 0.
- [ ] T017 [P] [US1] Write `standard/v1/schema/usage.json`:
  - every field is optional, with `anyOf` requiring at least one of `input_tokens` / `output_tokens` / `duration_ms` / `cost`;
  - `cost.currency` matches `^[A-Z]{3}$`; integers ≥ 0.

### Invalid examples (one schema rule each; format in [contracts/example-file.md](contracts/example-file.md))

- [ ] T018 [P] [US1] Write `standard/v1/examples/invalid/question-*.json`: missing `title`; `answer_by.role = approver`; a `one` field without `options`; `options` on a `text` field; a field key ending in `_other`; `expires_at = "tomorrow"`.
- [ ] T019 [P] [US1] Write `standard/v1/examples/invalid/approval-*.json`: `answer_by.role = caller`; `edit` without `args_schema`; `edit` on an `operation` subject; empty `decisions`; an unknown decision value.
- [ ] T020 [P] [US1] Write `standard/v1/examples/invalid/{answer,artifact,activity,usage}-*.json`:
  - `answered` without `value`; `declined` with `value`; an approval value `edit` without `args`;
  - `state` on a `file` artifact; `response` on a `file` artifact;
  - a `tool` activity without `state`; `delta` on a `tool` activity;
  - `usage` with only `model`; `currency = "usd"`.

### Normative text (`standard/v1/README.md`, one file, so sequential)

- [ ] T021 [US1] Replace the placeholder in `standard/v1/README.md` with these sections:
  - status (draft), conformance language, roles, and identifiers (FR-001);
  - the rule tag format with a pointer to how rules are numbered (FR-002);
  - declaration and activation on both bindings (FR-003, area `ACT`);
  - the placement rule and the text fallback (FR-004, `CORE`);
  - ignore unknown (FR-005, `CORE`).
- [ ] T022 [US1] Add the kind sections to `standard/v1/README.md`, with tagged rules for each (FR-006):
  - `question` / `approval` common fields and rules;
  - `question`, `approval` and `answer`;
  - the form → schema mapping table from data-model.md (FR-009).
- [ ] T023 [US1] Add the `artifact`, `activity` and `usage` sections to `standard/v1/README.md` (FR-006): streamed reply, `response`, guessing without metadata, `url` lifetime, the three activity types, reasoning and args opt-in, and the usage rules.
- [ ] T024 [US1] Add the binding sections to `standard/v1/README.md`:
  - A2A (FR-007, area `A2A`);
  - MCP (FR-008, area `MCP`), including D1 (the R2C object in the `InputRequiredResult`'s `_meta[key].input_requests`) and D2 (the derived answer, no `policy` on MCP).
- [ ] T025 [US1] Add these sections to `standard/v1/README.md`:
  - identifiers and resume (FR-011, `ID`);
  - trust and safety (FR-010, `SAFETY`);
  - versioning (FR-012, `VERSION`);
  - a "Not schema-checked" list of every rule without `schema` (FR-017);
  - a short "(non-normative)" caller guidance section (FR-013).
- [ ] T026 [US1] Run the suite. `test_schemas.py`, the invalid-example tests and the rule parsing pass. `test_rules.py` must now fail **only** on "wire rule without example", listing the to-do list for US2. Record that list in the phase report, then verify and commit `docs(standard): v1 normative text, six schemas, invalid examples`.

**Checkpoint**: US1 is usable on its own: the standard can be read and objects validated.

---

## Phase 4: User Story 2 — wire examples as the shared test suite (P1)

**Goal**: complete A2A and MCP messages for every `wire` rule, including the full streamed run.
Envelopes are accepted by the real SDK types.

**Independent test**:
- `test_examples.py` and `test_rules.py` pass with 0 uncovered `wire` rules;
- quickstart scenarios 2–5 each make the check fail (US2 scenarios 1–4).

### A2A examples (`standard/v1/examples/a2a/`)

- [ ] T027 [P] [US2] Write `agent-card.json`, `activation.json` (request with an `A2A-Extensions` header, and the response echoing it) and `not-activated.json` (the same exchange without the header: text and a standard artifact only, no R2C part, no reasoning).
- [ ] T028 [P] [US2] Write `question-one.json` (fallback TextPart, `other` default), `question-fields.json` (`many`, `text`, `number`, `bool`, `other: false`, `required: false`, with the answer), `question-caller.json` and `question-forwarded.json` (`origin`, `id` unchanged).
- [ ] T029 [P] [US2] Write `reask-errors.json` (a bad answer, then the same `id` with `errors`), `refuse-wrong-id.json`, `refuse-expired.json` and `text-answer-not-activated.json` (a single `one` field answered in text).
- [ ] T030 [P] [US2] Write:
  - `approval-four-eyes-edit.json`: `approver`, `approver_role`, `expires_at`, `args_schema`, answered `edit` with `args`;
  - `approval-operation-deny.json`: `operation`, `deny` with `reason`;
  - `approval-queued.json`: two approvals in tool-call order, the second only after the first answer.
- [ ] T031 [P] [US2] Write `answer-declined.json` and `answer-policy.json` (`answered_by: policy` on `answer_by: person`).
- [ ] T032 [P] [US2] Write `artifact-file-url.json`, `artifact-file-raw.json`, `artifact-live.json` (open, then the same `artifactId` closed), `artifact-version.json` (`append: false` replaces) and `artifact-no-metadata.json`.
- [ ] T033 [P] [US2] Write:
  - `activity-tool.json`: running, done with `duration_ms` and `detail`, and a second tool that ends `failed`;
  - `activity-step-nested.json`: a step with tool activities under it by `parent_id`;
  - `activity-reasoning.json`: coalesced deltas on one `id`.
- [ ] T034 [P] [US2] Write `usage-input-required.json`, `unknown-kind-ignored.json` (a marked part with `kind: provenance` next to a known one), `follow-up-context.json` (same `contextId`, no `taskId`) and `resubscribe.json` (`SubscribeToTaskRequest`, then `GetTask` returning the task's artifacts and `usage`).
- [ ] T035 [US2] Write `full-streamed-run.json`, following US2 scenario 2 and SC-006:
  - activation; a `step` activity;
  - `tool` running and done with a duration;
  - at least three `response` chunks (`append: false`, `append: true`, `lastChunk: true`) interleaved with the activities;
  - a `file` artifact; an `approval` at `input-required` and its `allow` answer;
  - `completed` with `usage`.

### MCP examples (`standard/v1/examples/mcp/`)

- [ ] T036 [P] [US2] Write `discover.json` (the R2C key under `capabilities.extensions`, full 2026-07-28 result) and `not-activated.json` (a client without the extension in its `clientCapabilities`: elicitation and result with no R2C `_meta`).
- [ ] T037 [P] [US2] Write `elicitation-question.json` (`one` with `other: false`, `many`, `text`, `number`, `bool`; R2C object in the `InputRequiredResult`'s `_meta`; retry with `inputResponses` + `requestState`; derived answer stated in `description`) and `elicitation-question-other.json` (`<key>` and `<key>_other` mapped back to one value).
- [ ] T038 [P] [US2] Write `elicitation-approval.json` (flat `args_schema`, so `edit` is kept with defaults pre-filled; `accept` → `edit`) and `elicitation-approval-edit-dropped.json` (nested `args_schema`, so `edit` is dropped; `decline` → `declined`).
- [ ] T039 [P] [US2] Write `progress-activity.json` (a request with `progressToken`, then `notifications/progress` with `message` = label and the activity in `_meta`) and `tool-result.json`. The tool result carries:
  - a `text` content with an `inline` `response` artifact;
  - a `resource_link` `file`;
  - an embedded `resource` file;
  - a `resource_link` `live`;
  - `usage` in the result's `_meta`.
- [ ] T040 [US2] Run the suite until `test_examples.py` and `test_rules.py` pass with 0 uncovered `wire` rules. Run quickstart scenarios 2–5 by hand and undo them. Then verify and commit `docs(standard): v1 wire examples for A2A and MCP`.

**Checkpoint**: US1 and US2 are both complete: the standard plus its shared test suite.

---

## Phase 5: User Story 3 — schemas inside the Python package (P2)

**Goal**: the wheel carries `ext_r2c/schema/v1/*.json`, byte-identical, taken from `standard/`
at build time ([contracts/packaged-schemas.md](contracts/packaged-schemas.md)).

**Independent test**: `test_packaged_schemas.py` passes on a fresh wheel. `unzip -l` shows six
files under `ext_r2c/schema/v1/`. Editing a schema and rebuilding keeps the test green (US3
scenarios 1–3).

- [ ] T041 [US3] Create `python/tests/test_packaged_schemas.py`, and run it to see it fail (the files are missing from the wheel):
  - `importlib.resources.files("ext_r2c") / "schema" / "v1"` holds exactly the six names of `standard_dir / "schema"`;
  - each file has the same bytes.
- [ ] T042 [US3] Create `python/hatch_build.py` (research R5):
  - class `SchemaHook(BuildHookInterface)`, whose `initialize` force-includes the first existing directory of `<root>/../standard/v1/schema` and `<root>/standard/v1/schema` as `ext_r2c/schema/v1`;
  - it raises `FileNotFoundError` when neither exists.
- [ ] T043 [US3] Wire the hook in `python/pyproject.toml`:
  - add `[tool.hatch.build.targets.wheel.hooks.custom]`;
  - add `[tool.hatch.build.targets.sdist.force-include] "../standard/v1/schema" = "standard/v1/schema"`;
  - add `"hatch_build.py"` to the sdist `include` list;
  - check that `uv build` succeeds (sdist first, then the wheel from the sdist) and that the sdist contains no stray directory (`.wheel-venv`, `dist`).
- [ ] T044 [US3] Run quickstart scenarios 6–7, then verify on Python 3.11, 3.12 and 3.13 (three fresh venvs) and commit `build: ship the v1 schemas inside the wheel`.

**Checkpoint**: US3 is complete; the Python package carries the standard's shapes.

---

## Phase 6: User Story 4 — the standard is the source of truth (P3)

**Goal**: design docs point to the standard, and deviations are recorded.

**Independent test**: US4 scenarios 1–2. Grep for each doc's dated note, and for the deviation
table in research.md.

- [ ] T045 [P] [US4] Add a dated note under the status line of `docs/research/2026-11-20-r2c-v1-design-brief.md`, without rewriting the body: the normative text now lives in `standard/v1/README.md` and wins, and deviations D1–D4 are listed in `specs/001-standard-v1/research.md`.
- [ ] T046 [P] [US4] Update `docs/whitepaper.md`:
  - a dated note at the top (same message);
  - replace the illustrative MCP JSON in §7 with an excerpt of `standard/v1/examples/mcp/elicitation-approval.json`, showing the D1 placement;
  - in the §7 table, change the `question` row to say the R2C object sits in the `InputRequiredResult`'s `_meta`;
  - change §6.3's wire excerpt to an excerpt of `full-streamed-run.json`.
- [ ] T047 [P] [US4] Update `docs/design-docs/one-remote-two-doors.md` and `docs/design-docs/activity-and-usage-kinds.md` only where they state MCP placement that D1 changed. Grep `_meta` in `docs/` and fix each stale hit.
- [ ] T048 [US4] Update:
  - `standard/v1/README.md` status line ("draft, written 2026-11-20");
  - `AGENTS.md` docs-table row "Read the normative standard" (drop "once written");
  - `WORKSTATE.md` (001 done; next 002);
  - `CHANGELOG.md` `[Unreleased]` → `Added`: the standard v1 text, schemas, examples, checks, and packaged schemas.

  Then verify and commit `docs: the standard is the source of truth`.

**Checkpoint**: every user story is complete.

---

## Phase 7: Polish and close

- [ ] T049 Ask a fresh-context reviewer for SC-005: an agent with only `standard/v1/README.md` and `standard/v1/schema/`, asked for each kind's required fields and its placement on A2A and on MCP. Fix any wrong answer in the README, and record the result in the phase report.
- [ ] T050 Final quality gate:
  - fresh `uv build`; full suite on 3.11, 3.12 and 3.13;
  - grep the docs for stale names (`inputRequests` placement, "once written", "placeholder");
  - run the leak scan over `git diff aca2860..HEAD`;
  - tick every checkbox in this file;
  - commit `chore(001): close standard v1` (no push without the maintainer's go).

---

## Dependencies and execution order

- **Setup (Phase 1)** has no dependency. **Foundational (Phase 2)** depends on Phase 1 and blocks every story.
- **US1 (Phase 3)** depends on Phase 2.
- **US2 (Phase 4)** depends on US1, because examples cite README rule ids and validate against the schemas.
- **US3 (Phase 5)** depends on US1 (the schemas) only; it may run before US2 if wanted.
- **US4 (Phase 6)** depends on US2 (the white paper quotes examples) and on US3 (the CHANGELOG lists packaging).
- **Polish (Phase 7)** comes last.
- Within a phase: the test tasks (T007–T010, T041) come before what they test; tasks writing the same file (T021–T025, the README) run in order.

## Parallel opportunities

- Phase 1: T002, T003 and T004 together.
- Phase 2: T007–T010 together, after T006 (they import the helper).
- US1: the six schemas T012–T017 together, then T018–T020 together; the README tasks are sequential.
- US2: T027–T034 together, and T036–T039 together. T035 (the full run) comes after the single examples, so it reuses their shapes.
- US4: T045, T046 and T047 together.

Example dispatch for US1 schemas (one message, six agents, each given the data-model row and the
FR-016 rules): "write `standard/v1/schema/<kind>.json` per data-model.md §<kind>; return the
file and the list of rules it enforces".

## Implementation strategy

- **MVP**: Phases 1–3. The standard text and the six schemas can be adopted on their own.
- **Then**: US2 (the examples, which specs 003 and 004 need), US3 (packaging, which spec 002 needs), US4 (docs).
- **One phase per go.** Each phase ends with a green suite on the installed wheel, a leak scan and a commit, then a report in Vietnamese and a stop.
