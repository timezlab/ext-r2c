"""Every A2A example played as a real in-process round trip (spec 003 story 7, contracts/replay.md).

- `client:<file>`: a wire executor sends the file's remote steps; `R2CClient` must read every
  R2C object as one typed item and send the file's client messages.
- `door:<file>:<pause>`: the file becomes a scripted source; the door must write the file's
  remote steps, in both pause styles.
- Card mode for `agent-card.json`, and three special flows.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from a2a.types.a2a_pb2 import (
    AgentCard,
    GetTaskRequest,
    Message,
    Part,
    SendMessageRequest,
    StreamResponse,
    SubscribeToTaskRequest,
)
from ext_r2c import URI
from ext_r2c.a2a import (
    ActivityItem,
    AnswerRejected,
    ArtifactItem,
    R2CClient,
    ReplyItem,
    RequestItem,
    SourceExecutor,
    TaskItem,
    UsageItem,
    agent_card,
)
from ext_r2c.a2a._codec import answer_text, r2c_part, read_part
from ext_r2c.core import (
    Answer,
    Approval,
    ArtifactMeta,
    Ask,
    CardInfo,
    CardSkill,
    Question,
    ReplyChunk,
    RunContext,
    RunEvent,
    RunInput,
    parse,
    to_json,
)
from google.protobuf import json_format

import a2a_replay_kit as kit
from a2a_harness import TIMEOUT, Caller, Served, a2a_client, kinds, message, run, serve, stream
from a2a_transport import StreamingASGITransport
from fake_sources import CARD

DOOR_EXEMPT = {
    "agent-card.json": "not a flow: compared as a card",
    "unknown-kind-ignored.json": "a source cannot emit an unknown kind",
    "artifact-no-metadata.json": "a data Part and no R2C metadata: no run event makes it",
}
SPECIAL = {"question-forwarded.json", "resubscribe.json", "follow-up-context.json"}
PAUSES = ["checkpoint", "live"]
FLOWS = [n for n in kit.names() if n != "agent-card.json"]
URL = "https://remote.example.com/"


def _card(url: str = URL) -> AgentCard:
    return agent_card(CARD, url)


# --- Door mode --------------------------------------------------------------------------------


def _request_in(events: list[StreamResponse]) -> Question | Approval | None:
    found = None
    for event in events:
        if event.HasField("status_update"):
            for part in event.status_update.status.message.parts:
                obj = read_part(part)
                if isinstance(obj, (Question, Approval)):
                    found = obj
    return found


def _task_of(events: list[StreamResponse]) -> dict[str, str]:
    for event in events:
        if event.HasField("task"):
            return {"task_id": event.task.id, "context_id": event.task.context_id}
        for name in ("status_update", "artifact_update"):
            if event.HasField(name):
                inner = getattr(event, name)
                return {"task_id": inner.task_id, "context_id": inner.context_id}
    return {}


async def _door_act(tc: Caller, example: kit.Example, turn: kit.Turn, wire_ids: dict[str, str],
                    now: dict[str, str], request: Question | Approval | None) -> list[StreamResponse]:
    if turn.action == kit.START:
        return await stream(tc, message(Part(text="Start."), context_id=kit.first_context(example)))
    if turn.action == kit.SAMPLE:
        assert request is not None, "a request to answer"
        reply = kit.sample_answer(request)
        return await stream(tc, message(Part(text=answer_text(reply, request)), r2c_part(reply), **now))
    step = turn.action
    assert isinstance(step, kit.Step) and step.type == "SendMessageRequest", step
    sent = json_format.ParseDict(step.body["message"], Message())
    sent.message_id = f"m-{uuid4().hex[:8]}"
    sent.task_id = wire_ids.get(sent.task_id, sent.task_id)
    sent.context_id = wire_ids.get(sent.context_id, sent.context_id)
    return await stream(tc, SendMessageRequest(message=sent))


def _learn(turn: kit.Turn, events: list[StreamResponse], wire_ids: dict[str, str]) -> None:
    """File task and context ids → the wire's, from a turn and the stream it gave."""
    got = _task_of(events)
    for step in turn.expect:
        task, ctx = kit._ids(step.body)
        if task and got:
            wire_ids.setdefault(task, got["task_id"])
        if ctx and got:
            wire_ids.setdefault(ctx, got["context_id"])


def _compare(turn: kit.Turn, events: list[StreamResponse], names: tuple[kit.Names, kit.Names], *,
             last: bool, where: str) -> None:
    got = list(events)
    shows_task = bool(turn.expect) and "task" in turn.expect[0].body
    if got and got[0].HasField("task") and not shows_task:
        got = got[1:]  # the leading Task the file does not show
    want = [kit.remote_form(s, names[0]) for s in turn.expect]
    have = [kit.wire_form(e, names[1]) for e in got[:len(want)]]
    if not last:
        extra = [json_format.MessageToDict(e) for e in got[len(want):]]
        assert not extra, f"{where}: events the file does not show: {extra}"
    assert have == want, f"{where}: the wire differs from the file\nwant {json.dumps(want, indent=1)}\nhave {json.dumps(have, indent=1)}"


async def _door(example: kit.Example, pause: str, *, prelude: bool = False) -> None:
    script = kit.script_from_example(example)
    source = kit.ScriptedSource(script, pause)
    stamp = kit.clock(example)
    plan = kit.turns(example)
    if prelude:
        plan.insert(0, kit.Turn(kit.START))  # a completed task first (`follow-up-context.json`)
    names = (kit.Names(), kit.Names())
    wire_ids: dict[str, str] = {}
    now: dict[str, str] = {}
    request: Question | Approval | None = None
    async with serve(SourceExecutor(source, clock=lambda: stamp), _card()) as served, \
            a2a_client(served, user="alice", r2c=example.activated) as tc:
        for n, turn in enumerate(plan):
            events = await _door_act(tc, example, turn, wire_ids, now, request)
            if prelude and n == 0:
                assert kinds(events)[-1] == "completed"
                continue
            _learn(turn, events, wire_ids)
            now = _task_of(events) or now
            request = _request_in(events) or request
            _compare(turn, events, names, last=n == len(plan) - 1, where=f"{example.name} turn {n}")
            if any(URI in s.headers.get("A2A-Extensions", "") for s in turn.expect):
                assert tc.echoed()[-1] == URI, f"{example.name} turn {n}: the URI was not echoed"


@pytest.mark.parametrize("pause", PAUSES)
@pytest.mark.parametrize("name", [n for n in FLOWS if n not in DOOR_EXEMPT and n not in SPECIAL])
def test_door(name: str, pause: str) -> None:
    run(_door(kit.load(name), pause))


def test_exemptions_are_exact() -> None:
    refused = set()
    for name in kit.names():
        try:
            kit.script_from_example(kit.load(name))
        except kit.NotScriptable:
            refused.add(name)
    assert refused == set(DOOR_EXEMPT)


# --- Client mode ------------------------------------------------------------------------------


class Counting(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self.inner.handle_async_request(request)


@contextlib.asynccontextmanager
async def _r2c(served: Served, example: kit.Example) -> AsyncIterator[tuple[R2CClient, Counting]]:
    transport = Counting(StreamingASGITransport(served.app))
    http = httpx.AsyncClient(transport=transport, headers={"Authorization": "Bearer alice"}, timeout=TIMEOUT)
    stamp = kit.clock(example)
    client = await R2CClient.connect(str(served.card.supported_interfaces[0].url), httpx_client=http,
                                     clock=lambda: stamp)
    try:
        yield client, transport
    finally:
        await client.aclose()
        await http.aclose()


_REPLY_META = ArtifactMeta(presentation="inline", response=True)


def _shown(items: list[Any]) -> list[str]:
    """The R2C objects a client's items carry, as sorted JSON."""
    out: list[Any] = []
    for item in items:
        if isinstance(item, ActivityItem):
            out.append(item.activity)
        elif isinstance(item, RequestItem):
            out.append(item.request)
        elif isinstance(item, UsageItem):
            out.append(item.usage)
        elif isinstance(item, ArtifactItem) and item.meta is not None:
            out.append(item.meta)
        elif isinstance(item, ReplyItem):
            out.append(_REPLY_META)
    return sorted(json.dumps(to_json(o), sort_keys=True) for o in out)


async def _raw(client: R2CClient, step: kit.Step) -> list[Any]:
    """Send the file's message as it is, the way a client that skips the check would, and read
    the reply with the client's own reader."""
    sent = json_format.ParseDict(step.body["message"], Message())
    sent.message_id = f"m-{uuid4().hex[:8]}"
    sent.task_id, sent.context_id = client.task_id or "", client.context_id or ""
    items: list[Any] = []
    async for event in client.client.send_message(SendMessageRequest(message=sent), context=client._context):
        items.extend(client._read(event))
    return items


async def _client_act(client: R2CClient, example: kit.Example, turn: kit.Turn) -> tuple[list[Any], bool]:
    """The items of a turn, and whether the file's message went out raw."""
    if turn.action == kit.START:
        return [i async for i in client.send("Start.", context_id=kit.first_context(example) or None)], False
    if turn.action == kit.SAMPLE:
        assert client.pending is not None
        return [i async for i in client.answer(kit.sample_answer(client.pending))], False
    step = turn.action
    assert isinstance(step, kit.Step) and step.type == "SendMessageRequest", step
    answer = kit.answer_of(step)
    if answer is not None:
        try:
            return [i async for i in client.answer(answer)], False
        except AnswerRejected:
            return await _raw(client, step), True  # the client refused it; the remote must too
    body = step.body["message"]
    items = [i async for i in client.send(
        kit.plain_text(step),
        context_id=client.context_id if body.get("contextId") else None,
        task_id=client.task_id if body.get("taskId") else None,
    )]
    return items, False


async def _client(example: kit.Example, *, prelude: bool = False) -> None:
    plan = kit.turns(example)
    if prelude:
        plan.insert(0, kit.Turn(kit.START))
    executor = kit.TurnExecutor([t.expect for t in plan])
    async with serve(executor, _card()) as served, _r2c(served, example) as (client, seen):
        for n, turn in enumerate(plan):
            where = f"{example.name} turn {n}"
            skipped, sent_at = client.skipped, len(seen.requests)
            items, raw = await _client_act(client, example, turn)
            found = [o for s in turn.expect for o in kit.objects(s)]
            shown = [o for o in found if kit.known(o)]
            assert _shown(items) == sorted(json.dumps(to_json(o), sort_keys=True) for o in shown), where
            assert client.skipped - skipped == len(found) - len(shown), where
            step = turn.action
            if isinstance(step, kit.Step) and not raw:
                request = seen.requests[sent_at]
                body = json.loads(request.content)["params"]["message"]
                assert kit.message_form(body) == kit.message_form(step.body["message"]), where
                for key in ("taskId", "contextId"):
                    assert bool(body.get(key)) == bool(step.body["message"].get(key)), f"{where}: {key}"
                if step.headers.get("A2A-Extensions"):
                    assert URI in request.headers.get("A2A-Extensions", ""), where


@pytest.mark.parametrize("name", [n for n in FLOWS if n not in SPECIAL])
def test_client(name: str) -> None:
    run(_client(kit.load(name)))


def test_client_guesses_artifacts_without_metadata() -> None:
    """R2C-ARTIFACT-7, `artifact-no-metadata.json`: what the client makes of each artifact."""
    example = kit.load("artifact-no-metadata.json")

    async def go() -> list[ArtifactItem]:
        executor = kit.TurnExecutor([t.expect for t in kit.turns(example)])
        async with serve(executor, _card()) as served, _r2c(served, example) as (client, _):
            return [i async for i in client.send("Start.") if isinstance(i, ArtifactItem)]

    found = run(go())
    assert [(i.meta, i.presentation) for i in found] == [(None, "file"), (None, "inline"), (None, "inline"), (None, "link")]
    assert found[2].data and isinstance(found[2].data[0], dict)


# --- Card mode --------------------------------------------------------------------------------


def test_card() -> None:
    body = kit.load("agent-card.json").steps[0].body
    skill = body["skills"][0]
    info = CardInfo(name=body["name"], description=body["description"], version=body["version"],
                    skills=(CardSkill(id=skill["id"], name=skill["name"], description=skill["description"],
                                      tags=tuple(skill["tags"])),))
    card = agent_card(info, body["supportedInterfaces"][0]["url"], output_modes=tuple(body["defaultOutputModes"]))
    assert card == json_format.ParseDict(body, AgentCard())


# --- Special flows ----------------------------------------------------------------------------


@pytest.mark.parametrize("pause", PAUSES)
def test_door_follow_up(pause: str) -> None:
    run(_door(kit.load("follow-up-context.json"), pause, prelude=True))


def test_client_follow_up() -> None:
    run(_client(kit.load("follow-up-context.json"), prelude=True))


@pytest.mark.parametrize("pause", PAUSES)
def test_door_resubscribe(pause: str) -> None:
    example = kit.load("resubscribe.json")
    working, stored = example.steps[1], example.steps[3]

    async def go() -> None:
        gate = asyncio.Event()
        source =kit.ScriptedSource(kit.script_from_example(example), pause, gate=gate)
        names = (kit.Names(), kit.Names())
        async with serve(SourceExecutor(source), _card()) as served, a2a_client(served, user="alice") as tc:
            first = tc.client.send_message(message(Part(text="Start."), context_id=kit.first_context(example)))
            opened = await first.__anext__()
            await first.aclose()  # the cut
            task_id = opened.task.id
            got: list[StreamResponse] = []
            async for event in tc.client.subscribe(SubscribeToTaskRequest(id=task_id)):
                got.append(event)
                if len(got) == 1:
                    gate.set()
                if kinds([event])[-1] in ("completed", "failed"):
                    break
            assert got[0].HasField("task")  # the snapshot
            assert kit.wire_form(got[1], names[1]) == kit.remote_form(working, names[0])
            task = await tc.client.get_task(GetTaskRequest(id=task_id))
            assert kit.wire_form(task, names[1]) == kit.remote_form(stored, names[0])

    run(go())


def test_client_resubscribe() -> None:
    example = kit.load("resubscribe.json")
    working, stored = example.steps[1], example.steps[3]

    async def go() -> None:
        gate = asyncio.Event()
        executor =kit.TurnExecutor([[working, stored]], gate=gate)
        async with serve(executor, _card()) as served, _r2c(served, example) as (client, _):
            async for item in client.send("Start.", context_id=kit.first_context(example)):
                assert isinstance(item, TaskItem)
                break  # the cut
            items: list[Any] = []
            async for item in client.reattach():
                items.append(item)
                if len(items) == 1:
                    gate.set()
            assert isinstance(items[0], TaskItem)
            want = sorted(json.dumps(to_json(o), sort_keys=True) for s in (working, stored) for o in kit.objects(s))
            assert _shown(items) == want
            back = await client.get_task()  # R2C-A2A-6
            assert _shown(back) == sorted(json.dumps(to_json(o), sort_keys=True) for o in kit.objects(stored))

    run(go())


class Forwarding:
    """The front remote: asks the inventory remote through `R2CClient`, forwards its question
    with `origin`, and passes the answer back (R2C-ASK-7)."""

    card = CARD

    def __init__(self, pause: str, client: R2CClient, origin: dict[str, str]) -> None:
        self.pause = pause
        self.client = client
        self.origin = origin
        self.asked: Question | None = None

    async def _forwarded(self) -> Question:
        items = [i async for i in self.client.send("Count the stock.")]
        (request,) = [i.request for i in items if isinstance(i, RequestItem)]
        assert isinstance(request, Question)
        self.asked = request
        forwarded = parse({**to_json(request), "origin": self.origin})
        assert isinstance(forwarded, Question)
        return forwarded

    async def _back(self, answer: Answer) -> AsyncIterator[RunEvent]:
        after = [i async for i in self.client.answer(answer)]
        assert after and after[-1].state == "completed"
        yield ReplyChunk("Counted.", last=True)

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        forwarded = await self._forwarded()
        if self.pause == "live":
            async for event in self._back(await ctx.ask(forwarded)):
                yield event
        else:
            yield Ask(forwarded)

    async def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        async for event in self._back(answer):
            yield event


@pytest.mark.parametrize("pause", PAUSES)
def test_door_question_forwarded(pause: str) -> None:
    example = kit.load("question-forwarded.json")
    inner_step, outer_step = example.steps
    (inner_request,) = kit.objects(inner_step)
    (outer_request,) = kit.objects(outer_step)
    assert isinstance(outer_request, Question) and outer_request.origin is not None
    origin = to_json(outer_request)["origin"]

    async def go() -> None:
        inventory = kit.ScriptedSource(kit.Script((("ask", inner_request),)), pause)
        async with serve(SourceExecutor(inventory), _card(origin["url"]),
                         rpc_url=httpx.URL(origin["url"]).path) as inner:
            http = httpx.AsyncClient(transport=StreamingASGITransport(inner.app), timeout=TIMEOUT,
                                     headers={"Authorization": "Bearer report-service"})
            client = R2CClient.from_card(inner.card, httpx_client=http)
            front = Forwarding(pause, client, origin)
            try:
                async with serve(SourceExecutor(front), _card()) as served, a2a_client(served, user="alice") as tc:
                    events = await stream(tc, message(Part(text="Start.")))
                    assert front.asked == inner_request  # the inventory remote's wire
                    names = (kit.Names(), kit.Names())
                    assert [kit.wire_form(e, names[1]) for e in events[1:]] == [kit.remote_form(outer_step, names[0])]
                    reply = kit.sample_answer(outer_request)
                    done = await stream(tc, message(Part(text=answer_text(reply, outer_request)), r2c_part(reply),
                                                    **_task_of(events)))
                    assert kinds(done)[-1] == "completed"
                    assert inventory.answers == [reply]
            finally:
                await client.aclose()
                await http.aclose()

    run(go())


def test_client_question_forwarded() -> None:
    example = kit.load("question-forwarded.json")
    for step in example.steps:  # two connections, one task each
        run(_client(kit.Example(example.name, (step,))))
