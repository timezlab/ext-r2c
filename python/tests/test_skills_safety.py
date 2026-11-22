"""Nothing outside the served files is reachable, and nothing is written (spec 005, story 3, SC-003).

Part A is the table of URIs that name nothing served: each is refused with `-32602`, the disk is not
touched for it, and none of the bytes of the secret, the hidden file or the neighbouring folder is in
anything the server sent. Part B is the scan's report of what it left out, a file that changed or was
swapped after the scan, the read that never follows a link, and the proof that the package cannot write.

Everything here is invented. A real MCP SDK client talks to a real `MCPServer`, as in the other skills
tests; what must be served is worked out from the disk before the traps are laid.
"""

from __future__ import annotations

import ast
import base64
import importlib.resources
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import ext_r2c.mcp
import ext_r2c.mcp.skills as skills_package
import pytest
from ext_r2c.mcp.skills import SkillsExtension, _read
from ext_r2c.mcp.skills._catalogue import LeftOutPath
from ext_r2c.mcp.skills._wire import (
    GetSkillParams,
    GetSkillRequest,
    GetSkillResult,
    ListSkillsRequest,
    ListSkillsResult,
)
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp_harness import mcp_client, run, serve
from mcp_transport import Record
from skills_fixtures import (
    SECRET,
    Fixture,
    add_fifo,
    add_symlink,
    outside_secret,
    snapshot,
    standard_tree,
    write_skill,
)

T = TypeVar("T")
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
CHANGED = "The skills changed on disk since they were scanned; refresh them."
MIB = 1024 * 1024
HIDDEN = b"HIDDEN-TOKEN\n"
DRAFT = b"DRAFT-PLAN\n"
UNSERVED = (SECRET, HIDDEN, DRAFT)
REFERENCE = "skill://pdf-notes/reference.md"
NOTES = "skill://team/billing/refunds/notes.txt"


# --- Helpers --------------------------------------------------------------------------------------


class Spy(SkillsExtension):
    """Notes every file the extension is asked to read from the disk."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reads: list[str] = []

    def _read_bytes(self, record: Any) -> bytes:
        self.reads.append(record.uri)
        return super()._read_bytes(record)


async def talk(ext: SkillsExtension, body: Callable[[Client], Awaitable[T]], *, record: Record | None = None) -> T:
    server = MCPServer("skills-safety", extensions=[ext])
    async with serve(server, record=record) as served, mcp_client(served, active=False, form=False) as client:
        return await body(client)


async def refusal(client: Client, uri: str) -> MCPError:
    """The error a read of `uri` raises; the test fails here if the server answers."""
    with pytest.raises(MCPError) as refused:
        await client.read_resource(uri)
    return refused.value


def bytes_of(content: Any) -> bytes:
    return base64.b64decode(content.blob) if hasattr(content, "blob") else content.text.encode("utf-8")


def sent_uris(record: Record) -> list[str]:
    """The URI of every `resources/read` the client sent, as it was on the wire."""
    return [m["params"]["uri"] for side, m in record if side == "client" and m.get("method") == "resources/read"]


def assert_clean(record: Record, tmp_path: Path, *secrets: bytes) -> None:
    """Nothing the server sent holds a path of this host, or any of `secrets` (as text or base64)."""
    wire = json.dumps([m for side, m in record if side == "remote"])
    for host in {str(tmp_path), os.path.realpath(tmp_path)}:
        assert host not in wire
    for secret in secrets:
        assert secret.decode("ascii") not in wire
        assert base64.b64encode(secret).decode("ascii") not in wire


@dataclass(frozen=True)
class Arena:
    """The standard tree with traps laid beside it: a secret outside the root, a hidden file and a
    link to the secret inside a skill, and a folder next to the skills that is not a skill."""

    tree: Fixture
    served: dict[str, bytes]  # what is to be served, worked out before the traps
    secret: Path


def arena(tmp_path: Path) -> Arena:
    tree = standard_tree(tmp_path)
    served = tree.expected()
    secret = outside_secret(tmp_path)
    skill = tree.root / "pdf-notes"
    (skill / ".env").write_bytes(HIDDEN)
    add_symlink(skill / "link.txt", secret)
    (tree.root / "drafts").mkdir()
    (tree.root / "drafts" / "plan.md").write_bytes(DRAFT)
    return Arena(tree, served, secret)


# --- Part A: URIs that name nothing served --------------------------------------------------------

TABLE = {
    "dotdot plain": "skill://pdf-notes/../../outside/secret.txt",
    "dotdot encoded lower": "skill://pdf-notes/%2e%2e/%2e%2e/outside/secret.txt",
    "dotdot encoded upper": "skill://pdf-notes/%2E%2E/%2E%2E/outside/secret.txt",
    "dotdot half encoded": "skill://pdf-notes/.%2e/.%2e/outside/secret.txt",
    "dotdot double encoded": "skill://pdf-notes/%252e%252e/%252e%252e/outside/secret.txt",
    "dotdot back to a served file": "skill://pdf-notes/../pdf-notes/reference.md",
    "single dot": "skill://pdf-notes/./reference.md",
    "backslashes": "skill://pdf-notes\\..\\..\\outside\\secret.txt",
    "user info": "skill://someone@pdf-notes/reference.md",
    "port": "skill://pdf-notes:8080/reference.md",
    "the link to the secret": "skill://pdf-notes/link.txt",
    "the hidden file": "skill://pdf-notes/.env",
    "the neighbouring folder": "skill://drafts/plan.md",
    "a query": "skill://pdf-notes/reference.md?x=1",
    "a fragment": "skill://pdf-notes/reference.md#top",
    "a trailing slash on a file": "skill://pdf-notes/reference.md/",
    "a trailing space": "skill://pdf-notes/reference.md ",
    "a doubled slash": "skill://pdf-notes//reference.md",
    "a null byte": "skill://pdf-notes/reference.md\x00",
    "SKILL.MD in capitals": "skill://pdf-notes/SKILL.MD",
    "a folder name in capitals": "skill://pdf-notes/ASSETS/logo.bin",
    "the first segment in capitals": "skill://TEAM/billing/refunds/SKILL.md",
    "an encoded slash": "skill://team/billing%2Frefunds/SKILL.md",
    "an encoded dot in a name": "skill://pdf-notes/reference%2emd",
    "a third slash": "skill:///etc/passwd",
    "the file scheme": "file:///etc/passwd",
    "a directory": "skill://pdf-notes/assets",
    "a directory with a slash": "skill://pdf-notes/assets/",
    "a skill folder": "skill://pdf-notes",
    "the scheme alone": "skill://",
    "an absolute path": "/etc/passwd",
    "an empty uri": "",
}


class TestTheTable:
    def test_there_are_enough_attempts_and_each_is_different(self) -> None:
        assert len(TABLE) >= 14 and len(set(TABLE.values())) == len(TABLE)

    @pytest.mark.parametrize("uri", list(TABLE.values()), ids=list(TABLE))
    def test_a_uri_that_names_nothing_served_is_invalid_params_and_reads_nothing(
        self, tmp_path: Path, uri: str
    ) -> None:
        trap = arena(tmp_path)
        spy, record = Spy(trap.tree.root), []

        async def body(client: Client) -> MCPError:
            return await refusal(client, uri)

        error = run(talk(spy, body, record=record))
        assert error.error.code == INVALID_PARAMS
        assert sent_uris(record) == [uri]  # the very string went out, not a tidied one
        assert spy.reads == []  # the disk was not asked for anything
        assert_clean(record, tmp_path, *UNSERVED)

    def test_after_all_of_them_the_skills_are_still_served_and_resources_list_holds_exactly_them(
        self, tmp_path: Path
    ) -> None:
        trap = arena(tmp_path)
        spy, record = Spy(trap.tree.root), []

        async def body(client: Client) -> tuple[list[int | None], dict[str, bytes], set[str], set[str]]:
            codes: list[int | None] = []
            for uri in TABLE.values():
                try:
                    await client.read_resource(uri)
                except MCPError as error:
                    codes.append(error.error.code)
                else:
                    codes.append(None)
            got = {uri: bytes_of((await client.read_resource(uri)).contents[0]) for uri in trap.served}
            listed = {str(r.uri) for r in (await client.list_resources()).resources}
            skills = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
            return codes, got, listed, {r.uri for s in skills.skills for r in s.resources}

        codes, got, listed, in_skills = run(talk(spy, body, record=record))
        assert codes == [INVALID_PARAMS] * len(TABLE)
        assert got == trap.served
        assert listed == in_skills == set(trap.served)  # the traps are in neither list
        assert sorted(spy.reads) == sorted(trap.served)  # only served files were ever opened
        assert_clean(record, tmp_path, *UNSERVED)

    @pytest.mark.parametrize(
        "uri",
        [
            "skill://pdf-notes/./SKILL.md",
            "skill://pdf-notes/../pdf-notes/SKILL.md",
            "skill://pdf-notes/%53KILL.md",
            "skill://pdf-notes/SKILL.md?x=1",
            "skill://pdf-notes/SKILL.md#top",
            "skill://PDF-NOTES/SKILL.md",
            "skill://pdf-notes/SKILL.MD",
        ],
    )
    def test_skills_get_takes_the_uri_as_literally(self, tmp_path: Path, uri: str) -> None:
        trap = arena(tmp_path)

        async def body(client: Client) -> tuple[MCPError, GetSkillResult]:
            with pytest.raises(MCPError) as refused:
                await client.session.send_request(GetSkillRequest(params=GetSkillParams(uri=uri)), GetSkillResult)
            real = await client.session.send_request(
                GetSkillRequest(params=GetSkillParams(uri="skill://pdf-notes/SKILL.md")), GetSkillResult
            )
            return refused.value, real

        error, real = run(talk(SkillsExtension(trap.tree.root), body))
        assert error.error.code == INVALID_PARAMS
        assert real.skill.uri == "skill://pdf-notes/SKILL.md"

    def test_skills_get_is_not_answered_for_a_path_of_this_host(self, tmp_path: Path) -> None:
        """The URI is a key and nothing else: the folder of a skill, its `SKILL.md`, as a path, as a
        `file:` URL or relative to the root, names no skill. The message gives back what was asked."""
        trap = arena(tmp_path)
        folder = Path(os.path.realpath(trap.tree.root / "pdf-notes"))
        asked = [
            str(folder),
            str(folder / "SKILL.md"),
            folder.as_uri(),
            (folder / "SKILL.md").as_uri(),
            "pdf-notes",
            "pdf-notes/SKILL.md",
            "SKILL.md",
        ]

        async def body(client: Client) -> list[MCPError]:
            errors = []
            for uri in asked:
                with pytest.raises(MCPError) as refused:
                    await client.session.send_request(GetSkillRequest(params=GetSkillParams(uri=uri)), GetSkillResult)
                errors.append(refused.value)
            return errors

        errors = run(talk(SkillsExtension(trap.tree.root), body))
        assert [e.error.code for e in errors] == [INVALID_PARAMS] * len(asked)
        assert [e.error.message for e in errors] == [f"No skill is served at {uri}" for uri in asked]


# --- Part B: what the scan leaves out -------------------------------------------------------------


def trapped_skill(tmp_path: Path) -> tuple[Fixture, Path]:
    """The standard tree, with one of every kind of entry a scan leaves out inside `pdf-notes`."""
    tree = standard_tree(tmp_path)
    secret = outside_secret(tmp_path)
    skill = tree.root / "pdf-notes"
    (skill / ".hidden.txt").write_text("hidden\n")
    (skill / ".cache").mkdir()
    (skill / ".cache" / "inside.txt").write_text("inside a hidden folder\n")
    (skill / "assets" / ".DS_Store").write_bytes(b"\x00")
    add_symlink(skill / "leak.txt", secret)
    add_symlink(skill / "leak-dir", secret.parent, directory=True)
    add_symlink(skill / "assets" / "dangling", "nowhere-at-all")
    add_fifo(skill / "pipe")
    add_fifo(skill / "assets" / "pipe2")
    return tree, secret


class TestLeftOut:
    def test_every_entry_not_served_is_reported_once_with_its_reason(self, tmp_path: Path) -> None:
        tree, _ = trapped_skill(tmp_path)
        ext = SkillsExtension(tree.root)
        assert ext.left_out == (
            LeftOutPath("pdf-notes/.cache", "hidden"),  # a hidden folder once, not what is inside it
            LeftOutPath("pdf-notes/.hidden.txt", "hidden"),
            LeftOutPath("pdf-notes/assets/.DS_Store", "hidden"),
            LeftOutPath("pdf-notes/assets/dangling", "symbolic link"),
            LeftOutPath("pdf-notes/assets/pipe2", "not a regular file"),
            LeftOutPath("pdf-notes/leak-dir", "symbolic link"),
            LeftOutPath("pdf-notes/leak.txt", "symbolic link"),
            LeftOutPath("pdf-notes/pipe", "not a regular file"),
        )
        assert isinstance(ext.left_out, tuple) and ext.left_out is ext.catalogue.left_out
        assert set(ext.catalogue.files) == set(standard_tree(tmp_path / "clean").expected())  # nothing else is served

    def test_nothing_left_out_is_in_the_listing(self, tmp_path: Path) -> None:
        tree, _ = trapped_skill(tmp_path)
        expected = standard_tree(tmp_path / "clean").expected()

        async def body(client: Client) -> tuple[set[str], set[str]]:
            skills = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
            return {r.uri for s in skills.skills for r in s.resources}, {
                str(r.uri) for r in (await client.list_resources()).resources
            }

        in_skills, listed = run(talk(SkillsExtension(tree.root), body))
        assert in_skills == listed == set(expected)

    def test_it_is_reported_where_no_skill_is_too(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        write_skill(tree.root, ".hidden-skill")
        add_symlink(tree.root / "linked-skill", tree.root / "pdf-notes", directory=True)
        (tree.root / "fake").mkdir()
        add_symlink(tree.root / "fake" / "SKILL.md", tree.root / "pdf-notes" / "SKILL.md")
        (tree.root / "drafts").mkdir()
        (tree.root / "drafts" / ".notes").write_text("n\n")
        add_fifo(tree.root / "a-pipe" / "SKILL.md")
        ext = SkillsExtension(tree.root)
        assert ext.left_out == (
            LeftOutPath(".hidden-skill", "hidden"),
            LeftOutPath("a-pipe/SKILL.md", "not a regular file"),
            LeftOutPath("drafts/.notes", "hidden"),
            LeftOutPath("fake/SKILL.md", "symbolic link"),  # a SKILL.md that is a link is not a SKILL.md
            LeftOutPath("linked-skill", "symbolic link"),
        )
        assert [s.name for s in ext.skills] == ["greetings", "pdf-notes", "refunds"]

    def test_a_link_is_reported_as_a_link_even_when_its_name_is_hidden_and_a_hidden_pipe_as_hidden(
        self, tmp_path: Path
    ) -> None:
        tree = standard_tree(tmp_path)
        add_symlink(tree.root / "pdf-notes" / ".dotlink", outside_secret(tmp_path))
        add_fifo(tree.root / "pdf-notes" / ".dotpipe")
        assert SkillsExtension(tree.root).left_out == (
            LeftOutPath("pdf-notes/.dotlink", "symbolic link"),
            LeftOutPath("pdf-notes/.dotpipe", "hidden"),
        )

    def test_a_name_that_is_not_text_is_reported_without_being_served(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        expected = set(tree.expected())  # worked out before the name that cannot be encoded is made
        folder = os.fsencode(str(tree.root / "pdf-notes"))
        try:
            with open(os.path.join(folder, b"bad-\xff.txt"), "wb") as stream:
                stream.write(b"unreachable by name\n")
        except OSError as e:
            pytest.skip(f"this file system takes no names that are not text: {e}")
        ext = SkillsExtension(tree.root)
        assert ext.left_out == (LeftOutPath("pdf-notes/bad-\\xff.txt", "undecodable name"),)
        assert set(ext.catalogue.files) == expected

    def test_a_pipe_whose_name_is_not_text_is_reported_for_its_name(self, tmp_path: Path) -> None:
        """Both reasons hold, and the name is the one the report gives."""
        tree = standard_tree(tmp_path)
        folder = os.fsencode(str(tree.root / "pdf-notes"))
        try:
            os.mkfifo(os.path.join(folder, b"bad-\xff.pipe"))
        except OSError as e:
            pytest.skip(f"this file system takes no names that are not text: {e}")
        assert SkillsExtension(tree.root).left_out == (LeftOutPath("pdf-notes/bad-\\xff.pipe", "undecodable name"),)

    def test_a_scan_with_nothing_to_report_reports_nothing(self, tmp_path: Path) -> None:
        assert SkillsExtension(standard_tree(tmp_path).root).left_out == ()

    def test_left_out_is_exported_with_the_other_names(self) -> None:
        assert ext_r2c.mcp.LeftOutPath is skills_package.LeftOutPath is LeftOutPath
        assert "LeftOutPath" in skills_package.__all__ and "LeftOutPath" in ext_r2c.mcp.__all__


class TestTheLog:
    def test_one_info_per_skill_and_one_warning_per_link_under_the_package_logger(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        tree, _ = trapped_skill(tmp_path)
        with caplog.at_level(logging.DEBUG, logger="ext_r2c.mcp.skills"):
            SkillsExtension(tree.root)
        records = [r for r in caplog.records if r.name == "ext_r2c.mcp.skills"]
        infos = [r.getMessage() for r in records if r.levelno == logging.INFO]
        warnings = [r.getMessage() for r in records if r.levelno == logging.WARNING]
        assert len(records) == len(infos) + len(warnings) == 3 + 3
        for uri in ("skill://greetings/SKILL.md", "skill://pdf-notes/SKILL.md", "skill://team/billing/refunds/SKILL.md"):
            assert sum(uri in line for line in infos) == 1, uri
        for path in ("pdf-notes/leak.txt", "pdf-notes/leak-dir", "pdf-notes/assets/dangling"):
            assert sum(path in line for line in warnings) == 1, path  # a hidden file or a pipe is no warning

    def test_nothing_is_logged_when_the_package_is_imported(self) -> None:
        code = (
            "import logging, sys\n"
            "logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)\n"
            "import ext_r2c.mcp, ext_r2c.mcp.skills\n"
            "assert logging.getLogger('ext_r2c.mcp.skills').handlers == []\n"
        )
        done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


# --- Part B: the reader never follows a link ------------------------------------------------------


@pytest.fixture(params=[True, False], ids=["no-follow open", "lstat fallback"])
def safe(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    """Both ways of reading: the kernel refuses a link (Linux, macOS), or each step is checked with
    `lstat` first (where `O_NOFOLLOW` or `dir_fd` is missing)."""
    monkeypatch.setattr(_read, "_SAFE", request.param)
    return bool(request.param)


class TestTheReader:
    @pytest.fixture
    def tmp_path(self, tmp_path: Path) -> Path:
        """The temporary folder by its real path: the reader is given real paths, as a scan resolves
        each root once, and one with a link in it would be refused."""
        return Path(os.path.realpath(tmp_path))

    def test_it_reads_a_file_below_a_folder(self, tmp_path: Path, safe: bool) -> None:
        tree = standard_tree(tmp_path)
        skill = str(tree.root / "pdf-notes")
        assert _read.read_bytes(skill, ("assets", "logo.bin")) == b"\x00\x01\xff\xfe\x00LOGO"
        assert _read.read_bytes(skill, ("SKILL.md",)) == (tree.root / "pdf-notes" / "SKILL.md").read_bytes()

    def test_a_limit_stops_the_read_after_that_many_bytes(self, tmp_path: Path, safe: bool) -> None:
        skill = str(standard_tree(tmp_path).root / "pdf-notes")
        whole = _read.read_bytes(skill, ("reference.md",))
        assert len(whole) > 10
        assert _read.read_bytes(skill, ("reference.md",), 10) == whole[:10]
        assert _read.read_bytes(skill, ("reference.md",), len(whole)) == whole
        assert _read.read_bytes(skill, ("reference.md",), len(whole) + 1) == whole
        assert _read.read_bytes(skill, ("reference.md",), 0) == b""

    def test_a_file_larger_than_one_piece_is_read_whole_and_to_the_limit(self, tmp_path: Path, safe: bool) -> None:
        tree = standard_tree(tmp_path)
        skill = tree.root / "pdf-notes"
        data = bytes(range(256)) * (2 * MIB // 256) + b"tail!"  # two pieces and a bit
        (skill / "big.bin").write_bytes(data)
        assert _read.read_bytes(str(skill), ("big.bin",)) == data
        assert _read.read_bytes(str(skill), ("big.bin",), len(data) + 1) == data
        assert _read.read_bytes(str(skill), ("big.bin",), MIB + 7) == data[: MIB + 7]
        assert _read.read_bytes(str(skill), ("big.bin",), 2 * MIB) == data[: 2 * MIB]

    def test_a_file_larger_than_one_piece_is_served_whole(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        data = bytes(range(256)) * (2 * MIB // 256) + b"tail!"
        (tree.root / "pdf-notes" / "big.bin").write_bytes(data)

        async def body(client: Client) -> bytes:
            return bytes_of((await client.read_resource("skill://pdf-notes/big.bin")).contents[0])

        assert run(talk(SkillsExtension(tree.root), body)) == data

    @pytest.mark.skipif(not sys.platform.startswith(("linux", "darwin")), reason="Windows reads by the lstat path")
    def test_where_the_kernel_can_refuse_a_link_it_is_the_kernel_that_does(self) -> None:
        assert _read._SAFE is True

    def test_a_link_as_the_file_is_refused(self, tmp_path: Path, safe: bool) -> None:
        tree = standard_tree(tmp_path)
        add_symlink(tree.root / "pdf-notes" / "copy.md", tree.root / "pdf-notes" / "reference.md")
        with pytest.raises(OSError):
            _read.read_bytes(str(tree.root / "pdf-notes"), ("copy.md",))

    def test_a_link_as_a_folder_on_the_way_is_refused(self, tmp_path: Path, safe: bool) -> None:
        tree = standard_tree(tmp_path)
        add_symlink(tree.root / "pdf-notes" / "assets-link", tree.root / "pdf-notes" / "assets", directory=True)
        with pytest.raises(OSError):
            _read.read_bytes(str(tree.root / "pdf-notes"), ("assets-link", "logo.bin"))

    def test_a_link_as_the_skill_folder_or_above_it_is_refused(self, tmp_path: Path, safe: bool) -> None:
        tree = standard_tree(tmp_path)
        add_symlink(tmp_path / "skills-link", tree.root, directory=True)
        for folder in (tmp_path / "skills-link" / "pdf-notes", tmp_path / "skills-link"):
            parts = ("reference.md",) if folder.name == "pdf-notes" else ("pdf-notes", "reference.md")
            with pytest.raises(OSError):
                _read.read_bytes(str(folder), parts)

    @pytest.mark.parametrize("what", ["a folder", "a pipe", "a missing file"])
    def test_anything_but_a_regular_file_is_refused_without_waiting(
        self, tmp_path: Path, safe: bool, what: str
    ) -> None:
        tree = standard_tree(tmp_path)
        skill = tree.root / "pdf-notes"
        if what == "a pipe":
            add_fifo(skill / "thing")
        elif what == "a folder":
            (skill / "thing").mkdir()
        started = time.monotonic()
        with pytest.raises(OSError):
            _read.read_bytes(str(skill), ("thing",))
        assert time.monotonic() - started < 1.0

    def test_it_leaves_no_descriptor_open(self, tmp_path: Path, safe: bool) -> None:
        if not os.path.isdir("/proc/self/fd"):
            pytest.skip("this platform does not list descriptors")
        skill = str(standard_tree(tmp_path).root / "pdf-notes")
        before = len(os.listdir("/proc/self/fd"))
        for parts in (("reference.md",), ("assets", "logo.bin"), ("missing",), ("assets",)):
            try:
                _read.read_bytes(skill, parts)
            except OSError:
                pass
        assert len(os.listdir("/proc/self/fd")) == before


# --- Part B: a file that changed after the scan ---------------------------------------------------


class TestChangedAfterTheScan:
    def test_a_file_that_grew_by_five_mebibytes_is_refused_and_the_listing_keeps_the_old_entry(
        self, tmp_path: Path
    ) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        target = tree.root / "pdf-notes" / "reference.md"
        old = target.read_bytes()
        target.write_bytes(old + b"x" * (5 * MIB))
        record: Record = []

        async def body(client: Client) -> tuple[MCPError, ListSkillsResult]:
            error = await refusal(client, REFERENCE)
            return error, await client.session.send_request(ListSkillsRequest(), ListSkillsResult)

        error, listed = run(talk(ext, body, record=record))
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)
        entry = next(r for s in listed.skills for r in s.resources if r.uri == REFERENCE)
        assert entry.size == len(old)  # the entry is the scan's, until the owner refreshes
        assert_clean(record, tmp_path, b"x" * 64)

    def test_a_file_replaced_by_a_folder_is_refused(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        target = tree.root / "pdf-notes" / "reference.md"
        target.unlink()
        target.mkdir()
        (target / "inner.txt").write_bytes(b"INNER\n")
        record: Record = []
        error = run(talk(ext, lambda client: refusal(client, REFERENCE), record=record))
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)
        assert_clean(record, tmp_path, b"INNER\n")

    def test_a_file_that_grew_hugely_is_not_read_into_memory(self, tmp_path: Path) -> None:
        """The read stops one byte past the size in the entry, so a file that became 256 MiB costs
        a few bytes. Only a read of the whole file would allocate anything near that."""
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        with open(tree.root / "pdf-notes" / "reference.md", "r+b") as stream:
            stream.truncate(256 * MIB)  # sparse: the old bytes, then zeros

        async def body(client: Client) -> tuple[MCPError, int]:
            tracemalloc.start()
            try:
                tracemalloc.reset_peak()
                error = await refusal(client, REFERENCE)
                return error, tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()

        error, peak = run(talk(ext, body))
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)
        assert peak < 32 * MIB


# --- Part B: a file swapped for a link after the scan ---------------------------------------------


def swap_file_for_a_link(tmp_path: Path, tree: Fixture) -> str:
    """The file becomes a link to an outside file with the very same bytes."""
    target = tree.root / "pdf-notes" / "reference.md"
    outside = tmp_path / "outside" / "copy.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(target, outside)
    target.unlink()
    add_symlink(target, outside)
    return REFERENCE


def swap_a_folder_in_the_skill(tmp_path: Path, tree: Fixture) -> str:
    """`assets` becomes a link to an outside copy of itself."""
    folder = tree.root / "pdf-notes" / "assets"
    shutil.copytree(folder, tmp_path / "outside" / "assets-copy")
    shutil.rmtree(folder)
    add_symlink(folder, tmp_path / "outside" / "assets-copy", directory=True)
    return "skill://pdf-notes/assets/logo.bin"


def swap_a_folder_above_the_skill(tmp_path: Path, tree: Fixture) -> str:
    """`team`, which holds the nested skill, becomes a link to an outside copy."""
    folder = tree.root / "team"
    shutil.copytree(folder, tmp_path / "outside" / "team-copy")
    shutil.rmtree(folder)
    add_symlink(folder, tmp_path / "outside" / "team-copy", directory=True)
    return NOTES


def swap_the_skill_folder(tmp_path: Path, tree: Fixture) -> str:
    folder = tree.root / "pdf-notes"
    shutil.copytree(folder, tmp_path / "outside" / "pdf-notes-copy")
    shutil.rmtree(folder)
    add_symlink(folder, tmp_path / "outside" / "pdf-notes-copy", directory=True)
    return REFERENCE


def swap_the_root(tmp_path: Path, tree: Fixture) -> str:
    moved = tmp_path / "skills-moved"
    tree.root.rename(moved)
    add_symlink(tree.root, moved, directory=True)
    return REFERENCE


SWAPS = {
    "the file": swap_file_for_a_link,
    "a folder in the skill": swap_a_folder_in_the_skill,
    "a folder above the skill": swap_a_folder_above_the_skill,
    "the skill folder": swap_the_skill_folder,
    "the root": swap_the_root,
}


class TestSwappedForALink:
    @pytest.mark.parametrize("swap", list(SWAPS.values()), ids=list(SWAPS))
    def test_a_link_with_the_same_bytes_is_refused_where_it_was_put(
        self, tmp_path: Path, safe: bool, swap: Callable[[Path, Fixture], str]
    ) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        record: Record = []

        async def body(client: Client) -> tuple[bytes, str, MCPError]:
            before = bytes_of((await client.read_resource(REFERENCE)).contents[0])  # fine until the swap
            uri = swap(tmp_path, tree)
            return before, uri, await refusal(client, uri)

        before, uri, error = run(talk(ext, body, record=record))
        assert before == (tmp_path / "skills" / "pdf-notes" / "reference.md").read_bytes()  # the copy is the same
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED), uri
        assert sent_uris(record)[-1] == uri
        assert_clean(record, tmp_path)

    def test_a_file_swapped_for_a_pipe_is_refused_at_once_and_a_failing_build_cannot_hang_the_suite(
        self, tmp_path: Path
    ) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        target = tree.root / "pdf-notes" / "reference.md"
        target.unlink()
        add_fifo(target)
        stop = threading.Event()

        def open_the_other_end() -> None:
            """After three seconds, give a reader that is waiting in `open` a writer, then let it go."""
            if stop.wait(3.0):
                return
            for _ in range(100):
                try:
                    os.close(os.open(target, os.O_WRONLY | os.O_NONBLOCK))
                    return
                except OSError:
                    if stop.wait(0.05):
                        return

        helper = threading.Thread(target=open_the_other_end, daemon=True)
        helper.start()

        async def body(client: Client) -> tuple[MCPError, float]:
            started = time.monotonic()
            error = await refusal(client, REFERENCE)
            return error, time.monotonic() - started

        try:
            error, elapsed = run(talk(ext, body))
        finally:
            stop.set()
            helper.join(timeout=10)
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)
        assert elapsed < 1.5  # a read that waited for a writer would take the three seconds

    def test_a_pipe_that_holds_the_very_bytes_is_still_not_a_file(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        target = tree.root / "pdf-notes" / "reference.md"
        data = target.read_bytes()
        target.unlink()
        add_fifo(target)
        fd = os.open(target, os.O_RDWR)  # both ends in one: the pipe has a writer and holds the bytes
        os.write(fd, data)
        lock = threading.Lock()
        open_ends = [fd]

        def close() -> None:
            with lock:
                while open_ends:
                    os.close(open_ends.pop())

        timer = threading.Timer(3.0, close)  # lets a reader that waits for the end of the data finish
        timer.start()
        try:
            error = run(talk(ext, lambda client: refusal(client, REFERENCE)))
        finally:
            timer.cancel()
            close()
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)


# --- Part B: nothing is ever written --------------------------------------------------------------


def make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o222)
    root.chmod(root.stat().st_mode & ~0o222)


def make_writable(root: Path) -> None:
    root.chmod(root.stat().st_mode | 0o700)
    for path in root.rglob("*"):
        if not path.is_symlink():
            path.chmod(path.stat().st_mode | 0o700)


class TestNeverWrites:
    def test_a_read_only_tree_serves_every_flow_and_is_left_exactly_as_it_was(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        expected = tree.expected()
        make_read_only(tree.root)
        try:
            before = snapshot(tree.root)
            ext = SkillsExtension(tree.root)

            async def body(client: Client) -> dict[str, bytes]:
                await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
                await client.session.send_request(
                    GetSkillRequest(params=GetSkillParams(uri="skill://pdf-notes/SKILL.md")), GetSkillResult
                )
                await client.list_resources()
                return {uri: bytes_of((await client.read_resource(uri)).contents[0]) for uri in expected}

            got = run(talk(ext, body))
            assert got == expected
            assert snapshot(tree.root) == before
        finally:
            make_writable(tree.root)


FORBIDDEN = {
    "O_WRONLY",
    "O_RDWR",
    "O_CREAT",
    "O_TRUNC",
    "O_APPEND",
    "write_text",
    "write_bytes",
    "unlink",
    "rmdir",
    "rename",
    "mkdir",
    "chmod",
    "shutil",
    "makedirs",
    "removedirs",
    "truncate",
    "utime",
    "chown",
    "symlink",
}
MODE_LETTERS = set("rwxabt+U")


def audit(source: str) -> list[str]:
    """What in `source` could write: a forbidden name, an import of one, or an `open` whose mode has
    `w`, `a`, `x` or `+`. Docstrings and comments are not code, so they are not read."""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            problems.append(f"{line}: .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN:
            problems.append(f"{line}: {node.id}")
        elif isinstance(node, ast.Import):
            problems += [f"{line}: import {a.name}" for a in node.names if a.name.split(".")[0] in FORBIDDEN]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in FORBIDDEN:
                problems.append(f"{line}: from {node.module}")
            problems += [f"{line}: from {node.module} import {a.name}" for a in node.names if a.name in FORBIDDEN]
        elif isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if called in {"open", "fdopen"}:
                modes = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                modes = [m for m in modes if m and set(m) <= MODE_LETTERS]
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        value = keyword.value
                        modes.append(value.value if isinstance(value, ast.Constant) else "?")
                if any(set(m) & set("wax+") or m == "?" for m in modes):
                    problems.append(f"{line}: {called}(mode {modes})")
    return problems


class TestTheAudit:
    @pytest.mark.parametrize(
        "source",
        [
            "import os\nos.open(p, os.O_WRONLY)",
            "import os\nos.open(p, os.O_RDWR)",
            "import os\nos.open(p, os.O_RDONLY | os.O_CREAT)",
            "import os\nos.open(p, os.O_TRUNC)",
            "import os\nos.open(p, os.O_APPEND)",
            "open(p, 'w')",
            "open(p, 'a')",
            "open(p, 'x')",
            "open(p, 'r+')",
            "open(p, 'rb+')",
            "open(p, mode='wb')",
            "open(p, mode=chosen)",
            "p.open('w')",
            "os.fdopen(fd, 'wb')",
            "p.write_text('x')",
            "p.write_bytes(b'x')",
            "p.unlink()",
            "os.rmdir(p)",
            "os.rename(a, b)",
            "os.mkdir(p)",
            "os.makedirs(p)",
            "os.chmod(p, 0o600)",
            "os.truncate(p, 0)",
            "os.utime(p)",
            "os.symlink(a, b)",
            "import shutil",
            "import shutil.thing",
            "from shutil import rmtree",
            "from os import unlink",
            "from os import O_WRONLY",
        ],
    )
    def test_each_way_to_write_is_found(self, source: str) -> None:
        assert audit(source), source

    @pytest.mark.parametrize(
        "source",
        [
            "open(p, 'rb')",
            "open(p)",
            "open(p, mode='r')",
            "open('example.txt')",
            "open('wax.txt', 'rb')",
            "os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)",
            "x = 'w'",
            "'''A docstring that says O_WRONLY and unlink.'''",
            "# a comment about mkdir and shutil",
            "name.replace('a', 'b')",
        ],
    )
    def test_reading_is_not_flagged(self, source: str) -> None:
        assert audit(source) == [], source

    def test_the_installed_modules_hold_nothing_that_could_write(self) -> None:
        package = importlib.resources.files("ext_r2c.mcp.skills")
        modules = {entry.name: entry.read_text(encoding="utf-8") for entry in package.iterdir() if entry.name.endswith(".py")}
        assert {"_read.py", "_scan.py", "extension.py", "client.py", "_catalogue.py"} <= set(modules)
        assert {name: audit(source) for name, source in modules.items() if audit(source)} == {}
