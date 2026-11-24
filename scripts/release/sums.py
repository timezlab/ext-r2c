"""The checksum list of a release, in the format `sha256sum` writes and reads (spec 008, research R12).

    sums.py write --dir DIR [--summary]
    sums.py check --dir DIR

`write` hashes the one wheel and the one sdist in DIR and writes `SHA256SUMS`; `check` compares every file
against the list and refuses a wheel or sdist the list does not name.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

from release_common import Refusal, run_main

LIST_NAME = "SHA256SUMS"
LINE_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^/\\\s]+)$")


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def artifacts(folder: Path) -> list[Path]:
    return sorted([*folder.glob("*.whl"), *folder.glob("*.tar.gz")], key=lambda p: p.name)


def write(folder: Path, summary: bool) -> int:
    wheels, sdists = sorted(folder.glob("*.whl")), sorted(folder.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise Refusal(
            "sums",
            f"the folder holds {len(wheels)} wheels and {len(sdists)} sdists",
            "it must hold exactly one of each; clear it and build again",
        )
    rows = [(path.name, path.stat().st_size, digest(path)) for path in artifacts(folder)]
    (folder / LIST_NAME).write_text("".join(f"{sha}  {name}\n" for name, _, sha in rows), encoding="utf-8")
    for name, size, sha in rows:
        print(f"{name}  {size} bytes  {sha}")
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and target:
        table = ["| file | bytes | SHA-256 |", "|---|---:|---|"]
        table += [f"| `{name}` | {size} | `{sha}` |" for name, size, sha in rows]
        with open(target, "a", encoding="utf-8") as f:
            f.write("\n".join(table) + "\n")
    return 0


def check(folder: Path) -> int:
    listing = folder / LIST_NAME
    if not listing.is_file():
        raise Refusal("sums", f"the folder has no {LIST_NAME}", "write it with sums.py write before anything is tested")
    recorded: dict[str, str] = {}
    for line in listing.read_text(encoding="utf-8").splitlines():
        match = LINE_RE.match(line)
        if not match:
            raise Refusal("sums", f"a line of {LIST_NAME} is not '<sha256>  <name>' with a bare file name", "write the list again with sums.py write")
        if match["name"] in recorded:
            raise Refusal("sums", f"{LIST_NAME} lists {match['name']} twice", "write the list again with sums.py write")
        recorded[match["name"]] = match["digest"]
    for name, sha in recorded.items():
        path = folder / name
        if not path.is_file():
            raise Refusal("sums", f"{name} is in {LIST_NAME} but not in the folder", "restore the file or write the list again")
        if digest(path) != sha:
            raise Refusal("sums", f"{name} does not match {LIST_NAME}", "the file changed after the list was written; build it again")
    unlisted = [path.name for path in artifacts(folder) if path.name not in recorded]
    if unlisted:
        raise Refusal("sums", f"{unlisted[0]} is in the folder but not in {LIST_NAME}", "remove it, or write the list again")
    print(f"sums ok: {len(recorded)} files")
    return 0


def body(argv: list[str] | None) -> int:
    parser = argparse.ArgumentParser(prog="sums.py", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    writer = commands.add_parser("write")
    writer.add_argument("--dir", type=Path, required=True)
    writer.add_argument("--summary", action="store_true")
    checker = commands.add_parser("check")
    checker.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args(argv)
    return write(args.dir, args.summary) if args.command == "write" else check(args.dir)


def main(argv: list[str] | None = None) -> int:
    return run_main(lambda: body(argv))


if __name__ == "__main__":
    sys.exit(main())
