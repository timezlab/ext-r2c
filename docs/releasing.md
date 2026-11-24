# Releasing a pre-release

This is the maintainer's runbook for cutting a pre-release of the Python SDK, such as `0.1.0a1`. A release is
one pushed tag; `.github/workflows/release.yml` does the rest. The commands below use `0.1.0a1`: replace the
number for the next release.

What the workflow does after a tag is pushed, in order:

1. `preflight` checks the tag against the version in `python/pyproject.toml`, that the tagged commit is on
   `main`, that the version is a pre-release in normal form, that `CHANGELOG.md` has a dated section for it,
   that no published release has that tag yet, and that the two `LICENSE` files are the same.
2. `wheel` builds the wheel and the source archive **once**, runs the whole test suite on Python 3.11, 3.12
   and 3.13 against that one wheel, and checks the files: their content, a generic scan for private-looking
   text, and a `SHA256SUMS` list.
3. `publish` is the only job with write permission. It makes a draft release, uploads the three files, reads
   them back, compares the bytes with the tested ones, and only then makes the release public, marked as a
   pre-release. It runs no built code.
4. `verify` downloads the files from the public address with no credential, compares them with the list, and
   installs the install line of the release notes into a clean environment.

No version of the package goes to PyPI: the bare name `ext-r2c` on PyPI is not this project. What a release
does not do is written in [`known-limits.md`](known-limits.md), and the release notes quote that file whole.

## 1. Choose the number

The number is written once, in `python/pyproject.toml`. It must be `MAJOR.MINOR.PATCH` followed by `a`, `b` or
`rc` and a number, for example `0.1.0a2` or `0.1.0b1`. A final number such as `0.1.0` is refused by the
workflow on purpose: a final release needs its own decision.

A number is used up by a published release. A tag that never became a release can be pushed again (step 8).

## 2. Make the version commit

One commit changes, together:

- `python/pyproject.toml`: `version`, and the `Development Status` classifier when the stage changes
  (`3 - Alpha` for `aN`, `4 - Beta` for `bN` and `rcN`).
- `CHANGELOG.md`: `## [Unreleased]` becomes `## [0.1.0a1] - YYYY-MM-DD` (the date of the commit), with a fresh,
  empty `## [Unreleased]` above it. The section is the "Changes" part of the release notes, so it says what
  changed for someone who has not read the commits.
- The install address in the root `README.md`, in `python/README.md` and in
  `examples/langgraph_agent/README.md`:

  ```text
  ext-r2c[a2a,mcp,langgraph] @ https://github.com/timezlab/ext-r2c/releases/download/v0.1.0a1/ext_r2c-0.1.0a1-py3-none-any.whl
  ```

Nothing under `python/src/` and nothing under `standard/` changes in a version commit. Then build, install the
wheel into a clean environment and run the whole suite there, as the root `README.md` shows. A test fails when
a README names a different wheel than the installed one, or when the changelog has no section for it.

## 3. Scan the built files with your own pattern

CI runs a generic scan (home-directory prefixes, private address ranges, token shapes) and prints only a file,
a category and a count. It cannot know what is private to you. This step is a promise, not a gate: nothing
checks that it was done.

Build the files, unpack them, and search them with the pattern you keep **outside this repository**. The
pattern is not in this repository, because the repository is public and a pattern of private names would be
the leak.

```bash
cd python && uv build --out-dir ../.release-dist && cd ..
unpacked=$(mktemp -d)
unzip -q .release-dist/*.whl -d "$unpacked"
tar -xzf .release-dist/*.tar.gz -C "$unpacked"
grep -rIEn -f "$PATTERN_FILE" "$unpacked"      # expect no output
```

Fix what it finds in the source and make the version commit again. Do not go on while there is output.

## 4. Push and wait for CI

```bash
git push
```

Wait for the run of that commit (`python.yml`): `wheel / build`, three `wheel / checks` (3.11, 3.12, 3.13) and
`wheel / inspect` must all be green. A red run is fixed before anything else; the next steps assume this one.

## 5. Start the manual run

```bash
gh workflow run release.yml --ref main
gh run watch
```

Pick the run that was just started. A manual start runs the checks that need no tag (the version is a
pre-release, the changelog section, the license copy) and says in its log that it skipped the three that need
one. Then `wheel` runs in full and the notes are assembled and shown in the run's summary. `publish` and
`verify` are skipped, so nothing becomes public: no tag, no release, no file.

Read the summary: the wheel, the source archive and the sums are listed, and the notes have their three parts
(status, known limits, changes). If a job is red, fix it as its own commit, push, and start the manual run
again.

## 6. Tag and push the tag

Tag the commit that CI and the manual run passed, in the same sitting as the push of the version commit.
The READMEs name a release that does not exist until the tag is pushed, so keep that window short.

```bash
git fetch origin && git status -sb          # main is equal to origin/main
git tag -a v0.1.0a1 -m "0.1.0a1"
git push origin v0.1.0a1
```

The tag is annotated and begins with `v`. The push starts `release.yml`. Pushing a tag is the one act that
publishes: do it when you mean it.

## 7. What to read afterwards

```bash
gh run watch
gh release view v0.1.0a1
```

- All four jobs are green; `verify` is the one that matters most, because it installed what anyone can
  download.
- The release page shows a **pre-release** with exactly three files: `ext_r2c-0.1.0a1-py3-none-any.whl`,
  `ext_r2c-0.1.0a1.tar.gz` and `SHA256SUMS`.
- The notes have the three parts: the status and the install line, the known limits, and the changes.
- From a clean environment, the install line works as written, with no `--pre`.

The seven publishing calls and `verify` run for real only at the first tag, so read the first run slowly. What
else the build did not prove is listed in the plan's
[gaps](../specs/008-release/research.md#r15-gaps-stated-not-hidden).

## 8. When a run fails

Nothing is public before the last call of `publish`, so a red run before it leaves nothing to withdraw.

- **A job failed for a reason outside the code** (a network error, a runner problem): re-run the failed jobs
  from the run's page, or `gh run rerun RUN_ID --failed`. A draft left behind by an earlier try is refreshed, not
  duplicated, and a release that is already public with the same bytes counts as success.
- **The workflow or the code needs a fix**: fix it on `main` and push it. Then delete the tag that never
  became a release, delete the draft if there is one, and tag again (step 6):

  ```bash
  gh release delete v0.1.0a1 --yes            # only a draft; this does not touch the tag
  git push origin --delete v0.1.0a1
  git tag -d v0.1.0a1
  ```

  Check first that the release is a draft, with `gh release view v0.1.0a1 --json isDraft`. Never delete a
  release that is public (step 9).
- **`verify` is red and the release is public**: the files may not have been served yet. Re-run `verify` once.
  If it is red again, treat the release as a published mistake.

## 9. When a published release is wrong

A published pre-release is never changed, not by the workflow and not by hand. A mistake in one is fixed by the
next number: start again at step 1 with `0.1.0a2`, and say in its changelog section what was wrong.

Withdrawing a release by deleting it is done by hand, and only when it leaked data. Deleting the page does not
take back copies that were already downloaded, so treat what leaked as leaked: change it at its source first.
Then delete the release and its tag, and publish the next number.
