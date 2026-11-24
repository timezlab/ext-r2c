"""What the release scripts share: the grammar of a version and a tag, the readers of the repository's own
files, the names of the files a release carries, and the way a refusal becomes an exit code.

Standard library only; it imports nothing from `ext_r2c`, and the package imports nothing from here
(spec 008, contracts/scripts.md). Python 3.11 to 3.13.
"""

from __future__ import annotations

import datetime
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

# A pre-release in the normal form of PEP 440: three numbers without leading zeros, then a, b or rc, then a
# number. No `.dev`, `.post`, epoch or local part, so the file names `uv build` writes are predictable.
#
# `\Z`, not `$`: `$` also matches before a trailing newline, and `re.ASCII` keeps `\d` to the digits 0-9.
VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(a|b|rc)(0|[1-9]\d*)\Z", re.ASCII)
FINAL_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z", re.ASCII)
SECTION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\] - (?P<date>\S+)\s*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\Z", re.ASCII)
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SUMS_LIST = "SHA256SUMS"
SUMS_SCRIPT = Path(__file__).with_name("sums.py")


def printable(text: str) -> str:
    """`text` for a log line: a character that is not printable (a newline, an escape) is spelled out.

    A name that comes from inside an archive is data; printed raw, a newline in it would start a line of its
    own in the public log, and a line that starts with `::` is a command to the runner.
    """
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode("ascii") for c in text)


class Refusal(Exception):
    """A gate said no. `id` names the check; `what` says what failed; `change` says what to change."""

    def __init__(self, id: str, what: str, change: str) -> None:
        super().__init__(what)
        self.id = id
        self.what = what
        self.change = change

    def line(self) -> str:
        change = printable(self.change).rstrip(".")
        return f"refused [{self.id}]: {printable(self.what).rstrip('.')}. {change[:1].upper()}{change[1:]}."


def run_main(fn: Callable[[], int]) -> int:
    """Run a script's body: a refusal is exit 1 and one line on standard error; any other error is exit 2."""
    try:
        return fn()
    except Refusal as refusal:
        print(refusal.line(), file=sys.stderr)
        return 1
    except Exception as error:  # an unexpected failure is the script's, not a gate's
        print(printable(f"error: {type(error).__name__}: {error}"), file=sys.stderr)
        return 2


def check_version(version: str) -> str:
    """Return `version` if it is a normal-form pre-release; otherwise refuse with the right id."""
    if VERSION_RE.match(version):
        return version
    if FINAL_RE.match(version):
        raise Refusal(
            "prerelease-only",
            f"the version {version} is a final release",
            "use a pre-release number such as 0.1.0a1; a final release needs its own decision",
        )
    raise Refusal(
        "version-grammar",
        f"the version {version!r} is not a pre-release in normal form",
        "write it as MAJOR.MINOR.PATCH followed by a, b or rc and a number, for example 0.1.0a1",
    )


def read_version(root: Path) -> str:
    """The version in `ROOT/python/pyproject.toml`: the one place the number is written."""
    with (root / "python" / "pyproject.toml").open("rb") as f:
        return str(tomllib.load(f)["project"]["version"])


def tag_for(version: str) -> str:
    return f"v{version}"


def version_from_tag(tag: str) -> str:
    """The version a tag names: `v` and a normal-form pre-release; anything else is refused, before any call."""
    if not tag.startswith("v"):
        raise Refusal(
            "version-grammar",
            f"the tag {tag!r} does not start with v",
            "name it v and the version, for example v0.1.0a1",
        )
    return check_version(tag[1:])


def check_sums(folder: Path, ident: str = "sums") -> None:
    """Run `sums.py check` on `folder`; a refusal of it is raised again under `ident`.

    The script is run, not imported: this module is the only one the others import (contracts/scripts.md).
    """
    done = subprocess.run(
        [sys.executable, str(SUMS_SCRIPT), "check", "--dir", str(folder)],
        capture_output=True,
        text=True,
    )
    if done.returncode == 0:
        return
    lines = done.stderr.strip().splitlines()
    last = lines[-1] if lines else ""
    prefix = "refused [sums]: "
    if done.returncode == 1 and last.startswith(prefix):
        what, _, change = last.removeprefix(prefix).partition(". ")
        raise Refusal(ident, what, change or f"write {SUMS_LIST} again")
    raise Refusal(ident, f"the check of {SUMS_LIST} could not run", last or "run sums.py check by hand")


def wheel_name(version: str) -> str:
    return f"ext_r2c-{version}-py3-none-any.whl"


def sdist_name(version: str) -> str:
    return f"ext_r2c-{version}.tar.gz"


def address(repository: str, version: str) -> str:
    """The address an adopter installs the wheel from."""
    return f"https://github.com/{repository}/releases/download/{tag_for(version)}/{wheel_name(version)}"


def changelog_section(text: str, version: str) -> str:
    """The body of `## [VERSION] - DATE` up to the next `## `; refuse if it is missing, undated or empty.

    A body that holds only sub-headings (`### Added`) and blank lines is empty. `[Unreleased]` is never the
    section of a version.
    """
    lines = text.splitlines()
    start = None
    for number, line in enumerate(lines):
        match = SECTION_RE.match(line)
        if match and match["version"] == version:
            if not DATE_RE.match(match["date"]) or not _is_date(match["date"]):
                raise Refusal(
                    "changelog-section",
                    f"the CHANGELOG section for {version} has the date {match['date']!r}",
                    "date it as YYYY-MM-DD, for example 2026-11-24",
                )
            start = number + 1
            break
    if start is None:
        raise Refusal(
            "changelog-section",
            f"CHANGELOG.md has no section '## [{version}] - DATE'",
            "rename [Unreleased] to the version and the date of the release",
        )
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    if not any(line.strip() and not line.startswith("#") for line in body):
        raise Refusal(
            "changelog-section",
            f"the CHANGELOG section for {version} is empty",
            "write what changed under it",
        )
    return "\n".join(body).strip("\n") + "\n"


def _is_date(value: str) -> bool:
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True
