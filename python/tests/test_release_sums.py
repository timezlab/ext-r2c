"""`scripts/release/sums.py`: write and check `SHA256SUMS`, in the format `sha256sum` writes and reads
(spec 008, contracts/release-assets.md, R12).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from release_fixtures import DEFAULT_VERSION, load_script, make_dist, make_wheel


@pytest.fixture(scope="module")
def sums():
    return load_script("sums")


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    return make_dist(tmp_path / "dist")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refused(sums, argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    assert sums.main(argv) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith("refused [sums]:"), err
    return err


def test_write_makes_the_sha256sum_format(sums, dist: Path) -> None:
    assert sums.main(["write", "--dir", str(dist)]) == 0
    text = (dist / "SHA256SUMS").read_text()
    names = sorted(p.name for p in dist.iterdir() if p.suffix == ".whl" or p.name.endswith(".tar.gz"))
    assert text == "".join(f"{digest(dist / n)}  {n}\n" for n in names)
    assert all(re.fullmatch(r"[0-9a-f]{64}  \S+", line) for line in text.splitlines())
    assert "SHA256SUMS" not in text, "the list does not name itself"
    assert names[0].endswith(".whl"), "sorted by name, the wheel first"


def test_a_file_named_twice_in_the_list_is_refused_even_when_the_last_line_is_right(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sums.main(["write", "--dir", str(dist)])
    listing = dist / "SHA256SUMS"
    lines = listing.read_text().splitlines()
    wheel_line = next(line for line in lines if line.endswith(".whl"))
    wrong = "0" * 64 + wheel_line[64:]
    listing.write_text("\n".join([wrong, *lines]) + "\n")  # a wrong line first, the right one after it
    err = refused(sums, ["check", "--dir", str(dist)], capsys)
    assert "twice" in err and ".whl" in err


def test_the_list_name_is_the_one_every_script_uses(sums) -> None:
    assert sums.LIST_NAME == load_script("release_common").SUMS_LIST


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum on this machine")
def test_sha256sum_accepts_the_list(sums, dist: Path) -> None:
    sums.main(["write", "--dir", str(dist)])
    done = subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=dist, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_write_prints_name_size_and_digest(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sums.main(["write", "--dir", str(dist)])
    out = capsys.readouterr().out
    for path in dist.glob("*.whl"):
        assert path.name in out and str(path.stat().st_size) in out and digest(path) in out


def test_check_passes_after_write(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sums.main(["write", "--dir", str(dist)])
    assert sums.main(["check", "--dir", str(dist)]) == 0
    assert "sums ok: 2 files" in capsys.readouterr().out


def test_check_names_a_file_with_an_altered_byte(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sums.main(["write", "--dir", str(dist)])
    wheel = next(dist.glob("*.whl"))
    wheel.write_bytes(wheel.read_bytes() + b"x")
    err = refused(sums, ["check", "--dir", str(dist)], capsys)
    assert wheel.name in err


def test_check_refuses_a_missing_file(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sums.main(["write", "--dir", str(dist)])
    sdist = next(dist.glob("*.tar.gz"))
    sdist.unlink()
    err = refused(sums, ["check", "--dir", str(dist)], capsys)
    assert sdist.name in err


def test_check_refuses_an_extra_wheel(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sums.main(["write", "--dir", str(dist)])
    extra = make_wheel(dist, "0.9.0a1")
    err = refused(sums, ["check", "--dir", str(dist)], capsys)
    assert extra.name in err


def test_check_refuses_a_missing_list(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    refused(sums, ["check", "--dir", str(dist)], capsys)


def test_check_refuses_a_name_with_a_path(sums, dist: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sums.main(["write", "--dir", str(dist)])
    sums_file = dist / "SHA256SUMS"
    sums_file.write_text(sums_file.read_text().replace(f"ext_r2c-{DEFAULT_VERSION}.tar.gz", f"../ext_r2c-{DEFAULT_VERSION}.tar.gz"))
    err = refused(sums, ["check", "--dir", str(dist)], capsys)
    assert "bare file name" in err, "the list is refused for its shape, not for a file that happens to be missing"


@pytest.mark.parametrize("what", ["two-wheels", "no-sdist", "no-wheel"])
def test_write_needs_exactly_one_wheel_and_one_sdist(sums, dist: Path, capsys: pytest.CaptureFixture[str], what: str) -> None:
    if what == "two-wheels":
        make_wheel(dist, "0.9.0a1")
    elif what == "no-sdist":
        next(dist.glob("*.tar.gz")).unlink()
    else:
        next(dist.glob("*.whl")).unlink()
    refused(sums, ["write", "--dir", str(dist)], capsys)
    assert not (dist / "SHA256SUMS").exists()


def test_summary_writes_a_table_to_the_step_summary(sums, dist: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    assert sums.main(["write", "--dir", str(dist), "--summary"]) == 0
    text = target.read_text()
    for path in dist.glob("*.whl"):
        assert path.name in text and digest(path) in text
    assert text.lstrip().startswith("|") or "\n|" in text


def test_summary_without_the_variable_is_fine(sums, dist: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert sums.main(["write", "--dir", str(dist), "--summary"]) == 0
