"""Plain text for a request or an activity, for a client that does not read R2C (R2C-CORE-4,
FR-019, research R13). The format is in ``contracts/forms.md`` "Fallback text" of spec 002."""

from __future__ import annotations

from .forms import edit_offered
from .models import Activity, Approval, Field, Question

__all__ = ["fallback_text"]


def _hint(field: Field) -> str:
    labels = ", ".join(o.label for o in field.options or [])
    parts = []
    if field.type == "one":
        parts.append(f"one of: {labels}, or another" if field.other else f"one of: {labels}")
    elif field.type == "many":
        parts.append(f"one or more of: {labels}, or others" if field.other else f"one or more of: {labels}")
    elif field.type == "number":
        parts.append("a number")
    elif field.type == "bool":
        parts.append("yes/no")
    if not field.required:
        parts.append("optional")
    return "; ".join(parts)


def _question(q: Question) -> list[str]:
    lines = [e.message for e in q.errors or []]
    lines.append(f"{q.origin.name} asks: {q.title}" if q.origin else q.title)
    if q.description:
        lines.append(q.description)
    for f in q.fields:
        hint = _hint(f)
        lines.append(f"- {f.header}: {f.text} ({hint})" if hint else f"- {f.header}: {f.text}")
    return lines


def _approval(a: Approval) -> list[str]:
    role = a.answer_by.approver_role
    lines = [f"Approval needed ({role}): {a.title}" if role else f"Approval needed: {a.title}"]
    if a.description:
        lines.append(a.description)
    offered = [d for d in a.decisions if d != "edit" or edit_offered(a)]
    reply = f"Reply with one of: {' | '.join(offered)}"
    lines.append(f"{reply} (expires {a.expires_at})" if a.expires_at else reply)
    return lines


def fallback_text(obj: Question | Approval | Activity) -> str:
    """The plain text of ``obj``; never empty."""
    if isinstance(obj, Question):
        return "\n".join(_question(obj))
    if isinstance(obj, Approval):
        return "\n".join(_approval(obj))
    if isinstance(obj, Activity):
        return f"{obj.label}: {obj.detail}" if obj.detail else obj.label
    raise TypeError(f"no fallback text for {type(obj).__name__}")
