"""The records a scan produces and the catalogue built from them (spec 005, `data-model.md`):
exact dictionaries, sorted lists, one record per directory, a fresh generation on every build.
The records here are made by hand: no folder is read."""

from __future__ import annotations

import copy
import dataclasses
import pickle
from collections.abc import Sequence
from typing import Any

import pytest
from ext_r2c.mcp.skills._catalogue import (
    Catalogue,
    DirectoryRecord,
    FileRecord,
    LeftOutPath,
    SkillInfo,
    SkillRecord,
    SkillsError,
)
from ext_r2c.mcp.skills._content import mime_for
from ext_r2c.mcp.skills._uris import encode_uri

DIGEST = "sha256:" + "0" * 64
DIR = "inode/directory"


def file_record(path: Sequence[str], parts: Sequence[str], *, size: int = 10, folder: str | None = None) -> FileRecord:
    return FileRecord(
        uri=encode_uri(path, file=parts),
        parts=tuple(parts),
        folder=folder or "/skills/" + "/".join(path),
        size=size,
        digest=DIGEST,
        mime=mime_for(parts[-1]),
        skill=encode_uri(path, file="SKILL.md"),
    )


def skill_record(
    path: Sequence[str],
    others: Sequence[Sequence[str]] = (),
    *,
    folder: str | None = None,
    dirs: Sequence[Sequence[str]] | None = None,
) -> SkillRecord:
    """A skill at `path` whose files are `SKILL.md` and `others` (each a list of path parts). `dirs`
    are the folders the scan found (each a list of path parts below the skill folder); left out, the
    record says none, as a record made before directories were recorded did."""
    folder = folder or "/skills/" + "/".join(path)
    parts: list[Sequence[str]] = [["SKILL.md"], *others]
    extra = {} if dirs is None else {"dirs": tuple(tuple(d) for d in dirs)}
    return SkillRecord(
        name=path[-1],
        path=tuple(path),
        uri=encode_uri(path, file="SKILL.md"),
        folder=folder,
        frontmatter={"name": path[-1], "description": f"The {path[-1]} skill."},
        files=tuple(file_record(path, p, folder=folder) for p in parts),
        **extra,
    )


REFUNDS = ("team", "billing", "refunds")
REFUND_OTHERS = [["templates", "reply.md"], ["notes.txt"], ["assets", "logo.bin"]]


def standard_records() -> list[SkillRecord]:
    return [skill_record(REFUNDS, REFUND_OTHERS), skill_record(("greetings",))]


# --- The dictionaries and the lists ----------------------------------------------------------------


def test_the_dictionaries_are_exact() -> None:
    catalogue = Catalogue.build(standard_records(), [])
    assert dict(catalogue.by_uri) == {s.uri: s for s in catalogue.skills}
    assert set(catalogue.by_uri) == {"skill://greetings/SKILL.md", "skill://team/billing/refunds/SKILL.md"}
    assert set(catalogue.files) == {
        "skill://greetings/SKILL.md",
        "skill://team/billing/refunds/SKILL.md",
        "skill://team/billing/refunds/templates/reply.md",
        "skill://team/billing/refunds/notes.txt",
        "skill://team/billing/refunds/assets/logo.bin",
    }
    for uri, record in catalogue.files.items():
        assert record.uri == uri
    for uri, record in catalogue.by_uri.items():
        assert record.uri == uri


def test_the_skills_are_sorted_by_uri() -> None:
    records = [
        skill_record(("zeta",)),
        skill_record(("alpha",)),
        skill_record(("team", "mid")),
        skill_record(("beta",)),
        skill_record(("yyy", "aaa")),  # by name it would be first; by URI it is after `team`
    ]
    catalogue = Catalogue.build(records, [])
    assert [s.uri for s in catalogue.skills] == [
        "skill://alpha/SKILL.md",
        "skill://beta/SKILL.md",
        "skill://team/mid/SKILL.md",
        "skill://yyy/aaa/SKILL.md",
        "skill://zeta/SKILL.md",
    ]
    assert [catalogue.by_uri[s.uri] for s in catalogue.skills] == list(catalogue.skills)


def test_the_files_of_a_skill_are_sorted_by_relative_path() -> None:
    shuffled = [["templates", "reply.md"], ["notes.txt"], ["a", "b.md"], ["a.md"], ["a-b.md"], ["assets", "logo.bin"]]
    catalogue = Catalogue.build([skill_record(("x",), shuffled)], [])
    assert [f.parts for f in catalogue.skills[0].files] == [
        ("SKILL.md",),
        ("a-b.md",),  # "a-b.md" < "a.md" < "a/b.md": the path as one string, not as a list of names
        ("a.md",),
        ("a", "b.md"),
        ("assets", "logo.bin"),
        ("notes.txt",),
        ("templates", "reply.md"),
    ]


def test_the_catalogue_serves_the_records_it_lists() -> None:
    catalogue = Catalogue.build(standard_records(), [])
    for skill in catalogue.skills:
        for record in skill.files:
            assert catalogue.files[record.uri] is record


def test_what_the_scan_left_out_is_kept_in_order() -> None:
    left = [LeftOutPath(".hidden", "hidden"), LeftOutPath("team/link", "symbolic link"), LeftOutPath("zz", "not a regular file")]
    assert Catalogue.build(standard_records(), left).left_out == tuple(left)
    assert Catalogue.build(standard_records(), iter(left)).left_out == tuple(left)
    assert Catalogue.build(standard_records(), []).left_out == ()


def test_an_empty_catalogue() -> None:
    catalogue = Catalogue.build([], [])
    assert catalogue.skills == ()
    assert dict(catalogue.by_uri) == {} and dict(catalogue.files) == {} and dict(catalogue.directories) == {}


# --- Directories -----------------------------------------------------------------------------------


def test_one_directory_record_per_directory_of_every_skill() -> None:
    catalogue = Catalogue.build(standard_records(), [])
    assert set(catalogue.directories) == {
        "skill://greetings",
        "skill://team/billing/refunds",
        "skill://team/billing/refunds/templates",
        "skill://team/billing/refunds/assets",
    }
    for uri, record in catalogue.directories.items():
        assert isinstance(record, DirectoryRecord)
        assert record.uri == uri


def test_a_prefix_above_two_skills_is_not_a_directory() -> None:
    catalogue = Catalogue.build([skill_record(("team", "billing", "refunds")), skill_record(("team", "billing", "invoices"))], [])
    for prefix in ("skill://team", "skill://team/billing", "skill://team/billing/"):
        assert prefix not in catalogue.directories
    assert "skill://team/billing/refunds" in catalogue.directories
    assert "skill://team/billing/invoices" in catalogue.directories


def test_a_directory_uri_has_no_trailing_slash() -> None:
    catalogue = Catalogue.build(standard_records(), [])
    assert not [uri for uri in catalogue.directories if uri.endswith("/")]


def test_the_children_are_the_direct_children_sorted_by_name() -> None:
    catalogue = Catalogue.build(standard_records(), [])
    root = "skill://team/billing/refunds"
    assert catalogue.directories[root].children == (
        (f"{root}/SKILL.md", "SKILL.md", "text/markdown", False),
        (f"{root}/assets", "assets", DIR, True),
        (f"{root}/notes.txt", "notes.txt", "text/plain", False),
        (f"{root}/templates", "templates", DIR, True),
    )
    assert catalogue.directories[f"{root}/templates"].children == ((f"{root}/templates/reply.md", "reply.md", "text/markdown", False),)
    assert catalogue.directories[f"{root}/assets"].children == (
        (f"{root}/assets/logo.bin", "logo.bin", "application/octet-stream", False),
    )
    assert catalogue.directories["skill://greetings"].children == (
        ("skill://greetings/SKILL.md", "SKILL.md", "text/markdown", False),
    )


def test_children_are_sorted_by_name_not_by_their_encoded_uri() -> None:
    # Encoded, "é.md" is "%C3%A9.md" and would sort first; by name it sorts last.
    catalogue = Catalogue.build([skill_record(("x",), [["z.md"], ["é.md"]])], [])
    assert [c.name for c in catalogue.directories["skill://x"].children] == ["SKILL.md", "z.md", "é.md"]


def test_children_have_named_fields() -> None:
    child = Catalogue.build(standard_records(), []).directories["skill://greetings"].children[0]
    assert (child.uri, child.name, child.mime, child.is_dir) == ("skill://greetings/SKILL.md", "SKILL.md", "text/markdown", False)


def test_a_directory_lists_a_folder_once_however_many_files_it_holds() -> None:
    others = [["docs", "a.md"], ["docs", "b.md"], ["docs", "deep", "c.md"], ["docs", "deep", "d.md"]]
    catalogue = Catalogue.build([skill_record(("x",), others)], [])
    assert [c[1] for c in catalogue.directories["skill://x"].children] == ["SKILL.md", "docs"]
    assert [c[1] for c in catalogue.directories["skill://x/docs"].children] == ["a.md", "b.md", "deep"]
    assert [c[1] for c in catalogue.directories["skill://x/docs/deep"].children] == ["c.md", "d.md"]
    assert set(catalogue.directories) == {"skill://x", "skill://x/docs", "skill://x/docs/deep"}


def test_a_folder_the_scan_found_is_a_directory_even_with_no_file_in_it() -> None:
    record = skill_record(("x",), [["docs", "a.md"]], dirs=[["docs"], ["empty"], ["docs", "deep"]])
    catalogue = Catalogue.build([record], [])
    assert set(catalogue.directories) == {"skill://x", "skill://x/docs", "skill://x/docs/deep", "skill://x/empty"}
    assert catalogue.directories["skill://x/empty"].children == ()
    assert catalogue.directories["skill://x/docs/deep"].children == ()
    # ... and it is a child of its parent, a folder like any other, in name order.
    assert [(c.name, c.is_dir) for c in catalogue.directories["skill://x"].children] == [
        ("SKILL.md", False),
        ("docs", True),
        ("empty", True),
    ]
    assert catalogue.directories["skill://x/docs"].children[-1] == ("skill://x/docs/deep", "deep", DIR, True)


def test_the_folders_above_a_listed_one_are_directories_too() -> None:
    """A record that names only `a/b/c` still gets `a` and `a/b`: no folder is a child that has no record."""
    catalogue = Catalogue.build([skill_record(("x",), dirs=[["a", "b", "c"]])], [])
    assert set(catalogue.directories) == {"skill://x", "skill://x/a", "skill://x/a/b", "skill://x/a/b/c"}
    assert [c.name for c in catalogue.directories["skill://x/a"].children] == ["b"]
    for directory in catalogue.directories.values():
        for child in directory.children:
            assert child.uri in catalogue.files or child.uri in catalogue.directories


def test_a_folder_that_is_also_a_file_name_is_refused_even_when_it_is_empty() -> None:
    with pytest.raises(SkillsError) as caught:
        Catalogue.build([skill_record(("x",), [["docs"]], dirs=[["docs"]], folder="/one/x")], [])
    assert "skill://x/docs" in caught.value.reason


def test_a_record_with_no_dirs_gives_the_directories_it_always_gave() -> None:
    assert Catalogue.build(standard_records(), []).directories.keys() == {
        "skill://greetings",
        "skill://team/billing/refunds",
        "skill://team/billing/refunds/templates",
        "skill://team/billing/refunds/assets",
    }


def test_dirs_has_a_default_and_is_kept_by_the_sort_of_the_files() -> None:
    plain = skill_record(("x",))
    assert plain.dirs == ()
    kept = Catalogue.build([skill_record(("x",), [["b.md"], ["a.md"]], dirs=[["empty"]])], []).skills[0]
    assert kept.dirs == (("empty",),)
    assert [r.parts for r in kept.files] == [("SKILL.md",), ("a.md",), ("b.md",)]


def test_dirs_are_in_pre_order_without_repeats_whatever_order_a_record_gave_them() -> None:
    """A folder comes before what is in it, and each is there once: the order a hand-made record is in
    does not leak into what the catalogue keeps."""
    given = [["b"], ["a", "z"], ["a"], ["b"], ["a", "m", "q"]]
    kept = Catalogue.build([skill_record(("x",), dirs=given)], []).skills[0]
    assert kept.dirs == (("a",), ("a", "m", "q"), ("a", "z"), ("b",))


def test_names_are_decoded_and_uris_are_encoded() -> None:
    catalogue = Catalogue.build([skill_record(("x",), [["my dir", "café.md"]])], [])
    root = catalogue.directories["skill://x"]
    assert root.children[1] == ("skill://x/my%20dir", "my dir", DIR, True)
    inner = catalogue.directories["skill://x/my%20dir"]
    assert inner.children == (("skill://x/my%20dir/caf%C3%A9.md", "café.md", "text/markdown", False),)


# --- A fresh generation every time -----------------------------------------------------------------


def test_two_builds_have_different_generations() -> None:
    records = standard_records()
    first, second = Catalogue.build(records, []), Catalogue.build(records, [])
    assert first.generation != second.generation
    assert isinstance(first.generation, str) and first.generation
    assert "." not in first.generation and "." not in second.generation


def test_many_builds_never_repeat_a_generation() -> None:
    assert len({Catalogue.build([], []).generation for _ in range(200)}) == 200


# --- Immutability ----------------------------------------------------------------------------------


def test_the_catalogue_and_its_records_are_frozen() -> None:
    catalogue = Catalogue.build(standard_records(), [])
    skill = catalogue.skills[0]
    for target, attribute in [
        (catalogue, "generation"),
        (catalogue, "skills"),
        (skill, "name"),
        (skill.files[0], "size"),
        (next(iter(catalogue.directories.values())), "children"),
    ]:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(target, attribute, None)


def test_the_dictionaries_cannot_be_changed() -> None:
    catalogue = Catalogue.build(standard_records(), [])
    for mapping in (catalogue.by_uri, catalogue.files, catalogue.directories):
        with pytest.raises(TypeError):
            mapping["skill://x"] = None  # type: ignore[index]
        with pytest.raises(TypeError):
            del mapping[next(iter(mapping))]  # type: ignore[attr-defined]


# --- Two things with one URI -----------------------------------------------------------------------


def test_two_skills_with_one_uri_are_refused() -> None:
    first = skill_record(("same",), folder="/one/same")
    second = skill_record(("same",), folder="/two/same")
    with pytest.raises(SkillsError) as caught:
        Catalogue.build([first, second], [])
    assert "skill://same/SKILL.md" in caught.value.reason
    assert caught.value.folder in {"/one/same", "/two/same"}


def test_a_file_and_a_directory_with_one_uri_are_refused() -> None:
    outer = skill_record(("a",), [["b"]], folder="/one/a")  # the file skill://a/b ...
    inner = skill_record(("a", "b"), folder="/two/a/b")  # ... and the folder skill://a/b
    with pytest.raises(SkillsError) as caught:
        Catalogue.build([outer, inner], [])
    assert "skill://a/b" in caught.value.reason


def test_two_directories_with_one_uri_are_refused() -> None:
    outer = skill_record(("a",), [["docs", "x.md"]], folder="/one/a")  # the folder skill://a/docs ...
    inner = skill_record(("a", "docs"), folder="/two/a/docs")  # ... and the skill folder skill://a/docs
    with pytest.raises(SkillsError) as caught:
        Catalogue.build([outer, inner], [])
    assert "skill://a/docs" in caught.value.reason


def test_two_skills_whose_uris_differ_only_in_the_case_of_the_first_segment_are_refused() -> None:
    with pytest.raises(SkillsError) as caught:
        Catalogue.build([skill_record(("Team", "x"), folder="/one"), skill_record(("team", "x"), folder="/two")], [])
    assert caught.value.folder in {"/one", "/two"}
    assert "served twice" in caught.value.reason


def test_a_difference_in_case_is_a_difference_everywhere_but_the_first_segment() -> None:
    catalogue = Catalogue.build(
        [skill_record(("team", "X")), skill_record(("team", "x")), skill_record(("Team", "y")), skill_record(("team", "z"))], []
    )
    assert len(catalogue.skills) == 4


def test_a_file_and_a_folder_with_one_name_in_one_skill_are_refused() -> None:
    with pytest.raises(SkillsError) as caught:
        Catalogue.build([skill_record(("x",), [["docs"], ["docs", "a.md"]], folder="/one/x")], [])
    assert "skill://x/docs" in caught.value.reason
    assert caught.value.folder == "/one/x"


def test_a_skill_inside_another_skills_path_is_fine_when_the_uris_differ() -> None:
    catalogue = Catalogue.build([skill_record(("a",), [["docs", "x.md"]]), skill_record(("a", "other"))], [])
    assert "skill://a/other/SKILL.md" in catalogue.files


# --- Public records and the error ------------------------------------------------------------------


def test_skills_error_names_the_folder_and_the_reason() -> None:
    error = SkillsError("/skills/x", "no SKILL.md")
    assert isinstance(error, ValueError)
    assert (error.folder, error.reason) == ("/skills/x", "no SKILL.md")
    assert str(error) == "/skills/x: no SKILL.md"


def test_skills_error_can_be_raised_and_caught_as_a_value_error() -> None:
    with pytest.raises(ValueError, match=r"^f: r$"):
        raise SkillsError("f", "r")


def test_skills_error_survives_a_pickle_and_a_copy() -> None:
    error = SkillsError("/skills/x", "no SKILL.md")
    for again in (pickle.loads(pickle.dumps(error)), copy.copy(error), copy.deepcopy(error)):
        assert type(again) is SkillsError
        assert (again.folder, again.reason, str(again)) == ("/skills/x", "no SKILL.md", "/skills/x: no SKILL.md")


def test_skill_info_and_left_out_are_frozen_records() -> None:
    info = SkillInfo(name="n", uri="skill://n/SKILL.md", description="d", files=2, size=30)
    left = LeftOutPath(path="team/link", reason="symbolic link")
    assert [f.name for f in dataclasses.fields(info)] == ["name", "uri", "description", "files", "size"]
    assert [f.name for f in dataclasses.fields(left)] == ["path", "reason"]
    for record, attribute in ((info, "name"), (info, "size"), (left, "path"), (left, "reason")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(record, attribute, "x")
    assert info == SkillInfo("n", "skill://n/SKILL.md", "d", 2, 30)
    assert hash(left) == hash(LeftOutPath("team/link", "symbolic link"))


def test_the_record_fields_are_those_of_the_data_model() -> None:
    def names(cls: Any) -> list[str]:
        return [f.name for f in dataclasses.fields(cls)]

    assert names(FileRecord) == ["uri", "parts", "folder", "size", "digest", "mime", "skill"]
    assert names(SkillRecord) == ["name", "path", "uri", "folder", "frontmatter", "files", "dirs"]
    assert names(DirectoryRecord) == ["uri", "children"]
    assert names(Catalogue) == ["generation", "skills", "by_uri", "files", "directories", "left_out"]
