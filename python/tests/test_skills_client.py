"""The caller's client of MCP Skills (spec 005, story 2): it lists, loads and reads skills, and
VERIFIES every file against the entry the server gave (size, SHA-256, and the frontmatter of
`SKILL.md`), refusing what does not verify. A real MCP SDK `Client` talks to a real `MCPServer`;
a server that lies is the real extension with its entries or its bytes falsified (`Lying`), or the
real server with its `resources/read` answer falsified (`LyingServer`). What is true is worked out
from the disk by `skills_fixtures`, never by package code.

Part A: what a good server gets. Part B: what a lying one gets (SC-002). Part C: the types."""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import pickle
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import mcp_types as types
import pytest
from ext_r2c.mcp.skills import (
    SkillDirectoryEntry,
    LoadedSkill,
    RefusedEntry,
    SkillContent,
    SkillFileRef,
    SkillItem,
    SkillListing,
    SkillRefused,
    SkillsClient,
    SkillsExtension,
)
from ext_r2c.mcp.skills._wire import EXTENSION_ID, ListSkillsResult, RawGetSkillResult, RawListSkillsResult
from ext_r2c.mcp.skills.client import parse_entry
from mcp.client import Client
from mcp.client.caching import CacheConfig
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp_harness import URL, http_client, mcp_client, run, serve
from mcp_transport import Record
from skills_fixtures import Fixture, standard_tree, write_skill

GREETINGS = "skill://greetings/SKILL.md"
PDF = "skill://pdf-notes/SKILL.md"
REFUNDS = "skill://team/billing/refunds/SKILL.md"
LOGO = "skill://pdf-notes/assets/logo.bin"  # 9 bytes, not UTF-8: sent as a blob
REFERENCE = "skill://pdf-notes/reference.md"  # UTF-8: sent as text
MAX_FILES = 512
MAX_BYTES = 16 * 1024 * 1024


# --- The helpers ----------------------------------------------------------------------------------


class Lying(SkillsExtension):
    """The real extension, saying something false. `entry` maps a skill URI to a function from the
    true wire entry (a plain dict) to what is sent instead, in the list and in the get alike (any
    JSON value, so a shape the typed model would not allow can be sent); `data` maps a file URI to a
    function from the true bytes to the bytes sent; `declare` is what `server/discover` says."""

    def __init__(
        self,
        folders: Any,
        *,
        entry: dict[str, Callable[[Any], Any]] | None = None,
        data: dict[str, Callable[[bytes], bytes]] | None = None,
        declare: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(folders)
        self._entry_lies = entry or {}
        self._data_lies = data or {}
        self._declare = {"directoryRead": False} if declare is None else declare

    def wire(self, skill: Any) -> Any:
        truth = self._entry(skill).model_dump(by_alias=True, exclude_none=True)
        lie = self._entry_lies.get(skill.uri)
        return lie(truth) if lie else truth

    def settings(self) -> dict[str, Any]:
        return self._declare

    async def _list(self, ctx: Any, params: Any) -> Any:
        return RawListSkillsResult(skills=[self.wire(s) for s in self.catalogue.skills], ttl_ms=0, cache_scope="private")

    async def _get(self, ctx: Any, params: Any) -> Any:
        skill = self.catalogue.by_uri.get(params.uri)
        if skill is None:
            raise MCPError(code=types.INVALID_PARAMS, message=f"No skill is served at {params.uri}")
        return RawGetSkillResult(skill=self.wire(skill), ttl_ms=0, cache_scope="private")

    def _read_bytes(self, record: Any) -> bytes:
        data = super()._read_bytes(record)
        lie = self._data_lies.get(record.uri)
        return lie(data) if lie else data


class LyingServer(MCPServer):
    """A real server whose `resources/read` answer is rewritten by `reply(uri, truth)`, a function
    from the true result to the one sent, so that the shape of the answer can be falsified too."""

    def __init__(self, ext: SkillsExtension, reply: Callable[[str, types.ReadResourceResult], Any]) -> None:
        self._reply = reply
        super().__init__("liar", extensions=[ext])

    async def _handle_read_resource(self, ctx: Any, params: Any) -> Any:
        truth = await super()._handle_read_resource(ctx, params)
        return self._reply(str(params.uri), truth)


@contextlib.asynccontextmanager
async def connected(
    served_by: SkillsExtension | MCPServer, *, record: Record | None = None, origin: str = "docs"
) -> AsyncIterator[SkillsClient]:
    """Serve `served_by` (an extension goes on a plain `MCPServer`), connect an SDK client that
    knows nothing of the extension, and wrap it in a `SkillsClient`."""
    server = served_by if isinstance(served_by, MCPServer) else MCPServer("skills-test", extensions=[served_by])
    async with serve(server, record=record) as served, mcp_client(served, active=False, form=False) as client:
        yield SkillsClient(client, origin=origin)


def sent(record: Record, method: str) -> list[dict[str, Any]]:
    """The requests the client put on the wire for `method`."""
    return [message for side, message in record if side == "client" and message.get("method") == method]


def skills_requests(record: Record) -> list[dict[str, Any]]:
    return [m for side, m in record if side == "client" and str(m.get("method", "")).startswith(("skills/", "resources/"))]


def by_uri(listing: SkillListing) -> dict[str, SkillItem]:
    return {item.uri: item for item in listing.skills}


def truth_of(tree: Fixture) -> dict[str, bytes]:
    return tree.expected()


def resource(entry: dict[str, Any], uri: str) -> dict[str, Any]:
    return next(r for r in entry["resources"] if r["uri"] == uri)


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --- Part A: a good server ------------------------------------------------------------------------


class TestDeclaration:
    def test_a_skills_server_is_declared_and_says_whether_it_reads_directories(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root

        async def body(served_by: SkillsExtension) -> tuple[bool, bool]:
            async with connected(served_by) as skills:
                return skills.declared, skills.directory_read

        assert run(body(SkillsExtension(root))) == (True, True)  # on by default since phase 8
        assert run(body(SkillsExtension(root, directory_read=False))) == (True, False)
        assert run(body(Lying(root, declare={"directoryRead": True}))) == (True, True)
        assert run(body(Lying(root, declare={}))) == (True, False)  # an empty object is a valid declaration
        assert run(body(Lying(root, declare={"directoryRead": "yes"}))) == (True, False)  # only `true` counts

    def test_a_server_without_the_extension_is_not_declared(self) -> None:
        async def body() -> tuple[bool, bool]:
            async with connected(MCPServer("plain")) as skills:
                return skills.declared, skills.directory_read

        assert run(body()) == (False, False)

    def test_the_extension_without_the_resources_capability_is_not_declared(self) -> None:
        # The SDK always declares `resources`, so no real server can lack it: a stub stands in.
        class Stub:
            server_capabilities = types.ServerCapabilities(extensions={EXTENSION_ID: {"directoryRead": True}})

        skills = SkillsClient(Stub(), origin="docs")  # type: ignore[arg-type]
        assert (skills.declared, skills.directory_read) == (False, False)

    def test_an_origin_is_a_non_empty_string(self) -> None:
        for origin in ("", None, 3):
            with pytest.raises(ValueError, match="origin"):
                SkillsClient(object(), origin=origin)  # type: ignore[arg-type]


class TestListAndGet:
    def test_list_gives_one_validated_item_per_skill_and_reads_no_file(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        record: Record = []

        async def body() -> tuple[SkillListing, SkillItem]:
            async with connected(SkillsExtension(tree.root), record=record) as skills:
                listing = await skills.list()
                return listing, await skills.get(REFUNDS)

        listing, got = run(body())
        assert listing.refused == ()
        assert [item.uri for item in listing.skills] == [GREETINGS, PDF, REFUNDS]
        refunds = by_uri(listing)[REFUNDS]
        assert (refunds.origin, refunds.name, refunds.description) == ("docs", "refunds", "Handles refund requests.")
        assert refunds.key == ("docs", REFUNDS)
        assert refunds.frontmatter == {
            "name": "refunds",
            "description": "Handles refund requests.",
            "license": "MIT",
            "metadata": {"owner": "billing", "tags": ["refunds", "support"]},
        }
        expected = truth_of(tree)
        for item in listing.skills:
            wanted = {uri for uri in expected if uri.startswith(item.uri.removesuffix("SKILL.md"))}
            assert {f.uri for f in item.files} == wanted
            for ref in item.files:
                assert (ref.size, ref.digest) == (len(expected[ref.uri]), digest_of(expected[ref.uri]))
        assert got == refunds
        # SC-004: a listing, and a get, read no file.
        assert sent(record, "resources/read") == []
        assert len(sent(record, "skills/list")) == 1 and len(sent(record, "skills/get")) == 1

    def test_get_of_an_unknown_skill_is_the_servers_own_error_not_a_refusal(self, tmp_path: Path) -> None:
        async def body() -> MCPError:
            async with connected(SkillsExtension(standard_tree(tmp_path).root)) as skills:
                with pytest.raises(MCPError) as caught:  # caught inside: the harness wraps what escapes
                    await skills.get("skill://nothing/SKILL.md")
                return caught.value

        assert run(body()).error.code == -32602

    def test_list_follows_the_cursor_until_there_is_none(self, tmp_path: Path) -> None:
        class Paged(SkillsExtension):
            async def _list(self, ctx: Any, params: Any) -> ListSkillsResult:
                skills = self.catalogue.skills
                after = {None: 0, "after-0": 1, "after-1": 2}[params.cursor if params else None]
                last = after == len(skills) - 1
                return ListSkillsResult(
                    skills=[self._entry(skills[after])],
                    next_cursor=None if last else f"after-{after}",
                    ttl_ms=0,
                    cache_scope="private",
                )

        record: Record = []

        async def body() -> SkillListing:
            async with connected(Paged(standard_tree(tmp_path).root), record=record) as skills:
                return await skills.list()

        listing = run(body())
        assert [item.uri for item in listing.skills] == [GREETINGS, PDF, REFUNDS] and listing.refused == ()
        cursors = [m.get("params", {}).get("cursor") for m in sent(record, "skills/list")]
        assert cursors == [None, "after-0", "after-1"]

    def test_a_frontmatter_field_is_data_and_nothing_is_done_with_it(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "tool-user", extra="allowed-tools: Bash(rm -rf /)\ndisable-model-invocation: true\n")

        async def body() -> SkillItem:
            async with connected(SkillsExtension(root)) as skills:
                (item,) = (await skills.list()).skills
                await skills.load(item)  # loading it is verifying it, nothing more
                return item

        item = run(body())
        assert item.frontmatter["allowed-tools"] == "Bash(rm -rf /)"
        assert item.frontmatter["disable-model-invocation"] is True

    def test_two_skills_of_one_name_under_different_prefixes_stay_apart(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "a/pdf", description="The a one.")
        write_skill(root, "b/pdf", description="The b one.")

        async def body() -> SkillListing:
            async with connected(SkillsExtension(root)) as skills:
                return await skills.list()

        a, b = run(body()).skills
        assert (a.name, b.name) == ("pdf", "pdf")
        assert (a.uri, b.uri) == ("skill://a/pdf/SKILL.md", "skill://b/pdf/SKILL.md")
        assert a.key != b.key and (a.description, b.description) == ("The a one.", "The b one.")

    def test_one_skill_from_two_servers_has_two_keys_and_two_clients_share_nothing(self, tmp_path: Path) -> None:
        root = standard_tree(tmp_path).root
        record: Record = []

        async def body() -> tuple[SkillItem, SkillItem]:
            async with connected(SkillsExtension(root), origin="one", record=record) as one:
                async with connected(SkillsExtension(root), origin="two", record=record) as two:
                    a = by_uri(await one.list())[PDF]
                    b = by_uri(await two.list())[PDF]
                    await one.load(a)
                    await two.load(b)  # a second client has no memory of the first one's read
                    return a, b

        a, b = run(body())
        assert a.uri == b.uri and a.key == ("one", PDF) and b.key == ("two", PDF) and a.key != b.key
        assert len(sent(record, "resources/read")) == 2


class TestLoadAndRead:
    def test_load_reads_only_skill_md_and_read_one_file_each(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        expected = truth_of(tree)
        record: Record = []

        async def body() -> tuple[LoadedSkill, SkillContent, SkillContent]:
            async with connected(SkillsExtension(tree.root), record=record) as skills:
                item = by_uri(await skills.list())[PDF]
                assert sent(record, "resources/read") == []
                loaded = await skills.load(item)
                assert len(sent(record, "resources/read")) == 1
                one = await skills.read(item, REFERENCE)
                two = await skills.read(item, LOGO)
                return loaded, one, two

        loaded, one, two = run(body())
        assert loaded.instructions.data == expected[PDF] and loaded.item.uri == PDF
        assert (loaded.instructions.origin, loaded.instructions.uri) == ("docs", PDF)
        assert (one.data, one.uri, one.origin) == (expected[REFERENCE], REFERENCE, "docs")
        assert two.data == expected[LOGO]
        # SC-004: 1 for SKILL.md, then 1 for each supporting file asked for; nothing read ahead.
        assert [m["params"]["uri"] for m in sent(record, "resources/read")] == [PDF, REFERENCE, LOGO]

    def test_every_file_of_every_skill_comes_through_the_client_byte_for_byte(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        expected = truth_of(tree)

        async def body() -> dict[str, bytes]:
            got: dict[str, bytes] = {}
            async with connected(SkillsExtension(tree.root)) as skills:
                for item in (await skills.list()).skills:
                    for ref in item.files:
                        got[ref.uri] = (await skills.read(item, ref.uri)).data
            return got

        got = run(body())
        assert got == expected and len(got) == 12  # the BOM and CRLF file, the Latin-1 file and the binary one too

    def test_text_decodes_strictly(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)

        async def body() -> dict[str, SkillContent]:
            async with connected(SkillsExtension(tree.root)) as skills:
                item = by_uri(await skills.list())["skill://greetings/SKILL.md"]
                return {
                    ref.uri.rsplit("/", 1)[1]: await skills.read(item, ref.uri)
                    for ref in item.files
                    if not ref.uri.endswith("SKILL.md")
                }

        files = run(body())
        assert files["windows.txt"].text() == "﻿line one\r\nline two\r\n"  # the BOM stays a character
        assert files["caf%C3%A9.md"].text() == "Un café, s'il vous plaît.\n"
        with pytest.raises(UnicodeDecodeError):
            files["legacy.txt"].text()  # Latin-1 is not UTF-8: there is no guess, no replacement

    def test_a_file_the_server_sends_as_a_blob_or_as_text_verifies_either_way(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)

        def as_blob(uri: str, truth: types.ReadResourceResult) -> types.ReadResourceResult:
            (content,) = truth.contents
            data = content.text.encode() if isinstance(content, types.TextResourceContents) else base64.b64decode(content.blob)
            return types.ReadResourceResult(
                contents=[types.BlobResourceContents(uri=uri, blob=base64.b64encode(data).decode(), mime_type="x/y")]
            )

        async def body() -> bytes:
            async with connected(LyingServer(SkillsExtension(tree.root), as_blob)) as skills:
                item = by_uri(await skills.list())[PDF]
                return (await skills.read(item, REFERENCE)).data

        assert run(body()) == truth_of(tree)[REFERENCE]

    def test_the_sdk_cache_is_bypassed_so_every_call_reaches_the_server_and_is_verified(self, tmp_path: Path) -> None:
        # A server may let a `resources/read` answer be kept (`ttlMs`), and the SDK client then serves
        # the second plain read from memory; the skills client never does: each read goes out and is
        # checked. The pair of plain reads is the control that shows the cache is on.
        tree = standard_tree(tmp_path)
        record: Record = []

        def keepable(uri: str, truth: types.ReadResourceResult) -> types.ReadResourceResult:
            return truth.model_copy(update={"ttl_ms": 60_000})

        async def body() -> None:
            server = LyingServer(SkillsExtension(tree.root), keepable)
            async with serve(server, record=record) as served:
                transport = streamable_http_client(URL, http_client=http_client(served))
                async with Client(transport, cache=CacheConfig()) as client:
                    skills = SkillsClient(client, origin="docs")
                    item = by_uri(await skills.list())[PDF]
                    await skills.read(item, REFERENCE)
                    await skills.read(item, REFERENCE)
                    await client.read_resource(REFERENCE)  # the plain SDK call: cached by the SDK
                    await client.read_resource(REFERENCE)

        run(body())
        assert len(sent(record, "resources/read")) == 3  # two bypassed reads, one cached pair


# --- Part B: a lying server (SC-002) --------------------------------------------------------------


def front(**fields: Any) -> Callable[[Any], Any]:
    return lambda e: {**e, "frontmatter": {**e["frontmatter"], **fields}}


def without_field(name: str) -> Callable[[Any], Any]:
    return lambda e: {**e, "frontmatter": {k: v for k, v in e["frontmatter"].items() if k != name}}


def put(**fields: Any) -> Callable[[Any], Any]:
    return lambda e: {**e, **fields}


def drop(name: str) -> Callable[[Any], Any]:
    return lambda e: {k: v for k, v in e.items() if k != name}


def resources(change: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]) -> Callable[[Any], Any]:
    return lambda e: {**e, "resources": change(copy.deepcopy(e["resources"]))}


def edit(target: str, /, **fields: Any) -> Callable[[Any], Any]:
    """Change fields of one resource of the entry (`uri` among them)."""
    return resources(lambda rs: [{**r, **fields} if r["uri"] == target else r for r in rs])


def without_key(uri: str, key: str) -> Callable[[Any], Any]:
    return resources(lambda rs: [{k: v for k, v in r.items() if k != key} if r["uri"] == uri else r for r in rs])


def totalling(total: int) -> Callable[[Any], Any]:
    """The entry whose files hold exactly `total` bytes together: `SKILL.md` takes what the rest leave."""
    def change(rs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        others = sum(r["size"] for r in rs if r["uri"] != PDF)
        return [{**r, "size": total - others} if r["uri"] == PDF else r for r in rs]
    return resources(change)


def many(n: int) -> Callable[[Any], Any]:
    """The entry with exactly `n` resources: `SKILL.md` and invented files with zero bytes."""
    def change(rs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        own = next(r for r in rs if r["uri"] == PDF)
        return [own] + [{"uri": f"skill://pdf-notes/x/{i}.txt", "digest": "sha256:" + "0" * 64, "size": 0} for i in range(n - 1)]
    return resources(change)


BAD_ENTRIES: list[tuple[str, Callable[[Any], Any], str]] = [
    ("the entry is a number", lambda e: 42, "entry"),
    ("the entry is an array", lambda e: [e], "entry"),
    ("no uri", drop("uri"), "entry"),
    ("the uri is not a string", put(uri=7), "entry"),
    ("no frontmatter", drop("frontmatter"), "entry"),
    ("the frontmatter is not an object", put(frontmatter="name: x"), "entry"),
    ("no name", without_field("name"), "entry"),
    ("the name is not a string", front(name=3), "entry"),
    ("no description", without_field("description"), "entry"),
    ("the description is not a string", front(description=["a"]), "entry"),
    ("the uri ends in another file", put(uri="skill://pdf-notes/OTHER.md"), "entry"),
    ("the uri is that of another skill", put(uri="skill://other/SKILL.md"), "entry"),
    ("the uri has no scheme", put(uri="pdf-notes/SKILL.md"), "entry"),
    ("the uri has one slash after the scheme", put(uri="skill:/pdf-notes/SKILL.md"), "entry"),
    ("the uri is of another scheme and the files are not under it", put(uri="https://pdf-notes/SKILL.md"), "resources"),
    ("the uri has a query", put(uri="skill://pdf-notes/SKILL.md?x=1"), "entry"),
    ("the uri spells SKILL.md with an encoded character", put(uri="skill://pdf-notes/SKILL%2Emd"), "entry"),
    ("the name is empty", lambda e: {**e, "uri": "skill:///SKILL.md", "frontmatter": {**e["frontmatter"], "name": ""}}, "entry"),
    ("a file of another skill is listed", edit(LOGO, uri="skill://other/x.txt"), "resources"),
    ("a file of a neighbour that starts like the skill is listed", edit(LOGO, uri="skill://pdf-notes-evil/x.txt"), "resources"),
    ("the skill folder itself is listed as a file", edit(LOGO, uri="skill://pdf-notes"), "resources"),
    ("a file of another scheme is listed", edit(LOGO, uri="docs://pdf-notes/x.txt"), "resources"),
    ("a listed file has an empty segment", edit(LOGO, uri="skill://pdf-notes//x.txt"), "resources"),
    ("a listed file ends in a slash", edit(LOGO, uri="skill://pdf-notes/x/"), "resources"),
    ("a listed file has a dot segment", edit(LOGO, uri="skill://pdf-notes/./x.txt"), "resources"),
    ("a listed file climbs out", edit(LOGO, uri="skill://pdf-notes/../other/x.txt"), "resources"),
    ("a listed file climbs out, encoded", edit(LOGO, uri="skill://pdf-notes/%2e%2e/x.txt"), "resources"),
    ("a listed file has an encoded slash", edit(LOGO, uri="skill://pdf-notes/a%2Fb.txt"), "resources"),
    ("a listed file has an encoded backslash", edit(LOGO, uri="skill://pdf-notes/a%5Cb.txt"), "resources"),
    ("a listed file has an encoded line feed", edit(LOGO, uri="skill://pdf-notes/a%0Ab.txt"), "resources"),
    ("the uri is SKILL.md alone", put(uri="skill://SKILL.md"), "entry"),
    ("the name is not the folder's", front(name="pdf"), "entry"),
    ("resources is missing", drop("resources"), "resources"),
    ("resources is dynamic", put(resources="dynamic"), "resources"),
    ("resources is an object", put(resources={}), "resources"),
    ("resources is a number", put(resources=3), "resources"),
    ("a resource is not an object", resources(lambda rs: [*rs, 5]), "resources"),
    ("a resource has no uri", without_key(LOGO, "uri"), "resources"),
    ("a resource uri is not a string", edit(LOGO, uri=4), "resources"),
    ("a digest is missing", without_key(LOGO, "digest"), "resources"),
    ("a digest is not a string", edit(LOGO, digest=5), "resources"),
    ("a digest is in upper case", edit(LOGO, digest="sha256:" + "A" * 64), "resources"),
    ("a digest has no prefix", edit(LOGO, digest="0" * 64), "resources"),
    ("a digest is short", edit(LOGO, digest="sha256:abcd"), "resources"),
    ("a digest is long", edit(LOGO, digest="sha256:" + "0" * 65), "resources"),
    ("a size is missing", without_key(LOGO, "size"), "resources"),
    ("a size is negative", edit(LOGO, size=-1), "resources"),
    ("a size is not whole", edit(LOGO, size=1.5), "resources"),
    ("a size is a boolean", edit(LOGO, size=True), "resources"),
    ("a size is a string", edit(LOGO, size="9"), "resources"),
    ("a resource uri is repeated", resources(lambda rs: [*rs, rs[0]]), "resources"),
    ("SKILL.md is not among the resources", resources(lambda rs: [r for r in rs if r["uri"] != PDF]), "resources"),
    ("513 resources", many(MAX_FILES + 1), "limit"),
    ("one byte more than 16 MiB", totalling(MAX_BYTES + 1), "limit"),
    ("one file of more than 16 MiB", edit(PDF, size=MAX_BYTES + 1), "limit"),
    ("two files together more than 16 MiB", resources(lambda rs: [{**rs[0], "size": MAX_BYTES}, {**rs[1], "size": 1}, *rs[2:]]), "limit"),
]


class TestAnEntryThatIsNotValid:
    @pytest.mark.parametrize(("lie", "check"), [(lie, check) for _, lie, check in BAD_ENTRIES], ids=[w for w, _, _ in BAD_ENTRIES])
    def test_list_returns_the_good_ones_and_names_the_bad_one_and_get_raises(
        self, tmp_path: Path, lie: Callable[[Any], Any], check: str
    ) -> None:
        ext = Lying(standard_tree(tmp_path).root, entry={PDF: lie})
        sent_uri = ext.wire(ext.catalogue.by_uri[PDF])  # what the server sends for it, lie applied
        record: Record = []

        async def body() -> tuple[SkillListing, SkillRefused]:
            async with connected(ext, record=record) as skills:
                listing = await skills.list()
                with pytest.raises(SkillRefused) as caught:
                    await skills.get(PDF)
                return listing, caught.value

        listing, refusal = run(body())
        assert [item.uri for item in listing.skills] == [GREETINGS, REFUNDS]  # the others still come
        (refused,) = listing.refused
        entry_uri = sent_uri.get("uri") if isinstance(sent_uri, dict) else None
        assert isinstance(refused, RefusedEntry) and refused.check == check
        assert refused.uri == (entry_uri if isinstance(entry_uri, str) else None) and refused.reason
        assert (refusal.check, refusal.uri, refusal.reason) == (refused.check, refused.uri, refused.reason)
        assert sent(record, "resources/read") == []  # a bad entry is refused with no file read

    @pytest.mark.parametrize(
        ("lie", "says"),
        [
            (lambda e: 42, "not an object"),
            (drop("uri"), "no uri"),
            (put(frontmatter="name: x"), "no frontmatter that is an object"),
            (front(name=3), "no name that is a string"),
            (front(description=["a"]), "no description that is a string"),
            (drop("resources"), "does not list its files"),
            (resources(lambda rs: [*rs, 5]), "is not an object"),
            (resources(lambda rs: [*rs, {"digest": rs[0]["digest"], "size": 1}]), "no uri that is a string"),
            (edit(LOGO, digest="0" * 64), "no digest of the form sha256:<64 lowercase hex>"),
            (edit(LOGO, size=-1), "no size that is a whole number of bytes"),
            (resources(lambda rs: [*rs, rs[0]]), "one file twice"),
            (resources(lambda rs: [r for r in rs if r["uri"] != PDF]), "its own SKILL.md"),
            (many(MAX_FILES + 1), "more than 512 files"),
            (totalling(MAX_BYTES + 1), "more than 16777216 bytes"),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_the_reason_says_what_is_wrong_with_the_entry(self, tmp_path: Path, lie: Callable[[Any], Any], says: str) -> None:
        # Several checks refuse the same entry with the same `check`; the reason is how a caller
        # (and a person reading a log) tells which one did.
        async def body() -> RefusedEntry:
            async with connected(Lying(standard_tree(tmp_path).root, entry={PDF: lie})) as skills:
                (refused,) = (await skills.list()).refused
                return refused

        assert says in run(body()).reason

    def test_the_files_of_an_item_keep_the_order_the_server_listed_them_in(self, tmp_path: Path) -> None:
        ext = SkillsExtension(standard_tree(tmp_path).root)

        async def body() -> SkillListing:
            async with connected(ext) as skills:
                return await skills.list()

        for item in run(body()).skills:
            listed = [(r.uri, r.size, r.digest) for r in ext.catalogue.by_uri[item.uri].files]
            assert [(f.uri, f.size, f.digest) for f in item.files] == listed and len(listed) > 1

    def test_the_reasons_for_resources_that_are_not_given_are_three_distinct_ones(self, tmp_path: Path) -> None:
        reasons = set()
        for lie in (drop("resources"), put(resources="dynamic"), put(resources={})):
            ext = Lying(standard_tree(tmp_path).root, entry={PDF: lie})

            async def body() -> SkillListing:
                async with connected(ext) as skills:
                    return await skills.list()

            reasons.add(run(body()).refused[0].reason)
        assert len(reasons) == 3

    @pytest.mark.parametrize(
        ("lie", "label"),
        [(many(MAX_FILES), "exactly 512 files"), (totalling(MAX_BYTES), "exactly 16 MiB")],
        ids=["512-files", "16-mib"],
    )
    def test_the_limits_themselves_pass(self, tmp_path: Path, lie: Callable[[Any], Any], label: str) -> None:
        async def body() -> SkillListing:
            async with connected(Lying(standard_tree(tmp_path).root, entry={PDF: lie})) as skills:
                return await skills.list()

        listing = run(body())
        assert listing.refused == () and len(listing.skills) == 3, label

    def test_get_that_answers_for_another_skill_is_refused(self, tmp_path: Path) -> None:
        ext = Lying(standard_tree(tmp_path).root, entry={GREETINGS: lambda e: copy.deepcopy(ext.wire(ext.catalogue.by_uri[PDF]))})

        async def body() -> SkillRefused:
            async with connected(ext) as skills:
                with pytest.raises(SkillRefused) as caught:
                    await skills.get(GREETINGS)
                return caught.value

        refusal = run(body())
        assert refusal.check == "response" and refusal.uri == GREETINGS

    def test_an_entry_listed_twice_is_returned_once_and_the_second_is_refused(self, tmp_path: Path) -> None:
        class Twice(Lying):
            async def _list(self, ctx: Any, params: Any) -> Any:
                skills = self.catalogue.skills
                return RawListSkillsResult(
                    skills=[self.wire(s) for s in (*skills, skills[0])], ttl_ms=0, cache_scope="private"
                )

        async def body() -> SkillListing:
            async with connected(Twice(standard_tree(tmp_path).root)) as skills:
                return await skills.list()

        listing = run(body())
        assert [item.uri for item in listing.skills] == [GREETINGS, PDF, REFUNDS]
        (refused,) = listing.refused
        assert (refused.check, refused.uri) == ("entry", GREETINGS) and "more than once" in refused.reason


def raw_entry(
    *, root: str = "skill://pdf-notes", name: str = "pdf-notes", description: str = "Takes notes.", files: tuple[str, ...] = ()
) -> dict[str, Any]:
    """A valid wire entry, written by hand: `SKILL.md` and `files` under `root`, each one byte."""
    uris = [f"{root}/SKILL.md", *files]
    return {
        "uri": f"{root}/SKILL.md",
        "frontmatter": {"name": name, "description": description},
        "resources": [{"uri": uri, "digest": "sha256:" + "0" * 64, "size": 1} for uri in uris],
    }


def refusal_of(raw: Any) -> SkillRefused:
    with pytest.raises(SkillRefused) as caught:
        parse_entry("docs", raw)
    return caught.value


class TestWhatAnEntryMustBe:
    """The rules `parse_entry` holds an entry to, checked on an entry written by hand."""

    @pytest.mark.parametrize(
        ("root", "name"),
        [
            ("skill://x", "x"),
            ("skill://" + "a" * 64, "a" * 64),
            ("skill://caf%C3%A9", "café"),
            ("skill://team/Docs_v2", "Docs_v2"),
            ("docs://pdf-notes", "pdf-notes"),
            ("HTTPS://host/pdf-notes", "pdf-notes"),
            ("x-skill+v1.2://pdf-notes", "pdf-notes"),
        ],
        ids=["one-letter", "64-characters", "non-ascii", "upper-case-and-underscore", "docs-scheme", "https-scheme", "odd-scheme"],
    )
    def test_a_name_and_a_scheme_that_are_fine_pass_and_so_do_files_inside(self, root: str, name: str) -> None:
        """No scheme is privileged (the extension's own text); the files are inside the skill's folder."""
        files = (f"{root}/a/b/c.txt", f"{root}/caf%C3%A9.md", f"{root}/x.txt?y=1")
        item = parse_entry("docs", raw_entry(root=root, name=name, files=files))
        assert (item.name, item.uri) == (name, f"{root}/SKILL.md")
        assert [f.uri for f in item.files][1:] == list(files)

    @pytest.mark.parametrize(
        ("root", "name"),
        [
            ("skill://", ""),
            ("skill://" + "a" * 65, "a" * 65),
            ("skill://pdf%20notes", "pdf notes"),
            ("skill://a%5Cb", "a\\b"),
            ("skill://a%2Fb", "a/b"),
            ("skill://a%0Ab", "a\nb"),
            ("skill://a%09b", "a\tb"),
            ("skill://a%E2%80%AEb", "a" + chr(0x202E) + "b"),  # a right-to-left override
            ("skill://a%C2%A0b", "a" + chr(0xA0) + "b"),  # a no-break space
        ],
        ids=["empty", "65-characters", "a-space", "a-backslash", "a-slash", "a-line-feed", "a-tab", "a-bidi-override", "a-no-break-space"],
    )
    def test_a_name_that_is_not_one_to_64_printable_characters_without_a_space_or_a_slash_is_refused(
        self, root: str, name: str
    ) -> None:
        refused = refusal_of(raw_entry(root=root, name=name))
        assert refused.check == "entry" and "name" in refused.reason
        assert name == "" or name not in refused.reason  # a reason is fixed text: it never quotes what the server sent

    @pytest.mark.parametrize("length", [1, 1024])
    def test_a_description_of_1_to_1024_characters_passes(self, length: int) -> None:
        assert len(parse_entry("docs", raw_entry(description="d" * length)).description) == length

    @pytest.mark.parametrize("length", [0, 1025])
    def test_a_description_that_is_empty_or_over_1024_characters_is_refused(self, length: int) -> None:
        refused = refusal_of(raw_entry(description="d" * length))
        assert refused.check == "entry" and "description" in refused.reason

    @pytest.mark.parametrize(
        "root",
        ["pdf-notes", "skill:/pdf-notes", "skill:pdf-notes", "://pdf-notes", "1skill://pdf-notes", "sk ill://pdf-notes", "skill//pdf-notes"],
        ids=["no-scheme", "one-slash", "no-slash", "empty-scheme", "digit-first", "a-space", "no-colon"],
    )
    def test_a_uri_that_does_not_begin_with_a_scheme_and_two_slashes_is_refused(self, root: str) -> None:
        assert refusal_of(raw_entry(root=root)).check == "entry"


class TestAKnownLimit:
    """The client compares the entry's frontmatter with what this package's reader makes of `SKILL.md`,
    and that reader leaves a plain scalar as text unless it is a JSON number, boolean or null. A server
    that reads YAML 1.1 sends `true` for `yes`: that entry does not match its own file, and is refused."""

    @pytest.mark.parametrize(
        ("text", "typed"),
        [
            ("yes", True),
            ("off", False),
            ("0755", 493),
            ("0x1f", 31),
            ("1_000", 1000),
            ("12:30", 750),
            ("2026-01-02 10:00:00", "2026-01-02T10:00:00"),
        ],
        ids=["yes", "off", "octal", "hex", "underscore", "sexagesimal", "timestamp"],
    )
    def test_an_entry_that_types_what_the_reader_leaves_as_text_is_refused(
        self, tmp_path: Path, text: str, typed: Any
    ) -> None:
        folder = tmp_path / "skills"
        write_skill(folder, "typed", extra=f"setting: {text}\n")
        uri = "skill://typed/SKILL.md"

        async def body() -> tuple[Any, SkillRefused]:
            async with connected(Lying(folder, entry={uri: front(setting=typed)})) as skills:
                (item,) = (await skills.list()).skills
                with pytest.raises(SkillRefused) as caught:
                    await skills.load(item)
                return item.frontmatter["setting"], caught.value

        sent_value, refusal = run(body())
        assert sent_value == typed
        assert refusal.check == "frontmatter" and "differs" in refusal.reason

    def test_the_same_file_served_honestly_loads_and_the_text_stays_text(self, tmp_path: Path) -> None:
        folder = tmp_path / "skills"
        write_skill(folder, "typed", extra="setting: yes\n")

        async def body() -> Any:
            async with connected(SkillsExtension(folder)) as skills:
                (item,) = (await skills.list()).skills
                await skills.load(item)
                return item.frontmatter["setting"]

        assert run(body()) == "yes"


class TestAFileThatDoesNotVerify:
    """The server's entry and the bytes it sends disagree, or the entry itself lies about a file."""

    @pytest.mark.parametrize(
        ("lie", "check", "target"),
        [
            pytest.param(edit(REFERENCE, size=10_000), "size", REFERENCE, id="size bigger"),
            pytest.param(edit(REFERENCE, size=3), "size", REFERENCE, id="size smaller"),
            pytest.param(edit(REFERENCE, size=len(b"# Reference\n\nA short reference.\n") - 1), "size", REFERENCE, id="size one less"),
            pytest.param(edit(REFERENCE, size=len(b"# Reference\n\nA short reference.\n") + 1), "size", REFERENCE, id="size one more"),
            pytest.param(edit(LOGO, size=3), "size", LOGO, id="size of a blob smaller"),
            pytest.param(edit(LOGO, size=10), "size", LOGO, id="size of a blob bigger"),
            pytest.param(edit(REFERENCE, digest="sha256:" + "0" * 64), "digest", REFERENCE, id="digest differs"),
            pytest.param(edit(LOGO, digest="sha256:" + "0" * 64), "digest", LOGO, id="digest of a blob differs"),
        ],
    )
    def test_an_entry_that_lies_about_a_file_is_caught_by_the_read(
        self, tmp_path: Path, lie: Callable[[Any], Any], check: str, target: str
    ) -> None:
        async def body() -> SkillRefused:
            async with connected(Lying(standard_tree(tmp_path).root, entry={PDF: lie})) as skills:
                item = by_uri(await skills.list())[PDF]
                with pytest.raises(SkillRefused) as caught:
                    await skills.read(item, target)
                return caught.value

        refusal = run(body())
        assert (refusal.check, refusal.uri) == (check, target) and refusal.reason

    @pytest.mark.parametrize(
        ("label", "change", "check"),
        [
            ("same length, other bytes", lambda b: b"X" * len(b), "digest"),
            ("one byte flipped", lambda b: bytes([b[0] ^ 1]) + b[1:], "digest"),
            ("a byte added", lambda b: b + b"!", "size"),
            ("a byte missing", lambda b: b[:-1], "size"),
            ("empty", lambda b: b"", "size"),
        ],
    )
    def test_tampered_bytes_are_caught_whichever_way_they_are_sent(
        self, tmp_path: Path, label: str, change: Callable[[bytes], bytes], check: str
    ) -> None:
        for target in (REFERENCE, LOGO):  # one sent as text, one as a blob
            ext = Lying(standard_tree(tmp_path).root, data={target: change})

            async def body() -> SkillRefused:
                async with connected(ext) as skills:
                    item = by_uri(await skills.list())[PDF]
                    with pytest.raises(SkillRefused) as caught:
                        await skills.read(item, target)
                    return caught.value

            refusal = run(body())
            assert refusal.check == check and refusal.uri == target, label

    @pytest.mark.parametrize(
        ("target", "name"),
        [("skill://greetings/caf%C3%A9.md", "text"), ("skill://pdf-notes/assets/logo.bin", "blob")],
        ids=["multi-byte text", "blob"],
    )
    def test_a_size_that_is_one_byte_short_gets_past_the_bound_and_is_still_a_size_failure(
        self, tmp_path: Path, target: str, name: str
    ) -> None:
        # The bound is taken from the size before decoding: 25 characters are at most 26 bytes, and
        # the base64 of 9 bytes fits the base64 of 8. The bytes are then counted, exactly.
        tree = standard_tree(tmp_path)
        skill = target.split("/")[2] + "/SKILL.md"
        skill_uri = "skill://" + skill
        ext = Lying(tree.root, entry={skill_uri: edit(target, size=len(truth_of(tree)[target]) - 1)})

        async def body() -> SkillRefused:
            async with connected(ext) as skills:
                item = by_uri(await skills.list())[skill_uri]
                with pytest.raises(SkillRefused) as caught:
                    await skills.read(item, target)
                return caught.value

        refusal = run(body())
        assert (refusal.check, refusal.uri) == ("size", target), name
        assert "number of bytes" in refusal.reason  # not the bound, which says "longer"

    def test_nothing_is_returned_by_a_refused_read_and_the_good_files_still_load(self, tmp_path: Path) -> None:
        tree = standard_tree(tmp_path)
        ext = Lying(tree.root, data={REFERENCE: lambda b: b"X" * len(b)})

        async def body() -> bytes:
            async with connected(ext) as skills:
                item = by_uri(await skills.list())[PDF]
                result: Any = None
                with pytest.raises(SkillRefused):
                    result = await skills.read(item, REFERENCE)
                assert result is None
                return (await skills.load(item)).instructions.data

        assert run(body()) == truth_of(tree)[PDF]

    @pytest.mark.parametrize(
        "lie",
        [
            front(license="GPL"),  # a value differs
            front(extra="not in the file"),  # the entry has a field the file lacks
            without_field("license"),  # the file has a field the entry lacks
        ],
        ids=["a-value-differs", "a-field-is-added", "a-field-is-removed"],
    )
    def test_the_frontmatter_of_skill_md_must_equal_the_entrys(self, tmp_path: Path, lie: Callable[[Any], Any]) -> None:
        # The entry is changed, not the file: `REFUNDS` has `license`, which the entry may drop or alter.
        ext = Lying(standard_tree(tmp_path).root, entry={REFUNDS: lie})

        async def body() -> SkillRefused:
            async with connected(ext) as skills:
                item = by_uri(await skills.list())[REFUNDS]  # the entry is valid in itself
                with pytest.raises(SkillRefused) as caught:
                    await skills.load(item)
                return caught.value

        refusal = run(body())
        assert (refusal.check, refusal.uri) == ("frontmatter", REFUNDS)

    def test_the_three_frontmatter_differences_have_three_reasons(self, tmp_path: Path) -> None:
        reasons = set()
        for lie in (front(license="GPL"), front(extra="x"), without_field("license")):
            ext = Lying(standard_tree(tmp_path).root, entry={REFUNDS: lie})

            async def body() -> SkillRefused:
                async with connected(ext) as skills:
                    item = by_uri(await skills.list())[REFUNDS]
                    with pytest.raises(SkillRefused) as caught:
                        await skills.load(item)
                    return caught.value

            reasons.add(run(body()).reason)
        assert len(reasons) == 3

    @pytest.mark.parametrize(
        "lie",
        [
            front(license=True),  # the file says the text MIT: a boolean is not a string
            front(metadata={"owner": "billing", "tags": ["refunds", "support", "x"]}),
            front(metadata={"owner": "billing", "tags": ["support", "refunds"]}),  # order of a list matters
            front(metadata={"owner": "billing"}),
            front(metadata={"owner": "billing", "tags": ["refunds", "support"], "extra": 1}),
        ],
        ids=["bool-for-string", "longer-list", "other-order", "missing-key", "extra-key"],
    )
    def test_nested_values_are_compared_whole(self, tmp_path: Path, lie: Callable[[Any], Any]) -> None:
        ext = Lying(standard_tree(tmp_path).root, entry={REFUNDS: lie})

        async def body() -> SkillRefused:
            async with connected(ext) as skills:
                item = by_uri(await skills.list())[REFUNDS]
                with pytest.raises(SkillRefused) as caught:
                    await skills.load(item)
                return caught.value

        assert run(body()).check == "frontmatter"

    def test_a_boolean_is_not_a_number_and_a_whole_float_is_the_same_number(self, tmp_path: Path) -> None:
        root = tmp_path / "skills"
        write_skill(root, "typed", extra="flag: true\nlevel: 1\nratio: 2.0\n")
        ext_true = Lying(root, entry={"skill://typed/SKILL.md": front(flag=1)})  # `1` for `true`
        ext_one = Lying(root, entry={"skill://typed/SKILL.md": front(level=True)})  # `true` for `1`
        ext_float = Lying(root, entry={"skill://typed/SKILL.md": front(ratio=2)})  # `2` for `2.0`: one number

        async def body(ext: SkillsExtension) -> str:
            async with connected(ext) as skills:
                item = by_uri(await skills.list())["skill://typed/SKILL.md"]
                try:
                    await skills.load(item)
                except SkillRefused as e:
                    return e.check
                return "ok"

        assert [run(body(e)) for e in (ext_true, ext_one, ext_float)] == ["frontmatter", "frontmatter", "ok"]

    def test_a_skill_md_whose_frontmatter_cannot_be_read_is_refused_even_when_its_digest_matches(self, tmp_path: Path) -> None:
        bad = b"# no frontmatter at all\n"
        ext = Lying(
            standard_tree(tmp_path).root,
            entry={PDF: edit(PDF, size=len(bad), digest=digest_of(bad))},
            data={PDF: lambda b: bad},
        )

        async def body() -> SkillRefused:
            async with connected(ext) as skills:
                item = by_uri(await skills.list())[PDF]
                with pytest.raises(SkillRefused) as caught:
                    await skills.load(item)
                return caught.value

        refusal = run(body())
        assert (refusal.check, refusal.uri) == ("frontmatter", PDF)
        assert "no frontmatter" not in refusal.reason  # the reason never carries the file's text

    def test_only_the_skills_own_skill_md_is_checked_for_frontmatter(self, tmp_path: Path) -> None:
        # `examples/SKILL.md` is an ordinary file of `refunds`; the file need not have any frontmatter.
        tree = standard_tree(tmp_path)

        async def body() -> bytes:
            async with connected(SkillsExtension(tree.root)) as skills:
                item = by_uri(await skills.list())[REFUNDS]
                return (await skills.read(item, "skill://team/billing/refunds/examples/SKILL.md")).data

        assert run(body()) == truth_of(tree)["skill://team/billing/refunds/examples/SKILL.md"]


class TestAFileThatIsNotListed:
    @pytest.mark.parametrize(
        "uri",
        [
            "skill://pdf-notes/not-there.md",  # nothing at all
            "skill://greetings/legacy.txt",  # a real file, of another skill
            "skill://pdf-notes/reference.md?x=1",
            "skill://pdf-notes/../greetings/legacy.txt",
            "skill://PDF-NOTES/reference.md",
            "file:///etc/passwd",
            "",
        ],
    )
    def test_it_is_refused_and_no_request_is_sent(self, tmp_path: Path, uri: str) -> None:
        record: Record = []

        async def body() -> SkillRefused:
            async with connected(SkillsExtension(standard_tree(tmp_path).root), record=record) as skills:
                item = by_uri(await skills.list())[PDF]
                before = len(record)
                with pytest.raises(SkillRefused) as caught:
                    await skills.read(item, uri)
                assert len(record) == before  # nothing crossed the wire
                return caught.value

        refusal = run(body())
        assert (refusal.check, refusal.uri) == ("unlisted", uri)
        assert sent(record, "resources/read") == []

    def test_load_of_an_item_without_its_skill_md_is_refused_the_same_way(self, tmp_path: Path) -> None:
        async def body() -> SkillRefused:
            async with connected(SkillsExtension(standard_tree(tmp_path).root)) as skills:
                item = by_uri(await skills.list())[PDF]
                forged = SkillItem(
                    item.origin, item.uri, item.name, item.description, item.frontmatter,
                    tuple(f for f in item.files if f.uri != PDF),
                )
                with pytest.raises(SkillRefused) as caught:
                    await skills.load(forged)
                return caught.value

        assert run(body()).check == "unlisted"


class TestAnAnswerThatIsNotOneFile:
    """The server's `resources/read` answer has the wrong shape. The extension itself is honest."""

    @staticmethod
    def reply_with(make: Callable[[str, types.ReadResourceResult], list[Any]]) -> Callable[[str, types.ReadResourceResult], Any]:
        return lambda uri, truth: types.ReadResourceResult(contents=make(uri, truth))

    @pytest.mark.parametrize(
        ("label", "make", "check"),
        [
            ("no content", lambda uri, truth: [], "response"),
            ("two contents", lambda uri, truth: [*truth.contents, *truth.contents], "response"),
            ("another uri", lambda uri, truth: [truth.contents[0].model_copy(update={"uri": "skill://pdf-notes/OTHER.md"})], "response"),
            (
                "a text longer than the size",
                lambda uri, truth: [types.TextResourceContents(uri=uri, text=truth.contents[0].text + "x", mime_type="text/plain")],
                "size",
            ),
            (
                "a blob longer than the base64 of the size",
                lambda uri, truth: [types.BlobResourceContents(uri=uri, blob="A" * 400, mime_type="x/y")],
                "size",
            ),
            (
                "an oversize blob that is not even base64: refused before it is decoded",
                lambda uri, truth: [types.BlobResourceContents(uri=uri, blob="!" * 13, mime_type="x/y")],
                "size",
            ),
            (
                "a blob that is not base64",
                lambda uri, truth: [types.BlobResourceContents(uri=uri, blob="!" * 12, mime_type="x/y")],
                "response",
            ),
            (
                "a blob with the wrong padding",
                lambda uri, truth: [types.BlobResourceContents(uri=uri, blob="AAAAAAAAA", mime_type="x/y")],
                "response",
            ),
        ],
    )
    def test_it_is_refused(self, tmp_path: Path, label: str, make: Callable[..., list[Any]], check: str) -> None:
        target = LOGO if "blob" in label else REFERENCE

        async def body() -> SkillRefused:
            server = LyingServer(SkillsExtension(standard_tree(tmp_path).root), self.reply_with(make))
            async with connected(server) as skills:
                item = by_uri(await skills.list())[PDF]
                with pytest.raises(SkillRefused) as caught:
                    await skills.read(item, target)
                return caught.value

        refusal = run(body())
        assert (refusal.check, refusal.uri) == (check, target), label

    @pytest.mark.parametrize(
        ("size", "longest"),
        [(1, 4), (2, 4), (3, 4), (4, 8), (7, 12), (8, 12), (9, 12), (10, 16)],
        ids=lambda v: str(v),
    )
    def test_the_bound_of_a_blob_is_the_base64_of_the_size_rounded_up(self, tmp_path: Path, size: int, longest: int) -> None:
        # Not base64 at all, so nothing but the bound can say `size`: `longest` characters get past
        # it (and fail as not base64), one more is a size failure before any decoding.
        def blob(length: int) -> Callable[[str, types.ReadResourceResult], Any]:
            return lambda uri, truth: types.ReadResourceResult(
                contents=[types.BlobResourceContents(uri=uri, blob="!" * length, mime_type="x/y")]
            )

        async def body(length: int) -> str:
            ext = Lying(standard_tree(tmp_path).root, entry={PDF: edit(LOGO, size=size)})
            async with connected(LyingServer(ext, blob(length))) as skills:
                item = by_uri(await skills.list())[PDF]
                with pytest.raises(SkillRefused) as caught:
                    await skills.read(item, LOGO)
                return caught.value.check

        assert (run(body(longest)), run(body(longest + 1))) == ("response", "size")

    def test_a_blob_the_size_of_the_base64_of_the_file_is_not_refused_by_the_bound(self, tmp_path: Path) -> None:
        # The bound is exact: the base64 of 9 bytes is 12 characters, and the true blob has 12.
        tree = standard_tree(tmp_path)

        async def body() -> bytes:
            async with connected(SkillsExtension(tree.root)) as skills:
                item = by_uri(await skills.list())[PDF]
                return (await skills.read(item, LOGO)).data

        assert run(body()) == truth_of(tree)[LOGO] and len(base64.b64encode(truth_of(tree)[LOGO])) == 12


class _AnyList(types.PaginatedResult, types.CacheableResult):
    skills: Any  # what a hostile server may put there: the real model would not allow it


class _NoSkill(types.CacheableResult):
    """An answer to `skills/get` that has no `skill`."""


class _Stub:
    """A stand-in for the SDK client, for the answers the real SDK server would never send (it
    checks its own results): `answer(uri)` is what `read_resource` returns, or raises."""

    server_capabilities = types.ServerCapabilities(resources=types.ResourcesCapability(), extensions={EXTENSION_ID: {}})

    def __init__(self, answer: Callable[[str], types.ReadResourceResult]) -> None:
        self._answer = answer

    async def read_resource(self, uri: str, *, cache_mode: str = "use") -> types.ReadResourceResult:
        return self._answer(uri)


def _read_through_stub(answer: Callable[[str], types.ReadResourceResult]) -> SkillRefused:
    item = SkillItem("o", PDF, "pdf-notes", "d", {"name": "pdf-notes", "description": "d"}, (SkillFileRef(PDF, 10, "sha256:" + "0" * 64),))

    async def body() -> SkillRefused:
        with pytest.raises(SkillRefused) as caught:
            await SkillsClient(_Stub(answer), origin="o").read(item, PDF)  # type: ignore[arg-type]
        return caught.value

    return run(body())


class TestAnAnswerThatIsNotTheKindAsked:
    """An answer the SDK cannot read as a skills answer is one refusal, not a pydantic error that
    carries the text the server sent."""

    def test_a_list_that_is_not_an_array_and_a_get_without_a_skill_are_refused(self, tmp_path: Path) -> None:
        class Hostile(SkillsExtension):
            async def _list(self, ctx: Any, params: Any) -> Any:
                return _AnyList(skills="secret-from-the-server")

            async def _get(self, ctx: Any, params: Any) -> Any:
                return _NoSkill()

        async def body() -> list[SkillRefused]:
            refusals: list[SkillRefused] = []
            async with connected(Hostile(standard_tree(tmp_path).root)) as skills:
                for call in (skills.list, lambda: skills.get(PDF)):
                    with pytest.raises(SkillRefused) as caught:
                        await call()
                    refusals.append(caught.value)
            return refusals

        refusals = run(body())
        assert [r.check for r in refusals] == ["response", "response"]
        # The pydantic error holds the text the server sent; `from None` keeps it out of any traceback.
        assert all("secret-from-the-server" not in r.reason and r.__suppress_context__ for r in refusals)

    def test_a_read_that_is_not_a_resource_answer_is_refused(self) -> None:
        def invalid(uri: str) -> types.ReadResourceResult:
            return types.ReadResourceResult.model_validate({"resultType": "complete", "secret": "from-the-server"})  # no contents

        refusal = _read_through_stub(invalid)
        assert (refusal.check, refusal.uri) == ("response", PDF)
        assert "from-the-server" not in refusal.reason and refusal.__suppress_context__

    def test_a_text_that_cannot_be_encoded_is_a_response_failure_not_a_crash(self) -> None:
        # A lone surrogate is a str Python holds and UTF-8 cannot write. It cannot cross the real
        # wire, so a stand-in client hands it over in-process.
        refusal = _read_through_stub(
            lambda uri: types.ReadResourceResult(contents=[types.TextResourceContents(uri=uri, text="\ud800")])
        )
        assert (refusal.check, refusal.uri) == ("response", PDF)

    def test_a_text_longer_than_the_size_is_refused_before_it_is_encoded(self) -> None:
        # The entry says 10 bytes; a text of 50 characters cannot be that, and the caller must not
        # spend memory encoding it to find out. A `str` that refuses to encode proves it is not tried.
        class Bomb(str):
            __slots__ = ()

            def encode(self, *args: Any, **kwargs: Any) -> bytes:
                raise AssertionError("a text longer than the size of the entry was encoded")

        refusal = _read_through_stub(
            lambda uri: types.ReadResourceResult(
                contents=[types.TextResourceContents.model_construct(uri=uri, text=Bomb("x" * 50))]
            )
        )
        assert (refusal.check, refusal.uri) == ("size", PDF)


class TestAServerThatDidNotDeclareTheExtension:
    def test_every_method_refuses_and_no_skills_request_is_sent(self, tmp_path: Path) -> None:
        item = SkillItem("docs", PDF, "pdf-notes", "d", {"name": "pdf-notes", "description": "d"}, (SkillFileRef(PDF, 1, "sha256:" + "0" * 64),))
        record: Record = []
        server = MCPServer("plain")

        @server.resource("skill://pdf-notes/SKILL.md")
        def plain() -> str:
            return "x"

        async def body() -> list[SkillRefused]:
            refusals: list[SkillRefused] = []
            async with connected(server, record=record) as skills:
                before = len(record)
                for call in (skills.list, lambda: skills.get(PDF), lambda: skills.load(item), lambda: skills.read(item, PDF)):
                    with pytest.raises(SkillRefused) as caught:
                        await call()
                    refusals.append(caught.value)
                assert len(record) == before
            return refusals

        refusals = run(body())
        assert [r.check for r in refusals] == ["declaration"] * 4 and all(r.reason for r in refusals)
        assert skills_requests(record) == []


# --- Part C: the types ----------------------------------------------------------------------------


class TestTheTypes:
    def test_a_refusal_carries_its_uri_check_and_reason_and_survives_pickling(self) -> None:
        refusal = SkillRefused("digest", "the SHA-256 differs from the entry's", "skill://a/SKILL.md")
        assert (refusal.check, refusal.reason, refusal.uri) == ("digest", "the SHA-256 differs from the entry's", "skill://a/SKILL.md")
        assert str(refusal) == "digest: the SHA-256 differs from the entry's ('skill://a/SKILL.md')"
        assert str(SkillRefused("declaration", "no skills here")) == "declaration: no skills here"
        again = pickle.loads(pickle.dumps(refusal))
        assert (again.check, again.reason, again.uri) == (refusal.check, refusal.reason, refusal.uri)
        assert isinstance(refusal, Exception)

    def test_a_uri_with_a_line_break_stays_on_one_line_in_the_message(self) -> None:
        assert "\n" not in str(SkillRefused("entry", "bad", "skill://a\nforged log line"))

    def test_the_value_types_are_frozen_and_an_item_is_identified_by_origin_and_uri(self) -> None:
        item = SkillItem("o", "skill://a/SKILL.md", "a", "d", {"name": "a", "description": "d"}, ())
        assert item.key == ("o", "skill://a/SKILL.md")
        for frozen in (
            item,
            SkillFileRef("skill://a/SKILL.md", 1, "sha256:" + "0" * 64),
            RefusedEntry(None, "entry", "r"),
            SkillListing((), ()),
            SkillContent("o", "u", b""),
            LoadedSkill(item, SkillContent("o", "u", b"")),
            SkillDirectoryEntry("o", "u", "n", "text/plain", False),
        ):
            with pytest.raises(AttributeError):  # a frozen dataclass refuses any assignment
                frozen.anything = "x"  # type: ignore[attr-defined]
        assert hash(item) == hash(SkillItem("o", "skill://a/SKILL.md", "a", "d", {"name": "a", "description": "d"}, ()))
        assert SkillDirectoryEntry("o", "u", "n", "inode/directory", True).is_dir is True

    def test_the_names_are_exported_from_the_package_and_from_the_door(self) -> None:
        import ext_r2c.mcp
        import ext_r2c.mcp.skills as package

        names = {
            "SkillsClient", "SkillItem", "SkillFileRef", "SkillListing", "RefusedEntry", "SkillContent", "LoadedSkill",
            "SkillDirectoryEntry", "SkillRefused",
        }
        assert names <= set(package.__all__) and names <= set(ext_r2c.mcp.__all__)
        for name in names:
            assert getattr(ext_r2c.mcp, name) is getattr(package, name)

