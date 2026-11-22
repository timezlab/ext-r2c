"""Reading a served file from disk (spec 005, research R4).

First cut (phase 3): the file is opened by the path the catalogue recorded, read whole, and compared
with the entry's size and SHA-256. A mismatch, or a file that cannot be read any more, is
`FileChanged`: the caller sends no byte. The hardened read (no link followed at any step, a bounded
read) replaces `read_bytes` in phase 5.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence

from ._catalogue import FileRecord


class FileChanged(Exception):
    """The file on disk is no longer the one the scan described. The message names nothing."""

    def __init__(self) -> None:
        super().__init__("The file changed on disk since it was scanned")

    def __reduce__(self) -> tuple[type[FileChanged], tuple[()]]:
        return (type(self), ())


def read_bytes(folder: str, parts: Sequence[str]) -> bytes:
    """The bytes of the file `parts` below `folder` (an `OSError` if it cannot be read)."""
    with open(os.path.join(folder, *parts), "rb") as stream:
        return stream.read()


def read_file(record: FileRecord) -> bytes:
    """The bytes of a served file, if they are still what the scan saw; else `FileChanged`."""
    try:
        data = read_bytes(record.folder, record.parts)
    except OSError:
        raise FileChanged from None
    if len(data) != record.size or "sha256:" + hashlib.sha256(data).hexdigest() != record.digest:
        raise FileChanged
    return data
