"""Typed models of the six R2C kinds, judged by the packaged schemas (research R1, R2).

Every model is open: unknown fields are kept and written back. Defaults (``other``,
``required``) are read through the model but never written. ``kind`` is always written.
Parsing checks the object against its schema before building the model; ``to_json`` checks
what it writes, so code cannot emit an object its schema rejects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

from ._schemas import errors, kind_validator

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
    "Option",
    "Origin",
    "Question",
    "R2CObject",
    "Request",
    "Subject",
    "Unknown",
    "Usage",
    "parse",
    "to_json",
]

Number: TypeAlias = int | float


class InvalidObject(ValueError):
    """An R2C object its schema (or a rule the schema cannot express) rejects."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        self.errors = errors
        shown = "; ".join(f"{p or '/'}: {m}" for p, m in errors[:5])
        more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
        super().__init__(f"invalid R2C object: {shown}{more}")


@dataclass(frozen=True)
class Unknown:
    """An object of a kind this package does not know; a receiver ignores it (R2C-CORE-5)."""

    kind: str
    data: dict[str, Any] = field(repr=False)


class _Open(BaseModel):
    """Open object: unknown fields are kept (R2C-CORE-6)."""

    model_config = ConfigDict(extra="allow", protected_namespaces=())


# --- Shared parts ------------------------------------------------------------------------------


class Option(_Open):
    label: str
    description: str | None = None


class Field(_Open):
    key: str
    header: str
    text: str
    type: Literal["one", "many", "text", "number", "bool"]
    options: list[Option] | None = None
    other: bool = True
    required: bool = True


class AnswerBy(_Open):
    role: Literal["person", "caller"]


class ApproverBy(_Open):
    role: Literal["person", "approver"]
    approver_role: str | None = None


class AnsweredBy(_Open):
    role: Literal["person", "approver", "policy", "caller"]
    label: str | None = None


class Origin(_Open):
    name: str
    url: str


class ErrorItem(_Open):
    key: str | None = None
    message: str


class Subject(_Open):
    type: str
    name: str
    args: dict[str, Any] | None = None
    args_schema: dict[str, Any] | None = None
    target: str | None = None


class Cost(_Open):
    amount: Number
    currency: str


# --- The six kinds ------------------------------------------------------------------------------


class _Kind(_Open):
    _kind: ClassVar[str]

    def model_post_init(self, context: Any, /) -> None:
        # `kind` has a default, so an object built in code would not dump it with exclude_unset.
        self.__pydantic_fields_set__.add("kind")

    @classmethod
    def parse(cls, obj: Mapping[str, Any]) -> Any:
        """Check ``obj`` against this kind's schema and build the model; ``InvalidObject`` otherwise."""
        if not isinstance(obj, Mapping):
            raise InvalidObject([("", "an R2C object is a JSON object")])
        if obj.get("kind") != cls._kind:
            raise InvalidObject([("/kind", f"expected kind {cls._kind!r}, got {obj.get('kind')!r}")])
        found = errors(kind_validator(cls._kind), obj) or cls._rule_errors(obj)
        if found:
            raise InvalidObject(found)
        return cls.model_validate(dict(obj))

    @classmethod
    def _rule_errors(cls, obj: Mapping[str, Any]) -> list[tuple[str, str]]:
        """Rules of the standard a schema cannot check on one object."""
        return []


class _Request(_Kind):
    id: str
    title: str
    description: str | None = None
    expires_at: str | None = None
    origin: Origin | None = None
    errors: list[ErrorItem] | None = None

    def expires(self) -> datetime | None:
        """``expires_at`` as an aware ``datetime``, or ``None``."""
        if self.expires_at is None:
            return None
        return datetime.fromisoformat(self.expires_at.upper().replace("Z", "+00:00"))


class Question(_Request):
    _kind: ClassVar[str] = "question"
    kind: Literal["question"] = "question"
    answer_by: AnswerBy
    fields: list[Field]

    @classmethod
    def _rule_errors(cls, obj: Mapping[str, Any]) -> list[tuple[str, str]]:
        # R2C-QUESTION-4: keys unique within a question, labels unique within a field.
        out: list[tuple[str, str]] = []
        keys: set[str] = set()
        for i, f in enumerate(obj["fields"]):
            if f["key"] in keys:
                out.append((f"/fields/{i}/key", f"field key {f['key']!r} is used twice"))
            keys.add(f["key"])
            labels: set[str] = set()
            for j, o in enumerate(f.get("options") or []):
                if o["label"] in labels:
                    out.append((f"/fields/{i}/options/{j}/label", f"option label {o['label']!r} is used twice"))
                labels.add(o["label"])
        return out


class Approval(_Request):
    _kind: ClassVar[str] = "approval"
    kind: Literal["approval"] = "approval"
    answer_by: ApproverBy
    subject: Subject
    decisions: list[Literal["allow", "edit", "deny"]]


class Answer(_Kind):
    _kind: ClassVar[str] = "answer"
    kind: Literal["answer"] = "answer"
    id: str
    outcome: Literal["answered", "declined"]
    answered_by: AnsweredBy
    value: dict[str, Any] | None = None
    note: str | None = None


class ArtifactMeta(_Kind):
    _kind: ClassVar[str] = "artifact"
    kind: Literal["artifact"] = "artifact"
    presentation: Literal["file", "inline", "live"]
    state: Literal["open", "closed"] | None = None
    response: Literal[True] | None = None


class Activity(_Kind):
    _kind: ClassVar[str] = "activity"
    kind: Literal["activity"] = "activity"
    id: str
    type: str
    label: str
    state: Literal["running", "done", "failed"] | None = None
    name: str | None = None
    args: dict[str, Any] | None = None
    detail: str | None = None
    duration_ms: int | None = None
    parent_id: str | None = None
    delta: str | None = None


class Usage(_Kind):
    _kind: ClassVar[str] = "usage"
    kind: Literal["usage"] = "usage"
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int | None = None
    cost: Cost | None = None
    model: str | None = None


Request: TypeAlias = Question | Approval
R2CObject: TypeAlias = Question | Approval | Answer | ArtifactMeta | Activity | Usage

_MODELS: dict[str, type[_Kind]] = {
    m._kind: m for m in (Question, Approval, Answer, ArtifactMeta, Activity, Usage)
}


def parse(obj: Mapping[str, Any]) -> R2CObject | Unknown:
    """The model of an R2C object, ``Unknown`` for a kind this package does not know.

    Raises ``InvalidObject`` when ``kind`` is missing or the object breaks its schema.
    """
    if not isinstance(obj, Mapping):
        raise InvalidObject([("", "an R2C object is a JSON object")])
    kind = obj.get("kind")
    if "kind" not in obj:
        raise InvalidObject([("", "'kind' is a required property")])
    if not isinstance(kind, str):
        raise InvalidObject([("/kind", "'kind' must be a string")])
    model = _MODELS.get(kind)
    if model is None:
        return Unknown(kind, dict(obj))
    parsed: R2CObject = model.parse(obj)
    return parsed


def to_json(model: R2CObject) -> dict[str, Any]:
    """The JSON value of a model, checked against its schema; ``InvalidObject`` if it breaks it."""
    data: dict[str, Any] = model.model_dump(mode="json", exclude_unset=True)
    found = errors(kind_validator(model._kind), data) or type(model)._rule_errors(data)
    if found:
        raise InvalidObject(found)
    return data
