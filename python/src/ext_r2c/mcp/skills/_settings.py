"""The settings of a `SkillsExtension`, checked before anything is scanned (spec 005, FR-006).

A bad setting is a plain `ValueError` that names it; a problem with the folders themselves is a
`SkillsError` from the scan. Nothing here touches the file system.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, Final

SCOPES: Final = ("private", "public")


def _shown(value: Any) -> str:
    return f"{value!r:.40}"


def folders_of(folders: Any) -> tuple[str, ...]:
    """The folders to scan, as text and absolute (so a later `refresh` after a `chdir` reads the same
    ones). A bare string or path-like is one folder, never a list of characters."""
    if isinstance(folders, (str, os.PathLike)):
        items: list[Any] = [folders]
    elif isinstance(folders, Sequence) and not isinstance(folders, (bytes, bytearray)):
        items = list(folders)
    else:
        raise ValueError(f"folders must be a folder or a list of folders, not {type(folders).__name__}")
    if not items:
        raise ValueError("folders must hold at least one folder")
    return tuple(_folder(item) for item in items)


def _folder(item: Any) -> str:
    if not isinstance(item, (str, os.PathLike)):
        raise ValueError(f"folders must hold folders, not {type(item).__name__}")
    path = os.fspath(item)
    if not isinstance(path, str):
        raise ValueError("folders must hold text paths, not bytes")
    if not path or "\0" in path:
        raise ValueError("folders must not hold an empty path or one with a NUL byte")
    return os.path.join(os.getcwd(), path)


def patterns_of(name: str, patterns: Any) -> tuple[str, ...]:
    """A list of non-empty glob patterns; a bare string is a mistake (it would be a list of letters)."""
    if isinstance(patterns, (str, bytes, bytearray)) or not isinstance(patterns, Sequence):
        raise ValueError(f"{name} must be a list of patterns, not {type(patterns).__name__}")
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"{name} must hold only non-empty strings, not {_shown(pattern)}")
    return tuple(patterns)


def ttl_ms_of(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:  # `True` is an `int`
        raise ValueError(f"ttl_ms must be a whole number of milliseconds, 0 or more, not {_shown(value)}")
    return value


def cache_scope_of(value: Any) -> str:
    if not isinstance(value, str) or value not in SCOPES:
        raise ValueError(f"cache_scope must be one of {', '.join(SCOPES)}, not {_shown(value)}")
    return value
