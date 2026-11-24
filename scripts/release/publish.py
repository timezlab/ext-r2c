"""The one script that writes a release (spec 008, research R3, FR-010 to FR-012).

    publish.py --tag TAG --repository OWNER/NAME --dir DIR --notes FILE

DIR holds the three files that were tested. A draft is created (or a leftover one is refreshed), the three files
are uploaded and read back, and only a draft whose bytes equal the tested ones is published, last. A published
release is never changed: the same bytes are success with no write, anything else is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from release_common import (
    REPOSITORY_RE,
    SUMS_LIST,
    Refusal,
    check_sums,
    run_main,
    sdist_name,
    version_from_tag,
    wheel_name,
)

STATE_FIELDS = "tagName,isDraft,isPrerelease"


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="publish.py", description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    args = parser.parse_args(argv)
    if not REPOSITORY_RE.match(args.repository):
        parser.error("--repository must be OWNER/NAME")
    if not args.dir.is_dir():
        parser.error("--dir must be a folder")
    if not args.notes.is_file():
        parser.error("--notes must be a file")
    return args


class Gh:
    """`gh release VERB ... --repo OWNER/NAME`: the only way this script reaches GitHub."""

    def __init__(self, repository: str) -> None:
        self.repository = repository

    def __call__(self, verb: str, *args: str) -> str:
        done = subprocess.run(
            ["gh", "release", verb, *args, "--repo", self.repository],
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            detail = " ".join(done.stderr.split()) or f"exit status {done.returncode}"
            raise Refusal(
                "gh",
                f"gh release {verb} failed: {detail}",
                "run the job again; a draft that was left behind is reused and nothing is public before the last step",
            )
        return done.stdout


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def digests(folder: Path) -> dict[str, str]:
    return {path.name: sha256(path) for path in sorted(folder.iterdir()) if path.is_file()}


def check_files(folder: Path, wanted: list[str]) -> None:
    """DIR holds exactly the wheel, the sdist and the list: no other file, no folder, no hidden file."""
    found = sorted(path.name for path in folder.iterdir())
    if found == wanted and all((folder / name).is_file() for name in wanted):
        return
    missing = [name for name in wanted if name not in found]
    extra = [name for name in found if name not in wanted]
    what = f"{missing[0]} is missing from the folder" if missing else f"{extra[0]} is in the folder and is not a release file"
    raise Refusal("unexpected-files", what, f"the folder must hold exactly {', '.join(wanted)}")


def compare(read: Path, tested: dict[str, str], ident: str, where: str, change: str) -> None:
    """What was read from `where` is exactly the tested files: the three names, the same SHA-256 each."""
    got = digests(read)
    for name in sorted(tested):
        if name not in got:
            raise Refusal(ident, f"{name} is missing from {where}", change)
        if got[name] != tested[name]:
            raise Refusal(ident, f"{name} in {where} is not the file that was tested", change)
    extra = sorted(set(got) - set(tested))
    if extra:
        raise Refusal(ident, f"{extra[0]} is in {where} and is not one of the three tested files", change)


def state_of(gh: Gh, tag: str) -> dict | None:
    rows = json.loads(gh("list", "--limit", "200", "--json", STATE_FIELDS))
    return next((row for row in rows if row["tagName"] == tag), None)


def read_back(gh: Gh, tag: str, into: Path) -> None:
    gh("download", tag, "--pattern", "*", "--dir", str(into))


def already_published(gh: Gh, tag: str, row: dict, tested: dict[str, str]) -> int:
    """A release that is public is read and never written: the same bytes are success, anything else is refused."""
    change = "a mistake in a published pre-release is fixed by the next number"
    if not row["isPrerelease"]:
        raise Refusal("published-differs", f"the published release {tag} is not marked as a pre-release", change)
    with tempfile.TemporaryDirectory() as folder:
        read_back(gh, tag, Path(folder))
        compare(Path(folder), tested, "published-differs", f"the published release {tag}", change)
    print(f"already published: {tag} holds the three tested files; nothing was written")
    return 0


def prepare_draft(gh: Gh, tag: str, row: dict | None, notes: Path, wanted: list[str]) -> None:
    """A draft that holds this run's notes and none of another run's files."""
    if row is None:
        gh("create", tag, "--draft", "--prerelease", "--latest=false", "--verify-tag", "--title", tag, "--notes-file", str(notes))
        return
    gh("edit", tag, "--notes-file", str(notes), "--prerelease", "--latest=false")
    assets = json.loads(gh("view", tag, "--json", "assets"))["assets"]
    for stray in sorted(asset["name"] for asset in assets if asset["name"] not in wanted):
        gh("delete-asset", tag, stray, "--yes")


def body(argv: list[str] | None) -> int:
    args = parse(argv)
    version = version_from_tag(args.tag)
    wanted = sorted([wheel_name(version), sdist_name(version), SUMS_LIST])
    check_files(args.dir, wanted)
    check_sums(args.dir)
    tested = digests(args.dir)
    gh = Gh(args.repository)

    row = state_of(gh, args.tag)
    if row is not None and not row["isDraft"]:
        return already_published(gh, args.tag, row, tested)

    prepare_draft(gh, args.tag, row, args.notes, wanted)
    gh("upload", args.tag, *(str(args.dir / name) for name in wanted), "--clobber")
    with tempfile.TemporaryDirectory() as folder:
        read_back(gh, args.tag, Path(folder))
        compare(Path(folder), tested, "upload-differs", "the draft", "run the job again; the draft is still unpublished")

    gh("edit", args.tag, "--draft=false", "--prerelease", "--latest=false")
    after = state_of(gh, args.tag)
    if after is None or after["isDraft"] or not after["isPrerelease"]:
        raise Refusal(
            "not-public",
            f"after the publishing call {args.tag} is not a published pre-release",
            "look at the release on GitHub and run the job again",
        )
    print(f"published {args.tag}: {len(wanted)} files, pre-release")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_main(lambda: body(argv))


if __name__ == "__main__":
    sys.exit(main())
