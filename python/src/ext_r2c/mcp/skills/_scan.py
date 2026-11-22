"""Folders in, a `Catalogue` out (spec 005, research R6).

Each root is resolved once per scan. The walk goes through the folders in sorted order without
following a link; a folder that holds a regular `SKILL.md` is a skill (the nearest one on a path
wins), and what is below it is its files, not more skills. The filters are matched against the skill
folder's name before anything of the skill is read, so a skill they leave out is never parsed and may
be broken in any way.

A skill that is served is checked whole: `SKILL.md` is read and its frontmatter must be plain data
with a `name` that is allowed and is the folder's name and a `description`; the walk then lists the
files with their `stat` sizes and refuses the skill at the first file past 512 files or 16 MiB, so
nothing but `SKILL.md` has been read when it does; only then is every file read, each read bounded by
what is left of the 16 MiB, and hashed.

Hidden entries, symbolic links, anything that is not a regular file and names that are not text are
never served, and each is reported as a `LeftOut` with its path below the root and its reason.

Every problem with the folders is a `SkillsError(folder, reason)`. The reason names what is wrong and
never quotes a file's text or the host path of anything above the folder it names; an `OSError`
becomes the system's own words for it ("Permission denied").
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import stat
from collections.abc import Iterator, Sequence
from typing import Any, NamedTuple

from ._catalogue import Catalogue, FileRecord, LeftOut, SkillRecord, SkillsError
from ._content import mime_for
from ._frontmatter import FrontmatterError, read_frontmatter
from ._limits import MAX_BYTES, MAX_FILES
from ._read import read_bytes
from ._uris import SKILL_FILE, encode_uri

_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_NAME_LENGTH = 64
_DESCRIPTION_LENGTH = 1024


class _Root(NamedTuple):
    """A folder the owner gave: as given (and made absolute), and with every link resolved."""

    given: str
    real: str

    def named(self, below: tuple[str, ...]) -> str:
        """The folder `below` this root, as an error names it: the root as given, anything under it by
        the path the scan reads."""
        return os.path.join(self.real, *below) if below else self.given


class _Found(NamedTuple):
    """A skill folder: its path in the URI, and where it is below the root (empty for the root)."""

    path: tuple[str, ...]
    below: tuple[str, ...]


def scan_roots(
    folders: Sequence[str | os.PathLike[str]], include: Sequence[str] = (), exclude: Sequence[str] = ()
) -> Catalogue:
    """The catalogue of every skill found under `folders` that the filters let through. A problem with
    any folder, or with any skill that is let through, is a `SkillsError`: nothing is half built."""
    skills: list[SkillRecord] = []
    left_out: list[LeftOut] = []
    found_any = False
    for folder in folders:
        root = _Root(os.fspath(folder), os.path.realpath(folder))
        _check_root(root)
        for found in _search(root, (), left_out):
            found_any = True
            if _allowed(found.path[-1], include, exclude):
                skills.append(_describe(root, found, left_out))
    if not skills:
        where = ", ".join(os.fspath(folder) for folder in folders)
        if not found_any:
            raise SkillsError(where, "no skill found: a skill is a folder that holds a SKILL.md")
        raise SkillsError(where, f"the filters leave no skill to serve (include {list(include)}, exclude {list(exclude)})")
    return Catalogue.build(skills, sorted(left_out, key=lambda item: (item.path, item.reason)))


def _why(error: OSError) -> str:
    """The system's words for `error`, which never hold the path it was about."""
    return error.strerror or type(error).__name__


def _cannot_read(parts: Sequence[str], error: OSError) -> str:
    name = _shown(tuple(parts))
    return f"{name} cannot be read: {_why(error)}" if name else f"cannot be read: {_why(error)}"


def _check_root(root: _Root) -> None:
    try:
        mode = os.stat(root.given).st_mode
    except (FileNotFoundError, NotADirectoryError):
        raise SkillsError(root.given, "does not exist") from None
    except OSError as error:
        raise SkillsError(root.given, f"cannot be read: {_why(error)}") from None
    if not stat.S_ISDIR(mode):
        raise SkillsError(root.given, "is not a directory")


def _allowed(name: str, include: Sequence[str], exclude: Sequence[str]) -> bool:
    """`name` is let through when it matches an `include` (or there is none) and no `exclude`."""
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in exclude):
        return False
    return not include or any(fnmatch.fnmatchcase(name, pattern) for pattern in include)


def _reason(entry: os.DirEntry[str]) -> str | None:
    """Why a scan does not serve `entry`, or `None` when it may be served (a folder or a regular
    file). A link comes first, so one with a hidden name is still reported as a link."""
    if entry.is_symlink():
        return "symbolic link"
    if entry.name.startswith("."):
        return "hidden"
    try:
        entry.name.encode("utf-8")
    except UnicodeEncodeError:  # a name that is not text has no URI
        return "undecodable name"
    if not (entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False)):
        return "not a regular file"
    return None


def _shown(path: tuple[str, ...]) -> str:
    """A path below the root for a report: `/` between names, and a byte that is not text as `\\xNN`,
    so the line can be printed."""
    return "/".join(path).encode("utf-8", "surrogateescape").decode("utf-8", "backslashreplace")


def _entries(folder: str, shown: tuple[str, ...], left_out: list[LeftOut]) -> list[os.DirEntry[str]]:
    """What the folder at `shown` (its path below the root) holds, by name, without the entries a
    scan never serves; each of those is added to `left_out`. An `OSError` is the caller's to name."""
    kept: list[os.DirEntry[str]] = []
    with os.scandir(folder) as found:
        for entry in sorted(found, key=lambda entry: entry.name):
            reason = _reason(entry)
            if reason is None:
                kept.append(entry)
            else:
                left_out.append(LeftOut(_shown((*shown, entry.name)), reason))
    return kept


def _search(root: _Root, below: tuple[str, ...], left_out: list[LeftOut]) -> Iterator[_Found]:
    """Every skill folder at or under `below`, in order. A folder with a `SKILL.md` is one and is
    not searched further (`_files` reports what it leaves out); a root that is one is named by its
    own folder name."""
    skipped: list[LeftOut] = []
    try:
        entries = _entries(os.path.join(root.real, *below), below, skipped)
    except OSError as error:
        raise SkillsError(root.named(below), f"cannot be read: {_why(error)}") from None
    if any(entry.name == SKILL_FILE and entry.is_file(follow_symlinks=False) for entry in entries):
        yield _Found(below or (os.path.basename(root.real),), below)
        return
    left_out.extend(skipped)
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from _search(root, (*below, entry.name), left_out)


def _files(
    folder: str, shown: tuple[str, ...], left_out: list[LeftOut], below: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], int]]:
    """Every regular file under `folder`, depth first and by name, as its path from `folder` down and
    its size now. `shown` is where `folder` is below the root, for the report. Lazy, so a caller that
    has seen enough stops the walk."""
    try:
        entries = _entries(os.path.join(folder, *below), (*shown, *below), left_out)
    except OSError as error:
        raise SkillsError(folder, _cannot_read(below, error)) from None
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from _files(folder, shown, left_out, (*below, entry.name))
        elif entry.is_file(follow_symlinks=False):
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError as error:
                raise SkillsError(folder, _cannot_read((*below, entry.name), error)) from None
            yield (*below, entry.name), size


def _read(folder: str, parts: tuple[str, ...], limit: int) -> bytes:
    """At most `limit` bytes of the file; one that cannot be read is a `SkillsError`."""
    try:
        return read_bytes(folder, parts, limit)
    except OSError as error:
        raise SkillsError(folder, _cannot_read(parts, error)) from None


def _text_field(frontmatter: dict[str, Any], field: str, folder: str) -> str:
    if field not in frontmatter:
        raise SkillsError(folder, f"frontmatter has no {field}")
    value = frontmatter[field]
    if not isinstance(value, str):
        raise SkillsError(folder, f"frontmatter {field} is not a string")
    return value


def _check_fields(frontmatter: dict[str, Any], folder: str, folder_name: str) -> str:
    """The skill's name, once the name and the description are known to be allowed. The reason never
    quotes the value: it is file text."""
    name = _text_field(frontmatter, "name", folder)
    if len(name) > _NAME_LENGTH or not _NAME.fullmatch(name):
        raise SkillsError(
            folder, f"name must be 1 to {_NAME_LENGTH} lower-case letters, digits and single hyphens, such as my-skill"
        )
    if name != folder_name:
        raise SkillsError(folder, "name must be the same as the name of the folder")
    description = _text_field(frontmatter, "description", folder)
    if not 1 <= len(description) <= _DESCRIPTION_LENGTH:
        raise SkillsError(folder, f"description must be 1 to {_DESCRIPTION_LENGTH} characters")
    return name


def _too_many_bytes(folder: str) -> SkillsError:
    return SkillsError(folder, f"holds more than {MAX_BYTES} bytes, the most a skill may serve")


def _listing(folder: str, shown: tuple[str, ...], left_out: list[LeftOut]) -> list[tuple[tuple[str, ...], int]]:
    """The files of the skill with their sizes, or a `SkillsError` at the first one that is past a
    limit. Only `stat` has been asked of the rest, and the walk stops there."""
    listed: list[tuple[tuple[str, ...], int]] = []
    total = 0
    for parts, size in _files(folder, shown, left_out):
        if len(listed) == MAX_FILES:
            raise SkillsError(folder, f"has more than {MAX_FILES} files, the most a skill may serve")
        total += size
        if total > MAX_BYTES:
            raise _too_many_bytes(folder)
        listed.append((parts, size))
    return listed


def _describe(root: _Root, found: _Found, left_out: list[LeftOut]) -> SkillRecord:
    """The record of one skill: its frontmatter, and every file with its size and digest."""
    folder = os.path.join(root.real, *found.below)
    uri = encode_uri(found.path, file=SKILL_FILE)
    skill_md = _read(folder, (SKILL_FILE,), MAX_BYTES + 1)
    if len(skill_md) > MAX_BYTES:
        raise _too_many_bytes(folder)
    try:
        frontmatter = read_frontmatter(skill_md)
    except FrontmatterError as error:
        raise SkillsError(folder, f"SKILL.md frontmatter: {error.reason}") from None
    name = _check_fields(frontmatter, folder, found.path[-1])
    listed = _listing(folder, found.below, left_out)
    files = []
    used = len(skill_md)  # the bytes read so far, so that a file that grew cannot go past the limit unseen
    for parts, _ in listed:
        if parts == (SKILL_FILE,):
            data = skill_md
        else:
            room = MAX_BYTES - used
            data = _read(folder, parts, room + 1)
            if len(data) > room:
                raise _too_many_bytes(folder)
            used += len(data)
        files.append(
            FileRecord(
                uri=encode_uri(found.path, file=parts),
                parts=parts,
                folder=folder,
                size=len(data),
                digest="sha256:" + hashlib.sha256(data).hexdigest(),
                mime=mime_for(parts[-1]),
                skill=uri,
            )
        )
    return SkillRecord(name=name, path=found.path, uri=uri, folder=folder, frontmatter=frontmatter, files=tuple(files))
