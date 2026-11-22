"""The scripted chat model of the LangGraph bridge's tests (spec 006, research R17).

The model is the only fake in those tests: the graph, the middleware, the checkpointer and the
bridge are the real packages. It says what a script says, where a script is a **pure function of
the message history**: a "restart" builds a new graph and a new model object, and the new one must
say the same thing the old one would have. A counter kept in the model would break that, so the
counters live in objects the test passes in (`Calls`, `Gate`).

Every name here is invented (constitution VI): no real people, hosts or products.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


@dataclass(frozen=True)
class Turn:
    """What the model says in one call: text, then tool calls, with optional usage and a name."""

    text: str = ""
    calls: tuple[tuple[str, dict[str, Any]], ...] = ()
    tokens: tuple[int, int] | None = None  # (input tokens, output tokens), as the provider reports
    model: str | None = None  # `response_metadata["model_name"]`
    blocks: tuple[dict[str, Any], ...] = ()  # extra standard content blocks, kept after the text


def Say(text: str, *, tokens: tuple[int, int] | None = None, model: str | None = None) -> Turn:
    """A turn that is only text."""
    return Turn(text=text, tokens=tokens, model=model)


def Call(
    *calls: tuple[str, dict[str, Any]],
    text: str = "",
    tokens: tuple[int, int] | None = None,
    model: str | None = None,
) -> Turn:
    """A turn that calls tools (in this order), with optional text before the calls."""
    return Turn(text=text, calls=tuple(calls), tokens=tokens, model=model)


@dataclass
class Calls:
    """How many times the model was called (one per `_generate` or `_astream`)."""

    n: int = 0


@dataclass
class Gate:
    """Holds the model's stream after `after` pieces of text until `event` is set (SC-007).

    `reached` is set when the model is waiting; `closed` is set when the stream was closed before
    it ended (a cancel closes it), so a test can see the producer was stopped.
    """

    after: int = 3
    event: asyncio.Event = field(default_factory=asyncio.Event)
    reached: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False


def last_human(messages: Sequence[BaseMessage]) -> str:
    """The text of the newest human message (`""` when there is none)."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.text
    return ""


def since_human(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """The messages after the newest human message."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            return list(messages[i + 1 :])
    return list(messages)


def tool_results(messages: Sequence[BaseMessage]) -> list[ToolMessage]:
    """The tool messages of the current turn, in order."""
    return [m for m in since_human(messages) if isinstance(m, ToolMessage)]


def humans(messages: Sequence[BaseMessage]) -> int:
    """How many human messages the history holds."""
    return sum(isinstance(m, HumanMessage) for m in messages)


def pieces(text: str) -> Iterator[str]:
    """Words, each with the space that follows it: what a provider's tokens look like."""
    return iter(re.findall(r"\S+\s*", text))


def dangling(messages: Sequence[BaseMessage]) -> list[str]:
    """The ids of tool calls that no later `ToolMessage` answers."""
    answered: set[str] = set()
    out: list[str] = []
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            answered.add(message.tool_call_id)
        elif isinstance(message, AIMessage):
            out += [c["id"] for c in message.tool_calls if c["id"] and c["id"] not in answered]
    return out


class Scripted(BaseChatModel):
    """A chat model that says what `script(messages)` returns.

    - `streams=False`: a model that does not stream (only `_generate`); the stream of the graph then
      carries one whole message. (Not `stream`: that name shadows an attribute of the parent class.)
    - `strict=True`: refuses a history with a tool call no tool message answers, as real providers
      do (spec finding 6).
    - `gate`: see `Gate`.
    - `calls`: a `Calls` the test passes in; the model never keeps a counter of its own.
    """

    script: Any
    streams: bool = True
    strict: bool = False
    gate: Any = None
    calls: Any = None

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Scripted:
        """`create_agent` binds its tools; the script decides the calls, so nothing is bound."""
        return self

    def _should_stream(self, *args: Any, **kwargs: Any) -> bool:
        return self.streams and super()._should_stream(*args, **kwargs)

    # -- what to say -------------------------------------------------------------------------

    def _turn(self, messages: list[BaseMessage]) -> Turn:
        if self.calls is not None:
            self.calls.n += 1
        if self.strict:
            open_calls = dangling(messages)
            if open_calls:
                raise ValueError(f"an assistant message with tool calls must be answered: {open_calls}")
        turn = self.script(messages)
        assert isinstance(turn, Turn), f"the script returned {turn!r}, not a Turn"
        return turn

    @staticmethod
    def _tool_calls(turn: Turn, messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
        """Call ids are a function of the history, so the same history gives the same ids."""
        turn_no = sum(isinstance(m, AIMessage) for m in messages)
        return [
            {"name": name, "args": dict(args), "id": f"call-{turn_no}-{i}", "type": "tool_call"}
            for i, (name, args) in enumerate(turn.calls)
        ]

    @staticmethod
    def _usage(turn: Turn) -> dict[str, Any] | None:
        if turn.tokens is None:
            return None
        i, o = turn.tokens
        return {"input_tokens": i, "output_tokens": o, "total_tokens": i + o}

    @staticmethod
    def _meta(turn: Turn) -> dict[str, Any]:
        return {"model_name": turn.model} if turn.model else {}

    # -- the two ways a model answers ---------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        turn = self._turn(messages)
        content: Any = turn.text
        if turn.blocks:
            content = ([{"type": "text", "text": turn.text}] if turn.text else []) + list(turn.blocks)
        message = AIMessage(
            content=content,
            tool_calls=self._tool_calls(turn, messages),
            usage_metadata=self._usage(turn),  # type: ignore[arg-type]
            response_metadata=self._meta(turn),
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, None, **kwargs)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        turn = self._turn(messages)
        gate = self.gate
        finished = False
        waited = gate is None
        try:
            sent = 0
            for piece in pieces(turn.text):
                if not waited and sent == gate.after:
                    waited = True
                    gate.reached.set()
                    await gate.event.wait()
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
                sent += 1
            if not waited:
                waited = True
                gate.reached.set()
                await gate.event.wait()
            chunks = [
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(self._tool_calls(turn, messages))
            ]
            content: Any = list(turn.blocks) if turn.blocks else ""
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=content,
                    tool_call_chunks=chunks,  # type: ignore[arg-type]
                    usage_metadata=self._usage(turn),  # type: ignore[arg-type]
                    response_metadata=self._meta(turn),
                    chunk_position="last",
                )
            )
            finished = True
        finally:
            if gate is not None and not finished:
                gate.closed = True


Script = Callable[[list[BaseMessage]], Turn]
