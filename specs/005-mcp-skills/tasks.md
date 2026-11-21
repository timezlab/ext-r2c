---
description: "Task list for 005-mcp-skills"
---

# Tasks: MCP Skills (`ext_r2c.mcp` skills extension)

**Input**: design documents in `specs/005-mcp-skills/` ([plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md))

**Tests**: required. Constitution VII asks for tests first, run against the installed wheel,
with the extension tested by real round trips. In every phase:
1. write the phase's tests first;
2. run them and confirm they fail for the expected reason;
3. only then write production code.

If a test passes on its first run, say so in the phase's report and prove it is not vacuous by a
**mutation check**: break the line of production code it guards, watch the test fail, restore.

**Organization**: the nine phases of the plan's delivery order. `/speckit-implement` runs **one
phase per go**: finish the phase, verify, commit, report, stop.
- Phases 1 and 2 have no story label. They are the setup and the foundation every story uses.
- The stories follow the spec's priorities: US1 → US2 → US3 (all P1), US4 → US5 (P2), US6 (P3).
- Phase 3 builds **first cuts** of the scan and the read on purpose (plan, "Order"); phase 5
  replaces them, test first.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US6 from spec.md
- **Verify** (end of every phase), from `python/`:
  1. `rm -rf dist && uv build`;
  2. recreate `../.ci-venv`, install the wheel and the `dev` group (Python 3.11);
  3. `../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider` (the whole suite: the
     tests of specs 001–004 must still pass unchanged);
  4. `../.core-venv` with the wheel alone: `python -I tests/core_only.py`;
  5. `../.a2a-venv` with `wheel[a2a]`: `python -I tests/a2a_only.py`;
  6. `../.mcp-venv` with `wheel[mcp]`: `python -I tests/mcp_only.py`;
  7. `uvx ruff check --select F src tests`;
  8. leak-scan the staged added lines (must be 0);
  9. commit with an explicit pathspec and no co-author trailer.

## Path conventions

- Package: `python/src/ext_r2c/mcp/skills/`; tests: `python/tests/`
- `SKILLS_ID` means `io.modelcontextprotocol/skills`.
- A *fixture tree* is the three-skill tree of T004 (`standard_tree`).
- Test modules may import the package's private modules (`ext_r2c.mcp.skills._wire`, …): they
  test the installed wheel.
- All fixture content is invented (constitution VI): names like `refunds`, `pdf-notes`,
  `greetings`; no real people, hosts or local paths; `example.com` only.

---

## Phase 1: Packaging, vet and spike

**Goal**:
- PyYAML is vetted again on the day it is added, and sits in `[mcp]` and the dev group.
- `ext_r2c/mcp/skills/` exists, is scanned by the import rules, and imports nothing of `ext_r2c`.
- The tests have fixture folders.
- The SDK facts the design leans on are pinned by tests.

**Independent test**: `test_packaging.py`; `core_only.py`, `mcp_only.py`; `test_skills_spike.py`.

- [ ] T001 Repeat the PyYAML vet with the `security-audit` skill, on the day the dependency is
  added, and write the result under R7 of `specs/005-mcp-skills/research.md` ("Vet repeated on
  <date> by T001"):
  - OSV query for `PyYAML` (`MAL-` advisories: must be none) and the advisories that apply to
    the range;
  - upload dates of 6.0.3 and 6.0.4 (6.0.4 was uploaded 2026-11-20), yanked files, wheels for
    CPython 3.11, 3.12, 3.13 on Linux, macOS and Windows, empty `requires_dist`, no install script;
  - **stop and tell the maintainer** if a `MAL-` advisory, a yanked release, a changed
    maintainer or a changed dependency list shows up. If the maintainer chose `<6.0.4`, use that
    bound in T007 instead of `<7`.
- [ ] T002 [P] Extend `python/tests/test_packaging.py` (test first):
  - **`test_extras`**: the `mcp` extra now has two requirements, `mcp` with `>=2.3,<3` and
    `PyYAML` with `>=6.0.3,<7` (the current `len(mcp) == 1` assertion changes).
  - **`_imports`** walks sub-folders, so `ext_r2c/mcp/skills/` is scanned by
    `test_mcp_imports_only_allowed_modules`; `MCP_ALLOWED_TOP_LEVEL` gains `yaml`. Core and A2A
    have no sub-folders, so their scans do not change.
  - **`test_mcp_skills_imports_no_ext_r2c`**: every file in the installed `ext_r2c/mcp/skills/`
    imports nothing from `ext_r2c` (absolute) and uses no relative import that climbs out of
    the package (level 2 or more); `from . import x` and `from ._wire import y` are fine.
    The test asserts the folder exists (`ext_r2c/mcp/skills is not in the installed wheel`).
  - **`test_core_import_loads_no_yaml`**: a subprocess (`python -I`) that imports `ext_r2c` and
    `ext_r2c.core` has no `yaml` module in `sys.modules`.
- [ ] T003 [P] Extend the two scripts pytest does not collect:
  - `python/tests/core_only.py`: after importing `ext_r2c.core`, assert `yaml` is not loaded.
  - `python/tests/mcp_only.py`: add `import ext_r2c.mcp.skills` and `import yaml` to the import
    check, and leave a `# phase 7:` comment where the skills round trip goes (T059).
- [ ] T004 [P] Create `python/tests/skills_fixtures.py`, invented content only:
  - `write_skill(root, path, *, description="Does one thing.", extra="", body="Steps.\n",
    files=None) -> Path`: writes `<root>/<path>/SKILL.md` with frontmatter `name` (the last
    segment of `path`), `description` and the YAML text `extra` (the caller controls the exact
    YAML), then the body; `files` maps a relative path to `bytes` or `str` and is written below
    the skill folder.
  - `standard_tree(tmp_path) -> Fixture` builds `<tmp_path>/skills` with the SC-001 tree:
    - `team/billing/refunds`: `extra` has `license: MIT` and a nested `metadata:` mapping;
      files `templates/reply.md`, `notes.txt`, and `examples/SKILL.md` (a nested `SKILL.md`,
      which is an ordinary file of `refunds`);
    - `pdf-notes`: `assets/logo.bin` (bytes with `\x00`, `\xff`, `\xfe`), `scripts/run.sh`,
      `reference.md`;
    - `greetings`: UTF-8 text with non-ASCII characters, a file named `café.md`, `legacy.txt`
      holding Latin-1 bytes (`b"caf\xe9"`), and `windows.txt` with a byte-order mark and CRLF.
    - `Fixture` has `root`, `names` and `expected()`, which returns `{uri: bytes}` computed
      **independently** (walk the tree, percent-encode with `urllib.parse.quote(seg, safe="")`),
      never with package code.
  - `outside_secret(tmp_path) -> Path`: a file outside the root with known bytes
    (`b"not for callers\n"`), so a leak would show.
  - `add_symlink(...)`, `add_fifo(...)`: create the thing or `pytest.skip` with the reason when
    the platform cannot.
  - `many_skills(root, n)`: `n` skills named `skill-001`…, each with `SKILL.md` only.
  - `snapshot(root)`: `{relative path: (size, mtime_ns)}` of a tree, to prove nothing was written.
- [ ] T005 [P] Write `python/tests/test_skills_spike.py`. Each test pins one SDK fact the design
  leans on, with a throwaway `Extension` subclass and the harness (`serve`, `mcp_client` with
  `active=False`, `run`); a failing one stops the phase and updates research and plan first.
  1. `test_extension_binds_new_methods_and_declares_settings`: `MethodBinding` for `skills/list`,
     `skills/get` and `resources/directory/read` is accepted; `settings()` appears at
     `capabilities.extensions[SKILLS_ID]`; one registered resource declares `resources` (R1).
  2. `test_resources_are_read_once_and_cannot_be_removed`: `resources()` is read at construction;
     `MCPServer.add_resource` adds one later; there is no removal API (R1, R5).
  3. `test_typed_result_carries_cache_fields`: a `CacheableResult` and a `PaginatedResult`
     subclass go out as `ttlMs`, `cacheScope`, `resultType`, `nextCursor` (R2).
  4. `test_untyped_request_drops_its_params`: `types.Request(method=..., params={"uri": ...})`
     reaches the server without `uri`; a typed `Request` subclass keeps it (R2).
  5. `test_resource_read_compares_raw_strings`: for a registered `skill://team/x/SKILL.md`, each
     of `..` (plain, `%2e%2e`, `.%2e`), a backslash, a query, a fragment, a trailing slash, a
     case change and an unregistered path is `-32602` and never reaches `Resource.read` (R3).
  6. `test_mcperror_in_read_keeps_its_code`: `MCPError(-32603, msg)` raised in `read()` arrives
     with code and message; any other exception arrives as a generic error without the original
     text (R4).
  7. `test_client_declares_nothing_for_the_extension`: the server sees no entry for `SKILLS_ID` in
     the client capabilities of a request (R2).
  8. `test_text_and_blob_follow_the_return_type`: `read()` returning `str` goes out as `text`,
     `bytes` as a base64 `blob`, with the resource's MIME (R4).
  9. `test_in_memory_client_carries_typed_skills_requests`: the SDK's own in-memory
     `Client(server)` (no HTTP) can send a typed `skills/list` request and parse a typed result.
     It decides how `mcp_only.py` runs its round trip in T059.
- [ ] T006 Build, install, and run T002, T003 and T005. Confirm the expected failures: the extra
  has one requirement, `ext_r2c/mcp/skills` is missing, and `yaml` is not yet a dependency. The
  spike tests pass or fail by the facts alone.
- [ ] T007 Change `python/pyproject.toml`: `mcp = ["mcp>=2.3,<3", "PyYAML>=6.0.3,<7"]` and the same
  `PyYAML` line in the `dev` group, with a comment saying the group lists what the extras bring.
- [ ] T008 Create `python/src/ext_r2c/mcp/skills/__init__.py`: a module docstring that says it is
  MCP Skills, **Beta**, written against the beta revision read on 2026-11-21 (base protocol
  2026-07-28), and that it imports nothing of `ext_r2c`; an empty `__all__`.
- [ ] T009 Run T002, T003, T005 on the wheel until green. Fix the harness, not the facts. If a
  fact does not hold, stop and update `research.md` and `plan.md` before going on. Run
  `core_only.py` and `mcp_only.py` in their venvs.
- [ ] T010 Verify, then commit `feat(005): PyYAML in [mcp], skills package skeleton, SDK spike`.

---

## Phase 2: Foundation (reader, URIs, cursor, records, wire models)

**Goal**: everything the stories share, with no server and no disk walk yet.

**Independent test**: `test_skills_frontmatter.py`, `test_skills_wire.py`,
`test_skills_catalogue.py`, all pure units on the installed wheel.

- [ ] T011 [P] Write `python/tests/test_skills_frontmatter.py` (R7). `read_frontmatter(data)`
  takes the bytes or text of a `SKILL.md` and returns the mapping, or raises `FrontmatterError`
  with a `reason` from a fixed set (no host path):
  - **keeps**: every field passes through (`license`, a nested `metadata`, `allowed-tools`, lists,
    numbers, `null`, `true`/`false`); key order is not required, content is;
  - **text stays text**: `2026-01-02` and a full timestamp are the strings the author wrote;
    `yes`, `no`, `on`, `off` are strings, so `name: no` is `"no"`;
  - **refuses**, one test each: a duplicate key; an anchor; an alias; a merge key `<<`; the tags
    `!!python/object`, `!!binary`, `!!set` and a custom `!foo`; a top level that is a list, a
    scalar or empty; a non-string key (`1: a`); `.inf` and `.nan`; nesting deeper than the cap;
    an alias bomb (a "billion laughs" document is refused for its aliases, in bounded time);
    text over 64 KiB (65,536 bytes passes, 65,537 fails); no opening `---`; an unclosed
    frontmatter; text that is not UTF-8; a YAML syntax error;
  - **shape of the document**: the frontmatter is the text between the opening `---` (after an
    optional UTF-8 byte-order mark) and the next line that is exactly `---`; CRLF is accepted;
    a `---` inside the body or inside a quoted value does not close it; the body is ignored.
- [ ] T012 [P] Write `python/tests/test_skills_wire.py`:
  - **names** (`skill_name_ok`): valid `a`, `a-b`, `a1`, a 64-character name; invalid: empty,
    65 characters, uppercase, a leading or trailing hyphen, `--`, `_`, space, `.`, `é`.
  - **URIs** (`encode_uri(segments, file=...)`): `("team", "billing", "refunds")` and
    `SKILL.md` give `skill://team/billing/refunds/SKILL.md`; each of space, `é`, `%`, `+`, `#`,
    `?`, `\` in a segment becomes `%XX`; the result is pure ASCII; `authority_key` (the first
    segment, case-folded) makes `Team` and `team` collide; `last_segments(uri, n)` returns the
    percent-decoded last `n` segments, used for "ends in `<name>/SKILL.md`".
  - **content** (`mime_for`, `as_text_or_bytes`): each extension of the table in R11 and
    `application/octet-stream` for an unknown one; the extension is compared in lower case;
    `SKILL.md` is `text/markdown`; UTF-8 that re-encodes identically is `str` (a byte-order mark
    and CRLF survive; an empty file is `""`); Latin-1 bytes, a lone `\xff` and a binary file are
    `bytes`.
  - **cursor**: `encode_cursor(generation, offset)` and `decode_cursor(cursor, generation,
    total)` round trip; each of these raises `CursorError`: not base64url, no separator, a
    non-integer or negative offset, another generation, an offset past `total`, an over-long string.
  - **wire models**: `ListSkillsResult`, `GetSkillResult` and `ReadDirectoryResult` serialise by
    alias to `skills` / `skill` / `resources`, `ttlMs`, `cacheScope`, `resultType: "complete"`,
    `nextCursor` (absent when unset); a `Skill` has `uri`, `frontmatter`, `resources` and no
    `_meta` when unset; a `SkillResource` rejects a digest that is not `sha256:` plus 64
    lowercase hex and a negative size; the typed requests keep `uri` and `cursor`. The JSON shapes
    equal the examples in `contracts/wire-mapping.md`.
- [ ] T013 [P] Write `python/tests/test_skills_catalogue.py`:
  - a catalogue built from hand-made records has exact dictionaries `by_uri`, `files`,
    `directories`; `skills` sorted by URI; a skill's files sorted by relative path;
  - one directory record per directory of every skill, the root included; its children are the
    direct children only, sorted by name, as `(uri, name, mime, is_dir)`; a prefix above two
    skills is **not** a directory; a directory URI has no trailing slash;
  - two builds have different `generation` tokens;
  - `SkillsError("folder", "reason")` is a `ValueError` with `.folder`, `.reason` and the message
    `folder: reason`; `SkillInfo` and `LeftOut` are frozen.
- [ ] T014 Build, install, and run T011–T013. Confirm the expected failures: the modules do not
  exist.
- [ ] T015 [P] Create `python/src/ext_r2c/mcp/skills/_frontmatter.py` (R7): the pure-Python
  `SafeLoader` subclass with the timestamp resolver removed, `yes/no/on/off` kept as text,
  duplicate keys, anchors, aliases and unknown tags refused; `read_frontmatter`, the post-load
  JSON check (string keys; `str`, `int`, finite `float`, `bool`, `None`, lists, mappings; depth
  cap), the 64 KiB cap, `RecursionError` and any other failure turned into `FrontmatterError`;
  `MAX_FRONTMATTER_BYTES`.
- [ ] T016 [P] Create `python/src/ext_r2c/mcp/skills/_uris.py`: `SCHEME`, `SKILL_FILE`,
  `skill_name_ok` (`^[a-z0-9]+(-[a-z0-9]+)*$`, at most 64), `encode_uri`, `authority_key`,
  `last_segments`.
- [ ] T017 [P] Create `python/src/ext_r2c/mcp/skills/_content.py`: the fixed MIME table (R11) and
  `mime_for`, `as_text_or_bytes`. It does not use `mimetypes`.
- [ ] T018 [P] Create `python/src/ext_r2c/mcp/skills/_cursor.py`: `encode_cursor`,
  `decode_cursor`, `CursorError`.
- [ ] T019 Create `python/src/ext_r2c/mcp/skills/_catalogue.py`: the frozen records
  (`FileRecord`, `SkillRecord`, `DirectoryRecord`), `Catalogue.build(skills, left_out)` with the
  dictionaries, directories and a random `generation`, and the public `SkillInfo`, `LeftOut`,
  `SkillsError`. Field names are those of `data-model.md`.
- [ ] T020 Create `python/src/ext_r2c/mcp/skills/_wire.py`: the models of `data-model.md`
  (server results, the typed requests of R2, the client's result models with raw `skills`). Its
  docstring names the beta revision and the base protocol; no other module knows the shapes.
- [ ] T021 Run T011–T013 on the wheel until green.
- [ ] T022 Verify, then commit `feat(005): frontmatter reader, URIs, cursor, catalogue, wire models`.

---

## Phase 3: Serve and read a folder (US1, P1) 🎯 MVP

**Goal**: a real MCP SDK client lists, gets and reads every file of the fixture tree, and every
byte equals the disk's.

**Independent test**: `test_skills_scan.py` (units) and `test_skills_serve.py` (round trips).

**First cuts**: the scan skips hidden entries, links and non-regular files without reporting them
(phase 5 reports); the read opens the recorded path and checks size and digest (phase 5 hardens
it). `settings()` returns `{"directoryRead": False}` until phase 8 serves the method.

- [ ] T023 [P] [US1] Write `python/tests/test_skills_scan.py`, the finding and describing part,
  with `scan_roots(folders, include, exclude)` returning a `Catalogue`:
  - the fixture tree gives three skills with paths `pdf-notes`, `greetings`,
    `team/billing/refunds`, sorted by URI, each `name` equal to the last segment;
  - **nearest `SKILL.md` wins** (story 4, scenario 4): `refunds/examples/SKILL.md` is a file of
    `refunds`, listed in its `resources`, and `examples` is not scanned for skills; a skill
    folder directly under a folder without `SKILL.md` is a skill whose path starts at the root;
  - a root that itself holds a `SKILL.md` is one skill whose path is its own name;
  - several roots are scanned in the order given; a prefix folder is never a skill;
  - the nested path becomes `skill://team/billing/refunds/SKILL.md` (story 4, scenario 3);
  - each skill's files: `SKILL.md` exactly once, sorted by relative path; size and digest equal
    an independent `hashlib.sha256` and `stat`; digest text is `sha256:` plus 64 lowercase hex;
  - frontmatter passes through unchanged (`license`, nested `metadata`);
  - the file with a non-ASCII name gets an ASCII URI with `%C3%A9`;
  - hidden entries, links and non-regular files are absent from the served files (no report yet).
- [ ] T024 [P] [US1] Write `python/tests/test_skills_serve.py`, round trips over the harness with
  `SkillsExtension` on a plain `MCPServer` and the fixture tree, using the package's typed
  requests for `skills/*`:
  1. `server/discover` declares `resources` and `extensions[SKILLS_ID]` with a boolean
     `directoryRead` (scenario 1; the default value is asserted in phase 8).
  2. `skills/list`: `resultType: "complete"`, `ttlMs`, `cacheScope`, one entry per skill with
     `uri`, `frontmatter` (including extra fields unchanged) and `resources` (`SKILL.md` once,
     every other file once, digest and size equal to the disk's) (scenario 2).
  3. `skills/get` for each skill returns the list's entry plus `ttlMs` and `cacheScope`; an unknown
     skill URI is `-32602`; a supporting file's URI is `-32602` (scenario 3).
  4. `resources/read` of **every file of every skill** returns the disk's bytes: `text` for a UTF-8
     file, `blob` for the binary and Latin-1 files; the BOM and CRLF file comes back byte for
     byte; `SKILL.md` has `mimeType: text/markdown` (scenario 4, **SC-001**).
  5. `resources/list`, as a client that does not know the extension, shows every file as an
     ordinary resource; `SKILL.md` has the frontmatter's `name` and `description` (scenario 5).
  6. `ttl_ms=1000` and `cache_scope="public"` appear on both `skills/list` and `skills/get`.
  7. No result carries a `_meta` key of this package (FR-015).
- [ ] T025 [US1] Build, install, and run T023–T024. Confirm the expected failures: `scan_roots`
  and `SkillsExtension` do not exist.
- [ ] T026 [US1] Create `python/src/ext_r2c/mcp/skills/_scan.py`, first cut: resolve each root once
  with `os.path.realpath`; walk in sorted order without following links; the nearest `SKILL.md`
  makes a skill folder; read `SKILL.md` with `_frontmatter`; require `name` (string) and
  `description` (string); build the skill path, URIs, sizes, digests and MIME; build the
  `Catalogue`. Entries that are hidden, links or not regular are skipped. Errors raise
  `SkillsError` with a plain reason; the full list of build errors is phase 6.
- [ ] T027 [US1] Create `python/src/ext_r2c/mcp/skills/_read.py`, first cut: `read_file(record)`
  opens the recorded path, reads it, compares size and SHA-256, and returns the bytes, or raises
  `FileChanged` when anything differs.
- [ ] T028 [US1] Create `python/src/ext_r2c/mcp/skills/extension.py`:
  - `SkillFile`, a `Resource` whose `async read()` looks the URI up in the **current**
    catalogue and calls the extension's `_read_bytes(record)` in a worker thread
    (`anyio.to_thread.run_sync`); `FileChanged` becomes `MCPError(-32603, "The skills changed on
    disk since they were scanned; refresh them.")`; the bytes go out through `as_text_or_bytes`;
    `SKILL.md` has the frontmatter's `name` and `description` and `text/markdown`.
  - `SkillsExtension(Extension)` with `identifier = SKILLS_ID`, the constructor of
    `contracts/skills-api.md` (folders as a path or a list, the other settings with their
    defaults; **validation of the settings is phase 6**), `settings()`, `resources()` (one
    `SkillFile` per file), the two method bindings for `skills/list` (all skills on one page for
    now) and `skills/get`, and the properties `skills` and `catalogue`.
  - Two private override points the tests use to make a server lie: `_entry(skill)` builds the
    wire `Skill` of one skill, and `_read_bytes(record)` produces a file's bytes.
  - Each handler reads `self._catalogue` once.
- [ ] T029 [US1] Export `SkillsExtension` and `SkillInfo` from
  `python/src/ext_r2c/mcp/skills/__init__.py` and `python/src/ext_r2c/mcp/__init__.py`.
- [ ] T030 [US1] Run T023–T024 on the wheel until green. Run the by-hand example of
  `quickstart.md` section 5 (server side) and see `skill://refunds/SKILL.md` listed.
- [ ] T031 [US1] Verify, then commit `feat(005): serve skills from folders`.

---

## Phase 4: The caller's client (US2, P1)

**Goal**: a client that lists, loads and verifies, and refuses everything that does not verify,
without reading ahead of need.

**Independent test**: `test_skills_client.py`, against the fixture tree and against servers that
lie.

- [ ] T032 [P] [US2] Write `python/tests/test_skills_client.py`, part A (happy paths):
  - `declared` is true on a skills server and false on a server without the extension;
    `directory_read` reflects the declaration;
  - `list()` returns a `SkillListing` whose items carry `origin`, `uri`, `name`, `description`,
    `frontmatter`, `files`, and `key == (origin, uri)`; with the recording transport the number of
    `resources/read` requests after `list()` and after `get()` is **0** (scenario 7, SC-004);
  - `load(item)` returns the verified `SKILL.md` bytes, equal to the disk's, tagged with the
    origin; after it the recorder shows exactly 1 read; after `read(item, uri)` for N supporting
    files it shows 1 + N (**SC-004**);
  - every file of every fixture skill is read through the client and equals the disk's;
  - `SkillContent.text()` decodes strictly and raises on a Latin-1 file;
  - two skills with the same name under different prefixes (`a/pdf`, `b/pdf`) are both listed and
    have different keys; two servers with the same skill give different keys by origin; two
    `SkillsClient`s share nothing;
  - a frontmatter field such as `allowed-tools` is returned as data and nothing is done with it.
- [ ] T033 [US2] In the same file, part B (refusals; **SC-002**). A test subclass
  `Lying(SkillsExtension)` overrides `_entry` and `_read_bytes` (T028) so that a server says
  something false; each case asserts a `SkillRefused` with the URI (or `None`) and the named
  `check`, and that **no content is returned** (the exception is the only result):
  - `size` bigger and smaller than the bytes; a `digest` that differs; a `SKILL.md` whose
    frontmatter differs from the entry's in a value, in an added field and in a removed field;
  - a URI not in `resources` (`unlisted`), with the recorder showing **no request sent**;
  - `resources: "dynamic"`, `resources` missing, `resources` an object or a number (three
    distinct reasons);
  - 513 resources; resources whose sizes sum to more than 16,777,216; exactly 512 files and exactly
    16 MiB pass;
  - a malformed `digest` (uppercase hex, no prefix, short), a negative or non-integer or boolean
    `size`, a repeated resource URI, a `SKILL.md` missing from `resources`, a skill URI that does
    not end in `<name>/SKILL.md`, a missing `name` or `description`;
  - the response has no content, two contents, or a content with another URI; a `blob` larger than
    the base64 of `size` and a `text` longer than `size` are refused **before** being decoded;
    invalid base64;
  - a server that has not declared the extension, or not the `resources` capability: every
    method raises `declaration` and the recorder shows **no `skills/*` request**;
  - one bad entry among good ones: `list()` returns the good items and a `Refused` for the bad,
    while `get()` of the bad one raises.
- [ ] T034 [US2] Build, install, and run T032–T033. Confirm the expected failure: no `SkillsClient`.
- [ ] T035 [US2] Create `python/src/ext_r2c/mcp/skills/client.py`, part 1: the types of
  `contracts/skills-api.md` (`SkillFileRef`, `SkillItem`, `Refused`, `SkillListing`,
  `SkillContent`, `LoadedSkill`, `DirectoryEntry`, `SkillRefused`), `SkillsClient.__init__`
  (non-empty `origin`), `declared`, `directory_read`, and the declaration check every method
  runs first.
- [ ] T036 [US2] Same file, part 2: entry validation (R13): one function turns a raw JSON entry
  into a `SkillItem` or raises `SkillRefused` with `entry`, `resources` or `limit`, covering every
  case of T033's entry list.
- [ ] T037 [US2] Same file, part 3: `list()` (follows `nextCursor`, validates each entry on its
  own) and `get(uri)`, through the typed requests of `_wire`.
- [ ] T038 [US2] Same file, part 4: `read(item, uri)` and `load(item)`: refuse an unlisted URI
  without a request; check one content with the same URI; bound by `size` before decoding; then
  length, then SHA-256; for `SKILL.md`, the frontmatter by `_frontmatter` against the entry's,
  field by field. Nothing is cached or written.
- [ ] T039 [US2] Export the client names from `ext_r2c/mcp/skills/__init__.py` and
  `ext_r2c/mcp/__init__.py`.
- [ ] T040 [US2] Run T032–T033 on the wheel until green. **Mutation check**: remove, one at a
  time, the size check, the digest check, the frontmatter comparison, the unlisted check and the
  declaration check, and confirm a named test fails for each; restore them.
- [ ] T041 [US2] Verify, then commit `feat(005): the skills client verifies what it loads`.

---

## Phase 5: Nothing outside the skills is served (US3, P1)

**Goal**: the owner's disk is only reachable through the served files, and a file that changed
after the scan is never sent.

**Independent test**: `test_skills_safety.py`.

- [ ] T042 [P] [US3] Write `python/tests/test_skills_safety.py`, part A (**SC-003**): a fixture tree
  plus a secret outside the root (T004), a hidden file, a symlink to the secret, and a folder
  next to the skills. A table of **at least 14** `resources/read` URIs, each `-32602` with none of the
  secret's or any unserved file's bytes in the response, and the skills still readable after:
  `..` plain, `%2e%2e`, `%2E%2E`, `.%2e` and a double-encoded `%252e%252e`; a backslash; user info
  and a port in the first segment; the symlink's URI; the hidden file's URI; the neighbouring
  folder; a query; a fragment; a trailing slash on a file; `SKILL.MD` and `TEAM` (case); an encoded
  slash `%2F`; `skill:///etc/passwd` and `file:///etc/passwd`; a directory URI; an empty path.
  `resources/list` holds exactly the served files.
- [ ] T043 [US3] In the same file, part B:
  - **left out** (scenarios 2, 3): with a symlink to a file and one to a folder, a hidden file and
    folder, a named pipe and (where the platform allows) a name that is not valid UTF-8,
    `extension.left_out` holds one `LeftOut(path, reason)` for each, with the reasons `symbolic
    link`, `hidden`, `not a regular file`, `undecodable name`; paths are relative to the root with `/`;
    none is in `skills/list`; a `SKILL.md` that is a symlink is not a `SKILL.md`; the logger
    `ext_r2c.mcp.skills` emits one `INFO` line per skill and one `WARNING` per symlink, and
    nothing is logged at import.
  - **changed on disk after the scan** (scenario 4): same-size edit, a grown file (5 MiB), a
    deleted file, a file replaced by a directory → each read is `-32603` with exactly the fixed
    message, **no bytes** and no host path in the message; `skills/list` still shows the old
    entry.
  - **swapped after the scan**: the file replaced by a **symlink to an outside file with identical
    bytes** is refused; a **directory component** replaced by a symlink to an outside copy is
    refused; the file replaced by a **named pipe** answers `-32603` promptly, and a helper thread
    opens the pipe's other end so a failing run cannot hang the suite.
  - **never writes** (scenario 5): the whole fixture tree made read-only still serves every flow;
    `snapshot()` before and after the flows is equal; and a source audit of the installed
    `ext_r2c/mcp/skills/*.py` finds none of `O_WRONLY`, `O_RDWR`, `O_CREAT`, `O_TRUNC`,
    `O_APPEND`, `write_text`, `write_bytes`, `unlink`, `rmdir`, `rename`, `mkdir`, `chmod`,
    `shutil`, nor `open(` with a mode containing `w`, `a`, `x` or `+`.
  - **no host path on the wire**: every failing response above is searched for `str(tmp_path)`.
- [ ] T044 [US3] Build, install, and run T042–T043. Confirm the expected failures: `left_out` is
  missing, the pipe test fails by the elapsed-time assertion, and the swapped link is followed
  by the first-cut read. The unreachable-URI table and the digest checks may pass at once: they
  are the SDK's exact matching and the first cut's digest check. Say so in the report and prove
  them by mutation in T047.
- [ ] T045 [US3] `python/src/ext_r2c/mcp/skills/_scan.py`: record every skipped entry as
  `LeftOut(path, reason)` (hidden, symbolic link, not a regular file, undecodable name; a
  `SKILL.md` that is a link is a `symbolic link`); put the list in the `Catalogue`; the
  extension's `left_out` property and the logging of the plan.
- [ ] T046 [US3] `python/src/ext_r2c/mcp/skills/_read.py`: replace the first cut with the read of
  R4 in a function run in a worker thread: open the skill folder, then each component with
  `os.open(name, O_NOFOLLOW | O_CLOEXEC, dir_fd=fd)` (directories with `O_DIRECTORY`, the last
  with `O_RDONLY | O_NONBLOCK`); `fstat` must be a regular file; read at most `size + 1` bytes;
  compare the length and the SHA-256 of **those bytes**; return them. Every `OSError` and every
  mismatch is `FileChanged`, whose text carries no path. Where `O_NOFOLLOW` or `dir_fd` is missing,
  `lstat` each component first and say so in a comment. No write flag anywhere.
- [ ] T047 [US3] Run T042–T043 on the wheel until green. **Mutation check**: remove `O_NOFOLLOW`
  (the swapped-link tests fail), the `fstat` check (the pipe test fails), the digest comparison
  (the changed-on-disk tests fail), the `size + 1` bound (the grown-file test is still
  `-32603`, so note that the bound is verified by reading the code and by T043's source audit
  only); restore them.
- [ ] T048 [US3] Verify, then commit `feat(005): nothing outside the skills is served`.

---

## Phase 6: Filters, build errors and refresh (US4, P2)

**Goal**: the owner chooses what is served, is told exactly what is wrong when the folder is
wrong, and can scan again without risking a running server.

**Independent test**: `test_skills_scan.py` (filters), `test_skills_build_errors.py`,
`test_skills_refresh.py`.

- [ ] T049 [P] [US4] Extend `python/tests/test_skills_scan.py`, the filters (scenarios 1, 2, 7),
  on a tree with `a`, `b-draft`, `c`:
  - `include=["a", "c"]` serves `a` and `c`; `exclude=["*-draft"]` serves `a` and `c`;
    `include=["*"]` with `exclude=["a"]` serves everything but `a` (exclude wins);
  - patterns are case-sensitive (`A` does not match `a`) and are matched on the **last segment**:
    `exclude=["team"]` does not remove `team/billing/refunds`, and a pattern containing `/`
    never matches;
  - **a broken skill that the filters exclude does not stop the build**: a `SKILL.md` with no
    frontmatter, one with a wrong name, one over the file limit; the build succeeds and the broken
    one is not served.
- [ ] T050 [P] [US4] Write `python/tests/test_skills_build_errors.py` (**SC-005**, scenarios 5, 6).
  A table: each case builds a bad tree in `tmp_path` and asserts a `SkillsError` whose `folder`
  and `reason` are non-empty, `str(error) == f"{folder}: {reason}"`, and the text names the
  folder. **At least 20 cases**, grouped in the kinds of R6:
  - roots: missing; a file, not a directory; unreadable (skipped when running as root);
  - files: `SKILL.md` unreadable; a supporting file unreadable; `SKILL.md` not UTF-8;
  - frontmatter: none; not closed; YAML error; duplicate key; alias; unknown tag; over 64 KiB; not
    a mapping;
  - fields: `name` missing, not a string, empty, 65 characters, uppercase, `--`, a leading
    hyphen, non-ASCII; `description` missing, empty, not a string, 1,025 characters; `name`
    different from the folder name;
  - limits: 513 files fails, 512 passes; 16 MiB + 1 byte fails, 16 MiB passes (a sparse file, and
    the error is raised from `stat` sizes **before** any hashing);
  - sets: a duplicate URI across two roots; a duplicate by case in the first segment; no skill
    under the root; nothing left after the filters (the message names the filters).
  - **settings** are `ValueError`, not `SkillsError`: `ttl_ms` negative, a string or a bool;
    `page_size` 0 or a bool; `cache_scope="shared"`; `include="a"` or `exclude=[""]`; `folders=[]`
    or `""`; a `str`, a `PathLike` and a list are accepted forms of `folders`.
- [ ] T051 [P] [US4] Write `python/tests/test_skills_refresh.py` (FR-007; D2):
  - after editing a file, the list and the entry still show the old digest and a read is `-32603`;
    after `refresh()` the list shows the new digest, the read works, `skills` and `left_out`
    show the new scan;
  - a skill added on disk appears after `refresh(server)`, and its files are readable through
    `resources/read`; `refresh()` **without** the server raises `SkillsError` and the old
    catalogue keeps serving unchanged;
  - a file removed on disk: after `refresh()` its read is `-32602` and it is **still in
    `resources/list`** (the documented limit), and its listed metadata keeps its old values;
  - a skill removed on disk: `skills/get` is `-32602` and the list omits it;
  - a bad edit (broken frontmatter): `refresh()` raises `SkillsError`, the old catalogue keeps
    serving, and a later fix plus `refresh()` recovers;
  - `refresh()` can be called repeatedly; each success changes the catalogue's generation;
  - a burst of `skills/list` requests while refreshes run: every response is consistent (all
    digests of one generation), never a mix.
- [ ] T052 [US4] Build, install, and run T049–T051. Confirm the expected failures: no filters, a
  few build errors still plain, no settings checks, no `refresh`.
- [ ] T053 [US4] `python/src/ext_r2c/mcp/skills/_scan.py`: apply `include` / `exclude` with
  `fnmatch.fnmatchcase` on the last segment **before** reading a skill; every error kind of R6
  raised as `SkillsError(folder, reason)`; the limits checked from `stat` sizes before hashing;
  the name and description rules; the folder-name rule; duplicate URIs with the first segment
  case-folded; nothing left; an `OSError` becomes a reason without a host path other than the
  folder the owner gave.
- [ ] T054 [US4] `python/src/ext_r2c/mcp/skills/extension.py`: the `include` and `exclude`
  arguments; settings validation (`ValueError`); the accepted forms of `folders`.
- [ ] T055 [US4] `python/src/ext_r2c/mcp/skills/extension.py`: `refresh(server=None)`: scan again
  with the same arguments; new file URIs need `server.add_resource` (without a server:
  `SkillsError`, nothing changed); swap `self._catalogue` in one assignment; a failed scan keeps
  the old catalogue; `SkillFile.read` looks the URI up in the current catalogue, so a removed file
  is `MCPError(-32602, ...)`.
- [ ] T056 [US4] Run T049–T051 on the wheel until green. **Mutation check**: apply the filters
  after parsing (the excluded-broken tests fail) and swap the catalogue in two steps (the burst
  test fails); restore.
- [ ] T057 [US4] Verify, then commit `feat(005): filters, build errors, refresh`.

---

## Phase 7: Beside R2C, or alone (US5, P2)

**Goal**: the extension works on a server that also has R2C, on a skills-only server, and on a
server built by hand; spec 004's flows are untouched.

**Independent test**: `test_skills_compose.py`; `mcp_only.py` in `../.mcp-venv`.

- [ ] T058 [P] [US5] Write `python/tests/test_skills_compose.py` (**SC-006**):
  1. `mcp_server("agent", R2CExtension(tools=[...]), extensions=[skills])`: one R2C flow of spec
     004 (use the simplest flow of `test_mcp_serve.py` that asks a question) **and** the skills
     flows complete on the same server; `server/discover` declares both `MCP_KEY` and
     `SKILLS_ID`; the R2C wire of the flow equals the wire of the same flow on a server built
     without skills (compared after the normaliser of `mcp_replay_kit.py`, or message by message
     for the fields that matter).
  2. A skills-only server `MCPServer("docs", extensions=[SkillsExtension(...)])`: skills flows
     pass, `MCP_KEY` is not declared, no tool is listed.
  3. A hand-built server with a plain tool and the extension: the tool is callable and untouched
     (the extension does not intercept `tools/call`).
  4. `mcp_server(...)` without `extensions` is unchanged; `extensions` may be a tuple; the
     extensions are served after R2C's (`[R2C, *extensions]`); two extensions with the same
     identifier fail as the SDK says.
- [ ] T059 [P] [US5] `python/tests/mcp_only.py`: add `_skills_check()`: build a skills folder in a
  temporary directory, serve it with `MCPServer(..., extensions=[SkillsExtension(...)])`, list and
  read one skill. Use the SDK's in-memory `Client(server)` if T005 test 9 shows it carries the
  typed requests; if not, check the server side only (declaration, `skills`, `left_out == ()`) as
  spec 004's check does, and say so in the file. Assert no `a2a`, `langchain` or `langgraph`
  module is loaded.
- [ ] T060 [US5] Build, install, and run T058–T059. Confirm the expected failure: `mcp_server`
  does not accept `extensions`.
- [ ] T061 [US5] `python/src/ext_r2c/mcp/server.py`: `extensions: Sequence[Extension] = ()`
  appended after the R2C extension, with its docstring; no other change.
- [ ] T062 [US5] Run T058–T059 on the wheel until green, then the **whole** suite: the tests of
  specs 001–004 pass unchanged, and both replays report the same counts as before.
- [ ] T063 [US5] Verify, then commit `feat(005): skills beside R2C, or alone`.

---

## Phase 8: Many skills, and directories (US6, P3)

**Goal**: a long list pages by an opaque cursor; the files of a skill can be listed by directory;
the client can read both.

**Independent test**: `test_skills_pages.py`, `test_skills_directory.py`.

- [ ] T064 [P] [US6] Write `python/tests/test_skills_pages.py` (**SC-007**):
  - 60 skills with `page_size=25` give pages of 25, 25 and 10; across them every skill appears
    **exactly once**, in URI order; each entry is whole (its `resources` complete); `nextCursor` is
    absent on the last page; `page_size=1` and a `page_size` above the count work;
  - a skill with 512 files is whole on its page;
  - `SkillsClient.list()` returns all 60;
  - a bad cursor is `-32602` with a fixed message that carries no path: garbage, an empty
    string, valid base64 of a wrong shape, a negative offset, an offset past the end, a cursor
    of another server, and **a cursor from before a `refresh()`** (the generation changed);
  - the client refuses a server whose `nextCursor` repeats (`SkillRefused`, check `response`) and
    does not loop.
- [ ] T065 [P] [US6] Write `python/tests/test_skills_directory.py` (FR-013, scenarios 2, 3):
  - by default discovery says `directoryRead: true`; with `directory_read=False` it says `false`
    and `resources/directory/read` is `-32601`; the client's `directory_read` follows;
  - a skill's root lists its **direct children only**: `SKILL.md` (with the frontmatter's `name`
    and `description`, `text/markdown`), files with their MIME, subfolders as
    `mimeType: inode/directory`; a nested directory works; an **empty** directory (made in the
    fixture) answers `"resources": []`;
  - not directories, each `-32602`: `skill://team/billing` (a prefix above skills), a file, an
    unknown URI, a trailing slash, `..`, a skill the filters exclude;
  - paging with `page_size=1` and a bad cursor;
  - directory resources are not in `resources/list`;
  - the directory answers come from the catalogue: after the files are deleted on disk, a
    directory read still answers and a file read is `-32603`;
  - the files reachable through directories equal the files of the entry.
  - **client** `list_directory(item, uri)`: allowed for the skill's root and below, tagged with
    the origin, following pages; refused with `check="directory"` and **no request** for another
    skill's root, a prefix above skills, a non-`skill` scheme, or when `directoryRead` is not
    declared; a child the entry does not list (a server that lies) comes back as metadata and
    `read` still refuses it as `unlisted`.
- [ ] T066 [US6] Build, install, and run T064–T065. Confirm the expected failures: one page only,
  `directoryRead` false, no directory method, no `list_directory`.
- [ ] T067 [US6] `python/src/ext_r2c/mcp/skills/_scan.py` and `_catalogue.py`: record every
  directory of a served skill, **empty ones included** (hidden and linked ones are not), with the
  children `(uri, name, mime, is_dir)` sorted by name.
- [ ] T068 [US6] `python/src/ext_r2c/mcp/skills/extension.py`: page `skills/list` with `_cursor`
  and `page_size`; the `resources/directory/read` binding, only when `directory_read` is on;
  `settings()` returns `{"directoryRead": self._directory_read}`; every cursor error is
  `MCPError(-32602, ...)` with a fixed message.
- [ ] T069 [US6] `python/src/ext_r2c/mcp/skills/client.py`: `list_directory`, and the guard that a
  repeated `nextCursor` stops `list()` and `list_directory()` with `SkillRefused`.
- [ ] T070 [US6] Run T064–T065 on the wheel until green.
- [ ] T071 [US6] Verify, then commit `feat(005): pages and directory reads`.

---

## Phase 9: Docs and final gate

**Goal**: the docs say what exists, the diff is reviewed by someone who did not write it, and
every environment passes.

- [ ] T072 [P] `python/README.md`: a Skills section: serve a folder (the example of
  `quickstart.md`), `include` / `exclude`, `refresh`, beside R2C with `mcp_server(extensions=)`,
  the client; the v1 limits (ASCII names, nearest `SKILL.md`, a file is sent whole, the refresh
  limits), the Beta note, and that `[mcp]` now brings PyYAML. Invented names only.
- [ ] T073 [P] `ARCHITECTURE.md`: the `mcp/skills/` rows, and the rule that it imports nothing of
  `ext_r2c`.
- [ ] T074 [P] `CHANGELOG.md`: Added (the skills extension, the client, `mcp_server(extensions=)`,
  PyYAML in `[mcp]`). No Changed entry: the standard does not change.
- [ ] T075 [P] The ADR `docs/design-docs/skills-frontmatter-and-nesting.md` (Context, Decision,
  Alternatives, Consequences: Better / Worse / Must now be true) for D1 (a YAML reader in
  `[mcp]`) and the nearest-`SKILL.md` rule; a row for it in the `AGENTS.md` Docs table (the file
  stays under 150 lines).
- [ ] T076 [P] Reconcile older docs, grepping `skill` / `Skills` over `README.md`,
  `ARCHITECTURE.md`, `AGENTS.md`, `docs/`, `python/README.md` and `specs/001`–`004`:
  - in `docs/design-docs/one-remote-two-doors.md` and `docs/whitepaper.md`, add a dated note
    (2026-11-21, never a rewrite of the body) for the three differences of the plan: the URI form
    (`skill://<skill-path>/…`), no `exclude_files`, and no link is ever followed;
  - in completed specs, annotate with a dated note any "left open for Skills" statement that 005
    settles;
  - fix any current-tense statement that says skills are unbuilt.
- [ ] T077 `WORKSTATE.md`: spec 5 done (counts, commit), the "Next" bullet moved on, and the
  waiting-for-approval list updated.
- [ ] T078 Outside review of the diff `4bc6c9d..HEAD` (the 005 phases): launch the
  `code-reviewer` and the `security-reviewer` agents **in one message**, each with a
  self-contained brief (the diff range, what the feature does, the output contract: findings
  ranked by severity with file and line). Focus the security reviewer on path handling, the
  dictionary lookup, the safe read, the YAML reader and the client's verification; the code
  reviewer on correctness, the first-cut-to-final replacement of phase 5, and the tests'
  strength. For each finding that holds: write a failing test, fix, and record it under "Outside
  review" in `research.md`. State what was left on purpose.
- [ ] T079 Final verification, `quickstart.md` sections 1–4, on **Python 3.11, 3.12 and 3.13**
  (**SC-008**): build; the whole suite on each; the core-only, A2A-only and MCP-only runs;
  `uvx ruff check --select F src tests`; the leak scan. Record the test counts.
- [ ] T080 Fill "Notes: where reality differed" below, tick `checklists/requirements.md`, then
  commit `chore(005): close MCP Skills`. Do not push: that is the maintainer's go.

---

## Dependencies and execution order

- **Phase 1 → Phase 2 → Phase 3** are strictly serial: the fixtures, the spike facts and the
  foundation come before any extension code.
- **Phase 3 (US1)** is the MVP. **Phases 4 (US2) and 5 (US3)** both need phase 3 and do not need
  each other; one phase per go keeps them serial.
- **Phase 6 (US4)** extends the scan and the constructor of phases 3 and 5. **Phase 7 (US5)**
  needs the extension only. **Phase 8 (US6)** needs phase 4 (the client), phase 6 (`refresh`, for
  the stale cursor, and the settings) and phase 3.
- **Phase 9** is last.

## Parallel opportunities

Inside each phase, the tasks marked [P] are in different files and can be written together:
- phase 1: T002–T005;
- phase 2: T011–T013, then T015–T018;
- phase 3: T023 and T024;
- phase 4: T032 (T033 is in the same file);
- phase 5: T042 (T043 is in the same file);
- phase 6: T049–T051;
- phase 7: T058 and T059;
- phase 8: T064 and T065;
- phase 9: T072–T076.

Production tasks in a phase touch the same modules and stay serial, except T015–T018.

## Implementation strategy

- **MVP**: phases 1–3. A real MCP SDK client lists, gets and reads every file of a skills folder,
  and the bytes equal the disk's (SC-001).
- **Then**: the client (4), the safety envelope (5), filters, errors and refresh (6), composition
  (7), pages and directories (8), docs and the gate (9).
- **Each phase** ends verified and committed, and waits for the maintainer's go.

## Decisions made while writing these tasks

Not in the spec or the research; the maintainer may overrule any of them when approving.

- **A first cut of the scan and the read in phase 3**, then the hardened versions in phase 5
  (T046 replaces T027), each time test first. Alternative: write the hardened read at once. The
  cost of the order is one rewritten function; the gain is that the phase 5 tests fail for a real
  reason instead of passing on code written to pass them.
- **`settings()` says `directoryRead: false` until phase 8**, so no commit between phases
  declares a method that is not served (FR-008).
- **Two private override points** on the extension, `_entry` and `_read_bytes`, so the client's
  tests can use a server that lies without patching the SDK.
- **The client refuses a repeated `nextCursor`** (T064, T069): a server that pages forever would
  otherwise hang `list()`. Not in the spec; small and in the safe direction.
- **The MIME table compares extensions in lower case** (T012), so `README.MD` is Markdown.
- **Settings reject a `bool` where an integer is wanted** (T050): `True` is an `int` in Python.
- **The empty directories of a skill are directories** (T065, T067), as the text says an empty
  directory answers an empty list.
- **Tests skip, with a reason, where the platform or the user cannot make the condition**
  (symbolic links and pipes on Windows, an unreadable folder when running as root, a file name
  that is not UTF-8 on a platform that cannot create one).
- **`test_packaging.py` scans sub-folders** (T002), which today it does not, so that
  `mcp/skills/` is covered by the existing rule.

## Notes: where reality differed

Filled by T080.
