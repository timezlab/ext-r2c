# Data model: the first pre-release

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md)

Nothing here is a class of the SDK. These are the things a run reads, makes and decides about, and the
rules that connect them. Scripts and workflows are in [contracts/](contracts/).

## 1. Version and tag

| Name | Rule | Example |
|---|---|---|
| Version | one string in `python/pyproject.toml`: three numbers without leading zeros, then `a`, `b` or `rc` and a number (the regular expression is in [research R4](research.md#r4-where-the-scripts-live-and-how-their-tests-run-fr-004-fr-005-fr-009-fr-016)): a PEP 440 pre-release in normal form | `0.1.0a1` |
| Final version | the same without the `aN`/`bN`/`rcN` part; valid PEP 440, refused by this job (D4) | `0.1.0` |
| Tag | `v` + the version, exactly | `v0.1.0a1` |
| Wheel name | `ext_r2c-` + version + `-py3-none-any.whl` | `ext_r2c-0.1.0a1-py3-none-any.whl` |
| Sdist name | `ext_r2c-` + version + `.tar.gz` | `ext_r2c-0.1.0a1.tar.gz` |
| Install address | `https://github.com/OWNER/NAME/releases/download/` + tag + `/` + wheel name | the line of the spec's D3 |

Refusal split: a string that is not a normal-form version at all is `version-grammar`; a valid final
version is `prerelease-only`. The version has one home; `ext_r2c.__version__` and the file names follow it.

## 2. Release (the GitHub object)

States, and what moves a release between them. Only `publish.py` makes a transition.

```text
absent ──create (draft, prerelease, not latest)──▶ draft
draft  ──upload, read back, every SHA-256 equal──▶ draft, verified
draft, verified ──edit --draft=false──▶ published (pre-release, not latest)
published ──(nothing)──▶ published         never edited, never emptied, never deleted by this job
```

| Field | Value |
|---|---|
| Tag | `vX.YaN`, already on the remote (`--verify-tag`) |
| Title | the tag |
| Draft | true until the compare passes |
| Pre-release | always true (D4); never "latest" |
| Assets | exactly three: wheel, sdist, `SHA256SUMS` |
| Notes | the three parts of [release-assets.md](contracts/release-assets.md) |

Reads at the start of `publish.py` (R3): **absent**, **draft**, **published**. The table of reruns is in
[research R3](research.md#r3-draft-upload-download-back-compare-publish-and-a-rerun-fr-010-fr-011-fr-012-d7).

## 3. Asset and the checksum list

| Asset | Made by | Recorded where |
|---|---|---|
| wheel | `uv build` in `build` | a line of `SHA256SUMS` |
| sdist | `uv build` in `build` | a line of `SHA256SUMS` |
| `SHA256SUMS` | `sums.py write` in `build` | it is the record; it lists the other two and not itself |

Rules: the sums exist **before any test** (FR-006); the bytes tested, the bytes uploaded and the bytes read
back from the draft are equal if and only if each file's SHA-256 equals its line; the public copies read by
`verify` are compared the same way.

## 4. Gate

One check that can stop a run. `where`: which job; `tag run`/`manual run`: whether it runs there.

| Gate (refusal id) | Script | Where | Tag run | Manual run | Test |
|---|---|---|---|---|---|
| `event` | `preflight.py` | `preflight` | yes | yes | fixture |
| `version-grammar` | `preflight.py` | `preflight` | yes | yes | fixture |
| `prerelease-only` | `preflight.py` | `preflight` | yes | yes | fixture |
| `tag-matches-version` | `preflight.py` | `preflight` | yes | skipped | fixture |
| `changelog-section` | `preflight.py` (and `notes.py`) | `preflight` | yes | yes | fixture |
| `on-main` | `preflight.py` | `preflight` | yes | skipped | temporary git repository |
| `no-published-release` | `preflight.py` | `preflight` | yes | skipped | fake `gh` |
| `license-copy` | `preflight.py` | `preflight` | yes | yes | fixture |
| `notes` | `notes.py` | `preflight` | yes | yes | fixture |
| a failing Python leg | the legs' steps | `wheel` / `checks` | yes | yes | the real run |
| the adopter's path | `adopter_path.py` | `wheel` / `checks` | yes | yes | the real run |
| `wheel-contents`, `wheel-metadata`, `schemas`, `sdist-contents` | `content.py` | `wheel` / `inspect` | yes | yes | fixture; real bytes in CI |
| `scan` | `scan.py` | `wheel` / `inspect` | yes | yes | fixture; real bytes in CI |
| `sums` (a leg's check of the downloaded files) | `sums.py check` | `wheel` / `checks`, `inspect` | yes | yes | fixture |
| `unexpected-files`, `upload-differs`, `published-differs`, `gh` | `publish.py` | `publish` | yes | skipped | fake `gh` |
| `public-differs` | `verify.py` | `verify` | yes | skipped | local file server |

Every gate that is a script is a test on a fixture; the real run proves the wiring (SC-002). A gate that
refuses prints one line `refused [id]: what failed. What to change.` and creates nothing.

## 5. Run

| Kind | Starts on | Gates | Writes |
|---|---|---|---|
| **Real** | a pushed tag matching `v*` | all | a draft, three assets, then a public pre-release |
| **Manual** | `workflow_dispatch`, any branch | all but the three tag-bound | nothing outside the run; artifacts expire in 14 days |

A run has one version (the one in `pyproject.toml` at its ref) and, if real, one tag. Two runs for one tag
do not overlap (`concurrency`, no cancel).

## 6. Known limits

One file, `docs/known-limits.md`: a title line, then bullets, one per limit of FR-015, each linking the
paragraph of `python/README.md` that has the detail. It has no front matter and no other heading before its
bullets. The notes quote everything after the title line, verbatim. Edited like any document, by a commit.

## 7. The notes

Three parts, in this order, each non-empty (R11):

| Part | Heading in the notes | Source |
|---|---|---|
| status | `## Status` | `scripts/release/status-block.md` with its four placeholders |
| known limits | `## Known limits` | `docs/known-limits.md` without its title line |
| changes | `## Changes in <version>` | the body of `## [<version>] - <date>` in `CHANGELOG.md` |

## 8. The changelog section

`CHANGELOG.md` follows Keep a Changelog. For a version V the section starts at the line
`## [V] - YYYY-MM-DD` (the date a valid ISO date) and ends before the next line that starts with `## `. It is
**non-empty** if it holds at least one line that is neither blank nor a `###` heading. `## [Unreleased]`
is never a release section.

## 9. What the scan reads and says

Input: the members of the wheel and the sdist that decode as UTF-8. Output: for each file and category
(`home-path`, `private-address`, `email`, `token`) a count of lines; never text. A member that does not
decode is "binary" and is named. Categories and the reserved-domain allowance are in
[research R10](research.md#r10-the-scan-fr-009-d5-sc-006).

## 10. Where each fact lives

| Fact | Lives in | Read by |
|---|---|---|
| the version | `python/pyproject.toml` | `preflight.py`, `content.py`, `notes.py`, the README test |
| the changelog section | `CHANGELOG.md` | `preflight.py`, `notes.py` |
| the known limits | `docs/known-limits.md` | `notes.py`, the READMEs (by link) |
| the checks CI and the release run | `.github/workflows/wheel.yml` | `python.yml`, `release.yml` |
| the Python versions | the matrix of `wheel.yml` only | |
| the install address | derived from the repository and the version; written in three READMEs | the README test |
| the schemas the wheel must carry | `standard/v1/schema/*.json` | `content.py` (names only) |
