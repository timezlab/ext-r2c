"""Many skills, paged by an opaque cursor (spec 005, story 6, SC-007, FR-012): `skills/list` answers
`page_size` skills at a time; every skill is on exactly one page, whole; a cursor is good for the one
listing and the one catalogue it came from, and anything else is `-32602` with a fixed message. A real
MCP SDK client talks to a real `MCPServer`; what is true is worked out from the disk with `hashlib`,
never by package code."""

from __future__ import annotations

import base64
import hashlib
import math
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypeVar

import mcp_types as types
import pytest
from ext_r2c.mcp.skills import SkillRefused, SkillsClient, SkillsExtension
from ext_r2c.mcp.skills._wire import (
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
from skills_fixtures import many_skills, write_skill

T = TypeVar("T")
INVALID_PARAMS = -32602
FIXED = "Invalid cursor"
COUNT = 60
NAMES = [f"skill-{i:03d}" for i in range(1, COUNT + 1)]
URIS = [f"skill://{name}/SKILL.md" for name in NAMES]


async def talk(ext: SkillsExtension, body: Callable[[Client], Awaitable[T]], *, record: Record | None = None) -> T:
    server = MCPServer("skills-test", extensions=[ext])
    async with serve(server, record=record) as served, mcp_client(served, active=False, form=False) as client:
        return await body(client)


async def page(client: Client, cursor: str | None = None) -> ListSkillsResult:
    params = None if cursor is None else types.PaginatedRequestParams(cursor=cursor)
    request = ListSkillsRequest() if params is None else ListSkillsRequest(params=params)
    return await client.session.send_request(request, ListSkillsResult)


async def every_page(client: Client) -> list[ListSkillsResult]:
    pages = [await page(client)]
    while pages[-1].next_cursor is not None:
        pages.append(await page(client, pages[-1].next_cursor))
        assert len(pages) <= COUNT + 1, "the cursor never ends"
    return pages


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def sent(record: Record, method: str) -> list[dict[str, Any]]:
    return [m for side, m in record if side == "client" and m.get("method") == method]


def wire_results(record: Record, method: str) -> list[dict[str, Any]]:
    ids = [m["id"] for m in sent(record, method) if "id" in m]
    return [m["result"] for side, m in record if side == "remote" and m.get("id") in ids and "result" in m]


def tree_of_sixty(tmp_path: Path) -> Path:
    """Sixty skills; four of them hold more than their `SKILL.md`, among them the last of the first
    page and the first of the second, so a page that cut an entry short would show."""
    root = tmp_path / "skills"
    many_skills(root, COUNT)
    for number in (10, 25, 26, 50):
        write_skill(
            root,
            f"skill-{number:03d}",
            files={"a.md": f"a of {number}\n", "docs/b.md": f"b of {number}\n", "bin/c.dat": bytes([number, 0, 255])},
        )
    return root


def truth(root: Path) -> dict[str, dict[str, tuple[str, int]]]:
    """`{skill uri: {file uri: (digest, size)}}`, worked out from the disk."""
    found: dict[str, dict[str, tuple[str, int]]] = {}
    for skill in sorted(p for p in root.iterdir() if p.is_dir()):
        files = {}
        for file in sorted(p for p in skill.rglob("*") if p.is_file()):
            data = file.read_bytes()
            relative = file.relative_to(root).as_posix()
            files[f"skill://{relative}"] = ("sha256:" + hashlib.sha256(data).hexdigest(), len(data))
        found[f"skill://{skill.name}/SKILL.md"] = files
    return found


def entry_files(skill: Any) -> dict[str, tuple[str, int]]:
    return {r.uri: (r.digest, r.size) for r in skill.resources}


# --- The pages -----------------------------------------------------------------------------------


class TestPages:
    def test_sixty_skills_at_twenty_five_come_as_25_25_and_10_each_once_in_uri_order(self, tmp_path: Path) -> None:
        root = tree_of_sixty(tmp_path)
        record: Record = []

        async def body(client: Client) -> list[ListSkillsResult]:
            return await every_page(client)

        pages = run(talk(SkillsExtension(root, page_size=25), body, record=record))
        assert [len(p.skills) for p in pages] == [25, 25, 10]
        assert [s.uri for p in pages for s in p.skills] == URIS  # each exactly once, and in order
        assert [p.next_cursor is not None for p in pages] == [True, True, False]
        results = wire_results(record, "skills/list")
        assert ["nextCursor" in r for r in results] == [True, True, False]  # absent, not null, on the last page
        assert all(r["resultType"] == "complete" and r["ttlMs"] == 300_000 and r["cacheScope"] == "private" for r in results)

    def test_every_entry_is_whole_on_its_page(self, tmp_path: Path) -> None:
        root = tree_of_sixty(tmp_path)
        expected = truth(root)

        async def body(client: Client) -> list[ListSkillsResult]:
            return await every_page(client)

        pages = run(talk(SkillsExtension(root, page_size=25), body))
        for p in pages:
            for skill in p.skills:
                assert entry_files(skill) == expected[skill.uri], skill.uri
        assert len(entry_files(pages[0].skills[24])) == 4 and len(entry_files(pages[1].skills[0])) == 4  # 25 and 26 hold 4 files

    @pytest.mark.parametrize("page_size", [1, 2, 7, 25, 59, 60, 61, 1000])
    def test_the_page_size_is_how_many_skills_come_at_a_time(self, tmp_path: Path, page_size: int) -> None:
        root = tmp_path / "skills"
        many_skills(root, COUNT)

        async def body(client: Client) -> list[ListSkillsResult]:
            return await every_page(client)

        pages = run(talk(SkillsExtension(root, page_size=page_size), body))
        assert len(pages) == math.ceil(COUNT / page_size)
        assert [len(p.skills) for p in pages[:-1]] == [page_size] * (len(pages) - 1)
        assert 1 <= len(pages[-1].skills) <= page_size
        assert [s.uri for p in pages for s in p.skills] == URIS
        assert [p.next_cursor is None for p in pages] == [False] * (len(pages) - 1) + [True]

    def test_a_page_size_that_holds_them_all_gives_one_page_without_a_cursor(self, tmp_path: Path) -> None:
        """60 skills and `page_size=60` is the edge: the page is full and there is nothing after it."""
        root = tmp_path / "skills"
        many_skills(root, COUNT)

        async def body(client: Client) -> list[ListSkillsResult]:
            return await every_page(client)

        (only,) = run(talk(SkillsExtension(root, page_size=COUNT), body))
        assert len(only.skills) == COUNT and only.next_cursor is None

    def test_the_default_is_twenty_five(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        many_skills(root, COUNT)

        async def body(client: Client) -> list[ListSkillsResult]:
            return await every_page(client)

        pages = run(talk(SkillsExtension(root), body))
        assert [len(p.skills) for p in pages] == [25, 25, 10]

    def test_a_skill_with_five_hundred_and_twelve_files_is_whole_on_a_page_of_its_own(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "a-first")
        write_skill(root, "big", files={f"f{i:03d}.txt": f"{i}\n" for i in range(511)})  # with SKILL.md: 512
        write_skill(root, "z-last")

        async def body(client: Client) -> list[ListSkillsResult]:
            return await every_page(client)

        pages = run(talk(SkillsExtension(root, page_size=1), body))
        assert [p.skills[0].uri for p in pages] == ["skill://a-first/SKILL.md", "skill://big/SKILL.md", "skill://z-last/SKILL.md"]
        assert [len(p.skills[0].resources) for p in pages] == [1, 512, 1]

    def test_the_same_cursor_gives_the_same_page_every_time(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        many_skills(root, COUNT)

        async def body(client: Client) -> tuple[ListSkillsResult, ListSkillsResult, ListSkillsResult]:
            first = await page(client)
            assert first.next_cursor is not None
            return first, await page(client, first.next_cursor), await page(client, first.next_cursor)

        first, second, again = run(talk(SkillsExtension(root, page_size=25), body))
        assert [s.uri for s in second.skills] == URIS[25:50]
        assert second.model_dump() == again.model_dump()
        assert second.next_cursor == again.next_cursor

    def test_a_cursor_is_opaque_ascii_text_that_names_no_path_and_no_skill(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        many_skills(root, COUNT)

        async def body(client: Client) -> str:
            cursor = (await page(client)).next_cursor
            assert cursor is not None
            return cursor

        cursor = run(talk(SkillsExtension(root, page_size=25), body))
        shown = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
        assert str(tmp_path) not in cursor and str(tmp_path) not in shown
        assert "skill-" not in cursor and "skill-" not in shown
        assert cursor.isascii() and "=" not in cursor

    def test_the_client_lists_all_sixty_through_the_pages(self, tmp_path: Path) -> None:
        root = tree_of_sixty(tmp_path)
        expected = truth(root)
        record: Record = []

        async def body(client: Client) -> Any:
            return await SkillsClient(client, origin="docs").list()

        listing = run(talk(SkillsExtension(root, page_size=25), body, record=record))
        assert not listing.refused
        assert [item.uri for item in listing.skills] == URIS
        assert {item.uri: {f.uri: (f.digest, f.size) for f in item.files} for item in listing.skills} == expected
        assert len(sent(record, "skills/list")) == 3
        assert sent(record, "resources/read") == []  # listing reads no file

    def test_the_client_reads_each_page_once_whatever_the_page_size(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        many_skills(root, 10)
        record: Record = []

        async def body(client: Client) -> Any:
            return await SkillsClient(client, origin="docs").list()

        listing = run(talk(SkillsExtension(root, page_size=3), body, record=record))
        assert len(listing.skills) == 10 and len(sent(record, "skills/list")) == 4


# --- A bad cursor --------------------------------------------------------------------------------


class TestBadCursors:
    def refused(self, ext: SkillsExtension, cursor: str, tmp_path: Path) -> None:
        async def body(client: Client) -> MCPError:
            with pytest.raises(MCPError) as caught:
                await page(client, cursor)
            return caught.value

        error = run(talk(ext, body))
        assert error.error.code == INVALID_PARAMS
        assert error.error.message == FIXED  # fixed text: the cursor is not echoed, and no path is in it
        assert str(tmp_path) not in str(error)

    def ext(self, tmp_path: Path, **kwargs: Any) -> SkillsExtension:
        root = tmp_path / "skills"
        many_skills(root, COUNT)
        return SkillsExtension(root, page_size=25, **kwargs)

    @pytest.mark.parametrize(
        "cursor",
        ["!!!", "not a cursor", "", " ", "%%%%", "====", "a" * 300, "../../etc/passwd", "skill://skill-001/SKILL.md", "\x00"],
        ids=["bang", "words", "empty", "space", "percent", "padding", "long", "path", "uri", "nul"],
    )
    def test_garbage_is_invalid_params(self, tmp_path: Path, cursor: str) -> None:
        self.refused(self.ext(tmp_path), cursor, tmp_path)

    @pytest.mark.parametrize("text", ["nonsense", "abc.def", "only-a-generation", "1.2.3", ".5", "a.b.c", "x.", "."])
    def test_valid_base64_of_a_wrong_shape_is_invalid_params(self, tmp_path: Path, text: str) -> None:
        self.refused(self.ext(tmp_path), b64(text), tmp_path)

    @pytest.mark.parametrize("offset", ["-1", "60", "61", "999999999999999999999", "025", "+5", "5.0", " 5", "٥"])
    def test_an_offset_that_is_negative_past_the_end_or_not_written_so_is_invalid_params(
        self, tmp_path: Path, offset: str
    ) -> None:
        ext = self.ext(tmp_path)
        self.refused(ext, b64(f"{ext.catalogue.generation}.{offset}"), tmp_path)

    def test_a_cursor_of_another_server_is_invalid_params(self, tmp_path: Path) -> None:
        mine, other = self.ext(tmp_path), SkillsExtension(tmp_path / "skills", page_size=25)

        async def body(client: Client) -> str | None:
            return (await page(client)).next_cursor

        theirs = run(talk(other, body))
        assert theirs is not None
        self.refused(mine, theirs, tmp_path)

    def test_a_cursor_from_before_a_refresh_is_invalid_params_and_a_new_one_works(self, tmp_path: Path) -> None:
        ext = self.ext(tmp_path)

        async def body(client: Client) -> tuple[MCPError, list[str]]:
            first = await page(client)
            assert first.next_cursor is not None
            ext.refresh()  # nothing changed on the disk: the catalogue is a new one all the same
            with pytest.raises(MCPError) as caught:
                await page(client, first.next_cursor)
            fresh = await page(client)
            assert fresh.next_cursor is not None
            return caught.value, [s.uri for s in (await page(client, fresh.next_cursor)).skills]

        error, second = run(talk(ext, body))
        assert error.error.code == INVALID_PARAMS and error.error.message == FIXED
        assert second == URIS[25:50]

    def test_a_cursor_from_before_a_refresh_that_changed_the_skills_is_refused_too(self, tmp_path: Path) -> None:
        ext = self.ext(tmp_path)
        server = MCPServer("skills-test", extensions=[ext])

        async def body() -> None:
            async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
                first = await page(client)
                assert first.next_cursor is not None
                # It sorts before the others: an offset into the old list would repeat a skill on the next page.
                write_skill(tmp_path / "skills", "skill-000")
                ext.refresh(server)
                with pytest.raises(MCPError) as caught:
                    await page(client, first.next_cursor)
                assert caught.value.error.code == INVALID_PARAMS and caught.value.error.message == FIXED
                assert (await page(client)).skills[0].uri == "skill://skill-000/SKILL.md"

        run(body())

    def test_a_good_cursor_still_works_after_bad_ones(self, tmp_path: Path) -> None:
        ext = self.ext(tmp_path)

        async def body(client: Client) -> list[str]:
            first = await page(client)
            assert first.next_cursor is not None
            for bad in ("!!!", b64("x.1")):
                with pytest.raises(MCPError):
                    await page(client, bad)
            return [s.uri for s in (await page(client, first.next_cursor)).skills]

        assert run(talk(ext, body)) == URIS[25:50]

    def test_a_cursor_of_the_listing_of_a_directory_is_not_one_of_skills_list(self, tmp_path: Path) -> None:
        """A cursor is a position in one list: given to another list it would skip or repeat its entries
        without a word, so it is refused."""
        root = tmp_path / "skills"
        write_skill(root, "docs", files={f"f{i}.md": "x\n" for i in range(5)})
        many_skills(root, 3)
        ext = SkillsExtension(root, page_size=2)

        async def body(client: Client) -> None:
            opened = await client.session.send_request(
                ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://docs")), ReadDirectoryResult
            )
            assert opened.next_cursor is not None
            with pytest.raises(MCPError) as caught:
                await page(client, opened.next_cursor)
            assert caught.value.error.code == INVALID_PARAMS and caught.value.error.message == FIXED

        run(talk(ext, body))


# --- The client does not loop --------------------------------------------------------------------


class Looping(SkillsExtension):
    """A server that goes on saying there is a page after this one, with the cursors it is given."""

    def __init__(self, folders: Any, cursors: list[str | None]) -> None:
        super().__init__(folders)
        self._cursors = cursors
        self.asked: list[str | None] = []

    async def _list(self, ctx: Any, params: Any) -> ListSkillsResult:
        self.asked.append(None if params is None else params.cursor)
        number = len(self.asked) - 1
        cursor = self._cursors[min(number, len(self._cursors) - 1)]
        first = self.catalogue.skills[0]
        return ListSkillsResult(skills=[self._entry(first)], next_cursor=cursor, ttl_ms=0, cache_scope="private")


class TestAServerThatPagesForever:
    @pytest.mark.parametrize(
        ("cursors", "asked"),
        [
            (["again"], 2),  # the cursor it gave comes back as the next one
            (["", ""], 2),  # an empty string is a cursor, and a repeated one
            (["a", "b", "a"], 3),  # not the cursor before, but one it gave earlier
            (["a", "b", "c", "b"], 4),
        ],
        ids=["same", "empty", "back-to-the-first", "back-to-the-second"],
    )
    def test_the_client_refuses_a_cursor_it_has_seen_and_stops(
        self, tmp_path: Path, cursors: list[str | None], asked: int
    ) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs")
        ext = Looping(root, cursors)
        record: Record = []

        async def body(client: Client) -> SkillRefused:
            with pytest.raises(SkillRefused) as caught:
                await SkillsClient(client, origin="docs").list()
            return caught.value

        refused = run(talk(ext, body, record=record))
        assert refused.check == "response"
        assert len(sent(record, "skills/list")) == len(ext.asked) == asked  # it did not go on asking

    def test_distinct_cursors_that_end_are_not_a_loop(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "docs")
        ext = Looping(root, ["a", "b", "c", None])

        async def body(client: Client) -> Any:
            return await SkillsClient(client, origin="docs").list()

        listing = run(talk(ext, body))
        assert ext.asked == [None, "a", "b", "c"]  # every page was asked for, and no page after the last
        # This server says the same skill on every page. One skill is one URI (outside review, R17): it is
        # returned once and each repeat is refused, so a server cannot fill a list by repeating itself.
        assert [item.uri for item in listing.skills] == ["skill://docs/SKILL.md"]
        assert [(r.check, r.uri) for r in listing.refused] == [("entry", "skill://docs/SKILL.md")] * 3
