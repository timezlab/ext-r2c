"""`scripts/release/release_common.py`: the grammar of a version and a tag, the changelog section, the names
of the files, and how a refusal becomes an exit code (spec 008, contracts/scripts.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from release_fixtures import changelog_text, load_script, make_repo


@pytest.fixture(scope="module")
def common():
    return load_script("release_common")


# --- the version grammar -------------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["0.1.0a1", "0.1.0b2", "1.2.3rc10", "10.20.30a0", "0.0.0a1"])
def test_a_normal_form_pre_release_passes(common, version: str) -> None:
    assert common.check_version(version) == version


@pytest.mark.parametrize(
    "version",
    [
        "0.1.0a01",  # a leading zero in the pre-release number
        "0.1.0.dev1",
        "0.1.0a1.post2",
        "01.0.0a1",
        "0.1a1",
        "v0.1.0a1",
        "0.1.0-alpha.1",
        "0.1.0a1 ",
        "",
        "0.1.0a",
        "0.1.0c1",
        "0.1.0a1+local",
        "1!0.1.0a1",
    ],
)
def test_any_other_spelling_is_the_version_grammar_refusal(common, version: str) -> None:
    with pytest.raises(common.Refusal) as caught:
        common.check_version(version)
    assert caught.value.id == "version-grammar"


@pytest.mark.parametrize("version", ["0.1.0", "1.0.0", "10.2.3"])
def test_a_final_version_is_a_pre_release_only_refusal(common, version: str) -> None:
    with pytest.raises(common.Refusal) as caught:
        common.check_version(version)
    assert caught.value.id == "prerelease-only"
    assert "own decision" in caught.value.line()


def test_read_version_reads_pyproject_under_the_root(common, tmp_path: Path) -> None:
    make_repo(tmp_path, version="0.2.0b3")
    assert common.read_version(tmp_path) == "0.2.0b3"


# --- the tag and the file names ------------------------------------------------------------------------


def test_the_tag_is_v_and_the_version(common) -> None:
    assert common.tag_for("0.1.0a1") == "v0.1.0a1"


def test_file_names_and_address(common) -> None:
    assert common.wheel_name("0.1.0a1") == "ext_r2c-0.1.0a1-py3-none-any.whl"
    assert common.sdist_name("0.1.0a1") == "ext_r2c-0.1.0a1.tar.gz"
    assert common.address("timezlab/ext-r2c", "0.1.0a1") == (
        "https://github.com/timezlab/ext-r2c/releases/download/v0.1.0a1/ext_r2c-0.1.0a1-py3-none-any.whl"
    )


# --- the changelog section -----------------------------------------------------------------------------


def test_the_section_body_is_returned_up_to_the_next_heading(common) -> None:
    body = common.changelog_section(changelog_text("0.1.0a1"), "0.1.0a1")
    assert "The first pre-release." in body
    assert "A skeleton" not in body  # the next version's section is not part of it
    assert "Unreleased" not in body


def test_a_section_dated_in_the_future_is_accepted(common) -> None:
    text = changelog_text("0.1.0a1", date="2099-01-01")
    assert "pre-release" in common.changelog_section(text, "0.1.0a1")


@pytest.mark.parametrize(
    "text",
    [
        "# Changelog\n\n## [Unreleased]\n\n- something\n",  # [Unreleased] is never the section
        changelog_text("0.1.0a2"),  # another version only
        changelog_text("0.1.0a1", body="\n"),  # empty body
        changelog_text("0.1.0a1", body="### Added\n\n### Fixed\n\n"),  # only sub-headings
        changelog_text("0.1.0a1", date="soon"),  # a date that is not a date
        changelog_text("0.1.0a1", date="2026-13-40"),  # a date that does not exist
        changelog_text("0.1.0a1", date="20261124"),  # not the dashed form
        "",
    ],
)
def test_a_missing_or_empty_or_undated_section_is_refused(common, text: str) -> None:
    with pytest.raises(common.Refusal) as caught:
        common.changelog_section(text, "0.1.0a1")
    assert caught.value.id == "changelog-section"


def test_a_version_that_is_a_prefix_of_another_is_not_confused(common) -> None:
    text = changelog_text("0.1.0a10")
    with pytest.raises(common.Refusal):
        common.changelog_section(text, "0.1.0a1")


# --- a refusal and its exit code -----------------------------------------------------------------------


def test_a_refusal_prints_one_line_with_its_id_and_what_to_change(common) -> None:
    line = common.Refusal("on-main", "the tagged commit is not on main", "Merge it into main first").line()
    assert line == "refused [on-main]: the tagged commit is not on main. Merge it into main first."


def test_what_to_change_starts_with_a_capital(common) -> None:
    line = common.Refusal("x", "it failed", "fix the thing").line()
    assert line == "refused [x]: it failed. Fix the thing."


def test_a_trailing_full_stop_is_not_doubled(common) -> None:
    line = common.Refusal("x", "it failed.", "Fix it.").line()
    assert line == "refused [x]: it failed. Fix it."


def test_run_main_maps_a_refusal_to_one_and_prints_it(common, capsys: pytest.CaptureFixture[str]) -> None:
    def gate() -> int:
        raise common.Refusal("scan", "a line", "remove it")

    assert common.run_main(gate) == 1
    captured = capsys.readouterr()
    assert captured.err.strip() == "refused [scan]: a line. Remove it."
    assert captured.out == ""


def test_run_main_maps_any_other_error_to_two(common, capsys: pytest.CaptureFixture[str]) -> None:
    def broken() -> int:
        raise FileNotFoundError("no such file")

    assert common.run_main(broken) == 2
    assert "no such file" in capsys.readouterr().err


def test_run_main_passes_a_success_through(common) -> None:
    assert common.run_main(lambda: 0) == 0
