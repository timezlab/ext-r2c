# Research: MCP Skills (`ext_r2c.mcp` skills extension)

Phase 0 of [plan.md](plan.md). Facts about the MCP Python SDK were read from the installed
`mcp-2.3.0` and `mcp_types-2.3.0` wheels on 2026-11-21 and checked with throwaway scripts (not
committed; task T005 turns the facts that matter into a pinned test). Facts about the
protocol come from the beta text of the extension (`specification/beta/skills.mdx` and
`schema/beta/schema.json` in the ext-skills repository), and about the skill format from
agentskills.io; both were downloaded and read in full. Paths are inside the installed `mcp`
package. The extension is **Beta and may break**: R16 says what we do about that.

## R1. What the SDK's `Extension` gives us

- **Finding** (spike S1): one `Extension` can do everything this feature needs.
  - `MethodBinding("skills/list" | "skills/get" | "resources/directory/read", params_type,
    handler)` is accepted: none of the three is a spec method, so none is refused at
    construction. A handler returns a pydantic model or a dict.
  - `ResourceBinding(resource)` registers one concrete `Resource` per file. `MCPServer` keys it by
    `str(resource.uri)` and lists it in `resources/list` (602 resources list in 12 ms, unpaged).
  - `settings()` appears at `capabilities.extensions["io.modelcontextprotocol/skills"]` as
    `{"directoryRead": true}`. The `resources` capability (`subscribe` and `listChanged` both
    true) is declared by every `MCPServer`, whether or not a resource is registered, so the
    declaration the extension requires holds on any server this feature extends.
    *Corrected 2026-11-22 by T005: this bullet first said the capability appears "as soon as one
    resource is registered". `test_resources_capability_is_always_declared` pins the real
    behaviour. Nothing in the design depended on the old wording: a skill always has at least
    `SKILL.md`, and a server with no skill is a build error (FR-007) for its own reason.*
  - `Extension.resources()` is read **once**, when `MCPServer` is built. `MCPServer.add_resource`
    exists; there is no way to remove a resource, and `ResourceBinding` cannot carry a template.
  - `SkillsExtension` declares no tool and overrides no interceptor, so it never touches
    `tools/call` and does not collide with `R2CExtension`.
- **Decision**: `SkillsExtension(Extension)` with `identifier = "io.modelcontextprotocol/skills"`,
  settings `{"directoryRead": bool}`, one `SkillFile` resource per served file, and the three
  method bindings (the third only when `directory_read` is on, so that `resources/directory/read`
  is `-32601` when off, FR-013).
- **Alternatives**: a `Server.middleware` that answers `skill://` reads (needs the owner to pass
  the middleware: breaks "works on a hand-built `MCPServer`", FR-016); a resource template
  (unreachable from an `Extension`).

## R2. Typed requests and results

- **Finding** (spike S2, all checked on a real client and server over the in-process transport):
  - A handler may return a `CacheableResult` subclass: `ttl_ms` and `cache_scope` go out as
    `ttlMs` and `cacheScope`, `result_type="complete"` as `resultType`, and the server adds the
    `_meta` `serverInfo` stamp. `PaginatedResult` adds `nextCursor`. The same subclasses parse
    the result on the client (`class ListSkillsResult(PaginatedResult, CacheableResult)`, as the
    SDK does for `ListResourcesResult`).
  - The params model must subclass `RequestParams` (or `PaginatedRequestParams` for a cursor):
    `_meta` parses uniformly. A wrong type (`uri: 5`) is `-32602` from the SDK.
  - **A client request must be a typed class.** `types.Request(method="skills/get",
    params={"uri": "..."})` coerces the dict into the base `RequestParams` and **drops `uri`**
    (the wire shows `params: {}`), so the server answers `-32602`. The client defines
    `class GetSkillRequest(types.Request[GetSkillParams, Literal["skills/get"]])` and a
    paginated one for list and directory reads, and sends them with `session.send_request(req,
    ResultType)`.
  - The client stamps `_meta` (protocol version, client info, capabilities) on every request;
    the 2026-07-28 HTTP ladder requires it. `Mcp-Name` is mirrored only for `tools/call`,
    `prompts/get` and `resources/read`, and the extension text asks for no header on its own
    methods, so none is set.
  - The client sends **no** capability for this extension: the examples in the text carry
    `clientCapabilities: {}`, and a client only has to observe the server's declaration.
- **Decision**: wire models live in one module shared by server and client (`_wire.py`); the
  client keeps `skills` as raw JSON objects in the result model and validates each entry itself,
  so one bad entry becomes a named refusal instead of a pydantic error on the whole page
  (R13).

## R3. URIs: taken literally, compared to a dictionary

- **Finding** (spike S1): `ResourceManager.get_resource` compares the raw request string with the
  registered strings. `skill://TEAM/…` does not match `skill://team/…`, `..`, `%2e%2e`, `?x=1`,
  `#f`, a backslash and a missing file are all `Unknown resource` → `-32602`, and none reaches
  our code. The SDK keeps case, spaces and non-ASCII characters in the registered URI. Pydantic's
  `AnyUrl` would normalise `..` and percent-encoding, but the JSON-RPC layer passes plain `str`.
- **Decision**:
  - The URI of a file is built **once, at scan time**, from the path segments the scan walked,
    each percent-encoded with `urllib.parse.quote(segment, safe="")` (unreserved characters stay,
    everything else, including `%`, space and every non-ASCII byte, is `%XX`). The result is pure
    ASCII, which also keeps it clear of the `Mcp-Name` header's non-ASCII handling.
  - A request is answered by **exact dictionary lookup** of the whole URI string in the
    catalogue (`files`, `skills`, `directories`). No path is ever built from, joined with or
    derived from a request string (FR-014); the disk is touched only through the record the
    lookup returned.
  - The first segment is the URI authority. After encoding it is a valid RFC 3986 `reg-name`
    (unreserved and percent-encoded characters only). Authorities compare case-insensitively, so
    two skills whose first segments differ only in case are a **duplicate** and a build error.
  - A folder name is used as it is on disk; a name that is not valid UTF-8 cannot be a segment, so
    the entry is left out and reported (`undecodable name`), like a hidden file.
- **Alternatives**: encode nothing (works with the SDK, but a space or `é` in a segment is an
  invalid URI that other clients may reject or normalise); a resource template for the whole
  `skill://` scheme (not reachable, R1).

## R4. A read opens once, hashes once, sends what it hashed

- **Finding**: `Resource.read()` is `async` and returns `str | bytes`; the SDK sends `str` as
  `text` and `bytes` as a base64 `blob` and sets the MIME from the resource. A `MCPError`
  raised in `read()` goes out unchanged with its code and message (checked with `-32603`); any
  other exception becomes `UnexpectedResourceError("Error reading resource <uri>")`, with the
  original only as `__cause__` (no path on the wire).
- **Decision**: `SkillFile.read()` looks the URI up in the *current* catalogue and runs one
  blocking function in a worker thread (`anyio.to_thread.run_sync`):
  1. open the skill folder, then each path component with `os.open(name, O_NOFOLLOW, dir_fd=fd)`
     (the last one as a file, the others as directories), so a link swapped in after the scan is
     refused by the kernel, not by a check that could race;
  2. `fstat` the descriptor: a regular file or `-32603`;
  3. read at most `size + 1` bytes: a file that grew is detected without reading it all;
  4. compare the length and the SHA-256 of **those bytes** with the entry: any difference is
     `MCPError(-32603, "The skills changed on disk since they were scanned; refresh them.")` and
     no byte is sent (FR-012);
  5. return those same bytes: as `str` when they decode as UTF-8 and re-encode identically,
     otherwise as `bytes` (FR-011).
  The server never writes (no `O_WRONLY`, `O_CREAT`, `O_TRUNC` anywhere), and no error text
  carries a path of the host.
  **Not "changed" when it is not (R17).** Only the errors that say the file is gone or swapped
  (`ENOENT`, `ENOTDIR`, `ELOOP`, `ENXIO`, `EISDIR`, `EINVAL`) are the "changed" answer above; any
  other `OSError` is `-32603` with the fixed "The server could not read the file." and one `WARNING`
  in the log (URI and the system's words, no path).
  **A hard link is not a link.** `O_NOFOLLOW` refuses a symbolic link; a name that is a hard link to a
  file elsewhere is that file's own name as far as the kernel is concerned, and is read. A scan
  cannot refuse it by `st_nlink > 1` without dropping the skills that ship in installed packages
  (their files are hard-linked from the package manager's store). Named as a limit in the README and
  the contract.
  Where the platform has no `O_NOFOLLOW` or `dir_fd` (Windows), the function falls back to
  `lstat` of every component before opening, and the digest check stays the backstop; CI and the
  tested platform are Linux.
- **Alternatives**: hold the bytes in memory (up to 16 MiB × every skill; stale after an edit
  without any signal); hash at scan and trust the file at read (the bug the digest check exists
  to catch).

## R5. How entries are held, and what a refresh can do (D2)

- **Finding**: `Extension.resources()` runs once and the SDK cannot remove a resource (R1).
- **Decision**:
  - The extension holds one immutable **catalogue**: skills by URI, files by URI (path parts,
    skill folder, digest, size, MIME), directories by URI (sorted children), the list of what
    the scan left out, and a random **generation** token. Handlers read the catalogue **once** at
    the start of a request, so one request sees one snapshot.
  - Entries hold the digest and size, never the bytes (R4).
  - `refresh(server=None)` scans again with the same folders and filters, builds a new
    catalogue, and swaps it in one assignment. If the scan fails, the old catalogue stays and the
    error is raised: **a bad edit never breaks a running server**.
  - A file the new scan finds that was never registered with the SDK needs
    `MCPServer.add_resource`, so `refresh(server)` takes the server and registers it. Without
    the server, such a file makes `refresh()` raise `SkillsError` (old catalogue kept) rather
    than leave `skills/get` listing a file `resources/read` cannot find.
  - A file the new scan no longer finds stays in the SDK's `resources/list` (it cannot be
    removed) and a read of it is `-32602`, the same as any URI that is not served. The
    resource's `name`, `description` and MIME in `resources/list` keep their values from
    registration. All three limits are written in the API contract.
  - The generation changes on every refresh, so a cursor from before it is `-32602` (R9).
- **Alternatives**: scan on every request (a list and a read can disagree, a bad edit breaks the
  running server: the spec's own alternative to D2); a refresh that rebuilds the whole `MCPServer`
  (the owner already can; it drops live sessions).

## R6. Finding skills

- **Decision** (all of this is FR-001 to FR-007, with the order made explicit):
  1. Each root is resolved once (`os.path.realpath`); the owner's own path may be a link. A root
     that is missing or not a directory is an error naming it.
  2. The scan walks each root depth first in sorted name order, never following a link. Hidden
     names (a leading `.`), symbolic links, entries that are not regular files or folders, and
     names that are not valid UTF-8 are left out, each recorded with its path and reason.
  3. A folder holding a regular file named exactly `SKILL.md` is a skill folder. **The nearest
     `SKILL.md` on a path wins**: a deeper `SKILL.md` is a supporting file of the outer skill, and
     its folder is not scanned for skills. A root that holds a `SKILL.md` is a skill itself.
  4. The skill path is the folder's path below its root (the root's own name is not part of it),
     so `skills/team/billing/refunds` under the root `skills` is `skill://team/billing/refunds`.
     A skill folder that is itself the root has a one-segment path, its own name.
  5. **Filters first, checks after**: `include` and `exclude` are matched, with
     `fnmatch.fnmatchcase`, against the folder's last segment (D4: exclude wins; empty `include`
     means all). Only a skill that passes is read, parsed and counted, so a broken skill the
     filters exclude does not stop the build (FR-006).
  6. For a served skill: read `SKILL.md`, parse and validate the frontmatter (R7, R8), require the
     folder name to equal `name`, collect the regular files below it, enforce 512 files and
     16,777,216 bytes (`SKILL.md` counts in both), and hash every file.
  7. Two skills with the same URI (compared with the authority case-folded, R3), or no skill left
     after the filters, is an error naming the folders and the filters.
- **Why nearest wins** (the extension allows a server to publish nested skills as their own
  entries, and says an enclosing skill's `resources` then lists the nested files too): publishing
  both would give one file two entries in two manifests and double-count it against the limits;
  the simpler rule is conformant, because the text only describes what a server that publishes
  nested skills does. The text of the extension says a host never acts on a nested `SKILL.md`'s
  frontmatter, which is what serving it as an ordinary file amounts to. A server that wants a
  nested skill served puts it in a sibling folder. This is a documented v1 limit.
- **Error kinds** (SC-005 asks for at least 8; each names the folder and the reason, and each
  has a test, R14): missing root; root not a directory; unreadable root, `SKILL.md` or file;
  `SKILL.md` not UTF-8; no frontmatter; frontmatter not closed; frontmatter not readable as
  plain data (YAML error, duplicate key, alias, tag, too large, not a mapping); `name` or
  `description` missing, not a string, empty, too long, or `name` not allowed; `name` different
  from the folder name; over 512 files; over 16 MiB; duplicate URI; nothing left to serve.
  Bad settings (negative `ttl_ms`, `page_size` below 1, unknown `cache_scope`) are `ValueError`
  at construction.

## R7. The frontmatter reader (D1) and the PyYAML vet

- **Finding**: the MCP SDK brings no YAML package (checked in its requirements and in a clean
  venv). Frontmatter is YAML, and the extension requires it to pass through "verbatim" as JSON.
- **Vet** (read on 2026-11-21, with the `security-audit` skill's checks):
  - Package `PyYAML` on PyPI, MIT, `requires_python >=3.10`, project at `github.com/yaml/pyyaml`,
    the long-standing reference package; wheels for CPython 3.11, 3.12 and 3.13 on the major
    platforms for 6.0.3 (29 wheels) and 6.0.4 (manylinux x86-64 wheels checked), plus an sdist.
  - OSV: 8 advisories for the package, all `GHSA-` or `PYSEC-`, all about loading untrusted YAML
    with an unsafe or bypassable loader, and all fixed in 5.4 or earlier (the latest fix is 5.4;
    read one by one); **none** is a `MAL-` (malware) advisory, and **none applies to 6.0.3**.
    The reader of R7 uses `SafeLoader` and refuses every tag it does not know anyway.
  - Recency: **6.0.4 was uploaded on 2026-11-20, one day before this plan**; 6.0.3 is from
    2025-09-25 and has been out for fourteen months. A one-day-old release of a package this old
    and this watched is the thing the recency check exists to flag, and it is flagged here.
  - No install script runs for the wheels, and the package declares no dependencies
    (`requires_dist` is empty).
  - **Vet repeated on 2026-11-22 by T001**, from the PyPI JSON and the OSV API: nothing changed.
    OSV still lists the same 8 advisories (all fixed in 5.4 or earlier, none a `MAL-`), and an
    OSV query for versions 6.0.3 and 6.0.4 returns no advisory; neither release is yanked; each has
    wheels for CPython 3.11, 3.12 and 3.13 on Linux, macOS and Windows plus an sdist;
    `requires_dist` is empty. 6.0.4 is now two days old (uploaded 2026-11-20 by the upstream
    maintainer who published the GitHub release the same hour). Its release notes: Python 3.15
    support, Python 3.8 and 3.9 dropped, a fix for exponential merge-key expansion, libyaml 0.2.6
    wheels. Nothing there touches the pure-Python `SafeLoader` this feature uses. The bound stays
    `>=6.0.3,<7`.
- **Decision**: add `PyYAML>=6.0.3,<7` to the `[mcp]` extra (and the dev group). A pinned ceiling
  below 6.0.4 would be stricter than the rest of the project (`mcp>=2.3,<3` takes the newest) and
  would hold the pin back forever; instead **T001 repeats the vet** (OSV `MAL-` query, upload
  date, wheel list) on the day the dependency is added and stops if anything changed. The
  maintainer may still choose `<6.0.4` for now; it is a one-token change.
- **The reader** (`_frontmatter.py`, tested on 3.11 against PyYAML 6.0.3 in a scratch venv):
  a `SafeLoader` subclass, pure Python (not `CSafeLoader`, whose hooks differ), that
  - builds plain data only: the Python and binary tags and every unknown tag fail
    (`could not determine a constructor`; checked), and a decoded `!!binary` value (bytes) is
    refused after loading because it is not JSON;
  - keeps a date or timestamp as the text the author wrote (the timestamp resolver is removed;
    checked: `2026-01-02` stays `'2026-01-02'`);
  - reads only `true` and `false` as booleans (`yes`, `no`, `on` stay text, so `name: no` is the
    string `no`; checked);
  - rejects a duplicate key (PyYAML keeps the last one silently; checked);
  - rejects every anchor and alias, merge keys included (an alias bomb has no way in; checked);
  - is followed by a check that the result is a mapping of string keys whose values are JSON
    (`str`, `int`, finite `float`, `bool`, `None`, lists, mappings) with a depth cap, and by a
    size cap of **64 KiB** on the frontmatter text (a guard of this plan, not of the protocol).
    A `RecursionError` or any other failure while loading is the same "not readable" error.
  - the document is the text between the opening `---` line (after an optional UTF-8 byte-order
    mark) and the next line that is exactly `---`; carriage returns are accepted.
  - **As built (phase 2, recorded 2026-11-22; the ADR `skills-frontmatter-and-nesting` has the
    same text).** The reader is stricter than the list above. Anchors, aliases, merge keys and the
    depth cap are refused **while the document is composed**, so a document that is too deep or has
    an alias is never built (not "after it is loaded"). Numbers and booleans are JSON-like only:
    `true` and `false`; integers (`3`, `-4`); floats (`1.5`, `2.5e3`); `null`. So `yes`, `no`,
    `on`, `off`, `12:30` (sexagesimal), `0755` (octal), `1_000`, `0x1f` and `2026-01-02` stay the
    text the author wrote, on the server and on the client alike. The reader is a pure-Python
    `SafeLoader` subclass whose resolvers and constructors are cut to a whitelist, and every
    failure is one `FrontmatterError` whose `reason` comes from a fixed set (`REASONS`) and whose
    message carries no file text, no line and no path. `.inf` and `.nan` are refused (`not json`).
- **Alternatives**: a `[skills]` extra (a second install step for a feature `Remote` should get
  with `[mcp]`); a hand-written subset parser (a valid skill the parser misreads is served
  wrongly, and the client would misread it the same way, so the check would agree with the
  error); `ruamel.yaml` (a larger package, same vet needed, round-trip features we do not use).
- **Known limit**: the client compares the entry's frontmatter with what **this** reader makes of
  the `SKILL.md` it fetched. An entry from another server that typed a value this reader keeps as
  text (a timestamp rendered as a different string, `yes` as `true`, `0755` as the number 493, `0x1f`
  as 31, `12:30` as 750) differs from it and is refused: a false refusal, the safe direction, named
  in the contract. It is YAML 1.1 against this reader, and any server whose reader follows YAML 1.1
  meets it. (Widened in R17: phase 2 made the reader stricter than this paragraph first said.)
  A quoted scalar is always text, and an explicit core tag (`!!int`, `!!bool`, `!!float`, `!!str`) is
  accepted for what it says; `.inf`, `.nan` and every other tag (`!!timestamp` too) are refused.

## R8. Names and descriptions

- **Finding** (agentskills.io, read in full): `name` is 1–64 characters of lowercase letters,
  digits and hyphens, no leading or trailing hyphen, no `--`, and equals the folder name;
  `description` is 1–1024 characters; `compatibility` (≤500), `license`, `metadata` and
  `allowed-tools` are optional. The text says "unicode lowercase alphanumeric (a-z, 0-9)", and
  the examples and the reference check are ASCII.
- **Decision**: the **server** accepts `^[a-z0-9]+(-[a-z0-9]+)*$` up to 64 characters (an ASCII
  rule, written in the contract as a v1 limit, so a non-ASCII `name` is a build error naming the
  folder) and a non-empty string `description` of at most 1024 characters. Every other field is
  passed through unchecked. The **client** does not apply the character rule (a stricter client
  would refuse valid skills from other servers); it checks that the entry's URI ends in
  `<name>/SKILL.md` (FR-021).
- A frontmatter `metadata` key that starts with `io.modelcontextprotocol/` is reserved by the
  extension; this feature defines none, adds none, and passes the author's through unchanged.

## R9. Wire shapes, cache hints, page size, cursor

- **Finding** (schema, read in full): `ListSkillsResult` requires `cacheScope`, `resultType`
  (`"complete"`), `skills`, `ttlMs`, and has an optional `nextCursor`; `GetSkillResult` requires
  `cacheScope`, `resultType`, `skill`, `ttlMs` (so the spec's open point is settled: **both**
  methods carry the hints); `ReadResourceDirectoryResult` requires `cacheScope`, `resources`,
  `resultType`, `ttlMs` and takes a `cursor`. `cacheScope` is `"private"` or `"public"`.
  `GetSkillRequestParams` is `{uri, _meta}`; the directory read is `{uri, cursor?, _meta}`.
- **Decision**:
  - defaults: `ttl_ms=300_000` (the catalogue is fixed until a refresh, and a stale entry makes a
    read fail the digest check loudly, so five minutes is a safe hint), `cache_scope="private"`
    (the SDK's default; the owner opts into `"public"`), `page_size=25`. An entry is a complete
    manifest, up to 512 files at about 150 bytes each (≈75 KB), so a page of 25 stays under 2 MB
    at the limit. One `page_size` serves `skills/list` and the directory read.
  - ordering is sorted by URI (skills) or by name (a directory's children, files and folders
    together), so a listing is stable and a cursor is a position.
  - the **cursor** is opaque: base64url of `<generation>.<offset>`. A cursor that does not decode,
    belongs to another generation (an earlier refresh, another process), or points past the end
    is `-32602` with a fixed message (`Invalid cursor`, never the cursor). It carries no path and
    grants nothing. An empty-string cursor is a cursor (and a bad one): only an absent cursor is
    the first page.
  - **A cursor is good for one listing of one catalogue** (decided in phase 8). `skills/list` uses
    the catalogue's `generation`; a directory read uses `<generation>-<first 16 hex of the SHA-256
    of the directory's URI>`. A cursor of `skill://docs` given to `skill://docs/a`, or to
    `skills/list`, is `-32602` instead of a position in another list: with only the generation, it
    would be accepted and silently skip or repeat children. The hash is a label, not a secret (a
    client can compute it); the check is there so a mix-up is loud, not to authenticate.
  - `resultType` is always `"complete"`; `_meta` on skills and resources carries no key (FR-015).
- **Alternatives**: `ttl_ms=0` by default (every client re-fetches every time; the spec's own
  example uses 300000); `"public"` by default (a server behind authentication would hand a shared
  cache what only some callers may see).

## R10. Directory reads (FR-013)

- **Finding** (text, read in full): `resources/directory/read` takes `{uri, cursor?}` and returns
  the **direct children** as `Resource` objects (files with their ordinary metadata, folders as
  `mimeType: inode/directory`), is paginated, carries `ttlMs` and `cacheScope`, is `-32602` for a
  URI that does not exist or is not a directory, and an empty directory is an empty list. Directory
  URIs have no trailing slash, and "need not appear in `resources/list`".
- **Decision**: the catalogue has one record per directory of every served skill (the root
  included), with its children sorted by name; only those URIs are directories, so
  `skill://team/billing` (a prefix above two skills) is `-32602`. A child file carries the same
  `name`, `description` and MIME it has in `resources/list` (the `SKILL.md` child shows the
  frontmatter's). The directory resources are not registered with the SDK, so they stay out of
  `resources/list`. The method answers from the catalogue and never touches the disk.
- **How it was built** (phase 8): the scan records every folder it walks in `SkillRecord.dirs`
  (empty ones too), so an empty folder is a directory that answers `[]`; hidden and linked folders
  are never entered and so are not directories. Only a skill's own `SKILL.md` takes the
  frontmatter's name and description; a `SKILL.md` below the root is an ordinary file named
  `SKILL.md`, in `resources/list` and in a directory alike (one helper, `_named`). The method is
  bound only when `directory_read` is on, so with it off the SDK itself answers `-32601`.
  `ReadDirectoryParams` extends `PaginatedRequestParams`; every answer carries `ttlMs`,
  `cacheScope` and `resultType`.
- **Residual risks, not closed** (recorded in phase 8 and sent to the outside review of phase 9):
  - the number of **directories** is not capped (the limits are 512 files and 16 MiB): a skill
    folder with a million empty folders is walked, held in the catalogue and answered from it
    (*closed by the outside review, R17: 1024 folders in a skill, 1024 searched in a root, 32
    deep*);
  - the client catches a **repeated** cursor, not an endless run of distinct ones: a hostile server
    that invents a new cursor every time still keeps `list()` asking. A caller that must bound
    that wraps the call in its own timeout.

## R11. MIME types, and text versus blob

- **Decision**: a fixed table of about 20 extensions (`md`, `txt`, `json`, `yaml`/`yml`, `toml`,
  `csv`, `html`, `css`, `js`, `ts`, `py`, `sh`, `xml`, `svg`, `pdf`, `png`, `jpg`/`jpeg`, `gif`,
  `webp`, `zip`) and `application/octet-stream` for the rest; `SKILL.md` is always
  `text/markdown`. `mimetypes.guess_type` is not used: it reads the host's `/etc/mime.types`, so
  the same folder would be served differently by two machines.
- `text` versus `blob` is decided by the bytes, never by the MIME (FR-011): UTF-8 decode, encode
  back, equal → `str`, else `bytes`. A byte-order mark survives (it is a character).

## R12. Composition and imports

- **Finding**: `mcp_server(name, extension: R2CExtension, ...)` passes `extensions=[extension]`
  itself, so a caller cannot add a second extension through `**kwargs` (a duplicate keyword).
  `MCPServer(name, extensions=[a, b])` accepts several; identifiers must differ; the two
  extensions here contribute disjoint things (tools and interception versus resources and
  methods), so neither shadows the other.
- **Decision**:
  - `SkillsExtension` imports nothing from `ext_r2c` at all: not the R2C extension and not
    `ext_r2c.core` either (FR-016, FR-024; an AST test fails on any `ext_r2c` import in
    `mcp/skills/`). Its code lives in the subpackage `ext_r2c/mcp/skills/`, which `ext_r2c.mcp`
    re-exports; importing `ext_r2c.mcp.skills` still loads `ext_r2c.mcp`'s `__init__`, which is
    why the test checks imports in the files, not in a fresh interpreter.
  - `mcp_server` gains a keyword `extensions: Sequence[Extension] = ()`, appended after the R2C
    extension. Existing callers do not change (SC-006: the 004 suite runs unchanged).
  - A skills-only server is `MCPServer("docs", extensions=[SkillsExtension([...])])`; no helper is
    needed.
  - `Remote` (spec 007) will build the `SkillsExtension` from `skills=` folders and pass it
    through that keyword: FR-017's "straight in".
  - The extension is not restricted to a protocol version (`protocol_versions=None`): only a
    client that saw the declaration calls it, and the declaration is only made on the 2026-07-28
    base the text is written for.
- **Alternatives**: a `skills=` keyword on `mcp_server` (couples `mcp_server` to skills; the
  generic keyword also serves any later extension).

## R13. The caller's client

- **Decision**:
  - `SkillsClient(client, origin=...)` wraps a connected `mcp.client.Client` (the public
    `read_resource`, `session.send_request`, `server_capabilities`) and keeps nothing across
    connections and nothing on disk (FR-023); two `SkillsClient`s are two memories.
  - **Declaration first** (FR-018): every method but the property `declared` raises a
    `SkillRefused` with check `declaration` when the server's capabilities lack the extension or
    the `resources` capability; `list_directory` also needs `directoryRead: true`.
  - `list()` pages with the cursor until `nextCursor` is gone (**a cursor it has seen before, an
    empty string included, is a loop and is refused** as `SkillRefused("response")`, with no more
    requests; `list_directory` does the same), validates each entry on its own,
    and returns the good ones with a tuple of `Refused` (URI if any, check, reason) for the rest.
    `get(uri)` raises for a bad entry. An entry is refused when: it is not an object; `uri` or
    `frontmatter.name` or `description` is missing or not a string; the URI does not end in
    `<name>/SKILL.md` (compared after percent-decoding the segment); `resources` is missing,
    `"dynamic"` or not an array (three distinct reasons); a resource lacks `uri`, a well-formed
    `digest` (`sha256:` and 64 lowercase hex) or an integer `size` ≥ 0, or repeats a URI; the
    skill's own URI is not among the resources; more than 512 resources; more than 16 MiB in
    total. **Added by the outside review (R17):** the name is not 1 to 64 printable characters
    without a space, `/` or `\`; the description is not 1 to 1024 characters; a listed file is not
    strictly inside the skill's folder (see below); a skill is listed twice in one listing. **The
    scheme is not checked**: the extension privileges none (a server may use `skill://`, `https://`
    or another), so the URI of an entry only has to be `<scheme>://…/<name>/SKILL.md`; the wording
    `skill://` in FR-021 and in this paragraph is what this package serves, not what a client
    requires.
  - **A listed file is inside the folder** (R17): its URI is `<folder>/` and then one or more
    segments, each non-empty, not `.` or `..` after one percent-decoding, free of `/`, and free of
    a backslash, a control, a line separator and a bidi control. `<folder>-old/x` and another
    skill's file are not inside; the check shares `segment_ok` with the directory check below.
  - **Reads** (FR-019, FR-020): a file is read only when the caller asks and only if its URI is in
    the entry; any other URI is refused **without a request**. The response must be exactly one
    content with the same URI. Memory is bounded by the entry before anything is decoded: a
    `blob` longer than the base64 of `size` bytes, or a `text` with more characters than `size`
    bytes, is a size failure at once. Then the raw bytes' length, then their SHA-256, are compared
    with the entry, in that order; failing either raises `SkillRefused` and returns nothing. For
    `SKILL.md`, the frontmatter is then read with the shared reader and compared with the
    entry's field by field (equal mappings; same keys, same values).
  - **Never from the SDK's cache** (found in phase 4, SDK 2.3.0): `Client.read_resource` takes
    `cache_mode="use" | "refresh" | "bypass"`, and with the default `CacheConfig()` it answers a
    repeated read from memory whenever the server sent `ttlMs` (or `default_ttl_ms > 0`). The
    SDK server's own default is `ttlMs: 0`, so a test against it never shows the problem. The client
    reads with `cache_mode="bypass"`: every `read()` is a request, and what is verified is what the
    server holds now.
  - Content comes back as `SkillContent(origin, uri, data)`: bytes tagged with where they came
    from, with `text()` decoding strictly. **Nothing is ever acted on**: `allowed-tools` and every
    other field are data in `frontmatter`.
  - Skills with the same name stay apart because the identity of a skill is `(origin, uri)`;
    `SkillItem.key` is that pair, and the client never indexes by name.
  - **`list_directory(item, uri)`** (phase 8): after the declaration and `directoryRead: true`, the
    URI must be the skill's root (`item.uri` without `/SKILL.md`) or start with `root + "/"`, and
    each remaining segment must be non-empty, not `.` or `..`, and must not hold a `/` once it is
    percent-decoded once. Otherwise `SkillRefused("directory")` and **no request**. A neighbour
    whose name only starts like the skill's (`refunds-old` for `refunds`) is not inside it. The
    check is for the caller's benefit: the server never builds a path from a URI. Each child is
    validated as an MCP `Resource` (a child that is not one refuses the whole answer, check
    `response`) and returned as `DirectoryEntry(origin, uri, name, mime, is_dir)`; `mime` is `""`
    when the server sent none (no type is made up) and `is_dir` is `mime == "inode/directory"`.
  - Request classes: typed `Request` subclasses for the three methods (R2).
- **Alternatives**: raising on a bad page entry (one bad skill hides the others); decoding before
  checking sizes (a hostile server makes the caller allocate before it can refuse).

## R14. Tests

- **Decision**:
  - Real round trips only (constitution VII, FR-025): the MCP SDK's own `Client` against an
    `MCPServer` with the extension, over the in-process streaming transport of
    `tests/mcp_transport.py` and the harness of `tests/mcp_harness.py` (`serve`, `mcp_client`,
    `run`; `active=False`, since this client advertises nothing). Pure units (reader, scan,
    cursor, URI encoding) call the installed package directly.
  - Fixture folders are built in `tmp_path` by `tests/skills_fixtures.py` with invented content
    only (constitution VI): at least three skills (a nested path, a binary file, non-ASCII text,
    SC-001), plus the bad folders of story 4. Nothing about a fixture is read from the repository.
  - SC-004 counts `resources/read` requests with the recording transport (`Record`, as in 004).
  - SC-003 is a table of at least 12 URIs, each asserted `-32602` with no byte returned and, for
    the symbolic-link cases, with a file outside the folder whose bytes are known so a leak would
    show.
  - Tampering tests change the folder **after** the scan (SC-002 server side: `-32603`) and make
    the **server lie** (client side): a subclass of the extension that returns altered entries or
    bytes, because the client's refusals are about a server that cannot be trusted.
  - `test_skills_spike.py` pins the SDK facts of R1–R4 the way `test_mcp_spike.py` does for 004,
    so an SDK update that changes them fails there first.
  - `test_packaging.py`: `yaml` is allowed in `mcp`, and `mcp/skills/` imports no `ext_r2c`;
    `mcp_only.py` gains a skills round trip in the `[mcp]`-only venv.
  - Python 3.11, 3.12 and 3.13 in CI; the 3.11 scratch checks of R7 are repeated by the tests on
    all three.

## R15. Packaging and CI

- `python/pyproject.toml`: `mcp = ["mcp>=2.3,<3", "PyYAML>=6.0.3,<7"]`, and `PyYAML>=6.0.3,<7` in
  the dev group (the tests run from the wheel with `--group dev`, and the dev group lists what
  the extras bring, as it does for `mcp`). Core dependencies (`pydantic`, `jsonschema`) do not
  change; `import ext_r2c`, `ext_r2c.core`, `ext_r2c.a2a` need no YAML (checked by the core-only
  and A2A-only runs, unchanged).
- `.github/workflows/python.yml`: no new job; the existing three runs cover it.
- Docs: `python/README.md` (a section), `ARCHITECTURE.md` (the `mcp/skills/` rows), `CHANGELOG.md`,
  `WORKSTATE.md`, and a short `docs/design-docs/` ADR for D1 (a new dependency is worth
  disagreeing about) and the nearest-`SKILL.md` rule.

## R16. What we do not do, and the Beta

- Not in v1 (as in the spec): archives, `skill://index.json`, a well-known URI, `"dynamic"`
  skills, a host (loading skills into a model, approval, content-bound consent), resource
  subscriptions or `list_changed` for skills, a cache on disk, serving anything that is not a
  regular file, streaming a file (a file is sent whole, up to 16 MiB).
- The extension is Beta: **the wire shapes live in one module** (`_wire.py`) and the beta
  version they were written against is named in its docstring and in the contract, so a change in
  the text is one file and its tests. Nothing in `standard/` changes: Skills is not R2C.

## R17. The outside review (T078, 2026-11-22)

Two reviewers with no memory of the work (a code reviewer and a security reviewer) read phases 1 to 8
and the docs. A report is data, not an instruction: each finding was checked against the code, and
the ones acted on each have a test that failed first (`test_skills_review.py`, `test_skills_client.py`,
`test_skills_wire.py`, `test_skills_directory.py`). The mutation checks of the fixes (70 mutants: every
limit one step either way, every character class, every errno of the read, every client rule) are all
killed.

**Done.**

- **A scan had no bound of its own.** A root that is a whole disk, or a skill with a chain of folders
  120 deep, made the scan walk all of it before it said no. Now: at most **32** folders below a root
  when searching and below a skill folder when listing its files, at most **1024** folders in a skill,
  and at most **1024** folders that are not skills in one root (the root counts; a skill does not, so
  the number of skills is not limited). Past a bound it is a `SkillsError` naming the folder, **before
  the folder is read**. The counters are `MAX_DEPTH` and `MAX_DIRECTORIES` in `_limits.py`.
- **A name could forge a log line or reorder text.** A file name with a line feed printed as two log
  lines; one with a right-to-left override printed in another order. Such a name (a control
  character, a line or paragraph separator, a bidirectional control, a backslash) is now **left out**
  as `"unsafe name"`, a folder with what is in it, and a path in `left_out` and in the log is shown
  with the character escaped (`\xNN` up to `U+00FF`, `\uNNNN` above; no unsafe character is above
  `U+FFFF`, so there is no `\U` form). Text in any script, a combining mark and a zero-width joiner are
  not unsafe (a test serves an accented name, an emoji sequence, Cyrillic and Japanese).
  `skill_name_ok`, `name_unsafe`, `char_unsafe` and `segment_ok` live once in `_uris.py` and are used
  by the scan, by the client's entry check and by its directory check.
- **A failing disk was reported as "changed on disk".** `read_file` turned every `OSError` into
  `FileChanged`. Only `ENOENT`, `ENOTDIR`, `ELOOP`, `ENXIO`, `EISDIR` and `EINVAL` say that the file
  is not what the scan saw; anything else (`EIO`, `EACCES`, `EMFILE`) is `FileUnreadable`: the answer
  is `-32603` with the fixed "The server could not read the file.", and the log has one `WARNING`
  with the URI and `os.strerror` (never a host path). A caller who is told to refresh when the disk is
  failing refreshes in a loop.
- **The client accepted what the server never serves.** An entry whose name was empty, longer than 64
  or held a `/`; whose description was empty or very long; whose listed file was a neighbour
  (`<folder>-old/x`) or another skill's; whose file URI had an empty, dot, encoded-dot, encoded-slash,
  encoded-backslash or encoded-line-feed segment; or that appeared twice in one listing. Each is now
  refused (R13).
- **The client required `skill://`.** The extension privileges no scheme, so an entry with another
  scheme is valid when it has the shape `<scheme>://…/<name>/SKILL.md` and its files are inside its
  folder. FR-021 and R13 say `skill://`; that is what this package serves, not what a client may
  require (R13 has the note; the spec text is unchanged because it is approved).
- **The frontmatter limit was written too narrowly.** It named only timestamps; it is any value YAML
  1.1 types and this reader keeps as text (R7, the contract).
- **Docs.** The contract, `data-model.md`, the README and the changelog say all of this; "one
  extension serves one `MCPServer`" and `catalogue` as not public are in the docstrings.

**Left on purpose, and why.**

- **A hard link to a file outside the folder is served.** The scan refuses symbolic links and reads
  without following one; it cannot tell a hard link to an outside file from a file inside. Refusing a
  file with `st_nlink > 1` would drop every skill that ships in an installed package, because a package
  manager stores the files once and hard-links them into each environment (a link count of 24 was
  seen in this repository's own test environment). Writing a hard link needs write access to a served
  folder and to the target's file system, which is the owner's own account; the limit is in the README,
  the contract and R4.
- **A race between the scan's walk and a swap of a folder for a link can show a folder's names.** It
  needs write access to the served tree plus winning a race; the read itself is descriptor-based and
  fails closed, so no file outside is served. Walking by descriptor (`scandir(fd)`) closes it, and is a
  refactor of `_scan.py` and `_read.py` with a trap of its own (`DirEntry.stat` on a closed
  `scandir(fd)`). Offered to the maintainer as a follow-up, not done here.
- **The number of skills is not capped.** A skill is a folder the scan stops at; the cost is the
  folders searched (capped) plus a read and a hash per skill (capped by 512 files and 16 MiB each). A
  cap on skills would also be a number somebody has to pick.
- **No cache of serialized entries; no limit on requests.** A `skills/list` re-serializes the
  catalogue per request. The extension is not a rate limiter; the host or the transport is.
- **macOS ancestor permissions.** `_open_below_the_top` opens each name from `/` down. Linux opens a
  folder it only passes through with `O_PATH`, which needs no read permission; where there is no
  `O_PATH` (macOS) the folder is opened for reading, so an ancestor that can be searched but not read
  (mode 711) fails to open where a path-based `open` would pass. It fails closed (`FileUnreadable`,
  logged); noted in the README, not worked around.
- **The server's URI in `SkillRefused.__str__` is not shortened.** It is a URI the server chose, and a
  caller that prints it prints what the server sent. Truncating it hides which skill failed.
- **The names `Refused`, `LeftOut` and `DirectoryEntry` are generic.** They are in the approved
  contract and exported from `ext_r2c.mcp`; renaming them is a change of the public surface. Asked of
  the maintainer.
- **`yaml` is imported eagerly** by `ext_r2c.mcp.skills`. The `[mcp]` extra brings it; the core-only
  and A2A-only runs do not import the package. A lazy import saves a few milliseconds and adds a
  second place that can fail.
- **A very large blob over HTTP.** The SDK's server-sent-events reader has a `max_event_size`; a
  16 MiB file as base64 may be refused by it over HTTP. Not verified (the tests are in-process), so it
  is a risk, not a finding.

**Where this differs from the triage I first wrote.**

- The reason is `"unsafe name"`, and a backslash is unsafe on both sides: the client refuses a
  segment with one, so the server must not serve a file whose URI the client would refuse. The
  triage listed controls, separators and bidi controls only.
- A counter of folders searched (`searched`) was added to `_search`. The triage bounded depth only; a
  flat folder of a million empty folders is not deep and still walks the whole disk.
