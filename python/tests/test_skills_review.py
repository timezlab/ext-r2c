"""What the outside review of spec 005 found on the server side (research R17), each as a test.

Part A: a scan has bounds that do not depend on the owner's tree (depth, folders). Part B: a name
that could forge a log line or reorder text is not served, and is reported with its bytes escaped.
Part C: an `OSError` that is not "the file changed" is not reported as a change. The client's side of
the review is in `test_skills_client.py`.

No character that a reader's editor could reorder or hide is written in this file: such a character is
made with `chr()`.
"""

from __future__ import annotations

import errno
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

import pytest
from ext_r2c.mcp.skills import SkillsExtension, _read
from ext_r2c.mcp.skills._catalogue import SkillsError
from ext_r2c.mcp.skills._scan import scan_roots
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp_harness import mcp_client, run, serve
from skills_fixtures import standard_tree, write_skill

T = TypeVar("T")
MAX_DEPTH = 32
MAX_DIRECTORIES = 1024
INTERNAL_ERROR = -32603
CHANGED = "The skills changed on disk since they were scanned; refresh them."
LOGGER = "ext_r2c.mcp.skills"


def chain(length: int, leaf: str | None = None) -> str:
    """`d/d/.../d` with `length` folders, and `leaf` (a file name) below them if there is one."""
    parts = ["d"] * length
    if leaf is not None:
        parts.append(leaf)
    return "/".join(parts)


# --- Part A: a scan is bounded --------------------------------------------------------------------


class TestDepth:
    def test_folders_below_a_skill_go_32_deep_and_no_deeper(self, tmp_path: Path) -> None:
        write_skill(tmp_path / "ok", "deep-ok", files={chain(MAX_DEPTH, "f.txt"): "x"})
        skill = scan_roots([tmp_path / "ok"], (), ()).skills[0]
        assert any(f.parts[-1] == "f.txt" for f in skill.files)
        assert len(skill.dirs) == MAX_DEPTH

        write_skill(tmp_path / "bad", "deep-bad", files={chain(MAX_DEPTH + 1, "f.txt"): "x"})
        with pytest.raises(SkillsError) as caught:
            scan_roots([tmp_path / "bad"], (), ())
        assert caught.value.folder.endswith("deep-bad")
        assert str(MAX_DEPTH) in caught.value.reason and "deep" in caught.value.reason

    def test_a_very_deep_chain_is_refused_at_once_not_walked_to_the_bottom(self, tmp_path: Path) -> None:
        write_skill(tmp_path, "deep-skill", files={chain(120, "f.txt"): "x"})  # 240 characters of path: fine for the disk
        with pytest.raises(SkillsError, match="deep"):
            scan_roots([tmp_path], (), ())

    def test_folders_above_a_skill_go_32_deep_and_no_deeper(self, tmp_path: Path) -> None:
        write_skill(tmp_path / "ok", chain(MAX_DEPTH - 1) + "/leaf-skill")
        (skill,) = scan_roots([tmp_path / "ok"], (), ()).skills
        assert len(skill.path) == MAX_DEPTH

        write_skill(tmp_path / "bad", chain(MAX_DEPTH) + "/leaf-skill")
        with pytest.raises(SkillsError) as caught:
            scan_roots([tmp_path / "bad"], (), ())
        assert str(MAX_DEPTH) in caught.value.reason and "deep" in caught.value.reason


class TestFolderCounts:
    def test_a_skill_may_hold_1024_folders_and_not_1025(self, tmp_path: Path) -> None:
        for count, folder in ((MAX_DIRECTORIES, "ok"), (MAX_DIRECTORIES + 1, "bad")):
            skill = write_skill(tmp_path / folder, "many-folders")
            for index in range(count):
                (skill / f"f{index:04d}").mkdir()
        (served,) = scan_roots([tmp_path / "ok"], (), ()).skills
        assert len(served.dirs) == MAX_DIRECTORIES
        with pytest.raises(SkillsError) as caught:
            scan_roots([tmp_path / "bad"], (), ())
        assert str(MAX_DIRECTORIES) in caught.value.reason and "folders" in caught.value.reason
        assert caught.value.folder.endswith("many-folders")

    def test_a_scan_searches_1024_folders_that_are_not_skills_and_not_1025(self, tmp_path: Path) -> None:
        """The root counts, so 1023 empty folders below it make 1024. A skill is not counted."""
        for count, folder in ((MAX_DIRECTORIES - 1, "ok"), (MAX_DIRECTORIES, "bad")):
            root = tmp_path / folder
            write_skill(root, "the-skill")
            for index in range(count):
                (root / f"empty-{index:04d}").mkdir()
        assert [s.name for s in scan_roots([tmp_path / "ok"], (), ()).skills] == ["the-skill"]
        with pytest.raises(SkillsError) as caught:
            scan_roots([tmp_path / "bad"], (), ())
        assert str(MAX_DIRECTORIES) in caught.value.reason and "folders" in caught.value.reason

    def test_many_skills_in_one_folder_are_not_counted_as_folders_searched(self, tmp_path: Path) -> None:
        """The number of skills is not limited (a skill is a folder the scan stops at)."""
        for index in range(MAX_DIRECTORIES + 50):
            write_skill(tmp_path, f"s-{index:04d}")
        assert len(scan_roots([tmp_path], (), ()).skills) == MAX_DIRECTORIES + 50


# --- Part B: a name that is not safe to print is not served ---------------------------------------


def _with(char: int) -> str:
    return "a" + chr(char) + "b.txt"


# (what is wrong, the name, how a report shows it: `\xNN` up to 0xff, `\uNNNN` above, never the character)
UNSAFE = [
    ("a line feed", _with(0x0A), "a\\x0ab.txt"),
    ("an escape", _with(0x1B), "a\\x1bb.txt"),
    ("a next-line", _with(0x85), "a\\x85b.txt"),
    ("a line separator", _with(0x2028), "a\\u2028b.txt"),
    ("a paragraph separator", _with(0x2029), "a\\u2029b.txt"),
    ("a right-to-left override", _with(0x202E), "a\\u202eb.txt"),
    ("a bidi isolate", _with(0x2066), "a\\u2066b.txt"),
    ("a left-to-right mark", _with(0x200E), "a\\u200eb.txt"),
    ("an arabic letter mark", _with(0x061C), "a\\u061cb.txt"),
    ("a backslash", _with(0x5C), "a\\x5cb.txt"),
]


class TestUnsafeNames:
    @pytest.mark.parametrize(("name", "shown"), [(n, s) for _, n, s in UNSAFE], ids=[w for w, _, _ in UNSAFE])
    def test_a_file_with_such_a_name_is_left_out_and_the_report_has_no_raw_character(
        self, tmp_path: Path, name: str, shown: str
    ) -> None:
        skill = write_skill(tmp_path, "safe-skill", files={"fine.txt": "ok"})
        try:
            (skill / name).write_text("hidden\n")
        except OSError:
            pytest.skip("this file system cannot hold that name")
        cat = scan_roots([tmp_path], (), ())
        (served,) = cat.skills
        assert sorted(f.parts[-1] for f in served.files) == ["SKILL.md", "fine.txt"]
        assert [(item.path, item.reason) for item in cat.left_out] == [(f"safe-skill/{shown}", "unsafe name")]
        assert cat.left_out[0].path.isascii() and cat.left_out[0].path.isprintable()

    def test_a_folder_with_such_a_name_is_left_out_with_what_is_in_it(self, tmp_path: Path) -> None:
        skill = write_skill(tmp_path, "safe-skill")
        (skill / _with(0x0A)).mkdir()
        (skill / _with(0x0A) / "inner.txt").write_text("inner\n")
        cat = scan_roots([tmp_path], (), ())
        assert [f.parts for f in cat.skills[0].files] == [("SKILL.md",)]
        assert cat.skills[0].dirs == ()
        assert [(i.path, i.reason) for i in cat.left_out] == [("safe-skill/a\\x0ab.txt", "unsafe name")]

    def test_a_folder_above_the_skills_with_such_a_name_hides_what_is_in_it(self, tmp_path: Path) -> None:
        write_skill(tmp_path, "team" + chr(0x0A) + "x/inner-skill")
        write_skill(tmp_path, "fine/real-skill")
        cat = scan_roots([tmp_path], (), ())
        assert [s.path for s in cat.skills] == [("fine", "real-skill")]
        assert [(i.path, i.reason) for i in cat.left_out] == [("team\\x0ax", "unsafe name")]

    def test_text_in_any_script_and_an_emoji_sequence_is_still_served(self, tmp_path: Path) -> None:
        """Only controls, line and paragraph separators, bidi controls and the backslash are unsafe: a
        combining mark and a zero-width joiner (an emoji sequence) are not."""
        names = [
            "cafe" + chr(0x0301) + ".txt",  # a combining accent
            chr(0x1F468) + chr(0x200D) + chr(0x1F4BB) + ".txt",  # an emoji sequence, joined
            "Привет.txt",
            "こんにちは.txt",
        ]
        write_skill(tmp_path, "texts", files={name: "x" for name in names})
        (served,) = scan_roots([tmp_path], (), ()).skills
        assert {f.parts[-1] for f in served.files} >= set(names)

    def test_a_link_with_such_a_name_is_announced_without_a_raw_line_break(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A link is logged by its path; a name with a line feed must not forge a second log line."""
        skill = write_skill(tmp_path / "root", "safe-skill")
        outside = tmp_path / "outside"
        outside.mkdir()
        try:
            (skill / ("x" + chr(0x0A) + "y")).symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("this platform cannot make symlinks")
        with caplog.at_level(logging.INFO, logger=LOGGER):
            SkillsExtension(tmp_path / "root")
        messages = [r.getMessage() for r in caplog.records if r.name == LOGGER]
        assert not any("\n" in message for message in messages)
        assert any("x\\x0ay" in message for message in messages)


# --- Part C: an error that is not "changed" is not reported as one --------------------------------


async def talk(ext: SkillsExtension, body: Callable[[Client], Awaitable[T]]) -> T:
    server = MCPServer("skills-review", extensions=[ext])
    async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
        return await body(client)


async def read_reference(client: Client) -> MCPError:
    with pytest.raises(MCPError) as refused:
        await client.read_resource("skill://pdf-notes/reference.md")
    return refused.value


class TestUnreadable:
    @pytest.mark.parametrize("code", [errno.EIO, errno.EACCES, errno.EMFILE], ids=["EIO", "EACCES", "EMFILE"])
    def test_a_read_that_fails_for_another_reason_is_not_a_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, code: int
    ) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)

        def broken(descriptor: int, limit: int | None) -> bytes:
            raise OSError(code, f"{tree.root}/secret-path went wrong")

        monkeypatch.setattr(_read, "_read_up_to", broken)
        with caplog.at_level(logging.WARNING, logger=LOGGER):
            error = run(talk(ext, read_reference))
        assert error.error.code == INTERNAL_ERROR
        assert error.error.message != CHANGED
        assert str(tmp_path) not in error.error.message and "secret-path" not in error.error.message
        warnings = [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert str(tmp_path) not in warnings[0] and "secret-path" not in warnings[0]
        assert "skill://pdf-notes/reference.md" in warnings[0]

    @pytest.mark.parametrize(
        "code",
        [errno.ENOENT, errno.ENOTDIR, errno.ELOOP, errno.ENXIO, errno.EISDIR, errno.EINVAL],
        ids=["ENOENT", "ENOTDIR", "ELOOP", "ENXIO", "EISDIR", "EINVAL"],
    )
    def test_the_errors_of_a_file_that_is_gone_or_swapped_are_still_a_change(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        ext = SkillsExtension(standard_tree(tmp_path).root)

        def gone(descriptor: int, limit: int | None) -> bytes:
            raise OSError(code, "x")

        monkeypatch.setattr(_read, "_read_up_to", gone)
        error = run(talk(ext, read_reference))
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)
