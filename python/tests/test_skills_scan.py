"""Finding and describing skills (spec 005, stories 1 and 4, research R6): a folder tree goes in, a
`Catalogue` comes out. The folders are built in `tmp_path` (`skills_fixtures.py`), and what a skill
must hold is worked out here from the disk with `hashlib` and `stat`, never with package code.

First cut (phase 3): the scan leaves out what it must not serve without saying so; reporting it,
the build errors and the filters come in later phases."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from ext_r2c.mcp.skills._catalogue import Catalogue, SkillRecord, SkillsError
from ext_r2c.mcp.skills._scan import scan_roots
from skills_fixtures import add_fifo, add_symlink, outside_secret, standard_tree, write_skill


def served(cat: Catalogue) -> dict[str, SkillRecord]:
    return {skill.uri: skill for skill in cat.skills}


def rel(parts: tuple[str, ...]) -> str:
    return "/".join(parts)


# --- What is found --------------------------------------------------------------------------------


class TestFinding:
    def test_the_fixture_tree_gives_three_skills_sorted_by_uri(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        cat = scan_roots([tree.root], (), ())
        assert [skill.uri for skill in cat.skills] == [
            "skill://greetings/SKILL.md",
            "skill://pdf-notes/SKILL.md",
            "skill://team/billing/refunds/SKILL.md",
        ]
        assert [skill.path for skill in cat.skills] == [tuple(n.split("/")) for n in tree.names]
        for skill in cat.skills:
            assert skill.name == skill.path[-1], skill.path

    def test_a_nested_skill_path_is_the_path_below_its_root(self, tmp_path: Path) -> None:
        """Story 4, scenario 3: `skills/team/billing/refunds` under the root `skills` is
        `skill://team/billing/refunds/SKILL.md`; the root's own name is not in it."""
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        refunds = served(cat)["skill://team/billing/refunds/SKILL.md"]
        assert refunds.path == ("team", "billing", "refunds")
        assert "skills" not in refunds.uri

    def test_a_prefix_folder_is_never_a_skill(self, tmp_path: Path) -> None:
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        assert "skill://team/SKILL.md" not in cat.by_uri
        assert "skill://team/billing/SKILL.md" not in cat.by_uri
        assert not any(uri.startswith("skill://team/SKILL") for uri in cat.files)

    def test_the_nearest_skill_md_wins(self, tmp_path: Path) -> None:
        """Story 4, scenario 4: `refunds/examples/SKILL.md` is a file of `refunds`, listed in its
        `resources`; `examples` is not scanned for skills."""
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        refunds = served(cat)["skill://team/billing/refunds/SKILL.md"]
        nested = "skill://team/billing/refunds/examples/SKILL.md"
        assert nested in {f.uri for f in refunds.files}
        assert nested in cat.files and cat.files[nested].skill == refunds.uri
        assert nested not in cat.by_uri
        assert len(cat.skills) == 3
        assert not any("examples" in skill.path for skill in cat.skills)

    def test_a_skill_folder_directly_under_a_folder_without_skill_md_starts_at_the_root(self, tmp_path: Path) -> None:
        root = tmp_path / "library"
        write_skill(root, "alpha")
        cat = scan_roots([root], (), ())
        assert [skill.path for skill in cat.skills] == [("alpha",)]
        assert cat.skills[0].uri == "skill://alpha/SKILL.md"

    def test_a_root_that_holds_a_skill_md_is_one_skill_named_by_its_own_folder(self, tmp_path: Path) -> None:
        folder = write_skill(tmp_path, "solo-skill", files={"notes/a.txt": "a\n"})
        cat = scan_roots([folder], (), ())
        assert [skill.path for skill in cat.skills] == [("solo-skill",)]
        assert sorted(rel(f.parts) for f in cat.skills[0].files) == ["SKILL.md", "notes/a.txt"]
        assert cat.files["skill://solo-skill/notes/a.txt"].parts == ("notes", "a.txt")

    def test_several_roots_are_all_scanned_and_the_catalogue_is_sorted_by_uri(self, tmp_path: Path) -> None:
        first, second = tmp_path / "first", tmp_path / "second"
        write_skill(first, "zulu")
        write_skill(first, "kilo")
        write_skill(second, "alpha")
        write_skill(second, "team/mike")
        for order in ([first, second], [second, first]):
            cat = scan_roots(order, (), ())
            assert [s.uri for s in cat.skills] == [
                "skill://alpha/SKILL.md",
                "skill://kilo/SKILL.md",
                "skill://team/mike/SKILL.md",
                "skill://zulu/SKILL.md",
            ]

    def test_a_root_given_as_a_link_is_followed_once_and_its_skills_record_the_real_folder(self, tmp_path: Path) -> None:
        """The owner's own path may be a link (R6): it is resolved once, at the root."""
        tree = standard_tree(tmp_path)
        link = add_symlink(tmp_path / "alias", tree.root, directory=True)
        cat = scan_roots([link], (), ())
        assert [s.uri for s in cat.skills] == [
            "skill://greetings/SKILL.md",
            "skill://pdf-notes/SKILL.md",
            "skill://team/billing/refunds/SKILL.md",
        ]
        real = Path(os.path.realpath(tree.root))
        assert {skill.folder for skill in cat.skills} == {str(real / name) for name in tree.names}


# --- What a skill holds ---------------------------------------------------------------------------


class TestDescribing:
    def test_every_file_is_served_once_with_its_size_and_digest(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        cat = scan_roots([tree.root], (), ())
        expected = tree.expected()
        every = [f for skill in cat.skills for f in skill.files]
        assert sorted(f.uri for f in every) == sorted(expected)  # each file once, nothing more
        assert set(cat.files) == set(expected)
        for record in every:
            data = expected[record.uri]
            assert record.size == len(data), record.uri
            assert record.digest == "sha256:" + hashlib.sha256(data).hexdigest(), record.uri
            assert len(record.digest) == len("sha256:") + 64 and record.digest == record.digest.lower()

    def test_a_size_and_digest_come_from_the_disk_not_from_the_name(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        cat = scan_roots([tree.root], (), ())
        logo = cat.files["skill://pdf-notes/assets/logo.bin"]
        on_disk = tree.root / "pdf-notes" / "assets" / "logo.bin"
        assert logo.size == on_disk.stat().st_size == 9
        assert logo.digest == "sha256:" + hashlib.sha256(on_disk.read_bytes()).hexdigest()

    def test_skill_md_is_listed_exactly_once_and_files_are_sorted_by_relative_path(self, tmp_path: Path) -> None:
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        for skill in cat.skills:
            paths = [rel(f.parts) for f in skill.files]
            assert paths.count("SKILL.md") == 1, skill.uri
            assert paths == sorted(paths), skill.uri
            assert [f.uri for f in skill.files].count(skill.uri) == 1
        refunds = served(cat)["skill://team/billing/refunds/SKILL.md"]
        assert [rel(f.parts) for f in refunds.files] == [
            "SKILL.md",
            "examples/SKILL.md",
            "notes.txt",
            "templates/reply.md",
        ]

    def test_a_file_record_knows_where_it_is_and_which_skill_it_belongs_to(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        cat = scan_roots([tree.root], (), ())
        real = Path(os.path.realpath(tree.root))
        record = cat.files["skill://team/billing/refunds/templates/reply.md"]
        assert record.parts == ("templates", "reply.md")
        assert record.folder == str(real / "team" / "billing" / "refunds")
        assert record.skill == "skill://team/billing/refunds/SKILL.md"
        assert record.mime == "text/markdown"

    def test_the_content_type_follows_the_extension_and_skill_md_is_markdown(self, tmp_path: Path) -> None:
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        mime = {uri: record.mime for uri, record in cat.files.items()}
        assert mime["skill://pdf-notes/SKILL.md"] == "text/markdown"
        assert mime["skill://pdf-notes/reference.md"] == "text/markdown"
        assert mime["skill://pdf-notes/scripts/run.sh"] == "text/x-shellscript"
        assert mime["skill://pdf-notes/assets/logo.bin"] == "application/octet-stream"
        assert mime["skill://team/billing/refunds/notes.txt"] == "text/plain"

    def test_the_frontmatter_passes_through_unchanged(self, tmp_path: Path) -> None:
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        assert served(cat)["skill://team/billing/refunds/SKILL.md"].frontmatter == {
            "name": "refunds",
            "description": "Handles refund requests.",
            "license": "MIT",
            "metadata": {"owner": "billing", "tags": ["refunds", "support"]},
        }
        assert served(cat)["skill://pdf-notes/SKILL.md"].frontmatter == {
            "name": "pdf-notes",
            "description": "Takes notes from a PDF.",
        }

    def test_a_non_ascii_file_name_gets_an_ascii_uri(self, tmp_path: Path) -> None:
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        uri = "skill://greetings/caf%C3%A9.md"
        assert uri in cat.files and cat.files[uri].parts == ("café.md",)
        assert all(uri.isascii() for uri in cat.files)

    def test_the_directories_of_every_skill_are_derived_from_its_files(self, tmp_path: Path) -> None:
        cat = scan_roots([standard_tree(tmp_path).root], (), ())
        assert set(cat.directories) == {
            "skill://greetings",
            "skill://pdf-notes",
            "skill://pdf-notes/assets",
            "skill://pdf-notes/scripts",
            "skill://team/billing/refunds",
            "skill://team/billing/refunds/examples",
            "skill://team/billing/refunds/templates",
        }


# --- What is not served ---------------------------------------------------------------------------


class TestLeftOut:
    def test_hidden_entries_links_and_pipes_are_not_served(self, tmp_path: Path) -> None:
        """They are absent from the served files (`test_skills_safety.py` checks what is reported)."""
        tree = standard_tree(tmp_path)
        before = tree.expected()
        secret = outside_secret(tmp_path)
        skill = tree.root / "pdf-notes"
        (skill / ".hidden.txt").write_text("hidden\n")
        (skill / ".cache").mkdir()
        (skill / ".cache" / "inside.txt").write_text("inside a hidden folder\n")
        (skill / "assets" / ".DS_Store").write_bytes(b"\x00")
        add_symlink(skill / "leak.txt", secret)
        add_symlink(skill / "leak-dir", secret.parent, directory=True)
        add_symlink(skill / "assets" / "also-leak.txt", "../../../outside/secret.txt")
        add_fifo(skill / "pipe")
        add_fifo(skill / "assets" / "pipe2")

        cat = scan_roots([tree.root], (), ())
        assert set(cat.files) == set(before)
        assert {uri for uri in cat.files if "leak" in uri or "pipe" in uri or "hidden" in uri or ".cache" in uri} == set()

    def test_a_hidden_folder_or_a_link_is_not_a_skill(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        write_skill(tree.root, ".hidden-skill")
        write_skill(tree.root, "team/.also-hidden")
        add_symlink(tree.root / "linked-skill", tree.root / "pdf-notes", directory=True)
        add_symlink(tree.root / "team" / "linked-too", tree.root / "greetings", directory=True)
        cat = scan_roots([tree.root], (), ())
        assert [skill.path for skill in cat.skills] == [tuple(n.split("/")) for n in tree.names]
        assert set(cat.files) == set(tree.expected())

    def test_only_a_regular_file_named_exactly_skill_md_makes_a_skill(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "real-one")
        for folder, name in (("lower", "skill.md"), ("mixed", "Skill.md"), ("readme", "SKILL.md.bak")):
            (root / folder).mkdir(parents=True)
            (root / folder / name).write_text("---\nname: x\ndescription: y\n---\n")
        (root / "a-folder" / "SKILL.md").mkdir(parents=True)  # a folder with that name is not a file
        add_fifo(root / "a-pipe" / "SKILL.md")  # nor is a named pipe, and it is never opened
        cat = scan_roots([root], (), ())
        assert [skill.path for skill in cat.skills] == [("real-one",)]

    def test_a_skill_md_that_is_a_link_does_not_make_a_skill(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "real-one")
        (root / "fake").mkdir()
        add_symlink(root / "fake" / "SKILL.md", root / "real-one" / "SKILL.md")
        cat = scan_roots([root], (), ())
        assert [skill.path for skill in cat.skills] == [("real-one",)]


# --- include and exclude --------------------------------------------------------------------------


class TestFilters:
    """`scan_roots` takes the filters (D4), so the scan applies them: glob patterns, case-sensitive,
    matched against the last segment of the skill path; exclude wins; filters first, checks after
    (R6). What happens when they leave nothing, and the settings' own checks, are phase 6."""

    @staticmethod
    def names(cat: Catalogue) -> list[str]:
        return [skill.name for skill in cat.skills]

    def test_include_keeps_only_the_matching_skills(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        assert self.names(scan_roots([root], ["pdf-*"], ())) == ["pdf-notes"]
        assert self.names(scan_roots([root], ["greetings", "refunds"], ())) == ["greetings", "refunds"]

    def test_exclude_drops_the_matching_skills(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        assert self.names(scan_roots([root], (), ["pdf-*"])) == ["greetings", "refunds"]
        assert self.names(scan_roots([root], (), ["pdf-*", "greetings"])) == ["refunds"]  # any pattern is enough

    def test_exclude_wins_over_include(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        assert self.names(scan_roots([root], ["*"], ["greetings"])) == ["pdf-notes", "refunds"]
        assert self.names(scan_roots([root], ["greetings", "pdf-notes"], ["greetings"])) == ["pdf-notes"]

    def test_patterns_are_case_sensitive(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        assert self.names(scan_roots([root], (), ["GREETINGS", "Pdf-*"])) == ["greetings", "pdf-notes", "refunds"]
        assert self.names(scan_roots([root], ["Greetings", "pdf-notes"], ())) == ["pdf-notes"]

    def test_patterns_see_the_last_segment_only(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        assert self.names(scan_roots([root], ["team", "pdf-notes"], ())) == ["pdf-notes"]  # a prefix is not the skill
        assert self.names(scan_roots([root], ["refunds"], ())) == ["refunds"]
        assert self.names(scan_roots([root], (), ["billing", "team"])) == ["greetings", "pdf-notes", "refunds"]

    def test_a_filtered_out_skill_is_never_read_so_a_broken_one_does_not_stop_the_build(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "good-one")
        broken = root / "draft-broken"
        broken.mkdir(parents=True)
        (broken / "SKILL.md").write_text("---\nname: [unclosed\n---\n")
        (broken / "big.bin").write_bytes(b"x" * 10)
        assert self.names(scan_roots([root], (), ["draft-*"])) == ["good-one"]
        assert self.names(scan_roots([root], ["good-*"], ())) == ["good-one"]
        with pytest.raises(SkillsError):
            scan_roots([root], (), ())

    def test_what_a_filtered_out_skill_holds_is_not_scanned_for_skills(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        write_skill(root, "team/billing/refunds/inner-skill")
        cat = scan_roots([root], (), ["refunds"])
        assert self.names(cat) == ["greetings", "pdf-notes"]
        assert not any("inner-skill" in uri for uri in cat.files)
        whole = scan_roots([root], (), ())
        assert "skill://team/billing/refunds/inner-skill/SKILL.md" in whole.files  # a file of refunds
        assert "skill://team/billing/refunds/inner-skill/SKILL.md" not in whole.by_uri


# --- The first cut's errors -----------------------------------------------------------------------


class TestFirstCutErrors:
    """The full list of build errors is phase 6; these are the ones the first cut already has to
    raise, so that no half-described skill is ever served."""

    def test_unreadable_frontmatter_names_the_skill_folder(self, tmp_path: Path) -> None:
        folder = tmp_path / "skills" / "broken"
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("no frontmatter here\n")
        with pytest.raises(SkillsError) as raised:
            scan_roots([tmp_path / "skills"], (), ())
        assert raised.value.folder == str(Path(os.path.realpath(folder)))
        assert "frontmatter" in raised.value.reason and "missing" in raised.value.reason

    @pytest.mark.parametrize("field", ["name", "description"])
    def test_a_missing_name_or_description_is_an_error(self, tmp_path: Path, field: str) -> None:
        folder = tmp_path / "skills" / "thing"
        folder.mkdir(parents=True)
        other = "description: Fine.\n" if field == "name" else "name: thing\n"
        (folder / "SKILL.md").write_text(f"---\n{other}---\nBody\n")
        with pytest.raises(SkillsError) as raised:
            scan_roots([tmp_path / "skills"], (), ())
        assert raised.value.folder == str(Path(os.path.realpath(folder)))
        assert field in raised.value.reason

    @pytest.mark.parametrize("field", ["name", "description"])
    def test_a_name_or_description_that_is_not_a_string_is_an_error(self, tmp_path: Path, field: str) -> None:
        folder = tmp_path / "skills" / "thing"
        folder.mkdir(parents=True)
        name, description = ("name: 7\n", "description: Fine.\n") if field == "name" else ("name: thing\n", "description: 7\n")
        (folder / "SKILL.md").write_text(f"---\n{name}{description}---\nBody\n")
        with pytest.raises(SkillsError) as raised:
            scan_roots([tmp_path / "skills"], (), ())
        assert field in raised.value.reason
