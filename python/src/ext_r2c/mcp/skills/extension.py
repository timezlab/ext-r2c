"""`SkillsExtension`: skills served from folders as an MCP SDK `Extension` (spec 005, research R1).

It binds `skills/list` and `skills/get` (and `resources/directory/read` unless `directory_read` is
off), registers one resource per served file so `resources/read` and `resources/list` work for any
client, and declares itself in `server/discover`. A handler reads the catalogue once and answers from
that object; a request URI is only ever looked up as a whole string in it, never turned into a path.

The settings are checked first (a bad one is a `ValueError`), then the folders are scanned (a problem
with them is a `SkillsError`); `refresh()` scans again and swaps the new catalogue in whole.
`skills/list` and a directory answer `page_size` entries at a time; a cursor is good for the one
listing and the one catalogue it came from (R9).

One extension serves one `MCPServer`: which files the SDK has been given a resource for is kept in the
extension, so a second server built from the same extension would not be given the files a refresh adds.

A file is read when it is asked for, and only then. If the bytes are no longer the ones the scan saw (the
file is gone, is another kind of thing, or has other bytes) the answer is `-32603` with `CHANGED`; if the
system cannot read it for any other reason (a failing disk, no permission, too many open files) the answer
is `-32603` with `UNREADABLE` and the log has one `WARNING` with the URI and the system's words, never a
path of this host.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any, Literal

import anyio.to_thread
import mcp_types as types
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import Resource
from mcp.shared.exceptions import MCPError
from pydantic import Field

from ._catalogue import Catalogue, Child, FileRecord, LeftOut, SkillInfo, SkillRecord, SkillsError
from ._content import DIRECTORY, as_text_or_bytes
from ._cursor import CursorError, decode_cursor, encode_cursor
from ._read import FileChanged, FileUnreadable, read_file
from ._scan import scan_roots
from ._settings import cache_scope_of, directory_read_of, folders_of, page_size_of, patterns_of, ttl_ms_of
from ._wire import (
    EXTENSION_ID,
    METHOD_DIRECTORY,
    METHOD_GET,
    METHOD_LIST,
    GetSkillParams,
    GetSkillResult,
    ListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryResult,
    Skill,
    SkillResource,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

CHANGED = "The skills changed on disk since they were scanned; refresh them."
UNREADABLE = "The server could not read the file."
log = logging.getLogger("ext_r2c.mcp.skills")


def _announce(catalogue: Catalogue) -> None:
    """Say what a build serves (one `INFO` line per skill) and which links it refused to follow (one
    `WARNING` each). Hidden entries and pipes are in `left_out`, not in the log."""
    for skill in catalogue.skills:
        log.info("Serving skill %s: %d files, %d bytes", skill.uri, len(skill.files), sum(f.size for f in skill.files))
    for item in catalogue.left_out:
        if item.reason == "symbolic link":
            log.warning("Not serving the symbolic link %s: a link is never followed", item.path)


def _named(skill: SkillRecord, record: FileRecord) -> tuple[str, str | None]:
    """The name and description a file is given wherever it is listed (`resources/list` and a directory
    alike): the skill's own `SKILL.md` carries the frontmatter's name and description; any other file,
    a `SKILL.md` below the root included, is named by its file name."""
    if record.uri == skill.uri:
        return skill.name, skill.frontmatter["description"]
    return record.parts[-1], None


class SkillFile(Resource):
    """One served file. Its bytes are not held: a read asks the extension, which opens the file
    again and checks it against the entry."""

    serve: Callable[[str], Awaitable[str | bytes]] = Field(repr=False, exclude=True)

    async def read(self) -> str | bytes:
        return await self.serve(str(self.uri))


class SkillsExtension(Extension):
    """Serves the skills found under `folders`: `skills/list`, `skills/get` and the files through
    `resources/read`. Beta: `io.modelcontextprotocol/skills`."""

    identifier = EXTENSION_ID

    def __init__(
        self,
        folders: str | os.PathLike[str] | Sequence[str | os.PathLike[str]],
        *,
        include: Sequence[str] = (),
        exclude: Sequence[str] = (),
        ttl_ms: int = 300_000,
        cache_scope: Literal["private", "public"] = "private",
        page_size: int = 25,
        directory_read: bool = True,
    ) -> None:
        """`include` and `exclude` are glob patterns matched, case-sensitively, against the name of a
        skill's folder: a skill is served when it matches an `include` (or there is none) and no
        `exclude`. `page_size` is how many skills `skills/list` (and how many children a directory)
        answers at a time. `directory_read` turns `resources/directory/read` on or off; with it off
        discovery says so and the method is not there. A bad setting raises `ValueError`; anything
        wrong with the folders raises `SkillsError`, naming the folder."""
        self._folders = folders_of(folders)
        self._include = patterns_of("include", include)
        self._exclude = patterns_of("exclude", exclude)
        self._ttl_ms = ttl_ms_of(ttl_ms)
        self._cache_scope = cache_scope_of(cache_scope)
        self._page_size = page_size_of(page_size)
        self._directory_read = directory_read_of(directory_read)
        # The file URIs the SDK has been given a resource for; `None` until a server asks (`resources()`).
        self._registered: set[str] | None = None
        self._catalogue = scan_roots(self._folders, self._include, self._exclude)
        _announce(self._catalogue)

    @property
    def catalogue(self) -> Catalogue:
        """What is served now, whole. For this package and its tests: it is not part of the public
        surface (`skills` and `left_out` are), and its shape may change."""
        return self._catalogue

    @property
    def left_out(self) -> tuple[LeftOut, ...]:
        """What the scan did not serve, and why: hidden entries, symbolic links, anything that is
        not a regular file, names that are not text and names that are not safe to print. Sorted by
        path below the folder given, each path with such a character escaped."""
        return self._catalogue.left_out

    @property
    def skills(self) -> tuple[SkillInfo, ...]:
        """What is served now, one line per skill."""
        return tuple(
            SkillInfo(
                name=skill.name,
                uri=skill.uri,
                description=skill.frontmatter["description"],
                files=len(skill.files),
                size=sum(record.size for record in skill.files),
            )
            for skill in self._catalogue.skills
        )

    def settings(self) -> dict[str, Any]:
        return {"directoryRead": self._directory_read}

    def resources(self) -> list[ResourceBinding]:
        """One resource per served file; the SDK reads this once, when the server is built."""
        catalogue = self._catalogue
        self._registered = {*(self._registered or ()), *catalogue.files}
        return [ResourceBinding(self._resource(skill, record)) for skill in catalogue.skills for record in skill.files]

    def refresh(self, server: MCPServer | None = None) -> None:
        """Scan the folders again, with the same filters, and serve what the new scan found.

        The new catalogue is built whole and then put in place with one assignment, so a request sees
        one scan from its first line to its last. If the scan fails, the old catalogue keeps serving
        and the `SkillsError` is raised. A file whose URI the SDK has not been given a resource for
        needs the `server` the extension is served by (it is added with `add_resource`); without
        one that is a `SkillsError` and nothing changes.

        The SDK cannot remove a resource: a file that is gone stays in `resources/list` with the
        name, description and type it had, and reading it is `-32602`. Blocks while it scans: call
        it from startup code, a signal handler or `anyio.to_thread`. It never writes.
        """
        catalogue = scan_roots(self._folders, self._include, self._exclude)
        registered = self._registered
        if registered is not None:  # before a server has asked for the resources, it is missing nothing
            new = [
                (skill, record)
                for skill in catalogue.skills
                for record in skill.files
                if record.uri not in registered
            ]
            if new and server is None:
                skill, record = new[0]
                raise SkillsError(skill.folder, f"{record.uri} is new, and only refresh(server) can give a new file to the server")
            if server is not None:
                # Registered before the swap, so that `skills/list` (what a client follows) never lists
                # a file the SDK would not find. For an instant `resources/list` can show a new file
                # that a read still refuses, because a read looks in the catalogue that is still the old one.
                for skill, record in new:
                    server.add_resource(self._resource(skill, record))
                    registered.add(record.uri)
        self._catalogue = catalogue
        _announce(catalogue)

    def methods(self) -> list[MethodBinding]:
        bindings = [
            MethodBinding(METHOD_LIST, types.PaginatedRequestParams, self._list),
            MethodBinding(METHOD_GET, GetSkillParams, self._get),
        ]
        if self._directory_read:  # off: the SDK answers -32601 for a method nobody binds
            bindings.append(MethodBinding(METHOD_DIRECTORY, ReadDirectoryParams, self._directory))
        return bindings

    # --- Two points a test overrides to make a server lie ---------------------------------------

    def _entry(self, skill: SkillRecord) -> Skill:
        """The wire entry of one skill, as `skills/list` and `skills/get` send it."""
        return Skill(
            uri=skill.uri,
            frontmatter=skill.frontmatter,
            resources=[SkillResource(uri=r.uri, digest=r.digest, size=r.size) for r in skill.files],
        )

    def _read_bytes(self, record: FileRecord) -> bytes:
        """The bytes of one served file, checked against the entry (runs in a worker thread)."""
        return read_file(record)

    # --- The handlers ---------------------------------------------------------------------------

    def _page(self, scope: str, total: int, cursor: str | None) -> tuple[int, int, str | None]:
        """Where a page starts and ends, and the cursor of the page after it (`None` on the last).
        `scope` names the one listing the cursor is good for. An empty-string cursor is a cursor, and a
        bad one: only `None` means the first page."""
        start = 0
        if cursor is not None:
            try:
                start = decode_cursor(cursor, scope, total)
            except CursorError as error:
                raise MCPError(code=types.INVALID_PARAMS, message=str(error)) from None
        end = start + self._page_size
        return start, end, encode_cursor(scope, end) if end < total else None

    async def _list(self, ctx: Any, params: types.PaginatedRequestParams | None) -> ListSkillsResult:
        catalogue = self._catalogue
        start, end, cursor = self._page(
            catalogue.generation, len(catalogue.skills), None if params is None else params.cursor
        )
        return ListSkillsResult(
            skills=[self._entry(skill) for skill in catalogue.skills[start:end]],
            next_cursor=cursor,
            ttl_ms=self._ttl_ms,
            cache_scope=self._cache_scope,
        )

    async def _directory(self, ctx: Any, params: ReadDirectoryParams) -> ReadDirectoryResult:
        """The direct children of one directory of a served skill, from the catalogue: the disk is not
        asked. The cursor is good for this directory of this catalogue only."""
        catalogue = self._catalogue
        directory = catalogue.directories.get(params.uri)
        if directory is None:
            raise MCPError(code=types.INVALID_PARAMS, message=f"No directory is served at {params.uri}")
        scope = f"{catalogue.generation}-{hashlib.sha256(params.uri.encode()).hexdigest()[:16]}"
        start, end, cursor = self._page(scope, len(directory.children), params.cursor)
        return ReadDirectoryResult(
            resources=[self._child(catalogue, child) for child in directory.children[start:end]],
            next_cursor=cursor,
            ttl_ms=self._ttl_ms,
            cache_scope=self._cache_scope,
        )

    @staticmethod
    def _child(catalogue: Catalogue, child: Child) -> types.Resource:
        """A child of a directory as `resources/list` describes it (a folder is `inode/directory`)."""
        if child.is_dir:
            return types.Resource(uri=child.uri, name=child.name, mime_type=DIRECTORY)
        record = catalogue.files[child.uri]
        name, description = _named(catalogue.by_uri[record.skill], record)
        return types.Resource(uri=child.uri, name=name, description=description, mime_type=child.mime)

    async def _get(self, ctx: Any, params: GetSkillParams) -> GetSkillResult:
        skill = self._catalogue.by_uri.get(params.uri)
        if skill is None:
            raise MCPError(code=types.INVALID_PARAMS, message=f"No skill is served at {params.uri}")
        return GetSkillResult(skill=self._entry(skill), ttl_ms=self._ttl_ms, cache_scope=self._cache_scope)

    async def _serve(self, uri: str) -> str | bytes:
        record = self._catalogue.files.get(uri)
        if record is None:  # registered once, gone since a refresh: the SDK cannot unregister it
            raise MCPError(code=types.INVALID_PARAMS, message=f"No file is served at {uri}")
        try:
            data = await anyio.to_thread.run_sync(self._read_bytes, record)
        except FileChanged:
            raise MCPError(code=types.INTERNAL_ERROR, message=CHANGED) from None
        except FileUnreadable as error:
            # The owner's to fix, and a caller can do nothing about it: the log has the system's words
            # and the URI (never a host path), the answer has neither.
            log.warning("Cannot read %s: %s", uri, os.strerror(error.code))
            raise MCPError(code=types.INTERNAL_ERROR, message=UNREADABLE) from None
        return as_text_or_bytes(data)

    def _resource(self, skill: SkillRecord, record: FileRecord) -> SkillFile:
        """The SDK resource of one file, named as `_named` says."""
        name, description = _named(skill, record)
        return SkillFile(uri=record.uri, name=name, description=description, mime_type=record.mime, serve=self._serve)
