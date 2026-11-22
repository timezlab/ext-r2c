"""The caller's client of MCP Skills (spec 005, research R13).

`SkillsClient` wraps a connected MCP SDK `Client`. It lists the skills a server offers, loads one on
demand and VERIFIES every file against the entry the server gave: the size, the SHA-256 and, for a
skill's own `SKILL.md`, the frontmatter. What does not verify raises `SkillRefused` and returns
nothing. Four rules hold everywhere:

- **Declaration first.** A server that did not declare the extension (with the `resources`
  capability) gets no skills request at all.
- **Nothing ahead of need.** A listing and a `get` read no file; a file is read when the caller asks,
  and only if its URI is in the entry. Any other URI is refused without a request.
- **Never trust, never act.** Content is untrusted bytes tagged with where they came from. No
  frontmatter field is interpreted: `allowed-tools` and the rest are data.
- **Nothing is kept.** No cache across calls or connections, nothing on disk. The SDK's own response
  cache is bypassed on every read, so each read reaches the server and is checked.

A reason is fixed text. It never carries the file's content or a field a server chose.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

import mcp_types as types
from mcp.client import Client
from pydantic import ValidationError

from ._frontmatter import FrontmatterError, read_frontmatter
from ._limits import MAX_BYTES, MAX_FILES
from ._uris import SKILL_FILE, last_segments
from ._wire import (
    EXTENSION_ID,
    GetSkillParams,
    GetSkillRequest,
    ListSkillsRequest,
    RawGetSkillResult,
    RawListSkillsResult,
)

Check = Literal[
    "declaration",  # the server did not declare the extension (or the resources capability)
    "entry",  # an entry is not a well-formed skill
    "resources",  # an entry's list of files is not well-formed
    "limit",  # an entry is over 512 files or 16 MiB
    "unlisted",  # a file the entry does not list
    "response",  # an answer that is not what was asked for
    "size",  # the bytes are not as many as the entry says
    "digest",  # the bytes are not the ones the entry hashed
    "frontmatter",  # SKILL.md says something other than the entry
    "directory",  # a directory read the server did not offer, or for a URI outside the skill
]

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_MISSING: Any = object()


# --- The types ---------------------------------------------------------------------------------------


class SkillRefused(Exception):
    """What a skills call refuses: `check` says which rule, `reason` is fixed text, and `uri` is the
    skill or file concerned, if there is one."""

    def __init__(self, check: Check, reason: str, uri: str | None = None) -> None:
        super().__init__(check, reason, uri)  # all three, so the exception survives pickling
        self.check = check
        self.reason = reason
        self.uri = uri

    def __str__(self) -> str:
        text = f"{self.check}: {self.reason}"
        # `repr` keeps a URI the server chose on one line: it cannot forge a second log line.
        return text if self.uri is None else f"{text} ({self.uri!r})"


@dataclass(frozen=True)
class SkillFileRef:
    """A file as the entry lists it: where to read it and what the bytes must be."""

    uri: str
    size: int
    digest: str


@dataclass(frozen=True)
class SkillItem:
    """One skill, as a server's entry described it and as this client validated it. Its identity is
    `key`, the pair of the server's `origin` and the skill's `uri`, never its name."""

    origin: str
    uri: str
    name: str
    description: str
    frontmatter: Mapping[str, Any]
    files: tuple[SkillFileRef, ...]

    @property
    def key(self) -> tuple[str, str]:
        return (self.origin, self.uri)

    def __hash__(self) -> int:
        # The frontmatter is a mapping and cannot be hashed; the rest says which skill this is.
        return hash((self.origin, self.uri, self.name, self.description, self.files))


@dataclass(frozen=True)
class Refused:
    """An entry of a listing that did not validate, and why (the others are still returned)."""

    uri: str | None
    check: Check
    reason: str


@dataclass(frozen=True)
class SkillListing:
    skills: tuple[SkillItem, ...]
    refused: tuple[Refused, ...]


@dataclass(frozen=True)
class SkillContent:
    """The bytes of one verified file, tagged with the server they came from."""

    origin: str
    uri: str
    data: bytes

    def text(self) -> str:
        """The bytes as UTF-8, strictly: invalid bytes raise `UnicodeDecodeError`, none are replaced
        or guessed, and a byte-order mark stays a character."""
        return self.data.decode("utf-8")


@dataclass(frozen=True)
class LoadedSkill:
    """A skill whose `SKILL.md` was read and verified."""

    item: SkillItem
    instructions: SkillContent


@dataclass(frozen=True)
class DirectoryEntry:
    """One child of a directory, as metadata only: it is not a file the entry lists."""

    origin: str
    uri: str
    name: str
    mime: str
    is_dir: bool


# --- An entry: one raw JSON value in, a SkillItem or a refusal out ----------------------------------


def parse_entry(origin: str, raw: object) -> SkillItem:
    """Validate one entry of `skills/list` or `skills/get`. The refusal carries the entry's own URI
    when it has one that is a string."""
    if not isinstance(raw, dict):
        raise SkillRefused("entry", "the entry is not an object")
    uri = raw.get("uri")
    if not isinstance(uri, str):
        raise SkillRefused("entry", "the entry has no uri that is a string")

    def refuse(check: Check, reason: str) -> SkillRefused:
        return SkillRefused(check, reason, uri)

    frontmatter = raw.get("frontmatter")
    if not isinstance(frontmatter, dict):
        raise refuse("entry", "the entry has no frontmatter that is an object")
    name, description = frontmatter.get("name"), frontmatter.get("description")
    if not isinstance(name, str):
        raise refuse("entry", "the frontmatter has no name that is a string")
    if not isinstance(description, str):
        raise refuse("entry", "the frontmatter has no description that is a string")
    if last_segments(uri, 2) != (name, SKILL_FILE):
        raise refuse("entry", "the uri is not skill://<path>/<name>/SKILL.md for the name of the frontmatter")

    listed = raw.get("resources", _MISSING)
    if listed is _MISSING:
        raise refuse("resources", "the entry does not list its files")
    if listed == "dynamic":
        raise refuse("resources", "the entry says its files are dynamic, so there is nothing to verify them against")
    if not isinstance(listed, list):
        raise refuse("resources", "the files of the entry are not an array")
    if len(listed) > MAX_FILES:
        raise refuse("limit", f"the entry lists more than {MAX_FILES} files")

    files: list[SkillFileRef] = []
    seen: set[str] = set()
    total = 0
    for resource in listed:
        if not isinstance(resource, dict):
            raise refuse("resources", "a listed file is not an object")
        file_uri, digest, size = resource.get("uri"), resource.get("digest"), resource.get("size")
        if not isinstance(file_uri, str):
            raise refuse("resources", "a listed file has no uri that is a string")
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise refuse("resources", "a listed file has no digest of the form sha256:<64 lowercase hex>")
        if type(size) is not int or size < 0:  # a boolean is not a size, and nor is 1.5
            raise refuse("resources", "a listed file has no size that is a whole number of bytes")
        if file_uri in seen:
            raise refuse("resources", "the entry lists one file twice")
        seen.add(file_uri)
        total += size
        files.append(SkillFileRef(file_uri, size, digest))
    if uri not in seen:
        raise refuse("resources", "the entry does not list its own SKILL.md")
    if total > MAX_BYTES:
        raise refuse("limit", f"the files of the entry hold more than {MAX_BYTES} bytes")
    return SkillItem(origin, uri, name, description, frontmatter, tuple(files))


# --- Bytes: bound, decode, then compare -------------------------------------------------------------


def _bytes_of(content: types.TextResourceContents | types.BlobResourceContents, ref: SkillFileRef) -> bytes:
    """The raw bytes of one content, after a bound taken from the entry and before any decoding: a
    server cannot make the caller allocate more than the entry said the file holds."""
    if isinstance(content, types.TextResourceContents):
        if len(content.text) > ref.size:  # a character is at least one byte
            raise SkillRefused("size", "the text is longer than the size of the entry", ref.uri)
        try:
            return content.text.encode("utf-8")
        except UnicodeEncodeError:
            raise SkillRefused("response", "the text is not valid Unicode", ref.uri) from None
    if len(content.blob) > 4 * ((ref.size + 2) // 3):  # the base64 of `size` bytes, padding included
        raise SkillRefused("size", "the blob is longer than the base64 of the size of the entry", ref.uri)
    try:
        return base64.b64decode(content.blob, validate=True)
    except ValueError:  # binascii.Error is one
        raise SkillRefused("response", "the blob is not valid base64", ref.uri) from None


def _same(a: object, b: object) -> bool:
    """Equal as JSON values: a boolean is not a number, `2` is `2.0`, a list is ordered."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b  # `True == 1` in Python, and it must not be here
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(_same(a[key], b[key]) for key in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b  # numbers (`2 == 2.0`), strings and null


def _check_frontmatter(item: SkillItem, data: bytes) -> None:
    """The frontmatter read from the bytes of `SKILL.md` must be the entry's, field by field."""
    try:
        actual = read_frontmatter(data)
    except FrontmatterError as error:
        raise SkillRefused("frontmatter", f"the frontmatter of SKILL.md cannot be read ({error.reason})", item.uri) from None
    if item.frontmatter.keys() - actual.keys():
        raise SkillRefused("frontmatter", "the entry has a frontmatter field that SKILL.md does not have", item.uri)
    if actual.keys() - item.frontmatter.keys():
        raise SkillRefused("frontmatter", "SKILL.md has a frontmatter field that the entry does not have", item.uri)
    if not _same(actual, item.frontmatter):
        raise SkillRefused("frontmatter", "a frontmatter value of SKILL.md differs from the entry's", item.uri)


# --- The client -------------------------------------------------------------------------------------

_Result = TypeVar("_Result", RawListSkillsResult, RawGetSkillResult)


class SkillsClient:
    """The skills of one server, read with verification. `origin` is the caller's label for that
    server (non-empty): it tags every item and every content, and with a URI it is a skill's identity.
    Two clients share nothing."""

    def __init__(self, client: Client, *, origin: str) -> None:
        if not isinstance(origin, str) or not origin:
            raise ValueError("origin must be a non-empty string: it labels the server this client reads")
        self._client = client
        self._origin = origin

    # --- What the server declared

    def _declaration(self) -> dict[str, Any] | None:
        """The settings the server declared for the extension, or `None` if it did not declare it or
        did not declare the `resources` capability (its files are ordinary resources)."""
        capabilities = self._client.server_capabilities
        settings = (capabilities.extensions or {}).get(EXTENSION_ID)
        return settings if capabilities.resources is not None and isinstance(settings, dict) else None

    @property
    def declared(self) -> bool:
        return self._declaration() is not None

    @property
    def directory_read(self) -> bool:
        """The server declared `directoryRead: true`. Only the value `true` counts."""
        settings = self._declaration()
        return settings is not None and settings.get("directoryRead") is True

    def _require_declared(self) -> None:
        if self._declaration() is None:
            raise SkillRefused("declaration", "the server did not declare the skills extension with the resources capability")

    # --- One request, one answer

    async def _ask(self, request: Any, result_type: type[_Result]) -> _Result:
        try:
            return await self._client.session.send_request(request, result_type)
        except ValidationError:
            raise SkillRefused("response", "the answer of the server is not a skills answer") from None

    # --- Listing

    async def list(self) -> SkillListing:
        """Every skill the server lists, page after page, and no file read. An entry that does not
        validate is returned in `refused`; the others still come."""
        self._require_declared()
        skills: list[SkillItem] = []
        refused: list[Refused] = []
        cursor: str | None = None
        while True:
            request = ListSkillsRequest(params=types.PaginatedRequestParams(cursor=cursor)) if cursor is not None else ListSkillsRequest()
            page = await self._ask(request, RawListSkillsResult)
            for raw in page.skills:
                try:
                    skills.append(parse_entry(self._origin, raw))
                except SkillRefused as refusal:
                    refused.append(Refused(refusal.uri, refusal.check, refusal.reason))
            cursor = page.next_cursor
            if cursor is None:
                return SkillListing(tuple(skills), tuple(refused))

    async def get(self, uri: str) -> SkillItem:
        """The entry of one skill. A server's own error (an unknown URI is `-32602`) is raised as the
        SDK raises it; an entry that does not validate, or that is for another skill, is a refusal."""
        self._require_declared()
        answer = await self._ask(GetSkillRequest(params=GetSkillParams(uri=uri)), RawGetSkillResult)
        item = parse_entry(self._origin, answer.skill)
        if item.uri != uri:
            raise SkillRefused("response", "the server answered with the entry of another skill", uri)
        return item

    # --- Reading

    async def load(self, item: SkillItem) -> LoadedSkill:
        """Read and verify the `SKILL.md` of a skill, and nothing else of it."""
        return LoadedSkill(item, await self.read(item, item.uri))

    async def read(self, item: SkillItem, uri: str) -> SkillContent:
        """Read one file the entry lists and verify it. Nothing is returned for a file that fails."""
        self._require_declared()
        ref = next((file for file in item.files if file.uri == uri), None)
        if ref is None:
            raise SkillRefused("unlisted", "the file is not one the entry lists", uri)
        try:
            # Bypass the SDK's cache: an answer it kept would skip the server and, with it, the checks.
            result = await self._client.read_resource(ref.uri, cache_mode="bypass")
        except ValidationError:
            raise SkillRefused("response", "the answer of the server is not a resource answer", ref.uri) from None
        if len(result.contents) != 1 or result.contents[0].uri != ref.uri:
            raise SkillRefused("response", "the answer is not exactly one content for the file asked for", ref.uri)
        data = _bytes_of(result.contents[0], ref)
        if len(data) != ref.size:
            raise SkillRefused("size", "the number of bytes differs from the size of the entry", ref.uri)
        if "sha256:" + hashlib.sha256(data).hexdigest() != ref.digest:
            raise SkillRefused("digest", "the SHA-256 differs from the digest of the entry", ref.uri)
        if ref.uri == item.uri:
            _check_frontmatter(item, data)
        return SkillContent(self._origin, ref.uri, data)
