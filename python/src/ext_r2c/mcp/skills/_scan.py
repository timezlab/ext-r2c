"""Folders in, a `Catalogue` out (spec 005, research R6).

Each root is resolved once. The walk goes through the folders in sorted order without following a
link; a folder that holds a regular `SKILL.md` is a skill (the nearest one on a path wins), and what
is below it is its files, not more skills. The filters are matched against the skill folder's name
before anything of the skill is read, so a skill they leave out is never parsed.

Hidden entries, symbolic links, anything that is not a regular file and names that are not text are
never served, and each is reported as a `LeftOut` with its path below the root and its reason. A
skill's own entries are reported once, and so are those of a folder that holds no skill. A root that
cannot be read raises the `OSError` as it is; phase 6 adds the full list of build errors.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Iterator, Sequence
from typing import Any, NamedTuple

from ._catalogue import Catalogue, FileRecord, LeftOut, SkillRecord, SkillsError
from ._content import mime_for
from ._frontmatter import FrontmatterError, read_frontmatter
from ._read import read_bytes
from ._uris import SKILL_FILE, encode_uri


class _Found(NamedTuple):
    """A skill folder: its path in the URI, and where it is below the root (empty for the root)."""

    path: tuple[str, ...]
    below: tuple[str, ...]


def scan_roots(
    folders: Sequence[str | os.PathLike[str]], include: Sequence[str] = (), exclude: Sequence[str] = ()
) -> Catalogue:
    """The catalogue of every skill found under `folders` that the filters let through."""
    skills: list[SkillRecord] = []
    left_out: list[LeftOut] = []
    for folder in folders:
        root = os.path.realpath(folder)
        skills.extend(
            _describe(root, found, left_out)
            for found in _search(root, (), left_out)
            if _allowed(found.path[-1], include, exclude)
        )
    return Catalogue.build(skills, sorted(left_out, key=lambda item: (item.path, item.reason)))


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
    scan never serves; each of those is added to `left_out`."""
    kept: list[os.DirEntry[str]] = []
    with os.scandir(folder) as found:
        for entry in sorted(found, key=lambda entry: entry.name):
            reason = _reason(entry)
            if reason is None:
                kept.append(entry)
            else:
                left_out.append(LeftOut(_shown((*shown, entry.name)), reason))
    return kept


def _search(root: str, below: tuple[str, ...], left_out: list[LeftOut]) -> Iterator[_Found]:
    """Every skill folder at or under `below`, in order. A folder with a `SKILL.md` is one and is
    not searched further (`_files` reports what it leaves out); a root that is one is named by its
    own folder name."""
    skipped: list[LeftOut] = []
    entries = _entries(os.path.join(root, *below), below, skipped)
    if any(entry.name == SKILL_FILE and entry.is_file(follow_symlinks=False) for entry in entries):
        yield _Found(below or (os.path.basename(root),), below)
        return
    left_out.extend(skipped)
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from _search(root, (*below, entry.name), left_out)


def _files(
    folder: str, shown: tuple[str, ...], left_out: list[LeftOut], below: tuple[str, ...] = ()
) -> Iterator[tuple[str, ...]]:
    """The path, from `folder` down, of every regular file under it: depth first, by name. `shown` is
    where `folder` is below the root, for the report."""
    for entry in _entries(os.path.join(folder, *below), (*shown, *below), left_out):
        if entry.is_dir(follow_symlinks=False):
            yield from _files(folder, shown, left_out, (*below, entry.name))
        elif entry.is_file(follow_symlinks=False):
            yield (*below, entry.name)


def _text_field(frontmatter: dict[str, Any], field: str, folder: str) -> str:
    if field not in frontmatter:
        raise SkillsError(folder, f"frontmatter has no {field}")
    value = frontmatter[field]
    if not isinstance(value, str):
        raise SkillsError(folder, f"frontmatter {field} is not a string")
    return value


def _describe(root: str, found: _Found, left_out: list[LeftOut]) -> SkillRecord:
    """The record of one skill: its frontmatter, and every file with its size and digest."""
    folder = os.path.join(root, *found.below)
    uri = encode_uri(found.path, file=SKILL_FILE)
    skill_md = read_bytes(folder, (SKILL_FILE,))
    try:
        frontmatter = read_frontmatter(skill_md)
    except FrontmatterError as error:
        raise SkillsError(folder, f"SKILL.md frontmatter: {error.reason}") from None
    name = _text_field(frontmatter, "name", folder)
    _text_field(frontmatter, "description", folder)
    files = []
    for parts in _files(folder, found.below, left_out):
        data = skill_md if parts == (SKILL_FILE,) else read_bytes(folder, parts)
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
