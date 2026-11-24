"""`scripts/release/notes.py`: the release notes, assembled from the repository (spec 008, R11, US5).

Three parts, in order: the status block, the known limits and the changes of the version. Nothing is typed
at release time and nothing is generated from commits.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from release_fixtures import DEFAULT_VERSION, changelog_text, load_script, make_repo, run_in_plain_locale

TAG = f"v{DEFAULT_VERSION}"
WHEEL = f"ext_r2c-{DEFAULT_VERSION}-py3-none-any.whl"
ADDRESS = f"https://github.com/owner/name/releases/download/{TAG}/{WHEEL}"


@pytest.fixture(scope="module")
def notes():
    return load_script("notes")


def build(notes, root: Path, out: Path, *extra: str) -> int:
    return notes.main(["--repository", "owner/name", "--out", str(out), "--root", str(root), *extra])


def refused(notes, root: Path, out: Path, capsys: pytest.CaptureFixture[str], ident: str, *extra: str) -> str:
    assert build(notes, root, out, *extra) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith(f"refused [{ident}]:"), err
    assert not out.exists(), "a refusal writes no notes"
    return err


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo")


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "RELEASE_NOTES.md"


def test_three_parts_in_order_with_the_named_headings(notes, root: Path, out: Path) -> None:
    assert build(notes, root, out) == 0
    headings = re.findall(r"^## .*$", out.read_text(), flags=re.M)
    assert headings == ["## Status", "## Known limits", f"## Changes in {DEFAULT_VERSION}"]


def test_the_four_placeholders_are_filled(notes, root: Path, out: Path) -> None:
    build(notes, root, out)
    text = out.read_text()
    assert f"{TAG} / {DEFAULT_VERSION}" in text
    assert WHEEL in text and ADDRESS in text
    assert "{{" not in text


def test_an_unknown_placeholder_is_refused(notes, tmp_path: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path / "repo", status_block="Status {{nope}}\n")
    err = refused(notes, root, out, capsys, "notes")
    assert "{{nope}}" in err


def test_every_line_of_the_known_limits_after_its_title_is_present_verbatim_and_in_order(
    notes, tmp_path: Path, out: Path
) -> None:
    limits = "# Known limits\n\n- State is in memory.\n  A second line, indented.\n- No authentication.\n\nA closing line.\n"
    root = make_repo(tmp_path / "repo", known_limits=limits)
    build(notes, root, out)
    text = out.read_text()
    position = 0
    for line in limits.splitlines()[1:]:
        if not line.strip():
            continue
        found = text.find(line, position)
        assert found >= 0, f"line missing or out of order: {line!r}"
        position = found
    assert "# Known limits" not in text.replace("## Known limits", ""), "the title line is dropped; the notes supply the heading"


def test_the_changes_part_is_the_body_of_that_versions_section_only(notes, root: Path, out: Path) -> None:
    build(notes, root, out)
    changes = out.read_text().split(f"## Changes in {DEFAULT_VERSION}")[1]
    assert "The first pre-release." in changes
    assert "A skeleton" not in changes  # the next section, an older version
    assert "Unreleased" not in changes


def test_an_empty_or_missing_changelog_section_is_refused(notes, tmp_path: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path / "empty", changelog=changelog_text(DEFAULT_VERSION, body="\n"))
    refused(notes, root, out, capsys, "changelog-section")
    root = make_repo(tmp_path / "missing", changelog=changelog_text("0.1.0a2"))
    refused(notes, root, out, capsys, "changelog-section")


@pytest.mark.parametrize(
    "case",
    ["no-limits", "title-only", "no-title", "no-status", "empty-status"],
)
def test_a_missing_or_empty_part_is_refused(notes, tmp_path: Path, out: Path, capsys: pytest.CaptureFixture[str], case: str) -> None:
    kwargs: dict = {
        "no-limits": {"known_limits": None},
        "title-only": {"known_limits": "# Known limits\n\n"},
        "no-title": {"known_limits": "- State is in memory.\n- No authentication.\n"},  # a line would be dropped as the "title"
        "no-status": {"status_block": None},
        "empty-status": {"status_block": "\n  \n"},
    }[case]
    root = make_repo(tmp_path / "repo", **kwargs)
    refused(notes, root, out, capsys, "notes")


def test_the_notes_are_read_and_written_as_utf8_whatever_the_locale(tmp_path: Path) -> None:
    """CHANGELOG.md holds characters outside ASCII (an ellipsis, a dash); a runner's locale must not matter."""
    body = "- Added: the first release… and a dash — in one line\n"
    root = make_repo(tmp_path / "repo", changelog=changelog_text(body=body))
    out = tmp_path / "RELEASE_NOTES.md"
    done = run_in_plain_locale("notes", "--repository", "owner/name", "--out", str(out), "--root", str(root))
    assert done.returncode == 0, done.stderr
    assert "… and a dash —" in out.read_bytes().decode("utf-8")


def test_the_version_can_be_named_and_defaults_to_pyproject(notes, tmp_path: Path, out: Path) -> None:
    root = make_repo(tmp_path / "repo", version="0.2.0b1")
    assert build(notes, root, out) == 0
    assert "## Changes in 0.2.0b1" in out.read_text()
    root2 = make_repo(tmp_path / "other", version="0.1.0a1", changelog=changelog_text("0.3.0rc1"))
    assert build(notes, root2, out, "--version", "0.3.0rc1") == 0
    assert "## Changes in 0.3.0rc1" in out.read_text()


def test_a_final_version_is_refused(notes, tmp_path: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path / "repo", version="1.0.0", changelog=changelog_text("1.0.0"))
    refused(notes, root, out, capsys, "prerelease-only")


def test_it_prints_how_many_bytes_it_wrote(notes, root: Path, out: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build(notes, root, out)
    assert f"notes ok: {out.stat().st_size} bytes" in capsys.readouterr().out
