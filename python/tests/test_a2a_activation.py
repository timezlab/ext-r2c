"""The card, the echoed header, and a caller that did not activate R2C (spec 003, story 3)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from a2a.types.a2a_pb2 import AgentCard, StreamResponse
from ext_r2c import URI
from ext_r2c.a2a import SourceExecutor, agent_card
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Answer,
    Ask,
    CardInfo,
    CardSkill,
    Question,
    ReplyChunk,
    RunContext,
    RunEvent,
    RunInput,
)
from google.protobuf import json_format

from a2a_harness import a2a_client, ids, kinds, run, send, serve
from fake_sources import CARD, CheckpointFake, LiveFake
from r2c_check import example_files, load_json


def _card() -> AgentCard:
    return agent_card(CARD, "https://remote.example.com/")


# --- The card -----------------------------------------------------------------------------------


def test_card_matches_the_example() -> None:
    path = next(p for p in example_files("a2a") if p.name == "agent-card.json")
    body = load_json(path)["steps"][0]["body"]
    skill = body["skills"][0]
    info = CardInfo(
        name=body["name"], description=body["description"], version=body["version"],
        skills=(CardSkill(id=skill["id"], name=skill["name"], description=skill["description"],
                          tags=tuple(skill["tags"])),),
    )
    card = agent_card(info, body["supportedInterfaces"][0]["url"], output_modes=tuple(body["defaultOutputModes"]))
    # `required: false` is the protobuf default, so the parsed file and the built card agree.
    assert card == json_format.ParseDict(body, AgentCard())


def test_card_declares_r2c_never_required() -> None:
    card = _card()
    (ext,) = card.capabilities.extensions
    assert ext.uri == URI and not ext.required
    assert card.capabilities.streaming


# --- Not active -----------------------------------------------------------------------------------


def _r2c_anywhere(events: list[StreamResponse]) -> list[str]:
    """Every place in the events that carries R2C metadata."""
    found = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == URI:
                    found.append(path)
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}/{i}")

    for n, e in enumerate(events):
        walk(json_format.MessageToDict(e), f"/{n}")
    return found


def _texts(event: StreamResponse) -> list[str]:
    parts = event.status_update.status.message.parts
    assert all(p.HasField("text") for p in parts), "a non-active status carries text only"
    return [p.text for p in parts]


@pytest.mark.parametrize("style", ["checkpoint", "live"])
def test_not_active(style: str) -> None:
    async def go() -> None:
        source = CheckpointFake({}) if style == "checkpoint" else LiveFake()
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served, r2c=False) as tc:
            first = await send(tc, "Write the report")
            assert kinds(first) == ["task", "working", "input_required"]
            (asked,) = _texts(first[2])
            assert "title" in asked
            second = await send(tc, "October", **ids(first))
            assert kinds(second) == ["working", "completed"]
            assert _texts(second[-1]) == ["Got: October"]
            assert _r2c_anywhere(first + second) == []  # SC-004
            assert tc.echoed() == [None, None]
            assert [a.value for a in source.answers] == [{"title": "October"}]

    run(go())


# --- Reasoning ----------------------------------------------------------------------------------


class Reasoner:
    pause = "live"
    card = CARD

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield ActivityEvent(Activity(id="r-1", type="reasoning", label="Thinking", delta="Reading..."))
        yield ReplyChunk("ok", last=True)

    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        raise NotImplementedError


@pytest.mark.parametrize("r2c", [True, False])
def test_reasoning_only_when_active(r2c: bool) -> None:
    async def go() -> list[str]:
        async with serve(SourceExecutor(Reasoner()), _card()) as served, a2a_client(served, r2c=r2c) as tc:
            return kinds(await send(tc, "Go"))

    expected = ["task", "working", "artifact:reply", "completed"] if r2c else ["task", "completed"]
    assert run(go()) == expected


# --- A text answer without activation (R2C-ASK-8) ---------------------------------------------------

WAREHOUSE = Question.parse({
    "kind": "question", "id": "q-1", "title": "Which warehouse?", "answer_by": {"role": "person"},
    "fields": [{"key": "warehouse", "header": "Warehouse", "text": "Which warehouse should the report cover?",
                "type": "one", "other": False, "options": [{"label": "North"}, {"label": "South"}]}],
})


class Warehouse:
    pause = "checkpoint"
    card = CARD

    def __init__(self) -> None:
        self.answers: list[Answer] = []

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        yield Ask(WAREHOUSE)

    async def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        self.answers.append(answer)
        yield ReplyChunk(f"Reading the {(answer.value or {})['warehouse']} inventory", last=True)


def test_text_answer_without_activation() -> None:
    async def go() -> None:
        source = Warehouse()
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served, r2c=False) as tc:
            first = await send(tc, "Build the inventory report for October.")
            assert kinds(first) == ["task", "input_required"]
            again = await send(tc, "Somewhere", **ids(first))
            assert kinds(again) == ["input_required"]  # asked again in text
            assert source.answers == []
            done = await send(tc, "south", **ids(first))
            assert kinds(done) == ["completed"]
            assert _texts(done[-1]) == ["Reading the South inventory"]
            (got,) = source.answers
            assert got.value == {"warehouse": "South"} and got.answered_by.role == "person"

    run(go())


def test_an_approval_is_never_taken_from_text() -> None:
    async def go() -> None:
        source = LiveFake()
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served, r2c=False) as tc:
            first = await send(tc, "Write and publish the report")
            again = await send(tc, "allow", **ids(first))
            assert kinds(again) == ["input_required"]
            assert source.answers == []

    run(go())
