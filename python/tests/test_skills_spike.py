"""The MCP SDK facts the skills extension leans on (spec 005, research R1 to R4). Each test pins
one; a failing one means the SDK changed under the design, and research and plan are revisited
first. A throwaway `Extension` stands in for the real one, which does not exist yet."""

from __future__ import annotations

import base64
from typing import Any, Literal

import mcp_types as types
import pytest
from mcp.client import Client
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import Resource
from mcp.shared.exceptions import MCPError
from mcp_harness import mcp_client, run, serve

SKILLS_ID = "io.modelcontextprotocol/skills"
SKILL_URI = "skill://team/x/SKILL.md"
NOTES_URI = "skill://team/x/notes.md"
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# --- Typed wire models: a request is a typed class, a result a `Cacheable`/`Paginated` one --------


class GetParams(types.RequestParams):
    uri: str


class ListRequest(types.PaginatedRequest[Literal["skills/list"]]):
    method: Literal["skills/list"] = "skills/list"


class GetRequest(types.Request[GetParams, Literal["skills/get"]]):
    method: Literal["skills/get"] = "skills/get"
    params: GetParams


class DirectoryRequest(types.Request[GetParams, Literal["resources/directory/read"]]):
    method: Literal["resources/directory/read"] = "resources/directory/read"
    params: GetParams


class ListResult(types.PaginatedResult, types.CacheableResult):
    skills: list[dict[str, Any]]
    result_type: types.ResultType = "complete"


class GetResult(types.CacheableResult):
    skill: dict[str, Any]
    result_type: types.ResultType = "complete"


class DirectoryResult(types.PaginatedResult, types.CacheableResult):
    resources: list[dict[str, Any]]
    result_type: types.ResultType = "complete"


# --- A throwaway extension ------------------------------------------------------------------------


class File(Resource):
    """A served file: `content` is what `read()` returns; each read is noted in `log`."""

    content: str | bytes = ""
    log: Any = None

    async def read(self) -> str | bytes:
        if self.log is not None:
            self.log.append(str(self.uri))
        return self.content


class Broken(Resource):
    """A file whose `read()` raises `error`."""

    error: Any = None

    async def read(self) -> str | bytes:
        raise self.error


class Probe(Extension):
    """What `SkillsExtension` will be built from: settings, resources, the three methods. It
    notes what each handler received."""

    identifier = SKILLS_ID

    def __init__(self, resources: list[Resource] | None = None, *, directory_read: bool = False) -> None:
        self.made = list(resources or [])
        self.directory_read = directory_read
        self.resources_calls = 0
        self.params: list[Any] = []
        self.capabilities: list[Any] = []

    def settings(self) -> dict[str, Any]:
        return {"directoryRead": self.directory_read}

    def resources(self) -> list[ResourceBinding]:
        self.resources_calls += 1
        return [ResourceBinding(r) for r in self.made]

    def methods(self) -> list[MethodBinding]:
        async def list_skills(ctx: Any, params: types.PaginatedRequestParams | None) -> ListResult:
            self.params.append(params)
            self.capabilities.append(ctx.session.client_capabilities)
            return ListResult(skills=[{"uri": SKILL_URI}], next_cursor="2", ttl_ms=5000, cache_scope="public")

        async def get_skill(ctx: Any, params: GetParams) -> GetResult:
            self.params.append(params)
            self.capabilities.append(ctx.session.client_capabilities)
            if params.uri != SKILL_URI:
                raise MCPError(code=INVALID_PARAMS, message=f"No skill is served at {params.uri}")
            return GetResult(skill={"uri": params.uri}, ttl_ms=7, cache_scope="private")

        async def read_directory(ctx: Any, params: GetParams) -> DirectoryResult:
            self.params.append(params)
            return DirectoryResult(resources=[{"uri": NOTES_URI}], ttl_ms=0, cache_scope="private")

        return [
            MethodBinding("skills/list", types.PaginatedRequestParams, list_skills),
            MethodBinding("skills/get", GetParams, get_skill),
            MethodBinding("resources/directory/read", GetParams, read_directory),
        ]


def _file(uri: str, content: str | bytes = "", mime: str = "text/markdown", log: Any = None) -> File:
    return File(uri=uri, name=uri.rsplit("/", 1)[-1], mime_type=mime, content=content, log=log)


def _server(extension: Extension) -> MCPServer:
    return MCPServer("spike", extensions=[extension])


# --- The facts ------------------------------------------------------------------------------------


class TestExtensionSurface:
    def test_extension_binds_new_methods_and_declares_settings(self) -> None:
        """R1: three methods that are no spec method are accepted; `settings()` is what
        `server/discover` declares for the extension; one resource declares `resources`."""
        probe = Probe([_file(SKILL_URI)], directory_read=True)
        server = _server(probe)  # MethodBinding for all three is accepted, nothing raises
        assert server._lowlevel_server.extensions == {SKILLS_ID: {"directoryRead": True}}

        async def go() -> None:
            async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
                assert client.server_capabilities.extensions == {SKILLS_ID: {"directoryRead": True}}
                assert client.server_capabilities.resources is not None
                session = client.session
                listed = await session.send_request(ListRequest(), ListResult)
                assert [s["uri"] for s in listed.skills] == [SKILL_URI]
                got = await session.send_request(GetRequest(params=GetParams(uri=SKILL_URI)), GetResult)
                assert got.skill == {"uri": SKILL_URI}
                directory = await session.send_request(DirectoryRequest(params=GetParams(uri=SKILL_URI)), DirectoryResult)
                assert [r["uri"] for r in directory.resources] == [NOTES_URI]

        run(go())

    def test_resources_capability_is_always_declared(self) -> None:
        """R1: `MCPServer` declares `resources` with or without a registered resource, so the
        capability the extension requires does not depend on what the extension registers."""

        async def go() -> Any:
            async with serve(_server(Probe([]))) as served, mcp_client(served, active=False, form=False) as client:
                return client.server_capabilities.resources

        declared = run(go())
        assert declared is not None
        assert declared.subscribe is True and declared.list_changed is True

    def test_resources_are_read_once_and_cannot_be_removed(self) -> None:
        """R1, R5: `resources()` is read when the server is built; a resource added later with
        `add_resource` is listed; nothing removes one, so a refresh swaps what a resource reads,
        never the registrations."""
        probe = Probe([_file(SKILL_URI)])
        server = _server(probe)
        assert probe.resources_calls == 1
        probe.made.append(_file(NOTES_URI))  # the extension changes its mind: too late
        assert probe.resources_calls == 1

        async def uris() -> list[str]:
            async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
                return sorted(str(r.uri) for r in (await client.list_resources()).resources)

        assert run(uris()) == [SKILL_URI]
        assert probe.resources_calls == 1

        server.add_resource(_file(NOTES_URI))
        assert run(uris()) == sorted([SKILL_URI, NOTES_URI])

        removers = [n for n in dir(server) if "resource" in n and n.startswith(("remove", "delete", "unregister"))]
        assert removers == []
        manager = server._resource_manager
        assert [n for n in dir(manager) if n.startswith(("remove", "delete", "unregister"))] == []


class TestTypedWire:
    def test_typed_result_carries_cache_fields(self) -> None:
        """R2: a `CacheableResult` and a `PaginatedResult` go out as `ttlMs`, `cacheScope`,
        `resultType` and `nextCursor`, and the same classes parse them on the client."""
        record: list[tuple[str, dict[str, Any]]] = []

        async def go() -> tuple[ListResult, GetResult]:
            async with serve(_server(Probe([_file(SKILL_URI)])), record=record) as served:
                async with mcp_client(served, active=False, form=False) as client:
                    listed = await client.session.send_request(ListRequest(), ListResult)
                    got = await client.session.send_request(GetRequest(params=GetParams(uri=SKILL_URI)), GetResult)
                    return listed, got

        listed, got = run(go())
        results = [m["result"] for side, m in record if side == "remote" and "skills" in m.get("result", {})]
        assert len(results) == 1
        wire = results[0]
        assert wire["ttlMs"] == 5000 and wire["cacheScope"] == "public"
        assert wire["resultType"] == "complete" and wire["nextCursor"] == "2"
        assert wire["skills"] == [{"uri": SKILL_URI}]
        assert (listed.ttl_ms, listed.cache_scope, listed.next_cursor) == (5000, "public", "2")
        assert (got.ttl_ms, got.cache_scope, got.result_type, got.skill) == (7, "private", "complete", {"uri": SKILL_URI})

    def test_untyped_request_drops_its_params(self) -> None:
        """R2: `Request(method=..., params={...})` turns the dict into the base params and loses
        `uri`; a typed request class keeps it. (So the client must define typed classes.)"""
        probe = Probe([_file(SKILL_URI)])
        record: list[tuple[str, dict[str, Any]]] = []

        async def go() -> None:
            async with serve(_server(probe), record=record) as served:
                async with mcp_client(served, active=False, form=False) as client:
                    untyped = types.Request(method="skills/get", params={"uri": SKILL_URI})
                    with pytest.raises(MCPError) as refused:
                        await client.session.send_request(untyped, GetResult)
                    assert refused.value.error.code == INVALID_PARAMS
                    got = await client.session.send_request(GetRequest(params=GetParams(uri=SKILL_URI)), GetResult)
                    assert got.skill == {"uri": SKILL_URI}

        run(go())
        sent = [m["params"] for side, m in record if side == "client" and m.get("method") == "skills/get"]
        assert len(sent) == 2
        assert "uri" not in sent[0], sent[0]
        assert sent[1]["uri"] == SKILL_URI, sent[1]
        assert [p.uri for p in probe.params] == [SKILL_URI]  # the handler never saw the untyped one

    def test_client_declares_nothing_for_the_extension(self) -> None:
        """R2: the client advertises no capability for the extension (the harness client with
        `active=False` advertises none at all), and the server answers the methods all the same."""
        probe = Probe([_file(SKILL_URI)])

        async def go() -> None:
            async with serve(_server(probe)) as served, mcp_client(served, active=False, form=False) as client:
                await client.session.send_request(ListRequest(), ListResult)
                await client.session.send_request(GetRequest(params=GetParams(uri=SKILL_URI)), GetResult)

        run(go())
        assert len(probe.capabilities) == 2
        for caps in probe.capabilities:
            declared = caps.extensions if caps else None
            assert not declared or SKILLS_ID not in declared, declared

    def test_in_memory_client_carries_typed_skills_requests(self) -> None:
        """R13: the SDK's own `Client(server)` (no HTTP) can send a typed `skills/list` and
        `skills/get` request and parse a typed result. It decides how `mcp_only.py` runs its
        round trip (T059)."""
        probe = Probe([_file(SKILL_URI)])

        async def go() -> None:
            async with Client(_server(probe), cache=None) as client:
                assert client.server_capabilities.extensions == {SKILLS_ID: {"directoryRead": False}}
                listed = await client.session.send_request(ListRequest(), ListResult)
                assert [s["uri"] for s in listed.skills] == [SKILL_URI]
                got = await client.session.send_request(GetRequest(params=GetParams(uri=SKILL_URI)), GetResult)
                assert got.skill == {"uri": SKILL_URI}
                read = await client.read_resource(SKILL_URI)
                assert [str(c.uri) for c in read.contents] == [SKILL_URI]

        run(go())


class TestResourceReads:
    def test_resource_read_compares_raw_strings(self) -> None:
        """R3: a read is a dictionary lookup of the request string as sent. `..` (plain, `%2e%2e`,
        `.%2e`), a backslash, a query, a fragment, a trailing slash, a case change and an
        unregistered path are `-32602` and never reach `Resource.read`; a registered URI is listed
        exactly as given, case, space and non-ASCII characters kept."""
        log: list[str] = []
        mixed = "skill://Mixed_Case/a%20b/%C3%A9.txt"
        server = _server(Probe([_file(SKILL_URI, "# x\n", log=log), _file(mixed, "m", "text/plain", log=log)]))
        unknown = [
            "skill://team/x/../x/SKILL.md",
            "skill://team/x/%2e%2e/x/SKILL.md",
            "skill://team/x/.%2e/x/SKILL.md",
            "skill://team/x/SKILL.md/..",
            "skill://team\\x/SKILL.md",
            "skill://team/x\\SKILL.md",
            "skill://team/x/SKILL.md?v=1",
            "skill://team/x/SKILL.md#top",
            "skill://team/x/SKILL.md/",
            "skill://TEAM/x/SKILL.md",
            "skill://team/x/skill.md",
            "skill://team/x/other.md",
            "skill://mixed_case/a%20b/%C3%A9.txt",
            "skill://Mixed_Case/a b/é.txt",
            "file:///etc/hostname",
        ]

        async def go() -> list[str]:
            async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
                listed = sorted(str(r.uri) for r in (await client.list_resources()).resources)
                for uri in unknown:
                    with pytest.raises(MCPError) as refused:
                        await client.read_resource(uri)
                    assert refused.value.error.code == INVALID_PARAMS, uri
                assert log == [], log
                assert (await client.read_resource(SKILL_URI)).contents[0].text == "# x\n"  # type: ignore[union-attr]
                assert (await client.read_resource(mixed)).contents[0].text == "m"  # type: ignore[union-attr]
                return listed

        assert run(go()) == sorted([SKILL_URI, mixed])
        assert log == [SKILL_URI, mixed]

    def test_mcperror_in_read_keeps_its_code(self) -> None:
        """R4: an `MCPError` raised in `read()` arrives with its code and message; any other
        exception arrives as a generic error that does not carry the original text."""
        stale = MCPError(code=INTERNAL_ERROR, message="The skills changed on disk; refresh them.")
        other = RuntimeError("boom at the private location /srv/private/data")
        files = [
            Broken(uri="skill://team/x/stale.md", name="stale.md", error=stale),
            Broken(uri="skill://team/x/other.md", name="other.md", error=other),
        ]

        async def go() -> tuple[MCPError, MCPError]:
            async with serve(_server(Probe(files))) as served, mcp_client(served, active=False, form=False) as client:
                with pytest.raises(MCPError) as first:
                    await client.read_resource("skill://team/x/stale.md")
                with pytest.raises(MCPError) as second:
                    await client.read_resource("skill://team/x/other.md")
                return first.value, second.value

        first, second = run(go())
        assert first.error.code == INTERNAL_ERROR
        assert first.error.message == "The skills changed on disk; refresh them."
        assert second.error.code == INTERNAL_ERROR
        assert "boom" not in second.error.message and "/srv/" not in second.error.message
        assert "/srv/" not in str(second.error.data)

    def test_text_and_blob_follow_the_return_type(self) -> None:
        """R4: `read()` returning `str` goes out as `text`, `bytes` as a base64 `blob`, each with
        the MIME the resource declares."""
        binary = b"\x00\xff\xfe\x01"
        server = _server(Probe([
            _file(SKILL_URI, "# Title\n", "text/markdown"),
            _file("skill://team/x/logo.bin", binary, "application/octet-stream"),
        ]))

        async def go() -> tuple[Any, Any]:
            async with serve(server) as served, mcp_client(served, active=False, form=False) as client:
                text = (await client.read_resource(SKILL_URI)).contents[0]
                blob = (await client.read_resource("skill://team/x/logo.bin")).contents[0]
                return text, blob

        text, blob = run(go())
        assert (text.text, text.mime_type) == ("# Title\n", "text/markdown")
        assert not hasattr(text, "blob")
        assert (blob.mime_type, base64.b64decode(blob.blob)) == ("application/octet-stream", binary)
        assert not hasattr(blob, "text")
