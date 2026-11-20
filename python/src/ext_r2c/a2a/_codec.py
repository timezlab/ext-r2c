"""R2C objects to and from A2A Parts and Artifacts, and what a stored Task says (spec 003).

- An **R2C Part** has ``data`` = the R2C object and ``metadata`` = ``{URI: {}}`` (R2C-CORE-1).
- An **artifact's** R2C metadata is ``{URI: <artifact object>}``.
- A protobuf ``Value`` holds every number as a double, so the codec turns integral floats back
  into ints before it parses (research R12).
- The pending request and the last usage are read from the task itself, never kept aside
  (research R2).

Private: the door and the client use it; the public names are re-exported by ``ext_r2c.a2a``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from a2a.types import Artifact, Message, Part, Role, Task, TaskArtifactUpdateEvent, TaskState
from google.protobuf import json_format, struct_pb2

from .. import URI
from ..core import (
    Answer,
    AnsweredBy,
    Approval,
    ArtifactMeta,
    BytesContent,
    Content,
    InvalidObject,
    Question,
    R2CObject,
    TextContent,
    Unknown,
    UrlContent,
    Usage,
    parse,
    to_json,
)

__all__ = [
    "Invalid",
    "answer_text",
    "artifact_update",
    "content_to_part",
    "last_usage",
    "part_to_content",
    "pending_request",
    "r2c_part",
    "read_artifact",
    "read_part",
    "read_parts",
    "text_answer",
]

_OCTETS = "application/octet-stream"


@dataclass(frozen=True)
class Invalid:
    """An R2C Part whose object breaks its schema: a receiver skips it (R2C-CORE-5)."""

    kind: str | None
    errors: tuple[tuple[str, str], ...]


def _ints(value: Any) -> Any:
    """``value`` with every integral float turned into an int, at any depth (research R12)."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _ints(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_ints(v) for v in value]
    return value


def _struct(obj: dict[str, Any]) -> struct_pb2.Struct:
    out = struct_pb2.Struct()
    out.update(obj)
    return out


def _value(obj: Any) -> struct_pb2.Value:
    return json_format.ParseDict(obj, struct_pb2.Value())


# --- R2C Parts ----------------------------------------------------------------------------------


def r2c_part(obj: R2CObject) -> Part:
    """The A2A Part that carries ``obj`` (checked against its schema on the way out)."""
    return Part(data=_value(to_json(obj)), metadata=_struct({URI: {}}))


def read_part(part: Part) -> R2CObject | Unknown | Invalid | None:
    """The R2C object in ``part``; ``Unknown`` for an unknown kind, ``Invalid`` for a broken
    object, ``None`` when ``part`` is not an R2C Part."""
    if not part.HasField("data") or URI not in part.metadata:
        return None
    if json_format.MessageToDict(part.metadata)[URI] != {}:
        return None
    data = _ints(json_format.MessageToDict(part.data))
    if not isinstance(data, dict):
        return None
    try:
        return parse(data)
    except InvalidObject as e:
        kind = data.get("kind")
        return Invalid(kind if isinstance(kind, str) else None, tuple(e.errors))


def read_parts(parts: Iterable[Part]) -> Iterator[R2CObject | Unknown | Invalid]:
    """The R2C objects of ``parts``, in order; Parts that are not R2C are left out."""
    for part in parts:
        obj = read_part(part)
        if obj is not None:
            yield obj


# --- Content and artifacts ----------------------------------------------------------------------


def content_to_part(content: Content) -> Part:
    """``TextContent`` → ``text``, ``BytesContent`` → ``raw``, ``UrlContent`` → ``url``."""
    if isinstance(content, TextContent):
        if content.media_type == "text/plain":
            return Part(text=content.text)
        return Part(text=content.text, media_type=content.media_type)
    if isinstance(content, BytesContent):
        return Part(raw=content.data, media_type=content.media_type, filename=content.name or "")
    return Part(url=content.url, media_type=content.media_type, filename=content.name or "")


def part_to_content(part: Part) -> Content | None:
    """The core content of a ``text``, ``raw`` or ``url`` Part; ``None`` for a ``data`` Part."""
    which = part.WhichOneof("content")
    if which == "text":
        return TextContent(part.text, part.media_type or "text/plain")
    if which == "raw":
        return BytesContent(part.raw, part.media_type or _OCTETS, part.filename or None)
    if which == "url":
        return UrlContent(part.url, part.media_type or _OCTETS, part.filename or None)
    return None


def artifact_update(
    task_id: str,
    context_id: str,
    artifact_id: str,
    contents: Sequence[Content],
    *,
    meta: ArtifactMeta | None,
    name: str | None = None,
    description: str | None = None,
    append: bool = False,
    last_chunk: bool = False,
) -> TaskArtifactUpdateEvent:
    """An artifact update; with ``meta``, the artifact carries ``{URI: meta}`` (R2C-A2A-5)."""
    artifact = Artifact(
        artifact_id=artifact_id,
        name=name or "",
        description=description or "",
        parts=[content_to_part(c) for c in contents],
    )
    if meta is not None:
        artifact.metadata.CopyFrom(_struct({URI: to_json(meta)}))
    return TaskArtifactUpdateEvent(
        task_id=task_id, context_id=context_id, artifact=artifact, append=append, last_chunk=last_chunk
    )


def read_artifact(artifact: Artifact) -> tuple[ArtifactMeta | None, tuple[Content, ...]]:
    """The artifact's R2C metadata (``None`` when absent, of another kind, or broken) and its
    parts as core content. A ``data`` Part has no core content and is left out."""
    meta: ArtifactMeta | None = None
    if URI in artifact.metadata:
        marked = _ints(json_format.MessageToDict(artifact.metadata)[URI])
        try:
            found = parse(marked) if isinstance(marked, dict) else None
        except InvalidObject:
            found = None
        meta = found if isinstance(found, ArtifactMeta) else None
    contents = tuple(c for c in (part_to_content(p) for p in artifact.parts) if c is not None)
    return meta, contents


# --- What a stored task says (research R2) ------------------------------------------------------


def _agent_messages(task: Task) -> Iterator[Message]:
    """The task's agent messages, newest first: the status message, then the history."""
    if task.status.HasField("message"):
        yield task.status.message
    for message in reversed(task.history):
        yield message


def _newest(task: Task, kind: type[Any] | tuple[type[Any], ...]) -> Any:
    for message in _agent_messages(task):
        if message.role != Role.ROLE_AGENT:
            continue
        for obj in reversed(list(read_parts(message.parts))):
            if isinstance(obj, kind):
                return obj
    return None


def pending_request(task: Task) -> Question | Approval | None:
    """The request the task waits for: the newest R2C request an agent message carries, only
    while the task is at input-required."""
    if task.status.state != TaskState.TASK_STATE_INPUT_REQUIRED:
        return None
    found: Question | Approval | None = _newest(task, (Question, Approval))
    return found


def last_usage(task: Task) -> Usage | None:
    """The newest usage an agent message of the task carries (R2C-USAGE-2)."""
    found: Usage | None = _newest(task, Usage)
    return found


# --- Answers in words ---------------------------------------------------------------------------


def _show(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(_show(v) for v in value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def answer_text(answer: Answer, request: Question | Approval) -> str:
    """The words that go with an answer Part (R2C-A2A-2, contracts/wire-mapping.md)."""
    if answer.outcome == "declined":
        return "Declined"
    value = answer.value or {}
    if isinstance(request, Approval):
        decision = value.get("decision")
        if decision == "allow":
            return "Allow"
        if decision == "deny":
            reason = value.get("reason")
            return f"Deny: {reason}" if reason else "Deny"
        if decision == "edit":
            return "Edited: " + json.dumps(value.get("args", {}), ensure_ascii=False)
        return str(decision)
    shown = [f"{f.header}: {_show(value[f.key])}" for f in request.fields if f.key in value]
    return "; ".join(shown) or "Answered"


def text_answer(request: Question | Approval, text: str) -> Answer | None:
    """A text-only reply as the answer, where R2C-ASK-8 allows it (research R9): a question
    with exactly one field of type ``one`` or ``text``. ``None`` otherwise."""
    if not isinstance(request, Question) or len(request.fields) != 1:
        return None
    field, said = request.fields[0], text.strip()
    if not said:
        return None
    if field.type == "one":
        value = next((o.label for o in field.options or [] if o.label.casefold() == said.casefold()), None)
        if value is None:
            if not field.other:
                return None
            value = said
    elif field.type == "text":
        value = said
    else:
        return None
    return Answer(
        id=request.id, outcome="answered", answered_by=AnsweredBy(role="person"), value={field.key: value}
    )
