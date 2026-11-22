"""What is wrong with the folders is said at build time, naming the folder (spec 005, story 4, SC-005).

Every case builds a bad tree in `tmp_path` and constructs a `SkillsExtension` from it, as an owner
would. Each must raise a `SkillsError` whose `folder` is the folder at fault and whose `reason` says what
is wrong without quoting the file; a bad setting is a plain `ValueError` instead. Everything here is
invented.
"""

from __future__ import annotations

import errno
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ext_r2c.mcp
import ext_r2c.mcp.skills as skills_package
import pytest
from ext_r2c.mcp import SkillsError
from ext_r2c.mcp.skills import SkillsExtension, _scan
from ext_r2c.mcp.skills._catalogue import SkillsError as CatalogueSkillsError
from skills_fixtures import standard_tree, write_skill

MIB = 1024 * 1024
LIMIT_BYTES = 16 * MIB
CAN_REFUSE_READS = hasattr(os, "geteuid") and os.geteuid() != 0 and sys.platform != "win32"
needs_permissions = pytest.mark.skipif(not CAN_REFUSE_READS, reason="a user that can read everything is not refused")


@dataclass(frozen=True)
class Bad:
    """A bad tree: what to build from, and what the error must say."""

    folders: tuple[Path, ...]
    folder: Path  # what `SkillsError.folder` must be
    reason: str  # a fragment `SkillsError.reason` must hold
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    also: tuple[Path, ...] = ()  # other folders of the owner that the reason may name
    restore: tuple[Path, ...] = ()  # made unreadable: given their permissions back after the test


def real(base: Path) -> Path:
    return Path(os.path.realpath(base))


def build(bad: Bad) -> SkillsError:
    with pytest.raises(SkillsError) as raised:
        SkillsExtension(list(bad.folders), include=bad.include, exclude=bad.exclude)
    return raised.value


def thing(base: Path, text: str | bytes, *, folder: str = "thing") -> Bad:
    """A root with one skill folder `thing` whose `SKILL.md` is `text`; the error is about the folder."""
    root = real(base) / "skills"
    skill = root / folder
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return Bad((root,), skill, "")


def with_reason(bad: Bad, reason: str) -> Bad:
    return Bad(bad.folders, bad.folder, reason, bad.include, bad.exclude, bad.also, bad.restore)


def frontmatter_case(text: str | bytes, reason: str) -> Callable[[Path], Bad]:
    return lambda base: with_reason(thing(base, text), reason)


def field_case(name_line: str, description_line: str, reason: str) -> Callable[[Path], Bad]:
    return frontmatter_case(f"---\n{name_line}{description_line}---\nBody\n", reason)


def bad_name(name: str) -> Callable[[Path], Bad]:
    """A skill in a folder that has the very name its frontmatter gives, so that nothing but the rule
    on names can refuse it (a folder with another name would be refused for that, too)."""
    text = f"---\nname: {name}\ndescription: Does one thing.\n---\nBody\n"
    return lambda base: with_reason(thing(base, text, folder=name), NAME_RULE)


GOOD_NAME = "name: thing\n"
GOOD_DESCRIPTION = "description: Does one thing.\n"
NAME_RULE = "single hyphens"  # only the rule on names says this; "name must be" is also the folder rule
DESCRIPTION_RULE = "description must be"


# --- The roots ------------------------------------------------------------------------------------


def root_missing(base: Path) -> Bad:
    root = real(base) / "nope"
    return Bad((root,), root, "does not exist")


def root_is_a_file(base: Path) -> Bad:
    root = real(base) / "a-file"
    root.write_text("not a folder\n")
    return Bad((root,), root, "is not a directory")


def root_below_a_file(base: Path) -> Bad:
    parent = real(base) / "a-file"
    parent.write_text("not a folder\n")
    return Bad((parent / "skills",), parent / "skills", "does not exist")


def root_unreadable(base: Path) -> Bad:
    root = real(base) / "skills"
    write_skill(root, "alpha")
    os.chmod(root, 0)
    return Bad((root,), root, "cannot be read", restore=(root,))


def a_folder_that_may_hold_skills_is_unreadable(base: Path) -> Bad:
    root = real(base) / "skills"
    write_skill(root, "alpha")
    (root / "team").mkdir()
    os.chmod(root / "team", 0)
    return Bad((root,), root / "team", "cannot be read", restore=(root / "team",))


def a_folder_in_a_skill_is_unreadable(base: Path) -> Bad:
    root = real(base) / "skills"
    skill = write_skill(root, "alpha", files={"assets/logo.bin": b"x"})
    os.chmod(skill / "assets", 0)
    return Bad((root,), skill, "assets cannot be read", restore=(skill / "assets",))


# --- The files ------------------------------------------------------------------------------------


def skill_md_unreadable(base: Path) -> Bad:
    root = real(base) / "skills"
    skill = write_skill(root, "alpha")
    os.chmod(skill / "SKILL.md", 0)
    return Bad((root,), skill, "SKILL.md cannot be read", restore=(skill / "SKILL.md",))


def a_supporting_file_unreadable(base: Path) -> Bad:
    root = real(base) / "skills"
    skill = write_skill(root, "alpha", files={"assets/logo.bin": b"x"})
    os.chmod(skill / "assets" / "logo.bin", 0)
    return Bad((root,), skill, "assets/logo.bin cannot be read", restore=(skill / "assets" / "logo.bin",))


# --- The limits -----------------------------------------------------------------------------------


def too_many_files(base: Path) -> Bad:
    root = real(base) / "skills"
    skill = write_skill(root, "alpha")
    for index in range(512):  # with `SKILL.md` that is 513
        (skill / f"f{index:03d}.txt").write_text("x")
    return Bad((root,), skill, "more than 512 files")


def too_many_bytes(base: Path) -> Bad:
    root = real(base) / "skills"
    skill = write_skill(root, "alpha")
    sparse(skill / "big.bin", LIMIT_BYTES + 1 - (skill / "SKILL.md").stat().st_size)  # one byte over, in all
    return Bad((root,), skill, f"more than {LIMIT_BYTES} bytes")


def sparse(path: Path, size: int) -> None:
    with open(path, "wb") as stream:
        stream.truncate(size)


# --- Sets of skills -------------------------------------------------------------------------------


def duplicate_across_two_roots(base: Path) -> Bad:
    first, second = real(base) / "first", real(base) / "second"
    earlier = write_skill(first, "alpha")
    later = write_skill(second, "alpha")
    return Bad((first, second), later, "served twice", also=(earlier,))


def duplicate_by_case_in_the_first_segment(base: Path) -> Bad:
    root = real(base) / "skills"
    upper = write_skill(root, "Team/x-skill")
    lower = write_skill(root, "team/x-skill")
    if (root / "team").samefile(root / "Team"):
        pytest.skip("this file system does not tell `Team` from `team`")
    return Bad((root,), lower, "served twice", also=(upper,))


def no_skill_under_the_root(base: Path) -> Bad:
    root = real(base) / "skills"
    (root / "just-a-folder").mkdir(parents=True)
    (root / "just-a-folder" / "notes.txt").write_text("not a skill\n")
    return Bad((root,), root, "no skill")


def nothing_left_after_an_include(base: Path) -> Bad:
    root = standard_tree(real(base)).root
    return Bad((root,), root, "include", include=("zz-*",))


def nothing_left_after_an_exclude(base: Path) -> Bad:
    root = standard_tree(real(base)).root
    return Bad((root,), root, "exclude", exclude=("*",))


CASES: dict[str, Callable[[Path], Bad]] = {
    # roots
    "root missing": root_missing,
    "root is a file": root_is_a_file,
    "root below a file": root_below_a_file,
    # frontmatter
    "no frontmatter": frontmatter_case("Just text.\n", "missing"),
    "frontmatter not closed": frontmatter_case("---\nname: thing\ndescription: x\n", "unclosed"),
    "frontmatter YAML error": frontmatter_case("---\nname: [unclosed\ndescription: x\n---\n", "syntax error"),
    "frontmatter duplicate key": frontmatter_case("---\nname: thing\nname: thing\ndescription: x\n---\n", "duplicate key"),
    "frontmatter alias": frontmatter_case("---\nname: thing\ndescription: &a x\nextra: *a\n---\n", "anchor or alias"),
    "frontmatter unknown tag": frontmatter_case("---\nname: thing\ndescription: !!python/object:os.system x\n---\n", "unknown tag"),
    "frontmatter over 64 KiB": frontmatter_case(
        "---\nname: thing\ndescription: x\nbig: " + "a" * 70_000 + "\n---\n", "too large"
    ),
    "frontmatter not a mapping": frontmatter_case("---\n- a\n- b\n---\n", "not a mapping"),
    "SKILL.md not UTF-8": frontmatter_case(b"---\nname: thing\ndescription: \xff\n---\n", "not utf-8"),
    # name
    "name missing": field_case("", GOOD_DESCRIPTION, "no name"),
    "name not a string": field_case("name: 7\n", GOOD_DESCRIPTION, "name is not a string"),
    "name empty": field_case('name: ""\n', GOOD_DESCRIPTION, NAME_RULE),
    "name of 65 characters": bad_name("a" * 65),
    "name in capitals": bad_name("Thing"),
    "name with a double hyphen": bad_name("a--b"),
    "name with a leading hyphen": bad_name("-thing"),
    "name with a trailing hyphen": bad_name("thing-"),
    "name not ASCII": bad_name("café"),
    "name with a space": bad_name("a b"),
    "name that is only hyphens": bad_name("---"),
    "name with a good start and a bad end": bad_name("thing-Two"),
    "name with an underscore": bad_name("a_b"),
    "name not the folder name": field_case("name: another-name\n", GOOD_DESCRIPTION, "same as the name of the folder"),
    # description
    "description missing": field_case(GOOD_NAME, "", "no description"),
    "description not a string": field_case(GOOD_NAME, "description: 7\n", "description is not a string"),
    "description empty": field_case(GOOD_NAME, 'description: ""\n', DESCRIPTION_RULE),
    "description of 1025 characters": field_case(GOOD_NAME, f"description: {'d' * 1025}\n", DESCRIPTION_RULE),
    # limits
    "513 files": too_many_files,
    "one byte over 16 MiB": too_many_bytes,
    # sets
    "the same URI in two roots": duplicate_across_two_roots,
    "the same URI but for the case of the first segment": duplicate_by_case_in_the_first_segment,
    "no skill under the root": no_skill_under_the_root,
    "nothing left after an include": nothing_left_after_an_include,
    "nothing left after an exclude": nothing_left_after_an_exclude,
    # what cannot be read
    "root unreadable": root_unreadable,
    "a folder that may hold skills unreadable": a_folder_that_may_hold_skills_is_unreadable,
    "a folder in a skill unreadable": a_folder_in_a_skill_is_unreadable,
    "SKILL.md unreadable": skill_md_unreadable,
    "a supporting file unreadable": a_supporting_file_unreadable,
}
UNREADABLE = {
    "root unreadable",
    "a folder that may hold skills unreadable",
    "a folder in a skill unreadable",
    "SKILL.md unreadable",
    "a supporting file unreadable",
}


def cases() -> list[Any]:
    return [
        pytest.param(make, id=name, marks=[needs_permissions] if name in UNREADABLE else [])
        for name, make in CASES.items()
    ]


# --- The table ------------------------------------------------------------------------------------


class TestEachFaultIsNamed:
    def test_there_are_at_least_twenty_cases(self) -> None:
        assert len(CASES) >= 20

    @pytest.mark.parametrize("make", cases())
    def test_a_skills_error_names_the_folder_and_says_what_is_wrong(self, tmp_path: Path, make: Callable[[Path], Bad]) -> None:
        bad = make(tmp_path)
        try:
            error = build(bad)
        finally:
            for path in bad.restore:
                os.chmod(path, 0o755)
        assert type(error) is SkillsError
        assert error.folder == str(bad.folder)
        assert error.reason and bad.reason in error.reason, error.reason
        assert str(error) == f"{error.folder}: {error.reason}"
        if "cannot be read" in bad.reason:  # the system's own words and nothing after them, not `[Errno 13] ...: '/a/path'`
            assert error.reason.endswith(f": {os.strerror(errno.EACCES)}"), error.reason
            assert "Errno" not in error.reason
        # The reason holds no host path but the folders the owner gave.
        leftover = error.reason
        for folder in (bad.folder, *bad.also, *bad.folders):
            leftover = leftover.replace(str(folder), "")
        assert str(real(tmp_path)) not in leftover, error.reason
        if bad.include or bad.exclude:  # the filters are named when they are what is wrong
            assert all(pattern in error.reason for pattern in (*bad.include, *bad.exclude))
        for folder in bad.also:  # a duplicate names both folders
            assert str(folder) in error.reason

    @pytest.mark.parametrize(
        "text",
        [
            "---\nname: thing\ndescription: [MARKER-7731\n---\n",
            "---\nname: thing\ndescription: x\nMARKER-7731: 1\nMARKER-7731: 2\n---\n",
            "---\nname: thing\ndescription: !MARKER-7731 x\n---\n",
            "---\nname: MARKER-7731\ndescription: x\n---\n",
            "---\nname: thing\ndescription: x\nbig: MARKER-7731\n" + "a" * 70_000 + "\n---\n",
        ],
        ids=["syntax error", "duplicate key", "unknown tag", "name that is not allowed", "too large"],
    )
    def test_a_reason_never_quotes_the_file(self, tmp_path: Path, text: str) -> None:
        error = build(thing(tmp_path, text))
        assert "MARKER-7731" not in error.reason and "MARKER-7731" not in str(error)

    def test_a_bad_skill_fails_the_whole_build_even_beside_good_ones(self, tmp_path: Path) -> None:
        """There is no extension to serve the good one: nothing is half built."""
        root = real(tmp_path) / "skills"
        write_skill(root, "good-one")
        (root / "bad-one").mkdir()
        (root / "bad-one" / "SKILL.md").write_text("Just text.\n")
        assert build(Bad((root,), root / "bad-one", "")).folder == str(root / "bad-one")

    def test_nothing_left_across_two_roots_names_both_folders(self, tmp_path: Path) -> None:
        first, second = standard_tree(real(tmp_path) / "one").root, standard_tree(real(tmp_path) / "two").root
        error = build(Bad((first, second), first, "", exclude=("*",)))
        assert error.folder == f"{first}, {second}" and "exclude" in error.reason

    def test_a_root_that_holds_no_skill_is_fine_beside_one_that_does(self, tmp_path: Path) -> None:
        """Nothing at all to serve is the error; one empty folder among others is not."""
        empty = real(tmp_path) / "empty"
        empty.mkdir()
        good = standard_tree(real(tmp_path)).root
        assert [s.name for s in SkillsExtension([empty, good]).skills] == ["greetings", "pdf-notes", "refunds"]

    def test_a_root_error_names_the_folder_as_given_and_one_below_it_names_where_it_is(self, tmp_path: Path) -> None:
        target, link = real(tmp_path) / "target", real(tmp_path) / "link"
        target.mkdir()
        link.symlink_to(target, target_is_directory=True)
        assert build(Bad((link,), link, "")).folder == str(link)  # no skill found: the root, as the owner gave it
        (write_skill(target, "alpha") / "SKILL.md").write_text("Just text.\n")
        assert build(Bad((link,), link, "")).folder == str(target / "alpha")  # a skill: where the scan found it

    @needs_permissions
    def test_an_unreadable_root_is_named_as_given_even_when_it_is_a_link(self, tmp_path: Path) -> None:
        target, link = real(tmp_path) / "target", real(tmp_path) / "link"
        write_skill(target, "alpha")
        link.symlink_to(target, target_is_directory=True)
        os.chmod(target, 0)
        try:
            error = build(Bad((link,), link, ""))
        finally:
            os.chmod(target, 0o755)
        assert error.folder == str(link) and error.reason == f"cannot be read: {os.strerror(errno.EACCES)}"


class TestTheEdgesOfTheFields:
    def test_the_longest_name_and_both_ends_of_the_description_are_allowed(self, tmp_path: Path) -> None:
        root = real(tmp_path) / "skills"
        longest = "a" * 64
        (root / longest).mkdir(parents=True)
        (root / longest / "SKILL.md").write_text(f"---\nname: {longest}\ndescription: {'d' * 1024}\n---\n")
        write_skill(root, "z", description="d")
        for name in ("a1-2b", "ab-cd-ef", "x9"):
            write_skill(root, name)
        assert {s.name for s in SkillsExtension(root).skills} == {longest, "a1-2b", "ab-cd-ef", "x9", "z"}


class TestTheLimitsAreOnTheirEdge:
    def test_512_files_pass_and_513_do_not(self, tmp_path: Path) -> None:
        root = real(tmp_path) / "skills"
        skill = write_skill(root, "alpha")
        for index in range(511):  # with `SKILL.md` that is 512
            (skill / f"f{index:03d}.txt").write_text("x")
        assert SkillsExtension(root).skills[0].files == 512
        (skill / "one-more.txt").write_text("x")
        assert build(Bad((root,), skill, "")).reason.startswith("has more than 512 files")

    def test_the_walk_stops_at_the_first_file_over_the_limit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A stray `SKILL.md` at the top of a big folder must not make the build stat every file in it."""
        root = real(tmp_path) / "skills"
        skill = write_skill(root, "alpha")
        for index in range(600):
            (skill / f"f{index:03d}.txt").write_text("x")
        listed: list[Any] = []
        walk = _scan._files

        def spy(*args: Any, **kwargs: Any) -> Any:
            for item in walk(*args, **kwargs):
                listed.append(item)
                yield item

        monkeypatch.setattr(_scan, "_files", spy)
        assert build(Bad((root,), skill, "")).reason.startswith("has more than 512 files")
        assert len(listed) == 513  # the 513th said no; the other 88 files were never looked at

    def test_exactly_16_mebibytes_pass_and_one_byte_more_does_not(self, tmp_path: Path) -> None:
        root = real(tmp_path) / "skills"
        skill = write_skill(root, "alpha")
        head = (skill / "SKILL.md").stat().st_size
        sparse(skill / "big.bin", LIMIT_BYTES - head)
        (info,) = SkillsExtension(root).skills
        assert info.size == LIMIT_BYTES and info.files == 2
        with open(skill / "big.bin", "ab") as stream:
            stream.write(b"x")
        assert LIMIT_BYTES + 1 == (skill / "big.bin").stat().st_size + head
        assert f"more than {LIMIT_BYTES} bytes" in build(Bad((root,), skill, "")).reason

    def test_a_skill_md_alone_may_fill_the_limit_and_not_pass_it(self, tmp_path: Path) -> None:
        root = real(tmp_path) / "skills"
        skill = root / "alpha"
        skill.mkdir(parents=True)
        head = b"---\nname: alpha\ndescription: Fills the limit.\n---\n"
        (skill / "SKILL.md").write_bytes(head + b"x" * (LIMIT_BYTES - len(head)))
        (info,) = SkillsExtension(root).skills
        assert (info.files, info.size) == (1, LIMIT_BYTES)
        with open(skill / "SKILL.md", "ab") as stream:
            stream.write(b"x")
        assert f"more than {LIMIT_BYTES} bytes" in build(Bad((root,), skill, "")).reason
        # Over the limit it is refused for its size, before anyone parses it: here the size is not
        # the only thing wrong with it, and it is the thing that is said.
        (skill / "SKILL.md").write_bytes(b"No frontmatter here.\n" + b"x" * LIMIT_BYTES)
        assert f"more than {LIMIT_BYTES} bytes" in build(Bad((root,), skill, "")).reason

    @pytest.mark.parametrize(("extra", "fits"), [(0, True), (1, False)], ids=["fills it exactly", "one byte over"])
    def test_a_file_that_grows_to_the_limit_is_served_and_one_byte_more_is_not(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: int, fits: bool
    ) -> None:
        root = real(tmp_path) / "skills"
        skill = write_skill(root, "alpha", files={"grows.bin": b"x" * 1024})
        target = LIMIT_BYTES - (skill / "SKILL.md").stat().st_size + extra  # in all: the limit, plus `extra`
        original = _scan.read_bytes

        def grow_then_read(folder: str, parts: tuple[str, ...], limit: int | None = None) -> bytes:
            if parts == ("grows.bin",):
                sparse(skill / "grows.bin", target)
            return original(folder, parts, limit)

        monkeypatch.setattr(_scan, "read_bytes", grow_then_read)
        if fits:
            assert SkillsExtension(root).skills[0].size == LIMIT_BYTES
        else:
            assert f"more than {LIMIT_BYTES} bytes" in build(Bad((root,), skill, "")).reason

    def test_two_files_that_grow_are_counted_together(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each fits in what is left when it is read; both together do not."""
        root = real(tmp_path) / "skills"
        skill = write_skill(root, "alpha", files={"a.bin": b"x" * 1024, "b.bin": b"x" * 1024})
        original = _scan.read_bytes

        def grow_then_read(folder: str, parts: tuple[str, ...], limit: int | None = None) -> bytes:
            if parts in (("a.bin",), ("b.bin",)):
                sparse(skill / parts[0], 9 * MIB)
            return original(folder, parts, limit)

        monkeypatch.setattr(_scan, "read_bytes", grow_then_read)
        assert f"more than {LIMIT_BYTES} bytes" in build(Bad((root,), skill, "")).reason

    @pytest.mark.parametrize("which", ["files", "bytes"])
    def test_a_skill_over_a_limit_is_refused_before_any_file_but_SKILL_md_is_read(
        self, tmp_path: Path, which: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad = (too_many_files if which == "files" else too_many_bytes)(tmp_path)
        reads: list[tuple[str, ...]] = []
        original = _scan.read_bytes

        def spy(folder: str, parts: tuple[str, ...], limit: int | None = None) -> bytes:
            reads.append(tuple(parts))
            return original(folder, parts, limit)

        monkeypatch.setattr(_scan, "read_bytes", spy)
        assert build(bad).folder == str(bad.folder)
        assert reads == [("SKILL.md",)]  # the frontmatter is needed to name the skill; nothing is hashed

    def test_a_file_that_grows_while_the_scan_runs_cannot_push_it_past_the_limit_unseen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`stat` said 1 KiB; by the time the file is read it holds 20 MiB. The read is bounded by the limit."""
        root = real(tmp_path) / "skills"
        skill = write_skill(root, "alpha", files={"grows.bin": b"x" * 1024})
        original = _scan.read_bytes

        def grow_then_read(folder: str, parts: tuple[str, ...], limit: int | None = None) -> bytes:
            if parts == ("grows.bin",):
                sparse(skill / "grows.bin", 20 * MIB)
                assert limit is not None and limit <= LIMIT_BYTES + 1  # a bound, not "everything"
            return original(folder, parts, limit)

        monkeypatch.setattr(_scan, "read_bytes", grow_then_read)
        assert "bytes" in build(Bad((root,), skill, "")).reason


# --- Settings -------------------------------------------------------------------------------------


class TestSettings:
    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("ttl_ms", -1),
            ("ttl_ms", "300"),
            ("ttl_ms", True),
            ("ttl_ms", 1.5),
            ("ttl_ms", None),
            ("page_size", 0),
            ("page_size", -1),
            ("page_size", True),
            ("page_size", 1.5),
            ("page_size", "25"),
            ("page_size", None),
            ("directory_read", "yes"),
            ("directory_read", 1),
            ("directory_read", 0),
            ("directory_read", None),
            ("cache_scope", "shared"),
            ("cache_scope", None),
            ("cache_scope", "Private"),
            ("include", "a"),
            ("include", None),
            ("include", [""]),
            ("include", [1]),
            ("exclude", "a"),
            ("exclude", [""]),
            ("exclude", [None]),
            ("folders", []),
            ("folders", ""),
            ("folders", [""]),
            ("folders", [5]),
            ("folders", None),
            ("folders", 5),
            ("folders", "a\0b"),
        ],
    )
    def test_a_bad_setting_is_a_value_error_naming_it_and_not_a_skills_error(
        self, tmp_path: Path, name: str, value: Any
    ) -> None:
        kwargs: dict[str, Any] = {"folders": real(tmp_path) / "does-not-exist"}  # never looked at: settings come first
        if name == "folders":
            kwargs["folders"] = value
        else:
            kwargs[name] = value
        with pytest.raises(ValueError) as raised:
            SkillsExtension(**kwargs)
        assert not isinstance(raised.value, SkillsError)
        assert name in str(raised.value)

    def test_the_good_edges_are_accepted(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        SkillsExtension(root, ttl_ms=0, cache_scope="public", include=("*",), exclude=[])
        SkillsExtension(root, page_size=1, directory_read=False)
        SkillsExtension(root, page_size=10**9, directory_read=True)  # as many as you like on a page
        SkillsExtension(str(root))

    def test_a_str_a_path_like_and_a_list_are_each_accepted_as_folders(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        other = real(tmp_path) / "other"
        write_skill(other, "zulu")
        expected = ["greetings", "pdf-notes", "refunds"]
        assert [s.name for s in SkillsExtension(str(tree.root)).skills] == expected
        assert [s.name for s in SkillsExtension(tree.root).skills] == expected
        assert [s.name for s in SkillsExtension([tree.root, str(other)]).skills] == [*expected, "zulu"]
        assert [s.name for s in SkillsExtension((other,)).skills] == ["zulu"]

    def test_a_bare_string_is_one_folder_and_not_a_list_of_characters(self, tmp_path: Path) -> None:
        root = real(tmp_path) / "x"
        write_skill(root, "alpha")
        assert [s.name for s in SkillsExtension(str(root)).skills] == ["alpha"]


# --- Names ----------------------------------------------------------------------------------------


class TestTheName:
    def test_skills_error_is_exported_with_the_other_names(self) -> None:
        assert ext_r2c.mcp.SkillsError is skills_package.SkillsError is CatalogueSkillsError
        assert "SkillsError" in ext_r2c.mcp.__all__ and "SkillsError" in skills_package.__all__
        assert issubclass(SkillsError, ValueError)
