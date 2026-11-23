# Feature Specification: The first pre-release, a tested wheel on a GitHub release (`0.1.0a1`)

**Feature Branch**: `main` (no branch; the directory is `specs/008-release`)

**Created**: 2026-11-23

**Status**: Draft

**Input**: User description: "008-release: a first pre-release of the Python SDK for the first outside
adopter. The adopter runs two LangChain / LangGraph agents in Python that call each other, as in
`examples/langgraph_agent/`. The maintainer's direction on 2026-11-23: a CI job that builds the wheel
when a release is made, then a first alpha or beta release for that adopter to integrate. Settle the
version of the first pre-release and where it lives; a release job that builds the wheel and the sdist,
runs the whole suite against the built wheel on Python 3.11, 3.12 and 3.13, and only then attaches both
files to a GitHub release marked pre-release; no PyPI publication (the name is not reserved); how an
adopter installs; what the release notes carry; a way to try the job without publishing anything; what
is checked before a release is cut; and that the wheel carries no example and no private data. Read the
installed tooling and the repository as they are today."

## Context

Specs 001 to 007 built the standard and the SDK. Nothing yet carries them to someone outside this
repository: the wheel exists only inside CI runs and on the maintainer's disk. The first outside adopter
will run two LangChain agents in Python that call each other, which is what
[`examples/langgraph_agent/`](../../examples/langgraph_agent/README.md) shows. They need a file they can
install, from a place that does not move, with the limits written down.

### What exists today (checked 2026-11-23)

1. **The version has one home.** `python/pyproject.toml` says `version = "0.0.1"`. `ext_r2c.__version__`
   is read from the installed metadata, and `test_smoke.py` pins the two equal, so no other file needs
   the number. The classifier says `Development Status :: 2 - Pre-Alpha` and the root README says
   "pre-alpha". There is no tag, no release and no ruleset on the GitHub repository (read with `gh`), and
   the repository is public. *This spec bumps the version in one place and moves the classifier and the
   README status with it (FR-001, FR-003).*
2. **CI builds and tests, and publishes nothing.** `.github/workflows/python.yml` runs on a push to
   `main` and on a pull request. For each of Python 3.11, 3.12 and 3.13 it builds the wheel and the sdist,
   installs the wheel into a clean venv, runs the suite there, and runs four single-extra checks (core
   alone, `[a2a]`, `[mcp]`, `[langgraph]`). Each leg builds for itself, so the three legs test three
   builds, not one. Nothing is uploaded. *A release needs one build whose exact bytes are tested and
   then attached (FR-006).*
3. **The workflow token is read-only by default.** The repository's default workflow permission is
   `read` (read with `gh api`). A job that writes a release has to ask for write access by name, and
   only that job should (FR-014).
4. **The built files are small and clean today.** The wheel has 74 files, all under `ext_r2c/` or its
   metadata: no example, no test. The sdist has 173 files: the source, the tests and the v1 schemas,
   and no `examples/` folder. A scan of both for absolute local paths, private address ranges, e-mail
   addresses and token prefixes finds one line, an invented address on `example.com` in a test inside the
   sdist. *The scan must let the reserved example domains through (FR-009).*
5. **The PyPI name is free, and not ours.** `ext-r2c` is not reserved (the maintainer chose to wait on
   2026-11-20, and on 2026-11-23 agreed to attach the wheel to a GitHub release instead) and PyPI
   answered `404` for it on 2026-11-23. Anyone may register it. A plain `pip install ext-r2c` would then fetch someone else's package. *Everything an adopter
   reads therefore gives a full address, never the bare name (FR-018).*
6. **A requirement by address, with extras, installs a pre-release with no flag.** A wheel built from a
   scratch copy with version `0.1.0a1` was installed by `pip` and checked by `uv` as
   `ext-r2c[a2a,mcp,langgraph] @ <address of the wheel>` (a local file address stood in for the release
   address), with no `--pre`; the file is named `ext_r2c-0.1.0a1-py3-none-any.whl`. A range,
   `ext-r2c>=0.1`, finds nothing, because it skips pre-releases. *So the install line is an address, and
   no version range works (D3).*
7. **The limits are written, but in three places.** *What this example does not do*
   ([`examples/langgraph_agent/README.md`](../../examples/langgraph_agent/README.md)), the *Durable state*,
   *Identity* and *The host guard* paragraphs of [`python/README.md`](../../python/README.md), and "Not
   done on purpose" in `WORKSTATE.md`. An adopter should not have to assemble them (FR-015).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The adopter installs the first pre-release with one line (Priority: P1)

The adopter's engineer has a Python project that runs two LangChain agents. They read the release page,
copy one install line into their requirements file, install, and run the example from the tagged source.
They know it is an alpha, and which limits to expect, before they write any code.

**Why this priority**: this is the whole point. Everything else in this spec only makes that moment safe
and repeatable.

**Independent Test**: in a clean venv on a machine with no checkout, install from the line the README
gives; check `ext_r2c.__version__`; take the tagged source's `examples/langgraph_agent/` and run
`python main.py --auto`. Before a real release exists the same is done with the dry run's files and a
local file address.

**Acceptance Scenarios**:

1. **Given** a published release `v0.1.0a1`, **When** one line
   `ext-r2c[a2a,mcp,langgraph] @ <release asset address>` is installed in a clean venv, **Then** it
   installs with no `--pre` flag, `ext_r2c.__version__` is `0.1.0a1`, and `from ext_r2c import Remote`
   works.
2. **Given** that install and the tagged source's example, **When** `python main.py --auto` runs,
   **Then** both conversations end as the example's README says.
3. **Given** the release page, **When** the engineer reads it, **Then** it says: this is an alpha, v1 of
   the standard is a draft, the package version and the standard's version are separate, and the
   limits (FR-015).

---

### User Story 2 - The maintainer cuts a release with one tag, and nothing is public until it is proven (Priority: P1)

The maintainer prepares the version and the changelog in a commit, pushes one tag, and walks away. The
job builds once, tests those exact files on every supported Python, checks them, and only then makes the
release public with those exact files.

**Why this priority**: a half-published or untested release is worse than none: the adopter installs it.

**Independent Test**: the manual run (Story 4) runs every gate and none of the publishing; a run made red
on purpose, once per kind of gate, on a scratch branch shows nothing public appears. The publishing steps
themselves run for real once, at the first release (D11).

**Acceptance Scenarios**:

1. **Given** a commit on `main` whose version is `0.1.0a1`, with a changelog section for it, **When** the
   tag `v0.1.0a1` is pushed, **Then** a pre-release `v0.1.0a1` appears with the wheel, the sdist and a
   checksum list, and the SHA-256 of each file equals the one recorded before the tests ran.
2. **Given** one Python leg fails, **When** the run ends, **Then** there is no public release and no
   public file, and the run says which leg failed.
3. **Given** the files upload but one differs from what was tested, **When** the job compares them,
   **Then** it stops before publishing.

---

### User Story 3 - A release that must not happen is refused, and says why (Priority: P1)

A tag that does not match the version, a version with no changelog entry, a tag on a commit that is not
on `main`, a version that is not a pre-release, a tag that already has a published release, or a built
file that carries a private-looking line: each stops the run before anything is public, with a message
that names the check and what to change.

**Why this priority**: the repository is public and every release is permanent for an adopter who has
installed it (principle VI). The checks are cheap; the mistakes are not.

**Independent Test**: each refusal is a test of the script that makes it, on a fixture (a version, a
changelog, a tag name, a built file), runnable on a laptop with no GitHub.

**Acceptance Scenarios**:

1. **Given** tag `v0.1.0a2` and version `0.1.0a1`, **When** the pre-flight runs, **Then** it fails
   naming both, and nothing is built.
2. **Given** a version `0.1.0` with no `a`, `b` or `rc`, **When** the pre-flight runs, **Then** it
   refuses: this job releases pre-releases only (D4).
3. **Given** a built wheel with a line holding a home-directory path, **When** the scan runs, **Then**
   it fails, names the file and the number of lines, and prints no text of any matched line.
4. **Given** a published release for `v0.1.0a1`, **When** the same tag is pushed again, **Then** the job
   refuses to touch it; a mistake is fixed by `a2`, never by replacing `a1` (FR-012).

---

### User Story 4 - The maintainer tries the whole job without publishing (Priority: P2)

Before the first real release, and after any change to the release job, the maintainer starts the job by
hand. It runs everything a release runs and stops before the part that makes anything public.

**Why this priority**: the first real run of a publishing job should not be its first run.

**Independent Test**: start it by hand; the list of tags and of releases is the same before and after;
the run's log shows the file names, sizes and checksums it would have attached.

**Acceptance Scenarios**:

1. **Given** the tree on any branch, **When** the manual run starts, **Then** pre-flight, build, tests on
   3.11, 3.12 and 3.13, content check and scan all run, the files and their checksums are listed, and no
   tag, no release and no repository change is made.
2. **Given** a change that breaks a gate, **When** the manual run starts, **Then** it fails the same way a
   real run would.

---

### User Story 5 - The release notes are the repository's words, not typed that day (Priority: P2)

The notes of a release are assembled from files in the repository: a short status block, the known
limits, and the changelog section for that version.

**Why this priority**: notes typed at release time drift, and an alpha's honesty is its limits.

**Independent Test**: a test builds the notes for `0.1.0a1` from the repository and checks the three
parts, in order; it fails if the changelog section is missing or empty.

**Acceptance Scenarios**:

1. **Given** the repository at the tag, **When** the notes are assembled, **Then** they hold the status
   block, the known limits and the section for exactly that version.
2. **Given** a changelog whose section for the version is empty, **When** the notes are assembled,
   **Then** it fails (this is also a pre-flight refusal).

---

### Edge Cases

- A tag written another way for the same version (`v0.1.0-alpha.1`): refused. The tag is `v` plus the
  version exactly as `pyproject.toml` writes it, and the asset's file name follows the normal form of the
  version, so the address an adopter copies is predictable.
- The tag points at a commit that is not on `main`: refused.
- A leg of the matrix is flaky and fails once: the run fails and publishes nothing; the maintainer reruns
  it. No automatic retry that could hide a real failure.
- The upload partly succeeds and then fails: what exists is a draft, invisible to the public; a rerun
  replaces the draft's files. Nothing is published until every file is verified.
- A run for a tag whose release is already published: refused, never "updated".
- The job's log and artifacts are public (public repository): no secret, private token or matched line
  may reach them, so the scan prints only a file name and a count.
- The scan hits an invented address on a reserved example domain (as one test already has): not a hit.
- The sdist is not tested by itself (its tests need the repository's `standard/` and `examples/`). The
  wheel is the tested artifact (principle VII); the sdist is attached as the source of that wheel.
- A fork pushes a tag: its token has no write access to this repository, and no release appears here.
- The adopter's tool refuses a pre-release it was not asked for: not here, because an exact address is
  asked for by name; a range such as `ext-r2c>=0.1` would skip it, which is why the install line is an
  address.

## Requirements *(mandatory)*

### Functional Requirements

**The version and what a release is**

- **FR-001**: The first pre-release MUST be `0.1.0a1` (D1). The version MUST be written once, in
  `python/pyproject.toml`; the wheel's and the sdist's file names, their metadata and
  `ext_r2c.__version__` follow it.
- **FR-002**: A release's tag MUST be `v` plus the package version, exactly. This job MUST release only
  PEP 440 pre-release versions (`aN`, `bN`, `rcN`) and refuse a final version (D4).
- **FR-003**: In the commit that sets `0.1.0a1`, the `Development Status` classifier MUST become
  `3 - Alpha`, the root README's status paragraph MUST say alpha, and the changelog's `Unreleased`
  section MUST become `[0.1.0a1] - <date>` with a fresh empty `Unreleased` above it.

**Before anything is built (pre-flight)**

- **FR-004**: The job MUST refuse, before building, unless all of these hold: the tag equals `v` plus the
  version; the version is a pre-release; the changelog has a non-empty section for the version with a
  date; the tagged commit is reachable from `main`; no published release exists for the tag;
  `python/LICENSE` equals the root `LICENSE`.
- **FR-005**: Every refusal MUST name the check that failed and what to change, and MUST create
  nothing.

**Build once, test those bytes, attach those bytes**

- **FR-006**: The wheel and the sdist MUST be built once per run. Their SHA-256 MUST be recorded before
  any test, and the files tested and the files attached MUST be the same bytes, shown by the recorded
  sums.
- **FR-007**: Against the built wheel, in a clean venv, on Python 3.11, 3.12 and 3.13, the job MUST run
  every check CI runs on a push: the whole suite and the four single-extra checks. These checks MUST be
  defined once, so the release's gate and CI's gate cannot drift apart.
- **FR-008**: The job MUST also prove the adopter's path: a clean venv with only the wheel, its extras
  `[a2a,mcp,langgraph]` and the server the example names (no dev group) MUST run the example's
  `python main.py --auto` from the tagged source and end both conversations as the README says. This
  check MUST be added to CI's definition (FR-007), so it holds on every push.
- **FR-009**: The job MUST check the built files' content: the wheel holds only `ext_r2c/` and its
  metadata (no `examples/`, no tests); the schemas are inside it; its metadata version equals the tag's
  version. It MUST scan every text file of the wheel and the sdist for absolute local paths, private
  address ranges, e-mail addresses (reserved example domains allowed) and token prefixes. A hit MUST fail
  the run and MUST print the file and the count only, never the matched text.

**Make it public, and only then**

- **FR-010**: Only when every gate has passed, the job MUST create the GitHub release for the tag, marked
  pre-release and not "latest", with the wheel, the sdist and a checksum list as its assets and the
  notes of FR-016.
- **FR-011**: The files MUST be uploaded to a draft, downloaded back and compared by SHA-256 with the
  tested files, and only then published. A run that fails at any step MUST leave no public release and no
  public file.
- **FR-012**: A published release's files MUST never be replaced or removed by this job. A mistake in a
  published pre-release is fixed by the next number (`a2`).
- **FR-013**: After publishing, a separate read-only job MUST download the wheel from its public
  address with no credentials, install it with the extras in a clean venv, and check
  `ext_r2c.__version__`. If this fails the run MUST be red and say so; the job MUST NOT delete the
  release (the maintainer decides).

**Permissions**

- **FR-014**: The build, test and scan jobs MUST run with read-only permission. Exactly one job (the
  one that publishes; GitHub gives permission to a job, not to a step) MUST hold write permission, and it
  MUST run no code from the built files (it does not install or import the wheel). The job MUST run only on a pushed version tag and on a manual start, never on a pull request.
  It MUST use no credential but the workflow's own token, and it MUST NOT read or issue PyPI
  credentials.

**What the adopter reads**

- **FR-015**: The known limits MUST be one short section in the repository, linked from both READMEs
  and quoted whole in every release's notes (D8). For `0.1.0a1` it says: the state a restart loses
  (checkpointer, task store, request-state keys) is in memory unless the owner brings a durable one; no
  authentication, identity belongs to the deployment; the MCP door answers only loopback hosts until the
  public host is named; no relay of a question through more than one hop, and no guard against agents
  calling each other's agents; MCP Tasks is not supported; the package is not on PyPI; v1 is a draft and
  names may change.
- **FR-016**: A release's notes MUST be assembled by a script in the repository from three parts, in this
  order: a status block (alpha; v1 is a draft until the first outside adopter, principle IX; the
  package's SemVer is separate from the standard's version; the install line), the known limits, and the
  changelog section for exactly that version. Nothing is typed at release time.
- **FR-017**: A new document, `docs/releasing.md`, MUST list the maintainer's steps: the version and
  changelog commit, the private-token scan of the built files on the maintainer's own machine (D5), the
  manual run, the tag, what to read afterwards, and what to do when a run fails or a published release
  must be withdrawn. `AGENTS.md` MUST link it.
- **FR-018**: Both READMEs MUST show one install line for the current pre-release, as an address with
  the extras `[a2a,mcp,langgraph]`, and MUST say that the bare name `ext-r2c` on PyPI is not this
  project until it is published here (D3). A test MUST check that the address in the README names the
  wheel the build produces for the current version.

**The manual run**

- **FR-019**: A manual start MUST run the checks of FR-004 that do not need a tag (the version is a
  pre-release, the changelog section, the license copy), FR-006 to FR-009 and the assembly of the notes,
  list the files, sizes and checksums, and then stop. The checks that need a tag (the tag equals the
  version, the tagged commit is on `main`, no published release exists) run only on a real start. A
  manual start MUST create no tag, no release, no asset and no commit. It MUST be the same job as the real one with
  the publishing steps skipped, not a copy of it.

### Key Entities

- **Release**: a tag `vX.YaN`, a GitHub pre-release with notes and three assets. Public only after every
  gate, and permanent once public.
- **Asset**: the wheel, the sdist, or the checksum list; each tested and attached as the same bytes.
- **Gate**: one check that can stop a run: a pre-flight check, a Python leg, the adopter's-path check,
  the content check, the scan, the upload verification.
- **Run**: one start of the job, real (a tag) or manual (publishes nothing).
- **Known limits**: the one section that says what an alpha does not do.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a clean venv with no checkout, one requirement line by address with the three extras
  installs the files of a dry run (before a real release) or of the release (after it), with no
  `--pre`; `ext_r2c.__version__` equals `0.1.0a1`; the example from the tagged source ends both
  conversations as its README says.
- **SC-002**: For each kind of gate (tag and version differ, no changelog section, not on `main`, not a
  pre-release, a published release exists, a hit in the scan, a wrong content, an upload that differs, a
  failing Python leg) there is a refusal or a red run and 0 public releases and 0 public files. The
  script gates are each a test on a fixture; the wiring is shown by a manual run that is green and by one
  made red on purpose per gate on a scratch branch.
- **SC-003**: The SHA-256 of every attached file equals the one recorded before the tests (shown in the
  log and in the checksum list).
- **SC-004**: After a manual run the list of tags, the list of releases and the repository's commits are
  the same as before.
- **SC-005**: A test reads the workflow file and finds: no pull-request trigger; write permission on
  exactly one job; that job installs and imports nothing from the built files; no secret named.
- **SC-006**: The scan finds 0 hits on the current build of the wheel and of the sdist, and finds a
  planted home-directory path and a planted private address in fixtures, printing no matched text.
- **SC-007**: The wheel's file list equals `ext_r2c/` plus its metadata; it holds no `examples/` and no
  test.
- **SC-008**: The notes for `0.1.0a1`, built from the repository, hold the three parts in order and the
  changelog part is not empty; the assembly fails on an empty one.
- **SC-009**: An outside reader who has only the README and the release notes can say what to type to
  install, that the bare PyPI name is not this project, and the limits of FR-015 (checked once, as
  SC-012 of the earlier specs were).
- **SC-010**: CI is unchanged in what it proves: the full suite passes on the installed wheel on Python
  3.11, 3.12 and 3.13, every replay is unchanged, nothing under `python/src/` and nothing under
  `standard/` is changed by this spec.
- **SC-011**: A test finds `docs/releasing.md` with every step of FR-017, `AGENTS.md` linking it, both
  READMEs linking `docs/known-limits.md`, and the install address in both READMEs naming the wheel of the
  current version (FR-018).

## Assumptions

**Out of scope:** publishing to PyPI and reserving the name (D3); signing, attestation or provenance of
the files (a later step, GitHub offers it); releasing a final version such as `1.0.0` (D4); a different
platform's test legs (Linux only, as CI today); automatic version bumps or a generated changelog; a
container image or a conda package; a documentation site; any change under `python/src/` or `standard/`;
the TypeScript SDK; pushing the first tag (the maintainer's own act, and a separate go).

- The repository stays public, on GitHub Actions, with the default token read-only; the job asks for
  write permission by name where it needs it and changes no repository setting.
- The adopter reaches `github.com` release files without credentials (public repository).
- The maintainer pushes the tag. The first tag is not pushed by this spec's work: the spec's last phase
  ends with the commit that sets `0.1.0a1`, a manual run, and a report; the tag waits for the maintainer's
  go.
- The existing CI (`python.yml`) keeps its triggers and its checks; the plan finds the seam that lets the
  release reuse them (the release builds once; CI builds per leg).
- The scripts of this spec (pre-flight, content check, scan, notes) live in the repository outside the
  wheel, are plain Python with their own tests beside the others, and read nothing but the repository and
  the built files.
- The release job runs on Linux with Python 3.11, 3.12 and 3.13, as CI does.
- The suite has no network and no keys; the example runs with its scripted model.

### Decisions taken in this draft

Each has a default, so the plan can start; the maintainer can overrule any of them at the gate. D3, D5 and
D11 are the three the maintainer is asked about first: a risk the project carries, where private words may
live, and the one part of the job that no run proves before the first release.

- **D1. The first version is `0.1.0a1`: an alpha, not a beta.** *Example:* the adopter wires two agents
  and finds that `Remote`'s constructor wants one more argument; with `a1` that is expected, with `b1`
  it would read as a broken promise. *Why:* principle IX keeps v1 a draft until an outside remote adopts
  it, and a beta says "feature complete, shape settled". `0.1.0` rather than `0.0.2` says the SDK has
  its specs 001 to 007 behind it. *Alternatives:* `0.0.2a1` (reads as a patch of the skeleton);
  `0.1.0b1` (promises a settled shape). *Consequence:* the next numbers are `a2`, `a3`, then a `b` when
  the adopter's integration has not asked for a change in a while.
- **D2. A pushed tag starts the job, and the job creates the release.** *Example:* the maintainer
  pushes `v0.1.0a1`; the run builds, tests and publishes. *Why:* with "the release is made in the web
  page, then the job attaches files", the release is public, with no files, before a single test ran, and
  a red run leaves a public release that installs nothing. *Alternative:* start on "release published".
  Rejected for that reason. *Consequence:* a failed run leaves an unpublished tag; the maintainer deletes
  it, fixes, and pushes it again, or takes the next number. A tag whose release was published is never
  reused (FR-012).
- **D3. No PyPI in this spec; the adopter installs from the release's file address.** *Example:* the
  adopter's `requirements.txt` has
  `ext-r2c[a2a,mcp,langgraph] @ https://github.com/timezlab/ext-r2c/releases/download/v0.1.0a1/ext_r2c-0.1.0a1-py3-none-any.whl`.
  *Why:* the maintainer chose to wait on the name (2026-11-20) and agreed to the release-file route on
  2026-11-23; a file on a release needs no name and no account. *Risk the project carries:* PyPI answers `404` for `ext-r2c`, so anyone may
  register it, and a bare `pip install ext-r2c` would fetch their package; the install line is the whole
  defence, which is why FR-018 says it in both READMEs and the notes say it again. *Alternative:*
  reserve the name now by publishing `0.1.0a1` to PyPI with trusted publishing: it closes the risk,
  costs a decision about the name (and the name is then permanent), and is its own spec. *Consequence:*
  no version range works (`>=0.1` finds nothing); an adopter pins the address and changes it per
  release. Reconsider when a second adopter appears, or if the name is taken.
- **D4. This job releases pre-releases only.** *Example:* a tag `v0.1.0` is refused with "a final
  release needs its own decision". *Why:* a final release means "latest", a PyPI decision and a promise;
  none of those is made. *Alternative:* handle both. Rejected: it builds a path nobody has reasoned
  about, in a job that holds write permission.
- **D5. The scan's pattern is generic and public; the maintainer's private pattern stays on the
  maintainer's machine.** *Example:* the job knows to refuse a home-directory path or an address in a
  private range; it does not know the names of any private organisation, and the runbook has the
  maintainer run their own scan over the built files before tagging. *Why:* the private words must not
  be in a public repository (principle VI), and putting them in an Actions secret moves them to a service
  and a public log that can echo a hit. Every line in the wheel was also scanned at the commit that added
  it. *Alternative:* the pattern as an Actions secret. Rejected as the default; possible later, and the
  scan already prints no matched text. *Consequence:* the CI gate cannot know whether the maintainer's
  scan ran; the runbook's step is a promise, not a gate.
- **D6. One definition of the checks, not a copy.** *Example:* a fifth single-extra check is added to
  CI; the next release runs it with no edit to the release job. *Why:* the release's whole value is that
  it proves what CI proves, on the exact files it attaches. *Alternative:* copy CI's steps into the
  release job. Rejected: the copies drift, and the release job (the one with write access) is the worse
  place to find out. The plan finds the seam (the release builds once; CI builds per leg).
- **D7. A draft first, then public.** *Example:* the release exists as a draft while its files upload and
  are compared; publishing is the last call. *Why:* FR-011: a run that fails midway leaves nothing the
  public can see. *Alternative:* create the public release, then upload. Rejected: a window with a public
  release that has no files, or half of them.
- **D8. The known limits are one file, `docs/known-limits.md`.** *Why:* the notes quote the whole file
  and both READMEs link it; one place cannot disagree with itself. *Alternative:* a section of
  `python/README.md` cut out by heading by the script. Rejected: it breaks when someone renames the
  heading. The paragraphs in `python/README.md` stay as the detail; the file is the short list that
  points at them.
- **D9. The notes are assembled by a script from the repository, not generated from commits.**
  *Example:* the notes are the status block, the limits and the `[0.1.0a1]` section. *Why:* GitHub's
  generated notes list 90-odd commits of specs and fixes, which tells an adopter nothing. *Alternative:*
  generated notes. Rejected.
- **D10. A checksum list is an asset.** *Why:* an adopter that pins a hash, or checks a download, has
  something to compare; and it is how FR-006 is shown to a reader. *Alternative:* none; the log holds
  the sums. Rejected: the log is not a place an adopter looks.
- **D11. The publishing steps are not rehearsed; the manual run stops before them.** *Example:* the
  first time the job creates a draft, uploads, downloads back and publishes is the first real release.
  *Why:* FR-019 and SC-004 keep the manual run free of any write (no draft either), and D7 means a failure
  in those steps leaves nothing public; the runbook asks the maintainer to read the release page right
  after the run (FR-017). *Alternative:* let the manual run create a draft on a throwaway name, compare,
  and delete it. It would rehearse the part that matters most, at the price of a write permission on
  manual starts and a release object that exists for a minute; invisible to the public, but not nothing.
  *Consequence:* if the first real run fails in the publishing jobs, nothing is public (D7), so the
  maintainer fixes the workflow, deletes the unpublished tag and pushes it again (D2); a number is burned
  only by a published release. Say so if you prefer the rehearsal.
