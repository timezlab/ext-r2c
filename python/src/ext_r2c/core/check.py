"""Checking an answer against the request it answers (FR-014 to FR-018, research R6).

Every door and the example tests use the same check. It returns problems a person can read, each
with a machine ``code`` the door uses to re-ask or refuse, and never follows a ``$ref`` that leaves
its document (R2C-SAFETY-7).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache
from typing import Any, Literal

from jsonschema import Draft202012Validator, ValidationError

from ._schemas import kind_validator, schema, subschema_validator, validator
from .forms import answer_schema, edit_offered
from .models import Answer, Approval, ErrorItem, Question

__all__ = ["Limits", "Problem", "check_answer", "check_size", "decision"]

Code = Literal[
    "too_large", "invalid_answer", "wrong_id", "caller_on_approval", "expired",
    "invalid_value", "not_offered", "invalid_args",
]


@dataclass(frozen=True)
class Problem:
    """One reason an answer is not acceptable."""

    code: Code
    key: str | None
    message: str

    def as_error_item(self) -> ErrorItem:
        """The entry of a re-ask's ``errors`` (R2C-ASK-6)."""
        return ErrorItem(key=self.key, message=self.message) if self.key else ErrorItem(message=self.message)


@dataclass(frozen=True)
class Limits:
    """Size limits (R2C-SAFETY-4, R2C-SAFETY-5): the standard's by default, a caller's own if set."""

    message_bytes: int = 5 * 2**20
    file_bytes: int = 50 * 2**20


# --- Messages a person can read ----------------------------------------------------------------

_TYPE_NAMES = {
    "string": "text", "number": "a number", "integer": "a whole number", "boolean": "yes or no",
    "array": "a list", "object": "a group of values", "null": "empty",
}


def _show(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return value if isinstance(value, str) else json.dumps(value)


def _size(n: int) -> str:
    return f"{n // 2**20} MiB" if n % 2**20 == 0 else f"{n} bytes"


def _message(err: ValidationError) -> str:
    kw, val = err.validator, err.validator_value
    if kw == "type":
        names = val if isinstance(val, list) else [val]
        return f"Must be {' or '.join(_TYPE_NAMES.get(n, n) for n in names)}."
    if kw == "enum":
        return f"Must be one of: {', '.join(_show(v) for v in val)}."
    if kw == "const":
        return f"Must be {_show(val)}."
    if kw == "minLength":
        return "Cannot be empty." if val == 1 else f"Must be at least {val} characters long."
    if kw == "maxLength":
        return f"Must be at most {val} characters long."
    if kw == "minItems":
        return "Choose at least one." if val == 1 else f"Choose at least {val}."
    if kw == "maxItems":
        return f"Choose at most {val}."
    if kw == "uniqueItems":
        return "Each choice may appear only once."
    if kw == "minimum":
        return f"Must be at least {_show(val)}."
    if kw == "maximum":
        return f"Must be at most {_show(val)}."
    if kw == "exclusiveMinimum":
        return f"Must be more than {_show(val)}."
    if kw == "exclusiveMaximum":
        return f"Must be less than {_show(val)}."
    if kw == "required":
        return "This is needed."
    return "This value is not accepted."


def _keyed(v: Draft202012Validator, instance: Any) -> Iterator[tuple[str | None, str]]:
    """(key, message) per error: the key is the first step of the path, or each missing name."""
    for err in v.iter_errors(instance):
        path = list(err.absolute_path)
        if path:
            yield str(path[0]), _message(err)
        elif err.validator == "required" and isinstance(err.instance, dict):
            for name in err.validator_value:
                if name not in err.instance:
                    yield name, _message(err)
        else:
            yield None, _message(err)


def _one_per_key(code: Code, found: Iterable[tuple[str | None, str]], order: Sequence[str]) -> list[Problem]:
    seen: dict[str | None, Problem] = {}
    for key, message in found:
        seen.setdefault(key, Problem(code, key, message))
    rank = {k: i for i, k in enumerate(order)}
    return sorted(seen.values(), key=lambda p: rank.get(p.key, len(rank)) if p.key is not None else -1)


# --- The check ---------------------------------------------------------------------------------


@cache
def _approval_value_validator() -> Draft202012Validator:
    return subschema_validator(schema("answer"), "approval_value")


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


def _expired(request: Question | Approval, now: datetime | None) -> bool:
    expiry = request.expires()
    return expiry is not None and _now(now) >= expiry


def _wire(answer: Answer) -> dict[str, Any]:
    return answer.model_dump(mode="json", exclude_unset=True)


def check_size(*, text: str | None = None, raw_base64: str | None = None, limits: Limits = Limits()) -> Problem | None:
    """``too_large`` when inline content is above ``limits.message_bytes``: ``text`` in UTF-8 bytes,
    ``raw_base64`` by its decoded size, computed without decoding."""
    sizes = []
    if text is not None:
        sizes.append(len(text.encode("utf-8")))
    if raw_base64 is not None:
        compact = "".join(raw_base64.split())
        sizes.append(len(compact) * 3 // 4 - (len(compact) - len(compact.rstrip("="))))
    if any(n > limits.message_bytes for n in sizes):
        return Problem("too_large", None, f"The content is larger than {_size(limits.message_bytes)}.")
    return None


def check_answer(
    answer: Answer, request: Question | Approval, *, now: datetime | None = None, limits: Limits = Limits()
) -> list[Problem]:
    """Every problem of ``answer`` against ``request``; an empty list means it is acceptable."""
    wire = _wire(answer)
    size = len(json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > limits.message_bytes:
        return [Problem("too_large", None, f"The answer is larger than {_size(limits.message_bytes)}.")]
    if next(kind_validator("answer").iter_errors(wire), None) is not None:
        return [Problem("invalid_answer", None, "The answer is not well formed.")]

    problems: list[Problem] = []
    if answer.id != request.id:
        problems.append(Problem("wrong_id", None, "This answer is for another request."))
    if _expired(request, now):
        problems.append(Problem("expired", None, "The request has expired."))
    is_approval = isinstance(request, Approval)
    if is_approval and answer.answered_by.role == "caller":
        problems.append(Problem("caller_on_approval", None, "An approval cannot be answered by the caller."))
    if answer.outcome == "declined":
        return problems

    value = answer.value or {}
    if isinstance(request, Question):
        keys = [f.key for f in request.fields]
        return problems + _one_per_key("invalid_value", _keyed(validator(answer_schema(request)), value), keys)
    return problems + _approval_problems(value, request)


def _approval_problems(value: dict[str, Any], request: Approval) -> list[Problem]:
    invalid = _one_per_key("invalid_value", _keyed(_approval_value_validator(), value), ["decision", "args", "reason"])
    if invalid:
        return invalid
    chosen = value["decision"]
    if chosen not in request.decisions or (chosen == "edit" and not edit_offered(request)):
        return [Problem("not_offered", "decision", f"{chosen.capitalize()} is not offered.")]
    args_schema = request.subject.args_schema
    if chosen != "edit" or args_schema is None:
        return []
    props = args_schema.get("properties")
    order = list(props) if isinstance(props, dict) else []
    try:
        Draft202012Validator.check_schema(args_schema)
        return _one_per_key("invalid_args", _keyed(validator(args_schema), value["args"]), order)
    except Exception:  # a broken args_schema, or a local $ref that does not resolve: fail closed
        return [Problem("invalid_args", None, "The arguments could not be checked.")]


def decision(
    answer: Answer, request: Approval, *, now: datetime | None = None
) -> Literal["allow", "edit", "deny"]:
    """The effective decision (FR-018): the one sent when answered, ``deny`` when declined or
    expired. It fails closed: an answer for another id, from the caller, or with a decision that
    is not offered also gives ``deny``."""
    if not isinstance(request, Approval):
        raise TypeError("decision() takes an approval")
    if (
        answer.id != request.id
        or answer.outcome != "answered"
        or answer.answered_by.role == "caller"
        or _expired(request, now)
    ):
        return "deny"
    chosen = (answer.value or {}).get("decision")
    if chosen not in request.decisions or (chosen == "edit" and not edit_offered(request)):
        return "deny"
    return chosen  # type: ignore[no-any-return]
