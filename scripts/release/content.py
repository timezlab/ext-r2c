"""What the built wheel and sdist may hold (spec 008, FR-009).

    content.py --dir DIR [--version V] [--root PATH]

Reads `DIR/ext_r2c-V-py3-none-any.whl` and `DIR/ext_r2c-V.tar.gz`. Each check has its own refusal id. A
refusal names a member's path, never text read from a member. Nothing here writes anything.
"""

from __future__ import annotations

import argparse
import stat
import sys
import tarfile
import zipfile
from email.parser import HeaderParser
from pathlib import Path, PurePosixPath

from release_common import (
    REPOSITORY_ROOT,
    Refusal,
    read_version,
    run_main,
    sdist_name,
    wheel_name,
)

EXTRAS = ("a2a", "mcp", "langgraph")
FORBIDDEN_FOLDERS = ("tests", "examples")


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="content.py", description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    return parser.parse_args(argv)


def unsafe(path: str) -> bool:
    """A member path that is absolute or climbs out of the archive."""
    parts = PurePosixPath(path).parts
    return path.startswith("/") or ".." in parts or "\\" in path


def standard_schemas(root: Path) -> list[str]:
    folder = root / "standard" / "v1" / "schema"
    return sorted(p.name for p in folder.iterdir() if p.is_file())


def names_under(members: list[str], prefix: str) -> list[str]:
    return sorted(m[len(prefix) :] for m in members if m.startswith(prefix) and not m.endswith("/"))


def schema_difference(found: list[str], expected: list[str], ident: str, where: str) -> None:
    extra = [name for name in found if name not in expected]
    missing = [name for name in expected if name not in found]
    if extra or missing:
        what = []
        if extra:
            what.append("holds " + ", ".join(extra))
        if missing:
            what.append("lacks " + ", ".join(missing))
        raise Refusal(
            ident,
            f"the schema files in {where} are not the standard's ({'; '.join(what)})",
            "build from a checkout whose standard/v1/schema matches the package's schema folder",
        )


def check_wheel_contents(wheel: Path, version: str) -> zipfile.ZipFile:
    if not wheel.is_file():
        raise Refusal("wheel-contents", f"there is no {wheel.name} in the folder", "build the wheel there with uv build")
    archive = zipfile.ZipFile(wheel)
    dist_info = f"ext_r2c-{version}.dist-info"
    for info in archive.infolist():
        if stat.S_ISLNK(info.external_attr >> 16):
            raise Refusal("wheel-contents", f"the wheel has the member {info.filename}, a symbolic link", "a wheel holds plain files only")
    members = [name for name in archive.namelist() if not name.endswith("/")]
    for name in members:
        parts = PurePosixPath(name).parts
        if unsafe(name):
            raise Refusal("wheel-contents", f"the wheel has the member {name}, whose path leaves the archive", "remove it from the build")
        if parts[0] not in ("ext_r2c", dist_info):
            raise Refusal(
                "wheel-contents",
                f"the wheel has the member {name}, outside ext_r2c/ and {dist_info}/",
                "leave it out of the build",
            )
        if any(part in FORBIDDEN_FOLDERS for part in parts[:-1]) or (parts[-1].startswith("test_") and parts[-1].endswith(".py")):
            raise Refusal("wheel-contents", f"the wheel has the test or example file {name}", "leave it out of the build")
        try:
            archive.read(name).decode("utf-8")
        except UnicodeDecodeError:
            raise Refusal("wheel-contents", f"the wheel has the binary member {name}", "the first pre-release ships text only") from None
    if "ext_r2c/py.typed" not in members:
        raise Refusal("wheel-contents", "the wheel has no ext_r2c/py.typed", "ship the typing marker; the package is typed")
    return archive


def check_wheel_metadata(archive: zipfile.ZipFile, version: str) -> None:
    path = f"ext_r2c-{version}.dist-info/METADATA"
    if path not in archive.namelist():
        raise Refusal("wheel-metadata", f"the wheel has no {path}", "build the wheel again")
    headers = HeaderParser().parsestr(archive.read(path).decode("utf-8"))
    if headers.get("Name") != "ext-r2c":
        raise Refusal("wheel-metadata", "METADATA does not say Name: ext-r2c", "the project name is ext-r2c")
    if headers.get("Version") != version:
        raise Refusal("wheel-metadata", f"METADATA does not say Version: {version}", "build from the version in python/pyproject.toml")
    provided = headers.get_all("Provides-Extra") or []
    missing = [extra for extra in EXTRAS if extra not in provided]
    if missing:
        raise Refusal("wheel-metadata", "METADATA lacks Provides-Extra for " + ", ".join(missing), "declare every extra in python/pyproject.toml")


def check_schemas(archive: zipfile.ZipFile, root: Path) -> None:
    found = names_under(archive.namelist(), "ext_r2c/schema/v1/")
    schema_difference(found, standard_schemas(root), "schemas", "the wheel")


def check_sdist(sdist: Path, version: str, root: Path) -> None:
    if not sdist.is_file():
        raise Refusal("sdist-contents", f"there is no {sdist.name} in the folder", "build the sdist there with uv build")
    top = f"ext_r2c-{version}"
    with tarfile.open(sdist) as archive:
        for member in archive.getmembers():
            if not (member.isfile() or member.isdir()):
                raise Refusal("sdist-contents", f"the sdist has the member {member.name}, which is not a plain file", "an sdist holds plain files only")
        members = [m.name for m in archive.getmembers() if m.isfile()]
        for name in members:
            if unsafe(name):
                raise Refusal("sdist-contents", f"the sdist has the member {name}, whose path leaves the archive", "remove it from the build")
            if PurePosixPath(name).parts[0] != top:
                raise Refusal("sdist-contents", f"the sdist has the member {name}, outside {top}/", "build it again with uv build")
            if "examples" in PurePosixPath(name).parts[:-1]:
                raise Refusal("sdist-contents", f"the sdist has the example file {name}", "the examples are run from the tagged source, not shipped")
        for name in members:  # the scan reads text only, so a member that is not text would pass it unseen
            data = archive.extractfile(name)
            assert data is not None
            try:
                data.read().decode("utf-8")
            except UnicodeDecodeError:
                raise Refusal("sdist-contents", f"the sdist has the binary member {name}", "the first pre-release ships text only") from None
        info = f"{top}/PKG-INFO"
        if info not in members:
            raise Refusal("sdist-contents", f"the sdist has no {info}", "build it again with uv build")
        extracted = archive.extractfile(info)
        assert extracted is not None
        headers = HeaderParser().parsestr(extracted.read().decode("utf-8"))
    if headers.get("Version") != version:
        raise Refusal("sdist-contents", f"PKG-INFO does not say Version: {version}", "build from the version in python/pyproject.toml")
    found = names_under(members, f"{top}/standard/v1/schema/")
    schema_difference(found, standard_schemas(root), "sdist-contents", "the sdist")


def body(argv: list[str] | None) -> int:
    args = parse(argv)
    version = args.version or read_version(args.root)
    archive = check_wheel_contents(args.dir / wheel_name(version), version)
    with archive:
        check_wheel_metadata(archive, version)
        check_schemas(archive, args.root)
    check_sdist(args.dir / sdist_name(version), version, args.root)
    print(f"content ok: {version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_main(lambda: body(argv))


if __name__ == "__main__":
    sys.exit(main())
