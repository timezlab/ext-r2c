# Contract: the workflows

**Plan**: [../plan.md](../plan.md) | **Research**: [../research.md](../research.md) R1, R2, R6, R7

This describes the shape the workflow tests (SC-005) enforce. It is not the YAML. Actions are pinned by the
SHAs of research R6; `runs-on` is `ubuntu-24.04` everywhere.

## Rules for every workflow file

1. Top-level `permissions: contents: read`; a job may widen it only where this contract says.
2. Every `uses:` is `owner/name@<40 hex>` with `# vX.Y.Z` after it, or a local `./.github/workflows/...`.
3. Every `actions/checkout` sets `persist-credentials: false`. Every `astral-sh/setup-uv` sets
   `enable-cache: false`.
4. No `${{ ... }}` in any `run:`; values reach a script through `env:` and are read as `"$NAME"`.
5. No `secrets` context and no `secrets: inherit`. No `id-token`, no `packages`.
6. No `pull_request_target`, no `workflow_run`.
7. Every workflow and job has a `name:`.
8. The checks live only in `wheel.yml`: `python.yml` and `release.yml` contain no `uv build`, no `pytest`
   and no `tests/*_only.py` step.
9. *(Added after the outside review, phase 6, 2026-11-24, research R16.)* Every job that runs steps has
   `timeout-minutes`, between 1 and 60: `build` 15, `checks` 30, `inspect` 15 in `wheel.yml`; `preflight` 15,
   `publish` 15, `verify` 20 in `release.yml`. A job that only calls a workflow (`wheel` in `release.yml`, `wheel` in
   `python.yml`) has none, because GitHub refuses the key there: its limits are the jobs inside `wheel.yml`.

## `wheel.yml` (reusable)

`on: workflow_call` with no inputs, no secrets, no outputs.

| Job | Needs | Steps (in order) | Artifacts |
|---|---|---|---|
| `build` | none | checkout; setup-uv; `cmp LICENSE ../LICENSE`; `uv build`; `python3 ../scripts/release/sums.py write --dir dist --summary`; upload | uploads `dist` = `python/dist/*.whl`, `python/dist/*.tar.gz`, `python/dist/SHA256SUMS`, `if-no-files-found: error`, 14 days |
| `checks` | `build` | matrix `python: ["3.11", "3.12", "3.13"]`, `fail-fast: false`; checkout; setup-uv; download `dist` into `python/dist`; `sums.py check --dir dist`; venv + wheel + `--group dev`, then `pytest`; the four single-extra checks as today (`core_only.py`, `a2a_only.py`, `mcp_only.py`, `langgraph_only.py`); the adopter's path: venv, wheel with `[a2a,mcp,langgraph]` plus `uvicorn`, `python -I tests/adopter_path.py` | none |
| `inspect` | `build` | checkout; download `dist`; `sums.py check`; `content.py --dir dist` (the version comes from `pyproject.toml`, read by the script); `scan.py dist/*.whl dist/*.tar.gz` | none |

`defaults.run.working-directory: python` as today. The legs install the **downloaded** wheel; no job but
`build` runs `uv build`.

## `python.yml` (CI)

Triggers as today: `push` to `main`, `pull_request`. One job, `wheel`, `uses: ./.github/workflows/wheel.yml`,
`permissions: contents: read`. Nothing else.

## `release.yml`

Triggers: `push: tags: ["v*"]` and `workflow_dispatch:` (no inputs). `concurrency: group: release-<ref>`,
`cancel-in-progress: false`.

| Job | Needs | `if` | `permissions` | Steps |
|---|---|---|---|---|
| `preflight` | none | | `contents: read` | checkout (`fetch-depth: 0`); `preflight.py --event "$EVENT" --ref-type "$REF_TYPE" --tag "$TAG" --sha "$SHA" --repository "$REPOSITORY"` with `GH_TOKEN: ${{ github.token }}`; `notes.py --repository "$REPOSITORY" --out release-notes/RELEASE_NOTES.md`; write the notes to the step summary; upload `release-notes` |
| `wheel` | `preflight` | | `contents: read` | `uses: ./.github/workflows/wheel.yml` |
| `publish` | `preflight`, `wheel` | `github.event_name == 'push'` | **`contents: write`** | checkout (no credentials); download `dist` and `release-notes`; `publish.py --tag "$TAG" --repository "$REPOSITORY" --dir dist --notes release-notes/RELEASE_NOTES.md` with `GH_TOKEN: ${{ github.token }}` |
| `verify` | `publish` | `github.event_name == 'push'` | `contents: read` | checkout (no credentials); setup-uv; `verify.py --tag "$TAG" --repository "$REPOSITORY" --dir public`; `uv venv`; `uv pip install "ext-r2c[a2a,mcp,langgraph] @ $ADDRESS"`; `python -c` asserts `ext_r2c.__version__` and `from ext_r2c import Remote`. No `GH_TOKEN` |

**The one writer.** `publish` is the only job with `contents: write`. Its steps are `checkout`, two
`download-artifact` and the `publish.py` step; it has no setup-uv, no `pip`, no `uv`, no `python -m`, no
`python -c` and no install. It never imports or runs a file from `dist`.

**Environment values** (`env:` of the step that uses them): `EVENT: ${{ github.event_name }}`,
`REF_TYPE: ${{ github.ref_type }}`, `TAG: ${{ github.ref_name }}` (a real run only), `SHA: ${{ github.sha }}`,
`REPOSITORY: ${{ github.repository }}`.

**What a manual start does**: `preflight` (tag-free checks), the notes, `wheel` in full; `publish` and
`verify` are skipped. The `build` job's summary lists the files, sizes and sums.

## What the workflow tests assert (SC-005 and the rules above)

- `release.yml` has no `pull_request` trigger and its triggers are exactly a tag push and a manual start.
- Exactly one job of `release.yml` has `contents: write`; its steps hold none of `setup-uv`, `pip`, `uv`,
  `python -m`, `python -c`, `import`, an `install`, or a path under `dist` passed to an interpreter.
- No `secrets` appears in any workflow file.
- Every rule of the first list above holds for every file under `.github/workflows/`.
- `python.yml` and `release.yml` both call `wheel.yml` and hold none of the build and test steps.
- `wheel.yml` holds the four single-extra checks, the adopter's path, `sums.py`, `content.py`, `scan.py`.
- The matrix of Python versions appears only in `wheel.yml`.
