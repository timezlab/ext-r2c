# Research: the first pre-release (`0.1.0a1`)

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Checked**: 2026-11-24

Everything below was read from the installed tooling and the real repository, not from memory. Facts are
dated in [R13](#r13-what-was-measured-and-when). Where a fact could not be run before the first release,
the entry says so and names what covers it (spec D11). The entries answer the nine items the plan was
asked to settle; the order follows the spec's items, then the pieces they need.

## R1. The seam: one reusable workflow, called by CI and by the release (D6, FR-006, FR-007)

**Decision.** A reusable workflow `.github/workflows/wheel.yml` (`on: workflow_call`, no inputs) holds the
whole definition of the checks. It has three jobs:

1. `build`: check out, `cmp` the LICENSE copies, `uv build`, record `SHA256SUMS`, upload one artifact
   `dist` (wheel, sdist, `SHA256SUMS`).
2. `checks` (matrix 3.11, 3.12, 3.13, defined only here): download `dist`, check the sums, install **that
   wheel** into clean venvs and run what CI runs today (the suite with the dev group, then the four
   single-extra checks), then the adopter's path (R5).
3. `inspect`: download `dist`, run the content check and the scan (R10) on the same bytes.

`python.yml` (CI) shrinks to one job that calls it; `release.yml` calls it after pre-flight. A fifth
single-extra check is one more step in `wheel.yml` and reaches both with no other edit.

**Why this seam.**
- A *job* is the unit that can pass an artifact to a matrix. The release needs "build once, test those
  bytes" (FR-006); only a shared set of jobs gives that.
- The called workflow runs inside the caller's run, so the artifact it uploads is visible to the caller's
  later jobs (`publish` downloads `dist` from the same run), and the called workflow's `permissions` can
  only narrow the caller's.
- GitHub shows the legs as `wheel / checks (3.11)`; the old names `wheel (3.11)` go away. No ruleset or
  required check exists in the repository (R13), so nothing depends on the old names.

**Alternatives.**
- *A composite action* shares steps, not jobs: it cannot hold a matrix or hand one build to three legs, so
  each leg would build again (the thing FR-006 forbids).
- *A shared script* (`ci.sh`) called by both: hides the steps from the Actions page (one long step), and
  the per-Python venvs still need `uv` set up around it.
- *Copy the steps into `release.yml`* (D6 rejects it): the copies drift, and the file that holds write
  permission is the worse place to find out.

**What changes in the checks themselves.** Nothing in what they prove: the legs run the same suite and the
same four single-extra scripts, now on a downloaded wheel instead of a freshly built one. The `${{
matrix.python }}` that sat inside `run:` moves to an `env:` entry (R6). `python.yml` keeps its triggers
(`push` to `main`, `pull_request`); a tag push does not start it (the `branches` filter), so a release
starts only `release.yml`.

**Content check and scan also run in CI.** The spec words FR-009 for the release job. The plan puts
`inspect` in `wheel.yml`, so a hit shows on the push that causes it and not at tag time. Cost: a push may go
red on a scan hit, which is the point. Said at [Needs the maintainer](plan.md#needs-the-maintainer), point 2.

## R2. The job graph and the permission of each job (FR-010, FR-013, FR-014)

`release.yml`, triggers `push: tags: ["v*"]` and `workflow_dispatch` (no inputs); never `pull_request`,
`pull_request_target` or `workflow_run`. Workflow-level `permissions: contents: read`.

| Job | Needs | Runs when | `permissions` | What it does |
|---|---|---|---|---|
| `preflight` | none | always | `contents: read` | Check out the full history without credentials; `preflight.py` (R4); `notes.py` assembles the notes (US5) and fails on an empty changelog section; uploads artifact `release-notes`. |
| `wheel` | `preflight` | always | `contents: read` | `uses: ./.github/workflows/wheel.yml`: build once, test every leg on the one wheel, content check, scan. |
| `publish` | `preflight`, `wheel` | a pushed tag only | **`contents: write`** | Check out the scripts without credentials; download `dist` and `release-notes`; `publish.py` (R3): draft, upload, download back, compare, publish. |
| `verify` | `publish` | after `publish` succeeded | `contents: read` | Download the wheel and the sums from their **public** addresses with no token; compare; install the line the README gives into a clean venv; check `__version__`. |

- **One writer.** Only `publish` holds write permission (FR-014). It checks out the repository's own
  scripts and runs `python3 scripts/release/publish.py`; it never installs, imports or runs the wheel or the
  sdist, and it holds no `uv`/`pip` step. A test reads the workflow and fails if that changes (SC-005).
- **A failed gate publishes nothing.** `publish` is skipped when `preflight` or `wheel` fails (the default
  `success()`), and `wheel` fails when any leg, the content check or the scan fails.
- **`verify` is last and read-only** (FR-013). It sets no `GH_TOKEN`; its download requests carry no
  `Authorization` header. If it fails, the run is red and says so; nothing deletes the release.
- **Manual start.** `workflow_dispatch` runs `preflight` (with its tag-free checks only), `wheel` and the
  notes; `publish` and `verify` are skipped by `if: github.event_name == 'push'`, so a manual run is the
  same workflow with the writing jobs skipped, not a copy (FR-019).
- **Concurrency.** `concurrency: group: release-${{ github.ref }}`, `cancel-in-progress: false`: two
  pushes of one tag queue, and a publishing run is never cancelled halfway.
- **Runner.** `ubuntu-24.04` named explicitly (it is what `ubuntu-latest` means today; the runner has
  `gh` 2.104.0, Python 3.12.3 and Git 2.56.1, R13), so a later image change cannot alter the release job
  unnoticed.

**Why `verify` has `contents: read` and not `{}`.** `setup-uv` calls the GitHub API to resolve a version; a
job with no permissions at all might fail there, and the first place to find out would be after a real
publish. `contents: read` is the same permission every other job has, and the requirement of FR-013 (no
credentials for the *download*) is met by the step, which never sets a token.

## R3. Draft, upload, download back, compare, publish, and a rerun (FR-010, FR-011, FR-012, D7)

**Decision.** `scripts/release/publish.py` is the only code that writes a release. It runs `gh` (the
runner's, with the job's own `GH_TOKEN` and `--repo`), and runs these calls, no others (the test's fake
`gh` refuses any other, so a new call must be added to the test first):

| Step | Call | Notes |
|---|---|---|
| state | `gh release list --limit 200 --json tagName,isDraft,isPrerelease` | read the row for the tag: none, draft or published |
| create (none) | `gh release create TAG --draft --prerelease --latest=false --verify-tag --title TAG --notes-file NOTES` | `--verify-tag`: the tag must already exist on the remote |
| refresh (draft) | `gh release edit TAG --notes-file NOTES --prerelease --latest=false` | a leftover draft gets this run's notes |
| stray assets | `gh release view TAG --json assets`, then `gh release delete-asset TAG NAME --yes` | only on a draft; names outside the three expected |
| upload | `gh release upload TAG FILE... --clobber` | replaces a leftover draft's files |
| read back | `gh release download TAG --pattern "*" --dir DIR` | every asset, from the draft |
| publish | `gh release edit TAG --draft=false --prerelease --latest=false` | last call, only after the compare |

**Order.** (1) read the state; (2) published → go to *already published* below; (3) create or refresh the
draft; (4) remove stray assets; (5) upload the three files; (6) download them back into a clean directory;
(7) require exactly the three names and, for each, the SHA-256 recorded in `SHA256SUMS` (the sums recorded
before the tests); (8) only then `edit --draft=false`; (9) read the state again and require published,
pre-release, not draft. Any difference stops at (7) with the draft left in place and nothing public.

**Rerun after a partial failure.**

| What exists when the job starts | What `publish.py` does |
|---|---|
| nothing | creates the draft and goes on |
| a draft, no or some assets (an earlier run died) | refreshes the notes, removes strays, uploads with `--clobber`, compares, publishes |
| a draft with all three assets already equal | same path: upload again, compare, publish (idempotent) |
| a **published** release, assets equal to the recorded sums | prints "already published with the tested bytes" and succeeds; writes nothing. This covers a publish that succeeded on GitHub while the job lost the answer |
| a **published** release, an asset differs or is missing | refuses (`published-differs`) and writes nothing: FR-012, a published file is never replaced or removed |

Pre-flight refuses a *published* release before anything is built, so the "published" rows are reachable
only by re-running the failed `publish` job of the same run. A *new* run of a published tag never gets that
far.

**An unpublished tag left behind** (a failed run): the draft is invisible to the public. The maintainer
either re-runs the failed jobs, or deletes the remote tag and the draft (`gh release delete TAG --yes`,
**without** `--cleanup-tag`, then `git push --delete origin TAG`), fixes, and pushes the tag again. A
number is burned only by a *published* release (spec D2, D11). `docs/releasing.md` carries both.

**Facts checked** (gh 2.45 here, 2.104.0 on the runner; R13): the flags above exist in both; a draft is
found by its pending tag name, so `upload`, `download` and `edit` act on a draft; `releases/tags/{tag}` in
the REST API answers `404` for a draft and `200` only for a published release (so pre-flight reads it, R4).

**What no run proves before the first release (D11).** These seven calls run against the real GitHub only
at the first real tag. The plan's cover: (a) the fake `gh` in the tests implements the same table and keeps
a state, so the order, the rerun rows and the "never publish before the compare" rule are tested; (b) the
flags are the ones `gh release --help` lists in both versions; (c) the design leaves nothing public if a
call fails (D7). The first real run is the proof, and the runbook asks the maintainer to read the release
page right after it.

## R4. Where the scripts live and how their tests run (FR-004, FR-005, FR-009, FR-016)

**Decision.** `scripts/release/` at the repository root, plain Python, standard library only, supported on
3.11 to 3.13 (the runner's `python3` is 3.12, and the tests run on all three). Never in the wheel (the
wheel's `packages` is `src/ext_r2c`), never imported by the SDK, and importing nothing from it.

| File | Role | Refusal ids (`refused [id]`) |
|---|---|---|
| `release_common.py` | `Refusal`, version/tag grammar, `pyproject` and changelog readers, the wheel address, the exit-code wrapper | |
| `preflight.py` | the gates of FR-004 | `event`, `version-grammar`, `prerelease-only`, `tag-matches-version`, `changelog-section`, `on-main`, `no-published-release`, `license-copy` |
| `content.py` | wheel and sdist content (FR-009) | `wheel-contents`, `wheel-metadata`, `schemas`, `sdist-contents` |
| `scan.py` | generic private-looking-text scan (R10) | `scan` |
| `sums.py` | write and check `SHA256SUMS` (R12) | `sums` |
| `notes.py` | assemble the release notes (R11) | `notes` |
| `publish.py` | R3 | `unexpected-files`, `upload-differs`, `published-differs`, `gh` |
| `verify.py` | the public download check of `verify` (R2) | `public-differs` |
| `status-block.md` | the status block of the notes, with `{{tag}}`, `{{version}}`, `{{wheel}}`, `{{address}}` | |

Every script has `main(argv) -> int`, prints one line `refused [id]: what failed. What to change.` on a
refusal, and exits **0** pass, **1** refusal, **2** misuse or an unexpected error (so the Actions page tells
"a gate said no" from "the script broke"). Details: [contracts/scripts.md](contracts/scripts.md).

**Parsing, no dependency.** `tomllib` (3.11) reads `python/pyproject.toml`; the version is matched by one
strict regular expression, `^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(a|b|rc)(0|[1-9]\d*)$` (a pre-release in
PEP 440's normal form: no `.dev`, `.post`, epoch, local part or leading zero). A final version, or any other
spelling, is refused with a different id (`prerelease-only` or `version-grammar`). `packaging` is not
imported: the scripts run on the runner's bare `python3`.

**How "tests run against the installed wheel" applies (principle VII).** The rule keeps the tests from
passing on source that the wheel would not carry. These scripts are not in the wheel; what they act on is
(a) the repository's own files and (b) the built files. So:
- the tests are ordinary pytest files in `python/tests/` (`test_release_*.py`), so CI runs them in the
  installed-wheel venv with the rest, with no new workflow step;
- each imports the script **by path** from the checkout (`parents[2] / "scripts" / "release"`, as
  `test_example_langgraph.py` does for the example) and fails with a clear message outside a checkout;
- the scripts' logic is proven on **fixtures** (a tiny wheel or sdist written with `zipfile`/`tarfile`, a
  changelog, a version, a fake `gh`), and the real bytes are proven by the `inspect` job of `wheel.yml` on
  every push (R1). So the unit tests cover the refusals and the real run covers the real files.

**The fake `gh`.** `python/tests/release_fakes.py` writes an executable `gh` into a temporary directory put
first on `PATH`. It holds a JSON state (releases, assets, their bytes), implements exactly the calls of the
R3 table, exits non-zero on any other call and can be told to fail at call N or to return altered bytes on
download. Tests: fresh create; a leftover draft with a stray asset; an upload that comes back different
(stops before `edit --draft=false`); a published release with equal sums (succeeds, writes nothing); a
published release that differs (refuses, and the log shows no `delete-asset`, no `upload`, no `edit`);
a failure at each call (never a public release; the publish call is the last one).

**Fixtures are built from pieces.** The repository's own commit scan refuses any added line that holds a
home-directory prefix or a private-address range. The scan's patterns and the fixtures that plant a hit
therefore spell those strings from fragments at run time (for example `"/" + "ho" + "me" + "/"`), and a
test pins that the planted text is found. This is a property of how the files are written, not of what
they do.

**Alternatives.** *Scripts inline in the YAML* (untestable, and a leaky `run:` is the classic injection
site). *Scripts in `python/` and in the sdist* (they would ship in a source archive an adopter downloads
and they read the repository, which the archive lacks). *`packaging` for versions* (an import the bare
runner lacks; the strict regex is shorter than the dependency).

## R5. The adopter's path becomes part of CI's definition (FR-008)

**Decision.** `python/tests/adopter_path.py`, not collected by pytest (no `test_` prefix), run like the four
single-extra scripts: `python -I tests/adopter_path.py`. It is a step of `checks` in `wheel.yml`, after the
four single-extra steps, so it runs on every push, on 3.11, 3.12 and 3.13, and in the release.

What the step does, in a clean venv named for it:
1. `uv venv --python PY ../.adopter-venv`; `uv pip install ../.adopter-venv "$(ls dist/*.whl)[a2a,mcp,langgraph]" uvicorn`
   (the extras the install line names, plus the server the example's README names; **no dev group, no
   pytest**).
2. The script asserts pytest is not importable, then starts `python main.py --auto` as a subprocess with the
   working directory `examples/langgraph_agent` (the tagged source, as the adopter has it), two free ports in
   `PLANNER_URL` and `REPORTER_URL`, `R2C_EXAMPLE_MODEL` removed (the scripted model; no network, no keys)
   and a timeout of 120 s.
3. It asserts exit status 0 and that the output holds the two replies the example's README shows (the
   reporter's "Published." and the planner's "Not published: the approval was refused."), then prints
   `adopter path: ok`.

**Why in the shared workflow, per leg.** FR-008 says CI's definition; the cost is a few seconds per leg and
the value is that a change that breaks the adopter's first five minutes is red on the push that does it.
**Risk named:** `uvicorn` is not pinned (the example's README does not pin it, and the adopter's own
install does not), so a new `uvicorn` release can turn CI red with no change here. That is the adopter's
experience, so the red is true; the rerun and the fix are the maintainer's call.

**The example's own README line changes** (R8): its `pip install "ext-r2c[...]" uvicorn` would fetch
someone else's package if the name is ever taken (FR-018).

## R6. Pinning the actions, and the hygiene a workflow that holds write access needs (FR-014)

**Every `uses:` is a full 40-character commit SHA with the version as a trailing comment.** Resolved on
2026-11-24 from the tag (annotated tags dereferenced) and dated; each is at least two weeks old, the
repository's rule for any dependency:

| Action | Version | Commit | Commit date |
|---|---|---|---|
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` | 2026-07-17 |
| `astral-sh/setup-uv` | v10.3.3 | `68559e99cc807c1eb7e9238fd43a15bba460eec2` | 2026-10-28 |
| `actions/upload-artifact` | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | 2026-10-07 |
| `actions/download-artifact` | v8.0.2 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` | 2026-10-07 |

`setup-uv` v10.4.0 exists but is under two weeks old, so v10.3.3 is pinned. CI today uses
`checkout@v4` and `setup-uv@v6` by tag; moving them to these pins is a change to CI (point 3 of
[Needs the maintainer](plan.md#needs-the-maintainer)). Release-note facts that matter: `setup-uv` v10
disables its cache for release events by default, and the plan sets `enable-cache: false` everywhere in
`wheel.yml` and `release.yml` anyway; `download-artifact` v8 fails on a digest mismatch by default.

**The hygiene list** (what the zizmor audits and common practice ask; each is a line of the workflow test
of SC-005 unless it is only a review point):
1. No `pull_request_target`, no `workflow_run`; `release.yml` has no `pull_request` at all.
2. `permissions: contents: read` at the top of every workflow; one job overrides it with `contents:
   write`; no `id-token`, no `packages`.
3. `persist-credentials: false` on every `actions/checkout`.
4. No `${{ ... }}` inside any `run:` (template injection). Every value a script needs (`github.ref_name`,
   `github.event_name`, `github.repository`, `matrix.python`) goes through an `env:` entry and is read as
   `"$NAME"`; the tag is read from the environment, never interpolated into a command line.
5. Every `uses:` pinned by SHA; local `./.github/workflows/wheel.yml` is allowed.
6. No `secrets:` anywhere and no `secrets: inherit`; the only credential is the job's own token, read as
   `GH_TOKEN: ${{ github.token }}` in `preflight` (read) and `publish` (write).
7. `enable-cache: false` on `setup-uv` (cache-poisoning on a job that publishes).
8. Every workflow and job has a `name:`.
9. `concurrency` on the release (R2).
10. No write to `GITHUB_ENV` or `GITHUB_PATH` from a value derived from the tag or the event.

**Linting.** The tests above read the YAML (PyYAML, already in the dev group; it reads the key `on:` as
`True`, so the test looks up both). A static lint is a good extra and is not a gate:
- `zizmor` 1.32.0 (uploaded 2026-11-02, 22 days old; the only advisory OSV lists is a debug-logging one
  fixed in 1.28.0) run **offline**, never with a token, from a throwaway `uvx` environment. The newest
  versions, 1.33.0 and 1.33.1, are two days old and are not used.
- `actionlint` from the project's release binary, checksum compared.
Neither is a dependency of the project or a step of CI. **This session's attempt to run `zizmor` was
refused by the permission classifier**, so no lint has been run and no baseline of the current `python.yml`
exists; the maintainer decides whether to allow it for the phase that writes the workflows (point 1 of
[Needs the maintainer](plan.md#needs-the-maintainer)). The tests are the guard that does not depend on it.

## R7. The manual start (FR-019, D11)

- **Trigger.** `workflow_dispatch` with no inputs, on any branch. The version it uses is the one in
  `python/pyproject.toml` at that ref; there is nothing to type, so nothing to get wrong.
- **What runs.** `preflight` in manual mode runs the checks that need no tag: `event`, `version-grammar`,
  `prerelease-only`, `changelog-section`, `license-copy`. The three tag-bound ones (`tag-matches-version`,
  `on-main`, `no-published-release`) are skipped and the log says "skipped: manual start". Then the notes
  are assembled, `wheel` runs whole, and the build job writes the file list, sizes and checksums to the
  run's step summary. `publish` and `verify` are skipped.
- **What it writes.** Nothing outside the run: no tag, no release, no draft, no asset, no commit. Its
  artifacts expire with the run (14 days).
- **The guard inside the script.** `preflight.py` refuses any event other than `push` (a tag) and
  `workflow_dispatch`, and `push` only when the ref is a tag, so a trigger added to the YAML by mistake
  does not become a way to release.
- **It cannot run before the first push.** GitHub starts a manual run only for a workflow file that exists
  on the default branch. Until `release.yml` is on `main` there, the workflow's wiring is covered by the
  workflow tests and by lint, not by a run. The runbook and the plan's last phase say so; the manual run is
  the first step after the maintainer's push.
- **A gate made red on purpose** (SC-002): `gh workflow run release.yml --ref SCRATCH-BRANCH` on a branch
  that breaks one gate (a version `0.1.0`, a missing changelog section, a planted private-looking line, a
  failing test). The version commit being on `main` is not required.

## R8. Documents, the known limits and the README lines (FR-015, FR-017, FR-018, D8)

**New files.**
- `docs/known-limits.md`: a title and one short list, one bullet per limit of FR-015, each pointing at the
  paragraph of `python/README.md` that has the detail. The notes quote it whole (R11).
- `docs/releasing.md`: the maintainer's runbook, in the order of FR-017: (1) choose the number; (2) the
  version commit (version, classifier once, the changelog section with a date, the README address); (3)
  build and run the private-token scan of the built files with the maintainer's **own** pattern, which is
  never written in the repository (D5; the step is a promise, not a gate); (4) push and wait for CI; (5)
  the manual run; (6) the tag, annotated, pushed; (7) what to read afterwards (the release page, the
  `verify` job); (8) a failed run (re-run, or delete the unpublished tag and the draft); (9) a published
  mistake (the next number; withdrawing is deleting by hand, only for leaked data, and then the incident
  steps).

**Edited files.**
- Root `README.md`: the status paragraph says alpha and links `docs/known-limits.md`; a new *Install*
  part gives the one address line with `[a2a,mcp,langgraph]` and says the bare name `ext-r2c` on PyPI is
  not this project until it is published here.
- `python/README.md`: the paragraph above its Install table gives the same line and the same sentence;
  the "from a wheel file" lines keep working and say the placeholder is the address above.
- `examples/langgraph_agent/README.md` line 16: the address line replaces the bare-name install.
- `AGENTS.md` Docs table (+2 rows; the file has 70 lines against a limit of 150); `ARCHITECTURE.md` (the
  layout and the rule that `scripts/` imports nothing from `ext_r2c`); `CHANGELOG.md`; `WORKSTATE.md`.

**Tests (SC-011, FR-018)** in `python/tests/test_release_docs.py`, reading the repository from the
installed-wheel venv:
- the install address in each README equals
  `https://github.com/timezlab/ext-r2c/releases/download/v{V}/ext_r2c-{V}-py3-none-any.whl` for `V` the
  version of the **installed wheel** (`importlib.metadata`), so a version bump without the README edit fails;
- no line in any README that runs `pip install`, `uv pip install` or `uv add` names `ext-r2c` without an
  address (`@ https://`) or a wheel path;
- the sentence about the bare PyPI name is in both READMEs; both link `docs/known-limits.md`;
- `docs/releasing.md` has a heading for each step of FR-017, and `AGENTS.md` links it;
- the metadata classifier is not `Pre-Alpha`, and for an `aN` version is `3 - Alpha`.

**One known window.** The README names a release that does not exist until the tag is pushed. The runbook
says to push the version commit, run the manual run, and tag in the same sitting; the window is minutes.

## R9. The `0.1.0a1` commit (FR-001, FR-003)

One commit, made late in the work (the last tasks of the docs phase, so the README test and the manual run
see the same version):
- `python/pyproject.toml`: `version = "0.1.0a1"`; classifier `Development Status :: 3 - Alpha`.
- `README.md`: the status paragraph (alpha) and the install part (R8). `python/README.md`,
  `examples/langgraph_agent/README.md`: the address line.
- `CHANGELOG.md`: `## [Unreleased]` becomes `## [0.1.0a1] - <date of the commit>`, a fresh empty
  `## [Unreleased]` above it, and a line under *Added* for the release tooling and the known-limits file.
- **Nothing under `python/src/` or `standard/`** (SC-010): a task ends with `git diff --stat` over those
  two paths against the commit before this spec's work, expecting an empty result.
- `test_smoke.py` already pins `ext_r2c.__version__` to the installed metadata, so no other file carries the
  number. `uv.lock` is ignored by git (`.gitignore`), so there is no lock to move.
- The date is the day of the commit; pre-flight requires a valid ISO date, not today's.

## R10. The scan (FR-009, D5, SC-006)

**What it reads.** Every member of the wheel (a zip) and the sdist (a gzip tar) that decodes as UTF-8;
members that do not decode are counted as binary and listed by name (a binary in these files is itself
reported by the content check, which expects none).

**What it looks for, line by line** (four categories; a hit is a category and a count, never text):

| Category | Pattern (shape) |
|---|---|
| `home-path` | a home-directory prefix of Linux, macOS or Windows followed by a name, and `/root/` |
| `private-address` | an IPv4 address in one of the three private ranges of RFC 1918 (`10/8`, `172.16/12`, `192.168/16`), not part of a longer dotted number |
| `email` | `name@domain.tld`, unless the domain is `example.com`, `example.net`, `example.org`, or ends in `.example`, `.test`, `.invalid`, `.localhost` (RFC 2606 / 6761) |
| `token` | well-known prefixes and shapes: GitHub (`ghp_`, `gho_`, `ghs_`, `github_pat_`), AWS access key ids, `sk-` keys, Slack `xox*-`, a PEM private-key header, a JWT triple |

**Output.** One line per hit: `scan: <file in archive> <category> <number of lines>`, then `refused [scan]: N
lines in M files. Remove the text or, if it is invented, use example.com.` Exit 1. Nothing of a matched line
is printed or logged, so a public log cannot echo it.

**Measured on 2026-11-24 on a fresh build** (a prototype of these shapes, run on the 0.0.1 build in a
scratch directory, not committed): wheel 74 files, 0 binary, **0 hits**; sdist 173 files, 0 binary, **0
hits**. With the reserved-domain allowance switched off the sdist has **1** hit (an invented address on
`example.com` in `tests/test_remote_errors.py`), which is why the allowance is part of the rule.

**What it cannot know.** The names, hosts and ids of the maintainer's own organisations: they cannot be in a
public repository (principle VI), and moving them into an Actions secret would put them where a public log
can echo a hit (D5). The runbook's step 3 is that check, on the maintainer's machine.

**The spelling of the patterns.** The prefixes `home` and `root` are written from fragments in the source
(R4), and the scan has a test that plants one hit of each category in a fixture and one reserved-domain
address that must pass.

## R11. The notes (FR-016, D8, D9, US5)

`notes.py --version V --repository OWNER/NAME --out FILE` writes three parts in this order, and refuses if
any part is missing or empty:

1. `## Status`: `scripts/release/status-block.md` with `{{tag}}`, `{{version}}`, `{{wheel}}` and
   `{{address}}` replaced. It says: this is an alpha; the standard's `v1` is a draft until its first
   outside adopter (principle IX); the package's version is its own, separate from the standard's; the one
   install line; and that the bare PyPI name is not this project.
2. `## Known limits`: `docs/known-limits.md` **whole**, except that its own first line (the title) is
   dropped because the notes supply the heading.
3. `## Changes in V`: the body of the `## [V] - DATE` section of `CHANGELOG.md`, up to the next `## `.

Not generated from commits (D9). A test builds the notes for the repository at hand and checks the three
headings in order, that every non-title line of the known-limits file is present verbatim, and that an empty
changelog section is a refusal. The notes go in `release-notes/RELEASE_NOTES.md`, an artifact between
`preflight` and `publish`, and into the manual run's step summary.

## R12. The checksum list and the asset names (FR-006, D10, SC-003)

- **Names.** `ext_r2c-V-py3-none-any.whl`, `ext_r2c-V.tar.gz`, `SHA256SUMS`: the wheel's and sdist's names
  are what `uv build` writes for the normal-form version (the strict version grammar of R4 guarantees it),
  so the address an adopter copies is predictable.
- **Format.** The format `sha256sum` writes and reads: `<64 hex digits>`, two spaces, the file name, a
  newline; one line for the wheel and one for the sdist, sorted by name; the file does not list itself.
  `sha256sum -c SHA256SUMS` (Linux), `shasum -a 256 -c SHA256SUMS` (macOS) verify it.
- **When.** `sums.py write` runs in `build`, right after `uv build` and before the artifact is uploaded, so
  the sums exist before any test (FR-006). Each leg and `inspect` run `sums.py check` on the downloaded
  files; `publish` compares the files it downloads back from the draft against the same list; `verify`
  compares the public files against it.

## R13. What was measured, and when

| Fact | Value | Date |
|---|---|---|
| PyPI answer for `ext-r2c` | `404` (the name is free for anyone) | 2026-11-24 |
| Default workflow token permission | `read` | 2026-11-24 |
| Tags, releases | none; no ruleset | 2026-11-24 |
| `python/LICENSE` equals the root `LICENSE` | yes (`cmp`) | 2026-11-24 |
| Wheel / sdist | 74 files (`ext_r2c/` and its dist-info; 6 schemas under `ext_r2c/schema/v1/`) / 173 files (source, tests, schemas, no `examples/`) | 2026-11-24 |
| Scan prototype | wheel 0, sdist 0 (1 without the reserved-domain allowance) | 2026-11-24 |
| Install by address, extras, no `--pre` | works with `pip` and `uv` for `0.1.0a1`; `ext-r2c>=0.1` finds nothing | 2026-11-23 |
| `gh` | 2.45 here; 2.104.0 on the `ubuntu-24.04` runner (Python 3.12.3, Git 2.56.1) | 2026-11-23 |
| CI leg duration | about 77 s | 2026-11-23 |
| PyYAML and `on:` | read as the boolean key `True` | 2026-11-23 |
| Action pins | the table of R6, tags re-resolved to the same commits | 2026-11-24 |
| zizmor on PyPI | 1.32.0 (2026-11-02), 1.33.0 and 1.33.1 (2026-11-22); one OSV advisory, fixed in 1.28.0 | 2026-11-24 |
| Running zizmor here | refused by the permission classifier; not run | 2026-11-24 |

## R14. What was checked and needs no change

- `test_smoke.py` pins `ext_r2c.__version__` to `importlib.metadata.version("ext-r2c")`: the bump touches
  one file.
- `python/pyproject.toml`'s sdist `include` and the hatch hook are unchanged: they already keep `examples/`
  out of both files and put the schemas in the wheel.
- `python.yml`'s triggers stay; a tag push does not start it.
- The `gh` calls and flags of R3 exist in both the local and the runner version.
- No change under `python/src/` and none under `standard/`: no behaviour of the SDK or the standard is part
  of a release job.

## R15. Gaps stated, not hidden

1. The seven publishing calls and `verify` run for real once, at the first release (D11, R3).
2. The wiring of both workflows is not run before the first push: GitHub starts neither without the files
   on `main`. The phase that adds `wheel.yml` ends with a push so the CI refactor is proven alone, before
   `release.yml` exists (plan, Delivery order).
3. No static lint has been run (R6).
4. Whether `uvicorn` stays compatible with the example is not pinned (R5).
5. The private-token scan is the maintainer's promise (D5).
