# Implementation Plan: MCP Skills (`ext_r2c.mcp` skills extension)

**Branch**: `main` (folder `specs/005-mcp-skills`) | **Date**: 2026-11-21 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-mcp-skills/spec.md` (approved by the maintainer on
2026-11-21, decisions D1–D6 as written)

## Summary

Serve MCP Skills (`io.modelcontextprotocol/skills`, Beta, base protocol 2026-07-28) from the
`ext_r2c.mcp` subpackage, as a second MCP SDK `Extension` that is **not** R2C. It has two halves.

**Server side**
- `SkillsExtension` scans folders for `SKILL.md`, reads the YAML frontmatter, hashes every file,
  and holds one immutable *catalogue*. It serves `skills/list`, `skills/get`, the files through
  the SDK's own `resources/read`, and `resources/directory/read` when `directory_read` is on.
- A request URI is looked up as a whole string in the catalogue. No path is ever built from a
  request, and a read opens the file again, per component with `O_NOFOLLOW`, and sends only the
  bytes whose size and SHA-256 match the entry.
- `mcp_server` gains an `extensions=` keyword, so the extension sits beside `R2CExtension`; on a
  hand-built `MCPServer` it needs no helper.

**Caller side**
- `SkillsClient` wraps a connected MCP SDK client. It checks the server's declaration first,
  validates every entry on its own, reads a file only when asked and only if the entry lists it,
  and refuses anything whose size, digest or frontmatter does not match. It caches nothing and
  writes nothing.

**Tests**
- Real in-process round trips through the MCP SDK's own client and server, with fixture folders
  built in `tmp_path` from invented content, on the installed wheel.
- Nothing in `standard/` changes: Skills is not R2C.

Research found these gaps and limits in the MCP SDK 2.3 and the extension
([research.md](research.md)):
- `Extension.resources()` is read once and a resource cannot be removed, so a refresh can add
  files but not take them away ([R1](research.md#r1-what-the-sdks-extension-gives-us),
  [R5](research.md#r5-how-entries-are-held-and-what-a-refresh-can-do-d2)).
- **A client request must be a typed class**: an untyped request with dict params drops `uri`
  ([R2](research.md#r2-typed-requests-and-results)).
- The SDK compares the raw request string with the registered strings, so `..` and its encodings
  never reach our code; our own check is the dictionary lookup
  ([R3](research.md#r3-uris-taken-literally-compared-to-a-dictionary)).
- Only an `MCPError` raised in `read()` keeps its code on the wire
  ([R4](research.md#r4-a-read-opens-once-hashes-once-sends-what-it-hashed)).
- The SDK brings no YAML reader, so PyYAML joins `[mcp]`, vetted on the day it is added
  ([R7](research.md#r7-the-frontmatter-reader-d1-and-the-pyyaml-vet)). **PyYAML 6.0.4 was
  uploaded on 2026-11-20, one day before this plan**; T001 repeats the vet before the dependency is
  added.
- `mcp_server` cannot take a second extension through `**kwargs`
  ([R12](research.md#r12-composition-and-imports)).

## Technical Context

**Language/Version**: Python ≥ 3.11 (CI: 3.11, 3.12, 3.13)

**Primary Dependencies**:
- runtime core: `pydantic>=2` and `jsonschema>=4`, unchanged;
- extra: `[mcp]` = `mcp>=2.3,<3` and **`PyYAML>=6.0.3,<7`** (new, D1; no dependencies of its
  own; R7 has the vet);
- dev group: `PyYAML>=6.0.3,<7` is added beside `mcp` (the group lists what the extras bring).

**Storage**:
- None written. The server reads the owner's folders and never writes (FR-015).
- The catalogue (entries with digest and size, no bytes) is held in memory and replaced as a whole
  by `refresh()`. The client keeps nothing across connections and nothing on disk (FR-023).

**Testing**:
- pytest on the installed wheel. Async tests use `asyncio.run` through the harness of spec 004
  (`tests/mcp_harness.py`, `tests/mcp_transport.py`).
- Round trips use the MCP SDK `Client` against an `MCPServer` with the extension, over the
  in-process streaming transport. Pure units (reader, scan, cursor, URIs) call the installed
  package directly.
- Fixture folders are built in `tmp_path` by `tests/skills_fixtures.py`; symbolic links and
  named pipes are created there too (the tests skip where the platform cannot).

**Target Platform**: CPython on any OS; CI on Linux. Windows has no `O_NOFOLLOW` or `dir_fd`, so
the read falls back to `lstat` per component, and the digest check stays the backstop (R4).

**Project Type**: library (the `mcp.skills` subpackage of `ext-r2c`)

**Performance Goals**:
- A scan hashes every served file once. A skill is at most 512 files and 16 MiB, so a folder of
  tens of skills scans in well under a second on CI.
- A read costs one open per path component, one bounded read and one hash, in a worker thread so
  the event loop is not blocked.
- The skills suite finishes in under 30 s on CI.

**Constraints**:
- the import rules (constitution VIII): `mcp/skills/` imports **nothing** from `ext_r2c`, not even
  core (an AST test); the YAML reader is `yaml` from the `[mcp]` extra;
- no network port in tests; a public repository: invented names, `example.com`, no local paths;
- the server never writes, never follows a link, never builds a path from a request;
- the client never acts on frontmatter (`allowed-tools` and the rest are data);
- the Beta wire shapes live in one module, `_wire.py` (R16).

**Scale/Scope**:
- 11 modules in `mcp/skills/`, 13 public names ([contracts/skills-api.md](contracts/skills-api.md));
- one small change in `mcp/server.py` (the `extensions` keyword) and one in `mcp/__init__.py`;
- 8 new test files, 1 new fixture module, 3 changed existing tests or scripts.

## Constitution Check

*GATE: checked before Phase 0, re-checked after Phase 1.*

| Principle | How this plan meets it | Status |
|---|---|---|
| I. Schema is the single source of shape | Skills has no R2C shape. The wire shapes of the beta text are written once in `_wire.py` and checked against the examples of the contract; `standard/v1/schema/` is untouched | pass |
| II. Wire examples are the shared test suite | There is no R2C rule to exemplify, so no file is added to `standard/`; the tests carry their own fixture folders and the contract's JSON (spec, Assumptions) | pass (n/a) |
| III. Remote's logic unchanged | The extension serves folders; it touches no tool, no source and no interceptor. `mcp_server(...)` without `extensions=` behaves as in spec 004 (the 004 suite runs unchanged, SC-006) | pass |
| IV. An extension, never a protocol | It is MCP's own extension, declared in `capabilities.extensions` with its own id; no core change; a client that does not know it sees ordinary resources (story 1, scenario 5) | pass |
| V. Approval never answered by a model | No approval is involved. The client interprets no frontmatter and grants nothing (`allowed-tools` is data), so a skill cannot approve for the caller | pass (n/a) |
| VI. Public, neutral data | Fixtures use invented skill names and text; links, pipes and a binary file are made at test time; leak scan per commit | pass |
| VII. Test first, against the built artifact | Every phase starts with failing tests on the installed wheel; round trips use the real MCP SDK client and server; the tampering tests include a server that lies | pass |
| VIII. Small core, bindings behind extras | Core is unchanged; PyYAML goes behind `[mcp]` only; `mcp/skills/` imports no `ext_r2c`; core-only, A2A-only and MCP-only runs stay | pass |
| IX. Versioned by URI | Skills has its own id; `standard/v1` is not touched; the Beta revision it was built against is named in `_wire.py` and the contract | pass |

Re-check after the Phase 1 design: still a pass. One addition is worth a line: principle VIII
says bindings import core, and `mcp/skills/` goes further and imports nothing of ours, because
skills share no code with R2C (FR-016). This is stricter than the rule, not a violation. There is
no Complexity Tracking entry.

## Project Structure

### Documentation (this feature)

```text
specs/005-mcp-skills/
├── spec.md
├── plan.md                      # this file
├── research.md                  # R1–R16
├── data-model.md                # catalogue records, wire models, client types
├── quickstart.md                # validation guide
├── contracts/
│   ├── skills-api.md            # public names and signatures
│   └── wire-mapping.md          # what is put on the wire, and the errors
├── checklists/requirements.md
└── tasks.md                     # from /speckit-tasks
```

### Source code

```text
python/
├── pyproject.toml               # [mcp] += PyYAML>=6.0.3,<7; dev group the same
├── src/ext_r2c/mcp/
│   ├── __init__.py              # + re-exports of the skills names
│   ├── server.py                # mcp_server(..., extensions=())
│   └── skills/
│       ├── __init__.py          # public names; the Beta revision named in the docstring
│       ├── _frontmatter.py      # the YAML reader: plain data only, shared by server and client
│       ├── _uris.py             # name rule, URI encoding, the "ends in <name>/SKILL.md" helper
│       ├── _content.py          # fixed MIME table; text or blob by the bytes
│       ├── _cursor.py           # opaque cursor: generation and offset
│       ├── _catalogue.py        # immutable records, SkillInfo, LeftOut, SkillsError
│       ├── _scan.py             # roots → catalogue: walk, filters, checks, hashes
│       ├── _read.py             # the safe read: O_NOFOLLOW per component, bounded, verified
│       ├── _wire.py             # the only module that knows the beta shapes
│       ├── extension.py         # SkillsExtension and the SkillFile resource
│       └── client.py            # SkillsClient and its types
└── tests/
    ├── skills_fixtures.py       # fixture folders in tmp_path (invented content)
    ├── test_skills_spike.py     # phase 1: the SDK facts the design leans on
    ├── test_skills_frontmatter.py   # foundation: the reader
    ├── test_skills_wire.py      # foundation: URIs, MIME, cursor, wire models
    ├── test_skills_catalogue.py # foundation: records and directories
    ├── test_skills_scan.py      # US1 (finding, describing), US4 (filters)
    ├── test_skills_serve.py     # US1: list, get, read end to end
    ├── test_skills_client.py    # US2: load and verify, with a server that lies
    ├── test_skills_safety.py    # US3: unreachable URIs, left out, changed on disk, never writes
    ├── test_skills_build_errors.py  # US4: every build error names the folder; bad settings
    ├── test_skills_refresh.py   # US4: refresh and its limits
    ├── test_skills_compose.py   # US5: beside R2C, alone, hand-built
    ├── test_skills_pages.py     # US6: the cursor
    ├── test_skills_directory.py # US6: resources/directory/read and the client's list_directory
    ├── test_packaging.py        # + yaml allowed, the subpackage scanned, no ext_r2c import there
    ├── core_only.py             # + no yaml loaded
    └── mcp_only.py              # + a skills round trip

docs and records:
├── python/README.md             # a Skills section
├── ARCHITECTURE.md              # the mcp/skills/ rows and its import rule
├── CHANGELOG.md                 # Added
├── WORKSTATE.md
├── docs/design-docs/skills-frontmatter-and-nesting.md   # ADR: D1 and the nearest-SKILL.md rule
└── docs/whitepaper.md, docs/design-docs/one-remote-two-doors.md
                                 # dated notes where they describe skills differently (see below)
```

**Structure decision:**
- One subpackage, `ext_r2c/mcp/skills/`, under the door's package as `ARCHITECTURE.md` fixes.
  The spec said "in `ext_r2c.mcp`"; a subpackage keeps the skills code apart from R2C's modules
  and lets one AST test say "imports no `ext_r2c`" for exactly that folder.
- `test_packaging.py` today scans only the top level of `ext_r2c/mcp/`. T002 makes the scan
  recursive so the subpackage is covered by the existing rule, then adds the stricter one.
- Test helpers stay in `python/tests/` and are not shipped. `Remote` (007) will reuse the
  fixtures.

## Key design decisions

The full reasoning is in [research.md](research.md).

1. **One `Extension`, three methods, one resource per file** (R1). The directory method is bound
   only when `directory_read` is on, so it is `-32601` when off.
2. **Typed requests and results on both sides** (R2). A client built on a raw dict request would
   silently send nothing.
3. **A request URI is a dictionary key, never a path** (R3). Segments are percent-encoded once at
   scan time; the first segment is a valid authority; segments that differ only in case there are
   a duplicate.
4. **A read verifies what it sends** (R4). Per-component `O_NOFOLLOW`, `fstat`, at most `size+1`
   bytes, digest of the bytes about to be sent; any difference is `-32603` with a fixed message.
5. **An immutable catalogue, swapped whole** (R5). A failed refresh keeps the old one. The SDK
   cannot remove a resource, so refresh adds files through the server, never removes them, and
   a removed file answers `-32602`.
6. **Filters first, checks after** (R6). The nearest `SKILL.md` on a path is the skill; a deeper
   one is a supporting file.
7. **A hardened, pure-Python YAML reader** (R7, D1). Plain data only; dates and `yes/no` stay
   text; duplicates, anchors and unknown tags are refused; 64 KiB cap.
8. **Defaults** (R9): `ttl_ms=300000`, `cache_scope="private"`, `page_size=25`; cursor =
   generation + offset, so it is stale after a refresh.
9. **The client is a loader** (R13, D6). Declaration first, each entry validated on its own,
   bounded before decoded, checked in a fixed order, never cached.
10. **Composition by one keyword** (R12): `mcp_server(..., extensions=[...])`.

## Changes outside the new package

- **`mcp_server`** gains `extensions: Sequence[Extension] = ()`. Existing callers do not change.
- **`standard/`**: nothing. No schema, no example, no README rule.
- **`docs/design-docs/one-remote-two-doors.md` and `docs/whitepaper.md`** describe `Remote`'s
  `skills=` before this spec fixed the details. Three statements differ from what 005 builds, and
  T076 annotates them with a dated note (the body is a record, not rewritten):
  - 005 serves `skill://<skill-path>/…`, where the skill path is the folder's path below its root
    (the ADR says `skill://<name>/<path>`);
  - 005 has no `exclude_files`; a per-file filter is a later spec if `Remote` wants it;
  - 005 never follows any symbolic link (the ADR says "no symlink leaving the root") and leaves
    every link out.
- **`AGENTS.md`** gets one row in its Docs table (the ADR); it stays under 150 lines.

## Delivery order (input to `/speckit-tasks`; one phase per go)

| Phase | Content | Done when |
|---|---|---|
| 1. Packaging, vet and spike | PyYAML re-vet (T001); `[mcp]` and dev group; the skeleton package; `test_packaging.py` made recursive with the no-`ext_r2c` rule; `skills_fixtures.py`; `test_skills_spike.py` pinning the SDK facts of R1–R4 | tests on the wheel pass; every spike fact holds, or the plan is updated first |
| 2. Foundation | `_frontmatter.py`, `_uris.py`, `_content.py`, `_cursor.py`, `_catalogue.py`, `_wire.py`, each with its unit tests | the reader refuses every case of R7 and keeps every field; URIs, cursor and wire shapes match the contract |
| 3. Serve and read a folder (US1, P1) 🎯 MVP | `_scan.py` (first cut), `_read.py` (first cut), `extension.py`: discover, list, get, read | SC-001: a real SDK client lists, gets and reads every file of three fixture skills; bytes equal the disk |
| 4. The caller's client (US2, P1) | `client.py`: declaration, entries, `list`, `get`, `load`, `read`; the refusals table with a server that lies | SC-002, SC-004 |
| 5. Nothing outside is served (US3, P1) | what the scan leaves out and reports; the hardened `_read.py`; the unreachable-URI table; changed-on-disk; never writes | SC-003 |
| 6. Filters, build errors, refresh (US4, P2) | `include` / `exclude`, every build error, settings checks, `refresh(server)` | SC-005 |
| 7. Beside R2C, or alone (US5, P2) | `mcp_server(extensions=)`; skills-only and hand-built servers; `mcp_only.py` | SC-006 |
| 8. Pages and directories (US6, P3) | paged `skills/list`, `resources/directory/read`, `directoryRead` off, the client's `list_directory` | SC-007 |
| 9. Docs and final gate | README, `ARCHITECTURE.md`, `CHANGELOG.md`, `WORKSTATE.md`, the ADR, dated notes; outside review; 3.11 / 3.12 / 3.13; core-only, A2A-only, MCP-only; leak scan | SC-008 |

**Order:**
- Phases 1 and 2 first: every later phase uses the fixtures, the reader and the wire models.
- Phase 3 is the MVP. The scan and the read of phase 3 are **first cuts**: the scan skips what it
  must not serve without reporting it, and the read opens the recorded path and checks size and
  digest. Phase 5 adds the report and replaces the read with the hardened one. Each of them
  starts with tests that fail on the first cut.
- Phases 4 and 5 are independent of each other; both need phase 3.
- Phase 6 extends the scan and the extension's constructor; phase 7 needs only the extension;
  phase 8 needs phases 3, 4 and 6 (it uses the client, `refresh` for the stale-cursor test, and
  the settings).
- Phase 9 is last because it covers everything at once.

## Risks

| Risk | Mitigation |
|---|---|
| PyYAML 6.0.4 is one day old | T001 repeats the vet on the day it is added and stops if anything changed; `<6.0.4` is a one-token alternative the maintainer may choose |
| The extension is Beta and its shapes change | the shapes live in `_wire.py` and the contract names the revision; the spike and the wire tests fail on the first difference |
| The MCP SDK changes what we lean on (resources read once, typed requests, `MCPError` pass-through) | `mcp>=2.3,<3`; `test_skills_spike.py` pins each fact and fails loudly |
| An upstream SDK release ships skills support | a later spec may move to it with the same public entry (spec, Assumptions) |
| A refresh cannot remove a resource from the SDK | documented in the contract; a removed file answers `-32602`, and the owner can rebuild the server |
| The client's YAML comparison refuses an entry another server rendered differently | a false refusal, the safe direction; named in the contract (R7) |
| A hostile server pages forever or sends a huge body | the client refuses a repeated cursor and bounds a body by the entry's size before decoding (R13) |
| A file swapped for a pipe or link after the scan | `O_NOFOLLOW`, `O_NONBLOCK`, `fstat`, a bounded read and the digest; tests swap each in (phase 5) |
| `import ext_r2c.mcp` now needs PyYAML | it comes with `[mcp]`; the README says so; a bare `pip install mcp` user is outside the extra |
| Tests that need root-only or POSIX features (permissions, links, pipes) | they skip with a reason where the platform or the user (root) cannot make the condition |

## Complexity Tracking

None.

## Notes

- Facts about the SDK were checked on 2026-11-21 against `mcp 2.3.0` with throwaway scripts; T005
  turns the ones the design leans on into tests.
- The beta text read for this plan is `specification/beta/skills.mdx` and
  `schema/beta/schema.json` of the ext-skills repository; the SEP page is a historical record.
  The Agent Skills rules were read from agentskills.io.
- Phase 3's first cuts are a deliberate order of work, not a design change: the end state is the
  design of research R4 and R6.
