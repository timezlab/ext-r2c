"""The MCP door (spec 004): R2C over the MCP Python SDK, for the 2026-07-28 protocol.

Install with the ``[mcp]`` extra. ``mcp_server(name, R2CExtension(tools=[...]))`` serves
``ToolSpec``s and ``SourceTool``s with R2C; ``R2CClient`` is the caller's side
(contracts/mcp-api.md).
"""

from __future__ import annotations

from ._codec import mcp_response
from ._state import MemoryLedger, RoundLedger
from .activation import form_supported, is_active, owner_of
from .client import (
    ActivityItem,
    AnswerRejected,
    ArtifactItem,
    Item,
    Link,
    ProgressItem,
    R2CClient,
    ReplyItem,
    RequestItem,
    ResultItem,
    TooLarge,
    UsageItem,
)
from .extension import R2CExtension
from .server import mcp_server
from .skills import (
    DirectoryEntry,
    LeftOut,
    LoadedSkill,
    Refused,
    SkillContent,
    SkillFileRef,
    SkillInfo,
    SkillItem,
    SkillListing,
    SkillRefused,
    SkillsClient,
    SkillsError,
    SkillsExtension,
)
from .source_tool import SourceTool
from .tools import Approve, ToolOutput

__all__ = [
    "ActivityItem",
    "AnswerRejected",
    "Approve",
    "ArtifactItem",
    "DirectoryEntry",
    "Item",
    "LeftOut",
    "Link",
    "LoadedSkill",
    "MemoryLedger",
    "ProgressItem",
    "R2CClient",
    "R2CExtension",
    "Refused",
    "ReplyItem",
    "RequestItem",
    "ResultItem",
    "RoundLedger",
    "SkillContent",
    "SkillFileRef",
    "SkillInfo",
    "SkillItem",
    "SkillListing",
    "SkillRefused",
    "SkillsClient",
    "SkillsError",
    "SkillsExtension",
    "SourceTool",
    "TooLarge",
    "ToolOutput",
    "UsageItem",
    "form_supported",
    "is_active",
    "mcp_response",
    "mcp_server",
    "owner_of",
]
