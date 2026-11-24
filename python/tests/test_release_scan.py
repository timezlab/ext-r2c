"""`scripts/release/scan.py`: the generic private-looking-text scan of a built wheel or sdist (spec 008, R10).

Each planted string is spelled from fragments (`release_fixtures.planted`), because the repository's own
commit scan refuses the whole string. The scan prints a file, a category and a count, never a matched line.
"""

from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

import pytest

from release_fixtures import (
    ALLOWED_LINES,
    category_of,
    load_script,
    make_dist,
    make_sdist,
    make_wheel,
    planted,
)

KINDS = [
    "home-linux",
    "home-mac",
    "home-windows",
    "home-root",
    "address-10",
    "address-172",
    "address-172-top",
    "address-192",
    "email",
    "token-github",
    "token-github-pat",
    "token-aws",
    "token-sk",
    "token-slack",
    "token-pem",
    "token-jwt",
]
MEMBER = "ext_r2c/note.txt"


@pytest.fixture(scope="module")
def scan():
    return load_script("scan")


def wheel_with(tmp_path: Path, text: str, member: str = MEMBER) -> Path:
    return make_wheel(tmp_path, extra={member: text.encode()})


def windows(text: str, size: int = 6) -> list[str]:
    return [text[i : i + size] for i in range(len(text) - size + 1)]


@pytest.mark.parametrize("kind", KINDS)
def test_each_planted_kind_is_found_by_file_category_and_count(
    scan, tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    wheel = wheel_with(tmp_path, f"line one\n{planted(kind)}\nline three\n")
    assert scan.main([str(wheel)]) == 1
    captured = capsys.readouterr()
    assert f"scan: {MEMBER} {category_of(kind)} 1" in captured.out
    assert "refused [scan]: 1 lines in 1 files" in captured.err
    assert "example.com" in captured.err  # what to change


@pytest.mark.parametrize("kind", KINDS)
def test_nothing_of_a_planted_string_reaches_the_output(
    scan, tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    text = planted(kind)
    wheel = wheel_with(tmp_path, f"x {text} y\n")
    scan.main([str(wheel)])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert text not in output
    assert not [w for w in windows(text) if w in output], "a fragment of the planted text was printed"


def test_two_matches_on_one_line_count_once_and_two_lines_count_twice(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    one_line = f"{planted('address-10')} and {planted('address-192')}\n"
    wheel = wheel_with(tmp_path, one_line)
    scan.main([str(wheel)])
    assert f"scan: {MEMBER} private-address 1" in capsys.readouterr().out
    wheel.unlink()
    wheel = wheel_with(tmp_path, one_line + f"{planted('address-172')}\n")
    scan.main([str(wheel)])
    assert f"scan: {MEMBER} private-address 2" in capsys.readouterr().out


def test_a_line_with_two_categories_counts_in_each(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wheel = wheel_with(tmp_path, f"{planted('email')} {planted('token-aws')}\n")
    scan.main([str(wheel)])
    out = capsys.readouterr().out
    assert f"scan: {MEMBER} email 1" in out and f"scan: {MEMBER} token 1" in out


def test_the_summary_counts_lines_and_files(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wheel = make_wheel(
        tmp_path,
        extra={"ext_r2c/a.txt": planted("email").encode() + b"\n", "ext_r2c/b.txt": (planted("token-sk") + "\n" + planted("home-linux")).encode()},
    )
    assert scan.main([str(wheel)]) == 1
    assert "refused [scan]: 3 lines in 2 files" in capsys.readouterr().err


def test_an_sdist_is_read_too(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sdist = make_sdist(tmp_path, extra={"ext_r2c-0.1.0a1/src/a.txt": planted("home-mac").encode()})
    assert scan.main([str(sdist)]) == 1
    assert "scan: ext_r2c-0.1.0a1/src/a.txt home-path 1" in capsys.readouterr().out


@pytest.mark.parametrize("line", ALLOWED_LINES)
def test_reserved_domains_and_near_misses_pass(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str], line: str) -> None:
    wheel = wheel_with(tmp_path, line + "\n")
    assert scan.main([str(wheel)]) == 0, capsys.readouterr()


def test_a_binary_member_is_skipped_and_named(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wheel = make_wheel(tmp_path, extra={"ext_r2c/blob.bin": bytes([0xFF, 0xFE, 0x00, 0x80]) + planted("address-10").encode()})
    assert scan.main([str(wheel)]) == 0
    out = capsys.readouterr().out
    assert "skipped binary member ext_r2c/blob.bin" in out


def test_a_clean_dist_passes_and_counts_the_files(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dist = make_dist(tmp_path / "dist")
    files = [str(p) for p in sorted(dist.iterdir())]
    wheel_count = len([n for n in zipfile.ZipFile(next(p for p in dist.glob("*.whl"))).namelist() if not n.endswith("/")])
    with tarfile.open(next(dist.glob("*.tar.gz"))) as t:
        sdist_count = len([m for m in t.getmembers() if m.isfile()])
    assert scan.main(files) == 0
    assert f"scan ok: {wheel_count + sdist_count} files, 0 hits" in capsys.readouterr().out


def test_a_missing_file_is_exit_two(scan, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert scan.main([str(tmp_path / "nothing.whl")]) == 2
    capsys.readouterr()


def test_no_arguments_is_misuse(scan) -> None:
    with pytest.raises(SystemExit) as caught:
        scan.main([])
    assert caught.value.code == 2
