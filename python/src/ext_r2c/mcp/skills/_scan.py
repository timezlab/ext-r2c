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

Hidden entries, symbolic links, anything that is not a regular file, names that are not text and names
that are not safe to print (a control character, a line or paragraph separator, a bidirectional
control or a backslash) are never served, and each is reported as a `LeftOut` with its path below the
root and its reason. The path is shown with such a character escaped, so a name cannot break or
reorder the line it is printed in.

A scan is bounded whatever the tree: a folder is searched no more than 32 folders below its root, a
skill holds no folder more than 32 below its own, a skill holds at most 1024 folders, and a root
searches at most 1024 folders that are not skills (the root counts; a skill does not, and the number
of skills is not limited). Past a bound it is a `SkillsError` before the folder is read.

Every problem with the folders is a `SkillsError(folder, reason)`. The reason names what is wrong and
never quotes a file's text or the host path of anything above the folder it names; an `OSError`
becomes the system's own words for it ("Permission denied").
"""

from __future__ import annotations

import fnmatch
import hashlib
import itertools
import os
import stat
from collections.abc import Iterator, Sequence
from typing import Any, NamedTuple

from ._catalogue import Catalogue, FileRecord, LeftOut, SkillRecord, SkillsError
from ._content import mime_for
from ._frontmatter import FrontmatterError, read_frontmatter
from ._limits import (
    MAX_BYTES,
    MAX_DEPTH,
    MAX_DESCRIPTION_LENGTH,
    MAX_DIRECTORIES,
    MAX_FILES,
    MAX_NAME_LENGTH,
)
from ._read import read_bytes
from ._uris import SKILL_FILE, char_unsafe, encode_uri, name_unsafe, skill_name_ok


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
        for found in _search(root, (), left_out, itertools.count(1)):
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
    if name_unsafe(entry.name):  # a control character, a line break, a bidi control or a backslash
        return "unsafe name"
    if not (entry.is_dir(follow_symlinks=False) or entry.is_file(follow_symlinks=False)):
        return "not a regular file"
    return None


def _escape(char: str) -> str:
    """An unsafe character as `\\xNN` (up to U+00FF) or `\\uNNNN`. None is above U+FFFF, so there is no
    `\\UNNNNNNNN`."""
    code = ord(char)
    return f"\\x{code:02x}" if code <= 0xFF else f"\\u{code:04x}"


def _shown(path: tuple[str, ...]) -> str:
    """A path below the root for a report: `/` between names, a byte that is not text as `\\xNN`, and an
    unsafe character as `\\xNN`, `\\uNNNN` or `\\UNNNNNNNN`, so that the line can be printed and a name
    cannot break it or reorder it."""
    shown = []
    for char in "/".join(path):
        code = ord(char)
        if 0xDC80 <= code <= 0xDCFF:  # a byte that is not text, as the file system gave it
            shown.append(f"\\x{code - 0xDC00:02x}")
        elif char_unsafe(char):
            shown.append(_escape(char))
        else:
            shown.append(char)
    return "".join(shown)


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


def _search(
    root: _Root, below: tuple[str, ...], left_out: list[LeftOut], searched: Iterator[int]
) -> Iterator[_Found]:
    """Every skill folder at or under `below`, in order. A folder with a `SKILL.md` is one and is
    not searched further (`_files` reports what it leaves out); a root that is one is named by its
    own folder name. At most `MAX_DEPTH` folders deep, and at most `MAX_DIRECTORIES` folders that are
    not skills (`searched` counts them from 1, one count for the root), or it is a `SkillsError`: a
    root that is a whole disk cannot make the scan walk it."""
    if len(below) > MAX_DEPTH:
        raise SkillsError(root.named(below), f"is more than {MAX_DEPTH} folders deep, the most a scan searches")
    skipped: list[LeftOut] = []
    try:
        entries = _entries(os.path.join(root.real, *below), below, skipped)
    except OSError as error:
        raise SkillsError(root.named(below), f"cannot be read: {_why(error)}") from None
    if any(entry.name == SKILL_FILE and entry.is_file(follow_symlinks=False) for entry in entries):
        yield _Found(below or (os.path.basename(root.real),), below)
        return
    if next(searched) > MAX_DIRECTORIES:
        raise SkillsError(root.named(below), f"is past {MAX_DIRECTORIES} folders that are not skills, the most a scan searches")
    left_out.extend(skipped)
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from _search(root, (*below, entry.name), left_out, searched)


def _files(
    folder: str,
    shown: tuple[str, ...],
    left_out: list[LeftOut],
    dirs: list[tuple[str, ...]],
    below: tuple[str, ...] = (),
) -> Iterator[tuple[tuple[str, ...], int]]:
    """Every regular file under `folder`, depth first and by name, as its path from `folder` down and
    its size now. `shown` is where `folder` is below the root, for the report. Every folder the walk
    enters is added to `dirs` (an empty one too) before what is in it, so `dirs` is in pre-order. Lazy,
    so a caller that has seen enough stops the walk. A folder more than `MAX_DEPTH` deep, or one past
    `MAX_DIRECTORIES` folders, is a `SkillsError` before it is read."""
    if len(below) > MAX_DEPTH:
        raise SkillsError(folder, f"holds a folder more than {MAX_DEPTH} folders deep, the most a skill may hold")
    try:
        entries = _entries(os.path.join(folder, *below), (*shown, *below), left_out)
    except OSError as error:
        raise SkillsError(folder, _cannot_read(below, error)) from None
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            if len(dirs) == MAX_DIRECTORIES:
                raise SkillsError(folder, f"has more than {MAX_DIRECTORIES} folders, the most a skill may hold")
            dirs.append((*below, entry.name))
            yield from _files(folder, shown, left_out, dirs, (*below, entry.name))
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
    if not skill_name_ok(name):
        raise SkillsError(
            folder, f"name must be 1 to {MAX_NAME_LENGTH} lower-case letters, digits and single hyphens, such as my-skill"
        )
    if name != folder_name:
        raise SkillsError(folder, "name must be the same as the name of the folder")
    description = _text_field(frontmatter, "description", folder)
    if not 1 <= len(description) <= MAX_DESCRIPTION_LENGTH:
        raise SkillsError(folder, f"description must be 1 to {MAX_DESCRIPTION_LENGTH} characters")
    return name


def _too_many_bytes(folder: str) -> SkillsError:
    return SkillsError(folder, f"holds more than {MAX_BYTES} bytes, the most a skill may serve")


def _listing(
    folder: str, shown: tuple[str, ...], left_out: list[LeftOut]
) -> tuple[list[tuple[tuple[str, ...], int]], list[tuple[str, ...]]]:
    """The files of the skill with their sizes, and its folders, or a `SkillsError` at the first file
    that is past a limit. Only `stat` has been asked of the rest, and the walk stops there."""
    listed: list[tuple[tuple[str, ...], int]] = []
    dirs: list[tuple[str, ...]] = []
    total = 0
    for parts, size in _files(folder, shown, left_out, dirs):
        if len(listed) == MAX_FILES:
            raise SkillsError(folder, f"has more than {MAX_FILES} files, the most a skill may serve")
        total += size
        if total > MAX_BYTES:
            raise _too_many_bytes(folder)
        listed.append((parts, size))
    return listed, dirs


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
    listed, dirs = _listing(folder, found.below, left_out)
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
    return SkillRecord(
        name=name,
        path=found.path,
        uri=uri,
        folder=folder,
        frontmatter=frontmatter,
        files=tuple(files),
        dirs=tuple(dirs),
    )
