"""The pieces of the MCP example replay (spec 004 contracts/replay.md). Test helper only.

- `load(name)` reads an example; `turns(example)` splits it into what the client sends and the
  remote steps that answer it. A file that starts with a remote step gets a first call the
  harness makes up from the file's next client step (`first_call`); it is not compared.
- `script_from_example(example)` is the converter of door mode; `door_server(example, pause)`
  serves it, as a scripted `SourceTool`, or as a `ToolSpec` behind `approve=` when the file
  approves a direct call. Exempt files raise `NotScriptable`.
- `wire_server(example)` is the server of client mode: it answers each `tools/call` with the
  file's next remote steps, as they are (the SDK seals the file's `requestState`).
- `normalise(node, names)` puts a message in the form both sides are compared in.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import mcp_types as types
from ext_r2c import MCP_KEY
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Approval,
    ArtifactEvent,
    ArtifactMeta,
    Ask,
    BytesContent,
    Question,
    ReplyChunk,
    RunInput,
    TextContent,
    ToolSpec,
    UrlContent,
    Usage,
    UsageEvent,
    parse,
)
from ext_r2c.mcp import R2CExtension, SourceTool, mcp_server
from mcp.server.extension import Extension, ToolBinding
from mcp.server.mcpserver import MCPServer
from mcp.server.request_state import RequestStateSecurity

from mcp_harness import Scripted
from r2c_check import standard_path

EXAMPLES = standard_path() / "examples" / "mcp"
DOOR_EXEMPT = {"discover.json": "not a tool call: the door's server/discover is compared in discover mode"}
KEYS = [b"r" * 32]
_PRESENT = "<present>"
_PLAIN = "io.example/replay"  # the wire server's extension when the file is not activated


# --- Examples and turns -----------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    side: str  # "client" or "remote"
    type: str
    body: dict[str, Any]

    @property
    def params(self) -> dict[str, Any]:
        return self.body.get("params") or {}

    @property
    def result(self) -> dict[str, Any] | None:
        return self.body.get("result")

    @property
    def is_call(self) -> bool:
        return self.side == "client" and self.body.get("method") == "tools/call"

    @property
    def token(self) -> Any:
        return (self.params.get("_meta") or {}).get("progressToken")


@dataclass(frozen=True)
class Example:
    name: str
    steps: tuple[Step, ...]
    description: str

    @property
    def activated(self) -> bool:
        """Whether the client lists the R2C key, or the remote sends R2C (a file of remote steps
        only)."""
        calls = [s for s in self.steps if s.side == "client"]
        if calls:
            return any(MCP_KEY in json.dumps(s.params.get("_meta") or {}) for s in calls)
        return MCP_KEY in json.dumps([s.body for s in self.steps])

    @property
    def first_call(self) -> tuple[str, dict[str, Any], bool]:
        """(tool, arguments, progress) of the call that opens the file's flow."""
        call = next((s for s in self.steps if s.is_call), None)
        if call is None:
            return "tool", {}, False
        return call.params["name"], dict(call.params.get("arguments") or {}), call.token is not None


def names() -> list[str]:
    return sorted(p.name for p in EXAMPLES.glob("*.json"))


def load(name: str) -> Example:
    data = json.loads((EXAMPLES / name).read_text("utf-8"))
    steps = tuple(Step(s["from"], s["type"], s["body"]) for s in data["steps"])
    return Example(name, steps, data.get("description", ""))


@dataclass
class Turn:
    """A client `tools/call` (``None``: the made-up first call), then the remote steps it gets."""

    request: Step | None
    expect: list[Step] = field(default_factory=list)


def turns(example: Example) -> list[Turn]:
    out: list[Turn] = []
    for step in example.steps:
        if step.is_call:
            out.append(Turn(step))
        elif step.side == "remote" and step.type in ("result", "notification"):
            if not out:
                out.append(Turn(None))
            out[-1].expect.append(step)
    return out


def r2c(meta: Any) -> Any:
    return meta.get(MCP_KEY) if isinstance(meta, Mapping) else None


def requests(result: Mapping[str, Any]) -> list[tuple[str, Question | Approval | None, dict[str, Any]]]:
    """(key, R2C request or ``None``, elicitation params) for each entry of an input-required
    result."""
    objects = (r2c(result.get("_meta")) or {}).get("input_requests") or {}
    out = []
    for key, entry in (result.get("inputRequests") or {}).items():
        obj = objects.get(key)
        request = parse(obj) if obj is not None else None
        assert request is None or isinstance(request, (Question, Approval))
        out.append((key, request, entry.get("params") or {}))
    return out


# --- Door mode: the converter ------------------------------------------------------------------


class NotScriptable(Exception):
    """The file is not a tool call the door can play (`DOOR_EXEMPT`)."""


def rebuilt_question(key: str, params: Mapping[str, Any]) -> Question:
    """A question with the form's fields, for an elicitation that carries no R2C object."""
    schema = params.get("requestedSchema") or {}
    required = set(schema.get("required") or [])
    fields = []
    for name, prop in (schema.get("properties") or {}).items():
        found: dict[str, Any] = {"key": name, "header": prop.get("title", name), "text": prop.get("description", name),
                                 "type": {"number": "number", "integer": "number", "boolean": "bool"}.get(prop.get("type"), "text")}
        if "oneOf" in prop:
            found.update(type="one", other=False, options=[{"label": o["const"]} for o in prop["oneOf"]])
        elif prop.get("type") == "array":
            found.update(type="many", other=False, options=[{"label": o["const"]} for o in prop["items"]["anyOf"]])
        if name not in required:
            found["required"] = False
        fields.append(found)
    question = parse({"kind": "question", "id": key, "title": str(params.get("message") or key),
                      "answer_by": {"role": "person"}, "fields": fields})
    assert isinstance(question, Question)
    return question


def _content(block: Mapping[str, Any]) -> tuple[str | None, Any]:
    """(artifact id when the block names one, content) of a content block."""
    kind = block.get("type")
    if kind == "resource_link":
        return None, UrlContent(block["uri"], block.get("mimeType", ""), block.get("name"))
    if kind in ("image", "audio"):
        return None, BytesContent(base64.b64decode(block["data"]), block["mimeType"])
    if kind == "resource":
        resource = block["resource"]
        uri = str(resource.get("uri", ""))
        id = uri.removeprefix("urn:r2c:artifact:") if uri.startswith("urn:r2c:artifact:") else None
        if "text" in resource:
            return id, TextContent(resource["text"], resource.get("mimeType", "text/plain"))
        return id, BytesContent(base64.b64decode(resource["blob"]), resource.get("mimeType", ""))
    return None, TextContent(str(block.get("text", "")))


def _final(result: Mapping[str, Any]) -> list[Any]:
    events: list[Any] = []
    usage = r2c(result.get("_meta"))
    if usage is not None:
        events.append(UsageEvent(Usage.parse(usage)))
    blocks = result.get("content") or []
    marked = any(r2c(b.get("_meta")) is not None for b in blocks)
    reply: str | None = None
    for i, block in enumerate(blocks):
        meta = r2c(block.get("_meta"))
        if block.get("type") == "text" and reply is None and (meta or {}).get("response", not marked):
            reply = block["text"]
            continue
        id, content = _content(block)
        presentation = ArtifactMeta.parse(meta) if meta else ArtifactMeta(presentation="file")
        events.append(ArtifactEvent(id or f"a-{i + 1}", presentation, (content,)))
    events.append(ReplyChunk(reply or "", last=True))
    return events


def script_from_example(example: Example) -> list[Any]:
    """The run events a scripted source yields to make the door send the file's remote steps."""
    if example.name in DOOR_EXEMPT:
        raise NotScriptable(DOOR_EXEMPT[example.name])
    events: list[Any] = []
    asked: set[str] = set()
    for step in example.steps:
        if step.side != "remote":
            continue
        if step.type == "notification":
            meta = r2c(step.params.get("_meta"))
            activity = Activity.parse(meta) if meta else Activity.parse(
                {"kind": "activity", "id": f"p-{len(events)}", "type": "step", "state": "running",
                 "label": step.params.get("message", "")})
            events.append(ActivityEvent(activity))
        elif (result := step.result) is not None and result.get("resultType") == "input_required":
            usage = (r2c(result.get("_meta")) or {}).get("usage")
            if usage is not None:
                events.append(UsageEvent(Usage.parse(usage)))
            for key, request, params in requests(result):
                request = request or rebuilt_question(key, params)
                if request.id not in asked:  # a request seen before is the door's own re-ask
                    asked.add(request.id)
                    events.append(Ask(request))
        elif result is not None:
            events.extend(_final(result))
    return events


def direct_approval(example: Example) -> Approval | None:
    """The approval of a direct tool call: the file's first request, about the called tool."""
    tool = example.first_call[0]
    for step in example.steps:
        if step.side == "remote" and step.result and step.result.get("resultType") == "input_required":
            request = requests(step.result)[0][1]
            if isinstance(request, Approval) and request.subject.name == tool:
                return request
            return None
    return None


def door_server(example: Example, pause: str) -> tuple[Any, Scripted | None]:
    """The door that plays ``example`` (fixed request-state keys), and its scripted source."""
    security = RequestStateSecurity(keys=KEYS)
    approval = direct_approval(example)
    if approval is not None:
        async def never(arguments: Mapping[str, Any]) -> str:
            return "ran"

        spec = ToolSpec(approval.subject.name, "A tool behind approval.", dict(approval.subject.args_schema or {}), never)
        return mcp_server("replay", R2CExtension(tools=[spec], approve={spec.name: True}), security=security), None
    source = Scripted(pause, *script_from_example(example))
    tool = SourceTool(source, name=example.first_call[0], input_schema={"type": "object"},
                      to_input=lambda arguments: (RunInput(text=json.dumps(dict(arguments), sort_keys=True)), None))
    return mcp_server("replay", R2CExtension(tools=[tool]), security=security), source


# --- Client mode: the wire server --------------------------------------------------------------


class Replayer(Extension):
    """Answers each `tools/call` with the file's next remote steps: the notifications (with the
    call's own progress token), then the result."""

    identifier = MCP_KEY

    def __init__(self, example: Example) -> None:
        self.example = example
        self.turns = turns(example)
        self.calls = 0
        if not example.activated:
            self.identifier = _PLAIN

    def settings(self) -> dict[str, Any]:
        return {"revision": 1}

    def tools(self) -> list[ToolBinding]:
        def stub() -> str:
            raise RuntimeError("served by intercept_tool_call")

        names = {self.example.first_call[0]} | {s.params["name"] for s in self.example.steps if s.is_call}
        return [ToolBinding(stub, kwargs={"name": n, "structured_output": False}) for n in sorted(names)]

    async def intercept_tool_call(self, params: types.CallToolRequestParams, ctx: Any, call_next: Any) -> Any:
        turn = self.turns[self.calls] if self.calls < len(self.turns) else Turn(None)
        self.calls += 1
        token = (ctx.meta or {}).get("progress_token")
        result: dict[str, Any] | None = None
        for step in turn.expect:
            if step.type == "notification" and token is not None:
                sent = types.ProgressNotificationParams.model_validate({**step.params, "progressToken": token})
                await ctx.session.send_notification(types.ProgressNotification(params=sent),
                                                    related_request_id=ctx.request_id)
            elif step.result is not None:
                result = step.result
        if result is None:  # the file ends before the remote answers this call
            return types.CallToolResult(content=[types.TextContent(type="text", text="(the file ends here)")])
        if result.get("resultType") == "input_required":
            return types.InputRequiredResult.model_validate(result)
        return types.CallToolResult.model_validate(result)


def wire_server(example: Example) -> MCPServer:
    server = MCPServer("replay", extensions=[Replayer(example)], request_state_security=RequestStateSecurity(keys=KEYS))
    discover = next((s.result for s in example.steps if s.type == "discover"), None)
    if discover is not None:
        async def handle(ctx: Any, params: Any) -> types.DiscoverResult:
            return types.DiscoverResult.model_validate(discover)

        server._lowlevel_server.add_request_handler("server/discover", types.RequestParams, handle)
    return server


# --- Normalising ---------------------------------------------------------------------------------


class Names:
    """Stable names for what differs from run to run: JSON-RPC ids, request states, progress
    tokens and request ids (the door chooses an approval's id itself)."""

    def __init__(self) -> None:
        self.found: dict[str, dict[Any, str]] = {"id": {}, "state": {}, "token": {}, "request": {}}

    def __call__(self, kind: str, value: Any) -> str:
        found = self.found[kind]
        if value not in found:
            found[value] = f"<{kind}-{len(found) + 1}>"
        return found[value]


_KEYED = ("inputRequests", "inputResponses", "input_requests")


def normalise(node: Any, names: Names, *, key: str | None = None, top: bool = True) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if top and k == "id":
                out[k] = names("id", v)
            elif k == "_meta" and isinstance(v, dict):
                kept = {mk: mv for mk, mv in v.items() if not mk.startswith("io.modelcontextprotocol/")}
                if kept:
                    out[k] = normalise(kept, names, key=k, top=False)
            elif k == "requestState" and isinstance(v, str):
                out[k] = names("state", v)
            elif k == "progressToken":
                out[k] = names("token", v)
            elif k == "isError" and v is False:
                continue
            elif k in _KEYED and isinstance(v, dict):
                out[k] = {names("request", rk): normalise(rv, names, key=k, top=False) for rk, rv in v.items()}
            elif key == "input_requests" and k == "id":
                out[k] = names("request", v)
            elif key == "errors" and k == "message":
                out[k] = _PRESENT
            else:
                out[k] = normalise(v, names, key=k, top=False)
        return out
    if isinstance(node, list):
        return [normalise(v, names, key=key, top=False) for v in node]
    if isinstance(node, float) and node.is_integer():
        return int(node)
    return node
