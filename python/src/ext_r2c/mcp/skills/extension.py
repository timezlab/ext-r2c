"""`SkillsExtension`: skills served from folders as an MCP SDK `Extension` (spec 005, research R1).

It binds `skills/list` and `skills/get`, registers one resource per served file so `resources/read`
and `resources/list` work for any client, and declares itself in `server/discover`. A handler reads
the catalogue once and answers from that object; a request URI is only ever looked up as a whole
string in it, never turned into a path.

First cut (phase 3): all skills on one page, no directory method, and the settings are not checked
yet; later phases add them.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

import anyio.to_thread
import mcp_types as types
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import Resource
from mcp.shared.exceptions import MCPError
from pydantic import Field

from ._catalogue import Catalogue, FileRecord, SkillInfo, SkillRecord
from ._content import as_text_or_bytes
from ._read import FileChanged, read_file
from ._scan import scan_roots
from ._wire import (
    EXTENSION_ID,
    METHOD_GET,
    METHOD_LIST,
    GetSkillParams,
    GetSkillResult,
    ListSkillsResult,
    Skill,
    SkillResource,
)

CHANGED = "The skills changed on disk since they were scanned; refresh them."


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
        ttl_ms: int = 300_000,
        cache_scope: Literal["private", "public"] = "private",
    ) -> None:
        self._folders: tuple[str | os.PathLike[str], ...] = (
            (folders,) if isinstance(folders, (str, os.PathLike)) else tuple(folders)
        )
        self._ttl_ms = ttl_ms
        self._cache_scope = cache_scope
        self._catalogue = scan_roots(self._folders, (), ())

    @property
    def catalogue(self) -> Catalogue:
        """What is served now."""
        return self._catalogue

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
        return {"directoryRead": False}  # the directory method comes with phase 8

    def resources(self) -> list[ResourceBinding]:
        return [
            ResourceBinding(self._resource(skill, record)) for skill in self._catalogue.skills for record in skill.files
        ]

    def methods(self) -> list[MethodBinding]:
        return [
            MethodBinding(METHOD_LIST, types.PaginatedRequestParams, self._list),
            MethodBinding(METHOD_GET, GetSkillParams, self._get),
        ]

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

    async def _list(self, ctx: Any, params: types.PaginatedRequestParams | None) -> ListSkillsResult:
        catalogue = self._catalogue
        return ListSkillsResult(
            skills=[self._entry(skill) for skill in catalogue.skills],
            ttl_ms=self._ttl_ms,
            cache_scope=self._cache_scope,
        )

    async def _get(self, ctx: Any, params: GetSkillParams) -> GetSkillResult:
        skill = self._catalogue.by_uri.get(params.uri)
        if skill is None:
            raise MCPError(code=types.INVALID_PARAMS, message=f"No skill is served at {params.uri}")
        return GetSkillResult(skill=self._entry(skill), ttl_ms=self._ttl_ms, cache_scope=self._cache_scope)

    async def _serve(self, uri: str) -> str | bytes:
        record = self._catalogue.files[uri]
        try:
            data = await anyio.to_thread.run_sync(self._read_bytes, record)
        except FileChanged:
            raise MCPError(code=types.INTERNAL_ERROR, message=CHANGED) from None
        return as_text_or_bytes(data)

    def _resource(self, skill: SkillRecord, record: FileRecord) -> SkillFile:
        """The SDK resource of one file. The skill's own `SKILL.md` carries the frontmatter's name
        and description; any other file is named by its file name."""
        if record.uri == skill.uri:
            name, description = skill.name, skill.frontmatter["description"]
        else:
            name, description = record.parts[-1], None
        return SkillFile(uri=record.uri, name=name, description=description, mime_type=record.mime, serve=self._serve)
