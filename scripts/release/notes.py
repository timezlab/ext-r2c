"""The release notes, assembled from the repository (spec 008, research R11).

    notes.py --repository OWNER/NAME --out FILE [--version V] [--root PATH]

Three parts, in order: the status block (`scripts/release/status-block.md` with four placeholders filled),
the known limits (`docs/known-limits.md` after its title line, verbatim) and the changes of the version (the
body of its section of `CHANGELOG.md`). Nothing is typed at release time and nothing is generated from commits.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from release_common import (
    REPOSITORY_RE,
    REPOSITORY_ROOT,
    Refusal,
    address,
    changelog_section,
    check_version,
    read_version,
    run_main,
    tag_for,
    wheel_name,
)

PLACEHOLDER_RE = re.compile(r"\{\{[^{}]*\}\}")


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="notes.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args(argv)
    if not REPOSITORY_RE.match(args.repository):
        parser.error("--repository must be OWNER/NAME")
    return args


def read_part(path: Path, name: str) -> str:
    if not path.is_file():
        raise Refusal("notes", f"{name} is missing", f"write {name}; the notes are made of it")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise Refusal("notes", f"{name} is empty", f"write {name}; the notes are made of it")
    return text


def status_block(root: Path, version: str, repository: str) -> str:
    name = "scripts/release/status-block.md"
    text = read_part(root / name, name)
    filled = {
        "{{tag}}": tag_for(version),
        "{{version}}": version,
        "{{wheel}}": wheel_name(version),
        "{{address}}": address(repository, version),
    }
    for placeholder, value in filled.items():
        text = text.replace(placeholder, value)
    unknown = PLACEHOLDER_RE.findall(text)
    if unknown:
        raise Refusal("notes", f"{name} has the unknown placeholder {unknown[0]}", "use only {{tag}}, {{version}}, {{wheel}} and {{address}}")
    return text.strip("\n")


def known_limits(root: Path) -> str:
    name = "docs/known-limits.md"
    lines = read_part(root / name, name).splitlines()
    if not lines[0].startswith("# "):
        raise Refusal("notes", f"{name} does not start with a title line '# ...'", "start it with one title line; the notes supply the heading")
    rest = "\n".join(lines[1:]).strip("\n")
    if not rest.strip():
        raise Refusal("notes", f"{name} has nothing after its title", "list the limits under the title")
    return rest


def body(argv: list[str] | None) -> int:
    args = parse(argv)
    version = check_version(args.version or read_version(args.root))
    status = status_block(args.root, version, args.repository)
    limits = known_limits(args.root)
    changes = changelog_section((args.root / "CHANGELOG.md").read_text(encoding="utf-8"), version).strip("\n")
    text = f"## Status\n\n{status}\n\n## Known limits\n\n{limits}\n\n## Changes in {version}\n\n{changes}\n"
    args.out.write_text(text, encoding="utf-8")
    print(f"notes ok: {args.out.stat().st_size} bytes")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_main(lambda: body(argv))


if __name__ == "__main__":
    sys.exit(main())
