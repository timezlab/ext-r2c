# Contract: the Python API of `ext_r2c.mcp` skills

Phase 1 of [plan.md](../plan.md). Public names are exported from `ext_r2c.mcp` (and live in
`ext_r2c.mcp.skills`); everything in a module with a leading underscore is private. Needs the
`[mcp]` extra. Types are the shape, not the final source.

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
    def left_out(self) -> tuple[LeftOut, ...]: ...      # what the scan left out, and why

    def refresh(self, server: MCPServer | None = None) -> None: ...

    def settings(self) -> dict[str, Any]: ...           # {"directoryRead": directory_read}


@dataclass(frozen=True)
class SkillInfo:  name: str; uri: str; description: str; files: int; size: int
@dataclass(frozen=True)
class LeftOut:    path: str; reason: str   # "hidden" | "symbolic link" | "not a regular file" | "undecodable name"

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
    async def list_directory(self, item: SkillItem, uri: str) -> tuple[DirectoryEntry, ...]: ...
```

### Rules

- `origin` is the caller's label for this server (non-empty). It tags every item and content, and
  with the URI it is a skill's identity (`SkillItem.key`); the client never indexes by name.
- Every method except the two properties checks the declaration first and raises
  `SkillRefused(check="declaration")` if it is missing; `list_directory` also needs
  `directory_read` (`check="directory"`). Nothing is sent before the check.
- `list` and `get` send only `skills/list` / `skills/get`. `list` follows `nextCursor` until it is
  absent and returns every valid entry plus the `Refused` for each invalid one (R13 lists what
  makes an entry invalid). `get` raises `SkillRefused(check="entry" | "resources" | "limit")`.
- `load` and `read` send `resources/read` **only when called**, and `read` only for a URI listed
  in `item.files` (`check="unlisted"` otherwise, without a request). They verify, in this order:
  one content with the same URI (`response`); raw length against `size` (`size`; a `blob` or
  `text` larger than `size` allows is refused before it is decoded); SHA-256 against `digest`
  (`digest`); and, for the skill's `SKILL.md`, the frontmatter read by the shared reader
  against `item.frontmatter`, field by field (`frontmatter`). A failure raises `SkillRefused`
  with the URI, the check and the reason, and returns nothing.
- `list_directory` sends `resources/directory/read` for the skill's root (the entry's URI without
  `/SKILL.md`) or a path below it; any other URI is refused (`check="directory"`) without a
  request. It follows every page and returns the children as metadata. It never extends the manifest: a child the entry does not list is returned as
  metadata, and `read` still refuses it as `unlisted` (the text's "directory is not the
  manifest").
- Nothing is cached across connections and nothing is written to disk. Content is untrusted: no
  frontmatter field is interpreted. `SkillContent.text()` decodes strictly and raises on invalid
  UTF-8.
- **Known limit**: the frontmatter comparison uses this package's reader; an entry from another
  server whose rendering of a YAML timestamp differs from the author's text is refused (R7).

### Types

```python
@dataclass(frozen=True)
class SkillFileRef:   uri: str; size: int; digest: str
@dataclass(frozen=True)
class SkillItem:      origin: str; uri: str; name: str; description: str
                      frontmatter: Mapping[str, Any]; files: tuple[SkillFileRef, ...]
                      @property key -> tuple[str, str]       # (origin, uri)
@dataclass(frozen=True)
class Refused:        uri: str | None; check: str; reason: str
@dataclass(frozen=True)
class SkillListing:   skills: tuple[SkillItem, ...]; refused: tuple[Refused, ...]
@dataclass(frozen=True)
class SkillContent:   origin: str; uri: str; data: bytes; def text(self) -> str
@dataclass(frozen=True)
class LoadedSkill:    item: SkillItem; instructions: SkillContent
@dataclass(frozen=True)
class DirectoryEntry: origin: str; uri: str; name: str; mime: str; is_dir: bool
class SkillRefused(Exception): uri: str | None; check: str; reason: str
```

## What `Remote` (spec 007) will do

Build `SkillsExtension(skills_folders, include=..., exclude=...)` from its `skills=` argument and
hand it to `mcp_server(..., extensions=[skills])`. A `SkillsError` at build is raised from
`Remote(...)` as it is, naming the folder.
