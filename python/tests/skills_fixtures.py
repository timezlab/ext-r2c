"""Fixture folders for the MCP Skills tests (spec 005). Test helper only: not shipped.

Everything here is invented. `standard_tree` builds the three-skill tree of the spec's SC-001;
`Fixture.expected()` says what a server must serve for it, worked out by walking the folder and
percent-encoding each segment itself, never with package code, so a bug in the package cannot
hide in both the answer and the check.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import pytest

SECRET = b"not for callers\n"


def write_skill(
    root: Path,
    path: str,
    *,
    description: str = "Does one thing.",
    extra: str = "",
    body: str = "Steps.\n",
    files: dict[str, bytes | str] | None = None,
) -> Path:
    """Write `<root>/<path>/SKILL.md`, and `files` below that folder; return the skill folder.

    The frontmatter has `name` (the last segment of `path`), `description`, and `extra`, which is
    YAML text the caller controls exactly (it must end in a newline). `files` maps a path below the
    skill folder to its content: `str` is written as UTF-8, `bytes` as they are.
    """
    folder = root / path
    folder.mkdir(parents=True, exist_ok=True)
    name = PurePosixPath(path).name
    # A JSON string is a YAML double-quoted scalar, so any text is safe in either place.
    head = f"---\nname: {json.dumps(name, ensure_ascii=False)}\ndescription: {json.dumps(description, ensure_ascii=False)}\n"
    (folder / "SKILL.md").write_text(f"{head}{extra}---\n{body}", encoding="utf-8")
    for relative, content in (files or {}).items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return folder


@dataclass(frozen=True)
class Fixture:
    root: Path
    names: tuple[str, ...]  # skill paths below `root`, sorted

    def expected(self) -> dict[str, bytes]:
        """`{uri: bytes}` for every file of every skill: what a server has to serve."""
        found: dict[str, bytes] = {}
        for name in self.names:
            skill = self.root / name
            for file in sorted(p for p in skill.rglob("*") if p.is_file()):
                parts = [*name.split("/"), *file.relative_to(skill).parts]
                found["skill://" + "/".join(quote(part, safe="") for part in parts)] = file.read_bytes()
        return found


def standard_tree(tmp_path: Path) -> Fixture:
    """`<tmp_path>/skills` with three skills: a nested one, a binary one, a non-ASCII one."""
    root = tmp_path / "skills"
    write_skill(
        root,
        "team/billing/refunds",
        description="Handles refund requests.",
        extra="license: MIT\nmetadata:\n  owner: billing\n  tags:\n    - refunds\n    - support\n",
        body="# Refunds\n\nCheck the order, then reply.\n",
        files={
            "templates/reply.md": "Hello,\n\nYour refund is on its way.\n",
            "notes.txt": "Internal notes.\n",
            # A nested SKILL.md is an ordinary file of `refunds`, not a skill of its own.
            "examples/SKILL.md": "---\nname: examples\ndescription: A sample, not a skill.\n---\nSample.\n",
        },
    )
    write_skill(
        root,
        "pdf-notes",
        description="Takes notes from a PDF.",
        body="# PDF notes\n\nRead the file, write the notes.\n",
        files={
            "assets/logo.bin": b"\x00\x01\xff\xfe\x00LOGO",
            "scripts/run.sh": "#!/bin/sh\necho notes\n",
            "reference.md": "# Reference\n\nA short reference.\n",
        },
    )
    write_skill(
        root,
        "greetings",
        description="Says hello in many languages.",
        body="# Greetings\n\nXin chào, thế giới! Привет, мир! こんにちは\n",
        files={
            "café.md": "Un café, s'il vous plaît.\n",
            "legacy.txt": b"caf\xe9",  # Latin-1, not UTF-8
            "windows.txt": b"\xef\xbb\xbfline one\r\nline two\r\n",  # a byte-order mark and CRLF
        },
    )
    return Fixture(root, ("greetings", "pdf-notes", "team/billing/refunds"))


def outside_secret(tmp_path: Path) -> Path:
    """A file outside the skills root with known bytes (`SECRET`), so a leak would show."""
    secret = tmp_path / "outside" / "secret.txt"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_bytes(SECRET)
    return secret


def add_symlink(link: Path, target: Path | str, *, directory: bool = False) -> Path:
    """Make `link` a symlink to `target`, or skip the test where the platform cannot."""
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"this platform cannot make symlinks: {e}")
    return link


def add_fifo(path: Path) -> Path:
    """Make `path` a named pipe, or skip the test where the platform cannot."""
    if not hasattr(os, "mkfifo"):
        pytest.skip("this platform has no named pipes")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkfifo(path)
    except OSError as e:
        pytest.skip(f"this platform cannot make named pipes: {e}")
    return path


def many_skills(root: Path, n: int) -> list[str]:
    """`n` skills named `skill-001`, `skill-002`, ..., each with a `SKILL.md` only."""
    names = [f"skill-{i:03d}" for i in range(1, n + 1)]
    for name in names:
        write_skill(root, name)
    return names


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """`{path below root: (size, mtime_ns)}` for everything in a tree, links not followed: two
    snapshots that match prove that nothing was written, renamed or touched in between."""
    state: dict[str, tuple[int, int]] = {}
    for item in sorted(root.rglob("*")):
        info = item.lstat()
        state[item.relative_to(root).as_posix()] = (info.st_size, info.st_mtime_ns)
    return state
