"""Reading the files of a skill folder by directory (spec 005, story 6, FR-013): `resources/directory/read`
answers the direct children of a directory of a served skill, from the catalogue and never from the
disk; the client's `list_directory` asks for a skill's own directories only. A real MCP SDK client talks
to a real `MCPServer`. What is true is worked out from the disk and written out here, never taken from
package code.

Part A: the server. Part B: the client."""

from __future__ import annotations

import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote

import mcp_types as types
import pytest
from ext_r2c.mcp.skills import DirectoryEntry, SkillItem, SkillRefused, SkillsClient, SkillsExtension
from ext_r2c.mcp.skills._wire import (
    EXTENSION_ID,
    ListSkillsRequest,
    ListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryRequest,
    ReadDirectoryResult,
)
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp_harness import mcp_client, run, serve
from mcp_transport import Record
from skills_fixtures import Fixture, add_symlink, outside_secret, standard_tree, write_skill

T = TypeVar("T")
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
METHOD_NOT_FOUND = -32601
CHANGED = "The skills changed on disk since they were scanned; refresh them."
FIXED = "Invalid cursor"
DIR = "inode/directory"
METHOD = "resources/directory/read"

REFUNDS = "skill://team/billing/refunds"
PDF = "skill://pdf-notes"
GREETINGS = "skill://greetings"


# --- The helpers ----------------------------------------------------------------------------------


async def talk(ext: SkillsExtension | MCPServer, body: Callable[[Client], Awaitable[T]], *, record: Record | None = None) -> T:
    server = ext if isinstance(ext, MCPServer) else MCPServer("skills-test", extensions=[ext])
    async with serve(server, record=record) as served, mcp_client(served, active=False, form=False) as client:
        return await body(client)


async def read_directory(client: Client, uri: str, cursor: str | None = None) -> ReadDirectoryResult:
    params = ReadDirectoryParams(uri=uri) if cursor is None else ReadDirectoryParams(uri=uri, cursor=cursor)
    return await client.session.send_request(ReadDirectoryRequest(params=params), ReadDirectoryResult)


def sent(record: Record, method: str) -> list[dict[str, Any]]:
    return [m for side, m in record if side == "client" and m.get("method") == method]


def wire_results(record: Record, method: str) -> list[dict[str, Any]]:
    ids = [m["id"] for m in sent(record, method) if "id" in m]
    return [m["result"] for side, m in record if side == "remote" and m.get("id") in ids and "result" in m]


def tree_with_an_empty_folder(tmp_path: Path) -> Fixture:
    """The standard tree, and an empty folder in `refunds`."""
    tree = standard_tree(tmp_path)
    (tree.root / "team" / "billing" / "refunds" / "empty").mkdir()
    return tree


def disk_directories(tree: Fixture) -> set[str]:
    """The URI of every folder of every skill, the skill folder itself included, from the disk."""
    found: set[str] = set()
    for name in tree.names:
        skill = tree.root / name
        for folder in [skill, *(p for p in skill.rglob("*") if p.is_dir())]:
            parts = [*name.split("/"), *folder.relative_to(skill).parts]
            found.add("skill://" + "/".join(quote(part, safe="") for part in parts))
    return found


def names_of(result: ReadDirectoryResult) -> list[str]:
    return [child.name for child in result.resources]


# --- Part A: the server ---------------------------------------------------------------------------


class TestDeclaration:
    def test_a_directory_read_is_on_by_default_and_discovery_says_so(self, tmp_path: Path) -> None:
        async def body(client: Client) -> Any:
            return client.server_capabilities

        caps = run(talk(SkillsExtension(standard_tree(tmp_path).root), body))
        assert caps.extensions is not None
        assert caps.extensions[EXTENSION_ID] == {"directoryRead": True}
        assert caps.extensions[EXTENSION_ID]["directoryRead"] is True  # a boolean, not `1`

    def test_with_it_off_discovery_says_false_and_the_method_is_not_there(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        ext = SkillsExtension(root, directory_read=False)
        assert ext.settings() == {"directoryRead": False}

        async def body(client: Client) -> tuple[Any, MCPError]:
            with pytest.raises(MCPError) as caught:
                await read_directory(client, REFUNDS)
            return client.server_capabilities, caught.value

        caps, error = run(talk(ext, body))
        assert caps.extensions is not None and caps.extensions[EXTENSION_ID] == {"directoryRead": False}
        assert caps.extensions[EXTENSION_ID]["directoryRead"] is False
        assert error.error.code == METHOD_NOT_FOUND  # what the base protocol says of a method it does not know

    def test_with_it_off_the_other_methods_work_as_before(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root

        async def body(client: Client) -> tuple[int, int]:
            listed = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
            read = await client.read_resource("skill://pdf-notes/reference.md")
            return len(listed.skills), len(read.contents)

        assert run(talk(SkillsExtension(root, directory_read=False), body)) == (3, 1)

    def test_the_client_follows_what_the_server_declared(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root

        async def body(client: Client) -> bool:
            return SkillsClient(client, origin="docs").directory_read

        assert run(talk(SkillsExtension(root), body)) is True
        assert run(talk(SkillsExtension(root, directory_read=False), body)) is False

    @pytest.mark.parametrize("value", ["yes", 1, 0, None, "true"])
    def test_directory_read_is_a_boolean(self, tmp_path: Path, value: Any) -> None:
        with pytest.raises(ValueError, match="directory_read"):
            SkillsExtension(standard_tree(tmp_path).root, directory_read=value)


class TestTheChildren:
    def test_the_root_of_a_skill_lists_its_direct_children_and_nothing_below(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        record: Record = []

        async def body(client: Client) -> ReadDirectoryResult:
            return await read_directory(client, REFUNDS)

        result = run(talk(SkillsExtension(root), body, record=record))
        # By name: "SKILL.md" comes first (a capital sorts before a small letter), folders among the files.
        assert names_of(result) == ["refunds", "empty", "examples", "notes.txt", "templates"]
        (wire,) = wire_results(record, METHOD)
        assert wire["resources"] == [
            {
                "uri": f"{REFUNDS}/SKILL.md",
                "name": "refunds",  # the frontmatter's name and description, as in resources/list
                "description": "Handles refund requests.",
                "mimeType": "text/markdown",
            },
            {"uri": f"{REFUNDS}/empty", "name": "empty", "mimeType": DIR},
            {"uri": f"{REFUNDS}/examples", "name": "examples", "mimeType": DIR},
            {"uri": f"{REFUNDS}/notes.txt", "name": "notes.txt", "mimeType": "text/plain"},
            {"uri": f"{REFUNDS}/templates", "name": "templates", "mimeType": DIR},
        ]
        assert "nextCursor" not in wire
        assert wire["resultType"] == "complete" and wire["ttlMs"] == 300_000 and wire["cacheScope"] == "private"

    def test_a_nested_directory_lists_its_own_children(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        record: Record = []

        async def body(client: Client) -> list[ReadDirectoryResult]:
            return [
                await read_directory(client, f"{REFUNDS}/templates"),
                await read_directory(client, f"{PDF}/assets"),
                await read_directory(client, f"{PDF}/scripts"),
            ]

        run(talk(SkillsExtension(root), body, record=record))
        assert [r["resources"] for r in wire_results(record, METHOD)] == [
            [{"uri": f"{REFUNDS}/templates/reply.md", "name": "reply.md", "mimeType": "text/markdown"}],
            [{"uri": f"{PDF}/assets/logo.bin", "name": "logo.bin", "mimeType": "application/octet-stream"}],
            [{"uri": f"{PDF}/scripts/run.sh", "name": "run.sh", "mimeType": "text/x-shellscript"}],
        ]

    def test_a_skill_md_below_the_root_is_an_ordinary_file_with_the_name_of_a_file(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        record: Record = []

        async def body(client: Client) -> ReadDirectoryResult:
            return await read_directory(client, f"{REFUNDS}/examples")

        run(talk(SkillsExtension(root), body, record=record))
        (wire,) = wire_results(record, METHOD)
        assert wire["resources"] == [{"uri": f"{REFUNDS}/examples/SKILL.md", "name": "SKILL.md", "mimeType": "text/markdown"}]

    def test_a_name_that_is_not_ascii_is_a_name_and_its_uri_is_encoded(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        record: Record = []

        async def body(client: Client) -> ReadDirectoryResult:
            return await read_directory(client, GREETINGS)

        result = run(talk(SkillsExtension(root), body, record=record))
        assert names_of(result) == ["greetings", "café.md", "legacy.txt", "windows.txt"]
        (wire,) = wire_results(record, METHOD)
        assert wire["resources"][1] == {"uri": "skill://greetings/caf%C3%A9.md", "name": "café.md", "mimeType": "text/markdown"}

    def test_an_empty_directory_answers_an_empty_list(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        record: Record = []

        async def body(client: Client) -> ReadDirectoryResult:
            return await read_directory(client, f"{REFUNDS}/empty")

        run(talk(SkillsExtension(root), body, record=record))
        (wire,) = wire_results(record, METHOD)
        assert wire["resources"] == [] and "nextCursor" not in wire  # present, not left out
        assert wire["resultType"] == "complete"

    def test_a_folder_that_holds_only_what_is_never_served_is_empty_too(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        outside = outside_secret(tmp_path)
        cache = tree.root / "pdf-notes" / "cache"
        cache.mkdir()
        (cache / ".keep").write_text("hidden\n")
        add_symlink(cache / "link.txt", outside)

        async def body(client: Client) -> tuple[list[str], list[str]]:
            return names_of(await read_directory(client, f"{PDF}/cache")), names_of(await read_directory(client, PDF))

        cache_names, pdf_names = run(talk(SkillsExtension(tree.root), body))
        assert cache_names == []
        assert pdf_names == ["pdf-notes", "assets", "cache", "reference.md", "scripts"]

    def test_the_settings_of_the_cache_are_on_every_answer(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        record: Record = []

        async def body(client: Client) -> None:
            await read_directory(client, PDF)

        run(talk(SkillsExtension(root, ttl_ms=1234, cache_scope="public"), body, record=record))
        (wire,) = wire_results(record, METHOD)
        assert (wire["ttlMs"], wire["cacheScope"]) == (1234, "public")

    def test_a_child_is_described_as_resources_list_describes_it(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> tuple[dict[str, tuple[str, Any, str]], dict[str, tuple[str, Any, str]]]:
            listed = {
                str(r.uri): (r.name, r.description, r.mime_type or "") for r in (await client.list_resources()).resources
            }
            seen: dict[str, tuple[str, Any, str]] = {}
            for directory in (GREETINGS, PDF, f"{PDF}/assets", f"{PDF}/scripts", REFUNDS, f"{REFUNDS}/examples", f"{REFUNDS}/templates"):
                for child in (await read_directory(client, directory)).resources:
                    if child.mime_type != DIR:
                        seen[str(child.uri)] = (child.name, child.description, child.mime_type or "")
            return listed, seen

        listed, seen = run(talk(SkillsExtension(root), body))
        assert seen == listed and len(seen) == 12  # three skills of four files each

    def test_directories_are_not_resources(self, tmp_path: Path) -> None:
        tree = tree_with_an_empty_folder(tmp_path)

        async def body(client: Client) -> set[str]:
            return {str(r.uri) for r in (await client.list_resources()).resources}

        listed = run(talk(SkillsExtension(tree.root), body))
        assert listed == set(tree.expected())  # files only
        assert not listed & disk_directories(tree)

    def test_the_files_reached_through_directories_are_the_files_of_the_entries(self, tmp_path: Path) -> None:
        tree = tree_with_an_empty_folder(tmp_path)

        async def body(client: Client) -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
            skills = []  # every page: with a page size of 2 the three skills are on two pages
            listed = await client.session.send_request(ListSkillsRequest(), ListSkillsResult)
            skills.extend(listed.skills)
            while listed.next_cursor is not None:
                request = ListSkillsRequest(params=types.PaginatedRequestParams(cursor=listed.next_cursor))
                listed = await client.session.send_request(request, ListSkillsResult)
                skills.extend(listed.skills)
            assert len(skills) == 3
            entries = {s.uri: {r.uri for r in s.resources} for s in skills}
            reached: dict[str, set[str]] = {}
            folders: set[str] = set()
            for skill in skills:
                root = skill.uri.removesuffix("/SKILL.md")
                todo, files = [root], set()
                while todo:
                    uri = todo.pop()
                    folders.add(uri)
                    cursor = None
                    while True:
                        page = await read_directory(client, uri, cursor)
                        for child in page.resources:
                            if child.mime_type == DIR:
                                todo.append(str(child.uri))
                            else:
                                files.add(str(child.uri))
                        cursor = page.next_cursor
                        if cursor is None:
                            break
                reached[skill.uri] = files
            return entries, reached, folders

        entries, reached, folders = run(talk(SkillsExtension(tree.root, page_size=2), body))
        assert reached == entries
        assert {uri for files in reached.values() for uri in files} == set(tree.expected())
        assert folders == disk_directories(tree)  # every folder of the disk, the empty one too, and no other


class TestNotADirectory:
    TABLE = {
        "a prefix above skills": "skill://team/billing",
        "the first segment alone": "skill://team",
        "a file": f"{PDF}/reference.md",
        "a skill's SKILL.md": f"{PDF}/SKILL.md",
        "an unknown skill": "skill://nothing",
        "an unknown folder": f"{PDF}/nothing",
        "a trailing slash": f"{PDF}/",
        "a trailing slash below": f"{PDF}/assets/",
        "dot dot": f"{PDF}/..",
        "dot dot between folders": f"{PDF}/assets/../scripts",
        "dot": f"{PDF}/.",
        "an encoded dot dot": f"{PDF}/%2e%2e",
        "a folder name in capitals": f"{PDF}/ASSETS",
        "the skill in capitals": "skill://PDF-NOTES",
        "the first segment in capitals": "skill://TEAM/billing/refunds",
        "a query": f"{PDF}?x=1",
        "a fragment": f"{PDF}#top",
        "a doubled slash": f"{PDF}//assets",
        "a hidden folder": f"{PDF}/.git",
        "another scheme": "file:///etc",
        "the scheme alone": "skill://",
        "an absolute path": "/etc",
        "an empty uri": "",
    }

    @pytest.mark.parametrize("uri", list(TABLE.values()), ids=list(TABLE))
    def test_each_is_invalid_params_and_the_disk_is_not_asked(self, tmp_path: Path, uri: str) -> None:
        tree = standard_tree(tmp_path)
        (tree.root / "pdf-notes" / ".git").mkdir()
        reads: list[str] = []

        class Spy(SkillsExtension):
            def _read_bytes(self, record: Any) -> bytes:
                reads.append(record.uri)
                return super()._read_bytes(record)

        async def body(client: Client) -> MCPError:
            with pytest.raises(MCPError) as caught:
                await read_directory(client, uri)
            return caught.value

        error = run(talk(Spy(tree.root), body))
        assert error.error.code == INVALID_PARAMS
        assert str(tmp_path) not in str(error)
        assert reads == []

    def test_a_linked_folder_is_not_a_directory(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        add_symlink(tree.root / "pdf-notes" / "linked", outside_secret(tmp_path).parent, directory=True)

        async def body(client: Client) -> int:
            with pytest.raises(MCPError) as caught:
                await read_directory(client, f"{PDF}/linked")
            return caught.value.error.code

        assert run(talk(SkillsExtension(tree.root), body)) == INVALID_PARAMS

    def test_a_skill_the_filters_leave_out_is_not_a_directory_and_the_others_are(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root

        async def body(client: Client) -> list[int | str]:
            found: list[int | str] = []
            for uri in (PDF, f"{PDF}/assets", REFUNDS):
                try:
                    found.append(len((await read_directory(client, uri)).resources))
                except MCPError as error:
                    found.append(error.error.code)
            return found

        assert run(talk(SkillsExtension(root, exclude=["pdf-notes"]), body)) == [INVALID_PARAMS, INVALID_PARAMS, 4]
        assert run(talk(SkillsExtension(root, include=["pdf-*"]), body)) == [4, 1, INVALID_PARAMS]

class TestPages:
    def test_a_directory_pages_with_the_page_size_and_gives_each_child_once(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        record: Record = []

        async def body(client: Client) -> list[ReadDirectoryResult]:
            pages = [await read_directory(client, REFUNDS)]
            while pages[-1].next_cursor is not None:
                pages.append(await read_directory(client, REFUNDS, pages[-1].next_cursor))
            return pages

        pages = run(talk(SkillsExtension(root, page_size=2), body, record=record))
        assert [len(p.resources) for p in pages] == [2, 2, 1]
        assert [n for p in pages for n in names_of(p)] == ["refunds", "empty", "examples", "notes.txt", "templates"]
        assert ["nextCursor" in r for r in wire_results(record, METHOD)] == [True, True, False]

    def test_a_page_size_of_one_gives_a_page_a_child(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> int:
            pages, cursor = 0, None
            while True:
                page = await read_directory(client, REFUNDS, cursor)
                assert len(page.resources) == 1
                pages, cursor = pages + 1, page.next_cursor
                if cursor is None:
                    return pages

        assert run(talk(SkillsExtension(root, page_size=1), body)) == 5

    def test_a_directory_that_just_fits_has_no_second_page(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> ReadDirectoryResult:
            return await read_directory(client, REFUNDS)

        result = run(talk(SkillsExtension(root, page_size=5), body))
        assert len(result.resources) == 5 and result.next_cursor is None

    def test_a_bad_cursor_is_invalid_params_with_a_fixed_message(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> list[tuple[int, str]]:
            errors = []
            for bad in ("!!!", "", "bm9uc2Vuc2U", "a" * 300):
                with pytest.raises(MCPError) as caught:
                    await read_directory(client, REFUNDS, bad)
                errors.append((caught.value.error.code, caught.value.error.message))
            return errors

        assert run(talk(SkillsExtension(root, page_size=2), body)) == [(INVALID_PARAMS, FIXED)] * 4

    def test_an_empty_directory_has_no_page_a_cursor_could_point_to(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> MCPError:
            with pytest.raises(MCPError) as caught:
                await read_directory(client, f"{REFUNDS}/empty", "anything")
            return caught.value

        error = run(talk(SkillsExtension(root, page_size=2), body))
        assert error.error.code == INVALID_PARAMS and error.error.message == FIXED

    def test_a_cursor_is_good_for_one_directory_only(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> list[str]:
            first = await read_directory(client, REFUNDS)
            other = await read_directory(client, PDF)
            assert first.next_cursor is not None and other.next_cursor is not None
            assert first.next_cursor != other.next_cursor
            outcomes = []
            for uri, cursor in ((PDF, first.next_cursor), (REFUNDS, other.next_cursor), (f"{REFUNDS}/templates", first.next_cursor)):
                with pytest.raises(MCPError) as caught:
                    await read_directory(client, uri, cursor)
                outcomes.append(f"{caught.value.error.code} {caught.value.error.message}")
            # each one's own cursor still works
            assert names_of(await read_directory(client, REFUNDS, first.next_cursor)) == ["notes.txt", "templates"]
            return outcomes

        assert run(talk(SkillsExtension(root, page_size=3), body)) == [f"{INVALID_PARAMS} {FIXED}"] * 3

    def test_a_cursor_from_before_a_refresh_is_refused(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        ext = SkillsExtension(root, page_size=2)

        async def body(client: Client) -> None:
            first = await read_directory(client, REFUNDS)
            assert first.next_cursor is not None
            ext.refresh()
            with pytest.raises(MCPError) as caught:
                await read_directory(client, REFUNDS, first.next_cursor)
            assert caught.value.error.code == INVALID_PARAMS and caught.value.error.message == FIXED
            assert len((await read_directory(client, REFUNDS)).resources) == 2

        run(talk(ext, body))


class TestFromTheCatalogue:
    def test_a_directory_read_still_answers_when_the_files_are_gone_and_a_file_read_does_not(self, tmp_path: Path) -> None:
        tree = tree_with_an_empty_folder(tmp_path)
        ext = SkillsExtension(tree.root)
        shutil.rmtree(tree.root)  # everything the catalogue was made from

        async def body(client: Client) -> tuple[list[str], list[str], MCPError]:
            root = await read_directory(client, REFUNDS)
            empty = await read_directory(client, f"{REFUNDS}/empty")
            with pytest.raises(MCPError) as caught:
                await client.read_resource(f"{REFUNDS}/notes.txt")
            return names_of(root), names_of(empty), caught.value

        names, empty, error = run(talk(ext, body))
        assert names == ["refunds", "empty", "examples", "notes.txt", "templates"] and empty == []
        assert (error.error.code, error.error.message) == (INTERNAL_ERROR, CHANGED)

    def test_a_refresh_changes_what_a_directory_lists(self, tmp_path: Path) -> None:
        tree = tree_with_an_empty_folder(tmp_path)
        ext = SkillsExtension(tree.root)
        server = MCPServer("skills-test", extensions=[ext])

        async def body(client: Client) -> tuple[list[str], list[str], int]:
            before = names_of(await read_directory(client, REFUNDS))
            (tree.root / "team" / "billing" / "refunds" / "empty").rmdir()
            (tree.root / "team" / "billing" / "refunds" / "fresh").mkdir()
            ext.refresh(server)
            after = names_of(await read_directory(client, REFUNDS))
            with pytest.raises(MCPError) as caught:
                await read_directory(client, f"{REFUNDS}/empty")
            return before, after, caught.value.error.code

        before, after, gone = run(talk(server, body))
        assert before == ["refunds", "empty", "examples", "notes.txt", "templates"]
        assert after == ["refunds", "examples", "fresh", "notes.txt", "templates"]
        assert gone == INVALID_PARAMS


# --- Part B: the client ---------------------------------------------------------------------------


class RawDirectoryResult(types.PaginatedResult, types.CacheableResult):
    """What a lying server sends: children of any shape."""

    resources: list[Any]
    result_type: types.ResultType = "complete"


class LyingDirectory(SkillsExtension):
    """The real extension that answers `resources/directory/read` with what `reply(uri, cursor)` says: a
    pair of the children (any JSON values) and the next cursor."""

    def __init__(self, folders: Any, reply: Callable[[str, str | None], tuple[list[Any], str | None]], **kwargs: Any) -> None:
        super().__init__(folders, **kwargs)
        self._reply = reply
        self.asked: list[tuple[str, str | None]] = []

    async def _directory(self, ctx: Any, params: Any) -> RawDirectoryResult:
        self.asked.append((params.uri, params.cursor))
        children, cursor = self._reply(params.uri, params.cursor)
        return RawDirectoryResult(resources=children, next_cursor=cursor, ttl_ms=0, cache_scope="private")


async def first_item(skills: SkillsClient, uri: str = f"{REFUNDS}/SKILL.md") -> Any:
    return next(item for item in (await skills.list()).skills if item.uri == uri)


class TestListDirectory:
    def test_it_lists_the_children_of_a_directory_of_the_skill_tagged_with_the_origin(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> tuple[Any, ...]:
            skills = SkillsClient(client, origin="alpha")
            item = await first_item(skills)
            return await skills.list_directory(item, REFUNDS), await skills.list_directory(item, f"{REFUNDS}/templates")

        top, below = run(talk(SkillsExtension(root), body))
        assert top == tuple(
            DirectoryEntry("alpha", uri, name, mime, is_dir)
            for uri, name, mime, is_dir in [
                (f"{REFUNDS}/SKILL.md", "refunds", "text/markdown", False),
                (f"{REFUNDS}/empty", "empty", DIR, True),
                (f"{REFUNDS}/examples", "examples", DIR, True),
                (f"{REFUNDS}/notes.txt", "notes.txt", "text/plain", False),
                (f"{REFUNDS}/templates", "templates", DIR, True),
            ]
        )
        assert below == (DirectoryEntry("alpha", f"{REFUNDS}/templates/reply.md", "reply.md", "text/markdown", False),)

    def test_it_follows_every_page(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        record: Record = []

        async def body(client: Client) -> tuple[Any, ...]:
            skills = SkillsClient(client, origin="docs")
            return await skills.list_directory(await first_item(skills), REFUNDS)

        entries = run(talk(SkillsExtension(root, page_size=2), body, record=record))
        assert [e.name for e in entries] == ["refunds", "empty", "examples", "notes.txt", "templates"]
        assert len(sent(record, METHOD)) == 3

    def test_an_empty_directory_gives_an_empty_tuple(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> Any:
            skills = SkillsClient(client, origin="docs")
            return await skills.list_directory(await first_item(skills), f"{REFUNDS}/empty")

        assert run(talk(SkillsExtension(root), body)) == ()

    def test_every_file_a_directory_names_can_be_read_and_is_verified(self, tmp_path: Path) -> None:
        tree = tree_with_an_empty_folder(tmp_path)
        expected = tree.expected()

        async def body(client: Client) -> dict[str, bytes]:
            skills = SkillsClient(client, origin="docs")
            got: dict[str, bytes] = {}
            for item in (await skills.list()).skills:
                todo = [item.uri.removesuffix("/SKILL.md")]
                while todo:
                    for entry in await skills.list_directory(item, todo.pop()):
                        if entry.is_dir:
                            todo.append(entry.uri)
                        else:
                            got[entry.uri] = (await skills.read(item, entry.uri)).data
            return got

        assert run(talk(SkillsExtension(tree.root), body)) == expected

    def test_a_directory_is_not_a_file_to_read(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        record: Record = []

        async def body(client: Client) -> SkillRefused:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills)
            with pytest.raises(SkillRefused) as caught:
                await skills.read(item, f"{REFUNDS}/templates")
            return caught.value

        refused = run(talk(SkillsExtension(root), body, record=record))
        assert refused.check == "unlisted"
        assert sent(record, "resources/read") == []


class TestRefusedWithoutARequest:
    URIS = {
        "another skill's root": PDF,
        "a folder of another skill": f"{PDF}/assets",
        "a prefix above skills": "skill://team/billing",
        "the first segment alone": "skill://team",
        "a skill whose name starts with this one's": f"{REFUNDS}-old",
        "a folder whose name starts with this one's": f"{REFUNDS}x/templates",
        "another scheme": "file:///etc",
        "an https address": "https://example.com/skill",
        "the scheme alone": "skill://",
        "an empty uri": "",
        "dot dot": f"{REFUNDS}/..",
        "dot dot to another skill": f"{REFUNDS}/../../../../pdf-notes",
        "dot dot below": f"{REFUNDS}/templates/../..",
        "dot": f"{REFUNDS}/.",
        "an encoded dot dot": f"{REFUNDS}/%2e%2e",
        "an encoded dot dot in capitals": f"{REFUNDS}/%2E%2E/pdf-notes",
        "an encoded slash": f"{REFUNDS}/a%2Fb",
        "an encoded slash that climbs": f"{REFUNDS}/..%2F..%2Fpdf-notes",
        "a trailing slash": f"{REFUNDS}/",
        "a doubled slash": f"{REFUNDS}//templates",
    }

    @pytest.mark.parametrize("uri", list(URIS.values()), ids=list(URIS))
    def test_the_client_refuses_it_and_sends_nothing(self, tmp_path: Path, uri: str) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        record: Record = []

        async def body(client: Client) -> SkillRefused:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills)
            with pytest.raises(SkillRefused) as caught:
                await skills.list_directory(item, uri)
            return caught.value

        refused = run(talk(SkillsExtension(root), body, record=record))
        assert refused.check == "directory"
        assert sent(record, METHOD) == []

    def test_a_server_that_did_not_declare_a_directory_read_is_not_asked(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root
        record: Record = []

        async def body(client: Client) -> SkillRefused:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills)
            with pytest.raises(SkillRefused) as caught:
                await skills.list_directory(item, REFUNDS)
            return caught.value

        refused = run(talk(SkillsExtension(root, directory_read=False), body, record=record))
        assert refused.check == "directory"
        assert sent(record, METHOD) == []

    def test_a_server_that_did_not_declare_skills_at_all_is_refused_for_that(self) -> None:
        record: Record = []

        async def body(client: Client) -> SkillRefused:
            with pytest.raises(SkillRefused) as caught:
                await SkillsClient(client, origin="docs").list_directory(an_item(), REFUNDS)
            return caught.value

        refused = run(talk(MCPServer("bare"), body, record=record))
        assert refused.check == "declaration"  # the first thing wrong, before the directory
        assert sent(record, METHOD) == []

    def test_the_root_of_the_skill_and_a_folder_below_it_are_allowed(self, tmp_path: Path) -> None:
        root = tree_with_an_empty_folder(tmp_path).root

        async def body(client: Client) -> list[int]:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills)
            return [len(await skills.list_directory(item, uri)) for uri in (REFUNDS, f"{REFUNDS}/templates", f"{REFUNDS}/examples")]

        assert run(talk(SkillsExtension(root), body)) == [5, 1, 1]

    def test_a_sibling_skill_is_refused_even_when_it_is_real_and_a_neighbour(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs", files={"a/b.md": "b\n"})
        write_skill(root, "docs-extra", files={"c/d.md": "d\n"})
        record: Record = []

        async def body(client: Client) -> tuple[SkillRefused, int]:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills, "skill://docs/SKILL.md")
            with pytest.raises(SkillRefused) as caught:
                await skills.list_directory(item, "skill://docs-extra")
            return caught.value, len(await skills.list_directory(item, "skill://docs/a"))

        refused, inside = run(talk(SkillsExtension(root), body, record=record))
        assert refused.check == "directory" and inside == 1
        assert [m["params"]["uri"] for m in sent(record, METHOD)] == ["skill://docs/a"]  # only the one it was allowed


def an_item() -> SkillItem:
    """An entry made by hand, for a client wired to a server that serves nothing."""
    return SkillItem("docs", f"{REFUNDS}/SKILL.md", "refunds", "d", {"name": "refunds", "description": "d"}, ())


class TestAServerThatLies:
    def test_a_child_the_entry_does_not_list_comes_back_as_metadata_and_cannot_be_read(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs", files={"real.md": "real\n"})
        ghost = {"uri": "skill://docs/ghost.md", "name": "ghost.md", "mimeType": "text/markdown"}
        record: Record = []

        def reply(uri: str, cursor: str | None) -> tuple[list[Any], str | None]:
            return [ghost, {"uri": "skill://elsewhere/x", "name": "x"}], None

        async def body(client: Client) -> tuple[Any, SkillRefused]:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills, "skill://docs/SKILL.md")
            entries = await skills.list_directory(item, "skill://docs")
            with pytest.raises(SkillRefused) as caught:
                await skills.read(item, "skill://docs/ghost.md")
            return entries, caught.value

        entries, refused = run(talk(LyingDirectory(root, reply), body, record=record))
        assert entries == (
            DirectoryEntry("docs", "skill://docs/ghost.md", "ghost.md", "text/markdown", False),
            DirectoryEntry("docs", "skill://elsewhere/x", "x", "", False),  # no type: no type is made up
        )
        assert refused.check == "unlisted"
        assert sent(record, "resources/read") == []

    @pytest.mark.parametrize(
        "child",
        [5, "skill://docs/a", None, {"name": "no uri"}, {"uri": "skill://docs/a"}, {"uri": 5, "name": "n"}, {"uri": "u", "name": 5}],
        ids=["a number", "a string", "null", "no uri", "no name", "uri not a string", "name not a string"],
    )
    def test_a_child_that_is_not_a_resource_refuses_the_whole_answer(self, tmp_path: Path, child: Any) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs", files={"real.md": "real\n"})

        async def body(client: Client) -> SkillRefused:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills, "skill://docs/SKILL.md")
            with pytest.raises(SkillRefused) as caught:
                await skills.list_directory(item, "skill://docs")
            return caught.value

        refused = run(talk(LyingDirectory(root, lambda uri, cursor: ([child], None)), body))
        assert refused.check == "response"

    @pytest.mark.parametrize(
        ("cursors", "asked"),
        [(["again"], 2), ([""], 2), (["a", "b", "a"], 3)],
        ids=["same", "empty", "back-to-the-first"],
    )
    def test_a_server_that_pages_forever_is_refused_and_not_followed(
        self, tmp_path: Path, cursors: list[str], asked: int
    ) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs")
        record: Record = []
        seen: list[int] = []

        def reply(uri: str, cursor: str | None) -> tuple[list[Any], str | None]:
            seen.append(1)
            return [{"uri": "skill://docs/SKILL.md", "name": "docs"}], cursors[min(len(seen) - 1, len(cursors) - 1)]

        async def body(client: Client) -> SkillRefused:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills, "skill://docs/SKILL.md")
            with pytest.raises(SkillRefused) as caught:
                await skills.list_directory(item, "skill://docs")
            return caught.value

        refused = run(talk(LyingDirectory(root, reply), body, record=record))
        assert refused.check == "response"
        assert len(sent(record, METHOD)) == len(seen) == asked

    def test_distinct_cursors_that_end_are_followed_to_the_end(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs")
        cursors = ["a", "b", None]
        calls: list[str | None] = []

        def reply(uri: str, cursor: str | None) -> tuple[list[Any], str | None]:
            calls.append(cursor)
            return [{"uri": f"skill://docs/{len(calls)}", "name": str(len(calls))}], cursors[len(calls) - 1]

        async def body(client: Client) -> Any:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills, "skill://docs/SKILL.md")
            return await skills.list_directory(item, "skill://docs")

        entries = run(talk(LyingDirectory(root, reply), body))
        assert [e.name for e in entries] == ["1", "2", "3"] and calls == [None, "a", "b"]

    def test_a_listing_that_is_not_a_directory_answer_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs")

        class Wrong(LyingDirectory):
            async def _directory(self, ctx: Any, params: Any) -> Any:  # type: ignore[override]
                return types.EmptyResult()

        async def body(client: Client) -> SkillRefused:
            skills = SkillsClient(client, origin="docs")
            item = await first_item(skills, "skill://docs/SKILL.md")
            with pytest.raises(SkillRefused) as caught:
                await skills.list_directory(item, "skill://docs")
            return caught.value

        assert run(talk(Wrong(root, lambda uri, cursor: ([], None)), body)).check == "response"
