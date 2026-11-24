"""`scripts/release/content.py`: what the built wheel and sdist may hold (spec 008, FR-009).

Fixtures are a tiny wheel and a tiny sdist written with `zipfile` and `tarfile`; the real bytes are read by
the `inspect` job of `wheel.yml` on every push.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from release_fixtures import (
    DEFAULT_VERSION,
    SCHEMA_NAMES,
    make_dist,
    make_repo,
    make_sdist,
    make_wheel,
    metadata_text,
)


@pytest.fixture(scope="module")
def content():
    from release_fixtures import load_script

    return load_script("content")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo")


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    return make_dist(tmp_path / "dist")


def run(content, dist: Path, root: Path, *extra: str) -> int:
    return content.main(["--dir", str(dist), "--root", str(root), *extra])


def refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str], ident: str) -> str:
    assert run(content, dist, root) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith(f"refused [{ident}]:"), err
    return err


def rebuild(dist: Path, **wheel_kwargs: object) -> None:
    for old in dist.glob("*.whl"):
        old.unlink()
    make_wheel(dist, **wheel_kwargs)  # type: ignore[arg-type]


def rebuild_sdist(dist: Path, **kwargs: object) -> None:
    for old in dist.glob("*.tar.gz"):
        old.unlink()
    make_sdist(dist, **kwargs)  # type: ignore[arg-type]


# --- a good build --------------------------------------------------------------------------------------


def test_a_good_wheel_and_sdist_pass(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(content, dist, root) == 0
    assert f"content ok: {DEFAULT_VERSION}" in capsys.readouterr().out


def test_the_version_defaults_to_pyproject_and_can_be_named(content, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path / "repo", version="0.2.0b1")
    dist = make_dist(tmp_path / "dist", "0.2.0b1")
    assert run(content, dist, root) == 0
    other = make_dist(tmp_path / "other", "0.3.0rc2")
    assert run(content, other, root, "--version", "0.3.0rc2") == 0
    assert run(content, other, root) == 1  # pyproject says 0.2.0b1, the files are 0.3.0rc2
    capsys.readouterr()


# --- wheel-contents ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"stray.py": b""},
        {"ext_r2c/tests/test_x.py": b""},
        {"ext_r2c/examples/main.py": b""},
        {"ext_r2c/test_inside.py": b""},
        {"ext_r2c/../evil.py": b""},
        {"ext_r2c/blob.bin": bytes([0xFF, 0xFE, 0x00, 0x80])},
    ],
    ids=["outside", "tests-folder", "examples-folder", "test-file", "dot-dot", "binary"],
)
def test_a_wheel_member_that_does_not_belong_is_refused(
    content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str], extra: dict[str, bytes]
) -> None:
    rebuild(dist, extra=extra)
    refused(content, dist, root, capsys, "wheel-contents")


def test_a_wheel_without_py_typed_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rebuild(dist, drop=("ext_r2c/py.typed",))
    err = refused(content, dist, root, capsys, "wheel-contents")
    assert "py.typed" in err


def test_a_missing_wheel_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for wheel in dist.glob("*.whl"):
        wheel.unlink()
    refused(content, dist, root, capsys, "wheel-contents")


# --- wheel-metadata ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metadata",
    [
        metadata_text("9.9.9"),
        metadata_text(name="other-name"),
        metadata_text(extras=("mcp", "langgraph")),
        metadata_text(extras=("a2a", "langgraph")),
        metadata_text(extras=("a2a", "mcp")),
        "Metadata-Version: 2.5\n\nno headers\n",
    ],
    ids=["version", "name", "no-a2a", "no-mcp", "no-langgraph", "no-headers"],
)
def test_wrong_metadata_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str], metadata: str) -> None:
    rebuild(dist, metadata=metadata)
    refused(content, dist, root, capsys, "wheel-metadata")


# --- schemas -------------------------------------------------------------------------------------------


def test_a_schema_the_standard_does_not_have_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rebuild(dist, extra={"ext_r2c/schema/v1/extra.json": b"{}\n"})
    err = refused(content, dist, root, capsys, "schemas")
    assert "extra.json" in err


def test_a_schema_the_wheel_lacks_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rebuild(dist, drop=(f"ext_r2c/schema/v1/{SCHEMA_NAMES[0]}",))
    err = refused(content, dist, root, capsys, "schemas")
    assert SCHEMA_NAMES[0] in err


# --- sdist-contents ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"root": "wrong-root"},
        {"pkg_info_version": "9.9.9"},
        {"extra": {f"ext_r2c-{DEFAULT_VERSION}/examples/main.py": b""}},
        {"drop": (f"ext_r2c-{DEFAULT_VERSION}/standard/v1/schema/{SCHEMA_NAMES[0]}",)},
        {"drop": (f"ext_r2c-{DEFAULT_VERSION}/PKG-INFO",)},
    ],
    ids=["root", "pkg-info-version", "examples", "schema-missing", "pkg-info-missing"],
)
def test_a_wrong_sdist_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str], kwargs: dict) -> None:
    rebuild_sdist(dist, **kwargs)
    refused(content, dist, root, capsys, "sdist-contents")


TOP = f"ext_r2c-{DEFAULT_VERSION}"


@pytest.mark.parametrize(
    "kind",
    [tarfile.SYMTYPE, tarfile.LNKTYPE],
    ids=["symbolic-link", "hard-link"],
)
def test_an_sdist_member_that_is_a_link_is_refused(
    content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str], kind: bytes
) -> None:
    rebuild_sdist(dist, links={f"{TOP}/src": (kind, "../../../../outside")})
    refused(content, dist, root, capsys, "sdist-contents")


def test_an_sdist_with_a_binary_member_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The wheel has always refused one; the scan skips what does not decode, so the sdist may not hold one either."""
    rebuild_sdist(dist, extra={f"{TOP}/src/blob.bin": bytes([0xFF, 0xFE, 0x80])})
    err = refused(content, dist, root, capsys, "sdist-contents")
    assert "blob.bin" in err


def test_a_wheel_member_that_is_a_symbolic_link_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rebuild(dist, symlinks={"ext_r2c/escape.py": "../../outside"})
    refused(content, dist, root, capsys, "wheel-contents")


def test_a_member_name_with_a_newline_is_one_line_of_refusal(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rebuild(dist, extra={"elsewhere/a\n::add-mask::x.py": b""})
    err = refused(content, dist, root, capsys, "wheel-contents")
    assert "\n" not in err
    assert "::add-mask::x" in err, "the name is shown, spelled out"


def test_a_missing_sdist_is_refused(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for sdist in dist.glob("*.tar.gz"):
        sdist.unlink()
    refused(content, dist, root, capsys, "sdist-contents")


def test_a_refusal_never_holds_text_read_from_a_built_file(content, dist: Path, root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    secret = "MARKER-" + "TEXT-FROM-A-FILE"
    rebuild(dist, extra={"ext_r2c/tests/test_x.py": secret.encode()})
    err = refused(content, dist, root, capsys, "wheel-contents")
    assert secret not in err
