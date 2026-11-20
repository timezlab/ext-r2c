"""Run in a venv that holds the wheel with the `[a2a]` extra only (no dev group): the A2A door
works there and loads no other door or bridge (constitution VIII).

Not collected by pytest (no `test_` prefix). CI runs it as:
    python -I tests/a2a_only.py
It prints `a2a only: ok` or fails with an assertion.
"""

from __future__ import annotations

import importlib.util
import sys

OTHERS = ("mcp", "langchain", "langgraph")


class Hello:
    """A trivial source: one reply, then done."""

    pause = "live"

    def __init__(self) -> None:
        from ext_r2c.core import CardInfo, CardSkill

        skill = CardSkill(id="hello", name="Hello", description="Says hello.", tags=("greeting",))
        self.card = CardInfo(name="hello", description="Says hello.", version="0.0.1", skills=(skill,))

    async def run(self, input, ctx):  # type: ignore[no-untyped-def]
        from ext_r2c.core import ReplyChunk

        yield ReplyChunk("Hello.", last=True)

    def resume(self, answer, ctx):  # type: ignore[no-untyped-def]
        raise NotImplementedError


def main() -> None:
    import ext_r2c.a2a  # noqa: F401

    assert importlib.util.find_spec("pytest") is None, "pytest is installed: this is not an a2a-only venv"
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(OTHERS))
    assert not loaded, f"importing the A2A door loaded {loaded}"

    from ext_r2c import URI
    from ext_r2c.a2a import SourceExecutor, a2a_app, agent_card
    from google.protobuf import json_format

    source = Hello()
    card = agent_card(source.card, "https://remote.example.com/")
    app = a2a_app(SourceExecutor(source), card)
    uris = [e["uri"] for e in json_format.MessageToDict(card)["capabilities"]["extensions"]]
    assert uris == [URI], f"the card lists {uris}"
    assert app.state.request_handler is not None

    print("a2a only: ok")


if __name__ == "__main__":
    main()
