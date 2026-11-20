"""The MCP door (spec 004): R2C over the MCP Python SDK, for the 2026-07-28 protocol.

Install with the ``[mcp]`` extra. ``mcp_server(name, R2CExtension(tools=[...]))`` serves
``ToolSpec``s and ``SourceTool``s with R2C (contracts/mcp-api.md).
"""

from __future__ import annotations

from ._state import MemoryLedger, RoundLedger
from .activation import form_supported, is_active, owner_of
from .extension import R2CExtension
from .server import mcp_server
from .source_tool import SourceTool
from .tools import Approve, ToolOutput

__all__ = [
    "Approve",
    "MemoryLedger",
    "R2CExtension",
    "RoundLedger",
    "SourceTool",
    "ToolOutput",
    "form_supported",
    "is_active",
    "mcp_server",
    "owner_of",
]
