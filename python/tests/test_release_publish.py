"""`scripts/release/publish.py`: the one script that writes a release (spec 008, research R3, FR-010 to FR-012).

A fake `gh` (release_fakes.py) holds the releases and refuses any call outside the table. The order is the
point: a draft is created, the three files are uploaded and read back, and only a draft whose bytes equal the
recorded sums is published, last. A published release is never changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from release_fakes import FakeGh
from release_fixtures import DEFAULT_VERSION, load_script, make_dist

VERSION = DEFAULT_VERSION
TAG = f"v{VERSION}"
REPOSITORY = "owner/name"
WHEEL = f"ext_r2c-{VERSION}-py3-none-any.whl"
SDIST = f"ext_r2c-{VERSION}.tar.gz"
SUMS = "SHA256SUMS"
NOTES_TEXT = "The notes of this run.\n"


@pytest.fixture(scope="module")
def publish():
    return load_script("publish")


@dataclass
class World:
    gh: FakeGh
    dist: Path
    notes: Path

    def argv(self, **overrides: str) -> list[str]:
        values = {"--tag": TAG, "--repository": REPOSITORY, "--dir": str(self.dist), "--notes": str(self.notes)}
        values.update(overrides)
        return [part for pair in values.items() for part in pair]

    def files(self) -> dict[str, bytes]:
        return {name: (self.dist / name).read_bytes() for name in (WHEEL, SDIST, SUMS)}


def build_world(base: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A good dist (wheel, sdist, `SHA256SUMS`), a notes file and a fake `gh` with no release."""
    base.mkdir(parents=True, exist_ok=True)
    gh = FakeGh(base, monkeypatch)
    dist = make_dist(base / "dist")
    assert load_script("sums").main(["write", "--dir", str(dist)]) == 0
    notes = base / "notes.md"
    notes.write_text(NOTES_TEXT)
    return World(gh=gh, dist=dist, notes=notes)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> World:
    built = build_world(tmp_path / "w", monkeypatch)
    capsys.readouterr()  # the checksum table of the setup is not what a test reads
    return built


def build_scenario(base: Path, monkeypatch: pytest.MonkeyPatch, scenario: str) -> World:
    built = build_world(base, monkeypatch)
    if scenario == "leftover draft":
        built.gh.add_release(TAG, draft=True, assets={"old.txt": b"old", WHEEL: b"half"}, notes="old notes")
    return built


def verbs(gh: FakeGh) -> list[str]:
    """The `gh release` subcommand of each call, in order."""
    return [call[1] for call in gh.calls()]


def flag_value(call: list[str], flag: str) -> str:
    return call[call.index(flag) + 1]


def clean(gh: FakeGh) -> None:
    """No call outside the table, and no write to a published release."""
    assert gh.unexpected() == []
    assert gh.violations() == []


def refused(publish, argv: list[str], capsys: pytest.CaptureFixture[str], ident: str) -> str:
    assert publish.main(argv) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith(f"refused [{ident}]:"), err
    assert "\n" not in err, "a refusal is one line"
    return err


# --- a fresh run -------------------------------------------------------------------------------------------


def test_a_fresh_run_creates_a_draft_uploads_reads_back_and_publishes_last(
    publish, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    assert publish.main(world.argv()) == 0
    gh = world.gh
    assert verbs(gh) == ["list", "create", "list", "upload", "download", "list", "edit", "list"]
    calls = gh.calls()
    create, upload, download, publishing = calls[1], calls[3], calls[4], calls[6]
    assert create[2] == TAG
    for flag in ("--draft", "--prerelease", "--latest=false", "--verify-tag"):
        assert flag in create, flag
    assert flag_value(create, "--title") == TAG
    assert flag_value(create, "--notes-file") == str(world.notes)
    assert upload[2] == TAG and "--clobber" in upload
    uploaded = sorted(Path(arg).name for arg in upload if arg.startswith(str(world.dist)))
    assert uploaded == sorted([WHEEL, SDIST, SUMS])
    assert download[2] == TAG and flag_value(download, "--pattern") == "*"
    assert flag_value(download, "--dir") != str(world.dist), "the read-back goes to a clean directory"
    assert "--draft=false" in publishing and "--prerelease" in publishing and "--latest=false" in publishing
    assert [i for i, c in enumerate(calls) if "--draft=false" in c] == [6], "the publishing call is made once, after the compare"
    release = gh.release(TAG)
    assert release["draft"] is False and release["prerelease"] is True
    assert {name: gh.asset(TAG, name) for name in release["assets"]} == world.files()
    assert release["notes"] == NOTES_TEXT
    clean(gh)
    out = capsys.readouterr().out
    assert "published" in out and TAG in out


def test_the_dist_folder_is_read_and_never_changed(publish, world: World) -> None:
    before = (sorted(p.name for p in world.dist.iterdir()), world.files())
    assert publish.main(world.argv()) == 0
    assert (sorted(p.name for p in world.dist.iterdir()), world.files()) == before


def test_every_call_names_the_repository(publish, world: World) -> None:
    assert publish.main(world.argv()) == 0
    for call in world.gh.calls():
        assert call[0] == "release"
        assert flag_value(call, "--repo") == REPOSITORY, call


# --- a rerun after a partial failure -----------------------------------------------------------------------


def test_a_leftover_draft_gets_this_runs_notes_loses_its_stray_asset_and_is_uploaded_again(
    publish, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = build_scenario(tmp_path / "w", monkeypatch, "leftover draft")
    assert publish.main(world.argv()) == 0
    gh = world.gh
    assert verbs(gh) == ["list", "list", "edit", "view", "list", "delete-asset", "list", "upload", "download", "list", "edit", "list"]
    calls = gh.calls()
    refresh, view, delete = calls[2], calls[3], calls[5]
    assert refresh[2] == TAG and flag_value(refresh, "--notes-file") == str(world.notes)
    assert "--prerelease" in refresh and "--latest=false" in refresh and "--draft=false" not in refresh
    assert view[2] == TAG and flag_value(view, "--json") == "assets"
    assert delete[2:4] == [TAG, "old.txt"] and "--yes" in delete
    release = gh.release(TAG)
    assert sorted(release["assets"]) == sorted([WHEEL, SDIST, SUMS]), "the stray is gone, nothing else was removed"
    assert {name: gh.asset(TAG, name) for name in release["assets"]} == world.files(), "--clobber replaced the half file"
    assert release["notes"] == NOTES_TEXT and release["draft"] is False
    clean(gh)


def test_a_leftover_draft_that_already_holds_the_three_files_is_uploaded_again_and_published(
    publish, world: World
) -> None:
    world.gh.add_release(TAG, draft=True, assets=world.files(), notes="old notes")
    assert publish.main(world.argv()) == 0
    gh = world.gh
    assert verbs(gh) == ["list", "list", "edit", "view", "list", "upload", "download", "list", "edit", "list"]
    assert "delete-asset" not in verbs(gh)
    assert gh.release(TAG)["draft"] is False
    clean(gh)


def test_a_published_release_with_the_tested_bytes_succeeds_and_writes_nothing(
    publish, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.gh.add_release(TAG, draft=False, assets=world.files())
    assert publish.main(world.argv()) == 0
    assert world.gh.writes() == []
    assert verbs(world.gh) == ["list", "download"]
    assert "already published" in capsys.readouterr().out
    clean(world.gh)


@pytest.mark.parametrize(
    ("case", "name"),
    [
        ("the wheel differs", WHEEL),
        ("the sdist differs", SDIST),
        ("the list differs", SUMS),
        ("the sdist is missing", SDIST),
        ("an asset is extra", "extra.txt"),
        ("it is not a pre-release", "pre-release"),
    ],
)
def test_a_published_release_that_differs_is_refused_and_nothing_is_written(
    publish, world: World, capsys: pytest.CaptureFixture[str], case: str, name: str
) -> None:
    assets = world.files()
    prerelease = True
    if case.endswith("differs"):
        assets[name] = b"not the tested bytes"
    elif case == "the sdist is missing":
        del assets[SDIST]
    elif case == "an asset is extra":
        assets["extra.txt"] = b"x"
    else:
        prerelease = False
    world.gh.add_release(TAG, draft=False, prerelease=prerelease, assets=assets)
    err = refused(publish, world.argv(), capsys, "published-differs")
    assert name in err
    gh = world.gh
    assert gh.writes() == [], "a published file is never replaced or removed"
    assert set(verbs(gh)) <= {"list", "download"}
    assert gh.release(TAG)["draft"] is False
    clean(gh)


# --- an upload that does not come back the same -----------------------------------------------------------


@pytest.mark.parametrize(
    ("how", "name"),
    [("the wheel", WHEEL), ("the sdist", SDIST), ("the list", SUMS), ("a lost file", SDIST)],
)
def test_an_upload_that_comes_back_different_stops_before_the_publishing_call(
    publish, world: World, capsys: pytest.CaptureFixture[str], how: str, name: str
) -> None:
    if how == "a lost file":
        world.gh.lose_on_upload(name)
    else:
        world.gh.alter_on_download(name, "bytes the draft did not get")
    err = refused(publish, world.argv(), capsys, "upload-differs")
    assert name in err
    gh = world.gh
    assert not any("--draft=false" in call for call in gh.calls()), "nothing public"
    assert gh.release(TAG)["draft"] is True, "the draft stays, for the next run"
    clean(gh)


def test_the_state_after_publishing_is_read_and_must_say_published(
    publish, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.gh.publish_does_nothing()
    refused(publish, world.argv(), capsys, "not-public")
    assert world.gh.calls()[-1][1] == "list", "the state is read again after the publishing call"


# --- a release that changes while the script runs ---------------------------------------------------------

CHANGING_VERBS = {"create", "edit", "delete-asset", "upload"}


@pytest.mark.parametrize(
    ("scenario", "writes"),
    [
        ("fresh", ["upload", "edit"]),  # `create` is the first write: there is no release to read before it
        ("leftover draft", ["edit", "delete-asset", "upload", "edit"]),  # the notes, the stray, the files, the publishing call
    ],
)
def test_every_write_to_an_existing_release_is_right_after_a_read_of_its_state(
    publish, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, writes: list[str]
) -> None:
    world = build_scenario(tmp_path / "w", monkeypatch, scenario)
    assert publish.main(world.argv()) == 0
    calls = world.gh.calls()
    guarded = [number for number, call in enumerate(calls) if call[1] in CHANGING_VERBS - {"create"}]
    assert [calls[number][1] for number in guarded] == writes
    for number in guarded:
        assert calls[number - 1][1] == "list", f"call {number} ({calls[number][1]}) is not right after a read of the state"


@pytest.mark.parametrize("scenario", ["fresh", "leftover draft"])
def test_a_draft_that_someone_publishes_in_the_middle_is_not_written_to_by_the_next_write(
    publish, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scenario: str
) -> None:
    dry = build_scenario(tmp_path / "dry", monkeypatch, scenario)
    assert publish.main(dry.argv()) == 0
    capsys.readouterr()
    for number, call in enumerate(dry.gh.calls(), start=1):
        if call[1] in CHANGING_VERBS:
            continue  # the write is itself the call: nothing can be read between the last read and it
        world = build_scenario(tmp_path / f"meanwhile-{number}", monkeypatch, scenario)
        world.gh.publish_meanwhile(number)
        assert publish.main(world.argv()) in (0, 1), f"call {number} ({call[1]})"
        capsys.readouterr()
        assert world.gh.violations() == [], f"a write reached a release published at call {number} ({call[1]})"
        assert world.gh.unexpected() == []


def test_a_draft_that_is_published_before_the_upload_is_refused_with_its_own_reason(
    publish, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.gh.publish_meanwhile(3)  # a fresh run: list, create, then the read before the upload
    err = refused(publish, world.argv(), capsys, "not-a-draft")
    assert TAG in err
    assert "upload" not in verbs(world.gh)
    assert world.gh.violations() == []


def test_a_draft_that_is_deleted_before_the_upload_is_refused_with_its_own_reason_not_a_gh_failure(
    publish, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    world.gh.delete_meanwhile(3)  # a fresh run: list, create, then the read before the upload finds no release
    err = refused(publish, world.argv(), capsys, "not-a-draft")
    assert TAG in err
    assert "upload" not in verbs(world.gh)
    assert world.gh.violations() == []


@pytest.mark.parametrize("second_is_draft", [True, False])
def test_two_releases_for_one_tag_are_refused_before_any_write(
    publish, world: World, capsys: pytest.CaptureFixture[str], second_is_draft: bool
) -> None:
    world.gh.add_release(TAG, draft=True, assets=world.files())
    world.gh.add_row(TAG, draft=second_is_draft)
    err = refused(publish, world.argv(), capsys, "release-ambiguous")
    assert TAG in err and "2 releases" in err
    assert world.gh.writes() == []
    clean(world.gh)


# --- what is refused before any call is made -------------------------------------------------------------


def _extra_file(world: World) -> None:
    (world.dist / "notes.txt").write_text("not a release file\n")


def _hidden_file(world: World) -> None:
    (world.dist / ".gitignore").write_text("*\n")


def _a_folder(world: World) -> None:
    (world.dist / "sub").mkdir()


def _no_sdist(world: World) -> None:
    (world.dist / SDIST).unlink()


def _no_list(world: World) -> None:
    (world.dist / SUMS).unlink()


@pytest.mark.parametrize("damage", [_extra_file, _hidden_file, _a_folder, _no_sdist, _no_list])
def test_a_folder_without_exactly_the_three_files_is_refused_before_any_call(
    publish, world: World, capsys: pytest.CaptureFixture[str], damage
) -> None:
    damage(world)
    refused(publish, world.argv(), capsys, "unexpected-files")
    assert world.gh.calls() == []


def test_files_of_another_version_are_refused_before_any_call(
    publish, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    refused(publish, world.argv(**{"--tag": "v0.2.0a1"}), capsys, "unexpected-files")
    assert world.gh.calls() == []


def test_a_wheel_that_no_longer_matches_the_list_is_refused_before_any_call(
    publish, world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    with (world.dist / WHEEL).open("ab") as f:
        f.write(b"changed after the list was written")
    refused(publish, world.argv(), capsys, "sums")
    assert world.gh.calls() == []


@pytest.mark.parametrize(
    ("tag", "ident"),
    [
        ("0.1.0a1", "version-grammar"),
        ("x0.1.0a1", "version-grammar"),
        ("v0.1", "version-grammar"),
        ("v0.1.0a1; echo hi", "version-grammar"),
        ("v1.0.0", "prerelease-only"),
    ],
)
def test_a_tag_that_is_not_v_and_a_pre_release_is_refused_before_any_call(
    publish, world: World, capsys: pytest.CaptureFixture[str], tag: str, ident: str
) -> None:
    refused(publish, world.argv(**{"--tag": tag}), capsys, ident)
    assert world.gh.calls() == []


@pytest.mark.parametrize("bad", [{"--repository": "owner"}, {"--notes": "/no/such/notes.md"}])
def test_bad_arguments_are_misuse_not_a_refusal(publish, world: World, bad: dict[str, str]) -> None:
    with pytest.raises(SystemExit) as caught:
        publish.main(world.argv(**bad))
    assert caught.value.code == 2
    assert world.gh.calls() == []


# --- a failure of gh ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", ["fresh", "leftover draft"])
def test_a_gh_failure_at_any_call_ends_non_zero_and_nothing_is_public_before_the_publishing_call(
    publish, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], scenario: str
) -> None:
    dry = build_scenario(tmp_path / "dry", monkeypatch, scenario)
    assert publish.main(dry.argv()) == 0
    total = dry.gh.call_count()
    publishing_call = next(n for n, call in enumerate(dry.gh.calls(), start=1) if "--draft=false" in call)
    capsys.readouterr()
    for n in range(1, total + 1):
        world = build_scenario(tmp_path / f"fail-{n}", monkeypatch, scenario)
        world.gh.fail_at(n)
        assert publish.main(world.argv()) == 1, n
        err = capsys.readouterr().err
        assert "refused [gh]" in err and "injected failure" in err, (n, err)
        assert world.gh.call_count() == n, f"the script made a call after the failure of call {n}"
        release = world.gh.release(TAG)
        public = release is not None and not release["draft"]
        assert public == (n > publishing_call), f"call {n} failed; the publishing call is {publishing_call}"
        clean(world.gh)
