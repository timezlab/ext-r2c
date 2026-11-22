"""Folders in, a `Catalogue` out (spec 005, research R6).

Each root is resolved once. The walk goes through the folders in sorted order without following a
link; a folder that holds a regular `SKILL.md` is a skill (the nearest one on a path wins), and what
is below it is its files, not more skills. The filters are matched against the skill folder's name
before anything of the skill is read, so a skill they leave out is never parsed.

First cut (phase 3): hidden entries, links and anything that is not a regular file are left out
without a report, and a root that cannot be read raises the `OSError` as it is; phases 5 and 6 add
the report and the full list of build errors.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Iterator, Sequence
from typing import Any, NamedTuple

from ._catalogue import Catalogue, FileRecord, SkillRecord, SkillsError
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
    for folder in folders:
        root = os.path.realpath(folder)
        skills.extend(_describe(root, found) for found in _search(root, ()) if _allowed(found.path[-1], include, exclude))
    return Catalogue.build(skills)


def _allowed(name: str, include: Sequence[str], exclude: Sequence[str]) -> bool:
    """`name` is let through when it matches an `include` (or there is none) and no `exclude`."""
    if any(fnmatch.fnmatchcase(name, pattern) for pattern in exclude):
        return False
    return not include or any(fnmatch.fnmatchcase(name, pattern) for pattern in include)


def _entries(folder: str) -> list[os.DirEntry[str]]:
    """What a folder holds, by name, without the entries a scan never serves."""
    with os.scandir(folder) as found:
        return sorted(
            (entry for entry in found if not entry.name.startswith(".") and not entry.is_symlink()),
            key=lambda entry: entry.name,
        )


def _search(root: str, below: tuple[str, ...]) -> Iterator[_Found]:
    """Every skill folder at or under `below`, in order. A folder with a `SKILL.md` is one and is
    not searched further; a root that is one is named by its own folder name."""
    entries = _entries(os.path.join(root, *below))
    if any(entry.name == SKILL_FILE and entry.is_file(follow_symlinks=False) for entry in entries):
        yield _Found(below or (os.path.basename(root),), below)
        return
    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from _search(root, (*below, entry.name))


def _files(folder: str, below: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """The path, from `folder` down, of every regular file under it: depth first, by name."""
    for entry in _entries(os.path.join(folder, *below)):
        if entry.is_dir(follow_symlinks=False):
            yield from _files(folder, (*below, entry.name))
        elif entry.is_file(follow_symlinks=False):
            yield (*below, entry.name)


def _text_field(frontmatter: dict[str, Any], field: str, folder: str) -> str:
    if field not in frontmatter:
        raise SkillsError(folder, f"frontmatter has no {field}")
    value = frontmatter[field]
    if not isinstance(value, str):
        raise SkillsError(folder, f"frontmatter {field} is not a string")
    return value


def _describe(root: str, found: _Found) -> SkillRecord:
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
    for parts in _files(folder):
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
