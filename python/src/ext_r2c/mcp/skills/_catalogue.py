"""What a scan found, as immutable records, and the catalogue built from them (spec 005,
`data-model.md`).

A `Catalogue` is made once from the records of a scan and never changed. A refresh builds another
one and swaps it in whole (R5), so a request sees one catalogue from its first line to its last.
Every URI the server answers for is a key of one of its dictionaries; a request URI that is not a
key is not served, and no path is ever built from it.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, NamedTuple

from ._content import DIRECTORY
from ._uris import SCHEME, encode_uri

_PREFIX = f"{SCHEME}://"


class SkillsError(ValueError):
    """The skills cannot be served. `folder` is the folder the owner gave, or the skill folder
    that is at fault; `reason` says what is wrong without quoting any file's text."""

    def __init__(self, folder: str, reason: str) -> None:
        super().__init__(f"{folder}: {reason}")
        self.folder = folder
        self.reason = reason

    def __reduce__(self) -> tuple[type[SkillsError], tuple[str, str]]:
        return (type(self), (self.folder, self.reason))


@dataclass(frozen=True)
class LeftOut:
    """Something a scan did not serve: its path under the folder, and why (hidden, a symbolic link,
    not a regular file, a name that is not text)."""

    path: str
    reason: str


@dataclass(frozen=True)
class SkillInfo:
    """What the owner sees of one served skill (`skills()` on the extension)."""

    name: str
    uri: str
    description: str
    files: int
    size: int


@dataclass(frozen=True)
class FileRecord:
    """One served file. `parts` are its names from the skill folder down; `folder` is where the skill
    is on disk, kept for the safe read; `skill` is the URI of the `SKILL.md` it belongs to."""

    uri: str
    parts: tuple[str, ...]
    folder: str
    size: int
    digest: str
    mime: str
    skill: str


@dataclass(frozen=True)
class SkillRecord:
    """One served skill: its `SKILL.md` URI, its frontmatter as the reader returned it, its files, and
    every folder below it that a scan found (`dirs`, each a tuple of names from the skill folder
    down, empty ones too). Hidden and linked folders are not found, so they are not in it."""

    name: str
    path: tuple[str, ...]
    uri: str
    folder: str
    frontmatter: dict[str, Any]
    files: tuple[FileRecord, ...]
    dirs: tuple[tuple[str, ...], ...] = ()


class Child(NamedTuple):
    """A direct child of a directory: a file or a folder."""

    uri: str
    name: str
    mime: str
    is_dir: bool


@dataclass(frozen=True)
class DirectoryRecord:
    """A directory of a skill and its direct children, sorted by name."""

    uri: str
    children: tuple[Child, ...]


@dataclass(frozen=True)
class Catalogue:
    """All the skills of one scan. `by_uri` is keyed by a skill's `SKILL.md` URI, `files` by every
    served file's URI, `directories` by every directory's URI (no trailing slash). `generation`
    names this build: a page cursor is good only for the catalogue it came from."""

    generation: str
    skills: tuple[SkillRecord, ...]
    by_uri: Mapping[str, SkillRecord]
    files: Mapping[str, FileRecord]
    directories: Mapping[str, DirectoryRecord]
    left_out: tuple[LeftOut, ...]

    @classmethod
    def build(cls, skills: Iterable[SkillRecord], left_out: Iterable[LeftOut] = ()) -> Catalogue:
        """The catalogue of `skills`: sorted by URI, each skill's files sorted by their path under
        it, one directory record for every directory that holds a file. A skill, a file and a
        directory cannot share a URI (the first segment is compared in lower case, as a host is);
        if two do, it is a `SkillsError`."""
        ordered = tuple(sorted((_with_sorted_files(skill) for skill in skills), key=lambda skill: skill.uri))
        claimed: dict[str, tuple[str, str]] = {}  # folded URI -> ("file" or "directory", the skill's folder)
        files: dict[str, FileRecord] = {}
        directories: dict[str, DirectoryRecord] = {}
        for skill in ordered:
            for record in skill.files:
                _claim(claimed, record.uri, "file", skill.folder)
                files[record.uri] = record
            for directory in _directories_of(skill):
                _claim(claimed, directory.uri, "directory", skill.folder)
                directories[directory.uri] = directory
        return cls(
            generation=secrets.token_hex(8),
            skills=ordered,
            by_uri=MappingProxyType({skill.uri: skill for skill in ordered}),
            files=MappingProxyType(files),
            directories=MappingProxyType(directories),
            left_out=tuple(left_out),
        )


def _with_sorted_files(skill: SkillRecord) -> SkillRecord:
    return replace(
        skill,
        files=tuple(sorted(skill.files, key=lambda record: "/".join(record.parts))),
        dirs=tuple(sorted(set(skill.dirs))),
    )


def _fold(uri: str) -> str:
    """The URI with the ASCII letters of its first segment lowered (the authority, R3)."""
    authority, slash, rest = uri.removeprefix(_PREFIX).partition("/")
    return f"{_PREFIX}{authority.lower()}{slash}{rest}"


def _claim(claimed: dict[str, tuple[str, str]], uri: str, kind: str, folder: str) -> None:
    """Note that `uri` is taken by a `kind` ("file" or "directory") of the skill in `folder`; a second
    claim is an error that names both folders."""
    key = _fold(uri)
    earlier = claimed.get(key)
    if earlier is None:
        claimed[key] = (kind, folder)
        return
    what = "served twice" if earlier[0] == kind else "both a file and a directory"
    raise SkillsError(folder, f"{uri} is {what}; it is also in {earlier[1]}")


def _directories_of(skill: SkillRecord) -> Iterator[DirectoryRecord]:
    """One record for the skill folder, one for every folder that holds a file and one for every
    folder in `skill.dirs`, each with the folders above it: a child always has a record."""
    buckets: dict[tuple[str, ...], dict[str, Child]] = {(): {}}
    for record in skill.files:
        parts = record.parts
        for depth, name in enumerate(parts):
            if depth + 1 == len(parts):
                child = Child(record.uri, name, record.mime, False)
            else:
                child = Child(encode_uri(skill.path, file=parts[: depth + 1]), name, DIRECTORY, True)
            # A file and a folder of one name keep the first child here; `_claim` refuses the pair.
            buckets.setdefault(parts[:depth], {}).setdefault(name, child)
    for parts in skill.dirs:
        for depth, name in enumerate(parts):
            child = Child(encode_uri(skill.path, file=parts[: depth + 1]), name, DIRECTORY, True)
            buckets.setdefault(parts[:depth], {}).setdefault(name, child)
        buckets.setdefault(parts, {})
    for parts, bucket in buckets.items():
        children = tuple(sorted(bucket.values(), key=lambda child: child.name))
        yield DirectoryRecord(encode_uri(skill.path, file=parts), children)
