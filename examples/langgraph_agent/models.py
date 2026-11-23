"""The chat model of the example, and a stand-in for it.

With `R2C_EXAMPLE_MODEL` set (a LangChain `provider:model` name, for a provider whose package and key
you have), both agents use that model. Without it they use `Scripted`, so the example runs offline:
a model whose every answer is a function of the conversation so far.

The scripts below stand in for what a model would decide. They are not a pattern to copy: the code to
read is in `planner.py` and `reporter.py`, where the graphs, the tools and the one wrapping line are.
All names are invented.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

MONTH = re.compile(r"\d{4}-\d{2}")


class Scripted(BaseChatModel):
    """A chat model that says what `script(messages)` returns, an `AIMessage`."""

    script: Callable[[Sequence[BaseMessage]], AIMessage]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Scripted:
        return self  # the script decides the calls, so nothing needs binding

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self.script(messages))])


def chat_model(script: Callable[[Sequence[BaseMessage]], AIMessage]) -> BaseChatModel:
    """The model named by `R2C_EXAMPLE_MODEL`, or the scripted stand-in."""
    name = os.environ.get("R2C_EXAMPLE_MODEL")
    return init_chat_model(name) if name else Scripted(script=script)


# --- what the scripts read -----------------------------------------------------------------------


def said(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata={"input_tokens": 40, "output_tokens": 12, "total_tokens": 52},
                     response_metadata={"model_name": "scripted"})


def calls(name: str, **arguments: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": f"call-{name}", "type": "tool_call"}],
                     usage_metadata={"input_tokens": 40, "output_tokens": 8, "total_tokens": 48},
                     response_metadata={"model_name": "scripted"})


def asked(messages: Sequence[BaseMessage]) -> str:
    """The text of the newest human message."""
    return next((m.text for m in reversed(messages) if isinstance(m, HumanMessage)), "")


def results(messages: Sequence[BaseMessage]) -> dict[str, ToolMessage]:
    """What the tools answered since the newest human message, by tool name."""
    found: dict[str, ToolMessage] = {}
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, ToolMessage) and message.name:
            found.setdefault(message.name, message)
    return found


# --- the two scripts -----------------------------------------------------------------------------


def planner_script(messages: Sequence[BaseMessage]) -> AIMessage:
    done = results(messages)
    if "ask_reporter" in done:
        return said(f"The reporter says: {done['ask_reporter'].content}")
    month = MONTH.search(asked(messages))
    return calls("ask_reporter", request="Write the stock report and publish it.",
                 month=month.group() if month else "2026-10")


def reporter_script(messages: Sequence[BaseMessage]) -> AIMessage:
    done = results(messages)
    month = MONTH.search(asked(messages))
    if "ask_month" not in done and not month:
        return calls("ask_month")
    month_text = month.group() if month else str(done["ask_month"].content)
    if "get_holdings" not in done:
        return calls("get_holdings")
    report = f"Stock report for {month_text}: {str(done['get_holdings'].content).replace(chr(10), ', ')}."
    if "publish_page" in done:
        page = done["publish_page"]
        return said(f"{report} Not published: the approval was refused." if page.status == "error" else f"{report} Published.")
    if "publish" in asked(messages).lower():
        return calls("publish_page", slug=f"reports/{month_text}")
    return said(f"{report} Not published.")
