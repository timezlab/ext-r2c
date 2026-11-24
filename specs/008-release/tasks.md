---
description: "Task list for 008-release"
---

# Tasks: The first pre-release, a tested wheel on a GitHub release (`0.1.0a1`)

**Input**: design documents in `specs/008-release/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII asks for tests first, run in the installed-wheel venv. Here the code
under test is mostly the repository's own tooling (`scripts/release/`, the workflow files, the documents),
read **by path** from the checkout as `test_example_langgraph.py` reads the example (plan, Constitution
Check). In every phase:
1. write the phase's tests first;
2. run them and confirm they fail for the expected reason;
3. only then write the script, the workflow or the document.

If a test passes on its first run, say so in the phase's report and prove it is not vacuous by a
**mutation check**: break the line it guards, watch the test fail, restore.

**Organization**: the six phases of the plan's delivery order. `/speckit-implement` runs **one phase per
go**: finish the phase, verify, commit, report in Vietnamese, stop, unless the maintainer says "hết spec".
- Phases 1 and 2 are the scripts (US3 refusals, US5 notes); phase 3 is the shared definition of the checks
  (US1, US2) and **ends with a request to push**; phase 4 is the release job (US2, US4); phase 5 is the
  adopter's page and the `0.1.0a1` commit (US1, US5); phase 6 is the review, the first manual run and the
  report, and **ends before the tag**.
- Three tasks need a go of their own and are marked **[GO]**: the push after phase 3 (T036), the push
  after phase 6 (T062) and the manual run (T063). Pushing the first tag is not a task of this list.

## The decisions this list relies on

The maintainer asked for the plan and the tasks on 2026-11-24 ("duyệt, sinh plan và task"). The plan reads
that as approval of the spec with D1–D11 as written and takes its recommended answer on four of its five
points; point 1 (the lint) waits for an answer and the list follows its default. If the maintainer
overrules one, the tasks named change first.

| Point / decision | Settled as | Where it shows |
|---|---|---|
| D3 no PyPI; install by address | every install line is an address | T050, T051, T054 |
| D5 the private scan is the maintainer's | a runbook step, not a gate | T051 |
| D11 publishing not rehearsed | the fake `gh` and one real run; the manual run stops before it | T038, T063 |
| Plan point 1: lint the workflows | **A** (default: not run); **B** if the maintainer allows `zizmor` 1.32.0 offline and `actionlint` | T033, T046 |
| Plan point 2: content check and scan in CI | **A**: in `wheel.yml`'s `inspect` | T029 |
| Plan point 3: pin CI to the SHAs | **A** | T029, T030 |
| Plan point 4: order of the pushes | **A**: after phase 3, and again after phase 6 | T036, T062 |
| Plan point 5: the README before the tag | **A**: tag in the same sitting | T051, T054 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US5 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `rm -rf dist && uv build`;
  2. recreate `../.ci-venv`, install the wheel and the `dev` group (Python 3.11);
  3. `../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider` (the whole suite: the tests of
     specs 001–007 must still pass unchanged);
  4. the four single-extra scripts as in CI (`core_only.py`, `a2a_only.py`, `mcp_only.py`,
     `langgraph_only.py`) and, from phase 3, `adopter_path.py`;
  5. `uvx ruff check --select F src tests ../scripts`;
  6. repeat 1–3 on Python 3.12 and 3.13 at the end of phases 1, 3 and 6 (and when a task says so);
  7. leak-scan the staged added lines (must be 0);
  8. commit with an explicit pathspec and no co-author trailer. **Never push** except at a **[GO]** task.

## Path conventions

- Scripts: `scripts/release/`; tests and helpers: `python/tests/`; workflows: `.github/workflows/`;
  documents: `docs/` and the READMEs.
- A test imports a script **by path** (`parents[2] / "scripts" / "release"`, put on `sys.path` with
  `monkeypatch.syspath_prepend`) through one helper, `load_script(name)`, in `tests/release_fixtures.py`, and
  fails with a clear message when run outside a checkout (as the example's test does).
- The scripts take `--root PATH`; tests build a small repository in `tmp_path` (a `pyproject.toml`, a
  `CHANGELOG.md`, two `LICENSE` files, `docs/known-limits.md`, `standard/v1/schema/`), a small wheel with
  `zipfile` and a small sdist with `tarfile`. Nothing in a test touches the real tree, the network or `gh`.
- **Public repository (VI).** All fixture content is invented: `example.com`, names such as `alice`. A string
  that the repository's own commit scan refuses (a home-directory prefix, a private address range) is
  **never written whole in a file**: the scan's patterns and the fixtures spell it from fragments at run
  time (for example `"/" + "ho" + "me" + "/"`), and a test pins that the planted text is found.
- Warnings: `-W error::UserWarning` is on; handle a warning where it is raised and record it in
  `research.md`; never relax the flag.
- A workflow file is read as data with PyYAML; the key `on:` loads as `True`, so the helper looks up both.
- A task that edits a repository file uses the edit tools, not a shell redirect or `sed -i`.
- The scratch probes of the plan's research (the scan prototype) stay out of the repo.

---

## Phase 1: Scripts' core and pre-flight

**Goal**: the shared module and the first gate: every refusal of FR-004 exists, names its check and what to
change, and creates nothing; a manual start skips only the tag-bound checks.

**Independent test**: `tests/test_release_common.py`, `tests/test_release_preflight.py`.

- [X] T001 [US3] Confirm the ground and the "no change" claims. Re-measure and write one dated line under
  "Phase 1" in the notes of this file: PyPI answers `404` for `ext-r2c`; the default token permission is
  `read`; no tag and no release exists; `cmp python/LICENSE LICENSE` is silent; the wheel has 74 files and
  the sdist 173; **no dependency or extra changes** for this spec (`python/pyproject.toml` is touched only
  at T054). If a fact moved (a release or a tag appeared, the name is taken), stop and tell the maintainer.
- [X] T002 [P] [US3] `tests/release_fixtures.py` (a helper, not collected): `load_script(name)`;
  `make_repo(tmp_path, version=, changelog=, same_license=)` writing the small repository of "Path
  conventions"; `make_git_repo(...)` (a temporary git repository with `main`, a commit and optional tag,
  author set by `-c`); `make_wheel(...)`, `make_sdist(...)` builders (used from phase 2); `planted(kind)`
  returning the strings the scan must find, **built from fragments**.
- [X] T003 [P] [US3] `tests/release_fakes.py` (a helper, not collected), first cut: an executable `gh`
  written into `tmp_path/bin` and put first on `PATH`, holding a JSON state, answering only `gh api
  repos/OWNER/NAME/releases/tags/TAG` (found as published, `HTTP 404` as absent, any other error) and
  refusing every other call with a non-zero exit and a line naming the call; it appends each call to a log
  the test can read. Phase 4 extends it with the table of research R3.
- [X] T004 [P] [US3] `tests/test_release_common.py`, written to fail: version grammar (accepted: `0.1.0a1`,
  `0.1.0b2`, `1.2.3rc10`; `version-grammar`: `0.1.0a01`, `0.1.0.dev1`, `0.1.0a1.post2`, `01.0.0a1`, `0.1a1`,
  `v0.1.0a1`, `0.1.0-alpha.1`, a trailing space; `prerelease-only`: `0.1.0`, `1.0.0`); tag grammar (`v` +
  version exactly); `changelog_section` (found; empty; only `###` headings; missing; bad date; `[Unreleased]`
  is never a section; the next `## ` ends it; a section with a date in the future is accepted);
  `wheel_name`, `sdist_name`, `address`; `Refusal` prints exactly `refused [id]: what. change.`; `run_main`
  maps a `Refusal` to 1, any other exception to 2 and success to 0.
- [X] T005 [P] [US3] `tests/test_release_preflight.py`, written to fail, one test per row of
  [contracts/scripts.md](contracts/scripts.md) (`preflight.py`): `event` (an unknown event; `push` on a
  branch ref); `version-grammar`; `prerelease-only` (message says a final release needs its own decision);
  `tag-matches-version` (message names both); `changelog-section` (missing, empty, bad date);
  `on-main` (a temporary git repository: a tag on a commit that is not an ancestor of `origin/main`
  refuses, one on `main` passes); `no-published-release` (fake `gh`: found refuses; `404` passes; a draft
  looks like `404` and passes; a network or server error refuses, fail closed); `license-copy` (two files
  that differ by one byte). Plus: a manual start passes a good fixture and prints `skipped [<id>]: manual
  start` for exactly the three tag-bound checks; a manual start with a bad version still refuses; **every
  refusal names the check and what to change, and the directory listing is the same before and after**.
- [X] T006 [US3] Run T004 and T005: they fail because `release_common` and `preflight` do not exist, and
  for no other reason. Write the failure line in the notes.
- [X] T007 [US3] `scripts/release/release_common.py` (`Refusal`, the strict version regex of research R4,
  `read_version`, `changelog_section`, `wheel_name`, `sdist_name`, `address`, `run_main`) until T004 passes.
- [X] T008 [US3] `scripts/release/preflight.py` per the contract, until T005 passes.
- [X] T009 [US3] Run `preflight.py --event workflow_dispatch` on the real tree. Expected today:
  `refused [prerelease-only]` and exit `1` (the version is `0.0.1`). Write the line in the notes: the gate
  works on the real repository.
- [X] T010 [US3] Mutation check: change the `tag-matches-version` comparison, the `prerelease-only` test and
  the `on-main` ancestry call, one at a time; each makes a named test fail; restore. Record the three.
- [X] T011 Verify (Python 3.11, then 3.12 and 3.13; `ruff` includes `../scripts`) and commit: `feat(008):
  release script core and pre-flight`.

**Checkpoint**: pre-flight is a tested script; nothing in a workflow yet.

---

## Phase 2: Content, scan, sums and notes

**Goal**: the checks on the built files and the notes, each a script with fixture tests; the known limits
exist and are linked to the detail; on the real build the scan finds 0 and the content check passes.

**Independent test**: `tests/test_release_content.py`, `tests/test_release_scan.py`,
`tests/test_release_sums.py`, `tests/test_release_notes.py`, the first section of
`tests/test_release_docs.py`.

- [X] T012 [P] [US3] `tests/test_release_content.py`, written to fail: a good fixture passes; one test per
  id of the contract: a wheel member outside `ext_r2c/` and its dist-info; a `tests`, `examples` or
  `test_*.py` path inside; `ext_r2c/py.typed` missing; a binary member (`wheel-contents`); a wrong
  `Version:`, a missing `Name`, a missing `Provides-Extra` of `a2a`, `mcp` or `langgraph`
  (`wheel-metadata`); schema names that differ from `standard/v1/schema/` in one extra or one missing file
  (`schemas`); an sdist with a wrong root, a wrong `PKG-INFO` version, an `examples/` folder or no schema
  (`sdist-contents`); a missing wheel or sdist; the version defaulting to `pyproject.toml`.
- [X] T013 [P] [US3] `tests/test_release_scan.py`, written to fail: one planted hit for each category
  (`home-path` for Linux, macOS and Windows shapes and the root folder; `private-address` for each RFC 1918
  range; `email`; `token` for each shape), found with member name, category and **the number of lines**
  (two matches on one line count once); wheel (zip) and sdist (tar) both read; a binary member is skipped
  and named; reserved domains pass (`example.com`, `.org`, `.net`, `.example`, `.test`, `.invalid`,
  `.localhost`); a near miss (a longer dotted number such as `10.0.0.1.2`) is not a hit; **no planted
  string, and no fragment of one, appears in the output**; exit codes 0 and 1.
- [X] T014 [P] [US3] `tests/test_release_sums.py`, written to fail: `write` makes the format of
  [contracts/release-assets.md](contracts/release-assets.md) (two spaces, sorted, final newline, no line for
  itself); `sha256sum -c` accepts it (skipped if the binary is absent); `check` fails on an altered byte, a
  missing file, an extra wheel and a missing list; exactly one wheel and one sdist are required; `--summary`
  writes a table to the file named by `GITHUB_STEP_SUMMARY`.
- [X] T015 [P] [US5] `tests/test_release_notes.py`, written to fail: three parts in order with the headings
  `## Status`, `## Known limits`, `## Changes in V`; the four placeholders filled and an unknown `{{x}}`
  refused (`notes`); every line of the known-limits file after its title present verbatim and in order; the
  changelog part is the body of exactly that version's section (not `[Unreleased]`, not the next version);
  an empty or missing section is `changelog-section`; a missing or empty known-limits file or status block is
  `notes`.
- [X] T016 [P] [US5] `tests/test_release_docs.py`, section 1, written to fail: `docs/known-limits.md`
  exists, starts with one title line, has one bullet for each of the seven limits of FR-015 (found by a
  word of each), and every link in it points at a file and a heading that exist in the repository (most in
  `python/README.md`; see the Phase 2 notes for the two that do not).
- [X] T017 Run T012–T016: each fails because the script or the file does not exist, and for no other
  reason. Write the failure lines in the notes.
- [X] T018 [P] [US3] `scripts/release/content.py` until T012 passes.
- [X] T019 [P] [US3] `scripts/release/scan.py` until T013 passes (patterns spelled from fragments; the leak
  scan of the commit must report 0 on the file).
- [X] T020 [P] [US3] `scripts/release/sums.py` until T014 passes.
- [X] T021 [US5] `docs/known-limits.md` (a title and the seven bullets of FR-015, each with a link to the
  detail in `python/README.md`) and `scripts/release/status-block.md` (the status block of research R11 with
  its four placeholders) until T016 passes.
- [X] T022 [US5] `scripts/release/notes.py` until T015 passes.
- [X] T023 [US3] **Real bytes.** `uv build --out-dir <a folder outside the repository>` from `python/`, then
  `sums.py write`, `sums.py check`, `content.py` and `scan.py` on it. Expected and written in the notes:
  `content ok: 0.0.1`, the wheel's 74 files and the sdist's files (173 before this phase added tests, 182 after)
  and `scan ok: 256 files, 0 hits` (SC-006, SC-007). If the scan finds a
  line, the **file and category** are read, not waved through: fix the text or, for an invented address, use
  `example.com`.
- [X] T024 [US3] Mutation check: remove one category from the scan, remove the reserved-domain allowance
  (the sdist's one baseline hit must reappear), drop the `py.typed` check, skip the sums comparison, skip
  the empty-section check in the notes; each makes a named test fail; restore.
- [X] T025 Verify and commit: `feat(008): content check, scan, checksums and release notes`.

**Checkpoint**: the scripts that read the built files and assemble the notes are tested; the known limits
exist.

---

## Phase 3: The shared definition of the checks

**Goal**: CI and the release will run one definition. `wheel.yml` builds once, the matrix tests that one
wheel (the adopter's path included), `inspect` reads the same bytes; `python.yml` only calls it.

**Independent test**: `tests/test_release_workflows.py`, section 1; the local simulation of T032; then the
real run on GitHub (T036–T037).

- [X] T026 [P] [US2] `tests/test_release_workflows.py`, section 1, written to fail: for **every** file under
  `.github/workflows/` the rules of [contracts/workflows.md](contracts/workflows.md) (no `${{` in any
  `run:`, every `uses:` a 40-hex SHA or a local path, `persist-credentials: false` on each checkout,
  `enable-cache: false` on each setup-uv, no `secrets`, no `pull_request_target` or `workflow_run`, names
  everywhere, top-level `contents: read`); `wheel.yml` is `workflow_call` with jobs `build`, `checks`,
  `inspect`, the matrix of `3.11`, `3.12`, `3.13` only there, the four single-extra scripts, the adopter's
  step, and the `sums.py`, `content.py` and `scan.py` steps; `python.yml` keeps its triggers (`push` to
  `main`, `pull_request`), calls `wheel.yml` and holds no `uv build`, no `pytest` and no `*_only.py`.
- [X] T027 [P] [US1] `python/tests/adopter_path.py` (not collected) per the contract: asserts `pytest` is not
  importable, runs `python main.py --auto` in `examples/langgraph_agent` on two free ports with a 120 s
  timeout and no `R2C_EXAMPLE_MODEL`, asserts exit 0 and the two replies of the example's README, prints
  `adopter path: ok`; a failure prints the last lines of the output.
- [X] T028 [US1] Run the adopter's path by hand in a venv built as CI will build it (the wheel with
  `[a2a,mcp,langgraph]` and `uvicorn`, no dev group), on 3.11 and 3.13: `adopter path: ok`. Then prove it can
  fail: in a venv **without** the `langgraph` extra it fails with a clear message (the first draft said
  "without `uvicorn`", which cannot fail: `mcp` brings `uvicorn`, see the notes); in one with `pytest`
  installed it refuses. Write the three outcomes in the notes.
- [X] T029 [US2] `.github/workflows/wheel.yml` per the contract and the SHAs of research R6, with `# vX.Y.Z`
  comments, `permissions: contents: read`, `ubuntu-24.04`, `enable-cache: false`, the matrix once, values
  in `env:` and not in `run:`.
- [X] T030 [US2] `.github/workflows/python.yml`: the triggers as today and one job that calls `wheel.yml`.
- [X] T031 [P] `.gitignore`: `.adopter-venv/` and `.release-dist/`.
- [X] T032 [US2] **Simulate the legs locally**, on 3.11, 3.12 and 3.13: build once; copy `dist` aside as an
  artifact would arrive; run, in order, the steps of `checks` (the sums check; the clean venv with the wheel
  and the dev group, `pytest`; the four single-extra scripts; the adopter's path) and the steps of `inspect`
  (sums, content, scan). Expected: green on all three, with the same wheel checksum in each. Write the three
  checksums in the notes.
- [X] T033 [US2] If the maintainer allowed it (plan point 1, B): run `zizmor` 1.32.0 `--offline` (a throwaway
  `uvx` environment, no token) and `actionlint`'s release binary (checksum compared) on `.github/workflows/`;
  fix each finding test first where a test can express it; record versions and the summary. If not allowed,
  write "lint not run (plan point 1, default A)" in the notes.
- [X] T034 [US2] Run T026: it passes. Run the whole suite on the wheel.
- [X] T035 Verify and commit: `ci(008): one reusable definition of the checks, and the adopter's path`.
- [X] T036 **[GO]** Ask the maintainer to push. The push carries the unpushed `c9e7a7c`, `b307085`, `0a139b6`,
  the spec-008 documents and the commits of phases 1 to 3. After the go: `git push`, then watch the run of
  the pushed commit (`gh run list`, `gh run watch`).
- [X] T037 [US2] The refactor's proof, written in the notes: `wheel / build`, the three `wheel / checks`
  legs and `wheel / inspect` are green; each leg's log shows the build's checksum; each leg ends with `adopter
  path: ok`. A red leg is fixed here, as its own commit, before phase 4 begins.

**Checkpoint**: CI is one shared definition and has been seen green on GitHub; no release workflow exists.

---

## Phase 4: The release job

**Goal**: `release.yml` and the one script that writes. The publishing order, the reruns and "never touch a
published file" are tested against a fake `gh`; the workflow's permission rules are tested as data.

**Independent test**: `tests/test_release_publish.py`, `tests/test_release_verify.py`,
`tests/test_release_workflows.py`, section 2.

- [X] T038 [P] [US2] Extend `tests/release_fakes.py` with the table of research R3 (`release list --json`,
  `create`, `edit`, `view --json assets`, `delete-asset`, `upload --clobber`, `download --pattern --dir`),
  a state that mirrors drafts and published releases, a switch to fail at call N, a switch to return altered
  bytes on download, and the log of calls. Any call outside the table exits non-zero and is logged.
- [X] T039 [P] [US2] `tests/test_release_publish.py`, written to fail: a fresh run creates a draft
  (pre-release, not latest, `--verify-tag`), uploads the three files, reads them back and publishes **last**;
  a leftover draft with a stray asset has it removed; a leftover draft with the three files equal is
  uploaded again and published; an upload that comes back different stops with `upload-differs` and the log
  has **no** `--draft=false` call; a published release with equal sums succeeds with **no write call** in
  the log; a published release that differs refuses with `published-differs` and the log has no `upload`,
  no `delete-asset`, no `edit`, no `delete`; a directory without exactly the three names is
  `unexpected-files`; a `gh` failure at **each** call index ends non-zero with no public release; `--repo`
  is on every call; the script reads the state again after publishing and requires published, pre-release,
  not draft; no call outside the table is ever made.
- [X] T040 [P] [US2] `tests/test_release_verify.py`, written to fail: a local HTTP server on `127.0.0.1`
  serves the three files; equal bytes pass; an altered wheel or sdist is `public-differs`; a `404` is
  `public-differs`; **the server records no `Authorization` header**. The script takes a `--base-url` for
  this (a test seam; the default is the GitHub address). Add that option to
  [contracts/scripts.md](contracts/scripts.md) in the same commit.
- [X] T041 [P] [US2] `tests/test_release_workflows.py`, section 2, written to fail: `release.yml`'s triggers
  are exactly a push of tags `v*` and a manual start; no `pull_request`; exactly one job has `contents:
  write` and it is `publish`; its steps hold none of `setup-uv`, `pip`, `uv`, `python -m`, `python -c`,
  `import` or an `install`; the `needs` of each job and the `if` of `publish` and `verify` are those of the
  contract; `concurrency` has `cancel-in-progress: false`; `GH_TOKEN` is `${{ github.token }}` in `preflight`
  and `publish` and absent from `verify`; `wheel` calls `./.github/workflows/wheel.yml`; no `secrets`.
- [X] T042 Run T039–T041: each fails because the script or the workflow does not exist, and for no other
  reason. Write the failure lines in the notes.
- [X] T043 [US2] `scripts/release/publish.py` per the contract and research R3 until T039 passes.
- [X] T044 [P] [US2] `scripts/release/verify.py` until T040 passes.
- [X] T045 [US2] `.github/workflows/release.yml` per the contract, until T041 passes.
- [X] T046 [US2] Lint if allowed, as T033; otherwise note it again.
- [X] T047 [US2] Mutation check: add a `pip install` step to `publish`, add a `pull_request` trigger, set
  `cancel-in-progress: true`, give `verify` a `GH_TOKEN` (each makes a named workflow test fail); in
  `publish.py` publish before the compare, call `gh release delete`, and replace a published file (each
  makes a named publish test fail); restore.
- [X] T048 [US4] Read the workflow once as a manual start: list, by job, what runs and what is skipped, and
  confirm from the YAML (and by T041) that nothing in a manual start can write (`publish` and `verify` are
  skipped by `event_name`, `preflight` runs `--event workflow_dispatch`). Write the list in the notes.
- [X] T049 Verify and commit: `feat(008): the release job, the publishing script and the public check`.

**Checkpoint**: the release job exists and is tested as far as it can be before it runs. It has not run.

---

## Phase 5: The adopter's page and the cut

**Goal**: the maintainer's runbook, the install line in every README, and the one commit that sets
`0.1.0a1`. The README address is tied to the wheel's version by a test.

**Independent test**: `tests/test_release_docs.py` (all sections), the whole suite on the `0.1.0a1` wheel,
and `preflight.py` and `notes.py` on the real tree.

- [X] T050 [P] [US1] `tests/test_release_docs.py`, sections 2 and 3, written to fail: the install address in
  the root README, `python/README.md` and the example's README equals
  `https://github.com/timezlab/ext-r2c/releases/download/v{V}/ext_r2c-{V}-py3-none-any.whl` for `V` the
  version of the **installed wheel**; no line that runs `pip install`, `uv pip install` or `uv add` names
  `ext-r2c` without an address or a wheel path; both READMEs say the bare PyPI name is not this project
  and link `docs/known-limits.md`; `docs/releasing.md` has a heading for each step of FR-017; `AGENTS.md`
  links it; the metadata classifier is not `Pre-Alpha` and, for an `aN` version, is `3 - Alpha`; the changelog
  has a dated, non-empty section for the installed version; `notes.py` on the real repository writes the
  three parts and the changes part is not empty.
- [X] T051 [US1] `docs/releasing.md`, in the order of research R8: the number; the version commit; the
  maintainer's **own** private-token scan of the built files (the pattern is not in this repository; the step
  is a promise); push and wait for CI; the manual run (`gh workflow run release.yml --ref main`); the tag,
  annotated, and "tag in the same sitting as the push of the version commit"; what to read afterwards; a
  failed run (re-run the failed jobs, or delete the unpublished tag and the draft **without** cleaning up the
  tag by the release command); a published mistake (the next number; withdrawing is by hand and only for
  leaked data). Link `docs/known-limits.md` and the plan's gaps.
- [X] T052 [P] [US1] `AGENTS.md` (two rows of the Docs table; the file stays under 150 lines) and
  `ARCHITECTURE.md` (`scripts/release/`, the three workflows, and the rule that `scripts/` imports nothing
  from `ext_r2c` and the package nothing from it).
- [X] T053 [US1] Commit the documents so far: `docs(008): the releasing runbook and the layout`.
- [X] T054 [US1] **The `0.1.0a1` commit**, one commit: `python/pyproject.toml` (`version = "0.1.0a1"`, the
  classifier `Development Status :: 3 - Alpha`); the root `README.md` (the status paragraph says alpha and
  links `docs/known-limits.md`; a new *Install* part with the one address line and the sentence about the
  bare PyPI name); `python/README.md` (the same line and sentence above its Install table; its wheel-file
  lines say the placeholder is that address); `examples/langgraph_agent/README.md` line 16 (the address
  line); `CHANGELOG.md` (`## [Unreleased]` becomes `## [0.1.0a1] - <date of the commit>`, a fresh empty
  `## [Unreleased]` above it, and a line under *Added* for the release tooling and the known limits).
  Nothing under `python/src/` or `standard/`.
- [X] T055 [US1] Rebuild, reinstall and run the whole suite on the `0.1.0a1` wheel (T050 now passes;
  `test_smoke` pins `ext_r2c.__version__`). Then, on the real tree: `preflight.py --event workflow_dispatch`
  prints `preflight ok: version 0.1.0a1`; `notes.py` writes the notes (read them once, whole, and say
  whether an outsider could follow them); `sums.py`, `content.py` and `scan.py` on the new build pass; and
  `git diff --stat 06ff099 -- python/src standard` is **empty** (SC-010). Write each in the notes.
- [X] T056 [US1] The reading check (SC-009): a fresh-context reader is given **only** the two READMEs and the
  generated notes and answers: what to type to install; whether the bare name `ext-r2c` on PyPI is this
  project; which limits to expect. Record its answers; SC-009 is **for the maintainer to confirm**, as SC-012
  of the earlier specs was; it is not claimed here.
- [X] T057 Verify and commit: `feat(008): set 0.1.0a1 and tie the install address to the wheel`.

**Checkpoint**: the repository is ready to be released; nothing has been pushed beyond phase 3, no tag
exists, no release exists.

> Note (2026-11-24): phase 5 is done (T050–T057). The version is `0.1.0a1`, the three READMEs and the notes
> hold one install address that the tests tie to the wheel's name, and `preflight.py` passes on a manual start.
> Still true: nothing pushed beyond phase 3, no tag, no release.

---

## Phase 6: Review, the first manual run, and the report

**Goal**: an outside review of the part that holds write permission, the full gate on three Pythons, the
first manual run on GitHub, and a report. The phase ends **before the tag**.

- [X] T058 [P] Outside review of the workflows and the scripts, self-contained briefs, in one message: a
  **code reviewer** on `git diff 06ff099..HEAD` (what the change does, the contracts to read, the output
  contract: findings ranked with file and line) and a **security reviewer** on `release.yml`, `wheel.yml`,
  `python.yml`, `publish.py`, `verify.py`, `scan.py`, `preflight.py` (the questions: can any input reach a
  shell or a path; can the write job run built code; what can a fork or a pull request reach; what the
  public log can show). Each finding is fixed test first or answered in `research.md` (R16); a finding about
  the first real run is added to the runbook.
- [X] T059 The whole gate on 3.11, 3.12 and 3.13: the verify list, the simulation of T032 again on the final
  files, and the leak scan over the whole diff since `06ff099` (must be 0).
- [X] T060 `WORKSTATE.md` (spec 008 built, waiting for the push and the tag), `ARCHITECTURE.md` if the review
  changed anything, `CHANGELOG.md` if it needs a line, and the memory of this project; a dated note in
  `plan.md` that the body is kept as planned and where the build differs (the deviations list below).
  Commit: `docs(008): close the release work, ready for the first tag`.
- [X] T061 [P] Count what was built against the plan's scale line (files, tests, tasks) and the success
  criteria below; put the table in the notes.
- [X] T062 **[GO]** Ask the maintainer to push the commits of phases 4 to 6. After the go: `git push`; watch
  the run of the final commit: `wheel / build`, three `wheel / checks`, `wheel / inspect` green.
- [X] T063 **[GO]** Ask the maintainer to start the manual run. After the go: record `git ls-remote --tags
  origin | wc -l` and `gh release list | wc -l`; `gh workflow run release.yml --ref main`; watch it. Expected
  (SC-004, quickstart 6): `preflight` green with the three tag-bound checks said to be skipped, `wheel` green,
  `publish` and `verify` skipped, the build job's summary lists the wheel, the sdist and the sums, and the two
  counts are the same afterwards. A red job is read and fixed here as its own commit; the manual run is then
  repeated.
- [ ] T064 (optional, needs its own go) Red on purpose, one gate per scratch branch (quickstart 6): a version
  `0.1.0`, a renamed changelog section, a planted private-looking line in a test file, a failing test. Each
  run is red at the named gate and makes no public change; delete each branch afterwards.
- [X] T065 Report to the maintainer in Vietnamese: what exists, what was proven (and by which run), what is
  **not** proven (the seven publishing calls and `verify` run for real only at the first tag; the wiring
  before the first push; the lint if it was not run), the reading check for SC-009, what the maintainer does
  next (their own private-token scan, then `docs/releasing.md`), and that **the tag `v0.1.0a1` is theirs to
  push on a separate go**. Stop. Never push a tag; never create a release.

---

## Dependencies and order

- Phase 1 → phase 2 (the scripts share `release_common.py`) → phase 3 (`inspect` calls `content.py` and
  `scan.py`) → phase 4 (`release.yml` calls `wheel.yml`) → phase 5 (the version commit comes last so the
  README test, the notes and the manual run see `0.1.0a1`) → phase 6.
- Inside a phase: tests first (marked "written to fail"), then the "fail for the expected reason" task, then
  the code. Tasks marked [P] touch different files.
- T036 and T037 gate phase 4: a red CI there is the refactor's and is fixed first.
- T062 and T063 gate the report. T063 needs `release.yml` on `main`, which T062 provides.

## Parallel opportunities

- Phase 1: T002, T003, T004 and T005 write different files.
- Phase 2: T012–T016 together, then T018–T020 together; T021 and T022 follow T016 and T015.
- Phase 3: T026 and T027 together; T031 beside T029.
- Phase 4: T038–T041 together; T043 and T044 together after.
- Phase 5: T050 beside T051 and T052.
- Phase 6: T058's two reviewers run together; T061 beside T060.

## Success criteria → tasks

| SC | Met by |
|---|---|
| SC-001 | T028, T032, T055 (a clean venv, one line, the example); after a real release, `verify` |
| SC-002 | T005, T012, T013, T039 (the script gates); T064 (the wiring) |
| SC-003 | T014, T032, T039 |
| SC-004 | T063 |
| SC-005 | T026, T041, T047 |
| SC-006 | T013, T023, T055 |
| SC-007 | T012, T023 |
| SC-008 | T015, T050, T055 |
| SC-009 | T056 (for the maintainer to confirm) |
| SC-010 | T037, T055, T059 |
| SC-011 | T016, T050, T055 |

## Implementation strategy

- **MVP = phases 1 to 3**: the refusals and the shared, one-build definition of the checks, seen green on
  GitHub. It already makes CI prove the adopter's path on every push, and it publishes nothing.
- Phase 4 adds the part that can write, tested against a fake. Phase 5 makes the repository say what to
  type. Phase 6 shows the whole job once, without writing a release.
- Stop after each phase for the maintainer's go. The tag is not in this list.

## Notes

*(Dated lines go here as each phase runs: facts measured, the failure lines of the "fail for the expected
reason" tasks, the mutation checks, the outcomes of the manual simulation and of the real runs, and every
deviation from the plan, each with its reason.)*

### Phase 1 (2026-11-24)

- **T001, the ground.** PyPI answers `404` for `ext-r2c`; the default token permission is `read`; no tag
  (`git ls-remote --tags origin` is empty) and no release; `cmp python/LICENSE LICENSE` is silent; a fresh
  `uv build` of `0.0.1` gives a wheel of 74 files and an sdist of 173 files. Nothing moved. `python/pyproject.toml`
  is touched only at T054.
- **T006, red.** `tests/test_release_common.py` and `tests/test_release_preflight.py` ran before the scripts
  existed: 76 errors, every one `the release scripts are not at .../scripts/release` (the missing production
  directory, raised by `load_script`) and no other reason.
- **T007/T008, green.** `scripts/release/release_common.py` and `preflight.py`; 76 passed, then 77 with the
  capital-letter test below.
- **T009, the real tree.** `preflight.py --event workflow_dispatch` prints `refused [prerelease-only]: the
  version 0.0.1 is a final release. ...` and exits `1`; `--event schedule` prints `refused [event]` and exits
  `1`; no arguments exits `2`.
- **A test added after its fix.** The refusal line's second sentence was lower case ("remove it") when T009
  ran, against the contract's `What to change.` I fixed the line in `Refusal.line()` and added
  `test_what_to_change_starts_with_a_capital` afterwards, and the mutation check below proves it can fail. That
  is the one place this phase wrote a fix before its test; the old `run_main` test expected the lower case
  and was corrected with it.
- **T010, mutation check** (a scratch harness, restored after each mutant; the first run was invalid because a
  stale expectation made every mutant "die" on an already red test, so it was rerun after the fix): 7 of 7
  killed by the test that names them: `tag-matches-version` never refuses, `prerelease-only` never refuses,
  `on-main` never refuses, a `gh` error read as "not found", no capital on the change, the changelog date not
  validated, sub-headings counted as a body.
- **T011, verify.** 2923 passed on 3.11, 3.12 and 3.13 (2846 before this spec, plus 77); the four
  single-extra scripts ok on all three; `ruff --select F src tests ../scripts` clean.

### Phase 2 (2026-11-24)

- **T017, red.** The four script tests and the docs section ran before `content.py`, `scan.py`, `sums.py`,
  `notes.py` and `docs/known-limits.md` existed: 105 errors (25 content, 50 scan, 14 sums, 13 notes, 3 docs).
  Every one is `ModuleNotFoundError: No module named 'content'` (and the same for the others, raised by
  `load_script`) or, for the docs, the fixture's `docs/known-limits.md is missing`; no other reason. As in
  phase 1 they are errors at setup, not failures, because the module-scoped import is the first thing to fail.
- **T018–T022, green on the first run.** 25, 50, 14 and 13 passed, and the 3 docs tests once the two files
  existed. A first run with no red step in between is why T024 matters: each test below was shown able to
  fail.
- **One deviation: a leak the commit scan would have refused.** `scan.py` first held the Linux home prefix as
  one literal, which the commit's own scan refuses (a home-directory prefix). It is spelled from two pieces now, the way the
  test fixtures spell their planted strings; the scan reports 0 on the file.
- **Two deviations in the known limits.** (1) Five of the seven bullets point at `python/README.md`. The
  "one hop, no loop guard" limit has its detail only in
  `examples/langgraph_agent/README.md` (*What this example does not do*), and the draft limit in
  `standard/v1/README.md` §15, so T016 now checks that every link resolves to a file and a heading in the
  repository, not that it is in `python/README.md`. (2) *Durable state*, *Identity* and *The host guard* are
  bold paragraphs of `## Remote`, not headings, so three bullets link to `#remote`; the bullet names the
  paragraph in its link text. I wrote the MCP Tasks bullet from what `python/README.md` says (a call longer than
  the client's timeout fails on the client's side) after first writing a sentence the README does not support.
- **T023, real bytes** (built outside the repository; `python/` untouched): `sums.py write` gave
  `ext_r2c-0.0.1-py3-none-any.whl` 183493 bytes `d41c0c33…de296` and `ext_r2c-0.0.1.tar.gz` 481219 bytes
  `450cc370…afb7`; `sums.py check` printed `sums ok: 2 files` and `sha256sum -c` printed `OK` for both;
  `content.py` printed `content ok: 0.0.1`; `scan.py` printed `scanned …whl: 74 files`, `scanned …tar.gz: 182
  files` and `scan ok: 256 files, 0 hits`. The sdist is 9 files larger than at T001 (173) because this phase
  and the last added test files, which the sdist carries; their planted strings are spelled from fragments, so
  they do not hit.
- **T024, mutation check** (29 mutants, restored after each): the scan's reserved-domain allowance removed, the
  home-path category emptied, 172.31 left out of the private range, the matched line printed, a binary member
  not skipped, an sdist read as a wheel, the AWS key shape broken, a hit counted once per file; the content
  check's `py.typed` requirement, examples folder, member outside the two folders, missing extra, wrong
  `METADATA` version, missing schema, extra schema, wrong `PKG-INFO` version, binary member, dot-dot path and
  `test_*.py` file, each removed; the sums comparison, the unlisted-file check, the sort, the bare-name rule
  and the one-wheel rule; the notes' empty-limits check, unknown-placeholder check, title drop, title check and
  final-version check. 28 killed by the named test on the first run. One survived, "a missing title line
  passes": the `no-title` case had a single line, which the empty-body check refused anyway. I changed the case
  to two bullets so that only the title check can refuse it, and the mutant is killed. The sums test for a name
  with a path now also asserts the refusal says "bare file name", because it first passed for the wrong reason
  (the file was missing). A test that the notes refuse a final version was written before the run, for the last
  mutant of the list.
- **T025, verify.** 3029 passed on 3.11, 3.12 and 3.13 (2923 before this phase, plus 106); the four single-extra
  scripts ok on all three; `ruff --select F src tests ../scripts` clean after removing one unused import in
  `test_release_docs.py` and merging two `pathlib` imports in `content.py`.

### Phase 3 (2026-11-24)

- **T026, red.** `tests/test_release_workflows.py` ran against the old `python.yml` alone, before `wheel.yml` and
  the new `python.yml` existed: 20 failed, 4 passed and 1 skipped (reproduced again from the committed
  `python.yml` before this commit, same counts). The four that passed are properties the old file already had:
  no write to the environment files, no secret and no wide permission, no dangerous trigger, and the two
  triggers kept. The skip is `release.yml`, which a later phase writes (the test skips by name, it does not
  pass). The 20 failures are the missing top-level `contents: read`, actions pinned by tag, a checkout that
  keeps its credentials, an expression inside `run:`, steps with no name, a runner image that floats, the
  tests that read `wheel.yml` (the file does not exist), and a CI file that still builds, tests and holds the
  matrix itself. None is an error in the test. With `wheel.yml` present the per-file tests run on it too, so
  the file ends at 34 items: 33 pass, 1 skips.
- **T027/T028, the adopter's path by hand.** In a venv built as CI builds it (the wheel with
  `[a2a,mcp,langgraph]` and `uvicorn`, no dev group), `python -I tests/adopter_path.py` printed `adopter path:
  ok` on 3.11 and on 3.13. It can fail in two ways, both shown: in a venv with pytest installed it refuses
  before it starts the example, and in a venv without the `langgraph` extra it stops with the
  `ModuleNotFoundError` for `langchain`, followed by the last lines of the example's output.
- **One deviation: the planned failing case could not fail.** The task said to prove a failure in a venv
  *without* `uvicorn`. `mcp` depends on `uvicorn` (`uvicorn>=0.31.1`), so the extra `[mcp]` always installs it,
  and no venv with the wheel and the three extras lacks it. The explicit `uvicorn` in the install line is kept
  because the example's README says it and it costs nothing, but it is not what makes the path work. The two
  failing cases above replace it, and neither records a local path.
- **T029–T031, green.** `wheel.yml` (three jobs: `build`, `checks` with the matrix, `inspect`), `python.yml`
  (one job that calls it) and the two `.gitignore` lines. `release.yml` is not written.
- **T032, the legs simulated locally.** A script runs the `run:` steps of `wheel.yml` in order, as the runner
  would, with each `uses:` step replaced by a fresh copy of the tree and the one artifact of the build. The
  build ran once; each leg and `inspect` read the same three files. The wheel's SHA-256 was
  `d41c0c33cd8f00acaba000ae6c98b6d14c270c2b25b0bb4318fbe4d4785de296` on the build, on the 3.11 leg, on the 3.12
  leg, on the 3.13 leg and in `inspect`. Each leg printed `sums ok: 2 files`, then 3062 passed and 1 skipped (99 s
  on 3.11, 105 s on 3.12, 98 s on 3.13), the four single-extra scripts, and `adopter path: ok`. `inspect` printed
  `sums ok: 2 files`, `content ok: 0.0.1` and `scan ok: 258 files, 0 hits`. This is a local simulation, not a
  GitHub run: the `uses:` steps, the artifact transfer and the runner image are what T036/T037 prove.
- **T033, lint.** Lint not run (plan point 1, default A). Plan point 1 has no answer from the maintainer yet, so
  the default stands; the hygiene rules are held by T026's tests instead.
- **Mutation check on the workflow tests** (20 mutants, each restored): a checkout that keeps its credentials,
  a setup-uv that keeps its cache, an action pinned by a tag, an action with no version comment, the Python
  version written inside `run:`, the adopter's step dropped, the adopter installing the dev group, the matrix
  failing fast, a Python version removed from the matrix, `inspect` asking for write access, a second
  `uv build` in `checks`, the sums check no longer first, the scan of the sdist dropped, a step with no name, a
  floating runner image, an artifact allowed to be empty, `python.yml` keeping its own steps, losing its
  `pull_request` trigger, naming a secret, and widening its top-level permission. All 20 killed on the first run,
  each by the test that names the property. The harness gained an `nth` key for the checkouts, which appear
  three times.
- **T034/T035, verify.** 3062 passed and 1 skipped on 3.11 (92 s), 3.12 (96 s) and 3.13 (88 s), against the
  installed 0.0.1 wheel (3029 before this phase, plus the 33 workflow tests; the skip is `release.yml`); the
  four single-extra scripts ok on all three; `ruff --select F src tests ../scripts` clean.
- **T036, the push.** The maintainer said "go" (2026-11-24, "push, tiếp tục các phase sau"); `git push` carried eight
  commits, `a31da46..6e2748d`, to `main`. The go covers this push. The push after phase 6 (T062) and the manual
  run (T063) are asked for again; the tag is never part of any of them.
- **T037, the refactor's proof** (run 45351776466 of the pushed commit, all five jobs `success`, no workflow
  warning in any log; the logs were read through the REST API, because `gh run view --log` printed nothing
  with gh 2.45):
  - `wheel / build`: `ext_r2c-0.0.1-py3-none-any.whl  183493 bytes  d41c0c33…de296` and
    `ext_r2c-0.0.1.tar.gz  485567 bytes  4dbbbc1d…8bd9`; the artifact `dist` holds three files, 662357 bytes.
    The wheel's checksum is the one measured locally at T023 and T032, so the build is reproducible across
    machines.
  - `wheel / checks (3.11)`, `(3.12)`, `(3.13)`: each printed `sums ok: 2 files` first, then 3062 passed and
    1 skipped (81 s, 89 s, 55 s), `core only: ok`, `a2a only: ok`, `mcp only: ok`, `langgraph only: ok` and
    `adopter path: ok`. The legs check the downloaded files against `SHA256SUMS`; they do not print the digest
    itself, so "the same checksum" is shown by that check and by the build's own line, not by a line in each
    leg.
  - `wheel / inspect`: `sums ok: 2 files`, `content ok: 0.0.1`, `scan ok: 258 files, 0 hits`.
  - Nothing was red, so no fix commit was needed. The local simulation of T032 predicted these lines, but the
    `uses:` steps (checkout, setup-uv, the artifact upload and download) had never run before this run.

### Phase 4 (2026-11-24)

- **T038, the fake `gh`.** `release_fakes.py` now implements exactly the table of research R3, flags included, and
  answers any other call with exit status 99 (logged as unexpected). A write to a published release (an edit,
  an upload, a deleted asset) answers 98 and is logged as a violation, so a script that tries it fails visibly
  and a test can assert there were none. Switches: fail at call N, return altered bytes on download, lose a file
  on upload, make the publishing call do nothing. The earlier preflight and common tests pass with it.
- **T042, red.** Before any script or workflow existed: `test_release_publish.py` 32 errors, every one
  `ModuleNotFoundError: No module named 'publish'`; `test_release_verify.py` 18 errors, every one `No module
  named 'verify'`; `test_release_workflows.py` 12 failed, 33 passed and 1 skipped, every one of the 12 failing
  with "release.yml is missing" (counted again with the file set aside, 12 of 12). The skip is the old
  `release.yml` skip; it is gone now that the file exists. None of the 62 is an error in a test.
- **T043–T045, green.** `publish.py`: 32 of 32 on the first run. `verify.py`: 18 of 18. `release.yml`: the
  workflow tests 55 of 55 with no skip.
- **What was added to the contract while writing.** `release_common.py` gained `REPOSITORY_RE` (moved from
  `preflight.py` and `notes.py`, which now import it), `version_from_tag` and `check_sums`. `check_sums` *runs*
  `sums.py check` and raises its refusal again under the caller's id (`sums` in `publish.py`, `public-differs`
  in `verify.py`); it does not import it, so `release_common.py` stays the only module the others import and
  `sums.py` stays the one place that reads the list. `verify.py` takes `--base-url`, `--attempts` and `--pause`
  (the workflow passes 6 and 10, so a release that is a moment late is not a failure). Both are in
  [contracts/scripts.md](contracts/scripts.md).
- **Two choices in `release.yml` worth reading.** `notes.py` does not create the folder of its `--out`, so the
  step runs `mkdir -p release-notes` first. The address that `verify` installs is built from `$REPOSITORY`,
  `$TAG` and the *file name of the wheel `verify.py` just downloaded* (`basename public/*.whl`), not from a
  second copy of the naming rule: what is installed is the file that was checked.
- **T046, lint.** `ruff --select F src tests ../scripts` clean. The workflows are not linted for hygiene by a
  tool (plan point 1, default A, no answer from the maintainer); the rules are held by the tests of T041 and
  T026.
- **T047, mutation check.** 36 mutants, each restored: in `release.yml` (a `pip install` step in `publish`, a
  `pull_request` trigger, `cancel-in-progress: true`, a token in `verify`, `contents: write` in `preflight`,
  `publish` without its `if`, `publish` not waiting for `wheel`, a matrix in the `wheel` job, `publish`
  running a file of `dist`, the tag written as an expression inside `run:`, `publish`'s checkout keeping its
  credentials, `preflight` without the whole history, `verify` installing before it reads); in `publish.py`
  (publish before the compare, `gh release delete` on a published release, a published release treated as a
  draft, which is the "replace a published file" case, no `--clobber`, no `--verify-tag`, the sums check
  dropped, the state after publishing not read, strays left, a `gh` failure ignored, the pre-release flag of
  a published release not read, extra files allowed in the folder, the read-back going into the tested folder,
  the sdist not compared, an extra asset allowed); in `verify.py` (an `Authorization` header, the list check
  dropped, no second attempt, a non-http address accepted, zero attempts allowed, the sdist not downloaded, a
  failed download not named); in `release_common.py` (a tag without `v` accepted, the refusal id of the list
  not passed on). 35 were killed on the first run, each by the test that names the property. The 36th, "verify
  installs before it reads", survived because the mutant I wrote only appended `&& true` and did not change
  the order; I replaced it with a real swap of the two steps and it was killed by
  `test_verify_reads_the_public_files_...`. One real gap found while designing the mutants: `0.1.0a1` without
  the `v` is refused as `version-grammar` anyway (cutting the first character leaves `.1.0a1`), so that case
  could not tell a missing `v` check from a present one. `x0.1.0a1` can; it is now a case in both
  `test_release_publish.py` and `test_release_verify.py`.
- **T048, a manual start, read from the YAML.** `workflow_dispatch` on a branch:
  - `preflight` **runs**: `preflight.py --event workflow_dispatch` runs the `event`, version-grammar,
    `changelog-section` and `license-copy` checks, and prints three lines `skipped [tag-matches-version]`,
    `skipped [on-main]` and `skipped [no-published-release]: manual start`; so it makes no `gh` call. Then
    `notes.py`, the notes in the run summary, and the upload of `release-notes`.
  - `wheel` **runs** in full: the build, the three legs of `checks`, `inspect`.
  - `publish` is **skipped** by `if: github.event_name == 'push'`: the job never starts, so the one token that
    can write is never issued. `verify` is skipped by the same `if` (and by its `needs`).
  - Nothing in a manual start can write: only `publish` holds `contents: write` (the tests count exactly one
    use of the string in the file); only `publish.py` calls `gh release` for a write (`preflight.py` calls `gh
    api` to read); the only token in `preflight` is the read-only one.
  - What a manual start cannot show: the three tag-bound checks, `publish.py` and `verify.py` against real
    GitHub (decision D11). Also: on today's `main` the version is `0.0.1`, a final number, so a manual start now
    would be refused by `preflight.py` at the version grammar; it can pass only after the `0.1.0a1` commit of
    phase 5 (T054).
- **T049, verify.** 3136 passed, 0 skipped on 3.11 (122 s), 3.12 (113 s) and 3.13 (105 s), against the installed
  0.0.1 wheel (3062 passed and 1 skipped before this phase: the skip now runs, plus 33 `publish`, 19 `verify`,
  12 workflow tests of section 2 and the 9 per-file rules that now also read `release.yml`); the four
  single-extra scripts ok on all three. A first attempt started two loops at once in the same folders; both
  were stopped and discarded, and these numbers are from one clean run per version. Nothing has run on GitHub
  yet: `release.yml` has not been pushed.

### Phase 5 (2026-11-24)

- **T050, red.** `test_release_docs.py` has 24 tests (3 from section 1, 21 new): 16 failed and 8 passed on the
  0.0.1 wheel. Each of the 16 failed for the reason it names, read line by line: the three READMEs have no
  install line for `v0.0.1` (3); neither the root nor the Python README holds the sentence about the bare PyPI
  name (2) or links `docs/known-limits.md` (2) or stops saying pre-alpha (2); `docs/releasing.md` is missing
  (2); `AGENTS.md` has no row for it (1); `ARCHITECTURE.md` does not name `scripts/release/` (1); the
  classifier is `2 - Pre-Alpha` (1); `CHANGELOG.md` has no section `[0.0.1]` (1, refused `changelog-section`);
  `notes.py` on the real tree is refused `prerelease-only`, because `0.0.1` is a final number (1). The 8 that
  passed are the 3 of section 1, the check that the address the tests build is the one `release_common.address`
  builds, and four guards that hold now because nothing breaks them yet: no README names another release's
  address (3) and no install line names the bare package. They are checked by mutation after `0.1.0a1`.
- **T051, T052.** `docs/releasing.md` has nine `##` headings in the order of research R8; it says the private
  pattern is not in the repository; the tag step comes after the manual run and says "same sitting". `AGENTS.md`
  is 72 lines (the limit is 150). `ARCHITECTURE.md` has a new *Release tooling* section with the three workflows,
  the scripts and the import rule.
- **T053, mutation check of what is green now.** 15 mutants of the runbook, `AGENTS.md` and `ARCHITECTURE.md`,
  each run against the one test that owns it (running the whole file would stop at the first of the red tests
  and kill every mutant for the wrong reason: my first run did exactly that, and I discarded it): three
  headings renamed, two pairs of headings swapped, "same sitting" removed, `--ref main` removed, a `gh release
  create` line added, the tag command placed before the manual run, the sentence about the pattern changed, the
  link to the known limits removed, the two `AGENTS.md` rows removed one at a time, `AGENTS.md` padded past 150
  lines, `release.yml` and `python.yml` unnamed in `ARCHITECTURE.md`. All 15 were killed. One further mutant,
  "`wheel.yml` is not named in `ARCHITECTURE.md`", survived even with its two mentions removed, because the file
  names it in four places; it is equivalent (the claim stays true), not a gap. The commit of T053 holds the
  tests red until T054 on purpose (the plan orders it so); nothing is pushed between.
- **T054, the `0.1.0a1` set.** `python/pyproject.toml` changes two lines (`version = "0.1.0a1"`, the classifier
  `Development Status :: 3 - Alpha`). The root README says alpha and links `docs/known-limits.md`, and has a new
  *Install* part (the Python it needs, the one address line, the sentence about the bare PyPI name). The Python
  README has the same sentences above its extras table, and its wheel-file lines name
  `ext_r2c-0.1.0a1-py3-none-any.whl`. The example README's line 16 is the address line, with a paragraph on
  running it from a checkout of the tag. `CHANGELOG.md` has a fresh empty `## [Unreleased]` above
  `## [0.1.0a1] - 2026-11-24`, with a first bullet under *Added* for the release tooling. Nothing under
  `python/src/` or `standard/`.
- **T055, on the real tree.** The wheel and the sdist were rebuilt after the last edit of a README (the Python
  README is in the wheel's metadata). On that build: `sums.py` writes and checks 2 files; `content.py` ok
  `0.1.0a1`; `scan.py` scans 74 files of the wheel and 186 of the sdist, 0 hits; `preflight.py --event
  workflow_dispatch` prints `preflight ok: version 0.1.0a1`; `notes.py` writes 18436 bytes;
  `git diff --stat 06ff099 -- python/src standard` is **0 lines** (SC-010). I read the notes once, whole. They
  hold the status, the install line, the checksum sentence, the known limits and the changelog section, in that
  order, and an outsider can follow them. That reading found one real defect: the changelog section linked
  `docs/design-docs/one-remote-two-doors.md` by a relative path, which is dead on a release page. Test first
  (`test_the_notes_link_nothing_by_a_relative_path`, red), then the link became an absolute address (green).
- **T056, the reading check (SC-009).** A fresh-context reader was given only the two READMEs and the notes. It
  answered the install command, that the bare name on PyPI is not this project, and the limits to expect, all
  correctly. Its findings: no page said which Python the package needs. Acted on, test first (3 red:
  `test_both_readmes_name_the_python_they_need` for the two READMEs and `test_the_notes_name_the_python_they_need`),
  then one sentence in each README and in `scripts/release/status-block.md`, and 4 mutants of those sentences
  killed. Two further suggestions were **not** acted on: a how-to for checking the checksum in the notes, and
  what a later `0.1.0a2` would use as its address. Both are small and belong to a later release. SC-009 is **for
  the maintainer to confirm**; it is not claimed here, as SC-012 of the earlier specs was not.
- **T057, verify.** 3161 passed, 0 skipped on 3.11 (109 s), 3.12 (113 s) and 3.13 (104 s), against the
  installed `0.1.0a1` wheel (3136 before this phase: 25 new tests in `test_release_docs.py`); the four
  single-extra scripts ok on all three; `ruff check --select F` on `src`, `tests` and `scripts` is clean. The
  build the numbers come from: wheel `81ff75f9…9fb2` (183915 bytes), sdist `34cc6fe6…77ac` (497877 bytes). One
  verify loop at a time, in its own folders. Nothing has run on GitHub for this phase: the three commits of
  phases 4 and 5 are local (`origin/main` is at `6e2748d`), no tag exists, no release exists.

### Phase 6 (2026-11-24)

- **T058, the outside review.** Two reviewers with no memory of the build, run together: a security reviewer
  on the workflows and the scripts that touch the write job (11 findings, all low or info, none critical, no
  path for an outsider to reach the `contents: write` job) and a code reviewer on `git diff 06ff099..HEAD`
  (13 findings, one rated important, no blocker). Their reports are model output: each finding was checked
  against the code before anything changed. The whole account, finding by finding, is
  [research R16](research.md#r16-the-outside-review-of-the-finished-work-and-what-was-done-with-each-finding-phase-6-t058).
  **Fixed, each test first and seen red for the reason it names:** the scan missed an address or a path at the
  end of a sentence or a line and the doubled-backslash Windows form, and its e-mail pattern was quadratic on
  one very long line; a member name with a newline could forge a line of the public log; the sdist check
  ignored links and the wheel check ignored symbolic links; the sdist did not refuse a member that is not
  text; the version, date and repository grammars accepted a trailing newline or a non-ASCII digit; no job had
  a time limit; `publish` read the draft once and then wrote, so a draft published meanwhile would have been
  written to, and two rows for one tag were not handled; `verify` crashed on a cut-off body, took a short body
  for a wrong checksum, mishandled an address without its last slash and accepted a `nan` pause; a `git`
  status other than "not an ancestor" was reported as "not on main"; a missing `LICENSE` was a crash; text
  files were read in the locale's encoding; a name listed twice in `SHA256SUMS` was resolved by "last one
  wins"; the relative-link test knew one link form; the runbook misdescribed what `verify` installs and what
  the scan looks for. `urllib` hands over a body shorter than its `Content-Length` without an error: that was
  found by a probe, not by a reviewer, and fixed the same way. **Answered, not changed:** the gh-subprocess
  time limit, the anchoring of the sums, the unclosed zip handle, the `blob/main` links in the quoted limits,
  and lint. **Open for the maintainer (R16, R15 item 6):** the build toolchain (`uv`, `hatchling`) is not
  pinned, and a tag moved between the tests and `publish` is not caught in code; both have a one-line answer on
  GitHub's side (a tag ruleset for `v*`, an environment on `publish`, immutable releases). The release tests
  went from 315 to 388, the whole suite is 3234 passed on 3.11 (the quick venv, before the T059 loop).
  **Mutation check:** 39 mutants of the fixes (the four guards of `publish` and three of its refusals, five of
  `verify`, eight of the time limits, six of the scan, three of `content`, six of the grammars, `sums`,
  `preflight`, `notes`), each run against the tests of its own file. 37 were killed at once. Two survived: "a
  deleted release passes the guard" was a real gap (the branch had no test: a release deleted between the read
  and the write ended as a `gh` failure, not as `not-a-draft`); the fake `gh` got `delete_meanwhile`, a test
  was written first (red), and the mutant is killed. "A date ending in `$`" is equivalent: the date comes out
  of the changelog line by `\S+`, which cannot hold a newline, so `\Z` there is consistency, not a defence.
  Not proven: `release.yml` has never run on GitHub, and the real `gh` calls and `verify` run for real only at
  the first tag (D11).
- **T059, the whole gate on the final files** (the fix commit `ec3d1cc`). The wheel was rebuilt and is
  **byte for byte the one of phase 5**: `81ff75f9…9fb2`, 183915 bytes (nothing under `python/src/` changed);
  the sdist is new, `04694845…d96d`, 503759 bytes (it carries the tests, and they changed; phase 5's was
  497877). One verify loop at a time, in its own folders, against the installed wheel: **3234 passed, 0 failed**
  on 3.11 (135 s), 3.12 (144 s) and 3.13 (148 s), exit code 0 each; the four single-extra scripts ok on all
  three; `ruff check --select F` on `src`, `tests` and `scripts` is clean. The five scripts on that build, run
  the way the workflow runs them: `sums` writes and checks 2 files; `content` ok `0.1.0a1`; `scan` reads 74
  files of the wheel and 186 of the sdist, **0 hits**; `preflight --event workflow_dispatch` ok (the three
  tag-bound checks said to be skipped); `notes` writes 18436 bytes. **The T032 simulation again** (the `run:`
  steps of `wheel.yml` as GitHub runs them, in fresh copies of the tree): `build` green, the three legs green
  (3234 passed each, 136 s, 147 s and 126 s) with the same wheel checksum `81ff75f9…9fb2` on each and
  `adopter path: ok` at the end of each, and `inspect` green. The leak scan over the whole diff
  `06ff099..HEAD` is **0 hits**, and `git diff 06ff099 -- python/src standard` is **0 lines** (SC-010). The
  first attempt of one command in the chain ran the scripts with `python3 -I`, which drops the script's own
  folder from the import path, so the sibling import failed; the workflow does not use `-I` for them, and the
  rerun without it is the one reported. Nothing of this has run on GitHub: the commits of phases 4 to 6 are
  local (`origin/main` is at `6e2748d`), no tag exists, no release exists.
- **T061, what was built against the plan's scale line.**

  | Plan | Built |
  |---|---|
  | 3 workflow files (2 new, 1 reduced) | 3: `wheel.yml` and `release.yml` new, `python.yml` reduced to one job that calls `wheel.yml` |
  | 9 files in `scripts/release/` (8 scripts and the status block) | 9: `release_common`, `preflight`, `sums`, `content`, `scan`, `notes`, `publish`, `verify` and `status-block.md` |
  | 10 test files and 2 helpers in `python/tests/` | 10 `test_release_*.py` files and 2 helpers (`release_fakes.py`, `release_fixtures.py`); 388 release tests (315 before the review), 3234 in the whole suite |
  | 1 CI script (`adopter_path.py`) | 1 |
  | 2 new documents | 2: `docs/known-limits.md`, `docs/releasing.md` |
  | 8 edited documents | 7 documents (the root README, the Python README, the example README, `AGENTS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, and `WORKSTATE.md` once, for the tasks) plus `python/pyproject.toml` and `.gitignore`; `WORKSTATE.md` is **not yet updated for the close** (see T060) |
  | one release of 3 assets | none made; the three files exist as a build only |

  | Success criterion | Where it stands |
  |---|---|
  | SC-001 a clean venv, one line, the example | the adopter's path is green in CI (phase 3) and in the simulation; the public address works only after a real release, where `verify` is the proof |
  | SC-002 each gate refuses what it names | every script gate is tested, and the mutation checks of phases 1 to 6 killed their mutants; **the wiring on a branch (T064, red on purpose) was not run** |
  | SC-003 the tested bytes are the published bytes | one build, one checksum on every leg (seen on GitHub in phase 3 and in the simulation), compared again against the draft's download (tested against the fake `gh`) and the public download (tested against a local server) |
  | SC-004 the manual run makes nothing public | **waits for T063** (the maintainer's go) |
  | SC-005 the workflow rules as data | the workflow tests are green, with time limits added in phase 6 |
  | SC-006, SC-007 the scan is generic and prints only a file, a category and a count | tested with a planted hit per category and per boundary shape; 0 hits on the real build |
  | SC-008, SC-011 the README addresses are the wheel's | tested against the installed wheel; green |
  | SC-009 the reading check | done in T056; **for the maintainer to confirm** |
  | SC-010 nothing under `python/src/` or `standard/` changes | 0 lines of diff since `06ff099` |

- **T060, the close documents (2026-11-24).** The maintainer asked for the remaining tasks and the push
  ("handle nốt các task còn lại, push code"), which lifts the earlier hold on `WORKSTATE.md`: it now has the
  date, the spec 008 bullet (what was built, what is proven, what is not, the two open findings, the tag as the
  maintainer's own go), the section header and sequence item 8. `ARCHITECTURE.md` and `CHANGELOG.md` needed no
  change after the review (the layout and the `0.1.0a1` section were already right). The dated note in
  `plan.md` is in `2880eab`. The row of the T061 table that says `WORKSTATE.md` was not yet updated is kept as
  written at the time; this note is its answer. The results of the push (T062) and of the manual run (T063) go
  into `WORKSTATE.md` and into these notes once they are seen.
- **T062, the push (2026-11-24).** The maintainer's go was "handle nốt các task còn lại, push code". Before it:
  0 local tags, 0 remote tags, 0 releases. `git push` sent seven commits, `6e2748d..0f12b21` (the six of phases
  4 to 6 and the close documents of T060). The run of `0f12b21` (`python`, run 45397555463) is green on all five
  jobs: `wheel / build`, `wheel / checks` on 3.11, 3.12 and 3.13, and `wheel / inspect`. This is the first time
  `release.yml`, `publish.py`, `verify.py` and the fake-`gh` tests of phases 4 to 6 are on GitHub.
- **T063, the manual run (2026-11-24).** Counts before: 0 remote tags, 0 releases. `gh workflow run release.yml
  --ref main` started run 45398065112 (event `workflow_dispatch`, commit `0f12b21`). Result: `preflight` success,
  `wheel / build`, `wheel / checks` (3.11, 3.12, 3.13) and `wheel / inspect` success, `publish` **skipped**,
  `verify` **skipped**; the run is green. What the log shows:
  - `preflight`: `skipped [tag-matches-version]: manual start`, `skipped [on-main]: manual start`, `skipped
    [no-published-release]: manual start`, then `preflight ok: version 0.1.0a1` and `notes ok: 18436 bytes`
    (the same 18436 bytes as the local build);
  - `wheel / build`: `Successfully built` the sdist and the wheel; the wheel is `ext_r2c-0.1.0a1-py3-none-any.whl`,
    183915 bytes, SHA-256 `81ff75f99471818bdbb90dbedf5c549a0d06afb75ffb61f664058621797a9fb2`, the same as in the
    simulation of T059 and in the local build; the sdist is 503759 bytes, SHA-256
    `04694845f5016dfd136dd1ecf048c3050c2d44bf06639506c5586ca1f532d96d`, also the same;
  - two artifacts were uploaded, `dist` (the wheel, the sdist and `SHA256SUMS`) and `release-notes`;
  - counts after: 0 remote tags, 0 releases. Nothing was made public (SC-004 holds for this run).

  Two things this run does **not** show. The text of the build job's run summary (the lines `sums.py write
  --summary` writes to `GITHUB_STEP_SUMMARY`) cannot be read through `gh` or the REST API; the step that writes
  it is green and printed the same wheel and sdist lines into its log, and the summary code is tested, but nobody
  has looked at the rendered page. And the seven publishing calls and `verify` did not run (`publish` and `verify`
  are skipped by design): they run for real only at the first tag (D11). One finding about the tooling: `gh`
  2.45 shows the log of the `preflight` job only with `gh run view --log`; the logs of the jobs inside the
  reusable workflow come through `gh api repos/OWNER/REPO/actions/jobs/ID/logs`. The runbook's step for reading a
  failed run should say so.
- **T064 was not run.** It is optional and needs its own go. The wiring of each gate on a branch (a red
  `0.1.0`, a renamed changelog section, a planted private-looking line, a failing test) is therefore proven only
  by the tests of the scripts and of the workflow files, not by a red run on GitHub (SC-002).
- **T065, the report.** Given in Vietnamese as the closing message of the session of 2026-11-24. Nothing was
  tagged, nothing was released.
- **The first tag (2026-11-24, later in the same session, after T065).** The maintainer answered the report
  with "2 việc đó bạn làm luôn", read as the two steps the report named for them: the private-token scan
  (runbook step 3) and the tag. This is a separate go from the push and the manual run, and it is the
  maintainer's, given in their own words. What was done, in the runbook's order:
  - **Step 3.** The wheel and the sdist were rebuilt from `9ec15b4`, unpacked (260 files) and searched with the
    maintainer's own pattern, kept outside the repository: 0 matching lines. A control line with a private-looking
    path in a scratch file did match, so the pattern was working. The rebuilt files have the same SHA-256 as the
    ones CI built (wheel `81ff75f9…9fb2`, sdist `04694845…d96d`).
  - **Steps 4 and 5.** `main` equal to `origin/main` at `9ec15b4`; the run of that commit was green; a second
    manual run (45400364380, on `9ec15b4`) was green with `publish` and `verify` skipped and 0 tags, 0 releases.
  - **Step 6.** `git tag -a v0.1.0a1 -m "0.1.0a1"` on `9ec15b4` and `git push origin v0.1.0a1`.
  - **Step 7.** The tag run (45400874510) was green on all eight jobs. In the log of `publish`: `published
    v0.1.0a1: 3 files, pre-release`; in the log of `verify`: `verify ok: 0.1.0a1`, then the install of the public
    wheel address and `installed 0.1.0a1`. `gh release view v0.1.0a1`: not a draft, a pre-release, three assets
    (wheel 183915 bytes, sdist 503759 bytes, `SHA256SUMS` 188 bytes), the notes have `Status`, `Known limits` and
    `Changes in 0.1.0a1`. Downloaded with no token, the three files pass `sha256sum -c SHA256SUMS` and are
    byte-identical to the local build. The README's install line, run in a clean Python 3.12 venv with no
    `--pre`, installed `ext-r2c 0.1.0a1` and imported `ext_r2c`, `ext_r2c.a2a`, `ext_r2c.mcp`,
    `ext_r2c.bridges.langgraph` and `Remote`.
  - **What this closes.** The seven publishing calls and `verify` have now run against GitHub for real (D11),
    and SC-001, SC-003 and SC-004 hold on the real thing: a clean venv installs the example's dependencies from
    one line; the tested bytes are the published bytes; the earlier manual runs made nothing public. **Still
    open:** SC-002 on a red branch (T064), SC-009 (the maintainer's reading), the lint, and the two findings of
    R16 (an unpinned toolchain, a tag moved after the tests), which are GitHub settings. The next release is
    `0.1.0a2`; `0.1.0a1` is used up and never changed.
