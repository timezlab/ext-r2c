"""The LangGraph bridge (spec 006): serve a compiled LangGraph graph (a LangChain agent) over R2C.

Install with the ``[langgraph]`` extra. This package imports ``ext_r2c.core`` and the packages
the extra brings (``langgraph``, ``langchain_core``): no door, no other bridge. The graph being
wrapped is never changed; see specs/006-langgraph-bridge/contracts/langgraph-api.md.
"""

from __future__ import annotations

try:
    import langchain_core  # noqa: F401
    import langgraph  # noqa: F401
except ImportError as exc:  # pragma: no cover - exercised by a subprocess test
    raise ImportError(
        'The LangGraph bridge needs the [langgraph] extra: pip install "ext-r2c[langgraph]"'
    ) from exc

from .agent import LangGraphAgent

__all__ = ["LangGraphAgent"]
