# Contract: the Python API of `ext_r2c.mcp` skills

Phase 1 of [plan.md](../plan.md). Public names are exported from `ext_r2c.mcp` (and live in
`ext_r2c.mcp.skills`); everything in a module with a leading underscore is private. Needs the
`[mcp]` extra. Types are the shape, not the final source.

> **Renamed 2026-11-22** (the maintainer left the choice to us after the outside review, R17): three
> exported names were too generic for the `ext_r2c.mcp` namespace, which also holds R2C's names, and
> `Refused` sat beside the exception `SkillRefused`. `Refused` is now `RefusedEntry`, `LeftOut` is
> `LeftOutPath` and `DirectoryEntry` is `SkillDirectoryEntry`. Shape and behaviour are unchanged, and
> there are no aliases (the package is unpublished and has no outside user).

## Serving

```python
class SkillsExtension(Extension):
    """Serves skills from folders: skills/list, skills/get, resources/read of their files and,
    when directory_read is on, resources/directory/read. Beta: io.modelcontextprotocol/skills."""

    identifier = "io.modelcontextprotocol/skills"

    def __init__(
        self,
        folders: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
        *,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        directory_read: bool = True,
        ttl_ms: int = 300_000,
        cache_scope: Literal["private", "public"] = "private",
        page_size: int = 25,
    ) -> None: ...

    @property
    def skills(self) -> tuple[SkillInfo, ...]: ...      # what is served now
    @property
    def left_out(self) -> tuple[LeftOutPath, ...]: ...  # what the scan left out, and why

    def refresh(self, server: MCPServer | None = None) -> None: ...

    def settings(self) -> dict[str, Any]: ...           # {"directoryRead": directory_read}


@dataclass(frozen=True)
class SkillInfo:  name: str; uri: str; description: str; files: int; size: int
@dataclass(frozen=True)
class LeftOutPath: path: str; reason: str  # "hidden" | "symbolic link" | "not a regular file" | "undecodable name"
                                           # | "unsafe name"; path has such characters escaped (see Rules)

class SkillsError(ValueError):
    folder: str          # a root: as the owner gave it (made absolute); a skill or a folder below a
                         # root: the path the scan read (links resolved); "nothing left": every
                         # root given, joined by ", "
    reason: str          # message text is f"{folder}: {reason}"; never holds file text, and an OS
                         # error is the system's words for it ("Permission denied"), not its path
```

### Rules

- `folders` is a path or a list of paths. A bare string or `PathLike` is one folder, never a list
  of characters. At least one folder.
- `include` and `exclude` are glob patterns matched case-sensitively (`fnmatch.fnmatchcase`)
  against a skill's last path segment. A skill is served when it matches `include` (or `include`
  is empty) and no `exclude`.
- Construction scans (R6). Any problem is a `SkillsError` naming the folder and the reason;
  nothing is half built. Bad settings are `ValueError`: `ttl_ms` must be an int ≥ 0, `page_size`
  an int ≥ 1, `cache_scope` one of the two, `include` and `exclude` lists of non-empty strings.
- `skills` and `left_out` read the current catalogue. The owner is expected to log
  `left_out` (the build "says" what it left out, FR-004); the package logs one `INFO` line per
  skill and one `WARNING` per symbolic link under the logger `ext_r2c.mcp.skills`, and
  nothing at import.
- **Pages and cursors.** `skills/list` and every directory read give at most `page_size` entries
  and a `nextCursor` only when more follow. A cursor is opaque and good for **one listing of one
  catalogue**: one from another listing, another directory, an earlier refresh or another server
  is `-32602 "Invalid cursor"` (never echoed). An empty-string cursor is a bad cursor; only an
  absent one is the first page. With `directory_read=False` the method is not bound at all and the
  SDK answers `-32601`; `settings()` is `{"directoryRead": directory_read}` (default `True`).
  A folder the scan walked is a directory even when empty (it answers `[]`); a hidden or linked
  folder is not a directory.
- `refresh(server=None)` scans again with the same folders and filters. On success it swaps the
  catalogue in one assignment; on failure the old catalogue stays and the `SkillsError` is raised.
  If the new scan has a file URI the SDK has not been given a resource for, then with a `server`
  it is added through `server.add_resource`, and without one `refresh` raises `SkillsError`
  (the old catalogue stays). Until a server has asked the extension for its resources (it is
  built into one), no file is "new" and `server` is not needed. It blocks while it scans: call it
  from startup code, a signal handler, or `anyio.to_thread`. It never writes and takes no lock.
- **Refresh limits** (the SDK has no resource removal, R5): a file that disappears stays in
  `resources/list` and its read is `-32602`; a resource's `name`, `description` and MIME in
  `resources/list` keep their values from when it was registered. `skills/list`, `skills/get`
  and directory reads always show the new catalogue.
- **Limits are refused at the first file past them** ("has more than 512 files", "holds more than
  16777216 bytes"), from `stat` sizes, when nothing but `SKILL.md` has been read; the message does
  not count the files or bytes beyond that.
- **v1 limits**: a `name` must match `^[a-z0-9]+(-[a-z0-9]+)*$` (≤ 64) — ASCII only; a nested
  `SKILL.md` is an ordinary file of the outer skill and is not served as a skill (R6); a file is
  sent whole; the frontmatter text is at most 64 KiB.
- **Scan bounds** (R17), whatever the tree: a folder is searched at most 32 folders below its root;
  a skill holds no folder more than 32 below its own and at most 1024 folders (an empty one
  counts); a root searches at most 1024 folders that are not skills (the root counts, a skill does
  not, and the number of skills is not limited). Past a bound the scan is a `SkillsError` naming the
  folder, before the folder is read.
- **Names that are not safe to print.** A file or folder whose name has a control character (a
  line feed, an escape, `U+0085`), a line or paragraph separator (`U+2028`, `U+2029`), a
  bidirectional control (`U+061C`, `U+200E`, `U+200F`, `U+202A`–`U+202E`, `U+2066`–`U+2069`) or a
  backslash is **left out** as `"unsafe name"` (a folder with what is in it), like a name that is
  not text. Text in any script, a combining mark and a zero-width joiner are not unsafe. In
  `left_out` and in the log, a path is shown with such a character as `\xNN` (up to `U+00FF`) or
  `\uNNNN`, and a byte that is not text as `\xNN`, so a name cannot forge a log line or reorder one.
- **A file that cannot be read** is told apart from one that changed. The system errors that say
  the file is not what the scan saw (`ENOENT`, `ENOTDIR`, `ELOOP`, `ENXIO`, `EISDIR`, `EINVAL`) are
  `-32603` with the fixed "The skills changed on disk since they were scanned; refresh them." Any
  other (`EIO`, `EACCES`, `EMFILE`, …) is `-32603` with the fixed "The server could not read the
  file."; the log has one `WARNING` with the URI and the system's words, never a path of this host.
- **A hard link is not a link.** A file with more than one hard link is an ordinary file: the scan
  does not follow names that point elsewhere (symbolic links), and cannot tell a hard link to a
  file outside the folder from a file inside it. Do not make hard links to files that must not be
  served inside a served folder (a package manager's store does, and its files are served).
- **One extension serves one `MCPServer`**: what the SDK has been given a resource for is kept in
  the extension, so a file that a refresh adds is added to the one server `refresh(server)` is
  given.

### Using it

```python
skills = SkillsExtension(["skills"], exclude=["draft-*"])
server = MCPServer("docs", extensions=[skills])                 # alone, hand-built
server = mcp_server("agent", R2CExtension(tools=[...]), extensions=[skills])   # beside R2C
```

### `mcp_server` (changed)

```python
def mcp_server(name: str, extension: R2CExtension, *, extensions: Sequence[Extension] = (),
               security: RequestStateSecurity | None = None, **mcp_server_kwargs: Any) -> MCPServer: ...
```

`extensions` are served after the R2C extension. Without it, behaviour is exactly as in spec 004.

## The caller's client

```python
class SkillsClient:
    def __init__(self, client: mcp.client.Client, *, origin: str) -> None: ...

    @property
    def declared(self) -> bool: ...                 # extension and resources capability seen
    @property
    def directory_read(self) -> bool: ...           # directoryRead: true was declared

    async def list(self) -> SkillListing: ...                         # every page; no file read
    async def get(self, uri: str) -> SkillItem: ...                   # skills/get; refuses a bad entry
    async def load(self, item: SkillItem) -> LoadedSkill: ...         # reads and verifies SKILL.md only
    async def read(self, item: SkillItem, uri: str) -> SkillContent: ...   # one listed file, verified
    async def list_directory(self, item: SkillItem, uri: str) -> tuple[SkillDirectoryEntry, ...]: ...
```

### Rules

- `origin` is the caller's label for this server (non-empty). It tags every item and content, and
  with the URI it is a skill's identity (`SkillItem.key`); the client never indexes by name.
- Every method except the two properties checks the declaration first and raises
  `SkillRefused(check="declaration")` if it is missing; `list_directory` also needs
  `directory_read` (`check="directory"`). Nothing is sent before the check.
- `list` and `get` send only `skills/list` / `skills/get`. `list` follows `nextCursor` until it is
  absent and returns every valid entry plus the `RefusedEntry` for each invalid one (R13 lists what
  makes an entry invalid). A `nextCursor` the client has already received in this listing (an
  empty string too) is a loop: `SkillRefused(check="response")`, and no further request.
  `get` raises `SkillRefused(check="entry" | "resources" | "limit")`.
- **An entry is valid** (R13, R17) when all of this holds, and refused otherwise (`entry` for the entry
  itself, `resources` for its file list, `limit` for a limit): it is an object with a string `uri` and a
  `frontmatter` object; the `name` is 1 to 64 printable characters with no space, `/` or `\`; the
  `description` is 1 to 1024 characters; the `uri` is `<scheme>://…/<name>/SKILL.md` for that name,
  with **any** scheme (the extension privileges none; `skill://` is what this package serves); it
  lists its files (not `"dynamic"`, not missing), at most 512 and 16 MiB in all, each with a `uri`
  **strictly inside** the skill's folder (`<folder>/` and then segments, each non-empty, not `.` or
  `..`, free of `/`, a backslash and control, line-break or bidi characters after one
  percent-decoding; a neighbour such as `<folder>-old/…` or another skill's file is not inside), a
  `sha256:<64 lowercase hex>` digest and a whole-number size, none twice, its own `SKILL.md`
  among them. A skill listed twice in one listing (same `uri`) is returned once and the second is
  refused (`entry`).
- `load` and `read` send `resources/read` **only when called**, and `read` only for a URI listed
  in `item.files` (`check="unlisted"` otherwise, without a request). They verify, in this order:
  one content with the same URI (`response`); raw length against `size` (`size`; a `blob` or
  `text` larger than `size` allows is refused before it is decoded); SHA-256 against `digest`
  (`digest`); and, for the skill's `SKILL.md`, the frontmatter read by the shared reader
  against `item.frontmatter`, field by field (`frontmatter`). A failure raises `SkillRefused`
  with the URI, the check and the reason, and returns nothing.
- `list_directory` sends `resources/directory/read` for the skill's root (the entry's URI without
  `/SKILL.md`) or a path below it (`root/…`, so `refunds-old` is not inside `refunds`); every
  segment after the root must be non-empty, not `.` or `..`, and free of `/`, each after one
  percent-decoding. Any other URI is refused (`check="directory"`) without a request. It follows
  every page (a repeated cursor is `response`, as for `list`) and returns the children as
  `SkillDirectoryEntry(origin, uri, name, mime, is_dir)`; `mime` is `""` when the server sent none
  (none is made up), and `is_dir` is `mime == "inode/directory"`. A child that is not an MCP
  resource refuses the whole answer (`response`). It never extends the manifest: a child the entry
  does not list is returned as metadata, and `read` still refuses it as `unlisted` (the text's
  "directory is not the manifest").
- Nothing is cached across connections and nothing is written to disk. Content is untrusted: no
  frontmatter field is interpreted. `SkillContent.text()` decodes strictly and raises on invalid
  UTF-8.
- **Known limit**: the frontmatter comparison uses this package's reader, which keeps a plain
  scalar that YAML 1.1 would type (`yes`, `off`, `0755`, `0x1f`, `1_000`, `12:30`, a timestamp) as the
  text the author wrote. An entry from another server that typed such a value (a boolean, a number, a
  rendered timestamp) differs from what this client reads in `SKILL.md`, and is refused
  (`check="frontmatter"`) although the server is honest by its own reader (R7, R17).

### Types

```python
@dataclass(frozen=True)
class SkillFileRef:   uri: str; size: int; digest: str
@dataclass(frozen=True)
class SkillItem:      origin: str; uri: str; name: str; description: str
                      frontmatter: Mapping[str, Any]; files: tuple[SkillFileRef, ...]
                      @property key -> tuple[str, str]       # (origin, uri)
@dataclass(frozen=True)
class RefusedEntry:   uri: str | None; check: str; reason: str
@dataclass(frozen=True)
class SkillListing:   skills: tuple[SkillItem, ...]; refused: tuple[RefusedEntry, ...]
@dataclass(frozen=True)
class SkillContent:   origin: str; uri: str; data: bytes; def text(self) -> str
@dataclass(frozen=True)
class LoadedSkill:    item: SkillItem; instructions: SkillContent
@dataclass(frozen=True)
class SkillDirectoryEntry: origin: str; uri: str; name: str; mime: str; is_dir: bool
class SkillRefused(Exception): uri: str | None; check: str; reason: str
```

## What `Remote` (spec 007) will do

Build `SkillsExtension(skills_folders, include=..., exclude=...)` from its `skills=` argument and
hand it to `mcp_server(..., extensions=[skills])`. A `SkillsError` at build is raised from
`Remote(...)` as it is, naming the folder.
