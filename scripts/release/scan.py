"""A generic scan of a built wheel or sdist for text that looks private (spec 008, research R10).

    scan.py FILE [FILE ...]

Four categories: a home-directory path, a private address, an e-mail address (reserved example domains
pass) and a token shape. The scan is generic on purpose: the list of the maintainer's own private names stays
on the maintainer's machine (decision D5). It prints a member, a category and a count of lines. It never
prints, logs or raises a matched line.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from release_common import Refusal, printable, run_main

_FENCE = r"(?<![A-Za-z0-9._-])"
# The Linux prefix is spelled in two pieces so that this file does not trip the repository's own commit scan.
_LINUX_HOME = "/ho" + "me/"
# A hit ends where a name ends, so a path at the end of a line or before a quote counts, and so does an address
# at the end of a sentence; a doubled backslash is how a Windows path looks in source text. Every part of every
# pattern is bounded (an e-mail address has at most 64 characters before the @, labels of at most 63), so one
# very long line costs a time proportional to its length and cannot stall the job (outside review, T058).
PATTERNS: dict[str, re.Pattern[str]] = {
    "home-path": re.compile(
        _FENCE + _LINUX_HOME + r"[A-Za-z0-9._-]+"
        "|" + _FENCE + r"/Users/[A-Za-z0-9._-]+"
        r"|[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z0-9._-]+"
        "|" + _FENCE + r"/root/"
    ),
    "private-address": re.compile(
        r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?!\d|\.\d)"
    ),
    "email": re.compile(
        r"[A-Za-z0-9._%+-]{1,64}@(?P<domain>[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24})"
    ),
    "token": re.compile(
        r"(?:ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_]{20,}"
        r"|AKIA[0-9A-Z]{16}"
        r"|\bsk-[A-Za-z0-9]{20,}"
        r"|xox[abprs]-[A-Za-z0-9-]{10,}"
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
        r"|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}"
    ),
}
RESERVED_DOMAINS = ("example.com", "example.org", "example.net")
RESERVED_TLDS = ("example", "test", "invalid", "localhost")


def reserved(domain: str) -> bool:
    """RFC 2606 and RFC 6761 names that no one owns: safe to write in a public file."""
    domain = domain.lower()
    return domain in RESERVED_DOMAINS or domain.endswith(tuple("." + d for d in RESERVED_DOMAINS)) or domain.rsplit(".", 1)[-1] in RESERVED_TLDS


def members(path: Path) -> Iterator[tuple[str, bytes]]:
    """Every file member of a wheel (zip) or an sdist (tar.gz) as (path in the archive, bytes)."""
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.endswith("/"):
                    yield name, archive.read(name)
    else:
        with tarfile.open(path) as archive:
            for member in archive.getmembers():
                if member.isfile():
                    extracted = archive.extractfile(member)
                    assert extracted is not None
                    yield member.name, extracted.read()


def hit_categories(line: str) -> set[str]:
    found = set()
    for category, pattern in PATTERNS.items():
        for match in pattern.finditer(line):
            if category == "email" and reserved(match["domain"]):
                continue
            found.add(category)
            break
    return found


def body(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="scan.py", description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    counts: Counter[tuple[str, str]] = Counter()
    hit_lines = 0
    hit_files: set[str] = set()
    scanned = 0
    for path in args.files:
        here = 0
        for name, data in members(path):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                print(f"skipped binary member {printable(name)}")
                continue
            here += 1
            for line in text.splitlines():
                found = hit_categories(line)
                if found:
                    hit_lines += 1
                    hit_files.add(f"{path.name}:{name}")
                    for category in found:
                        counts[(name, category)] += 1
        print(f"scanned {printable(path.name)}: {here} files")
        scanned += here
    for (name, category), count in sorted(counts.items()):
        print(f"scan: {printable(name)} {category} {count}")
    if hit_lines:
        raise Refusal(
            "scan",
            f"{hit_lines} lines in {len(hit_files)} files look private",
            "remove the text or, if it is invented, use example.com",
        )
    print(f"scan ok: {scanned} files, 0 hits")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_main(lambda: body(argv))


if __name__ == "__main__":
    sys.exit(main())
