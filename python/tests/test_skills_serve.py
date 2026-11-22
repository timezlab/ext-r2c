"""Serving skills from folders, end to end (spec 005, story 1, SC-001): a real MCP SDK client talks to
a real `MCPServer` that carries `SkillsExtension`, over the in-process streaming transport. What a
server must serve is worked out from the disk by `skills_fixtures.Fixture.expected()` and `hashlib`,
never by package code. Requests are the package's typed ones (research R2)."""

from __future__ import annotations

import base64
import hashlib
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import unquote

import ext_r2c.mcp
import ext_r2c.mcp.skills as skills_package
import pytest
from ext_r2c.mcp.skills import SkillInfo, SkillsExtension
from ext_r2c.mcp.skills._catalogue import Catalogue
from ext_r2c.mcp.skills._wire import (
    EXTENSION_ID,
    GetSkillParams,
    GetSkillRequest,
    GetSkillResult,
    ListSkillsRequest,
    ListSkillsResult,
    Skill,
)
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp_harness import mcp_client, run, serve
from mcp_transport import Record
from skills_fixtures import Fixture, standard_tree

T = TypeVar("T")
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
CHANGED = "The skills changed on disk since they were scanned; refresh them."

FRONTMATTER = {
    "skill://greetings/SKILL.md": {"name": "greetings", "description": "Says hello in many languages."},
    "skill://pdf-notes/SKILL.md": {"name": "pdf-notes", "description": "Takes notes from a PDF."},
    "skill://team/billing/refunds/SKILL.md": {
        "name": "refunds",
        "description": "Handles refund requests.",
        "license": "MIT",
        "metadata": {"owner": "billing", "tags": ["refunds", "support"]},
    },
}
MIME = {"md": "text/markdown", "txt": "text/plain", "sh": "text/x-shellscript", "bin": "application/octet-stream"}


async def talk(ext: SkillsExtension, body: Callable[[Client], Awaitable[T]], *, record: Record | None = None) -> T:
    """Serve `ext` on a plain `MCPServer`, connect an SDK client that knows nothing of the extension,
    and run `body` with it."""
    server = MCPServer("skills-test", extensions=[ext])
    async with serve(server, record=record) as served, mcp_client(served, active=False, form=False) as client:
        return await body(client)


async def list_skills(client: Client) -> ListSkillsResult:
    return await client.session.send_request(ListSkillsRequest(), ListSkillsResult)


async def get_skill(client: Client, uri: str) -> GetSkillResult:
    return await client.session.send_request(GetSkillRequest(params=GetSkillParams(uri=uri)), GetSkillResult)


def wire_results(record: Record, method: str) -> list[dict[str, Any]]:
    """The raw `result` of every response to a request of `method`, as it was on the wire."""
    ids = [m["id"] for side, m in record if side == "client" and m.get("method") == method and "id" in m]
    return [m["result"] for side, m in record if side == "remote" and m.get("id") in ids and "result" in m]


def entry_of(skill: Skill) -> dict[str, Any]:
    return skill.model_dump(mode="json", by_alias=True, exclude_none=True)


def files_of(tree: Fixture, skill_uri: str) -> dict[str, bytes]:
    """The bytes of every file of one skill, from the disk."""
    prefix = skill_uri.removesuffix("SKILL.md")
    return {uri: data for uri, data in tree.expected().items() if uri.startswith(prefix)}


def suffix_of(uri: str) -> str:
    return uri.rpartition(".")[2]


# --- The extension object -------------------------------------------------------------------------


class TestTheObject:
    def test_it_is_the_skills_extension(self, tmp_path: Path) -> None:
        ext = SkillsExtension(standard_tree(tmp_path).root)
        assert ext.identifier == EXTENSION_ID == "io.modelcontextprotocol/skills"
        assert isinstance(ext.catalogue, Catalogue)
        assert ext.settings() == {"directoryRead": True}
        assert SkillsExtension(standard_tree(tmp_path).root, directory_read=False).settings() == {"directoryRead": False}

    def test_it_is_exported_from_the_package_and_from_the_door(self) -> None:
        assert ext_r2c.mcp.SkillsExtension is skills_package.SkillsExtension is SkillsExtension
        assert ext_r2c.mcp.SkillInfo is skills_package.SkillInfo is SkillInfo
        assert {"SkillsExtension", "SkillInfo"} <= set(skills_package.__all__)
        assert {"SkillsExtension", "SkillInfo"} <= set(ext_r2c.mcp.__all__)

    def test_a_folder_is_a_path_a_string_or_a_list_never_a_list_of_characters(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        uris = [[s.uri for s in SkillsExtension(folders).skills] for folders in (root, str(root), [root], [str(root)])]
        assert len(uris[0]) == 3 and uris.count(uris[0]) == 4

    def test_skills_tells_the_owner_what_is_served(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        infos = SkillsExtension(tree.root).skills
        assert [(i.name, i.uri, i.description) for i in infos] == [
            (frontmatter["name"], uri, frontmatter["description"]) for uri, frontmatter in FRONTMATTER.items()
        ]
        for info in infos:
            files = files_of(tree, info.uri)
            assert (info.files, info.size) == (len(files), sum(len(data) for data in files.values()))
        assert infos == tuple(infos) and all(isinstance(i, SkillInfo) for i in infos)


# --- Scenario 1: the declaration ------------------------------------------------------------------


class TestDeclaration:
    def test_discover_declares_resources_and_the_extension(self, tmp_path: Path) -> None:
        async def body(client: Client) -> Any:
            return client.server_capabilities

        caps = run(talk(SkillsExtension(standard_tree(tmp_path).root), body))
        assert caps.resources is not None
        assert caps.extensions is not None and set(caps.extensions) == {EXTENSION_ID}
        # `directoryRead` is true because the directory method is served (and false when it is not).
        assert caps.extensions[EXTENSION_ID] == {"directoryRead": True}


# --- Scenario 2: skills/list ----------------------------------------------------------------------


class TestList:
    def test_one_entry_per_skill_with_every_file_once_and_its_digest_and_size(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        record: Record = []
        listed = run(talk(SkillsExtension(tree.root), list_skills, record=record))
        [wire] = wire_results(record, "skills/list")
        assert wire["resultType"] == "complete"
        assert "nextCursor" not in wire  # three skills fit on a page of 25 (`test_skills_pages.py` has the rest)
        assert [e["uri"] for e in wire["skills"]] == list(FRONTMATTER)
        for entry in wire["skills"]:
            assert set(entry) == {"uri", "frontmatter", "resources"}  # no `_meta`
            assert entry["frontmatter"] == FRONTMATTER[entry["uri"]]  # extra fields unchanged
            files = files_of(tree, entry["uri"])
            uris = [r["uri"] for r in entry["resources"]]
            assert uris.count(entry["uri"]) == 1  # SKILL.md once
            assert sorted(uris) == sorted(files) and len(uris) == len(set(uris))
            for resource in entry["resources"]:
                data = files[resource["uri"]]
                assert set(resource) == {"uri", "digest", "size"}
                assert resource["size"] == len(data)
                assert resource["digest"] == "sha256:" + hashlib.sha256(data).hexdigest()
        assert [entry_of(s) for s in listed.skills] == wire["skills"]  # the typed model reads the same

    def test_the_default_cache_hints_are_five_minutes_and_private(self, tmp_path: Path) -> None:
        record: Record = []
        run(talk(SkillsExtension(standard_tree(tmp_path).root), list_skills, record=record))
        [wire] = wire_results(record, "skills/list")
        assert (wire["ttlMs"], wire["cacheScope"]) == (300_000, "private")


# --- Scenario 3: skills/get -----------------------------------------------------------------------


class TestGet:
    def test_get_returns_the_list_entry_plus_the_cache_hints(self, tmp_path: Path) -> None:
        record: Record = []

        async def body(client: Client) -> None:
            for uri in FRONTMATTER:
                await get_skill(client, uri)
            await list_skills(client)

        run(talk(SkillsExtension(standard_tree(tmp_path).root), body, record=record))
        [listed] = wire_results(record, "skills/list")
        gets = wire_results(record, "skills/get")
        assert [g["skill"] for g in gets] == listed["skills"]
        for wire in gets:
            assert wire["resultType"] == "complete"
            assert (wire["ttlMs"], wire["cacheScope"]) == (300_000, "private")

    @pytest.mark.parametrize(
        "uri",
        [
            "skill://nothing-here/SKILL.md",
            "skill://pdf-notes/reference.md",  # a supporting file of a skill is not a skill
            "skill://team/billing/refunds/examples/SKILL.md",  # a nested SKILL.md is a file, not a skill
            "skill://pdf-notes",
            "skill://pdf-notes/",
            "skill://team/billing/SKILL.md",  # a prefix above a skill
            "",
        ],
    )
    def test_anything_but_a_skills_skill_md_uri_is_invalid_params(self, tmp_path: Path, uri: str) -> None:
        async def body(client: Client) -> MCPError:
            with pytest.raises(MCPError) as refused:
                await get_skill(client, uri)
            return refused.value

        error = run(talk(SkillsExtension(standard_tree(tmp_path).root), body))
        assert error.error.code == INVALID_PARAMS
        assert str(tmp_path) not in error.error.message  # a request never makes the server name a host path


# --- Scenario 4: resources/read (SC-001) ----------------------------------------------------------


class TestRead:
    def test_every_file_of_every_skill_comes_back_byte_for_byte(self, tmp_path: Path) -> None:
        """SC-001. `text` where the bytes are UTF-8 (a byte-order mark and CRLF included), `blob`
        where they are not (a binary file, a Latin-1 file)."""
        tree = standard_tree(tmp_path)
        expected = tree.expected()

        async def body(client: Client) -> dict[str, Any]:
            return {uri: (await client.read_resource(uri)).contents for uri in expected}

        got = run(talk(SkillsExtension(tree.root), body))
        assert len(expected) == 12  # four files in each of the three skills
        for uri, data in expected.items():
            [content] = got[uri]
            assert str(content.uri) == uri
            try:
                text: str | None = data.decode("utf-8")
            except UnicodeDecodeError:
                text = None
            if text is None:
                assert not hasattr(content, "text") and base64.b64decode(content.blob) == data, uri
            else:
                assert not hasattr(content, "blob") and content.text.encode("utf-8") == data, uri
            assert content.mime_type == MIME[suffix_of(uri)], uri
        blobs = sorted(uri for uri, [c] in got.items() if hasattr(c, "blob"))
        assert blobs == ["skill://greetings/legacy.txt", "skill://pdf-notes/assets/logo.bin"]
        assert got["skill://greetings/windows.txt"][0].text == "﻿line one\r\nline two\r\n"

    def test_skill_md_is_markdown(self, tmp_path: Path) -> None:
        async def body(client: Client) -> list[str]:
            return [(await client.read_resource(uri)).contents[0].mime_type for uri in FRONTMATTER]

        assert run(talk(SkillsExtension(standard_tree(tmp_path).root), body)) == ["text/markdown"] * 3

    def test_a_read_runs_off_the_event_loop(self, tmp_path: Path) -> None:
        threads: list[int] = []

        class Spy(SkillsExtension):
            def _read_bytes(self, record: Any) -> bytes:
                threads.append(threading.get_ident())
                return super()._read_bytes(record)

        async def body(client: Client) -> int:
            await client.read_resource("skill://pdf-notes/reference.md")
            return threading.get_ident()

        loop_thread = run(talk(Spy(standard_tree(tmp_path).root), body))
        assert len(threads) == 1 and threads[0] != loop_thread


# --- Scenario 5: a client that does not know the extension ----------------------------------------


class TestAsOrdinaryResources:
    def test_resources_list_shows_every_file_and_skill_md_carries_the_frontmatters_name_and_description(
        self, tmp_path: Path
    ) -> None:
        tree = standard_tree(tmp_path)

        async def body(client: Client) -> Any:
            return (await client.list_resources()).resources

        resources = run(talk(SkillsExtension(tree.root), body))
        by_uri = {str(r.uri): r for r in resources}
        assert sorted(by_uri) == sorted(tree.expected()) and len(resources) == len(by_uri)
        for uri, frontmatter in FRONTMATTER.items():
            resource = by_uri[uri]
            assert (resource.name, resource.description) == (frontmatter["name"], frontmatter["description"])
            assert resource.mime_type == "text/markdown"
        other = by_uri["skill://team/billing/refunds/templates/reply.md"]
        assert (other.name, other.description, other.mime_type) == ("reply.md", None, "text/markdown")
        nested = by_uri["skill://team/billing/refunds/examples/SKILL.md"]
        assert nested.name == "SKILL.md" and nested.description is None  # a file, not the skill's own
        assert by_uri["skill://greetings/caf%C3%A9.md"].name == unquote("caf%C3%A9.md") == "café.md"


# --- Scenario 6: cache hints ----------------------------------------------------------------------


class TestCacheHints:
    def test_ttl_and_scope_appear_on_the_list_and_on_the_get(self, tmp_path: Path) -> None:
        record: Record = []

        async def body(client: Client) -> None:
            await list_skills(client)
            await get_skill(client, "skill://pdf-notes/SKILL.md")

        run(talk(SkillsExtension(standard_tree(tmp_path).root, ttl_ms=1000, cache_scope="public"), body, record=record))
        [listed] = wire_results(record, "skills/list")
        [got] = wire_results(record, "skills/get")
        assert (listed["ttlMs"], listed["cacheScope"]) == (1000, "public")
        assert (got["ttlMs"], got["cacheScope"]) == (1000, "public")


# --- Scenario 7: nothing of the package's own on the wire -----------------------------------------


class TestNothingExtra:
    def test_no_result_carries_a_meta_key_of_this_package(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        record: Record = []

        async def body(client: Client) -> None:
            await list_skills(client)
            await get_skill(client, "skill://pdf-notes/SKILL.md")
            await client.list_resources()
            await client.read_resource("skill://pdf-notes/SKILL.md")

        run(talk(SkillsExtension(tree.root), body, record=record))
        for method in ("skills/list", "skills/get", "resources/list", "resources/read"):
            results = wire_results(record, method)
            assert results, method
            for result in results:
                assert not any("skills" in key or "r2c" in key for key in result.get("_meta", {})), (method, result)

        def below(value: Any) -> list[dict[str, Any]]:
            """Every object in a JSON value that is not the top-level result."""
            if isinstance(value, dict):
                return [value, *[o for v in value.values() for o in below(v)]]
            if isinstance(value, list):
                return [o for v in value for o in below(v)]
            return []

        for method in ("skills/list", "skills/get", "resources/list", "resources/read"):
            for result in wire_results(record, method):
                nested = [o for v in result.values() for o in below(v)]
                assert not any("_meta" in o for o in nested), (method, nested)


# --- The two points a test uses to make a server lie ----------------------------------------------


class TestOverridePoints:
    def test_entry_is_where_the_list_and_the_get_get_each_skill(self, tmp_path: Path) -> None:
        class Liar(SkillsExtension):
            def _entry(self, skill: Any) -> Skill:
                entry = super()._entry(skill)
                entry.resources[0].digest = "sha256:" + "f" * 64
                return entry

        async def body(client: Client) -> tuple[ListSkillsResult, GetSkillResult]:
            return await list_skills(client), await get_skill(client, "skill://pdf-notes/SKILL.md")

        listed, got = run(talk(Liar(standard_tree(tmp_path).root), body))
        assert all(s.resources[0].digest == "sha256:" + "f" * 64 for s in listed.skills)
        assert got.skill.resources[0].digest == "sha256:" + "f" * 64

    def test_read_bytes_is_where_a_read_gets_its_bytes(self, tmp_path: Path) -> None:
        class Liar(SkillsExtension):
            def _read_bytes(self, record: Any) -> bytes:
                return b"not what is on disk"

        async def body(client: Client) -> Any:
            return (await client.read_resource("skill://pdf-notes/reference.md")).contents[0]

        assert run(talk(Liar(standard_tree(tmp_path).root), body)).text == "not what is on disk"


# --- A file that is not what the scan saw ---------------------------------------------------------


class TestChangedOnDisk:
    @pytest.mark.parametrize(
        "change",
        [
            pytest.param(lambda data: data[:-1] + b"X", id="same size, other bytes"),
            pytest.param(lambda data: data + b"more", id="grew"),
            pytest.param(lambda data: data[:3], id="shrank"),
            pytest.param(lambda data: b"", id="emptied"),
        ],
    )
    def test_a_read_after_a_change_is_an_internal_error_with_no_bytes(self, tmp_path: Path, change: Any) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        target = tree.root / "pdf-notes" / "reference.md"
        target.write_bytes(change(target.read_bytes()))

        async def body(client: Client) -> tuple[MCPError, Any]:
            with pytest.raises(MCPError) as refused:
                await client.read_resource("skill://pdf-notes/reference.md")
            # a file that did not change is still served, so one change does not take the rest down
            return refused.value, await client.read_resource("skill://pdf-notes/scripts/run.sh")

        error, other = run(talk(ext, body))
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)
        assert str(tmp_path) not in error.error.message
        assert other.contents[0].text == "#!/bin/sh\necho notes\n"

    def test_skill_md_is_checked_like_any_other_file(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        target = tree.root / "greetings" / "SKILL.md"
        target.write_bytes(target.read_bytes().replace(b"hello", b"HELLO"))

        async def body(client: Client) -> MCPError:
            with pytest.raises(MCPError) as refused:
                await client.read_resource("skill://greetings/SKILL.md")
            return refused.value

        assert run(talk(ext, body)).error.code == INTERNAL_ERROR

    def test_a_deleted_file_is_an_internal_error_too(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        ext = SkillsExtension(tree.root)
        (tree.root / "pdf-notes" / "reference.md").unlink()

        async def body(client: Client) -> MCPError:
            with pytest.raises(MCPError) as refused:
                await client.read_resource("skill://pdf-notes/reference.md")
            return refused.value

        error = run(talk(ext, body))
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)
