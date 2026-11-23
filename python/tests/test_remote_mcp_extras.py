"""What the MCP door serves beside plain tools: skills, resources, prompts and the agent as one tool
(spec 007, story 5; FR-008, FR-016, FR-017; D8, D9; research R9).

Each of them is the MCP door's alone: the A2A card says nothing of them. The skills are read by the
verifying `SkillsClient` of spec 005, so what a test reads is checked against the disk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import mcp_types as types
import pytest
from ext_r2c import MCP_KEY, Remote, RemoteError
from ext_r2c.core import CardInfo, CardSkill, RunInput
from ext_r2c.mcp import SkillsClient, SkillsError, SkillsExtension, SourceTool
from ext_r2c.mcp.skills import extension as skills_extension
from ext_r2c.mcp.source_tool import DEFAULT_SCHEMA
from mcp.server.mcpserver.prompts import Prompt
from mcp.server.mcpserver.resources import TextResource

from a2a_harness import run
from fake_sources import CARD, CheckpointFake
from mcp_harness import accept, call, texts
from remote_harness import CARD_PATH, mcp_options, quiet, serve_remote
from skills_fixtures import standard_tree, write_skill

SKILLS_ID = "io.modelcontextprotocol/skills"
NOTE = "resource://handbook/note"
ARGS = {"message": "Write the report", "context_id": "ctx-1"}


def publish_page(slug: str) -> str:
    """Publish a page of the handbook."""
    return f"published {slug}"


def say_hello(name: str) -> str:
    """A greeting for one person."""
    return f"Say hello to {name}."


def _note() -> TextResource:
    return TextResource(uri=NOTE, name="note", description="A note of the handbook.", text="Pages are published on Monday.")


def _mcp_only(**arguments: Any) -> Remote:
    """An MCP-only `Remote` with nothing but what a test gives it."""
    return Remote(expose=["mcp"], card=CARD, mcp=mcp_options(), **arguments)


async def _read_every_skill(client: Any) -> dict[str, bytes]:
    """Every file of every skill the server lists, read through the client that verifies each one."""
    skills = SkillsClient(client, origin="docs")
    assert skills.declared, "the skills extension is declared"
    listing = await skills.list()
    assert not listing.refused
    found: dict[str, bytes] = {}
    for item in listing.skills:
        loaded = await skills.load(item)
        assert loaded.instructions.uri == item.uri
        for ref in item.files:
            found[ref.uri] = (await skills.read(item, ref.uri)).data
    return found


async def _card_json(served: Any) -> Any:
    async with served.http() as http:
        response = await http.get(CARD_PATH)
        assert response.status_code == 200
        return response.json()


# --- 1. Skills (FR-016, D8) ---------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["a path", "a str", "a list of one"])
def test_a_skills_folder_is_served_whole(tmp_path: Path, how: str) -> None:
    tree = standard_tree(tmp_path)
    given: Any = {"a path": tree.root, "a str": str(tree.root), "a list of one": [tree.root]}[how]

    async def go() -> None:
        async with serve_remote(_mcp_only(skills=given)) as served, served.mcp() as client:
            assert await _read_every_skill(client) == tree.expected()

    run(go())


def test_a_list_of_folders_serves_the_skills_of_each(tmp_path: Path) -> None:
    tree = standard_tree(tmp_path)
    other = tmp_path / "more"
    write_skill(other, "hello", description="Says hello.", files={"notes.txt": "Wave.\n"})

    async def go() -> None:
        async with serve_remote(_mcp_only(skills=[tree.root, str(other)])) as served, served.mcp() as client:
            found = await _read_every_skill(client)
            assert set(found) == set(tree.expected()) | {"skill://hello/SKILL.md", "skill://hello/notes.txt"}
            assert found["skill://hello/notes.txt"] == b"Wave.\n"

    run(go())


def test_a_ready_skills_extension_is_served_as_it_is_with_its_own_settings(tmp_path: Path) -> None:
    tree = standard_tree(tmp_path)
    ready = SkillsExtension(tree.root, exclude=["greetings"])
    kept = {uri: data for uri, data in tree.expected().items() if not uri.startswith("skill://greetings/")}
    assert len(kept) < len(tree.expected())

    async def go() -> None:
        async with serve_remote(_mcp_only(skills=ready)) as served, served.mcp() as client:
            assert await _read_every_skill(client) == kept, "`exclude` is the extension's argument, and it held"

    run(go())


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Every scan of skills folders, by the folders scanned."""
    seen: list[tuple[str, ...]] = []
    real = skills_extension.scan_roots

    def counted(folders: Any, *rest: Any) -> Any:
        seen.append(tuple(folders))
        return real(folders, *rest)

    monkeypatch.setattr(skills_extension, "scan_roots", counted)
    return seen


def test_the_folders_are_read_once_and_only_when_the_app_is_built(tmp_path: Path, scans: list[tuple[str, ...]]) -> None:
    tree = standard_tree(tmp_path)
    remote = _mcp_only(skills=tree.root)
    assert scans == [], "`Remote(...)` reads no file"
    remote.app()
    assert scans == [(str(tree.root),)], "one extension, built once"


def test_a_ready_extension_is_not_built_again(tmp_path: Path, scans: list[tuple[str, ...]]) -> None:
    ready = SkillsExtension(standard_tree(tmp_path).root)
    assert len(scans) == 1
    _mcp_only(skills=ready).app()
    assert len(scans) == 1, "the one given is the one served"


def test_a_bad_folder_fails_app_with_the_skills_own_error_and_uses_the_remote_up(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-folder"
    with pytest.raises(SkillsError) as direct:
        SkillsExtension(missing)
    remote = _mcp_only(skills=missing, tools=[publish_page])  # `Remote(...)` reads no file, so it is not refused yet
    with pytest.raises(SkillsError) as through:
        remote.app()
    assert type(through.value) is type(direct.value) and str(through.value) == str(direct.value), "unchanged"
    with pytest.raises(RuntimeError, match="build a new `Remote`"):
        remote.app()


def test_skills_resources_and_prompts_leave_the_a2a_card_as_it_is(tmp_path: Path) -> None:
    tree = standard_tree(tmp_path)

    async def card(**extras: Any) -> Any:
        remote = quiet(agent=CheckpointFake({}), tools=[publish_page], **extras)
        async with serve_remote(remote) as served:
            return await _card_json(served)

    async def go() -> None:
        plain = await card()
        assert await card(skills=tree.root) == plain
        assert await card(resources=[_note()], prompts=[Prompt.from_function(say_hello)]) == plain
        assert [skill["id"] for skill in plain["skills"]] == ["report"], "the card's skills are the card's own"

    run(go())


def test_a_card_skill_and_an_mcp_skill_of_one_name_are_two_things(tmp_path: Path) -> None:
    """The word is shared, the things are not: a card skill says what the agent can do, an MCP skill
    is a folder of instructions a client loads (D8)."""
    tree = standard_tree(tmp_path)
    info = CardInfo(name="Pages", description="Publishes pages.", version="1",
                    skills=(CardSkill(id="greetings", name="greetings", description="Greets a caller."),))

    async def go() -> None:
        remote = quiet(agent=CheckpointFake({}), card=info, skills=tree.root)
        async with serve_remote(remote, info=info) as served:
            assert [skill["id"] for skill in (await _card_json(served))["skills"]] == ["greetings"]
            async with served.mcp() as client:
                listed = await SkillsClient(client, origin="docs").list()
                assert "skill://greetings/SKILL.md" in {item.uri for item in listed.skills}

    run(go())


# --- 2. The agent as one MCP tool (FR-008, D6) --------------------------------------------------------


def test_with_mcp_tool_the_agent_is_one_more_tool_that_pauses_and_goes_on() -> None:
    async def go() -> None:
        remote = quiet(agent=CheckpointFake({}), tools=[publish_page], mcp_tool=True)
        async with serve_remote(remote) as served, served.mcp() as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert sorted(tools) == ["agent", "publish_page"]
            assert tools["agent"].input_schema == DEFAULT_SCHEMA, "`{message, context_id?}`"
            first = await call(client, "agent", ARGS)
            assert isinstance(first, types.InputRequiredResult)
            done = await call(client, "agent", ARGS, state=first.request_state, responses=accept("q-1", title="October"))
            assert not done.is_error and texts(done) == ["Got: October"]

    run(go())


def test_without_mcp_tool_the_agent_is_not_an_mcp_tool() -> None:
    async def go() -> None:
        remote = quiet(agent=CheckpointFake({}), tools=[publish_page])
        async with serve_remote(remote) as served, served.mcp() as client:
            assert [t.name for t in (await client.list_tools()).tools] == ["publish_page"]

    run(go())


def test_a_source_tool_the_owner_built_is_served_beside_the_agents_own() -> None:
    schema = {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}

    def to_input(arguments: Any) -> Any:
        return RunInput(text=f"Write about {arguments['topic']}"), None

    writer = SourceTool(CheckpointFake({}), name="writer", description="Writes about a topic.", input_schema=schema,
                        to_input=to_input)

    async def go() -> None:
        remote = quiet(agent=CheckpointFake({}), tools=[writer], mcp_tool=True)
        async with serve_remote(remote) as served, served.mcp() as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert sorted(tools) == ["agent", "writer"]
            assert tools["writer"].input_schema == schema and tools["writer"].description == "Writes about a topic."
            assert isinstance(await call(client, "writer", {"topic": "stock"}), types.InputRequiredResult)
            assert isinstance(await call(client, "agent", ARGS), types.InputRequiredResult)

    run(go())


def test_a_tool_that_takes_the_agent_tools_name_is_a_build_problem() -> None:
    other = SourceTool(CheckpointFake({}))  # its default name is the agent tool's
    with pytest.raises(RemoteError) as caught:
        quiet(agent=CheckpointFake({}), tools=[other], mcp_tool=True)
    (problem,) = caught.value.problems
    assert problem.startswith("tools: ") and "agent" in problem
    quiet(agent=CheckpointFake({}), tools=[other]).app()  # without `mcp_tool` it is the only one of that name


# --- 3. Resources and prompts, served as given (FR-017, D9) -------------------------------------------


def test_a_resource_and_a_prompt_are_listed_read_and_fetched() -> None:
    async def go() -> None:
        remote = _mcp_only(tools=[publish_page], resources=[_note()], prompts=[Prompt.from_function(say_hello)])
        async with serve_remote(remote) as served, served.mcp() as client:
            (resource,) = (await client.list_resources()).resources
            assert (str(resource.uri), resource.name, resource.description) == (NOTE, "note", "A note of the handbook.")
            (content,) = (await client.read_resource(NOTE)).contents
            assert content.text == "Pages are published on Monday."

            (prompt,) = (await client.list_prompts()).prompts
            assert (prompt.name, prompt.description) == ("say_hello", "A greeting for one person.")
            assert [argument.name for argument in prompt.arguments or []] == ["name"]
            (message,) = (await client.get_prompt("say_hello", {"name": "Ada"})).messages
            assert message.content.text == "Say hello to Ada."

            assert [t.name for t in (await client.list_tools()).tools] == ["publish_page"], "beside the tools"

    run(go())


def test_several_resources_and_prompts_are_all_served() -> None:
    def say_goodbye(name: str) -> str:
        """A farewell for one person."""
        return f"Say goodbye to {name}."

    second = TextResource(uri="resource://handbook/rules", name="rules", text="Be brief.")

    async def go() -> None:
        remote = _mcp_only(resources=[_note(), second], prompts=[Prompt.from_function(say_hello),
                                                                 Prompt.from_function(say_goodbye)])
        async with serve_remote(remote) as served, served.mcp() as client:
            assert sorted(str(r.uri) for r in (await client.list_resources()).resources) == [NOTE, "resource://handbook/rules"]
            assert sorted(p.name for p in (await client.list_prompts()).prompts) == ["say_goodbye", "say_hello"]

    run(go())


# --- 4. An MCP door with no tool at all (R9) ----------------------------------------------------------


@pytest.mark.parametrize("what", ["skills", "a resource", "a prompt"])
def test_an_mcp_door_serves_with_no_tool_and_still_declares_r2c(tmp_path: Path, what: str) -> None:
    tree = standard_tree(tmp_path)
    given: dict[str, Any] = {"skills": {"skills": tree.root}, "a resource": {"resources": [_note()]},
                             "a prompt": {"prompts": [Prompt.from_function(say_hello)]}}[what]

    async def go() -> None:
        async with serve_remote(_mcp_only(**given)) as served, served.mcp() as client:
            assert (await client.list_tools()).tools == []
            declared = dict(client.server_capabilities.extensions or {})
            assert MCP_KEY in declared, "the R2C activation is uniform, tools or not"
            assert (SKILLS_ID in declared) == (what == "skills")
            if what == "skills":
                assert await _read_every_skill(client) == tree.expected()
            if what == "a resource":
                assert [str(r.uri) for r in (await client.list_resources()).resources] == [NOTE]
            if what == "a prompt":
                assert [p.name for p in (await client.list_prompts()).prompts] == ["say_hello"]

    run(go())
