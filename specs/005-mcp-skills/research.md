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
    `{"directoryRead": true}`, and the `resources` capability is declared as soon as one resource
    is registered. A skill always has at least `SKILL.md`, and a server with no skill is a build
    error (FR-007), so the `resources` declaration the extension requires always holds.
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
- **Alternatives**: a `[skills]` extra (a second install step for a feature `Remote` should get
  with `[mcp]`); a hand-written subset parser (a valid skill the parser misreads is served
  wrongly, and the client would misread it the same way, so the check would agree with the
  error); `ruamel.yaml` (a larger package, same vet needed, round-trip features we do not use).
- **Known limit**: the client compares the entry's frontmatter with what **this** reader makes of
  the `SKILL.md` it fetched. An entry from another server that rendered a YAML timestamp as a
  different string than the author's text is refused: a false refusal, the safe direction, named
  in the contract.

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
    is `-32602` with a fixed message. It carries no path and grants nothing.
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
  - `list()` pages with the cursor until `nextCursor` is gone, validates each entry on its own,
    and returns the good ones with a tuple of `Refused` (URI if any, check, reason) for the rest.
    `get(uri)` raises for a bad entry. An entry is refused when: it is not an object; `uri` or
    `frontmatter.name` or `description` is missing or not a string; the URI does not end in
    `<name>/SKILL.md` (compared after percent-decoding the segment); `resources` is missing,
    `"dynamic"` or not an array (three distinct reasons); a resource lacks `uri`, a well-formed
    `digest` (`sha256:` and 64 lowercase hex) or an integer `size` ≥ 0, or repeats a URI; the
    skill's own URI is not among the resources; more than 512 resources; more than 16 MiB in
    total.
  - **Reads** (FR-019, FR-020): a file is read only when the caller asks and only if its URI is in
    the entry; any other URI is refused **without a request**. The response must be exactly one
    content with the same URI. Memory is bounded by the entry before anything is decoded: a
    `blob` longer than the base64 of `size` bytes, or a `text` with more characters than `size`
    bytes, is a size failure at once. Then the raw bytes' length, then their SHA-256, are compared
    with the entry, in that order; failing either raises `SkillRefused` and returns nothing. For
    `SKILL.md`, the frontmatter is then read with the shared reader and compared with the
    entry's field by field (equal mappings; same keys, same values).
  - Content comes back as `SkillContent(origin, uri, data)`: bytes tagged with where they came
    from, with `text()` decoding strictly. **Nothing is ever acted on**: `allowed-tools` and every
    other field are data in `frontmatter`.
  - Skills with the same name stay apart because the identity of a skill is `(origin, uri)`;
    `SkillItem.key` is that pair, and the client never indexes by name.
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
