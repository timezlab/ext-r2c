"""`scripts/release/preflight.py`: every gate of FR-004 refuses, names its check and what to change, and
creates nothing. A manual start skips only the three checks that need a tag (spec 008, contracts/scripts.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from release_fakes import FakeGh
from release_fixtures import (
    DEFAULT_VERSION,
    changelog_text,
    commit_off_main,
    load_script,
    make_git_repo,
    make_repo,
)

TAG = f"v{DEFAULT_VERSION}"
REPOSITORY = "owner/name"
API_CALL = ["api", f"repos/{REPOSITORY}/releases/tags/{TAG}"]


@pytest.fixture(scope="module")
def preflight():
    return load_script("preflight")


@dataclass
class World:
    root: Path
    sha: str
    gh: FakeGh

    def argv(self, **overrides: str) -> list[str]:
        values = {
            "--event": "push",
            "--ref-type": "tag",
            "--tag": TAG,
            "--sha": self.sha,
            "--repository": REPOSITORY,
            "--root": str(self.root),
        }
        values.update(overrides)
        return [part for pair in values.items() for part in pair]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A good repository on `main`, a fake `gh`, and the arguments of a real tag run."""
    gh = FakeGh(tmp_path, monkeypatch)
    root = make_repo(tmp_path / "repo")
    return World(root=root, sha=make_git_repo(root), gh=gh)


def listing(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if ".git" not in p.relative_to(root).parts)


def refused(preflight, argv: list[str], capsys: pytest.CaptureFixture[str], ident: str) -> str:
    assert preflight.main(argv) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith(f"refused [{ident}]:"), err
    assert err.count("\n") == 0, "a refusal is one line"
    return err


# --- the good runs -------------------------------------------------------------------------------------


def test_a_good_tag_run_passes_and_says_so(preflight, world: World, capsys: pytest.CaptureFixture[str]) -> None:
    assert preflight.main(world.argv()) == 0
    out = capsys.readouterr().out
    assert f"preflight ok: version {DEFAULT_VERSION}" in out
    assert f"tag {TAG}" in out
    assert "skipped" not in out


def test_a_good_manual_start_skips_exactly_the_three_tag_checks(
    preflight, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(tmp_path, monkeypatch)
    root = make_repo(tmp_path / "repo")  # not even a git repository: nothing tag-bound is read
    assert preflight.main(["--event", "workflow_dispatch", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    skipped = [line for line in out.splitlines() if line.startswith("skipped")]
    assert skipped == [
        "skipped [tag-matches-version]: manual start",
        "skipped [on-main]: manual start",
        "skipped [no-published-release]: manual start",
    ]
    assert f"preflight ok: version {DEFAULT_VERSION}" in out
    assert gh.calls() == [], "a manual start asks GitHub nothing"


# --- check 1: the event --------------------------------------------------------------------------------


@pytest.mark.parametrize("event", ["pull_request", "pull_request_target", "schedule", "workflow_run", ""])
def test_an_unknown_event_is_refused(preflight, world: World, capsys: pytest.CaptureFixture[str], event: str) -> None:
    refused(preflight, world.argv(**{"--event": event}), capsys, "event")


def test_a_push_of_a_branch_is_refused(preflight, world: World, capsys: pytest.CaptureFixture[str]) -> None:
    refused(preflight, world.argv(**{"--ref-type": "branch"}), capsys, "event")


# --- checks 2 and 3: the version -----------------------------------------------------------------------


@pytest.mark.parametrize("version", ["0.1.0a01", "0.1.0.dev1", "0.1a1", "0.1.0a1.post1"])
def test_a_version_in_another_spelling_is_refused(
    preflight, tmp_path: Path, capsys: pytest.CaptureFixture[str], version: str
) -> None:
    root = make_repo(tmp_path / "repo", version=version)
    refused(preflight, ["--event", "workflow_dispatch", "--root", str(root)], capsys, "version-grammar")


def test_a_final_version_is_refused_and_says_it_needs_its_own_decision(
    preflight, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo", version="0.1.0")
    err = refused(preflight, ["--event", "workflow_dispatch", "--root", str(root)], capsys, "prerelease-only")
    assert "own decision" in err


# --- check 4: the tag equals the version ---------------------------------------------------------------


def test_a_tag_that_is_not_v_and_the_version_is_refused_and_both_are_named(
    preflight, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    err = refused(preflight, world.argv(**{"--tag": "v0.1.0a2"}), capsys, "tag-matches-version")
    assert "v0.1.0a2" in err and DEFAULT_VERSION in err


def test_a_tag_without_the_v_is_refused(preflight, world: World, capsys: pytest.CaptureFixture[str]) -> None:
    refused(preflight, world.argv(**{"--tag": DEFAULT_VERSION}), capsys, "tag-matches-version")


# --- check 5: the changelog ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        changelog_text("0.1.0a2"),
        changelog_text(DEFAULT_VERSION, body="\n"),
        changelog_text(DEFAULT_VERSION, date="whenever"),
    ],
    ids=["missing", "empty", "undated"],
)
def test_a_changelog_without_a_dated_non_empty_section_is_refused(
    preflight, tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str
) -> None:
    root = make_repo(tmp_path / "repo", changelog=text)
    refused(preflight, ["--event", "workflow_dispatch", "--root", str(root)], capsys, "changelog-section")


# --- check 6: the tagged commit is on main -------------------------------------------------------------


def test_a_tag_on_a_commit_that_main_does_not_contain_is_refused(
    preflight, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    side = commit_off_main(world.root)
    refused(preflight, world.argv(**{"--sha": side}), capsys, "on-main")


def test_a_tag_on_a_commit_that_main_contains_passes(preflight, world: World) -> None:
    assert preflight.main(world.argv()) == 0


# --- check 7: no published release of the tag ----------------------------------------------------------


def test_the_release_of_the_tag_is_read_from_the_api(preflight, world: World) -> None:
    assert preflight.main(world.argv()) == 0
    assert world.gh.calls() == [API_CALL]


def test_a_published_release_of_the_tag_is_refused(preflight, world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.gh.add_release(TAG, draft=False)
    err = refused(preflight, world.argv(), capsys, "no-published-release")
    assert "next number" in err


def test_a_draft_looks_like_nothing_published_and_passes(preflight, world: World) -> None:
    world.gh.add_release(TAG, draft=True)
    assert preflight.main(world.argv()) == 0


def test_a_failure_of_gh_other_than_not_found_fails_closed(
    preflight, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.gh.update(network_down=True)
    err = refused(preflight, world.argv(), capsys, "no-published-release")
    assert "cannot" in err.lower()


def test_a_server_error_fails_closed(preflight, world: World, capsys: pytest.CaptureFixture[str]) -> None:
    world.gh.update(fail_at=1)
    refused(preflight, world.argv(), capsys, "no-published-release")


# --- check 8: the licence copy -------------------------------------------------------------------------


def test_licence_copies_that_differ_by_a_byte_are_refused(
    preflight, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo", same_license=False)
    refused(preflight, ["--event", "workflow_dispatch", "--root", str(root)], capsys, "license-copy")


# --- order, a manual start's own gates, and "creates nothing" -------------------------------------------


def test_the_version_is_refused_before_the_tag_is_looked_at(
    preflight, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo", version="0.1.0")
    argv = ["--event", "push", "--ref-type", "tag", "--tag", "v9.9.9", "--sha", "HEAD", "--repository", REPOSITORY, "--root", str(root)]
    refused(preflight, argv, capsys, "prerelease-only")


def test_a_manual_start_with_a_bad_version_still_refuses(
    preflight, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path / "repo", version="1.0.0")
    refused(preflight, ["--event", "workflow_dispatch", "--root", str(root)], capsys, "prerelease-only")


def test_a_real_run_without_a_tag_is_misuse_not_a_refusal(preflight, world: World) -> None:
    argv = ["--event", "push", "--ref-type", "tag", "--root", str(world.root)]
    with pytest.raises(SystemExit) as caught:
        preflight.main(argv)
    assert caught.value.code == 2


@pytest.mark.parametrize(
    "case",
    ["event", "version", "tag", "changelog", "on-main", "published", "licence"],
)
def test_a_refusal_leaves_the_directory_as_it_found_it(
    preflight, world: World, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    argv = world.argv()
    if case == "event":
        argv = world.argv(**{"--event": "schedule"})
    elif case == "version":
        (world.root / "python" / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n')
    elif case == "tag":
        argv = world.argv(**{"--tag": "v0.0.0a0"})
    elif case == "changelog":
        (world.root / "CHANGELOG.md").write_text("# Changelog\n")
    elif case == "on-main":
        argv = world.argv(**{"--sha": commit_off_main(world.root)})
    elif case == "published":
        world.gh.add_release(TAG)
    elif case == "licence":
        (world.root / "python" / "LICENSE").write_bytes(b"other\n")
    before = listing(world.root)
    assert preflight.main(argv) == 1
    assert capsys.readouterr().err.startswith("refused [")
    assert listing(world.root) == before
