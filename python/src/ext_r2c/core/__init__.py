"""The protocol-free core of R2C: models, forms, answer checking, run events, sources, tools.

Every door (A2A, MCP) and every bridge builds on this package, which depends only on
``pydantic`` and ``jsonschema`` and imports no door and no bridge. See ``ARCHITECTURE.md``.
"""

from ._schemas import schema, schema_kinds
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
    "McpForm",
    "NotAskableOverMcp",
    "Option",
    "Origin",
    "Question",
    "R2CObject",
    "Request",
    "Subject",
    "Unknown",
    "Usage",
    "answer_from_mcp",
    "answer_schema",
    "edit_offered",
    "mcp_form",
    "parse",
    "schema",
    "schema_kinds",
    "to_json",
]
