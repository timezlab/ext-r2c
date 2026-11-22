"""MCP Skills (SEP-2640, extension ``io.modelcontextprotocol/skills``), served from folders and read
back with verification (spec 005).

**Beta.** Written against the beta revision of the extension read on 2026-11-21, on base protocol
2026-07-28. The extension may still change in ways that break this package; the pinned facts it
leans on are in ``tests/test_skills_spike.py``.

This package imports nothing of ``ext_r2c`` (a test enforces it), so it can be lifted out whole.
Install with the ``[mcp]`` extra.
"""

from __future__ import annotations

from ._catalogue import SkillInfo
from .client import (
    DirectoryEntry,
    LoadedSkill,
    Refused,
    SkillContent,
    SkillFileRef,
    SkillItem,
    SkillListing,
    SkillRefused,
    SkillsClient,
)
from .extension import SkillsExtension

__all__ = [
    "DirectoryEntry",
    "LoadedSkill",
    "Refused",
    "SkillContent",
    "SkillFileRef",
    "SkillInfo",
    "SkillItem",
    "SkillListing",
    "SkillRefused",
    "SkillsClient",
    "SkillsExtension",
]
