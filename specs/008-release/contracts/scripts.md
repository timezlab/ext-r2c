# Contract: the release scripts (`scripts/release/`)

**Plan**: [../plan.md](../plan.md) | **Research**: [../research.md](../research.md) R3, R4, R10–R12

Plain Python, standard library only, Python 3.11 to 3.13, no import from `ext_r2c`. Each file is run as
`python3 scripts/release/<name>.py ...` from the repository root and also imported by path in tests.

## Common behaviour

- `main(argv: list[str] | None = None) -> int`; the file ends with `sys.exit(main())` under
  `__main__`.
- **Exit codes**: `0` pass; `1` a gate refused; `2` misuse (bad arguments, a missing file) or an
  unexpected error. The Actions page therefore tells "a gate said no" from "the script broke".
- **A refusal** prints one line to standard error and nothing else of its own:
  `refused [<id>]: <what failed>. <what to change>.` The line names values the maintainer typed (a tag, a
  version, a file name in an archive). It never holds text read from a built file.
- **Environment, not interpolation.** The workflow passes values as environment variables and the scripts'
  arguments are filled from them by the shell (`--tag "$TAG"`); no script reads a secret.
- `--root PATH` (default: the repository root, two levels above the script) is where the repository files
  are read from. Tests point it at a temporary directory.
- `release_common.py` is the only module the others import (`Refusal(id, what, change)`, the version and tag
  grammar, `read_version(root)`, `changelog_section(text, version)`, `wheel_name(version)`,
  `sdist_name(version)`, `address(repository, version)`, and `run_main(fn)` which maps `Refusal` to exit 1).
  *Added while implementing phase 4 (2026-11-24):* `REPOSITORY_RE` (the `OWNER/NAME` check, moved here from
  `preflight.py` and `notes.py`), `version_from_tag(tag)` (a tag is `v` and a normal-form pre-release, else
  `version-grammar` or `prerelease-only`), and `check_sums(folder, ident)`, which **runs** `sums.py check` and
  raises its refusal again under `ident` (so `publish.py` says `sums` and `verify.py` says `public-differs`,
  and `sums.py` stays the only place that reads the list).
  *Changed after the outside review (phase 6, 2026-11-24, research R16):* the version, date and repository
  grammars end in `\Z` and read ASCII digits only (a trailing newline or an Arabic-Indic digit is refused),
  and every name read from an archive is printed through `printable` (a character that is not printable, such
  as a newline, is spelled out), so a name cannot forge a line of the public log. Every script reads and
  writes its text files as UTF-8, whatever the locale.

## `preflight.py`

```text
preflight.py --event EVENT [--ref-type TYPE] [--tag TAG] [--sha SHA] [--repository OWNER/NAME] [--root PATH]
```

| Input | Meaning |
|---|---|
| `--event` | `push` (a real run) or `workflow_dispatch` (manual); anything else is `event` |
| `--ref-type` | `tag` for a real run; a real run on any other ref is `event` |
| `--tag` | the pushed tag (real run only) |
| `--sha` | the tagged commit (real run only; default `HEAD`) |
| `--repository` | `OWNER/NAME` (real run only), to read the release of the tag |

Checks, in this order, each its own refusal id; the tag-bound ones are skipped on a manual start with a line
`skipped [<id>]: manual start`:

1. `event`: the event and ref type are the two allowed pairs.
2. `version-grammar`: the version in `python/pyproject.toml` is a normal-form version.
3. `prerelease-only`: it has an `a`, `b` or `rc` part (a final version is refused: "a final release needs
   its own decision").
4. `tag-matches-version` *(tag-bound)*: the tag equals `v` + the version; the message names both.
5. `changelog-section`: `CHANGELOG.md` has a section `## [V] - DATE` with a valid date and a non-empty body.
6. `on-main` *(tag-bound)*: `git merge-base --is-ancestor SHA origin/main` succeeds. Exit status 1 of git is
   "not on main"; any other status (a shallow checkout, no `origin/main`) is the same id with its own
   message, "origin/main could not be read", so the maintainer looks at the fetch and not at the history.
7. `no-published-release` *(tag-bound)*: `gh api repos/OWNER/NAME/releases/tags/TAG` answers not found (the
   API answers `404` for a draft and `200` only for a published release). A found
   release refuses ("a mistake in a published pre-release is fixed by the next number"); any other failure
   of `gh` (network, rate limit, a server error) also refuses, because the check cannot say yes.
8. `license-copy`: `python/LICENSE` equals the root `LICENSE`, byte for byte; a copy that cannot be read is
   the same refusal (not an exit 2).

On success prints `preflight ok: version V` (and `tag TAG`). Needs `git` and, for check 7, `gh`.

## `content.py`

```text
content.py --dir DIR [--version V] [--root PATH]
```

`V` defaults to the version in `ROOT/python/pyproject.toml`, so the workflow interpolates nothing. Reads
`DIR/ext_r2c-V-py3-none-any.whl` and `DIR/ext_r2c-V.tar.gz`; refuses if either is missing.

| Id | Refuses when |
|---|---|
| `wheel-contents` | a member is outside `ext_r2c/` and `ext_r2c-V.dist-info/`; a member path has a `tests` or `examples` folder or a file named `test_*.py`; `ext_r2c/py.typed` is missing; a member is binary; a member is a symbolic link |
| `wheel-metadata` | `METADATA` has no `Name: ext-r2c`, a `Version:` other than V, or lacks any of `Provides-Extra: a2a`, `mcp`, `langgraph` |
| `schemas` | the schema files under `ext_r2c/schema/v1/` are not exactly the names in `ROOT/standard/v1/schema/` |
| `sdist-contents` | the archive is not rooted at `ext_r2c-V/`; its `PKG-INFO` version is not V; it holds an `examples/` folder; `standard/v1/schema` is missing; a member is neither a plain file nor a folder (a symbolic or hard link, a device); a file member is not UTF-8 (the scan cannot read it) |

The release's tag equals the version by `preflight` (check 4), and the version is the wheel's by
`wheel-metadata`; there is no separate tag argument. Prints `content ok: V`.

## `scan.py`

```text
scan.py FILE [FILE ...]
```

For each wheel (`.whl`, zip) or sdist (`.tar.gz`), every member that decodes as UTF-8 is read line by line
for the four categories of research R10. Prints, for each hit, `scan: <member path> <category> <n>` and,
if any, the refusal `refused [scan]: N lines in M files. Remove the text or, if it is invented, use
example.com.` Exit 1. Prints `scan ok: F files, 0 hits` otherwise. **Never prints, logs or raises a matched
line**: a test plants one hit per category and asserts none of the planted text is in the output.
*Changed after the outside review (phase 6, 2026-11-24, research R16):* a hit is found at the end of a line
or a sentence (`10.0.0.5.`, a home path with nothing after the name) and in the doubled-backslash Windows
form; the e-mail pattern bounds its local part, so a very long line is read in linear time. A planted hit
per boundary shape is a test.

## `sums.py`

```text
sums.py write --dir DIR [--summary]
sums.py check --dir DIR
```

- `write`: hashes `DIR/*.whl` and `DIR/*.tar.gz` (exactly one of each; otherwise `sums`), writes
  `DIR/SHA256SUMS` in the format of [release-assets.md](release-assets.md), and prints a table of name, size
  in bytes and SHA-256. `--summary` also writes it as a Markdown table to the file named by
  `GITHUB_STEP_SUMMARY` if that is set.
- `check`: every line of `SHA256SUMS` must match its file and the directory must hold no other `*.whl` or
  `*.tar.gz`; otherwise `sums` and the first mismatching name. A name listed twice is `sums` too, even when
  the last line is right (the list contradicts itself).

## `notes.py`

```text
notes.py --repository OWNER/NAME --out FILE [--version V] [--root PATH]
```

`V` defaults to the version in `ROOT/python/pyproject.toml`. Writes the three parts of research R11 to
`FILE`. Refuses with `notes` if `docs/known-limits.md` or
`scripts/release/status-block.md` is missing or empty, and with `changelog-section` if the section is
missing or empty. The `{{tag}}`, `{{version}}`, `{{wheel}}` and `{{address}}` placeholders are the only
substitutions; an unknown `{{...}}` left in the output is `notes`. Prints `notes ok: N bytes`.

## `publish.py`

```text
publish.py --tag TAG --repository OWNER/NAME --dir DIR --notes FILE
```

Environment: `GH_TOKEN` (the job's own token; the script reads none other). Runs `gh` only as in the table
of research R3, in that order, and uses `--repo OWNER/NAME` on every call. Expects `DIR` to hold exactly
`ext_r2c-V-py3-none-any.whl`, `ext_r2c-V.tar.gz` and `SHA256SUMS` for V = the tag without `v` (else
`unexpected-files`), and runs `sums.py`'s check on `DIR` first.

| Id | Refuses when |
|---|---|
| `version-grammar`, `prerelease-only` | the tag is not `v` and a normal-form pre-release (refused before any call) |
| `unexpected-files` | `DIR` does not hold exactly the three names, or holds anything else, a folder or a hidden file included (refused before any call) |
| `sums` | a file of `DIR` no longer equals `SHA256SUMS` (refused before any call) |
| `upload-differs` | after the upload, the files read back from the draft are not exactly the three names with the recorded SHA-256 (stops before the publishing call; the draft stays) |
| `published-differs` | a published release exists and an asset differs or is missing or is extra, or it is not marked pre-release (nothing is written) |
| `release-ambiguous` | `gh release list` shows more than one release for the tag (drafts may share a tag name); refused before any write |
| `not-a-draft` | the state read just before a write to the release no longer says draft (someone published it meanwhile); nothing more is written |
| `not-public` | after the publishing call, the state read again does not say published, pre-release, not draft |
| `gh` | a `gh` call fails (its standard error is passed on and the script stops; it makes no further call) |

The calls, in order. A new release: `list`, `create`, `list`, `upload`, `download`, `list`,
`edit --draft=false`, `list`. A leftover draft: `list`, `list`, `edit` (this run's notes), `view`, then a
`list` and a `delete-asset` for each stray, `list`, `upload`, `download`, `list`, `edit --draft=false`,
`list`. A published
release: `list`, `download`, and no write. The download goes to a clean temporary folder, never to `DIR`,
which is only read.

*Changed after the outside review (phase 6, 2026-11-24, research R16):* every write to a release that
exists (the notes, a `delete-asset`, `upload`, the publishing `edit`) is preceded by a `list` that must
still say draft, so a draft that someone publishes in the middle is not written to; the few milliseconds
between that read and the write cannot be closed with `gh`. `create` is the first write and has no release to
read before it.

A published release whose assets all equal the recorded sums is **success with no writes**. The publishing
call (`gh release edit --draft=false`) is the last call of a normal run, and the script reads the state
again after it and requires published, pre-release, not draft. **It never calls** `gh release delete`,
`gh release delete-asset` on a published release, `gh release upload` on a published release, or any call
that changes a tag.

## `verify.py`

```text
verify.py --tag TAG --repository OWNER/NAME --dir DIR [--base-url URL] [--attempts N] [--pause SECONDS]
```

Downloads `SHA256SUMS`, the wheel and the sdist from
`https://github.com/OWNER/NAME/releases/download/TAG/` with `urllib` and **no `Authorization` header** into
`DIR` (and writes nothing else there), checks both archives against the downloaded `SHA256SUMS` (it runs
`sums.py check` on `DIR`), and refuses with `public-differs` on any difference or a failed download (the
refusal names the file and the HTTP status, never what was read). A download that fails is asked again up to
`--attempts` times (default 1) with `--pause` seconds between (default 10); the workflow passes 6 and 10 so a
release that is a moment late is not a failure. `--attempts` is 1 or more and `--pause` a finite number of
0 or more (anything else is misuse, and no request is made). A body that is cut off, by an error or by
ending before its `Content-Length`, is a failed download and is asked again, not a checksum mismatch.
`--base-url` (an `http://` or `https://` address; anything else is misuse; a missing last `/` is added)
replaces the GitHub address, for the tests' local server. The tag is checked first
(`version-grammar`, `prerelease-only`), before any request. The workflow then installs the line
`ext-r2c[a2a,mcp,langgraph] @ <address>` into a clean venv and asserts `ext_r2c.__version__` equals V.

## `adopter_path.py` (in `python/tests/`, run by CI)

Not a release script and not collected by pytest. `python -I tests/adopter_path.py` from `python/`, in the
adopter's venv: asserts `pytest` is not importable, runs `python main.py --auto` in
`examples/langgraph_agent` as a subprocess on two free ports with a 120 s timeout and no
`R2C_EXAMPLE_MODEL`, asserts exit status 0 and the two replies of the example's README, prints
`adopter path: ok`. Any other outcome is a failed assertion (exit 1) with the last lines of the output.
