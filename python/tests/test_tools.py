"""A plain function becomes a `ToolSpec` whose input schema checks every call and can back an
approval (spec 002, story 5; research R12)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Literal

import pytest

from ext_r2c.core import Approval, InvalidArguments, ToolSpec, mcp_form, tool_from_function


def reorder(item: str, quantity: int = 1) -> str:
    """Reorder an item from its usual supplier.

    The order is placed at once; use an approval to review it first.
    """
    return f"ordered {quantity} x {item}"


async def place_order(item: str, quantity: int, supplier: Literal["S-7", "S-9"] = "S-7") -> dict[str, Any]:
    """Place an order with a supplier."""
    await asyncio.sleep(0)
    return {"item": item, "quantity": quantity, "supplier": supplier}


def _call(tool: ToolSpec, args: dict[str, Any]) -> Any:
    return asyncio.run(tool.call(args))


# --- Story 5 scenarios -------------------------------------------------------------------------


def test_a_sync_function_becomes_a_tool() -> None:  # scenario 1
    tool = tool_from_function(reorder)
    assert tool.name == "reorder"
    assert tool.description == "Reorder an item from its usual supplier."
    schema = tool.input_schema
    assert schema["type"] == "object"
    assert schema["required"] == ["item"]
    assert schema["properties"]["item"]["type"] == "string"
    assert schema["properties"]["quantity"]["type"] == "integer"
    assert schema["properties"]["quantity"]["default"] == 1
    assert _call(tool, {"item": "A-113"}) == "ordered 1 x A-113"
    assert _call(tool, {"item": "A-113", "quantity": 3}) == "ordered 3 x A-113"


def test_bad_arguments_fail_before_the_function_runs() -> None:  # scenario 2
    calls: list[dict[str, Any]] = []

    def record(item: str, quantity: int = 1) -> None:
        calls.append({"item": item, "quantity": quantity})

    tool = tool_from_function(record)
    with pytest.raises(InvalidArguments) as caught:
        _call(tool, {"quantity": "three"})
    assert sorted(p.key or "" for p in caught.value.problems) == ["item", "quantity"]
    assert {p.code for p in caught.value.problems} == {"invalid_args"}
    assert calls == []


def test_a_flat_input_schema_keeps_edit_on_mcp() -> None:  # scenario 3
    tool = tool_from_function(place_order)
    approval = Approval.parse({
        "kind": "approval", "id": "ap-1", "title": "Place the order", "answer_by": {"role": "person"},
        "subject": {"type": "tool_call", "name": tool.name,
                    "args": {"item": "A-113", "quantity": 500, "supplier": "S-7"},
                    "args_schema": tool.input_schema},
        "decisions": ["allow", "edit", "deny"],
    })
    form = mcp_form(approval)
    assert form.decisions == ["allow", "edit", "deny"]
    assert form.requested_schema["properties"]["supplier"]["oneOf"] == [
        {"const": "S-7", "title": "S-7"}, {"const": "S-9", "title": "S-9"}]


# --- More --------------------------------------------------------------------------------------


def test_an_async_function_is_awaited() -> None:
    tool = tool_from_function(place_order)
    assert tool.input_schema["required"] == ["item", "quantity"]
    assert tool.input_schema["properties"]["supplier"]["enum"] == ["S-7", "S-9"]
    assert _call(tool, {"item": "A-113", "quantity": 2}) == {"item": "A-113", "quantity": 2, "supplier": "S-7"}
    with pytest.raises(InvalidArguments) as caught:
        _call(tool, {"item": "A-113", "quantity": 2, "supplier": "S-1"})
    assert [p.key for p in caught.value.problems] == ["supplier"]


def test_a_sync_function_runs_off_the_event_loop() -> None:
    seen: dict[str, int] = {}

    def where() -> None:
        seen["thread"] = threading.get_ident()

    async def go() -> None:
        seen["loop"] = threading.get_ident()
        await tool_from_function(where).call({})

    asyncio.run(go())
    assert seen["thread"] != seen["loop"]


def test_name_and_description_can_be_overridden() -> None:
    tool = tool_from_function(reorder, name="reorder_item", description="Reorder one item.")
    assert (tool.name, tool.description) == ("reorder_item", "Reorder one item.")


def test_the_description_is_the_first_paragraph() -> None:
    def wrapped() -> None:
        """First line
        goes on here.

        Second paragraph.
        """

    assert tool_from_function(wrapped).description == "First line goes on here."
    assert tool_from_function(lambda: None, name="nothing").description == ""


def test_star_parameters_are_refused() -> None:
    def star_args(*items: str) -> None: ...
    def star_kwargs(**options: str) -> None: ...
    def positional(item: str, /) -> None: ...

    for fn in (star_args, star_kwargs, positional):
        with pytest.raises(TypeError):
            tool_from_function(fn)


def test_unknown_arguments_are_refused() -> None:
    with pytest.raises(InvalidArguments) as caught:
        _call(tool_from_function(reorder), {"item": "A-113", "colour": "red"})
    assert caught.value.problems
    assert "item" not in [p.key for p in caught.value.problems]


def test_the_schema_is_checked_exactly() -> None:
    # The input schema says integer, so "3" is refused, as JSON Schema would.
    with pytest.raises(InvalidArguments):
        _call(tool_from_function(reorder), {"item": "A-113", "quantity": "3"})


def test_the_input_schema_has_no_top_level_title() -> None:
    assert "title" not in tool_from_function(reorder).input_schema


def test_a_tool_spec_is_frozen() -> None:
    tool = tool_from_function(reorder)
    with pytest.raises(AttributeError):
        tool.name = "other"  # type: ignore[misc]
