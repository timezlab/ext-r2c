"""Scanning the folders again while the server runs (spec 005, story 4, FR-007, D2).

A real MCP SDK client talks to a real `MCPServer` that serves a `SkillsExtension`; the folders are
edited under it and `refresh()` is called. What a refresh cannot do, because the SDK cannot remove a
resource, is tested here as the limit it is. Everything is invented.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import shutil
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

import anyio
import pytest
from ext_r2c.mcp import SkillsError
from ext_r2c.mcp.skills import SkillsExtension
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
from skills_fixtures import write_skill

T = TypeVar("T")
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
CHANGED = "The skills changed on disk since they were scanned; refresh them."


# --- Helpers --------------------------------------------------------------------------------------


async def session(ext: SkillsExtension, body: Callable[[MCPServer, Client], Awaitable[T]]) -> T:
    server = MCPServer("skills-refresh", extensions=[ext])
    async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
        return await body(server, client)


def sha(data: bytes | str) -> str:
    return "sha256:" + hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


async def digests(client: Client) -> dict[str, dict[str, str]]:
    """`{skill uri: {file uri: digest}}` as `skills/list` says it now."""
    listed = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
    return {skill.uri: {r.uri: r.digest for r in skill.resources} for skill in listed.skills}


async def entry(client: Client, uri: str) -> GetSkillResult:
    return await client.session.send_request(GetSkillRequest(params=GetSkillParams(uri=uri)), GetSkillResult)


async def read(client: Client, uri: str) -> bytes:
    content = (await client.read_resource(uri)).contents[0]
    return base64.b64decode(content.blob) if hasattr(content, "blob") else content.text.encode("utf-8")


async def read_error(client: Client, uri: str) -> MCPError:
    with pytest.raises(MCPError) as refused:
        await client.read_resource(uri)
    return refused.value


async def get_error(client: Client, uri: str) -> MCPError:
    with pytest.raises(MCPError) as refused:
        await entry(client, uri)
    return refused.value


async def listed_resources(client: Client) -> dict[str, Any]:
    return {str(resource.uri): resource for resource in (await client.list_resources()).resources}


def real(path: Path) -> Path:
    return Path(os.path.realpath(path))


ALPHA = "skill://alpha/SKILL.md"
BETA = "skill://beta/SKILL.md"


# --- An edit, then a refresh ----------------------------------------------------------------------


class TestAfterAnEdit:
    def test_until_a_refresh_the_list_keeps_the_old_digest_and_a_read_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        skill = write_skill(root, "alpha", files={"a.txt": "one\n"})
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            before = await digests(client)
            assert before[ALPHA]["skill://alpha/a.txt"] == sha("one\n")
            (skill / "a.txt").write_text("two\n")  # the same size: only the digest can tell
            (skill / ".draft").write_text("x")
            assert await digests(client) == before
            assert {r.uri: r.digest for r in (await entry(client, ALPHA)).skill.resources} == before[ALPHA]  # the entry too
            refused = await read_error(client, "skill://alpha/a.txt")
            assert (refused.error.code, refused.error.message) == (INTERNAL_ERROR, CHANGED)
            assert ext.left_out == ()

            assert ext.refresh() is None
            after = await digests(client)
            assert after[ALPHA]["skill://alpha/a.txt"] == sha("two\n")
            assert {r.uri: r.digest for r in (await entry(client, ALPHA)).skill.resources} == after[ALPHA]
            assert await read(client, "skill://alpha/a.txt") == b"two\n"
            assert ext.left_out == (LeftOutPath("alpha/.draft", "hidden"),)
            assert [(s.name, s.files) for s in ext.skills] == [("alpha", 2)]

        run(session(ext, body))

    def test_refresh_can_be_called_again_and_again_and_each_success_changes_the_generation(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "alpha")
        ext = SkillsExtension(root)
        generations = [ext.catalogue.generation]
        for _ in range(3):
            ext.refresh()
            generations.append(ext.catalogue.generation)
        assert len(set(generations)) == 4
        assert [s.name for s in ext.skills] == ["alpha"]


# --- Things that appear ---------------------------------------------------------------------------


class TestNewThings:
    def test_a_skill_added_on_disk_needs_the_server_and_is_then_readable(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "alpha")
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            first = ext.catalogue
            beta = write_skill(root, "beta", files={"b.txt": "bee\n"})
            with pytest.raises(SkillsError) as refused:  # the SDK was never given beta's files
                ext.refresh()
            assert refused.value.folder == str(real(beta))
            assert "server" in refused.value.reason and "refresh(" in refused.value.reason
            assert ext.catalogue is first  # nothing changed
            assert set(await digests(client)) == {ALPHA}
            assert "skill://beta/b.txt" not in await listed_resources(client)

            ext.refresh(server)
            ext.refresh()  # what was new has been given to the server, so no server is needed now
            assert set(await digests(client)) == {ALPHA, BETA}
            assert await read(client, "skill://beta/b.txt") == b"bee\n"
            assert await read(client, BETA) == (beta / "SKILL.md").read_bytes()
            assert {"skill://beta/b.txt", BETA} <= set(await listed_resources(client))
            assert [s.name for s in ext.skills] == ["alpha", "beta"]

        run(session(ext, body))

    def test_a_file_added_to_a_skill_is_the_same(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        alpha = write_skill(root, "alpha")
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            first = ext.catalogue
            (alpha / "notes").mkdir()
            (alpha / "notes" / "new.txt").write_text("fresh\n")
            with pytest.raises(SkillsError) as refused:
                ext.refresh()
            assert refused.value.folder == str(real(alpha))
            assert ext.catalogue is first
            assert "skill://alpha/notes/new.txt" not in (await digests(client))[ALPHA]
            ext.refresh(server)
            assert "skill://alpha/notes/new.txt" in (await digests(client))[ALPHA]
            assert await read(client, "skill://alpha/notes/new.txt") == b"fresh\n"

        run(session(ext, body))

    def test_a_refresh_with_a_server_and_nothing_new_adds_nothing_and_is_not_an_error(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "alpha", files={"a.txt": "one\n"})
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            before = set(await listed_resources(client))
            ext.refresh(server)
            ext.refresh(server)
            assert set(await listed_resources(client)) == before

        run(session(ext, body))


# --- Things that go ---------------------------------------------------------------------------------


class TestRemovedThings:
    def test_a_removed_file_is_not_read_any_more_but_stays_in_the_resource_list(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        skill = write_skill(root, "alpha", files={"a.txt": "one\n", "b.txt": "two\n"})
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            before = (await listed_resources(client))["skill://alpha/a.txt"]
            (skill / "a.txt").unlink()
            assert (await read_error(client, "skill://alpha/a.txt")).error.code == INTERNAL_ERROR  # not refreshed yet
            ext.refresh()
            gone = await read_error(client, "skill://alpha/a.txt")
            assert gone.error.code == INVALID_PARAMS
            assert CHANGED not in gone.error.message and str(tmp_path) not in gone.error.message
            assert "skill://alpha/a.txt" not in (await digests(client))[ALPHA]
            assert "skill://alpha/a.txt" not in {r.uri for r in (await entry(client, ALPHA)).skill.resources}
            after = (await listed_resources(client))["skill://alpha/a.txt"]  # the SDK cannot remove it
            assert (after.name, after.description, after.mime_type) == (before.name, before.description, before.mime_type)
            assert await read(client, "skill://alpha/b.txt") == b"two\n"

        run(session(ext, body))

    def test_a_removed_skill_is_neither_listed_nor_got_nor_read(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "alpha")
        beta = write_skill(root, "beta", files={"b.txt": "bee\n"})
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            assert set(await digests(client)) == {ALPHA, BETA}
            shutil.rmtree(beta)
            ext.refresh()
            assert set(await digests(client)) == {ALPHA}
            assert (await get_error(client, BETA)).error.code == INVALID_PARAMS
            for uri in (BETA, "skill://beta/b.txt"):
                assert (await read_error(client, uri)).error.code == INVALID_PARAMS
            assert [s.name for s in ext.skills] == ["alpha"]
            assert await read(client, ALPHA) == (root / "alpha" / "SKILL.md").read_bytes()

        run(session(ext, body))

    def test_a_resource_keeps_the_name_and_description_it_was_registered_with(self, tmp_path: Path) -> None:
        """The documented limit: `skills/get` shows the new frontmatter, `resources/list` the old."""
        root = tmp_path / "skills"
        skill = write_skill(root, "alpha", description="The first words.")
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            (skill / "SKILL.md").write_text("---\nname: alpha\ndescription: The second words.\n---\nBody\n")
            ext.refresh()
            assert (await entry(client, ALPHA)).skill.frontmatter["description"] == "The second words."
            assert (await listed_resources(client))[ALPHA].description == "The first words."
            assert await read(client, ALPHA) == (skill / "SKILL.md").read_bytes()  # and the bytes are the new ones

        run(session(ext, body))


# --- A bad edit -----------------------------------------------------------------------------------


class TestABadEdit:
    def test_a_failed_refresh_keeps_serving_the_old_catalogue_and_a_fix_recovers(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        skill = write_skill(root, "alpha", files={"a.txt": "one\n"})
        ext = SkillsExtension(root)

        async def body(server: MCPServer, client: Client) -> None:
            first = ext.catalogue
            before = await digests(client)
            good = (skill / "SKILL.md").read_text()
            (skill / "SKILL.md").write_text("no frontmatter now\n")
            with pytest.raises(SkillsError) as refused:
                ext.refresh()
            assert refused.value.folder == str(real(skill)) and "frontmatter" in refused.value.reason
            assert ext.catalogue is first and ext.catalogue.generation == first.generation
            assert await digests(client) == before  # the old entries, whole
            assert await read(client, "skill://alpha/a.txt") == b"one\n"  # a file that did not change still reads
            assert (await read_error(client, ALPHA)).error.code == INTERNAL_ERROR  # the edited one does not

            (skill / "SKILL.md").write_text(good.replace("Does one thing.", "Does it better."))
            ext.refresh()
            assert ext.catalogue.generation != first.generation
            assert (await entry(client, ALPHA)).skill.frontmatter["description"] == "Does it better."
            assert await read(client, ALPHA) == (skill / "SKILL.md").read_bytes()

        run(session(ext, body))

    def test_a_refresh_that_leaves_nothing_to_serve_is_an_error_and_keeps_the_old_catalogue(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        alpha = write_skill(root, "alpha")
        ext = SkillsExtension(root)
        first = ext.catalogue
        shutil.rmtree(alpha)
        with pytest.raises(SkillsError):
            ext.refresh()
        assert ext.catalogue is first and [s.name for s in ext.skills] == ["alpha"]

    def test_a_refresh_uses_the_same_filters_and_the_same_folders(self, tmp_path: Path) -> None:
        first, second = tmp_path / "first", tmp_path / "second"
        write_skill(first, "alpha")
        write_skill(first, "draft-one")
        write_skill(second, "beta")
        ext = SkillsExtension([first, second], exclude=["draft-*"])
        assert [s.name for s in ext.skills] == ["alpha", "beta"]
        write_skill(first, "draft-two")
        write_skill(second, "gamma")
        server = MCPServer("skills-refresh", extensions=[ext])
        ext.refresh(server)
        assert [s.name for s in ext.skills] == ["alpha", "beta", "gamma"]  # `gamma` is new, the drafts are still out


class TestTheSameFolders:
    def test_a_relative_folder_is_the_same_folder_after_a_chdir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """"The same folders" means the same ones even if the process has moved since."""
        home, elsewhere = tmp_path / "home", tmp_path / "elsewhere"
        write_skill(home / "skills", "alpha")
        write_skill(elsewhere / "skills", "decoy")  # what a refresh would find if it read `skills` from the new place
        monkeypatch.chdir(home)
        ext = SkillsExtension("skills")
        monkeypatch.chdir(elsewhere)
        ext.refresh()
        assert [s.name for s in ext.skills] == ["alpha"]

    def test_a_folder_that_is_a_link_is_followed_again_by_each_refresh(self, tmp_path: Path) -> None:
        """An owner who points a link at the next version of the skills and refreshes gets the next version."""
        one, two = tmp_path / "v1", tmp_path / "v2"
        write_skill(one, "alpha")
        write_skill(two, "alpha", files={"new.txt": "n\n"})
        link = tmp_path / "current"
        link.symlink_to(one, target_is_directory=True)
        ext = SkillsExtension(link)
        assert ext.skills[0].files == 1
        link.unlink()
        link.symlink_to(two, target_is_directory=True)
        server = MCPServer("skills-refresh", extensions=[ext])
        ext.refresh(server)
        assert ext.skills[0].files == 2


# --- What is logged -------------------------------------------------------------------------------


class TestTheLogOfARefresh:
    def test_a_refresh_says_what_it_now_serves(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        root = tmp_path / "skills"
        write_skill(root, "alpha")
        ext = SkillsExtension(root)
        server = MCPServer("skills-refresh", extensions=[ext])
        write_skill(root, "beta")
        with caplog.at_level(logging.INFO, logger="ext_r2c.mcp.skills"):
            caplog.clear()
            ext.refresh(server)
        lines = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert len(lines) == 2 and any(BETA in line for line in lines) and any(ALPHA in line for line in lines)

    def test_a_failed_refresh_logs_nothing_it_did_not_do(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        root = tmp_path / "skills"
        alpha = write_skill(root, "alpha")
        ext = SkillsExtension(root)
        (alpha / "SKILL.md").write_text("nothing\n")
        with caplog.at_level(logging.INFO, logger="ext_r2c.mcp.skills"):
            caplog.clear()
            with pytest.raises(SkillsError):
                ext.refresh()
        assert [r for r in caplog.records if r.levelno >= logging.INFO] == []


# --- A burst of requests while refreshes run -------------------------------------------------------


class TestWhileRefreshing:
    def test_a_burst_of_lists_is_never_a_mix_of_two_generations(self, tmp_path: Path) -> None:
        """Two skills whose files are edited together, then scanned, again and again in a thread. Every
        `skills/list` must hold both skills, and both with the files of the same edit."""
        root = tmp_path / "skills"
        alpha = write_skill(root, "alpha", files={"a.txt": "alpha 0\n"})
        beta = write_skill(root, "beta", files={"b.txt": "beta 0\n"})
        ext = SkillsExtension(root)
        allowed = {(sha(f"alpha {n}\n"), sha(f"beta {n}\n")) for n in (0, 1)}
        stop, errors, refreshes = threading.Event(), [], []

        def writer() -> None:
            version = 0
            try:
                while not stop.is_set():
                    version ^= 1
                    (alpha / "a.txt").write_text(f"alpha {version}\n")  # the same size: only the digest changes
                    (beta / "b.txt").write_text(f"beta {version}\n")
                    ext.refresh()
                    refreshes.append(version)
            except BaseException as error:  # reported by the test, not lost in the thread
                errors.append(error)

        async def body(server: MCPServer, client: Client) -> tuple[set[tuple[str, str]], int]:
            seen: set[tuple[str, str]] = set()
            count = 0
            # Until both edits were seen and the writer has refreshed 20 times (so that requests and
            # refreshes overlapped), but at most 3000 requests: the assertions after the run say if it fell short.
            while count < 150 or ((len(seen) < 2 or len(refreshes) < 20) and count < 3000):
                await anyio.sleep(0.001)  # lets the writer thread have the interpreter between two requests
                listing = await digests(client)
                assert set(listing) == {ALPHA, BETA}, "a list that is missing a skill"
                pair = (listing[ALPHA]["skill://alpha/a.txt"], listing[BETA]["skill://beta/b.txt"])
                assert pair in allowed, "the digests of two different edits in one list"
                seen.add(pair)
                count += 1
            return seen, count

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            seen, count = run(session(ext, body))
        finally:
            stop.set()
            thread.join(30)
        assert not thread.is_alive() and errors == []
        assert len(refreshes) >= 20 and len(seen) == 2, "the refreshes did not overlap the requests"
        assert count >= 150


def test_refresh_is_not_a_coroutine() -> None:
    """It blocks while it scans, and says so: an owner calls it from startup code, a signal handler or a thread."""
    import inspect

    assert not inspect.iscoroutinefunction(SkillsExtension.refresh)
    assert list(inspect.signature(SkillsExtension.refresh).parameters) == ["self", "server"]
