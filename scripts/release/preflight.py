"""The gates a release passes before anything is built (spec 008, FR-004).

    preflight.py --event EVENT [--ref-type TYPE] [--tag TAG] [--sha SHA] [--repository OWNER/NAME] [--root PATH]

Each check has its own refusal id. A manual start (`workflow_dispatch`) runs the checks that need no tag and
says which three it skipped. Nothing here writes a file, a tag or a release.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from release_common import (
    REPOSITORY_RE,
    REPOSITORY_ROOT,
    Refusal,
    changelog_section,
    check_version,
    read_version,
    run_main,
    tag_for,
)

REAL, MANUAL = "push", "workflow_dispatch"


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="preflight.py", description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref-type", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--sha", default="HEAD")
    parser.add_argument("--repository", default="")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args(argv)
    if args.event == REAL and args.ref_type == "tag":
        if not args.tag or not args.repository:
            parser.error("a tag run needs --tag and --repository")
        if not REPOSITORY_RE.match(args.repository):
            parser.error("--repository must be OWNER/NAME")
    return args


def check_event(args: argparse.Namespace) -> bool:
    """Return True for a manual start; refuse any event or ref that is not one of the two allowed pairs."""
    if args.event == MANUAL:
        return True
    if args.event == REAL and args.ref_type == "tag":
        return False
    ref = f" on a {args.ref_type}" if args.ref_type else ""
    raise Refusal(
        "event",
        f"the event {args.event!r}{ref} does not start a release",
        "start it by pushing a tag, or by a manual start of the workflow",
    )


def check_tag_matches(tag: str, version: str) -> None:
    if tag != tag_for(version):
        raise Refusal(
            "tag-matches-version",
            f"the tag is {tag} but python/pyproject.toml says {version}",
            f"push the tag {tag_for(version)}, or change the version",
        )


def check_on_main(root: Path, sha: str) -> None:
    done = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "origin/main"],
        capture_output=True,
        text=True,
    )
    if done.returncode == 1:  # git's answer for "not an ancestor"; any other status means git could not tell
        raise Refusal(
            "on-main",
            "the tagged commit is not on main",
            "merge it into main and tag the commit that is there",
        )
    if done.returncode != 0:
        raise Refusal(
            "on-main",
            "origin/main could not be read to tell whether the tagged commit is on main",
            "fetch main in full (a checkout with fetch-depth 0) and run it again",
        )


def check_no_published_release(repository: str, tag: str) -> None:
    done = subprocess.run(
        ["gh", "api", f"repos/{repository}/releases/tags/{tag}"],
        capture_output=True,
        text=True,
    )
    if done.returncode == 0:
        raise Refusal(
            "no-published-release",
            f"{tag} already has a published release",
            "a mistake in a published pre-release is fixed by the next number",
        )
    if "HTTP 404" in done.stderr:
        return  # not found: nothing is published (a draft answers 404 too)
    raise Refusal(
        "no-published-release",
        f"GitHub could not say whether {tag} is published",
        "try again; the check cannot say yes without an answer",
    )


def check_license_copy(root: Path) -> None:
    copies = []
    for name in ("python/LICENSE", "LICENSE"):
        try:
            copies.append((root / name).read_bytes())
        except OSError:
            raise Refusal("license-copy", f"{name} cannot be read", "keep the root LICENSE and its copy python/LICENSE") from None
    if copies[0] != copies[1]:
        raise Refusal(
            "license-copy",
            "python/LICENSE differs from the root LICENSE",
            "copy the root LICENSE to python/LICENSE",
        )


def skip(check: str) -> None:
    print(f"skipped [{check}]: manual start")


def body(argv: list[str] | None) -> int:
    args = parse(argv)
    manual = check_event(args)
    version = check_version(read_version(args.root))  # the two version checks, grammar first
    if manual:
        skip("tag-matches-version")
    else:
        check_tag_matches(args.tag, version)
    changelog_section((args.root / "CHANGELOG.md").read_text(encoding="utf-8"), version)
    if manual:
        skip("on-main")
        skip("no-published-release")
    else:
        check_on_main(args.root, args.sha)
        check_no_published_release(args.repository, args.tag)
    check_license_copy(args.root)
    print(f"preflight ok: version {version}" + ("" if manual else f" (tag {args.tag})"))
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_main(lambda: body(argv))


if __name__ == "__main__":
    sys.exit(main())
