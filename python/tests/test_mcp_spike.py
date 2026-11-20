"""The MCP SDK facts the door leans on (spec 004, research R1, R3, R5, R8, R13). Each test pins
one; a failing one means the SDK changed under the design, and the plan is revisited first."""

from __future__ import annotations

from typing import Any

import mcp_types as types
import pytest
from ext_r2c import MCP_KEY
from mcp.server.extension import Extension, ToolBinding
from mcp.server.mcpserver import MCPServer
from mcp.server.request_state import authenticated_principal
from mcp.shared.exceptions import MCPError
from mcp_harness import auth, dump, mcp_client, principal, run, serve

SCHEMA = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}
STATE = '{"n":1}'


class Spike(Extension):
    """Serves the tool `ask` itself: the first round asks one question, a retry completes."""

    identifier = MCP_KEY

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stub_ran = False

    def settings(self) -> dict[str, Any]:
        return {"revision": 1}

    def tools(self) -> list[ToolBinding]:
        def stub() -> str:
            self.stub_ran = True
            return "the stub ran"

        return [ToolBinding(stub, kwargs={"name": "ask", "description": "Asks.", "structured_output": False})]

    async def intercept_tool_call(self, params: types.CallToolRequestParams, ctx: Any, call_next: Any) -> Any:
        if params.name != "ask":
            return await call_next(ctx)
        caps = ctx.session.client_capabilities
        self.calls.append({
            "state": params.request_state, "responses": params.input_responses, "arguments": params.arguments,
            "extensions": caps.extensions if caps else None, "elicitation": caps.elicitation if caps else None,
            "principal": authenticated_principal(ctx), "token": (ctx.meta or {}).get("progress_token"),
        })
        token = (ctx.meta or {}).get("progress_token")
        if token is not None:
            note = types.ProgressNotification(params=types.ProgressNotificationParams(
                progress_token=token, progress=1, message="Working", _meta={MCP_KEY: {"kind": "activity"}}))
            await ctx.session.send_notification(note, related_request_id=ctx.request_id)
        if params.request_state is None:
            form = types.ElicitRequestFormParams(message="Which?", requested_schema={
                "type": "object", "properties": {"x": {"type": "string"}}})
            return types.InputRequiredResult(input_requests={"q-1": types.ElicitRequest(params=form)},
                                             request_state=STATE)
        return types.CallToolResult(content=[types.TextContent(type="text", text="done")])


async def list_schema(ctx: Any, call_next: Any) -> Any:
    """A server middleware that puts `SCHEMA` on the tool `ask` in `tools/list`."""
    result = await call_next(ctx)
    if ctx.method != "tools/list":
        return result
    data = result if isinstance(result, dict) else result.model_dump(mode="json", by_alias=True, exclude_none=True)
    for tool in data["tools"]:
        if tool["name"] == "ask":
            tool["inputSchema"] = SCHEMA
    return data


def _server(spike: Spike, **kwargs: Any) -> MCPServer:
    return MCPServer("spike", extensions=[spike], middleware=[list_schema], **kwargs)


ACCEPT = {"q-1": types.ElicitResult(action="accept", content={"x": "y"})}


def test_interceptor_short_circuits_before_argument_validation() -> None:
    async def main() -> None:
        spike = Spike()
        async with serve(_server(spike)) as served, mcp_client(served) as client:
            result = await client.session.call_tool("ask", {"message": "hi", "unknown": 1}, allow_input_required=True)
        assert isinstance(result, types.InputRequiredResult)
        assert spike.calls[0]["arguments"] == {"message": "hi", "unknown": 1}
        assert not spike.stub_ran

    run(main())


def test_middleware_rewrites_tools_list_schema() -> None:
    async def main() -> None:
        async with serve(_server(Spike())) as served, mcp_client(served) as client:
            listed = await client.session.list_tools()
        assert [(t.name, t.input_schema) for t in listed.tools] == [("ask", SCHEMA)]

    run(main())


def test_interceptor_input_required_is_sealed_and_unsealed() -> None:
    async def main() -> None:
        spike = Spike()
        async with serve(_server(spike)) as served, mcp_client(served) as client:
            first = await client.session.call_tool("ask", {"message": "hi"}, allow_input_required=True)
            assert isinstance(first, types.InputRequiredResult)
            assert first.request_state is not None and first.request_state.startswith("v1.")
            assert STATE not in first.request_state
            done = await client.session.call_tool("ask", {"message": "hi"}, input_responses=ACCEPT,
                                                  request_state=first.request_state, allow_input_required=True)
        assert isinstance(done, types.CallToolResult)
        assert spike.calls[1]["state"] == STATE
        assert spike.calls[1]["responses"]["q-1"].content == {"x": "y"}

    run(main())


def test_replayed_state_runs_twice() -> None:
    """The boundary does not make a state single use: the door's ledger must (research R3)."""

    async def main() -> None:
        spike = Spike()
        async with serve(_server(spike)) as served, mcp_client(served) as client:
            first = await client.session.call_tool("ask", {"message": "hi"}, allow_input_required=True)
            for _ in range(2):
                again = await client.session.call_tool("ask", {"message": "hi"}, input_responses=ACCEPT,
                                                       request_state=first.request_state, allow_input_required=True)
                assert isinstance(again, types.CallToolResult) and not again.is_error
        assert [c["state"] for c in spike.calls] == [None, STATE, STATE]

    run(main())


def test_principal_from_bearer() -> None:
    async def main() -> None:
        spike = Spike()
        async with serve(_server(spike, **auth())) as served:
            async with mcp_client(served, user="alice") as alice:
                first = await alice.session.call_tool("ask", {"message": "hi"}, allow_input_required=True)
            async with mcp_client(served, user="bob") as bob:
                await bob.session.call_tool("ask", {"message": "hi"}, allow_input_required=True)
                with pytest.raises(MCPError) as caught:
                    await bob.session.call_tool("ask", {"message": "hi"}, input_responses=ACCEPT,
                                                request_state=first.request_state, allow_input_required=True)
        assert caught.value.error.code == -32602
        assert [c["principal"] for c in spike.calls] == [principal("alice"), principal("bob")]
        assert principal("alice") != principal("bob")

    run(main())


def test_progress_with_meta() -> None:
    async def main() -> None:
        notes: list[types.ProgressNotification] = []

        async def handle(message: object) -> None:
            if isinstance(message, types.ProgressNotification):
                notes.append(message)

        record: list[tuple[str, dict[str, Any]]] = []
        async with serve(_server(Spike()), record=record) as served:
            async with mcp_client(served, message_handler=handle) as client:
                await client.session.call_tool("ask", {"message": "hi"}, meta={"progressToken": "p-1"},
                                               allow_input_required=True)
        assert [n.params.meta for n in notes] == [{MCP_KEY: {"kind": "activity"}}]
        assert notes[0].params.progress_token == "p-1" and notes[0].params.message == "Working"
        call_id = next(m["id"] for side, m in record if side == "client" and m.get("method") == "tools/call")
        order = [m.get("method") or "result" for side, m in record
                 if side == "remote" and (m.get("method") == "notifications/progress" or m.get("id") == call_id)]
        assert order == ["notifications/progress", "result"]

    run(main())


def test_raw_input_required_on_client() -> None:
    async def main() -> None:
        record: list[tuple[str, dict[str, Any]]] = []
        async with serve(_server(Spike()), record=record) as served, mcp_client(served) as client:
            first = await client.session.call_tool("ask", {"message": "hi"}, allow_input_required=True)
            assert isinstance(first, types.InputRequiredResult)  # the raising callback never ran
            await client.session.call_tool("ask", {"message": "hi"}, input_responses=ACCEPT,
                                           request_state=first.request_state, allow_input_required=True)
        retries = [m for side, m in record if side == "client" and "requestState" in (m.get("params") or {})]
        assert [r["params"]["requestState"] for r in retries] == [first.request_state]
        assert dump(first)["inputRequests"]["q-1"]["params"]["mode"] == "form"

    run(main())


def test_client_capabilities_per_request() -> None:
    async def main() -> None:
        spike = Spike()
        async with serve(_server(spike)) as served:
            async with mcp_client(served) as active:
                await active.session.call_tool("ask", {"message": "hi"}, allow_input_required=True)
            async with mcp_client(served, active=False, form=False) as plain:
                await plain.session.call_tool("ask", {"message": "hi"}, allow_input_required=True)
        assert MCP_KEY in (spike.calls[0]["extensions"] or {})
        assert spike.calls[0]["elicitation"] is not None
        assert MCP_KEY not in (spike.calls[1]["extensions"] or {})
        assert spike.calls[1]["elicitation"] is None

    run(main())
