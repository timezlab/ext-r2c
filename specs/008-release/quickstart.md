# Quickstart: validating the first pre-release

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Contracts**: [contracts/](contracts/)

A run-through that proves the feature, from a laptop first and GitHub last. Nothing here pushes a tag or
creates a release. Commands run from the repository root unless a `cd` says otherwise. "The wheel venv" is
the one the README builds (`uv build`, a clean venv, the wheel plus the dev group).

## 1. The scripts, on a laptop, with no GitHub

```bash
cd python && uv build --out-dir ../.release-dist && cd ..          # one build: wheel, sdist
python3 scripts/release/sums.py write --dir .release-dist           # SHA256SUMS before anything else
python3 scripts/release/sums.py check --dir .release-dist
python3 scripts/release/content.py --dir .release-dist              # wheel holds ext_r2c/ only, schemas, version
python3 scripts/release/scan.py .release-dist/*.whl .release-dist/*.tar.gz     # expect: 0 hits
python3 scripts/release/preflight.py --event workflow_dispatch      # the tag-free checks
python3 scripts/release/notes.py --repository timezlab/ext-r2c --out .release-dist/RELEASE_NOTES.md
```

Expected: each prints its `... ok` line and exits `0`. On a tree whose version is not yet a pre-release,
`preflight.py` prints `refused [prerelease-only]: ...` and exits `1`; that is the gate working. Add
`.release-dist/` is ignored by git (phase 3 adds it, with `.adopter-venv/`; `python/dist/` already is).

To see a refusal, change one input and run the script again: a version `0.1.0` (`prerelease-only`), a
changelog without the section (`changelog-section`), a home-directory path planted in a copy of the
wheel's text file (`scan`: file, category and count, no text).

## 2. The tests, on the installed wheel

```bash
cd python
uv build
uv venv .wheel-venv && uv pip install --python .wheel-venv dist/*.whl --group dev
.wheel-venv/bin/pytest tests/test_release_*.py          # the release tests alone
.wheel-venv/bin/pytest                                  # the whole suite
```

Expected: the release tests pass, including the fake-`gh` publishing rows (`test_release_publish.py`), the
workflow rules (`test_release_workflows.py`) and the README address (`test_release_docs.py`); the suite is
as green as before this spec. On Python 3.11, 3.12 and 3.13 (`uv venv --python 3.11`, and so on).

## 3. The adopter's path, by hand

In a clean directory with no checkout of the SDK, only the wheel and the example's source:

```bash
uv venv .adopter-venv && uv pip install --python .adopter-venv \
  "ext-r2c[a2a,mcp,langgraph] @ file://$PWD/<wheel path>" uvicorn
cd examples/langgraph_agent && ../../.adopter-venv/bin/python main.py --auto
```

Expected: both conversations end as the example's README shows (the reporter's reply ends `Published.`, the
planner's ends `Not published: the approval was refused.`), and the install needed no `--pre`. CI runs the
same thing as `python -I tests/adopter_path.py`.

## 4. The workflows, as data

```bash
cd python && .wheel-venv/bin/pytest tests/test_release_workflows.py
```

Expected: no `pull_request` trigger on the release; write permission on exactly one job, which installs and
imports nothing; every action pinned by commit; no `${{ }}` inside a `run:`; no secrets; the checks defined
only in `wheel.yml`. If the maintainer allowed a lint (plan, point 1):

```bash
uvx --from zizmor==1.32.0 zizmor --offline .github/workflows/
```

## 5. CI on GitHub after the first push (end of phase 3)

Push (on the maintainer's go) and open the run for the commit. Expected: `wheel / build`, three
`wheel / checks (3.11 | 3.12 | 3.13)` and `wheel / inspect` are green; each leg's log shows the same wheel
checksum as the build's summary; the legs' step list ends with `adopter path: ok`. A red leg is the
refactor's, and is fixed before `release.yml` is written.

## 6. The manual run, after `release.yml` is on `main` (end of phase 6)

```bash
git ls-remote --tags origin | wc -l ; gh release list | wc -l      # before: 0 and 0
gh workflow run release.yml --ref main
gh run watch                                                       # pick the run it just started
git ls-remote --tags origin | wc -l ; gh release list | wc -l      # after: the same two numbers
```

Expected: `preflight` (with the three tag-bound checks skipped and said so), `wheel` and the notes are green;
`publish` and `verify` are skipped; the `build` job's summary lists the wheel, the sdist and the sums; the
two counts did not change and the commit list is the same (SC-004). To prove a gate by making it red on
purpose, repeat on a scratch branch that breaks exactly one thing (SC-002), then delete the branch:

| Break on the scratch branch | Expected |
|---|---|
| version `0.1.0` | `preflight` refuses `prerelease-only` |
| rename the changelog section | `preflight` refuses `changelog-section` |
| plant a home-directory path in a test file | `inspect` refuses `scan` (file, category, count) |
| make one test fail | that leg is red; `wheel` is red |

## 7. The real release (not part of this spec's work)

On the maintainer's own go, after the runbook (`docs/releasing.md`): push the tag. Expected: a draft is
created and filled, the three files read back with the recorded sums, the release becomes public as a
pre-release, `verify` installs the line from the public address. Read the release page. If anything fails
before the last call, nothing is public and the runbook says what to do.
