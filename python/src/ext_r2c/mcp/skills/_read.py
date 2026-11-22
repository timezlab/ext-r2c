"""Reading a file from disk (spec 005, research R4): never through a link, never past its size.

A file is opened one name at a time, from the top of the file system down, each name relative to the
folder opened just before it and with `O_NOFOLLOW`, so a link that appears after the scan is refused by
the kernel and not by a check that could lose a race. The descriptor must be a regular file, and a read
stops after the number of bytes asked for, so a file that grew is found without being read. A served
read then compares the length and the SHA-256 of the bytes it read, and only those, with the entry.
Nothing here opens a file for writing.

Where the kernel cannot refuse a link at every step (no `O_NOFOLLOW`, no `dir_fd`: Windows), each name
on the way is checked with `lstat` first. That leaves a gap between the check and the open, which the
digest comparison covers; Linux and macOS never take that path.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from collections.abc import Sequence
from pathlib import Path

from ._catalogue import FileRecord

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_BINARY = getattr(os, "O_BINARY", 0)
# A folder opened only to be passed through needs no permission to be read (Linux); elsewhere it is
# opened for reading.
_PASS_THROUGH = getattr(os, "O_PATH", 0) or os.O_RDONLY
_SAFE = bool(_NOFOLLOW and _DIRECTORY and os.open in os.supports_dir_fd)
_CHUNK = 1 << 20


class FileChanged(Exception):
    """The file on disk is no longer the one the scan described. The message names nothing."""

    def __init__(self) -> None:
        super().__init__("The file changed on disk since it was scanned")

    def __reduce__(self) -> tuple[type[FileChanged], tuple[()]]:
        return (type(self), ())


class FileUnreadable(Exception):
    """The file could not be read for a reason that says nothing about the file: a failing disk, no
    permission, too many open files. `code` is the `errno`; the message holds nothing else, so no path
    of this host is in it."""

    def __init__(self, code: int) -> None:
        super().__init__(f"The file could not be read: {os.strerror(code)}")
        self.code = code

    def __reduce__(self) -> tuple[type[FileUnreadable], tuple[int]]:
        return (type(self), (self.code,))


# What the system says when the file is not what the scan saw: gone, replaced by a folder or a pipe, a
# link on the way. Every other error is the system's, not the file's.
_CHANGED = frozenset({errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.ENXIO, errno.EISDIR, errno.EINVAL})


def _open_below_the_top(folder: str, parts: Sequence[str]) -> int:
    """A descriptor for `parts` below `folder`, found by opening each name from `/` down."""
    names = [name for name in os.path.abspath(folder).split(os.sep) if name] + list(parts)
    held = os.open(os.sep, os.O_RDONLY | _DIRECTORY | _CLOEXEC)
    try:
        for index, name in enumerate(names):
            if index == len(names) - 1:  # the file: a pipe must not make the open wait for a writer
                flags = os.O_RDONLY | _NONBLOCK
            else:
                flags = _PASS_THROUGH | _DIRECTORY
            step = os.open(name, flags | _NOFOLLOW | _CLOEXEC, dir_fd=held)
            os.close(held)
            held = step
    except BaseException:
        os.close(held)
        raise
    return held


def _open_after_lstat(folder: str, parts: Sequence[str]) -> int:
    """The same, for a platform with no `O_NOFOLLOW`: every name on the way is `lstat`ed first."""
    path = Path(os.path.abspath(folder), *parts)
    for step in (*reversed(path.parents), path):
        if stat.S_ISLNK(os.lstat(step).st_mode):
            raise OSError(errno.ELOOP, "a symbolic link is on the way")
    return os.open(path, os.O_RDONLY | _NONBLOCK | _BINARY | _CLOEXEC)


def _read_up_to(descriptor: int, limit: int | None) -> bytes:
    """At most `limit` bytes (all of them for `None`), in pieces, so the size of the file in the
    entry, not the size of the file now, decides what is allocated."""
    pieces: list[bytes] = []
    remaining = limit
    while remaining is None or remaining > 0:
        piece = os.read(descriptor, _CHUNK if remaining is None else min(_CHUNK, remaining))
        if not piece:
            break
        pieces.append(piece)
        if remaining is not None:
            remaining -= len(piece)
    return b"".join(pieces)


def read_bytes(folder: str, parts: Sequence[str], limit: int | None = None) -> bytes:
    """The first `limit` bytes (all of them for `None`) of the regular file `parts` below `folder`.
    A link anywhere on the way, anything that is not a regular file, or a file that is gone is an
    `OSError`."""
    descriptor = (_open_below_the_top if _SAFE else _open_after_lstat)(folder, parts)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError(errno.EINVAL, "not a regular file")
        return _read_up_to(descriptor, limit)
    finally:
        os.close(descriptor)


def read_file(record: FileRecord) -> bytes:
    """The bytes of a served file, if they are still what the scan saw; else `FileChanged`. At most one
    byte more than the entry's size is read, which is enough to see that a file has grown. An `OSError`
    that does not say the file is gone or swapped (`_CHANGED`) is `FileUnreadable`, not a change."""
    try:
        data = read_bytes(record.folder, record.parts, record.size + 1)
    except OSError as error:
        if error.errno in _CHANGED:
            raise FileChanged from None
        raise FileUnreadable(error.errno or errno.EIO) from None
    if len(data) != record.size or "sha256:" + hashlib.sha256(data).hexdigest() != record.digest:
        raise FileChanged
    return data
