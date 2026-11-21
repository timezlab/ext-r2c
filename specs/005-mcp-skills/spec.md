# Feature Specification: MCP Skills (`ext_r2c.mcp` skills extension)

**Feature Branch**: `main` (no branch; the directory is `specs/005-mcp-skills`)

**Created**: 2026-11-21

**Status**: Draft

**Input**: User description: "005-mcp-skills — serve MCP Skills (SEP-2640, extension id
`io.modelcontextprotocol/skills`) from `ext_r2c.mcp`, behind the [mcp] extra, as a second MCP SDK
`Extension` that is not R2C (maintainer, 2026-11-20, Q1 A). Skills are read from folders with
include / exclude. The installed MCP Python SDK (2.3.0, protocol 2026-07-28) has no skills
support, so this package implements it. Server side: scan folders for `SKILL.md`, read the YAML
frontmatter, build each skill entry (`uri`, `frontmatter`, `resources` with `uri`, `digest`,
`size`); serve `skills/list`, `skills/get`, the files through `resources/read`, and optionally
`resources/directory/read`; declare the extension and the `resources` capability in
`server/discover`; limits of 512 files and 16 MiB per skill; nothing outside the folder is ever
served. Caller side: a small client that lists skills, loads one on demand, and verifies size,
digest and frontmatter against the entry, refusing what does not verify, reading nothing ahead
of need. Tests are real in-process client ⇄ server round trips. Done when a real MCP SDK client
lists, gets and reads a skill from a folder, the client's verification rejects a tampered file,
and `Remote` (007) can pass `skills=` folders into it."

## Context

Spec 004 built the MCP door for R2C. It left one thing out on purpose: MCP Skills. A *skill* is
a folder with a `SKILL.md` (instructions for an agent, with a name and a description at the top)
and, often, supporting files (reference text, scripts, templates). SEP-2640, now an MCP
extension, lets an MCP server hand such folders to a client, so a client's agent can load the
instructions it needs when it needs them.

This is **not R2C**. R2C is the extension a remote uses to ask its caller things. Skills is
MCP's own extension, with its own identifier (`io.modelcontextprotocol/skills`) and its own
methods. It shares only the door: the package `ext_r2c.mcp`, the `[mcp]` extra, and the habit of
testing against the real protocol SDK. It shares no code with the R2C extension and is useful on
a server that has no R2C at all.

What the published extension asks of a server, in short (read 2026-11-21 from the ext-skills
repository, `specification/beta/skills.mdx`; the SEP page is a historical record):

- A server declares the `resources` capability and the extension in `server/discover`.
- A skill is `skill://<skill-path>/SKILL.md` plus its files, each file an ordinary MCP
  resource. The last segment of `<skill-path>` is the skill's `name`.
- `skills/list` returns a **manifest** per skill: the `uri` of its `SKILL.md`, its `frontmatter`
  verbatim, and every file with its URI, a SHA-256 digest and a byte size. `skills/get` returns
  one such entry.
- A client **must** check every file against that manifest before using it, must read only files
  the manifest lists, and must not read ahead of need. The digest is a check against a corrupted
  or swapped file, not a security boundary: the server that signs nothing also vouches for it.
- Limits: 512 files and 16 MiB per skill.
- Not in v1: packed archives and an index resource (both were removed in review). The
  extension is **Beta** and may still change.

The MCP Python SDK 2.3.0 gives an `Extension` a place to add methods and resources and to
declare settings in `server/discover`, but ships nothing for skills, so this spec builds both
halves:

- **Server side**: serve folders of skills.
- **Caller side**: a small client that lists skills, loads one, and verifies what it gets.

`Remote` (007) will offer `skills=` (folders, with include / exclude) beside the R2C door; this
spec does not build `Remote`, but its public entry point is shaped so `Remote` can pass folders
straight in.

Readers of this spec are the people who write `Remote`, owners of an MCP server who want to hand
skills to their callers, and authors of MCP clients and hosts that load skills.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Serve a folder of skills and read one end to end (Priority: P1)

A server owner points the skills extension at a folder holding a few skills. A real MCP client
connects, finds the extension declared, lists the skills, gets one, and reads its `SKILL.md` and
a supporting file. What the client reads is, byte for byte, what is on disk.

**Why this priority**: it is the whole feature in one line, and the "done when" of the brief.

**Independent Test**: a fixture folder with three skills (one nested under a prefix folder, one
with a binary file, one with non-ASCII text); a real MCP SDK server and client in process;
list, get and read every file; compare bytes with the disk.

**Acceptance Scenarios**:

1. **Given** a server with the skills extension, **When** a client asks `server/discover`,
   **Then** the capabilities hold `resources` and the extension `io.modelcontextprotocol/skills`
   with its setting `directoryRead`.
2. **Given** that server, **When** the client calls `skills/list`, **Then** the result is
   `resultType: complete`, carries `ttlMs` and `cacheScope`, and has one entry per served skill:
   `uri` = `skill://<skill-path>/SKILL.md`, `frontmatter` with `name` and `description` (and any
   other field the author wrote, unchanged), and `resources` listing `SKILL.md` and every other
   served file once, each with `uri`, `digest` (`sha256:` and 64 lowercase hex) and `size`.
3. **Given** that list, **When** the client calls `skills/get` with a skill's `SKILL.md` URI,
   **Then** it gets the same entry; with a URI that names no served skill it gets error `-32602`.
4. **Given** an entry, **When** the client calls `resources/read` for a file in it, **Then** it
   gets the file's bytes (as `text` for a text file, as `blob` for a binary one), the `SKILL.md`
   with `mimeType: text/markdown`.
5. **Given** a client that does not know the extension, **When** it lists resources, **Then** it
   sees the skills' files as ordinary resources and nothing breaks.

---

### User Story 2 - Load a skill and refuse anything that does not verify (Priority: P1)

A caller that wants to use a skill from a server loads it through the skills client. The client
reads the entry, reads only the files it needs, and checks each one against the entry before
handing it over. A file that was swapped, truncated or edited on the way is refused, not used.

**Why this priority**: the extension makes verification the client's duty, and a client that
skips it turns a server's folder into an instruction channel for the caller's agent. It is also
the second half of "done when".

**Independent Test**: serve a skill whose file a test then changes in each way a server could lie
(size, digest, frontmatter, an unlisted file, a `dynamic` marker, a too-large skill); load it with
the client each time; assert a named refusal and no content returned.

**Acceptance Scenarios**:

1. **Given** a served skill, **When** the client loads it, **Then** it returns the entry and the
   verified content of each file asked for, tagged with the origin it came from.
2. **Given** a file whose bytes differ from the entry's `size` or `digest`, **When** the client
   reads it, **Then** it raises a refusal naming the URI and the failed check, and returns
   nothing.
3. **Given** a `SKILL.md` whose frontmatter differs from the entry's `frontmatter` in any field,
   **When** the client reads it, **Then** it is refused.
4. **Given** a request for a URI the entry does not list, **When** the client is asked for it,
   **Then** it refuses without sending a request.
5. **Given** an entry whose `resources` is the string `"dynamic"`, or is missing or any other
   value, **When** the client loads it, **Then** it refuses and names why.
6. **Given** a skill over 512 files or 16 MiB, **When** the client loads it, **Then** it declines
   and names the limit.
7. **Given** a list of skills, **When** the client lists them, **Then** it has sent no
   `resources/read` request; each file is read only when the caller asks for it.
8. **Given** a server that has not declared the extension, **When** the client is asked for
   skills, **Then** it raises a named error and sends no `skills/*` request.

---

### User Story 3 - Nothing outside the skills is ever served (Priority: P1)

An owner points the extension at a folder. Whatever is in the folder besides skills, and
whatever a client asks for besides skill files, must stay unreachable: secrets, parent folders,
files behind a symbolic link.

**Why this priority**: the server reads the owner's disk on a stranger's request. One leak here
is worse than any missing feature.

**Independent Test**: a fixture folder with a hidden file, a symbolic link to a file outside, a
neighbouring folder, and a skill; ask for every one of them by every spelling the test can
think of; assert none is returned and the skill still is.

**Acceptance Scenarios**:

1. **Given** a request URI with `..`, an encoded `..`, a backslash, user info or a port in its
   first segment, a query or a fragment, **When** the server reads it, **Then** it answers
   `-32602`, and no file outside the skill's served files is read.
2. **Given** a symbolic link inside a skill folder, **When** the server is built, **Then** the
   link is not followed and not served, and the build says it left it out.
3. **Given** a hidden file or folder (a name starting with `.`) inside a skill folder, **When**
   the server is built, **Then** it is not served and not listed, and the build says so.
4. **Given** a file that changes on disk after the server scanned the folder, **When** a client
   reads it, **Then** the server does not return bytes that fail the entry's digest: the read
   fails and says the skills need a refresh.
5. **Given** the server, **When** any request arrives, **Then** it never writes to the skill
   folders.

---

### User Story 4 - Choose which skills are served and get told when the folder is wrong (Priority: P2)

An owner has a folder of many skills, some not meant for callers. They pass include and exclude
patterns on the skill name. A folder that cannot be served correctly (a bad name, no
frontmatter, too many files) stops the server at start, naming the folder and the reason,
instead of serving something half-right.

**Why this priority**: `Remote` will pass folders from configuration; a silent skip would be a
mystery in production. Still, a single clean folder works without it.

**Independent Test**: a fixture with skills `a`, `b-draft`, `c`; build with various filters and
assert the served set; build with each broken folder and assert the error names it.

**Acceptance Scenarios**:

1. **Given** `include=["a", "c"]`, **When** the server is built, **Then** only `a` and `c` are
   served.
2. **Given** `exclude=["*-draft"]`, **When** the server is built, **Then** `b-draft` is not
   served; a pattern matches the skill's name, and exclude wins over include.
3. **Given** a skill nested in prefix folders (`team/billing/refunds`), **When** the server is
   built, **Then** its URI is `skill://team/billing/refunds/SKILL.md` and its `name` is
   `refunds`.
4. **Given** a `SKILL.md` deeper inside a skill folder, **When** the server is built, **Then** it
   is a supporting file of the enclosing skill, not a skill of its own.
5. **Given** a skill whose `name` differs from its folder name, a `SKILL.md` without frontmatter,
   a name or description missing, a duplicate URI across roots, more than 512 files or more than
   16 MiB, **When** the server is built, **Then** it raises an error that names the folder and
   the reason.
6. **Given** a root folder that does not exist, or filters that leave nothing to serve, **When**
   the server is built, **Then** it raises an error naming the folder and the filters.
7. **Given** a broken skill that the filters exclude, **When** the server is built, **Then** it
   is not an error: only what is served is checked.

---

### User Story 5 - Serve skills beside R2C, or alone (Priority: P2)

An owner who already serves tools with R2C adds skills to the same MCP server. Another owner
serves only skills. In both, each extension works as before.

**Why this priority**: `Remote` will build exactly this combination, and R2C must not be touched
by it.

**Independent Test**: one server with both extensions: run the R2C flows of spec 004 and the skills
flows of this spec on it; one server with skills only; one server built with the SDK's own
`MCPServer(extensions=[...])`.

**Acceptance Scenarios**:

1. **Given** a server with `R2CExtension` and the skills extension, **When** a client runs a
   question flow and a skills flow, **Then** both complete and each is as on a server with that
   extension alone.
2. **Given** a server with the skills extension only, **When** a client connects, **Then** it
   works, with no R2C key declared.
3. **Given** the skills extension, **When** it is added to a server built by hand with
   `MCPServer`, **Then** it works too; it needs no helper of this package.

---

### User Story 6 - Many skills, and the files of a skill folder by directory (Priority: P3)

A server serves more skills than fit in one page; a client wants to list a skill's files without
knowing them in advance.

**Why this priority**: both are optional parts of the extension, and a small server needs neither.

**Independent Test**: a server with more skills than the page size; page through; read a skill's
root as a directory.

**Acceptance Scenarios**:

1. **Given** more skills than one page holds, **When** the client lists, **Then** it follows the
   cursor until none is left and sees every skill exactly once; no skill's file set is split
   across pages; a bad cursor gives `-32602`.
2. **Given** the directory setting is on, **When** the client reads the directory of a skill's
   root, **Then** it gets the direct children only: files as resources, subfolders with
   `mimeType: inode/directory`; an empty folder gives an empty list; a URI that is not a served
   directory gives `-32602`.
3. **Given** the directory setting is off, **When** a client calls the method, **Then** it gets
   what the base protocol answers for an unknown method, and discovery says `directoryRead` is
   not on.

---

### Edge Cases

- **A text file that is not clean UTF-8** (a Latin-1 file, or one with a byte-order mark or
  Windows line ends): `text` in a response is a string, so a file is sent as `text` only when it
  decodes as UTF-8 and encodes back to the same bytes; otherwise it is sent as `blob`. The digest
  is always over the raw bytes.
- **The same skill name twice**: `skill://a/pdf` and `skill://b/pdf` are two skills with one name;
  the server serves both, and the client keeps them apart by origin and URI and never merges
  them.
- **A name that is not valid** under the Agent Skills naming rules: a build error naming the
  folder; the same rule is not applied to a skill the filters exclude.
- **YAML frontmatter that is not plain data**: a date written without quotes, a tag, a duplicate
  key, an alias bomb. Frontmatter is read with a loader that builds only plain data, keeps a
  date as the text the author wrote, rejects a duplicate key, and caps its size; failing that is
  a build error, and on the client a refusal.
- **A very large single file**: it is sent whole, up to the skill's 16 MiB; the server does not
  stream a file. A caller with a smaller request limit cannot read it and is told why.
- **A frontmatter field the server does not know**: passed through verbatim, served and compared
  like any other; `allowed-tools` and similar fields are data, never a grant (the client never
  acts on them).
- **A skill folder with no supporting files**: `resources` has one entry, `SKILL.md`.
- **A `SKILL.md` that is a symbolic link**: it is not a `SKILL.md` (a link is never followed);
  the build reports it left out, and a folder with nothing else to make it a skill is only a
  prefix.
- **The directory setting on a nested skill**: every directory under every served skill's root
  can be read, and no other.
- **Case-different file names** on a case-sensitive disk: two files, two entries.
- **A client whose connection drops between list and read**: nothing is cached across
  connections; a new connection lists again.
- **Skills changed on disk while the server runs**: the entries the server holds stay as they
  were at the scan, and a read that no longer matches fails (US3, scenario 4); a refresh makes
  the server scan again.

## Requirements *(mandatory)*

### Functional Requirements

**Finding and describing skills (stories 1, 4)**

- **FR-001**: The owner MUST be able to give one or more root folders. Under a root, a
  directory that holds a `SKILL.md` and is the nearest such directory on its path is one skill;
  its skill path is its path relative to the root, with `/` separators; a `SKILL.md` deeper
  inside it is a supporting file. A directory with no `SKILL.md` is only a prefix.
- **FR-002**: A skill's `SKILL.md` MUST begin with YAML frontmatter that has `name` and
  `description`; `name` MUST follow the Agent Skills naming rules and equal the last segment of
  the skill path. A skill that breaks this is an error naming the folder.
- **FR-003**: Each skill's entry MUST hold: `uri` = `skill://<skill-path>/SKILL.md`;
  `frontmatter` = every field the author wrote, unchanged in content; `resources` = an array
  with `SKILL.md` and every other served file, each exactly once, each with `uri`, `digest`
  (`sha256:` and 64 lowercase hex, over the raw bytes) and `size` (raw bytes). The server never
  uses `"dynamic"`.
- **FR-004**: The server MUST serve regular files only, and leave out every hidden entry (a name
  starting with `.`) and every symbolic link; the build MUST report each path it left out. An
  unreadable file is an error.
- **FR-005**: A skill MUST NOT have more than 512 files or more than 16 MiB (16,777,216 bytes)
  in total; a skill over a limit is an error naming the skill and the limit.
- **FR-006**: The owner MUST be able to give `include` and `exclude` as lists of glob patterns
  matched against the last segment of the skill path (the folder name, which for a valid skill
  is its `name`). A skill is served when it matches `include` (or `include` is empty) and
  matches no `exclude`. Only served skills are checked, so a broken skill that is filtered out
  does not stop the build.
- **FR-007**: The server MUST scan the folders when it is built, and MUST be able to scan them
  again on request (a refresh). A root that is missing or not a directory, two skills with the
  same URI, or no skill left to serve, is an error naming the folder and the filters.

**Serving (stories 1, 3, 6)**

- **FR-008**: The server MUST declare the `resources` capability and the extension
  `io.modelcontextprotocol/skills` in `server/discover`, with `directoryRead` true only when the
  directory method is served.
- **FR-009**: `skills/list` MUST return `resultType: complete`, `skills`, `ttlMs` and
  `cacheScope`; every served skill MUST appear (never a partial list); a list larger than one
  page MUST be paged by an opaque cursor, with each entry whole on one page; a bad cursor is
  `-32602`.
- **FR-010**: `skills/get` MUST take `params.uri` = a skill's `SKILL.md` URI and return
  `resultType: complete`, `skill` (the same shape as a list entry), `ttlMs` and `cacheScope`;
  any other URI is `-32602`; it MUST answer for every served skill.
- **FR-011**: Every served file MUST be readable through `resources/read` at its URI; a file is
  sent as `text` only when its bytes decode as UTF-8 and encode back identically, otherwise as
  `blob`; the `SKILL.md` resource has `mimeType: text/markdown` and its `name` and
  `description` from the frontmatter. A URI that names no served file is `-32602`.
- **FR-012**: The bytes of a read MUST match the entry's `digest` and `size`; when a file on disk
  no longer does, the read MUST fail with `-32603` saying the skills changed and need a
  refresh, and MUST NOT send the bytes.
- **FR-013**: When `directoryRead` is on, `resources/directory/read` MUST work for every
  directory under every served skill, root included: direct children only, files as resources,
  subdirectories as `mimeType: inode/directory`, an empty directory as an empty list, a cursor
  for paging; a URI that is not a served directory is `-32602`. When it is off, the method MUST
  not be served.
- **FR-014**: A request URI MUST be taken literally and compared to the served set: a `..`
  segment (plain or encoded), a backslash, user info or a port in the first segment, a query, a
  fragment or a trailing slash on a file MUST give `-32602` and MUST NOT touch the disk outside
  the served files; a symbolic link MUST never be followed.
- **FR-015**: The server MUST NOT write to the skill folders, and MUST NOT put anything in a
  resource's `_meta` other than keys under `io.modelcontextprotocol.skills/` (this spec adds
  none).

**Composition (story 5)**

- **FR-016**: The skills extension MUST be its own MCP SDK `Extension`, MUST NOT import the R2C
  extension or anything of R2C's, and MUST work alone, beside `R2CExtension` on one server, and
  on a server the owner builds with `MCPServer` directly.
- **FR-017**: The public entry MUST take the root folders, `include`, `exclude`, the directory
  switch, `ttlMs`, `cacheScope` and the page size, with a default for all but the folders, so
  `Remote` can pass `skills=` folders straight in.

**The caller's client (story 2)**

- **FR-018**: The client MUST work on a connected MCP SDK client, check the server's
  declaration before any `skills/*` request, and list every page, returning entries as typed
  items keyed by the origin label the caller gives and the URI.
- **FR-019**: The client MUST send no `resources/read` until the caller asks for a file, and
  MUST read only URIs the entry lists; any other is refused without a request.
- **FR-020**: For each file read, the client MUST check the raw size and the SHA-256 against the
  entry, and for a `SKILL.md` MUST also read its frontmatter and compare it field by field to
  the entry's; any failure raises a named refusal (the URI and the failed check) and returns
  nothing.
- **FR-021**: The client MUST refuse an entry whose `resources` is missing, `"dynamic"` or any
  other value than an array, whose `SKILL.md` URI does not end in `<name>/SKILL.md`, or that has
  more than 512 files or 16 MiB, and name the reason.
- **FR-022**: The client MUST keep skills with the same name apart (by origin and URI), MUST
  return content as untrusted data tagged with its origin, and MUST NOT act on any frontmatter
  field: `allowed-tools` and the like are data only.
- **FR-023**: The client MUST NOT cache across connections and MUST NOT write skill files to disk.

**Packaging and tests (all stories)**

- **FR-024**: Code for this feature MUST live in `ext_r2c.mcp`, import only `ext_r2c.core`
  where it needs anything of ours, the standard library, and the `[mcp]` extra's packages
  (including the YAML reader, D1); `import ext_r2c`, `ext_r2c.core` and `ext_r2c.a2a` MUST keep
  working without the extra, and the `[mcp]`-only test run MUST pass (constitution VIII).
- **FR-025**: Every scenario above MUST be covered by a real in-process round trip: the MCP SDK's
  own client against a server built with this package, over the SDK's transport, with no mock
  of the protocol (constitution VII); the fixture skills in the tests MUST use invented content
  (constitution VI).

### Key Entities

- **Skills extension**: the MCP SDK `Extension` that serves skills; its settings are
  `directoryRead` and the cache hints.
- **Root folder / filter**: where skills are found, and which ones are served (`include`,
  `exclude`).
- **Skill**: a folder with a `SKILL.md`; identified by its URI, named by its `name`.
- **Entry (manifest)**: what `skills/list` and `skills/get` return for one skill: `uri`,
  `frontmatter`, `resources`.
- **Skill file**: one served file: `uri`, `digest`, `size`, and its bytes through
  `resources/read`.
- **Skills client**: the caller's side: lists, loads, verifies.
- **Verification**: size, SHA-256 and frontmatter checked against the entry before content is
  used.
- **Origin**: the label the caller gives a server; with the URI, it identifies a skill on the
  client.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a fixture folder with at least three skills (a nested one, one with a binary
  file, one with non-ASCII text), a real MCP SDK client lists, gets and reads every file of every
  skill, and 100% of the bytes equal the disk's.
- **SC-002**: Of the tampering cases (changed size, changed digest, changed frontmatter, unlisted
  file, `dynamic`, missing `resources`, over a limit, extension not declared), 100% are refused by
  the client with a named reason, and 0 bytes of the tampered content are returned.
- **SC-003**: Of at least 12 attempts to reach what is not served (`..` in plain, encoded and
  mixed forms, a backslash, a symbolic link out, a hidden file, a neighbouring folder, a query, a
  fragment, a skill not served by the filters), 0 return any byte, and each gets `-32602`.
- **SC-004**: After a listing, the number of `resources/read` requests the server has seen is 0;
  after the caller asks for N files, it is N.
- **SC-005**: Each build error of story 4 (at least 8 kinds) names the folder and the reason, and
  a server with a broken but excluded skill starts.
- **SC-006**: One server with both `R2CExtension` and the skills extension passes the spec 004
  R2C flows and the skills flows of this spec, and the R2C suite of spec 004 is unchanged.
- **SC-007**: A server with more skills than one page lists every skill exactly once through the
  cursor.
- **SC-008**: The full suite passes on the installed wheel on Python 3.11, 3.12 and 3.13; the
  core-only and A2A-only environments still pass; the `[mcp]`-only environment passes.

## Assumptions

- **Users**: `Remote` (007) in this repository first; owners of an MCP server who want to hand
  skills to callers; authors of clients and hosts that load skills.
- **MCP Python SDK 2.3** (`mcp>=2.3,<3`) is the only MCP dependency. Its `Extension` can add
  methods (`skills/list`, `skills/get` and `resources/directory/read` are not spec methods, so
  they may be bound), add resources, and declare settings in `server/discover`. It has no skills
  support. Its implementations list says skills support is merged upstream and not yet released
  (unverified): a later spec may then move to the SDK's own, with the same public entry.
- **The extension is Beta.** This spec follows the `beta` revision of the ext-skills
  specification read on 2026-11-21 (`specification/beta/skills.mdx`), base protocol 2026-07-28.
  The plan records the revision it was built against; a breaking revision is a later spec. Two
  details differ between the sources and the plan settles them by reading the beta text again:
  whether `skills/get` carries `ttlMs` and `cacheScope` (this spec puts them on both), and the
  exact prefix spellings in `_meta` and `metadata` (this spec adds none).
- **The Agent Skills format** (agentskills.io) defines `SKILL.md`, the frontmatter and the name
  rules. This spec relies on it and has not yet read it in full; the plan reads it first and
  fixes the exact name and description rules.
- **No R2C change.** Skills has no R2C rule, so `standard/` and its examples do not change, and
  there is no R2C wire example for it; the replay-the-examples rule of constitution II is about
  R2C rules. The tests carry their own fixture folders.
- **Who may read skills** is the MCP server's business: the same skills go to every caller the
  server lets in. Authentication is the SDK's; showing different skills to different callers is
  out of scope.
- **Out of scope**: packed archives, an index resource and distribution by a well-known URL
  (all out of v1 of the extension); host-side duties of the extension (consent screens, approval
  of a skill's tools, an on-disk cache, a skill registry); `dynamic` skills; skills built from
  memory rather than from folders; running a skill or installing it into an agent; MCP Tasks;
  `Remote` itself (007); sending a skill to a client that did not ask.

### Decisions taken in this draft

The maintainer may overrule any of these when approving the spec; each has a default so the
spec is complete without an answer.

- **D1. A YAML reader, in `[mcp]`.** The SDK brings none, and frontmatter is YAML that must pass
  through verbatim and be compared field by field on both sides. Default: add PyYAML to the
  `[mcp]` extra (one reader for server and client, a loader that builds plain data only).
  Alternatives: a separate `[skills]` extra (cleaner for MCP users who serve no skills, one more
  extra to document and to name in the `Remote` error); a hand-written subset parser (no
  dependency, but a valid skill the parser misreads is served wrongly). The plan vets the package
  before it is added.
- **D2. Scan once, refresh on request.** Default: scan at build, hold the entries, fail a read
  that no longer matches. Alternative: scan on every request (edits show at once, but a list and
  a read can disagree and a bad edit breaks a running server).
- **D3. A broken folder stops the build.** Default: an error naming the folder; hidden files and
  symbolic links are left out with a report. Alternative: skip the folder with a warning (a
  server that starts but silently lacks a skill).
- **D4. Filters are globs on the skill name, exclude wins.** Alternative: match the path.
- **D5. `directoryRead` is on by default** (the server can do it for every folder it serves),
  and can be switched off.
- **D6. The client is a loader, not a host.** It verifies and returns tagged, untrusted data; it
  asks nobody's consent, caches nothing on disk and refuses `dynamic` skills.
