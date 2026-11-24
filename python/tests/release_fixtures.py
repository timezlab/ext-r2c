"""Helpers for the release-script tests (spec 008). Not collected by pytest.

The scripts under `scripts/release/` are not in the wheel, so a test loads one **by path** from the
checkout, as `test_example_langgraph.py` does for the example. What they act on is built here: a small
repository in `tmp_path`, a small wheel and a small sdist, and (in `release_fakes.py`) a fake `gh`.

The repository is public (principle VI). Everything here is invented, and any string the repository's own
commit scan refuses (a home-directory prefix, a private address range, a token shape) is spelled from
fragments at run time, never written whole in a file.
"""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "release"
REPO = SCRIPTS.parents[1]

SCHEMA_NAMES = (
    "activity.json",
    "answer.json",
    "approval.json",
    "artifact-meta.json",
    "question.json",
    "usage.json",
)

DEFAULT_VERSION = "0.1.0a1"
DEFAULT_DATE = "2026-11-24"


def load_script(name: str) -> ModuleType:
    """Import `scripts/release/<name>.py` by path; fail clearly outside a repository checkout."""
    if not SCRIPTS.is_dir():
        pytest.fail(f"the release scripts are not at {SCRIPTS}; run the tests from a repository checkout", pytrace=False)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(name)


# --- a small repository --------------------------------------------------------------------------------


def changelog_text(version: str = DEFAULT_VERSION, date: str = DEFAULT_DATE, body: str | None = None) -> str:
    body = "### Added\n\n- The first pre-release.\n" if body is None else body
    return (
        "# Changelog\n\nAll notable changes are recorded here.\n\n## [Unreleased]\n\n"
        f"## [{version}] - {date}\n\n{body}\n## [0.0.1] - 2026-11-20\n\n### Added\n\n- A skeleton.\n"
    )


def pyproject_text(version: str) -> str:
    return f'[project]\nname = "ext-r2c"\nversion = "{version}"\n'


def make_repo(
    root: Path,
    *,
    version: str = DEFAULT_VERSION,
    changelog: str | None = None,
    same_license: bool = True,
    known_limits: str | None = "# Known limits\n\n- State is in memory.\n- No authentication.\n",
    status_block: str | None = "This is an alpha: {{tag}} / {{version}}.\n\n`{{wheel}}`\n\n{{address}}\n",
) -> Path:
    """Write the small repository the scripts read, and return its root."""
    (root / "python").mkdir(parents=True, exist_ok=True)
    (root / "python" / "pyproject.toml").write_text(pyproject_text(version))
    (root / "CHANGELOG.md").write_text(changelog if changelog is not None else changelog_text(version))
    (root / "LICENSE").write_bytes(b"Apache License\nVersion 2.0\n")
    (root / "python" / "LICENSE").write_bytes(b"Apache License\nVersion 2.0\n" if same_license else b"Apache License\nVersion 2.1\n")
    schema = root / "standard" / "v1" / "schema"
    schema.mkdir(parents=True, exist_ok=True)
    for name in SCHEMA_NAMES:
        (schema / name).write_text("{}\n")
    if known_limits is not None:
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "known-limits.md").write_text(known_limits)
    if status_block is not None:
        (root / "scripts" / "release").mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "release" / "status-block.md").write_text(status_block)
    return root


def run_in_plain_locale(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run `scripts/release/SCRIPT.py` in a process whose default text encoding is ASCII, as on a machine whose
    locale is not UTF-8. A script that reads or writes text without naming the encoding fails there."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("LC_", "LANG", "PYTHON"))}
    env.update({"LC_ALL": "C", "LANG": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"})
    done = subprocess.run([sys.executable, str(SCRIPTS / f"{script}.py"), *args], capture_output=True, env=env)
    return subprocess.CompletedProcess(
        done.args, done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
    )


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=alice", "-c", "user.email=alice@example.com", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def make_git_repo(root: Path) -> str:
    """Turn `root` into a git repository on `main`, with `origin/main` at HEAD; return HEAD's sha."""
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/main", sha)
    return sha


def commit_off_main(root: Path) -> str:
    """A commit on a side branch that `origin/main` does not contain; return its sha."""
    git(root, "checkout", "-q", "-b", "side")
    (root / "side.txt").write_text("side\n")
    git(root, "add", "side.txt")
    git(root, "commit", "-q", "-m", "side")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "main")
    return sha


# --- a small wheel and a small sdist -------------------------------------------------------------------


def metadata_text(version: str = DEFAULT_VERSION, *, name: str = "ext-r2c", extras: tuple[str, ...] = ("a2a", "mcp", "langgraph")) -> str:
    lines = ["Metadata-Version: 2.5", f"Name: {name}", f"Version: {version}"]
    lines += [f"Provides-Extra: {extra}" for extra in extras]
    return "\n".join(lines) + "\n\nA readme.\n"


def wheel_members(version: str = DEFAULT_VERSION, *, metadata: str | None = None) -> dict[str, bytes]:
    dist = f"ext_r2c-{version}.dist-info"
    members: dict[str, bytes] = {
        "ext_r2c/__init__.py": b"__version__ = '0'\n",
        "ext_r2c/py.typed": b"",
        f"{dist}/METADATA": (metadata if metadata is not None else metadata_text(version)).encode(),
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\n",
        f"{dist}/RECORD": b"",
    }
    for name in SCHEMA_NAMES:
        members[f"ext_r2c/schema/v1/{name}"] = b"{}\n"
    return members


def make_wheel(
    directory: Path,
    version: str = DEFAULT_VERSION,
    *,
    extra: dict[str, bytes] | None = None,
    drop: tuple[str, ...] = (),
    metadata: str | None = None,
    symlinks: dict[str, str] | None = None,
) -> Path:
    members = wheel_members(version, metadata=metadata)
    members.update(extra or {})
    for name in drop:
        members.pop(name)
    path = directory / f"ext_r2c-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in sorted(members.items()):
            z.writestr(name, data)
        for name, target in sorted((symlinks or {}).items()):
            link = zipfile.ZipInfo(name)
            link.create_system = 3  # Unix: the mode below is read as a mode
            link.external_attr = (0o120777 << 16)  # a symbolic link
            z.writestr(link, target)
    return path


def sdist_members(version: str = DEFAULT_VERSION, *, pkg_info_version: str | None = None, root: str | None = None) -> dict[str, bytes]:
    top = root if root is not None else f"ext_r2c-{version}"
    shown = pkg_info_version if pkg_info_version is not None else version
    members: dict[str, bytes] = {
        f"{top}/PKG-INFO": metadata_text(shown).encode(),
        f"{top}/pyproject.toml": pyproject_text(version).encode(),
        f"{top}/src/ext_r2c/__init__.py": b"",
        f"{top}/tests/test_x.py": b"def test_x():\n    pass\n",
    }
    for name in SCHEMA_NAMES:
        members[f"{top}/standard/v1/schema/{name}"] = b"{}\n"
    return members


def make_sdist(
    directory: Path,
    version: str = DEFAULT_VERSION,
    *,
    extra: dict[str, bytes] | None = None,
    drop: tuple[str, ...] = (),
    pkg_info_version: str | None = None,
    root: str | None = None,
    links: dict[str, tuple[bytes, str]] | None = None,
) -> Path:
    """`links` maps a member name to (`tarfile.SYMTYPE` or `tarfile.LNKTYPE`, the name it points at)."""
    members = sdist_members(version, pkg_info_version=pkg_info_version, root=root)
    members.update(extra or {})
    for name in drop:
        members.pop(name)
    path = directory / f"ext_r2c-{version}.tar.gz"
    with tarfile.open(path, "w:gz") as t:
        for name, data in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        for name, (kind, target) in sorted((links or {}).items()):
            link = tarfile.TarInfo(name)
            link.type = kind
            link.linkname = target
            t.addfile(link)
    return path


def make_dist(directory: Path, version: str = DEFAULT_VERSION) -> Path:
    """A good wheel and sdist in `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    make_wheel(directory, version)
    make_sdist(directory, version)
    return directory


# --- strings the scan must find, spelled from fragments -----------------------------------------------

_HOME = "ho" + "me"


def planted(kind: str) -> str:
    """One line of text of the given kind. No whole planted string appears in any file of the repository."""
    table = {
        "home-linux": "/" + _HOME + "/alice/project/file.py",
        "home-mac": "/" + "Users" + "/alice/project/file.py",
        "home-windows": "C:" + "\\" + "Users" + "\\alice\\project",
        "home-root": "/" + "ro" + "ot" + "/.config/x",
        "address-10": "10." + "1.2.3",
        "address-172": "172." + "16.0.9",
        "address-172-top": "172." + "31.255.1",
        "address-192": "192." + "168.1.5",
        "email": "alice" + "@" + "acme-corp" + ".io",
        "token-github": "gh" + "p_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "token-github-pat": "github" + "_pat_" + "a1B2c3D4e5F6g7H8i9J0k1",
        "token-aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "token-sk": "s" + "k-" + "a1B2c3D4e5F6g7H8i9J0k1L2",
        "token-slack": "xo" + "xb-" + "1234567890-abcdefghij",
        "token-pem": "-----" + "BEGIN " + "RSA PRIVATE" + " KEY-----",
        "token-jwt": "ey" + "J" + "hbGciOiJIUzI1NiJ9" + "." + "ey" + "J" + "zdWIiOiJhbGljZSJ9" + ".sig",
    }
    return table[kind]


CATEGORY = {
    "home": "home-path",
    "address": "private-address",
    "email": "email",
    "token": "token",
}


def category_of(kind: str) -> str:
    return CATEGORY[kind.split("-")[0]]


# Strings the scan must let through (reserved example domains, a near miss, ordinary text).
ALLOWED_LINES = (
    "contact alice@example.com",
    "contact alice@example.org",
    "contact alice@example.net",
    "contact alice@host.example",
    "contact alice@host.test",
    "contact alice@host.invalid",
    "contact alice@host.localhost",
    "version 10.0.0.1.2 is not an address",
    "the 172.32.0.1 range is public",
    "see /usr/local/share and /var/run",
    "the build 10.0.0.1.2.3 is not an address.",
    "the folder /ho" + "me/ holds one folder per user",
)
