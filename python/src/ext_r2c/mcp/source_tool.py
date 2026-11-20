"""One ``AgentSource`` as one MCP tool, across the rounds of a tool call (spec 004, research R4,
R6, R9, R11, R12, data-model.md "Tool call lifecycle").

Each round reads the run until an ``Ask``, ``Done`` or ``Error``. An ``Ask`` gives an
input-required result whose ``requestState`` is the stopping point; the retry hands the derived
answer to the held run, or resumes a checkpoint source the door no longer holds.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp_types as types
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from ..core import (
    ActivityEvent,
    AgentSource,
    Answer,
    AnsweredBy,
    Approval,
    ArtifactEvent,
    Ask,
    Done,
    Driver,
    Error,
    NotAskableOverMcp,
    Question,
    ReplyChunk,
    Run,
    RunInput,
    Usage,
    UsageEvent,
    answer_from_mcp,
    parse,
    thread_id,
    to_json,
)
from ._codec import Block, content_blocks, final_result, input_required, output_too_large
from ._state import StoppingPoint, dump
from .activation import Round

__all__ = ["SourceTool"]

DEFAULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "What to ask the agent."},
        "context_id": {"type": "string", "description": "The conversation to continue; leave it out to start one."},
    },
    "required": ["message"],
    "additionalProperties": False,
}
_BLOCKS: TypeAdapter[list[Block]] = TypeAdapter(list[Block])
_NO_FORMS = "The client cannot show forms, so the request could not be asked."
_NOT_ASKABLE = "The request cannot be asked as a form."

ToInput = Callable[[Mapping[str, Any]], "tuple[RunInput, str | None]"]


def _default_to_input(arguments: Mapping[str, Any]) -> tuple[RunInput, str | None]:
    context = arguments.get("context_id")
    return RunInput(text=str(arguments.get("message", ""))), context if isinstance(context, str) and context else None


def _declined(request: Question | Approval, note: str) -> Answer:
    return Answer(id=request.id, outcome="declined", answered_by=AnsweredBy(role="policy"), note=note)


def _join(*lines: str | None) -> str | None:
    return "\n".join(line for line in lines if line) or None


def tool_error(text: str, *, usage: Usage | None = None, active: bool = False) -> types.CallToolResult:
    """A complete result with ``isError: true`` and ``text``."""
    return final_result(reply="", blocks=[], usage=usage, active=active, refusal=text, is_error=True)


@dataclass
class Held:
    """A tool call whose run the door holds in memory, with what it gathered for the final result."""

    run: Run
    call: str
    owner: str
    thread: str
    context: str
    reply: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    usage: Usage | None = None
    request: Question | Approval | None = None
    refusal: str | None = None


class SourceTool:
    """An ``AgentSource`` served as one tool (research R12).

    The default input schema is ``{message, context_id}``: ``message`` is the run's input text,
    and ``context_id`` names the conversation; without it the door chooses one and returns it in
    ``structuredContent``. ``input_schema`` with ``to_input(arguments) -> (RunInput, context_id
    or None)`` exposes the agent as a domain tool instead; each call without a context id is then
    its own conversation.
    """

    def __init__(self, source: AgentSource, *, name: str = "agent", title: str | None = None,
                 description: str | None = None, input_schema: dict[str, Any] | None = None,
                 to_input: ToInput | None = None) -> None:
        if (input_schema is None) != (to_input is None):
            raise ValueError("input_schema and to_input are given together")
        self.source = source
        self.driver = Driver(source)
        self.name = name
        self.title = title
        self.description = source.card.description if description is None else description
        self.input_schema = DEFAULT_SCHEMA if input_schema is None else input_schema
        self.to_input: ToInput = to_input or _default_to_input
        self._returns_context = input_schema is None
        self._check = Draft202012Validator(self.input_schema)
        self._runs: dict[str, Held] = {}

    # --- rounds -------------------------------------------------------------------------------

    async def first_round(self, r: Round, arguments: Mapping[str, Any]) -> types.CallToolResult | types.InputRequiredResult:
        problems = sorted(self._check.iter_errors(dict(arguments)), key=lambda e: list(e.path))
        if problems:
            return tool_error("invalid arguments: " + "; ".join(p.message for p in problems), active=r.active)
        run_input, context = self.to_input(arguments)
        context = context or uuid.uuid4().hex
        thread = thread_id("mcp", r.owner, context)
        held = Held(self.driver.start(thread, run_input), uuid.uuid4().hex, r.owner, thread, context)
        self._runs[held.call] = held
        return await self._pump(r, held)

    async def retry(self, r: Round, point: StoppingPoint,
                    responses: Mapping[str, types.ElicitResult]) -> types.CallToolResult | types.InputRequiredResult:
        request = parse(point.request)
        assert isinstance(request, (Question, Approval))
        response = responses[request.id]
        answer = answer_from_mcp(request, response.action, response.content)
        return await self.hand_over(r, point, request, answer)

    async def hand_over(self, r: Round, point: StoppingPoint, request: Question | Approval,
                        answer: Answer, *, refusal: str | None = None) -> types.CallToolResult | types.InputRequiredResult:
        """Give ``answer`` to the paused run: ``deliver`` when held, else ``Driver.resume``."""
        held = self._runs.get(point.call)
        if held is not None:
            held.request = None
            held.refusal = _join(held.refusal, refusal)
            await held.run.deliver(answer)
            return await self._pump(r, held)
        held = Held(self.driver.resume(point.thread or "", request, answer), point.call, r.owner,
                    point.thread or "", point.context or "",
                    reply=[str(point.output.get("reply") or "")],
                    blocks=_BLOCKS.validate_python(point.output.get("blocks") or []),
                    usage=Usage.parse(point.usage) if point.usage else None, refusal=refusal)
        self._runs[held.call] = held
        return await self._pump(r, held)

    # --- reading the run ----------------------------------------------------------------------

    async def _pump(self, r: Round, held: Held) -> types.CallToolResult | types.InputRequiredResult:
        try:
            while True:
                event = await anext(held.run)
                if isinstance(event, ReplyChunk):
                    held.reply.append(event.text)
                elif isinstance(event, ActivityEvent):
                    await r.progress(event.activity)
                elif isinstance(event, ArtifactEvent):
                    held.blocks.extend(content_blocks(event, active=True))
                elif isinstance(event, UsageEvent):
                    held.usage = event.usage
                elif isinstance(event, Ask):
                    result = await self._ask(r, held, event.request)
                    if result is not None:
                        return result
                elif isinstance(event, Done):
                    return self._end(r, held)
                elif isinstance(event, Error):
                    return self._end(r, held, error=event.reason)
        except anyio.get_cancelled_exc_class():
            with anyio.CancelScope(shield=True):
                await held.run.cancel()
            self._drop(held)
            raise

    async def _ask(self, r: Round, held: Held, request: Question | Approval) -> types.InputRequiredResult | types.CallToolResult | None:
        """The input-required result for ``request``, or ``None`` when the door answered it."""
        if not r.form:
            await held.run.deliver(_declined(request, _NO_FORMS))
            return None
        try:
            input_required(request, "", active=False, usage=None)
        except NotAskableOverMcp:
            await held.run.deliver(_declined(request, _NOT_ASKABLE))
            return None
        reply = "".join(held.reply)
        problem = output_too_large(reply, held.blocks, r.limits)
        if problem is not None:
            await held.run.cancel()
            self._drop(held)
            return tool_error(problem.message, usage=held.usage, active=r.active)
        point = StoppingPoint(
            call=held.call, round=uuid.uuid4().hex, kind="source", request=to_json(request),
            thread=held.thread, context=held.context, pause=self.source.pause,
            usage=to_json(held.usage) if held.usage is not None else None,
            output={"reply": reply, "blocks": _BLOCKS.dump_python(held.blocks, mode="json", by_alias=True,
                                                                  exclude_none=True)},
        )
        held.request = request
        refusal, held.refusal = held.refusal, None
        return input_required(request, dump(point), active=r.active, usage=held.usage, refusal=refusal)

    def _end(self, r: Round, held: Held, *, error: str | None = None) -> types.CallToolResult:
        self._drop(held)
        reply = "".join(held.reply)
        problem = output_too_large(reply, held.blocks, r.limits)
        if problem is not None:
            return tool_error(problem.message, usage=held.usage, active=r.active)
        structured = {"context_id": held.context} if self._returns_context else None
        return final_result(reply=reply, blocks=held.blocks, usage=held.usage, active=r.active,
                            refusal=_join(held.refusal, error), is_error=error is not None, structured=structured)

    def _drop(self, held: Held) -> None:
        if self._runs.get(held.call) is held:
            del self._runs[held.call]
