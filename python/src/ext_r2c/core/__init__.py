"""The protocol-free core of R2C: models, forms, answer checking, run events, sources, tools.

Every door (A2A, MCP) and every bridge builds on this package, which depends only on
``pydantic`` and ``jsonschema`` and imports no door and no bridge. See ``ARCHITECTURE.md``.
"""

__all__: list[str] = []
