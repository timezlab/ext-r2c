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
import base64
import json
import re
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


# What a provider keeps for itself: a signature on the reasoning and an encrypted block. A test looks
# for these two strings in every event of a run: they must never be in one (R2C-ACTIVITY-5).
SIGNATURE = "sig-9f2a-keep-private"
ENCRYPTED = "enc-71cd-keep-private"


@dataclass(frozen=True)
class Turn:
    """What the model says in one call: reasoning, then text, then tool calls, with optional usage and
    a name.

    `reasoning` is the pieces of the model's reasoning: a streaming model sends one chunk per piece,
    a model that does not stream puts them in one block. With `sealed` the reasoning also carries a
    provider's signature and an encrypted block, which are not the standard `reasoning` text.
    """

    text: str = ""
    calls: tuple[tuple[str, dict[str, Any]], ...] = ()
    tokens: tuple[int, int] | None = None  # (input tokens, output tokens), as the provider reports
    model: str | None = None  # `response_metadata["model_name"]`
    blocks: tuple[dict[str, Any], ...] = ()  # extra standard content blocks, kept after the text
    reasoning: tuple[str, ...] = ()
    sealed: bool = False


def Say(
    text: str,
    *,
    tokens: tuple[int, int] | None = None,
    model: str | None = None,
    reasoning: Sequence[str] = (),
    sealed: bool = False,
    blocks: Sequence[dict[str, Any]] = (),
) -> Turn:
    """A turn that is only text (and, when given, reasoning and extra content blocks)."""
    return Turn(
        text=text, tokens=tokens, model=model, reasoning=tuple(reasoning), sealed=sealed, blocks=tuple(blocks)
    )


def Call(
    *calls: tuple[str, dict[str, Any]],
    text: str = "",
    tokens: tuple[int, int] | None = None,
    model: str | None = None,
    reasoning: Sequence[str] = (),
    sealed: bool = False,
) -> Turn:
    """A turn that calls tools (in this order), with optional text before the calls."""
    return Turn(text=text, calls=tuple(calls), tokens=tokens, model=model, reasoning=tuple(reasoning), sealed=sealed)


def media(kind: str, data: bytes, mime: str, **extras: Any) -> dict[str, Any]:
    """A standard content block of `kind` (`image`, `audio`, `video`, `file`) that holds its bytes."""
    block: dict[str, Any] = {"type": kind, "base64": base64.b64encode(data).decode("ascii"), "mime_type": mime}
    return {**block, "extras": extras} if extras else block


def linked(kind: str, url: str, mime: str, **extras: Any) -> dict[str, Any]:
    """A standard content block of `kind` that holds a URL."""
    block: dict[str, Any] = {"type": kind, "url": url, "mime_type": mime}
    return {**block, "extras": extras} if extras else block


def hosted(kind: str, file_id: str, mime: str) -> dict[str, Any]:
    """A standard content block the provider keeps: it names the file and holds no data."""
    return {"type": kind, "file_id": file_id, "mime_type": mime}


def broken(kind: str, mime: str) -> dict[str, Any]:
    """A standard content block whose `base64` is not base64."""
    return {"type": kind, "base64": "!!! not base64 !!!", "mime_type": mime}


def vendor(value: dict[str, Any]) -> dict[str, Any]:
    """A block of a kind the standard does not have (`non_standard`)."""
    return {"type": "non_standard", "value": value}


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

    @staticmethod
    def _blocky(turn: Turn) -> bool:
        """Whether the message is a list of content blocks, not a plain string."""
        return bool(turn.blocks or turn.reasoning or turn.sealed)

    @classmethod
    def _whole(cls, turn: Turn) -> Any:
        """The content of a message that did not stream: the text alone, or a list of blocks, in the
        order a provider gives them (reasoning, text, files, the encrypted block)."""
        if not cls._blocky(turn):
            return turn.text
        out: list[dict[str, Any]] = []
        if turn.reasoning or turn.sealed:
            thought: dict[str, Any] = {"type": "reasoning", "reasoning": "".join(turn.reasoning)}
            out.append({**thought, "extras": {"signature": SIGNATURE}} if turn.sealed else thought)
        if turn.text:
            out.append({"type": "text", "text": turn.text})
        out += turn.blocks
        if turn.sealed:
            out.append(vendor({"type": "redacted_thinking", "data": ENCRYPTED}))
        return out

    # -- the two ways a model answers ---------------------------------------------------------

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        turn = self._turn(messages)
        message = AIMessage(
            content=self._whole(turn),
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
        blocky = self._blocky(turn)
        try:
            for piece in turn.reasoning:  # a provider streams its reasoning before its text
                thought: dict[str, Any] = {"type": "reasoning", "reasoning": piece, "index": 0}
                yield ChatGenerationChunk(message=AIMessageChunk(content=[thought]))  # type: ignore[list-item]
            sent = 0
            for piece in pieces(turn.text):
                if not waited and sent == gate.after:
                    waited = True
                    gate.reached.set()
                    await gate.event.wait()
                text: Any = [{"type": "text", "text": piece, "index": 1}] if blocky else piece
                yield ChatGenerationChunk(message=AIMessageChunk(content=text))
                sent += 1
            if not waited:
                waited = True
                gate.reached.set()
                await gate.event.wait()
            chunks = [
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(self._tool_calls(turn, messages))
            ]
            content: Any = ""
            if blocky:  # the files, then what the provider keeps: the signature and the encrypted block
                content = [{**block, "index": 2 + i} for i, block in enumerate(turn.blocks)]
                if turn.sealed:
                    content.insert(0, {"type": "reasoning", "reasoning": "", "extras": {"signature": SIGNATURE}, "index": 0})
                    content.append({**vendor({"type": "redacted_thinking", "data": ENCRYPTED}), "index": 2 + len(turn.blocks)})
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
