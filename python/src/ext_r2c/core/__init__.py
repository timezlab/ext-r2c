"""The protocol-free core of R2C: models, forms, answer checking, run events, sources, tools.

Every door (A2A, MCP) and every bridge builds on this package, which depends only on
``pydantic`` and ``jsonschema`` and imports no door and no bridge. See ``ARCHITECTURE.md``.
"""

from ._schemas import schema, schema_kinds
from .check import Limits, Problem, check_answer, check_size, decision
from .fallback import fallback_text
from .forms import McpForm, NotAskableOverMcp, answer_from_mcp, answer_schema, edit_offered, mcp_form
from .models import (
    Activity,
    Answer,
    AnswerBy,
    AnsweredBy,
    Approval,
    ApproverBy,
    ArtifactMeta,
    Cost,
    ErrorItem,
    Field,
    InvalidObject,
    Option,
    Origin,
    Question,
    R2CObject,
    Request,
    Subject,
    Unknown,
    Usage,
    parse,
    to_json,
)

__all__ = [
    "Activity",
    "Answer",
    "AnswerBy",
    "AnsweredBy",
    "Approval",
    "ApproverBy",
    "ArtifactMeta",
    "Cost",
    "ErrorItem",
    "Field",
    "InvalidObject",
    "Limits",
    "McpForm",
    "NotAskableOverMcp",
    "Option",
    "Origin",
    "Problem",
    "Question",
    "R2CObject",
    "Request",
    "Subject",
    "Unknown",
    "Usage",
    "answer_from_mcp",
    "answer_schema",
    "check_answer",
    "check_size",
    "decision",
    "edit_offered",
    "fallback_text",
    "mcp_form",
    "parse",
    "schema",
    "schema_kinds",
    "to_json",
]
