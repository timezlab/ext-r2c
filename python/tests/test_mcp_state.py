"""The stopping point the door puts in `requestState`, and the single-use round ledger (spec
004, research R3, data-model.md "Stopping point")."""

from __future__ import annotations

import json

import pytest
from ext_r2c.mcp._state import LostState, MemoryLedger, StoppingPoint, dump, load

from mcp_harness import run


def _point() -> StoppingPoint:
    return StoppingPoint(
        call="c" * 32, round="r" * 32, kind="source",
        request={"kind": "question", "id": "q-1", "title": "T", "answer_by": {"role": "person"}, "fields": []},
        thread="mcp:abc", context="ctx-1", pause="checkpoint",
        usage={"kind": "usage", "input_tokens": 3},
        output={"reply": "Before the ask.", "blocks": [{"type": "text", "text": "x"}]},
    )


def test_round_trip() -> None:
    point = _point()
    text = dump(point)
    assert json.loads(text)["v"] == 1 and " " not in text.split('"T"')[0]
    assert load(text) == point
    approve = StoppingPoint(call="c", round="r", kind="approve", request=point.request)
    assert load(dump(approve)) == approve


@pytest.mark.parametrize("text", ['{"v": 2, "call": "c"}', "not json", "[]", '{"v": 1}'])
def test_unknown_or_broken_state_is_lost(text: str) -> None:
    with pytest.raises(LostState):
        load(text)


def test_memory_ledger_claims_once() -> None:
    now = [1000.0]
    ledger = MemoryLedger(clock=lambda: now[0])

    async def main() -> None:
        assert await ledger.claim("n-1", until=1060.0) is True
        assert await ledger.claim("n-1", until=1060.0) is False
        assert await ledger.claim("n-2", until=1060.0) is True
        now[0] = 1061.0  # past the expiry: the entry is swept, the boundary refuses the state anyway
        assert await ledger.claim("n-1", until=1120.0) is True
        assert len(ledger) == 1

    run(main())
