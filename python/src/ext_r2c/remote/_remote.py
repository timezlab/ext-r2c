"""``Remote``: one adapter that serves an existing remote over A2A, MCP or both (spec 007)."""

from __future__ import annotations

from typing import Any

__all__ = ["Remote"]


class Remote:
    """Serves an existing remote over A2A, MCP or both, from one ASGI app."""

    def __init__(self, **configuration: Any) -> None:
        raise NotImplementedError("Remote is not built yet (spec 007, phase 3)")
