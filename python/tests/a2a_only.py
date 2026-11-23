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

    _remote_check()
    print("a2a only: ok")


def _remote_check() -> None:
    """An A2A-only `Remote` serves its card with nothing of MCP loaded, and the MCP door names its
    extra (spec 007, SC-010)."""
    import asyncio
    import json

    from a2a.server.tasks import InMemoryTaskStore
    from ext_r2c import URI, A2AOptions, Remote

    source = Hello()
    remote = Remote(expose=["a2a"], agent=source, url="https://remote.example.com",
                    a2a=A2AOptions(task_store=InMemoryTaskStore()))
    app = remote.app()

    async def asked() -> tuple[tuple[int, bytes], tuple[int, bytes]]:
        async with app.router.lifespan_context(app):
            return await _ask(app, "GET", "/.well-known/agent-card.json"), await _ask(app, "POST", "/mcp", b"{}")

    (status, body), (mcp_status, _) = asyncio.run(asked())
    card = json.loads(body)
    assert status == 200 and card["name"] == "hello", (status, body)
    assert [e["uri"] for e in card["capabilities"]["extensions"]] == [URI], card["capabilities"]
    assert card["supportedInterfaces"][0]["url"] == "https://remote.example.com/", card["supportedInterfaces"]
    assert mcp_status == 404, f"the MCP path answered {mcp_status} on an A2A-only Remote"
    loaded = sorted({m.split(".")[0] for m in sys.modules} & set(OTHERS))
    assert not loaded, f"an A2A-only Remote loaded {loaded}"

    try:
        Remote(expose=["mcp"], card=source.card, mcp_tool=True, agent=source)
    except ImportError as error:
        assert "ext-r2c[mcp]" in str(error), str(error)
    else:
        raise AssertionError("the MCP door built without the [mcp] extra")


async def _ask(app, method: str, path: str, body: bytes = b"") -> tuple[int, bytes]:  # type: ignore[no-untyped-def]
    """One HTTP request to an ASGI app with no client library: the status and the body."""
    waiting = [{"type": "http.request", "body": body, "more_body": False}]
    sent: list[dict] = []  # type: ignore[type-arg]

    async def receive():  # type: ignore[no-untyped-def]
        return waiting.pop() if waiting else {"type": "http.disconnect"}

    async def send(message) -> None:  # type: ignore[no-untyped-def]
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8000"), (b"content-type", b"application/json")],
        "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 50000),
    }
    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


if __name__ == "__main__":
    main()
