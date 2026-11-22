"""The content type of a file, and whether to send it as text or as bytes (spec 005, research R11).

The type comes from a fixed table, never from `mimetypes`, which reads the host's own list: two
machines would serve one folder with two sets of types.
"""

from __future__ import annotations

OCTET_STREAM = "application/octet-stream"
DIRECTORY = "inode/directory"

_MIME = {
    "md": "text/markdown",
    "txt": "text/plain",
    "json": "application/json",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "toml": "application/toml",
    "csv": "text/csv",
    "html": "text/html",
    "css": "text/css",
    "js": "text/javascript",
    "ts": "text/typescript",
    "py": "text/x-python",
    "sh": "text/x-shellscript",
    "xml": "application/xml",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "zip": "application/zip",
}


def mime_for(name: str) -> str:
    """The content type of a file name or a path (its last component counts), by extension, compared
    in lower case. `SKILL.md` is Markdown like any `.md`; an extension not in the table is
    `application/octet-stream`."""
    _, dot, extension = name.rpartition(".")  # a "/" after the last dot is never in the table
    return _MIME.get(extension.lower(), OCTET_STREAM) if dot else OCTET_STREAM


def as_text_or_bytes(data: bytes) -> str | bytes:
    """`str` if the bytes are UTF-8, else the bytes. Decided by the bytes, never by the type: strict
    UTF-8 decoding is a one-to-one mapping (no overlong form, no surrogate), so the text encodes
    back to exactly these bytes; a byte-order mark and CRLF are characters and survive."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data
