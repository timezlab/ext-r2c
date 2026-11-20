"""Every MCP example replayed as a real in-process round trip (spec 004 story 7, SC-001,
contracts/replay.md).

- `client:<file>`: a wire server plays the file's remote steps, and `R2CClient` must send the
  file's client steps and read every R2C object as one typed item.
- `door:<file>:<pause>`: the file's remote steps become a scripted source behind the door (or a
  tool behind `approve=`), and the door must send the file's remote steps.
- `discover`: `server/discover` of `mcp_server(...)` equals `discover.json`.
"""

from __future__ import annotations

from typing import Any

import httpx2
import mcp_types as types
import pytest
from ext_r2c.core import ReplyChunk, answer_from_mcp, parse, to_json
from ext_r2c.mcp import (
    ActivityItem,
    AnswerRejected,
    ArtifactItem,
    R2CClient,
    R2CExtension,
    RequestItem,
    SourceTool,
    UsageItem,
    mcp_server,
)

import mcp_replay_kit as kit
from mcp_harness import BASE, TIMEOUT, URL, Scripted, call, mcp_client, run, serve
from mcp_transport import Record, StreamingASGITransport

PAUSES = ["checkpoint", "live"]
DOOR = [n for n in kit.names() if n not in kit.DOOR_EXEMPT]


def _normalised(messages: list[dict[str, Any]]) -> list[Any]:
    names = kit.Names()
    return [kit.normalise(m, names) for m in messages]


# --- Door mode -----------------------------------------------------------------------------------


async def _door(example: kit.Example, pause: str) -> None:
    server, _ = kit.door_server(example, pause)
    record: Record = []
    door_names, file_names = kit.Names(), kit.Names()
    async with serve(server, record=record) as served, mcp_client(served, active=example.activated) as client:
        state: str | None = None
        keys: dict[str, str] = {}  # the file's request key → the door's (it chooses an approval's id)
        for turn in kit.turns(example):
            mark = len(record)
            if turn.request is None:
                tool, arguments, progress = example.first_call
                result = await call(client, tool, arguments, token="pt-1" if progress else None)
            else:
                params = turn.request.params
                responses = {keys.get(k, k): types.ElicitResult.model_validate(v)
                             for k, v in (params.get("inputResponses") or {}).items()}
                result = await call(client, params["name"], params.get("arguments") or {},
                                    state=state if "requestState" in params else None,
                                    responses=responses or None, token=turn.request.token)
            if isinstance(result, types.InputRequiredResult):
                assert result.request_state and result.request_state.startswith("v1."), "the door seals its state"
                state = result.request_state
                asked = next((s.result for s in turn.expect if s.result is not None), None) or {}
                keys.update(zip(asked.get("inputRequests") or {}, result.input_requests or {}))
            sent = record[mark:]
            ids = {m["id"] for side, m in sent if side == "client" and m.get("method") == "tools/call"}
            door = [m for side, m in sent if side == "remote" and (
                m.get("method") == "notifications/progress" or ("method" not in m and m.get("id") in ids))]
            if turn.expect:
                assert [kit.normalise(m, door_names) for m in door] == \
                    [kit.normalise(s.body, file_names) for s in turn.expect]


@pytest.mark.parametrize("pause", PAUSES)
@pytest.mark.parametrize("name", DOOR)
def test_door(name: str, pause: str) -> None:
    run(_door(kit.load(name), pause))


def test_exemptions_hold_both_ways() -> None:
    """A file is exempt from door mode exactly when it has no tool call to play."""
    for name in kit.names():
        example = kit.load(name)
        exempt = name in kit.DOOR_EXEMPT
        assert exempt == (not kit.turns(example)), name
        if exempt:
            with pytest.raises(kit.NotScriptable):
                kit.script_from_example(example)
        else:
            kit.script_from_example(example)
    assert set(kit.DOOR_EXEMPT) <= set(kit.names())


# --- Client mode ---------------------------------------------------------------------------------


async def _items(stream: Any) -> list[Any]:
    return [item async for item in stream]


async def _raw(client: R2CClient, step: kit.Step) -> list[Any]:
    """A retry the client would not send (no response, or one its check refuses), sent through
    its session with the state it holds; the result is read by the client as usual."""
    call_ = client._open
    assert call_ is not None
    params = step.params
    responses = {k: types.ElicitResult.model_validate(v) for k, v in (params.get("inputResponses") or {}).items()}
    result = await client.mcp.session.call_tool(
        call_.name, call_.arguments, meta={"progressToken": "pt-raw"} if step.token else None,
        input_responses=responses or None, request_state=call_.state, allow_input_required=True)
    client._open, client.pending = None, {}
    return list(client._result(call_, result))


async def _client_act(client: R2CClient, example: kit.Example, turn: kit.Turn) -> list[Any]:
    if turn.request is None:
        tool, arguments, progress = example.first_call
        return await _items(client.call(tool, arguments, progress=progress))
    params = turn.request.params
    if "requestState" not in params:
        return await _items(client.call(params["name"], params.get("arguments") or {},
                                        progress=turn.request.token is not None))
    responses = params.get("inputResponses") or {}
    if client.pending and set(client.pending) <= set(responses):
        try:
            got: list[Any] = []
            answers = []
            for key, response in responses.items():
                item = client.pending[key]
                if item.request is None:
                    got += await _items(client.respond(key, response["action"], response.get("content")))
                else:  # the derived answer: what the remote derives from the file's response
                    answers.append(answer_from_mcp(item.request, response["action"], response.get("content")))
            if answers:
                got += await _items(client.answer(*answers))
            return got
        except AnswerRejected:
            pass  # the client refuses to send it: the file shows a remote that is sent it anyway
    return await _raw(client, turn.request)


def _sent_objects(example: kit.Example) -> dict[str, list[Any]]:
    """Every R2C object in the file's remote steps, by what item it must come out as."""
    out: dict[str, list[Any]] = {"activity": [], "request": [], "plain": [], "usage": [], "artifact": []}
    for step in example.steps:
        if step.side != "remote":
            continue
        if step.type == "notification" and (meta := kit.r2c(step.params.get("_meta"))) is not None:
            out["activity"].append(to_json(parse(meta)))
        result = step.result or {}
        if result.get("resultType") == "input_required":
            for _, request, _params in kit.requests(result):
                out["request" if request is not None else "plain"].append(to_json(request) if request else None)
            if (usage := (kit.r2c(result.get("_meta")) or {}).get("usage")) is not None:
                out["usage"].append(to_json(parse(usage)))
        elif step.type == "result":
            if (usage := kit.r2c(result.get("_meta"))) is not None:
                out["usage"].append(to_json(parse(usage)))
            for block in result.get("content") or []:
                meta = kit.r2c(block.get("_meta"))
                if meta is not None and not meta.get("response"):
                    out["artifact"].append(to_json(parse(meta)))
    return out


def _read_objects(items: list[Any]) -> dict[str, list[Any]]:
    return {
        "activity": [to_json(i.activity) for i in items if isinstance(i, ActivityItem)],
        "request": [to_json(i.request) for i in items if isinstance(i, RequestItem) and i.request is not None],
        "plain": [None for i in items if isinstance(i, RequestItem) and i.request is None],
        "usage": [to_json(i.usage) for i in items if isinstance(i, UsageItem)],
        "artifact": [to_json(i.meta) for i in items if isinstance(i, ArtifactItem) and i.meta is not None],
    }


async def _client(example: kit.Example) -> None:
    record: Record = []
    got: list[Any] = []
    async with serve(kit.wire_server(example)) as served:
        http = httpx2.AsyncClient(transport=StreamingASGITransport(served.app, record=record), base_url=BASE,
                                  timeout=TIMEOUT)
        client = await R2CClient.connect(URL, http_client=http)
        try:
            assert client.active == example.activated
            for turn in kit.turns(example):
                got += await _client_act(client, example, turn)
            assert client.skipped == 0
        finally:
            await client.aclose()
            await http.aclose()
    turns = kit.turns(example)
    methods = {s.body.get("method") for s in example.steps if s.side == "client"}
    exchange = _exchange(record, methods, made_up=bool(turns) and turns[0].request is None)
    assert _requests(exchange) == _requests([(s.side, s.body) for s in example.steps])
    assert _read_objects(got) == _sent_objects(example)


def _exchange(record: Record, methods: set[Any], *, made_up: bool) -> list[tuple[str, dict[str, Any]]]:
    """The client's requests of the file's ``methods`` and the results that answer them, in wire
    order; without the made-up first call (its result stays: the file has it)."""
    out: list[tuple[str, dict[str, Any]]] = []
    asked: set[Any] = set()
    for side, message in record:
        if side == "client" and message.get("method") in methods | {"tools/call"}:
            if made_up and message.get("method") == "tools/call":
                made_up = False
                asked.add(message["id"])
                continue
            asked.add(message["id"])
            out.append((side, message))
        elif side == "remote" and "method" not in message and message.get("id") in asked:
            out.append((side, message))
    return out


def _requests(exchange: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    """The client's requests, normalised along with the results before them: a `requestState`
    sent back must be the one received."""
    names = kit.Names()
    normalised = [(side, kit.normalise(body, names)) for side, body in exchange]
    return [body for side, body in normalised if side == "client"]


@pytest.mark.parametrize("name", kit.names())
def test_client(name: str) -> None:
    run(_client(kit.load(name)))


# --- Discover mode -------------------------------------------------------------------------------


def test_discover() -> None:
    example = kit.load("discover.json")
    file_request, file_reply = (s.body for s in example.steps)
    server = mcp_server("replay", R2CExtension(tools=[SourceTool(Scripted("live", ReplyChunk("Hi.", last=True)))]))
    record: Record = []

    async def main() -> None:
        async with serve(server, record=record) as served, mcp_client(served):
            pass

    run(main())
    request = next(m for side, m in record if side == "client" and m.get("method") == "server/discover")
    reply = next(m for side, m in record if side == "remote" and m.get("id") == request["id"] and "result" in m)
    # R2C governs `capabilities.extensions` (R2C-ACT-4): equal. The capabilities the file lists
    # are there; the SDK's own others (prompts, resources, list-changed flags) and its cache hints
    # (required by MCP, compared for presence) are MCP's business.
    found, wanted = reply["result"], file_reply["result"]
    assert set(wanted["capabilities"]) <= set(found["capabilities"])
    capabilities = {k: wanted["capabilities"][k] if k != "extensions" else v
                    for k, v in found["capabilities"].items() if k in wanted["capabilities"]}
    hints = {k: wanted[k] for k in ("cacheScope", "ttlMs") if k in found}
    assert _normalised([request, {**reply, "result": {**found, **hints, "capabilities": capabilities}}]) == \
        _normalised([file_request, file_reply])
