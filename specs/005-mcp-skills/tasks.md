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

- [X] T001 Repeat the PyYAML vet with the `security-audit` skill, on the day the dependency is
  added, and write the result under R7 of `specs/005-mcp-skills/research.md` ("Vet repeated on
  <date> by T001"):
  - OSV query for `PyYAML` (`MAL-` advisories: must be none) and the advisories that apply to
    the range;
  - upload dates of 6.0.3 and 6.0.4 (6.0.4 was uploaded 2026-11-20), yanked files, wheels for
    CPython 3.11, 3.12, 3.13 on Linux, macOS and Windows, empty `requires_dist`, no install script;
  - **stop and tell the maintainer** if a `MAL-` advisory, a yanked release, a changed
    maintainer or a changed dependency list shows up. If the maintainer chose `<6.0.4`, use that
    bound in T007 instead of `<7`.
- [X] T002 [P] Extend `python/tests/test_packaging.py` (test first):
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
- [X] T003 [P] Extend the two scripts pytest does not collect:
  - `python/tests/core_only.py`: after importing `ext_r2c.core`, assert `yaml` is not loaded.
  - `python/tests/mcp_only.py`: add `import ext_r2c.mcp.skills` and `import yaml` to the import
    check, and leave a `# phase 7:` comment where the skills round trip goes (T059).
- [X] T004 [P] Create `python/tests/skills_fixtures.py`, invented content only:
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
- [X] T005 [P] Write `python/tests/test_skills_spike.py`. Each test pins one SDK fact the design
  leans on, with a throwaway `Extension` subclass and the harness (`serve`, `mcp_client` with
  `active=False`, `run`); a failing one stops the phase and updates research and plan first.
  1. `test_extension_binds_new_methods_and_declares_settings`: `MethodBinding` for `skills/list`,
     `skills/get` and `resources/directory/read` is accepted; `settings()` appears at
     `capabilities.extensions[SKILLS_ID]`; `resources` is declared (R1). A second test,
     `test_resources_capability_is_always_declared`, pins that `MCPServer` declares it even with
     no resource registered (corrected 2026-11-22: R1 first said "as soon as one is registered").
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
- [X] T006 Build, install, and run T002, T003 and T005. Confirm the expected failures: the extra
  has one requirement, `ext_r2c/mcp/skills` is missing, and `yaml` is not yet a dependency. The
  spike tests pass or fail by the facts alone.
- [X] T007 Change `python/pyproject.toml`: `mcp = ["mcp>=2.3,<3", "PyYAML>=6.0.3,<7"]` and the same
  `PyYAML` line in the `dev` group, with a comment saying the group lists what the extras bring.
- [X] T008 Create `python/src/ext_r2c/mcp/skills/__init__.py`: a module docstring that says it is
  MCP Skills, **Beta**, written against the beta revision read on 2026-11-21 (base protocol
  2026-07-28), and that it imports nothing of `ext_r2c`; an empty `__all__`.
- [X] T009 Run T002, T003, T005 on the wheel until green. Fix the harness, not the facts. If a
  fact does not hold, stop and update `research.md` and `plan.md` before going on. Run
  `core_only.py` and `mcp_only.py` in their venvs.
- [X] T010 Verify, then commit `feat(005): PyYAML in [mcp], skills package skeleton, SDK spike`.

*Phase 1 done 2026-11-22.* 910 tests pass on 3.11, 3.12 and 3.13 (898 before, 12 new), and
`core_only.py`, `a2a_only.py`, `mcp_only.py` and `ruff --select F` are clean. One SDK fact was
worse than recorded: `MCPServer` declares `resources` always, not "once a resource is
registered" (R1 corrected, test 2 added; nothing in the design changes). The `[mcp]` extra now
resolves PyYAML to 6.0.4, two days old and vetted by T001. Tests that passed on their first run
were each shown able to fail by a mutation check (a changed SDK, or a changed premise).

---

## Phase 2: Foundation (reader, URIs, cursor, records, wire models)

**Goal**: everything the stories share, with no server and no disk walk yet.

**Independent test**: `test_skills_frontmatter.py`, `test_skills_wire.py`,
`test_skills_catalogue.py`, all pure units on the installed wheel.

- [x] T011 [P] Write `python/tests/test_skills_frontmatter.py` (R7). `read_frontmatter(data)`
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
- [x] T012 [P] Write `python/tests/test_skills_wire.py`:
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
- [x] T013 [P] Write `python/tests/test_skills_catalogue.py`:
  - a catalogue built from hand-made records has exact dictionaries `by_uri`, `files`,
    `directories`; `skills` sorted by URI; a skill's files sorted by relative path;
  - one directory record per directory of every skill, the root included; its children are the
    direct children only, sorted by name, as `(uri, name, mime, is_dir)`; a prefix above two
    skills is **not** a directory; a directory URI has no trailing slash;
  - two builds have different `generation` tokens;
  - `SkillsError("folder", "reason")` is a `ValueError` with `.folder`, `.reason` and the message
    `folder: reason`; `SkillInfo` and `LeftOut` are frozen.
- [x] T014 Build, install, and run T011–T013. Confirm the expected failures: the modules do not
  exist.
- [x] T015 [P] Create `python/src/ext_r2c/mcp/skills/_frontmatter.py` (R7): the pure-Python
  `SafeLoader` subclass with the timestamp resolver removed, `yes/no/on/off` kept as text,
  duplicate keys, anchors, aliases and unknown tags refused; `read_frontmatter`, the post-load
  JSON check (string keys; `str`, `int`, finite `float`, `bool`, `None`, lists, mappings; depth
  cap), the 64 KiB cap, `RecursionError` and any other failure turned into `FrontmatterError`;
  `MAX_FRONTMATTER_BYTES`.
- [x] T016 [P] Create `python/src/ext_r2c/mcp/skills/_uris.py`: `SCHEME`, `SKILL_FILE`,
  `skill_name_ok` (`^[a-z0-9]+(-[a-z0-9]+)*$`, at most 64), `encode_uri`, `authority_key`,
  `last_segments`.
- [x] T017 [P] Create `python/src/ext_r2c/mcp/skills/_content.py`: the fixed MIME table (R11) and
  `mime_for`, `as_text_or_bytes`. It does not use `mimetypes`.
- [x] T018 [P] Create `python/src/ext_r2c/mcp/skills/_cursor.py`: `encode_cursor`,
  `decode_cursor`, `CursorError`.
- [x] T019 Create `python/src/ext_r2c/mcp/skills/_catalogue.py`: the frozen records
  (`FileRecord`, `SkillRecord`, `DirectoryRecord`), `Catalogue.build(skills, left_out)` with the
  dictionaries, directories and a random `generation`, and the public `SkillInfo`, `LeftOut`,
  `SkillsError`. Field names are those of `data-model.md`.
- [x] T020 Create `python/src/ext_r2c/mcp/skills/_wire.py`: the models of `data-model.md`
  (server results, the typed requests of R2, the client's result models with raw `skills`). Its
  docstring names the beta revision and the base protocol; no other module knows the shapes.
- [x] T021 Run T011–T013 on the wheel until green.
- [x] T022 Verify, then commit `feat(005): frontmatter reader, URIs, cursor, catalogue, wire models`.

---

## Phase 3: Serve and read a folder (US1, P1) 🎯 MVP

**Goal**: a real MCP SDK client lists, gets and reads every file of the fixture tree, and every
byte equals the disk's.

**Independent test**: `test_skills_scan.py` (units) and `test_skills_serve.py` (round trips).

**First cuts**: the scan skips hidden entries, links and non-regular files without reporting them
(phase 5 reports); the read opens the recorded path and checks size and digest (phase 5 hardens
it). `settings()` returns `{"directoryRead": False}` until phase 8 serves the method.

- [X] T023 [P] [US1] Write `python/tests/test_skills_scan.py`, the finding and describing part,
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
- [X] T024 [P] [US1] Write `python/tests/test_skills_serve.py`, round trips over the harness with
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
- [X] T025 [US1] Build, install, and run T023–T024. Confirm the expected failures: `scan_roots`
  and `SkillsExtension` do not exist.
- [X] T026 [US1] Create `python/src/ext_r2c/mcp/skills/_scan.py`, first cut: resolve each root once
  with `os.path.realpath`; walk in sorted order without following links; the nearest `SKILL.md`
  makes a skill folder; read `SKILL.md` with `_frontmatter`; require `name` (string) and
  `description` (string); build the skill path, URIs, sizes, digests and MIME; build the
  `Catalogue`. Entries that are hidden, links or not regular are skipped. Errors raise
  `SkillsError` with a plain reason; the full list of build errors is phase 6.
- [X] T027 [US1] Create `python/src/ext_r2c/mcp/skills/_read.py`, first cut: `read_file(record)`
  opens the recorded path, reads it, compares size and SHA-256, and returns the bytes, or raises
  `FileChanged` when anything differs.
- [X] T028 [US1] Create `python/src/ext_r2c/mcp/skills/extension.py`:
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
- [X] T029 [US1] Export `SkillsExtension` and `SkillInfo` from
  `python/src/ext_r2c/mcp/skills/__init__.py` and `python/src/ext_r2c/mcp/__init__.py`.
- [X] T030 [US1] Run T023–T024 on the wheel until green. Run the by-hand example of
  `quickstart.md` section 5 (server side) and see `skill://refunds/SKILL.md` listed.
- [X] T031 [US1] Verify, then commit `feat(005): serve skills from folders`.

---

## Phase 4: The caller's client (US2, P1)

**Goal**: a client that lists, loads and verifies, and refuses everything that does not verify,
without reading ahead of need.

**Independent test**: `test_skills_client.py`, against the fixture tree and against servers that
lie.

- [x] T032 [P] [US2] Write `python/tests/test_skills_client.py`, part A (happy paths):
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
- [x] T033 [US2] In the same file, part B (refusals; **SC-002**). A test subclass
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
- [x] T034 [US2] Build, install, and run T032–T033. Confirm the expected failure: no `SkillsClient`.
- [x] T035 [US2] Create `python/src/ext_r2c/mcp/skills/client.py`, part 1: the types of
  `contracts/skills-api.md` (`SkillFileRef`, `SkillItem`, `Refused`, `SkillListing`,
  `SkillContent`, `LoadedSkill`, `DirectoryEntry`, `SkillRefused`), `SkillsClient.__init__`
  (non-empty `origin`), `declared`, `directory_read`, and the declaration check every method
  runs first.
- [x] T036 [US2] Same file, part 2: entry validation (R13): one function turns a raw JSON entry
  into a `SkillItem` or raises `SkillRefused` with `entry`, `resources` or `limit`, covering every
  case of T033's entry list.
- [x] T037 [US2] Same file, part 3: `list()` (follows `nextCursor`, validates each entry on its
  own) and `get(uri)`, through the typed requests of `_wire`.
- [x] T038 [US2] Same file, part 4: `read(item, uri)` and `load(item)`: refuse an unlisted URI
  without a request; check one content with the same URI; bound by `size` before decoding; then
  length, then SHA-256; for `SKILL.md`, the frontmatter by `_frontmatter` against the entry's,
  field by field. Nothing is cached or written.
- [x] T039 [US2] Export the client names from `ext_r2c/mcp/skills/__init__.py` and
  `ext_r2c/mcp/__init__.py`.
- [x] T040 [US2] Run T032–T033 on the wheel until green. **Mutation check**: remove, one at a
  time, the size check, the digest check, the frontmatter comparison, the unlisted check and the
  declaration check, and confirm a named test fails for each; restore them.
- [x] T041 [US2] Verify, then commit `feat(005): the skills client verifies what it loads`.

---

## Phase 5: Nothing outside the skills is served (US3, P1)

**Goal**: the owner's disk is only reachable through the served files, and a file that changed
after the scan is never sent.

**Independent test**: `test_skills_safety.py`.

- [x] T042 [P] [US3] Write `python/tests/test_skills_safety.py`, part A (**SC-003**): a fixture tree
  plus a secret outside the root (T004), a hidden file, a symlink to the secret, and a folder
  next to the skills. A table of **at least 14** `resources/read` URIs, each `-32602` with none of the
  secret's or any unserved file's bytes in the response, and the skills still readable after:
  `..` plain, `%2e%2e`, `%2E%2E`, `.%2e` and a double-encoded `%252e%252e`; a backslash; user info
  and a port in the first segment; the symlink's URI; the hidden file's URI; the neighbouring
  folder; a query; a fragment; a trailing slash on a file; `SKILL.MD` and `TEAM` (case); an encoded
  slash `%2F`; `skill:///etc/passwd` and `file:///etc/passwd`; a directory URI; an empty path.
  `resources/list` holds exactly the served files.
- [x] T043 [US3] In the same file, part B:
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
- [x] T044 [US3] Build, install, and run T042–T043. Confirm the expected failures: `left_out` is
  missing, the pipe test fails by the elapsed-time assertion, and the swapped link is followed
  by the first-cut read. The unreachable-URI table and the digest checks may pass at once: they
  are the SDK's exact matching and the first cut's digest check. Say so in the report and prove
  them by mutation in T047.
- [x] T045 [US3] `python/src/ext_r2c/mcp/skills/_scan.py`: record every skipped entry as
  `LeftOut(path, reason)` (hidden, symbolic link, not a regular file, undecodable name; a
  `SKILL.md` that is a link is a `symbolic link`); put the list in the `Catalogue`; the
  extension's `left_out` property and the logging of the plan.
- [x] T046 [US3] `python/src/ext_r2c/mcp/skills/_read.py`: replace the first cut with the read of
  R4 in a function run in a worker thread: open the skill folder, then each component with
  `os.open(name, O_NOFOLLOW | O_CLOEXEC, dir_fd=fd)` (directories with `O_DIRECTORY`, the last
  with `O_RDONLY | O_NONBLOCK`); `fstat` must be a regular file; read at most `size + 1` bytes;
  compare the length and the SHA-256 of **those bytes**; return them. Every `OSError` and every
  mismatch is `FileChanged`, whose text carries no path. Where `O_NOFOLLOW` or `dir_fd` is missing,
  `lstat` each component first and say so in a comment. No write flag anywhere.
- [x] T047 [US3] Run T042–T043 on the wheel until green. **Mutation check**: remove `O_NOFOLLOW`
  (the swapped-link tests fail), the `fstat` check (the pipe test fails), the digest comparison
  (the changed-on-disk tests fail), the `size + 1` bound (the grown-file test is still
  `-32603`, so note that the bound is verified by reading the code and by T043's source audit
  only); restore them.
- [x] T048 [US3] Verify, then commit `feat(005): nothing outside the skills is served`.

---

## Phase 6: Filters, build errors and refresh (US4, P2)

**Goal**: the owner chooses what is served, is told exactly what is wrong when the folder is
wrong, and can scan again without risking a running server.

**Independent test**: `test_skills_scan.py` (filters), `test_skills_build_errors.py`,
`test_skills_refresh.py`.

- [x] T049 [P] [US4] Extend `python/tests/test_skills_scan.py`, the filters (scenarios 1, 2, 7),
  on a tree with `a`, `b-draft`, `c`:
  - `include=["a", "c"]` serves `a` and `c`; `exclude=["*-draft"]` serves `a` and `c`;
    `include=["*"]` with `exclude=["a"]` serves everything but `a` (exclude wins);
  - patterns are case-sensitive (`A` does not match `a`) and are matched on the **last segment**:
    `exclude=["team"]` does not remove `team/billing/refunds`, and a pattern containing `/`
    never matches;
  - **a broken skill that the filters exclude does not stop the build**: a `SKILL.md` with no
    frontmatter, one with a wrong name, one over the file limit; the build succeeds and the broken
    one is not served.
- [x] T050 [P] [US4] Write `python/tests/test_skills_build_errors.py` (**SC-005**, scenarios 5, 6).
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
- [x] T051 [P] [US4] Write `python/tests/test_skills_refresh.py` (FR-007; D2):
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
- [x] T052 [US4] Build, install, and run T049–T051. Confirm the expected failures: no filters, a
  few build errors still plain, no settings checks, no `refresh`.
- [x] T053 [US4] `python/src/ext_r2c/mcp/skills/_scan.py`: apply `include` / `exclude` with
  `fnmatch.fnmatchcase` on the last segment **before** reading a skill; every error kind of R6
  raised as `SkillsError(folder, reason)`; the limits checked from `stat` sizes before hashing;
  the name and description rules; the folder-name rule; duplicate URIs with the first segment
  case-folded; nothing left; an `OSError` becomes a reason without a host path other than the
  folder the owner gave.
- [x] T054 [US4] `python/src/ext_r2c/mcp/skills/extension.py`: the `include` and `exclude`
  arguments; settings validation (`ValueError`); the accepted forms of `folders`.
- [x] T055 [US4] `python/src/ext_r2c/mcp/skills/extension.py`: `refresh(server=None)`: scan again
  with the same arguments; new file URIs need `server.add_resource` (without a server:
  `SkillsError`, nothing changed); swap `self._catalogue` in one assignment; a failed scan keeps
  the old catalogue; `SkillFile.read` looks the URI up in the current catalogue, so a removed file
  is `MCPError(-32602, ...)`.
- [x] T056 [US4] Run T049–T051 on the wheel until green. **Mutation check**: apply the filters
  after parsing (the excluded-broken tests fail) and swap the catalogue in two steps (the burst
  test fails); restore.
- [x] T057 [US4] Verify, then commit `feat(005): filters, build errors, refresh`.

---

## Phase 7: Beside R2C, or alone (US5, P2)

**Goal**: the extension works on a server that also has R2C, on a skills-only server, and on a
server built by hand; spec 004's flows are untouched.

**Independent test**: `test_skills_compose.py`; `mcp_only.py` in `../.mcp-venv`.

- [x] T058 [P] [US5] Write `python/tests/test_skills_compose.py` (**SC-006**):
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
- [x] T059 [P] [US5] `python/tests/mcp_only.py`: add `_skills_check()`: build a skills folder in a
  temporary directory, serve it with `MCPServer(..., extensions=[SkillsExtension(...)])`, list and
  read one skill. Use the SDK's in-memory `Client(server)` if T005 test 9 shows it carries the
  typed requests; if not, check the server side only (declaration, `skills`, `left_out == ()`) as
  spec 004's check does, and say so in the file. Assert no `a2a`, `langchain` or `langgraph`
  module is loaded.
- [x] T060 [US5] Build, install, and run T058–T059. Confirm the expected failure: `mcp_server`
  does not accept `extensions`.
- [x] T061 [US5] `python/src/ext_r2c/mcp/server.py`: `extensions: Sequence[Extension] = ()`
  appended after the R2C extension, with its docstring; no other change.
- [x] T062 [US5] Run T058–T059 on the wheel until green, then the **whole** suite: the tests of
  specs 001–004 pass unchanged, and both replays report the same counts as before.
- [x] T063 [US5] Verify, then commit `feat(005): skills beside R2C, or alone`.

---

## Phase 8: Many skills, and directories (US6, P3)

**Goal**: a long list pages by an opaque cursor; the files of a skill can be listed by directory;
the client can read both.

**Independent test**: `test_skills_pages.py`, `test_skills_directory.py`.

- [x] T064 [P] [US6] Write `python/tests/test_skills_pages.py` (**SC-007**):
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
- [x] T065 [P] [US6] Write `python/tests/test_skills_directory.py` (FR-013, scenarios 2, 3):
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
- [x] T066 [US6] Build, install, and run T064–T065. Confirm the expected failures: one page only,
  `directoryRead` false, no directory method, no `list_directory`.
- [x] T067 [US6] `python/src/ext_r2c/mcp/skills/_scan.py` and `_catalogue.py`: record every
  directory of a served skill, **empty ones included** (hidden and linked ones are not), with the
  children `(uri, name, mime, is_dir)` sorted by name.
- [x] T068 [US6] `python/src/ext_r2c/mcp/skills/extension.py`: page `skills/list` with `_cursor`
  and `page_size`; the `resources/directory/read` binding, only when `directory_read` is on;
  `settings()` returns `{"directoryRead": self._directory_read}`; every cursor error is
  `MCPError(-32602, ...)` with a fixed message.
- [x] T069 [US6] `python/src/ext_r2c/mcp/skills/client.py`: `list_directory`, and the guard that a
  repeated `nextCursor` stops `list()` and `list_directory()` with `SkillRefused`.
- [x] T070 [US6] Run T064–T065 on the wheel until green.
- [x] T071 [US6] Verify, then commit `feat(005): pages and directory reads`.

---

## Phase 9: Docs and final gate

**Goal**: the docs say what exists, the diff is reviewed by someone who did not write it, and
every environment passes.

- [X] T072 [P] `python/README.md`: a Skills section: serve a folder (the example of
  `quickstart.md`), `include` / `exclude`, `refresh`, beside R2C with `mcp_server(extensions=)`,
  the client; the v1 limits (ASCII names, nearest `SKILL.md`, a file is sent whole, the refresh
  limits), the Beta note, and that `[mcp]` now brings PyYAML. Invented names only.
- [X] T073 [P] `ARCHITECTURE.md`: the `mcp/skills/` rows, and the rule that it imports nothing of
  `ext_r2c`.
- [X] T074 [P] `CHANGELOG.md`: Added (the skills extension, the client, `mcp_server(extensions=)`,
  PyYAML in `[mcp]`). No Changed entry: the standard does not change.
- [X] T075 [P] The ADR `docs/design-docs/skills-frontmatter-and-nesting.md` (Context, Decision,
  Alternatives, Consequences: Better / Worse / Must now be true) for D1 (a YAML reader in
  `[mcp]`) and the nearest-`SKILL.md` rule; a row for it in the `AGENTS.md` Docs table (the file
  stays under 150 lines).
- [X] T076 [P] Reconcile older docs, grepping `skill` / `Skills` over `README.md`,
  `ARCHITECTURE.md`, `AGENTS.md`, `docs/`, `python/README.md` and `specs/001`–`004`:
  - in `docs/design-docs/one-remote-two-doors.md` and `docs/whitepaper.md`, add a dated note
    (2026-11-21, never a rewrite of the body) for the three differences of the plan: the URI form
    (`skill://<skill-path>/…`), no `exclude_files`, and no link is ever followed;
  - in completed specs, annotate with a dated note any "left open for Skills" statement that 005
    settles;
  - fix any current-tense statement that says skills are unbuilt.
- [X] T077 `WORKSTATE.md`: spec 5 done (counts, commit), the "Next" bullet moved on, and the
  waiting-for-approval list updated.
- [X] T078 Outside review of the diff `4bc6c9d..HEAD` (the 005 phases): launch the
  `code-reviewer` and the `security-reviewer` agents **in one message**, each with a
  self-contained brief (the diff range, what the feature does, the output contract: findings
  ranked by severity with file and line). Focus the security reviewer on path handling, the
  dictionary lookup, the safe read, the YAML reader and the client's verification; the code
  reviewer on correctness, the first-cut-to-final replacement of phase 5, and the tests'
  strength. For each finding that holds: write a failing test, fix, and record it under "Outside
  review" in `research.md`. State what was left on purpose.
- [X] T079 Final verification, `quickstart.md` sections 1–4, on **Python 3.11, 3.12 and 3.13**
  (**SC-008**): build; the whole suite on each; the core-only, A2A-only and MCP-only runs;
  `uvx ruff check --select F src tests`; the leak scan. Record the test counts.
- [X] T080 Fill "Notes: where reality differed" below, tick `checklists/requirements.md`, then
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

Kept as a running list while the phases are built; T080 closes it.

**Phase 2 (2026-11-22)**

- **The reader is stricter than R7 drafted.** Anchors, aliases and the depth cap are refused while
  the document is composed (a document that is too deep or has an alias is never built), not after
  it is loaded. Numbers and booleans are JSON-like only (`true`/`false`, `3`, `-4`, `1.5`,
  `2.5e3`), so `yes`, `no`, `on`, `off`, `12:30`, `0755`, `1_000` and `2026-01-02` stay the text the
  author wrote. It is a pure-Python `SafeLoader` subclass with its resolvers and constructors cut to
  a whitelist. R7 and the ADR (T075) record the grammar.
- **`Catalogue.build` folds the authority for all three kinds** (skill, file, directory), as R3
  says for skills. `Team/x` and `team/x` clash; `Team/x` and `team/y` are different URIs and are
  both served. The contract's wording ("first segments differ only in case") is read that way: the
  hazard is one URI after the authority is normalised, not two skills under similar authorities.
- **Directories are derived from files only** for now. An empty directory has no file to derive it
  from; T067 adds it (a `dirs` field on `SkillRecord`, test first).
- **Code removed because a test could not reach it.** The mutation run found four checks that other
  checks already made redundant: the cursor's alphabet regex (the canonical re-encode rejects the
  same strings), `isascii` on the cursor digits (the ASCII decode before it rejects non-ASCII), the
  catalogue's per-name clash check inside `_directories_of` (`_claim` raises with the same message),
  and the reader's `len(front)` shortcut. Equivalent mutants left: a cursor cap of 257 (no valid
  unpadded cursor has that length) and `\Z` against `$` in the number patterns (a plain scalar never
  ends in a newline).
- **Two test slips found by the first run.** The size-cap test appended its extra byte after the
  closing fence (`x---`), so the file was unclosed, not too large; fixed in the test. The
  `__reduce__` of `SkillsError` and `CursorError` was written before its pickle test; the tests were
  added after and proven by removing it (both mutants killed).
- **The mutation harness had its own bug.** It first copied the source tree, which has no
  `schema/` (the wheel carries it), so the conftest summary hook crashed after the tests had passed
  and every survivor looked killed. It now copies the installed wheel and reads the pytest summary,
  not the exit code. The scratch harness is not committed.
- Mutation result: 109 mutants of the six modules, 108 killed; the survivor is the no-change
  control.

**Phase 3 (2026-11-22)**

- **The include / exclude filters are in the scan already.** T026 did not ask for them (phase 6
  does), but `scan_roots(folders, include, exclude)` takes them from the first cut because T023
  names that signature. They match the last segment of the skill path with `fnmatch.fnmatchcase`,
  exclude wins, an empty `include` means all, and a skill the filters drop is never read, so a broken
  `SKILL.md` that is filtered out is not an error. `TestFilters` covers them. What phase 6 still
  owes: the constructor arguments, their validation, and the "nothing left after the filters" error.
- **The constructor is `SkillsExtension(folders, *, ttl_ms, cache_scope)` for now.** `include` and
  `exclude` arrive with phase 6, `directory_read` and `page_size` with phase 8; none is accepted
  before its behaviour exists, so no argument is silently ignored. The settings are not validated
  yet (phase 6).
- **`settings()` says `{"directoryRead": False}`**, as decided; the two declaration tests assert
  `False` and phase 8 flips them. `SkillFile.read()` has no branch yet for a URI that has left the
  catalogue (phase 6 adds it with `refresh`); today the lookup is a plain key access.
- **Most tests passed on their first run once the code existed**: 59 of 60. The exception was a
  miscount in my own test (12 files, not 13). Because the tests were written before the code and the
  first run was green, each was proven by mutation, not by the green: 75 mutants over `_scan.py`,
  `_read.py` and `extension.py`, 68 killed. A mutant that makes the read of a pipe hang was killed by
  the 240 s timeout of the harness, which is how a hang shows up there.
- **The seven survivors are the control and six equivalents, kept and not killed.**
  - `fnmatch.fnmatch` for `fnmatchcase`: the two differ only where the platform folds case, which
    POSIX does not. The tests pin case-sensitivity (`test_patterns_are_case_sensitive`).
  - Dropping the `is_symlink()` test in `_entries`: the later `is_file/is_dir(follow_symlinks=False)`
    tests refuse links too. It stays because phase 5 reports each link as left out, and the report
    needs the first test.
  - `sorted` in `_entries`: the catalogue sorts skills and files again. It stays so that which build
    error is raised first does not depend on the order the file system returns names in.
  - Reading `SKILL.md` a second time instead of reusing the bytes already read: same bytes.
  - The skill's name taken from its folder instead of the frontmatter: the same until phase 6, which
    makes a mismatch an error.
  - Dropping the size comparison in `read_file`: the digest covers it. The comparison stays as the
    cheap first refusal and as the home of the phase 5 `size + 1` bound.
- **By hand (T030).** Quickstart section 5, server side, on the installed wheel: `skills/list` shows
  `skill://refunds/SKILL.md` with `ttlMs` 300000 and `cacheScope` private, `resources/read` returns it
  as `text/markdown`, and after the file is edited the next read is `-32603` with the "refresh them"
  message. The fixture's own nested skill is `skill://team/billing/refunds/SKILL.md`, not the
  quickstart's flat one. `refresh()` is phase 6.

**Phase 4 (2026-11-22)**

- **T034 failed as expected**: the file stopped at collection with `cannot import name
  'DirectoryEntry' from 'ext_r2c.mcp.skills'`, the first of the new names.
- **Two files, not one.** The client is `client.py`, and the two numbers the server (phase 6) and the
  client both need, 512 files and 16 MiB, live in a new `_limits.py` (`MAX_FILES`, `MAX_BYTES`), so
  neither side copies the other's constant. It is not in T035; it is two lines.
- **The SDK's read cache would have served a stale file.** `Client.read_resource` takes
  `cache_mode="use" | "refresh" | "bypass"`. With the default `CacheConfig()` it caches a read when the
  server sends `ttlMs` (or `default_ttl_ms > 0`), and a server that sends one would make a second
  `read()` return the first answer without a request, so the bytes verified would not be the bytes the
  server now holds. The client reads with `cache_mode="bypass"`, and a test serves `ttl_ms=60_000` to
  prove two reads are two requests. The SDK server's own default is `ttlMs: 0`, so a plain test would
  never have shown the problem (`research.md` R13).
- **A read answer with no `contents` cannot come from the SDK server**, which validates its own
  results ("Handler returned an invalid result"). That case, and a `pydantic.ValidationError` from
  the typed request, are tested through a stub client (`_Stub`, `_read_through_stub`), not through
  `Lying`. A `ValidationError` becomes `SkillRefused("response")` with `from None`, so the file's
  content is never echoed through pydantic's message.
- **`get(uri)` checks that the answer is for the skill asked.** T038 did not say so; a server that
  answers `skills/get` for another skill is refused with `response`, naming the URI requested.
- **The frontmatter comparison is strict.** `True` is not `1`, `2 == 2.0`, lists are ordered, and
  dictionaries must have the same keys both ways. That is the same grammar as the reader (R7), so a
  value the reader would call a boolean cannot pass as a number on either side.
- **The bound before decoding** is on the wire form: for `text`, `len(text) > size`; for a `blob`,
  `len(blob) > 4 * ((size + 2) // 3)`, the base64 length of `size` bytes. Reasons are fixed text and
  never echo file content.
- **The `declaration` check uses what the SDK lets through.** `ServerCapabilities.extensions` is
  `dict[str, dict]`, so a non-dict setting cannot reach the client and is not tested; the SDK always
  declares `resources`, so "extension declared but no `resources`" is tested through the stub too.
- **Deferred to phase 8:** the repeated-`nextCursor` guard (T064 and T069 already say so for
  `list()` and `list_directory()`). Today `list()` follows `nextCursor` until it is `None`. **Not
  refused:** two entries with the same URI in one listing; R13 does not list it, and they are two
  `SkillItem`s with one key.
- **The tests passed at once once the code existed, apart from four mistakes in the tests**
  (an `edit()` helper whose parameter `uri` clashed with a field; two cases that raised inside the
  harness's `connected()` and escaped as an `ExceptionGroup`; a "16 MiB exactly" case whose files
  summed to more). Because they were written before the code and the first run was green, each was
  proven by mutation, not by the green: 115 mutants over `client.py` and `_limits.py`, 114 killed; the
  one survivor is the control with no change. Mutation found six gaps in the tests, all closed:
  the reason fragments, the order of files, the nested `extra-key`, a text one byte short in
  multi-byte characters, a blob one byte short, and the rounding of the blob bound; and one branch
  of `_same` that nothing could reach (a numeric case after the `bool` case), which was removed.
- **Numbers.** 136 tests in `test_skills_client.py`; the suite is 1454 passed; replay counts are
  unchanged (A2A 31/29/3, MCP 14/13/1).

**Phase 5 (2026-11-22)**

- **T044 failed where it was meant to, and passed where it was said it might.** Against the first-cut
  read: 87 passed, 10 failed and 28 errored (the missing `_read._SAFE` flag, which the reader tests set).
  The failures were the missing `left_out` and log records, the 256 MiB file read whole into memory (a
  peak of 268,541,721 bytes against a 32 MiB bound), the pipe that took 2.99 s to refuse, and the pipe
  holding the very bytes that was served (`DID NOT RAISE`). A probe showed the first-cut read served
  through all five kinds of swap. The 32-row URI table, the audit and the digest checks passed at once,
  as T044 predicted: that is the SDK's exact matching plus the first cut's digest check, so they were
  proven by mutation (below), not by the green.
- **The read walks from `/`, not from the skill folder.** Each name is opened with `O_NOFOLLOW` relative
  to the folder opened before it, so a link anywhere on the way, above the root too, is refused by the
  kernel and not by a check that could lose a race. A folder that is only passed through is opened with
  `O_PATH` where there is one, so no read permission on an ancestor is needed. The last name is opened
  `O_NONBLOCK`, so a pipe never makes the open wait for a writer. Where `O_NOFOLLOW` or `dir_fd` is
  missing (Windows) each name is `lstat`ed first; that path is tested on Linux by switching `_read._SAFE`
  off, and **has not run on Windows**: there is no such runner.
- **`fstat` is observable in one test only.** A non-blocking read of a pipe nobody writes returns end of
  file at once, so without the `S_ISREG` check a plain pipe fails on the length anyway. The test that
  needs it opens a pipe `O_RDWR`, fills it with exactly the bytes of the entry and closes it from a timer
  after 3 s; without the check the read returns those bytes and the digest matches.
- **T047 said the `size + 1` bound could only be checked by reading the code. It is tested.** Reading
  `size` instead of `size + 1` is killed by the 5 MiB growth test (a file that grew by appending would be
  served as its old self), and reading without a bound is killed by the 256 MiB sparse file with a
  `tracemalloc` peak under 32 MiB.
- **`LeftOut`**: the order of the checks is symbolic link, hidden, undecodable name, not a regular file,
  so `.dotlink` is a link and `.dotpipe` is hidden, and a pipe with a name that is not text is reported
  for its name. A hidden folder is reported once and its content not at all. A skill's own entries are
  reported once (by the walk of its files), and so are the entries of a folder that holds no skill (by
  the search). A name that is not text is shown with `\xNN` for the bad bytes. The list is sorted by path,
  then reason, and is `ext.left_out` (also `ext.catalogue.left_out`); `LeftOut` is exported from
  `ext_r2c.mcp` and `ext_r2c.mcp.skills`.
- **Logging**: logger `ext_r2c.mcp.skills`; one `INFO` per skill (its URI, files and bytes, never a host
  path) and one `WARNING` per symbolic link, when the extension is built; nothing at import (checked in
  a `python -I` subprocess).
- **Mutation**: 59 mutants over `_read.py`, `_scan.py` and `extension.py`, tested by
  `test_skills_safety.py`; **54 killed and five not**. Not killed: the control; `_SAFE` forced on (it is
  already on where the kernel can refuse a link: equivalent); no length comparison (redundant, since a
  different length never has the same digest); the read loop without its limit test (`os.read(fd, 0)`
  returns nothing and the loop ends: equivalent); `FileChanged` with a text that names the working
  directory (the text is never sent: what goes on the wire is the fixed message, and the mutant that puts
  the folder in it is killed). "No digest comparison" is killed by `test_skills_serve.py` (same size, other
  bytes), not by the safety file.
- **Mutation found four gaps in the tests, closed with six new tests**: `_SAFE` silently off on Linux; a
  file larger than one 1 MiB piece (a read that stopped after the first piece); the order of "not text"
  and "not a regular file"; and `skills/get` answering for a host path (the folder, its `SKILL.md`, a
  `file:` URL, or a path relative to the root).
- **The URI rows are killed through registration, not through the package's own code.** The SDK matches a
  resource URI as an exact string, so `..`, `%2e%2e`, `?x=1`, `#f`, a backslash and `TEAM` never reach any
  code of the package. A mutant that registers `uri?x=1` as a second resource, and mutants of `skills/get`
  that drop a query or a fragment, match by prefix or look up the folder path, are killed by the table; a
  mutant inside `_serve` could not be, and none is needed.
- **Left for phase 6**: the scan still reads each file whole to hash it, before any limit is checked; phase
  6 checks the sizes from `stat` against 512 files and 16 MiB first. SC-003's row "a skill the filters do
  not serve" belongs there too.
- **Numbers.** 131 tests in `test_skills_safety.py` (125 first, six added by the mutation run); the suite
  is 1585 passed; replay counts are unchanged. The stale docstring in `test_skills_scan.py::TestLeftOut`
  ("phase 5 makes the scan report them") was updated.

**Phase 6 (2026-11-22)**

- **T052 failed where it was meant to.** Missing export of `SkillsError`, no `include` / `exclude`
  arguments, no `refresh`, no settings checks, no limits, "nothing left" not raised. **Passed at once**:
  "no frontmatter" and "unreadable name" in the filters test (the filters already ran before parsing: guards
  for the mutants of T056), `test_there_are_at_least_twenty_cases`, and the two "accepted forms of
  `folders`" tests (phase 3 behaviour).
- **`page_size` and `directory_read` are not checked here.** T050 lists `page_size` 0 or a bool, but the
  constructor has neither argument until phase 8 (T064–T071), so those two checks and their cases move
  there. Every other setting is checked, as a `ValueError` naming it, **before** the folders are scanned.
- **"Nothing to serve" is about all the roots, not one.** An empty root beside a good one is fine. With
  nothing at all, `SkillsError.folder` is every root given, joined by `", "`; the reason says whether there
  was no skill (`no skill found`) or the filters left none (and names `include` and `exclude`).
- **Which path an error names.** A root is named as the owner gave it, made absolute when the extension is
  built (so a later `chdir` changes nothing; a relative folder is tested with `monkeypatch.chdir`). A skill
  or a folder below a root is named by the path the scan read, with links resolved. The contract says so.
  Reasons never quote file text and never hold a host path: an `OSError` is `error.strerror`
  ("Permission denied"), because `str(error)` ends with the path.
- **The name is checked before it is compared with the folder**, so `Thing` in a folder `Thing` is refused
  for being `Thing`, not for the folder. The test table first used the folder `thing` and the fragment
  `name must be`, which both messages hold; mutation showed the rule on names was never tested (below).
- **Limits are refused at the first file past them**, not counted whole: `has more than 512 files` and
  `holds more than 16777216 bytes`, from `stat` sizes while nothing but `SKILL.md` has been read (a test
  spies on the walk: 513 items listed, the other 88 files never looked at). T050 said "513 files fails";
  it does, with "more than 512". A `SKILL.md` over the limit is refused for its size before it is parsed.
  Each hash read is bounded by what is left of the 16 MiB, so a file that grew after `stat` cannot take the
  skill past the limit unseen (a test grows files while the scan runs, one and two at a time).
- **`refresh(server=None)`.** The new catalogue is built whole and swapped in with one assignment; a failed
  scan keeps the old one. New file URIs are registered with `server.add_resource` **before** the swap, so
  `skills/list` (what a client follows) never names a file the SDK would not find; for an instant
  `resources/list` can show a new file that a read still refuses (the read looks in the old catalogue).
  Until a server has asked for the resources (`resources()`), `_registered` is `None` and nothing is "new",
  so an extension that has not been served yet refreshes without a server; the first cut demanded one and
  was wrong. A removed file stays in `resources/list` (the SDK cannot remove one) and a read of it is
  `-32602`. **No lock**: a signal handler that calls `refresh` could deadlock on a lock the interrupted
  request holds, and the swap is one assignment, so a request sees one scan from end to end.
- **The burst test needed a pause per request.** With none, the writer thread got 2 refreshes in 150
  requests and proved nothing; each request now sleeps 1 ms, the test insists on at least 20 refreshes and
  on both digests having been seen, and it stops at 3000 requests.
- **Mutation: 68 mutants over `_scan.py`, `_settings.py`, `extension.py` and `_catalogue.py`, tested by
  five files; 68 killed.** The first full run killed 59 and **left nine**: the rule on names (six mutants:
  capitals, `--`, a leading or trailing hyphen, a prefix match, the order of the two rules), the reason of an
  `OSError` holding the path (`str(error)`), a root error named by its resolved path (nothing in a
  temporary folder is a link), and the `SKILL.md` read bounded at the limit instead of one past it. All
  nine were gaps in the tests, none equivalent. Closed: names are tested in a folder that has the very name
  (so only the rule can refuse them) against a fragment only the rule says; every "cannot be read" case
  must end in `Permission denied` with no `Errno`; an unreadable root that is a link is named as given; an
  oversized `SKILL.md` with no frontmatter is refused for its size. The two T056 mutants (filters after
  parsing, and the catalogue cleared then filled) are killed by the filter test and the burst test. One
  mutant not written because it is equivalent: `resources()` as `set(files)` instead of the union with what
  was registered, which differs only when it is called twice.
- **Two runs of the mutation harness proved nothing and are not counted**: the first was given a label that
  matched no mutant (0 run), the second stopped at a mutant written without its replacement text.
- **Numbers.** 90 tests in `test_skills_build_errors.py` (42 cases in the table, 20 required), 17 in
  `test_skills_refresh.py`, 11 added to `test_skills_scan.py`; the suite is 1703 passed (was 1585); replay
  counts unchanged. `verify.sh` is green on core only, a2a only and mcp only; `ruff --select F` is clean.

**Phase 7 (2026-11-22)**

- **T060 failed where it was meant to.** Ten of 14 tests failed with `TypeError: MCPServer() got multiple
  values for keyword argument 'extensions'` (`mcp_server` passed its own `extensions=[extension]` and the
  caller's landed in `**mcp_server_kwargs`). **Four passed at once**: the skills-only server, the hand-built
  server with a plain tool (the call and the wire), and "without `extensions` the server is what it was".
  They do not go through `mcp_server`, so they pin what the SDK and phases 3–4 already did; each is proven
  by a mutant below, not by the green.
- **T061 is five lines.** `extensions: Sequence[Extension] = ()`, served as `[extension, *extensions]`; the
  order is observable as the order of `server._lowlevel_server.extensions`. A list, a tuple or any
  sequence works. Two extensions with one identifier fail with the SDK's own
  `ValueError: Extension '...' is already registered`; the build's `except` already gives R2C its `ttl`
  back, so the same `R2CExtension` can be built into a server again (tested for a duplicate skills
  extension and for R2C handed in twice).
- **R2C's middleware is only visible on `tools/list`.** The first mutant "R2C loses its middleware when
  extensions are given" **survived** the question flow and the wire comparison: the middleware gives each
  tool its own input schema on `tools/list`, which no flow of spec 004 asks for. A test compares the tool
  list of a server with skills and one without (a `ToolSpec` and a `SourceTool`); it kills the mutant.
- **The R2C wire is compared on `tools/call` only.** The record of a session with skills also holds
  `skills/*`, `resources/read`, the initialisation and `server/discover`, which the baseline has not;
  `tool_calls()` keeps the `tools/call` requests, the responses to them and the notifications, and
  `normalise` of `mcp_harness` renames the ids. The skills requests are made **while the R2C call is
  paused** (between its two rounds), so the test also shows a paused call survives them. The comparison
  would be vacuous if the skills never crossed the wire, so it also asserts that `skills/list` and
  `resources/read` are in the same record.
- **The identifier is spelled out in the tests**, `"io.modelcontextprotocol/skills"`, not imported from
  `_wire`: the first draft imported it, which would have let a mutant that changes the constant agree with
  itself, so it was changed before that mutant ran (and is killed). Each declaration is also checked for
  its own content (`{"revision": 1}` for R2C; the one key `directoryRead` for skills), since a mutant that
  gave skills R2C's `revision` survived a check of the keys alone.
- **`mcp_only.py` runs the round trip with the SDK's in-memory `Client(server)`** (T005 test 9 showed it
  carries the typed requests): lists, loads and reads a skill from a temporary folder through
  `SkillsClient`, builds the R2C-plus-skills server and checks the order of the declarations, and checks
  that no `a2a`, `langchain` or `langgraph` module was loaded. With `python -I` the tests folder is not on
  the path, so it uses no helper of `tests/`. A line `Serving skill ...` is printed on stderr: building an
  `MCPServer` configures logging at INFO (the package itself only logs, as phase 5 said).
- **Mutation: 11 mutants (`server.py`, `_wire.py`, `extension.py`), tested by `test_skills_compose.py`; 11
  killed**, after the two gaps above (the middleware, the content of the declaration) were closed. Six of
  the first eight mutants were not run at all: five had a search text that is also in the docstring and one
  a constant written wrongly (the harness refuses a text that does not occur exactly once); they were
  rewritten, not counted. The three that guard the tests that passed at once (the extension intercepts
  `tools/call`, adds a tool, adds R2C's `revision` to its declaration) are killed by those tests.
- **Numbers.** 15 tests in `test_skills_compose.py`; the suite is 1718 passed (was 1703); the tests of specs
  001–004 are unchanged and both replays report the same counts (A2A 31/29/3, MCP 14/13/1).

**Phase 8 (2026-11-22)**

- **T066 failed where it was meant to**: `skills/list` gave one page (no `nextCursor`, no `page_size` argument),
  discovery said `directoryRead: false`, `resources/directory/read` was `-32601` because nobody bound it, and
  `SkillsClient` had no `list_directory`. **Five tests passed at once** and are proven by a mutant each
  (`mutants_phase8b`, 6 mutants, 6 killed): a directory is not a file to read (the client does not send a
  folder URI to `resources/read`), directories are not registered as resources, distinct cursors that end are
  not a loop, a record with no `dirs` gives the directories it always gave, and a hidden or linked folder is
  not a directory.
- **A cursor is good for one listing of one catalogue** (decided here, written in R9). The plan said a cursor
  carries the generation. With only that, the cursor of `skill://docs` is also a valid position in
  `skill://docs/a` and in `skills/list`, so a mix-up is a silent skip or repeat of children, not an error. A
  directory cursor is now scoped by `<generation>-<first 16 hex of SHA-256 of the URI>`; `skills/list` by the
  generation alone. Example: with `page_size=3`, the cursor after the first page of `skill://refunds` is
  refused (`-32602 "Invalid cursor"`) when sent to `skill://refunds/templates` or to `skills/list`. The hash is
  a label, not a secret. An empty-string cursor is a cursor and a bad one; only `None` is the first page (a
  mutant that treats `""` as absent is killed).
- **`SkillRecord.dirs` is a new last field, default `()`** (T067), so every record built by hand in the tests
  of phases 3–7 still works and gives the directories it always gave. The scan appends each folder it enters,
  empty ones too; the catalogue sorts and de-duplicates them and derives the records of the folders above each
  one. A folder that has the URI of a file is still refused (`_claim`). A hidden folder and a linked folder
  are never entered, so they are not directories.
- **A nested `SKILL.md` is a file named `SKILL.md`**, in `resources/list` and in a directory alike: one helper
  (`_named`) gives the frontmatter's name and description only to the skill's own `SKILL.md`. A mutant that
  gave them to any `SKILL.md` is killed.
- **Two bugs of my own tests, found by the first green run, not by the code.** (1) A test read only the first
  page of `skills/list` with `page_size=2` and expected three skills; it now collects every page and asserts
  three. (2) A test about one directory's cursor expected the wrong second page of `REFUNDS` (with
  `page_size=3` it is `notes.txt`, `templates`); the expectation was fixed, not the code.
- **A phase-4 test went red and was updated, not weakened**: `test_a_skills_server_is_declared_and_says_whether_it_reads_directories`
  expected `directoryRead: false` by default, true only while the method did not exist. It now expects the new
  default (`True`) and has a second case for `directory_read=False` that expects `False` on the wire and in the
  client.
- **A surviving mutant, then killed: "a linked folder is walked".** Removing the scan's rule for a symbolic
  link, and walking a link as a folder, still left the link out, because `_reason` has a second rule: a
  directory entry that is neither a real directory nor a real file (`follow_symlinks=False`) is "not a regular
  file". That is two layers of defence, not a hole in the test; the mutant now removes the three of them and
  is killed. Both layers stay.
- **Mutation: 40 mutants in `mutants_phase8.py`, 40 killed**, plus the 6 of `mutants_phase8b.py` for the five
  tests that were green at once. None of the 46 was left alive.
- **Residual risks, not closed** (R10): the number of directories is not capped (the limits are 512 files and
  16 MiB, so a skill with a million empty folders is walked and held); the client catches a **repeated**
  cursor, not an endless run of distinct ones, so a caller that must bound a hostile server wraps the call in
  its own timeout. Both go to the outside review of phase 9.
- **Numbers.** `test_skills_pages.py` and `test_skills_directory.py` are new; the suite is 1888 passed (was
  1718) on Python 3.11. `verify.sh` is green on core only, a2a only and mcp only; ruff is clean.

**Phase 9 (2026-11-22)**

- **Docs (T072–T076).** `python/README.md` (a Skills section: serve, read, limits, what is left out),
  `ARCHITECTURE.md` (the `mcp/skills/` layout and its import rule), `CHANGELOG.md`, the ADR
  `docs/design-docs/skills-frontmatter-and-nesting.md` (decisions 1–5), and dated notes in the older docs
  that said Skills was "in 004" (`one-remote-two-doors.md`, `whitepaper.md`, the 002 and 004 specs and the
  004 contract). `AGENTS.md` got one Docs row and stays at 67 lines.
- **The outside review (T078).** A code reviewer and a security reviewer, both with no memory of the work,
  read phases 1 to 8. Each finding was checked against the code; the ones acted on each got a test that
  failed first. The record, with what was **left on purpose** and why, is `research.md` R17. In short:
  - the scan is bounded (32 deep; 1024 folders in a skill; 1024 searched per root), refused before the
    folder is read;
  - a name with a control character, a line or paragraph separator, a bidirectional control or a backslash
    is left out as `"unsafe name"`, and shown escaped in `left_out` and in the log;
  - only the errors that mean "the file is not what the scan saw" answer "changed on disk"; any other read
    error is `FileUnreadable`, answered `-32603` with a fixed message and one logged warning;
  - the client refuses an entry no server could have served (name and description lengths, a file not
    strictly inside the folder, an odd path segment, the same skill listed twice) and no longer requires
    the `skill://` scheme.
- **Deviations from the triage** (also in R17): the reason is `"unsafe name"` and a backslash is unsafe on
  both sides; a `searched` counter was added to `_search` because depth alone does not bound a flat folder
  of empty folders; the `\U` branch of `_escape` was removed as dead code (no unsafe character is above
  `U+FFFF`).
- **A phase-8 test went red and was updated, not weakened.** `test_distinct_cursors_that_end_are_not_a_loop`
  encoded "the same entry four times, all returned". Refusing a skill listed twice in one listing is a
  deliberate review fix; the test now asserts one returned skill and three refusals with `check="entry"`,
  and still proves the cursors are not mistaken for a loop.
- **One false kill, found and fixed.** The first run of the review mutants had a red baseline (the test
  above), so the mutant that replaced `endswith("/SKILL.md")` with a looser check was "killed" by the red
  test, not by a test of it. On a green baseline it survived: both branches refuse the entry, but with
  different `check` values (`resources`, not `entry`). A `SKILL%2Emd` row was added to the entry table; the
  mutant is now killed for the right reason. Lesson: confirm the baseline is green before a mutation run.
  One mutant of mine was also wrong (`errno.ELOOP, ` occurs twice in `_read.py`); it was rewritten to
  name the line it means.
- **Mutation: 70 mutants of the review fixes, 70 killed** (every limit one step either way, every
  character class, every errno of the read, every client rule).
- **Numbers (T079).** The suite is **2034 passed** (was 1888) on Python 3.11, 3.12 and 3.13, run against the
  installed wheel; core only, a2a only and mcp only are ok; `ruff check --select F` is clean (CI's own
  rule; there is no other ruff config). The replays are unchanged: R2C examples 46 valid, 20 invalid, 1
  unknown kind ignored, 102 objects round-tripped; A2A 31/29/3; MCP 14/13/1.
- **Open for the maintainer, not done here.** (1) Whether to rename the generic `Refused`, `LeftOut` and
  `DirectoryEntry` (approved contract, exported names). (2) Whether to walk the tree by descriptor
  (`scandir(fd)`), which closes the race that can show a folder's names; a refactor of `_scan.py` and
  `_read.py`. (3) Whether a 16 MiB blob over HTTP is refused by the SDK's event reader; unverified.
