# Implementation Plan: The first pre-release, a tested wheel on a GitHub release (`0.1.0a1`)

**Branch**: `main` (folder `specs/008-release`) | **Date**: 2026-11-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-release/spec.md`. The maintainer asked for the plan and
the tasks on 2026-11-24 ("duyệt, sinh plan và task"); this plan reads that as approval of the spec with
decisions D1–D11 as written, **D3** (no PyPI, install by full address), **D5** (the private-token scan stays
on the maintainer's machine, the CI scan is generic) and **D11** (the publishing steps are not rehearsed)
included. No workflow file, no script and no tag is written in this step.

## Summary

A release is one pushed tag. Two workflows share one definition of the checks, and a small set of plain
Python scripts decides what may be public.

- **One definition** (R1): a reusable workflow `wheel.yml` builds the wheel and the sdist **once**, records
  their SHA-256, and fans the one wheel out to a matrix of 3.11, 3.12 and 3.13 that runs what CI runs today
  plus the adopter's path (the example from the tagged source, no dev group). A content check and a scan
  read the same bytes. CI (`python.yml`) and the release (`release.yml`) both call it, so they cannot drift.
- **One tag** (R2): `release.yml` runs pre-flight (the tag equals the version, a pre-release, a changelog
  section, on `main`, no published release, the licence copy), assembles the notes, calls `wheel.yml`, and
  only then lets one job with write permission publish; a last read-only job installs from the public address.
- **Draft, compare, publish** (R3): `publish.py` creates a draft pre-release, uploads three files,
  downloads them back, compares each SHA-256 with the one recorded before the tests, and only then makes it
  public. A rerun after a partial failure has a defined result for each state; a published file is never
  replaced.
- **Scripts you can test on a laptop** (R4, R10–R12): `scripts/release/` holds the gates and the notes,
  standard library only, tested by `python/tests/test_release_*.py` with fixtures and a fake `gh`.
- **The adopter reads the repository's words** (R8, R11): `docs/known-limits.md` is quoted whole in the
  notes and linked from both READMEs; the install line is a full address everywhere; a test keeps the
  address equal to the wheel of the installed version.
- **Nothing in the SDK or the standard changes** (R9, R14).

Research settled the nine open items against the real repository and `gh` 2.45 / 2.104.0
([research.md](research.md)); one thing could not be run, a lint of the workflows, because the permission
classifier refused it ([R6](research.md#r6-pinning-the-actions-and-the-hygiene-a-workflow-that-holds-write-access-needs-fr-014)).

## Technical Context

**Language/Version**: Python ≥ 3.11 for the scripts and tests (CI 3.11, 3.12, 3.13; the runner's `python3`
is 3.12.3). Workflow YAML for GitHub Actions on `ubuntu-24.04`.

**Primary Dependencies**:
- scripts: **standard library only** (`tomllib`, `zipfile`, `tarfile`, `hashlib`, `re`, `subprocess`,
  `urllib`, `argparse`, `json`); the runner's `gh` for the publishing calls;
- tests: pytest and PyYAML, both already in the dev group; no new dependency and no new extra (principle VIII);
- workflows: four actions pinned by commit ([R6](research.md#r6-pinning-the-actions-and-the-hygiene-a-workflow-that-holds-write-access-needs-fr-014));
- the wheel's own dependencies are unchanged.

**Storage**: None. Artifacts between jobs (`dist`, `release-notes`, 14-day retention) and the draft release
are the only state, and a manual run keeps nothing.

**Testing**:
- pytest on the installed wheel: fixtures for every refusal, a fake `gh` for the publishing order and its
  reruns, the workflow files read as data, the documents read as data;
- the real bytes are checked by the `inspect` and `checks` jobs of `wheel.yml` on every push, and by the
  manual run after the first push;
- the publishing calls on the real GitHub run once, at the first release (D11).

**Target Platform**: GitHub Actions (public repository, default token read-only); the adopter's pip or uv on
any platform.

**Project Type**: repository tooling (workflows, scripts, documents) around a library; no new package.

**Performance Goals**: a leg stays near today's 77 s; the added jobs (`build`, `inspect`, adopter's path)
add under 2 minutes to a release run. No target for CI beyond not growing by more than one build.

**Constraints**:
- exactly one job with write permission, running no code from the built files (FR-014, SC-005);
- no `${{ }}` inside any `run:`; every action pinned by SHA; no `pull_request` trigger on the release;
- nothing public until every gate and the byte comparison pass (FR-011); a published file is never
  replaced (FR-012);
- a public repository (VI): no private word anywhere, scan output prints a file and a count only;
- nothing under `python/src/` or `standard/` changes (SC-010).

**Scale/Scope**: 3 workflow files (2 new, 1 reduced), 9 files in `scripts/release/` (8 scripts and the
status block), 10 test files and 2 helpers in `python/tests/`, 1 CI script (`adopter_path.py`), 2 new
documents, 8 edited documents; one release of 3 assets.

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | No shape is made or changed. The content check reads the schema names from `standard/v1/schema/` to prove the wheel carries them; `standard/` is untouched | pass (n/a) |
| II. Wire examples are the shared test suite | No R2C rule is added, no example is added; the replays run unchanged on every leg | pass (n/a) |
| III. Remote's logic unchanged | Nothing under `python/src/` changes; the adopter's path proves the example still runs from the wheel with its own code | pass (n/a) |
| IV. An extension, never a protocol | Not touched | pass (n/a) |
| V. Approval never answered by a model | Not touched; the adopter's-path check asserts the example's own outcome, which includes the refused approval | pass (n/a) |
| VI. Public, neutral data only | The scan is generic; scripts, tests and documents hold no private word; fixtures use invented data and `example.com` and spell home-directory prefixes from fragments; the scan prints a file and a count only; the private pattern stays on the maintainer's machine (D5); leak scan before each commit | pass |
| VII. Test first, against the built artifact | Each script starts with failing fixture tests, run in the installed-wheel venv; the real built bytes are checked by CI on every push; the one build is the one tested ([R4](research.md#r4-where-the-scripts-live-and-how-their-tests-run-fr-004-fr-005-fr-009-fr-016)) | pass, one point to note |
| VIII. Small core, bindings behind extras | No new dependency, no new extra, no import into or out of `ext_r2c`; `scripts/` imports nothing from the package and the package nothing from it | pass |
| IX. Versioned by URI | `standard/v1` untouched and still a draft; the package version (`0.1.0a1`) is separate and the notes say so | pass |

*The point to note (VII).* The scripts are not in the wheel, so "tests run against the installed wheel" is
read as: the tests run in the installed-wheel venv with the rest of the suite and import the scripts by
path from the checkout, exactly as the example's test does; and what the scripts act on, the built files,
is checked by CI on the real bytes. This is stated in R4 and is not an exception.

**Re-check after the Phase 1 design:** still a pass. Two additions are worth a line. First, the shared
workflow runs the content check and the scan on every push, not only in a release (point 2 below), so
principle VI is enforced earlier, not later. Second, the rule "one job with write permission that runs no
built code" is a test of the workflow file (SC-005), so principle VI's cost of a mistake stays a red test
and not a public release. Complexity Tracking has three small entries.

## Project Structure

### Documentation (this feature)

```text
specs/008-release/
├── spec.md
├── plan.md                      # this file
├── research.md                  # R1–R15
├── data-model.md                # release, asset, gate, run, known limits; states; the gate table
├── quickstart.md                # validation guide
├── contracts/
│   ├── scripts.md               # each script: arguments, environment, output, exit codes, refusal ids
│   ├── workflows.md             # wheel.yml, python.yml, release.yml: jobs, needs, permissions, artifacts
│   └── release-assets.md        # asset names, SHA256SUMS, the notes layout, the install line
├── checklists/requirements.md
└── tasks.md                     # from /speckit-tasks
```

### Source code (repository root)

```text
.github/workflows/
├── wheel.yml                  # NEW reusable: build once, checks matrix (incl. adopter's path), inspect
├── python.yml                 # CHANGED: triggers as today; one job that calls wheel.yml
└── release.yml                # NEW: preflight, wheel, publish (write), verify

scripts/release/               # NEW, outside the wheel, standard library only
├── release_common.py          # Refusal, grammar, readers, address, exit-code wrapper
├── preflight.py  content.py  scan.py  sums.py  notes.py  publish.py  verify.py
└── status-block.md            # the status part of the notes, with {{placeholders}}

python/tests/                  # NEW
├── release_fixtures.py        # tiny wheel/sdist/changelog builders (helper, not collected)
├── release_fakes.py           # the fake `gh` (helper, not collected)
├── adopter_path.py            # the adopter's path; run by CI as `python -I tests/adopter_path.py`
└── test_release_common.py  test_release_preflight.py  test_release_content.py  test_release_scan.py
    test_release_sums.py  test_release_notes.py  test_release_publish.py  test_release_verify.py
    test_release_workflows.py  test_release_docs.py

docs/
├── known-limits.md            # NEW: the short list, quoted whole in the notes
└── releasing.md               # NEW: the maintainer's runbook

README.md, python/README.md, examples/langgraph_agent/README.md   # CHANGED: the install line, status
AGENTS.md, ARCHITECTURE.md, CHANGELOG.md, WORKSTATE.md             # CHANGED: rows, layout, the section
python/pyproject.toml                                              # CHANGED once: 0.1.0a1, Alpha
.gitignore                                                         # CHANGED: .adopter-venv/, .release-dist/
```

**Structure Decision.** Tooling at the repository root in `scripts/release/` (it reads the repository, so it
cannot live in the wheel or the sdist), tests beside the others in `python/tests/` (so CI runs them with no
new step), documents in `docs/`, workflows in `.github/workflows/`. Nothing is added under
`python/src/ext_r2c/` or `standard/`.

## Key design decisions

Each is argued in `research.md`; this is the index.

| # | Decision | Where |
|---|---|---|
| 1 | One reusable `wheel.yml`: build once, a matrix on the one wheel, `inspect` on the same bytes; CI and the release both call it | R1 |
| 2 | Four jobs in the release; only `publish` has `contents: write` and runs no built code; `verify` is read-only and uses no token | R2 |
| 3 | `publish.py` is the only writer: draft, upload, download back, compare, publish; a table of reruns; a published file is never touched | R3 |
| 4 | Scripts in `scripts/release/`, standard library only, exit codes 0/1/2, tested by path with fixtures and a fake `gh` | R4 |
| 5 | The adopter's path is a step of the shared matrix, from the tagged source, no dev group | R5 |
| 6 | Every action by full SHA; no `${{ }}` in `run:`; `persist-credentials: false`; no secrets; the workflow tests enforce it | R6 |
| 7 | The manual start is the same workflow with `publish` and `verify` skipped; it uses the version in `pyproject.toml` at the ref | R7 |
| 8 | `docs/known-limits.md` and `docs/releasing.md`; one address line in three READMEs; a test ties it to the wheel's version | R8 |
| 9 | The `0.1.0a1` commit: version, classifier, README, changelog; nothing in `python/src/` or `standard/` | R9 |
| 10 | The scan: four categories, the reserved example domains pass, a hit is a file, a category and a count | R10 |
| 11 | Notes: status block, known limits whole, the changelog section; empty is a refusal | R11 |
| 12 | `SHA256SUMS` in `sha256sum`'s format, written before any test, compared at every later step | R12 |

## Changes outside the new files

- **`python.yml`**: the single job becomes a call of `wheel.yml`; the steps move; the triggers do not. The
  `${{ matrix.python }}` in `run:` becomes an `env:` value. Job names change to `wheel / checks (3.11)`.
- **`python/pyproject.toml`**: once, at the end: `0.1.0a1` and the Alpha classifier (R9). No other line.
- **`.gitignore`**: `.adopter-venv/` (the name the CI step uses, for a local run) and `.release-dist/`
  (the folder the quickstart builds into).
- **`ARCHITECTURE.md`**: `scripts/release/` in the layout, and the rule that it imports nothing from
  `ext_r2c`.
- **`standard/`, `python/src/`**: nothing (SC-010). The task that proves it is a `git diff --stat` on both
  paths.

## Delivery order (input to `/speckit-tasks`; one phase per go)

| Phase | Content | Done when |
|---|---|---|
| 1. Scripts' core and pre-flight (US3, P1) | `release_common.py`, `preflight.py`, `release_fixtures.py`; tests first: version and tag grammar, the changelog reader, every refusal of FR-004, the manual mode, the event guard | the pre-flight tests pass on the wheel venv; each refusal names its check and what to change |
| 2. Content, scan, sums, notes (US3, US5) | `content.py`, `scan.py`, `sums.py`, `notes.py`, `docs/known-limits.md`, `status-block.md`; tests first, with planted hits built from fragments | SC-006, SC-007, SC-008; the scan finds 0 on a real build of both files |
| 3. The shared definition (US1, US2; SC-010) | `wheel.yml`, `adopter_path.py`, the reduced `python.yml`, the CI part of `test_release_workflows.py`, `.gitignore`; the lint if the maintainer allows it | tests pass; **then a push (a go of its own) and a green CI on GitHub**; the run is the proof of the refactor |
| 4. The release job (US2, US4) | `publish.py`, `verify.py`, `release_fakes.py`, `release.yml`; tests first: the fake `gh` rows of R3, the workflow rules of SC-005 | SC-002 (script gates), SC-003, SC-005; the fake never sees a call outside the table |
| 5. The adopter's page and the cut (US1, US5) | `docs/releasing.md`, the READMEs, the example README, `AGENTS.md`, `ARCHITECTURE.md`, `test_release_docs.py` first; then the `0.1.0a1` commit and `CHANGELOG.md` | SC-009 (read once), SC-011; the README test passes on the installed `0.1.0a1` wheel; `git diff --stat python/src standard` is empty |
| 6. Review, the first manual run, the report | an outside review by a code reviewer and a security reviewer of the workflows and `publish.py`; 3.11 / 3.12 / 3.13; leak scan; **on the maintainer's go: push, then `gh workflow run release.yml`**; report | the manual run is green and the lists of tags and releases are unchanged (SC-004); the tag is **not** pushed |

**Order.**
- Phase 1 before 2 (the scripts share `release_common.py`); phase 2 before 3 (`inspect` calls `content.py`
  and `scan.py`).
- Phase 3 ends with a push so the CI refactor is proven alone, on GitHub, before `release.yml` exists. A red
  CI there is then the refactor's, and nothing about a release is in question.
- Phase 4 needs phase 3 (`release.yml` calls `wheel.yml`).
- Phase 5 holds the version commit last, so the README test, the notes and the manual run all see
  `0.1.0a1`.
- Phase 6 ends **before** the tag. Pushing the first tag is the maintainer's own act and a separate go
  (spec Assumptions).

## Needs the maintainer

Five points the approved spec did not settle. Each has a default the plan follows; none blocks the work and
any can be reversed before its phase.

1. **Run a static lint of the workflows.**
   - *Example:* `uvx --from zizmor==1.32.0 zizmor --offline .github/workflows/` reads the workflow files
     and reports unpinned actions, template injection and excess permissions. In this session the
     permission classifier refused to run it, so nothing has been linted.
   - *A (default):* skip the lint; the tests that read the YAML (SC-005) are the guard and the first manual
     run is the proof. *Cost:* a class of finding the tests do not look for stays unseen.
   - *B:* allow `zizmor` 1.32.0 (22 days old, offline, no token, throwaway environment, never a dependency
     or a CI step) and `actionlint`'s release binary, for phases 3 and 4. *Cost:* a tool run from the
     network on your machine.
   - *Recommendation:* B, offline only. Say which, and phase 3 follows it.
2. **The content check and the scan also run on every CI push** (the spec words them for the release job).
   - *Example:* a stray home-directory path in a new test shows as red on the push, not after you tag.
   - *A (default):* yes, in the shared `inspect` job. *Cost:* a false positive turns a push red; the scan
     already lets the reserved example domains through and finds 0 on today's files.
   - *B:* the release only. *Cost:* the first sign of a hit is a refused tag.
   - *Recommendation:* A.
3. **CI moves from `checkout@v4` and `setup-uv@v6` to the pinned SHAs of the current majors** (v7.0.1 and
   v10.3.3), and its job names change to `wheel / checks (3.11)`.
   - *A (default):* move, because a pinned release workflow beside an unpinned CI is a half measure and the
     file is rewritten anyway; phase 3's push proves it alone. *Cost:* two major-version steps of the
     actions in one change; the release notes of both were read for breaking changes (R6), and no ruleset
     names the old checks.
   - *B:* pin the newest versions of the *current* majors (v4, v6) and move later. *Cost:* the pins are
     bumped twice.
   - *Recommendation:* A.
4. **The order of the first pushes.** Phase 3 asks for a push of its own (to see CI green on the new
   shape); phase 6 asks for the push of everything else and then the manual run, because GitHub starts a
   manual run only for a workflow that is on `main`. Today three commits are still unpushed (`c9e7a7c`,
   `b307085`, `0a139b6`) and ride along with the first push.
   - *Recommendation:* push after phase 3, and again in phase 6. Say if you would rather push once, at the
     end; the cost is that the CI refactor and the release job are first seen together.
5. **The README names a release that does not exist until the tag is pushed.** The window is the time
   between pushing the version commit and the tag.
   - *Recommendation:* in phase 6, after the manual run is green, say "go tag" in the same sitting; the
     runbook says so. The alternative, committing the README edit only after the tag, would make the
     README test fail on the commit that bumps the version.

## Risks

| Risk | Mitigation |
|---|---|
| The publishing calls run on real GitHub only once, at the first release (D11) | the fake `gh` pins the order and the reruns; the flags are in both `gh` versions; a failure leaves a draft and nothing public; the runbook reads the release page right after |
| The restructured CI cannot be run before a push | phase 3 ends with a push of its own; the workflow tests read the YAML; lint if allowed (point 1) |
| A manual run needs `release.yml` on `main` | phase 6 pushes first; the runbook says it; the workflow tests and lint are the cover until then |
| A new `uvicorn` release breaks the adopter's-path step | the red is the adopter's experience; named in R5; the rerun and the pin are the maintainer's call |
| A scan false positive blocks a push | the reserved example domains pass; 0 hits today on both files; the scan reports file and category so the fix is findable without echoing text |
| A scan false negative leaks | the generic scan is a floor; the private pattern is the maintainer's promise (D5); the runbook asks for it before the tag |
| The write job is changed to run the wheel | SC-005's test reads the workflow and fails on any `uv`, `pip`, `python -m`, or import step in that job |
| A published release holds a mistake | the next number (`a2`); withdrawing is by hand, only for leaked data (runbook) |
| GitHub changes a `gh` flag | the runner image is pinned to `ubuntu-24.04`; the fake refuses unknown calls so a change is a visible test edit |
| Artifacts of a failed run are public | they hold what the repository already holds; retention is 14 days; the scan runs on the same bytes |
| The name `ext-r2c` is registered on PyPI by someone else | every install line is an address (FR-018); a test refuses a bare-name install line in the READMEs |

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| The licence copy is checked twice: `cmp` in `wheel.yml` (every push) and `filecmp` in pre-flight (FR-004) | CI checks it today; the release's refusal list must name it and must run before the build | dropping the CI line removes a check CI has; running pre-flight in CI would demand a changelog section on every push |
| CI job names change (`wheel (3.11)` to `wheel / checks (3.11)`) | a reusable workflow's jobs are named `caller / called` | keeping the old names needs the legs to stay in `python.yml`, which is the copy D6 rejects |
| The content check and the scan run in CI as well as the release | an earlier signal (point 2) | release only: the first notice of a hit is a refused tag |

## Notes

- Facts were checked on 2026-11-24 with throwaway scripts and `gh` against the real repository and a
  fresh build in a scratch directory; research R13 lists them with dates. A prototype of the scan was run on
  the `0.0.1` build; it is not committed, and phase 2 writes the real one test first.
- The spec's open-for-plan list is settled as follows: the seam is R1; the job graph and permissions R2; the
  draft flow and the reruns R3; the scripts and how their tests run R4; the adopter's path R5; the pins and
  hygiene R6; the manual start R7; the documents, the README lines and their test R8; the `0.1.0a1` commit
  R9.
- The first tag is not pushed by this spec's work, and no release is created. A tag, a release and a push
  are each the maintainer's own go.

*Note, 2026-11-24 (phase 6): the body above is kept as planned. Where the build differs, and why:* (1) the
known-limits links resolve to a file and a heading in the repository, not only to `python/README.md`, because
some limits have their detail in the example's README, in the standard or in a paragraph of `## Remote` (tasks,
phase 2), and the scan holds its home-directory prefix as two pieces, because the commit's own scan refuses the
whole (phase 2); (2) the adopter's path is shown failing in a venv with pytest installed and in a venv without
the `langgraph` extra, not in a venv without `uvicorn`, because `mcp` always installs it (tasks, phase 3); (3) the
outside review of phase 6 changed the publishing script, which now reads the release's state right before every
write to a release that exists (`not-a-draft`, `release-ambiguous`; R3's note), added a time limit to every job
that runs steps (a job that calls a workflow cannot have one), made `verify` retry a cut-off or short body, and
made the scan boundary-aware and bounded; none of it changes the job graph, the permissions or the call table.
Two findings are open for the maintainer and are not code: the build toolchain is not pinned, and a tag moved
between the tests and `publish` is not caught (research R16, R15 item 6). The full account is in `research.md`
R16 and in the notes of `tasks.md`.
