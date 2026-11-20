"""The pieces of the A2A example replay (spec 003 contracts/replay.md). Test helper only.

- `load(name)` reads an example; `turns(example)` splits it into what the caller does and what
  the remote answers.
- `script_from_example(example)` is the converter of door mode: a `Script`, or `NotScriptable`.
- `ScriptedSource(script, pause)` plays a script as a checkpoint or a live source.
- `TurnExecutor(turns)` is the wire executor of client mode: one `execute` call per turn.
- `normalise(node, names)` puts an event in the form both sides are compared in.
- `sample_answer(request)` is a valid answer for a request no client step answers.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import Message, Part, Role, StreamResponse, Task, TaskState, TaskStatus, TaskStatusUpdateEvent
from ext_r2c import URI
from ext_r2c.a2a._codec import part_to_content, read_artifact, read_part
from ext_r2c.core import (
    Activity,
    ActivityEvent,
    Answer,
    AnsweredBy,
    Approval,
    ArtifactEvent,
    ArtifactMeta,
    Ask,
    Question,
    R2CObject,
    ReplyChunk,
    RunContext,
    RunEvent,
    RunInput,
    TextContent,
    Unknown,
    Usage,
    UsageEvent,
    parse,
)
from google.protobuf import json_format

from fake_sources import CARD
from r2c_check import standard_path

EXAMPLES = standard_path() / "examples" / "a2a"
DEFAULT_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)  # before every expiry in the examples
ACTIVITY_TYPES = frozenset({"tool", "step", "reasoning"})
_PAUSED = "TASK_STATE_INPUT_REQUIRED"
_ENDS = frozenset({"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"})


# --- Examples and turns -----------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    side: str  # "client" or "remote"
    type: str
    body: dict[str, Any]
    headers: dict[str, str]

    @property
    def status(self) -> dict[str, Any] | None:
        update = self.body.get("statusUpdate")
        return update["status"] if update else None

    @property
    def state(self) -> str | None:
        if self.type == "Task":
            return str(self.body["status"]["state"])
        if "task" in self.body:
            return str(self.body["task"]["status"]["state"])
        status = self.status
        return str(status["state"]) if status else None


@dataclass(frozen=True)
class Example:
    name: str
    steps: tuple[Step, ...]

    @property
    def activated(self) -> bool:
        """Whether the caller asks for R2C: the file carries R2C somewhere, in a body or in an
        `A2A-Extensions` header (`follow-up-context.json` shows it only in headers)."""
        return URI in json.dumps([s.body for s in self.steps]) or any(
            URI in s.headers.get("A2A-Extensions", "") for s in self.steps)


def names() -> list[str]:
    return sorted(p.name for p in EXAMPLES.glob("*.json"))


def load(name: str) -> Example:
    data = json.loads((EXAMPLES / name).read_text("utf-8"))
    return Example(name, tuple(Step(s["from"], s["type"], s["body"], s.get("headers", {})) for s in data["steps"]))


START = "start"  # the harness sends "Start." to open the task
SAMPLE = "sample"  # the harness answers the pending request with `sample_answer`


@dataclass
class Turn:
    """What the caller does (`START`, `SAMPLE` or a client step), then the remote steps it gets."""

    action: str | Step
    expect: list[Step] = field(default_factory=list)


def turns(example: Example) -> list[Turn]:
    out: list[Turn] = []
    for step in example.steps:
        if step.side == "client":
            out.append(Turn(step))
            continue
        if not out:
            out.append(Turn(START))
        elif out[-1].expect and out[-1].expect[-1].state == _PAUSED:
            out.append(Turn(SAMPLE))  # a request with no client step after it
        out[-1].expect.append(step)
    return out


def first_context(example: Example) -> str:
    """The `contextId` of the file's first remote step, for the harness's "Start." message."""
    for step in example.steps:
        found = _ids(step.body)[1]
        if found:
            return found
    return ""


def _ids(body: dict[str, Any]) -> tuple[str, str]:
    """(task id, context id) of a remote step or a client message."""
    for key in ("statusUpdate", "artifactUpdate"):
        if key in body:
            return body[key].get("taskId", ""), body[key].get("contextId", "")
    if "task" in body:
        return body["task"].get("id", ""), body["task"].get("contextId", "")
    if "message" in body:
        return body["message"].get("taskId", ""), body["message"].get("contextId", "")
    return body.get("id", ""), body.get("contextId", "")


def clock(example: Example) -> datetime:
    """The door's clock (contracts/replay.md): the first timestamp after the client's answer, or
    the file's first timestamp, or `DEFAULT_NOW`."""
    stamps: list[tuple[int, str]] = []
    answered_at: int | None = None
    for n, step in enumerate(example.steps):
        if step.side == "client" and answered_at is None and _answer_of(step) is not None:
            answered_at = n
        status = step.status
        if status and "timestamp" in status:
            stamps.append((n, status["timestamp"]))
    after = [s for n, s in stamps if answered_at is not None and n > answered_at]
    chosen = after[0] if after else (stamps[0][1] if stamps else None)
    return datetime.fromisoformat(chosen.replace("Z", "+00:00")) if chosen else DEFAULT_NOW


def _answer_of(step: Step) -> Answer | None:
    for part in step.body.get("message", {}).get("parts", []):
        if "data" in part and part["data"].get("kind") == "answer":
            found = parse(part["data"])
            return found if isinstance(found, Answer) else None
    return None


def answer_of(step: Step) -> Answer | None:
    return _answer_of(step)


# --- Objects in a step ------------------------------------------------------------------------


def objects(step: Step) -> list[R2CObject | Unknown]:
    """The R2C objects a remote step carries: status Parts, then artifact metadata."""
    event = _event(step)
    out: list[R2CObject | Unknown] = []
    status: TaskStatus | None = None
    artifacts = []
    if isinstance(event, Task):
        status, artifacts = event.status, list(event.artifacts)
    elif event.HasField("status_update"):
        status = event.status_update.status
    elif event.HasField("task"):
        status, artifacts = event.task.status, list(event.task.artifacts)
    elif event.HasField("artifact_update"):
        artifacts = [event.artifact_update.artifact]
    if status is not None:
        for part in status.message.parts:
            obj = read_part(part)
            if obj is not None:
                out.append(obj)  # type: ignore[arg-type]
    for artifact in artifacts:
        meta, _ = read_artifact(artifact)
        if meta is not None:
            out.append(meta)
    return out


def known(obj: R2CObject | Unknown) -> bool:
    """Whether a v1 client shows `obj` (R2C-CORE-5, R2C-CORE-6)."""
    if isinstance(obj, Unknown):
        return False
    return not isinstance(obj, Activity) or obj.type in ACTIVITY_TYPES


def _event(step: Step) -> Any:
    if step.type == "Task":
        return json_format.ParseDict(step.body, Task())
    return json_format.ParseDict(step.body, StreamResponse())


# --- The converter (door mode) ----------------------------------------------------------------


class NotScriptable(Exception):
    """No run of an `AgentSource` gives this file's remote steps."""


@dataclass(frozen=True)
class Script:
    steps: tuple[tuple[str, Any], ...]  # ("emit", RunEvent) | ("ask", request) | ("fail", reason)


def _placeholder_question(text: str) -> Question:
    return Question.parse({"kind": "question", "id": "q-text", "title": text or "Question", "answer_by": {"role": "person"},
                           "fields": [{"key": "value", "header": "Value", "text": text or "Value", "type": "text"}]})


def _step_activity(text: str) -> Activity:
    return Activity.parse({"kind": "activity", "id": "step-text", "type": "step", "label": text or "Working",
                           "state": "running"})


def script_from_example(example: Example) -> Script:
    out: list[tuple[str, Any]] = []
    asked: set[str] = set()
    for step in example.steps:
        if step.side == "client":
            continue
        if step.type == "AgentCard":
            raise NotScriptable("not a flow: an agent card")
        found = objects(step)
        if any(not known(o) for o in found):
            raise NotScriptable("an unknown kind or activity type: a source cannot emit it")
        event = _event(step)
        if step.type == "Task" or event.HasField("artifact_update"):
            artifacts = list(event.artifacts) if step.type == "Task" else [event.artifact_update.artifact]
            last = True if step.type == "Task" else event.artifact_update.last_chunk
            for artifact in artifacts:
                out.append(("emit", _artifact_event(artifact, last, example.activated)))
        if step.type == "Task":
            out.extend(("emit", UsageEvent(o)) for o in found if isinstance(o, Usage))
        elif event.HasField("status_update"):
            out.extend(_status_steps(step, found, asked, example.activated))
    return Script(tuple(out))


def _artifact_event(artifact: Any, last: bool, activated: bool) -> RunEvent:
    if any(p.HasField("data") for p in artifact.parts):
        raise NotScriptable("a data Part: no run event makes it")
    meta, contents = read_artifact(artifact)
    if meta is None:
        if activated:
            raise NotScriptable("an artifact without R2C metadata: no run event makes it")
        meta = ArtifactMeta(presentation="file")  # not sent without activation
    if meta.response:
        return ReplyChunk("".join(c.text for c in contents if isinstance(c, TextContent)), last=last)
    return ArtifactEvent(artifact.artifact_id, meta, contents, artifact.name or None, artifact.description or None)


def _status_steps(step: Step, found: list[Any], asked: set[str], activated: bool) -> Iterator[tuple[str, Any]]:
    state = step.state
    text = "".join(p.get("text", "") for p in (step.status or {}).get("message", {}).get("parts", []))
    yield from (("emit", UsageEvent(o)) for o in found if isinstance(o, Usage))  # held for this status
    if state == "TASK_STATE_WORKING":
        activities = [o for o in found if isinstance(o, Activity)]
        if not activities and not activated:
            activities = [_step_activity(text)]
        yield from (("emit", ActivityEvent(a)) for a in activities)
    elif state == _PAUSED:
        requests = [o for o in found if isinstance(o, (Question, Approval))]
        if not requests and not activated:
            requests = [_placeholder_question(text)]
        for request in requests:
            if request.id in asked:
                continue  # a re-ask: the door makes it
            asked.add(request.id)
            yield ("ask", request)
        # A text-only input-required status after a client step is a refusal: the door makes it.
    elif state == "TASK_STATE_FAILED":
        yield ("fail", text or "failed")
    elif state == "TASK_STATE_REJECTED":
        return  # only the door rejects (a second task, R2C-ID-2); a source never does
    elif state not in ("TASK_STATE_COMPLETED", "TASK_STATE_SUBMITTED"):
        raise NotScriptable(f"a status a source cannot end in: {state}")


class ScriptedSource:
    """Plays a `Script`, pausing as `checkpoint` or `live`. `gate`, when given, holds the run
    before its first event."""

    card = CARD

    def __init__(self, script: Script, pause: str, *, gate: asyncio.Event | None = None) -> None:
        self.script = script
        self.pause = pause
        self.gate = gate
        self.answers: list[Answer] = []
        self._at: dict[str, int] = {}

    async def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]:
        if self.gate is not None:
            await self.gate.wait()
        async for event in self._play(0, ctx):
            yield event

    async def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]:
        self.answers.append(answer)
        async for event in self._play(self._at.pop(ctx.thread_id), ctx):
            yield event

    async def _play(self, start: int, ctx: RunContext) -> AsyncIterator[RunEvent]:
        for n in range(start, len(self.script.steps)):
            what, value = self.script.steps[n]
            if what == "emit":
                yield value
            elif what == "fail":
                raise RuntimeError(value)
            elif self.pause == "live":
                self.answers.append(await ctx.ask(value))
            else:
                self._at[ctx.thread_id] = n + 1
                yield Ask(value)
                return


# --- The wire executor (client mode) ----------------------------------------------------------


class TurnExecutor(AgentExecutor):
    """Emits each turn's remote steps as they are, one `execute` call per turn, with the ids
    a2a-sdk issued. A turn that does not end paused or over is ended completed."""

    def __init__(self, expect: list[list[Step]], *, gate: asyncio.Event | None = None) -> None:
        self.expect = list(expect)
        self.gate = gate

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        steps = self.expect.pop(0) if self.expect else []
        task_id, context_id = context.task_id or "", context.context_id or ""
        if context.current_task is None:
            if steps and "task" in steps[0].body:
                task = json_format.ParseDict(steps[0].body["task"], Task())
                task.id, task.context_id = task_id, context_id
                await event_queue.enqueue_event(task)
                steps = steps[1:]
            elif context.message is not None:
                await event_queue.enqueue_event(new_task_from_user_message(context.message))
        if self.gate is not None:
            await self.gate.wait()
        state = None
        for step in steps:
            for event in _emitted(step):
                event.task_id, event.context_id = task_id, context_id
                await event_queue.enqueue_event(event)
            state = step.state or state
        if state != _PAUSED and state not in _ENDS:
            done = TaskStatusUpdateEvent(task_id=task_id, context_id=context_id, status=TaskStatus(
                state=TaskState.TASK_STATE_COMPLETED,
                message=Message(message_id="m-done", role=Role.ROLE_AGENT, parts=[Part(text="Done.")])))
            await event_queue.enqueue_event(done)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def _emitted(step: Step) -> list[Any]:
    """The a2a-sdk events of a remote step; a `Task` step (a `GetTask` result) becomes its
    artifact updates and its last status."""
    event = _event(step)
    if step.type == "Task":
        from a2a.types.a2a_pb2 import TaskArtifactUpdateEvent

        out: list[Any] = [TaskArtifactUpdateEvent(artifact=a, last_chunk=True) for a in event.artifacts]
        return [*out, TaskStatusUpdateEvent(status=event.status)]
    which = event.WhichOneof("payload")
    return [getattr(event, which)] if which in ("status_update", "artifact_update") else []


# --- Normalising ------------------------------------------------------------------------------

_ID_KEYS = {"taskId": "task", "contextId": "context", "artifactId": "artifact"}
_PRESENT = "<present>"


@dataclass
class Names:
    """Ids renamed by first sight, per kind, so two sides compare without sharing ids."""

    seen: dict[tuple[str, str], str] = field(default_factory=dict)

    def __call__(self, kind: str, value: str) -> str:
        if not value:
            return value
        key = (kind, value)
        if key not in self.seen:
            count = sum(1 for k, _ in self.seen if k == kind) + 1
            self.seen[key] = f"{kind}-{count}"
        return self.seen[key]


def canonical(body: dict[str, Any], kind: type[Any] = StreamResponse) -> dict[str, Any]:
    """`body` through protobuf and back: defaults dropped, numbers as a2a-sdk writes them."""
    return json_format.MessageToDict(json_format.ParseDict(body, kind()))


def normalise(node: Any, names: Names, *, path: tuple[str, ...] = ()) -> Any:
    """Contracts/replay.md "Normalising": ids renamed, `timestamp` and `messageId` dropped,
    integral floats as ints, text Parts and error messages by presence only. What a2a-sdk adds
    and the files leave out is dropped too: a `Task`'s `history`, and the ids a status message
    repeats from its update."""
    if isinstance(node, dict):
        if "data" in node and "metadata" in node and URI in node.get("metadata", {}):
            return {"data": _words(_ints(node["data"])), "metadata": node["metadata"]}
        if "text" in node and not isinstance(node["text"], dict):
            return {**{k: v for k, v in node.items() if k != "text"}, "text": _PRESENT}
        out: dict[str, Any] = {}
        in_status = path[-2:] == ("status", "message")
        for key, value in node.items():
            if key in ("timestamp", "messageId", "history"):
                continue
            if in_status and key in ("taskId", "contextId"):
                continue
            if key in _ID_KEYS and isinstance(value, str):
                out[key] = names(_ID_KEYS[key], value)
            elif key == "id" and path and path[-1] == "task" and isinstance(value, str):
                out[key] = names("task", value)
            else:
                out[key] = normalise(value, names, path=(*path, key))
        return out
    if isinstance(node, list):
        return [normalise(v, names, path=path) for v in node]
    return _ints(node)


def _ints(node: Any) -> Any:
    if isinstance(node, float) and node.is_integer():
        return int(node)
    if isinstance(node, dict):
        return {k: _ints(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_ints(v) for v in node]
    return node


def _words(data: Any) -> Any:
    """An R2C object with the words of its `errors` by presence only."""
    if isinstance(data, dict) and isinstance(data.get("errors"), list):
        errors = [{**e, "message": _PRESENT} if isinstance(e, dict) and "message" in e else e for e in data["errors"]]
        return {**data, "errors": errors}
    return data


def remote_form(step: Step, names: Names) -> Any:
    """A file's remote step in the compared form."""
    if step.type == "Task":
        return normalise(canonical(step.body, Task), names, path=("task",))
    return normalise(canonical(step.body), names)


def wire_form(event: Any, names: Names) -> Any:
    if isinstance(event, Task):
        return normalise(json_format.MessageToDict(event), names, path=("task",))
    return normalise(json_format.MessageToDict(event), names)


def message_form(body: dict[str, Any]) -> Any:
    """A client message in the compared form, without its ids (they are checked apart)."""
    message = canonical({"message": body}, StreamResponse)["message"]
    message.pop("taskId", None)
    message.pop("contextId", None)
    return normalise(message, Names())


# --- A valid answer ---------------------------------------------------------------------------


def sample_answer(request: Question | Approval) -> Answer:
    """A valid answer made by the test: the first option, a sample text."""
    if isinstance(request, Approval):
        decision = request.decisions[0]
        value: dict[str, Any] = {"decision": decision}
        if decision == "edit":
            value["args"] = request.subject.args or {}
        return Answer(id=request.id, outcome="answered", answered_by=AnsweredBy(role=request.answer_by.role),
                      value=value)
    value = {}
    for f in request.fields:
        first = f.options[0].label if f.options else "Sample"
        value[f.key] = {"one": first, "many": [first], "text": "Sample", "number": 1, "bool": True}[f.type]
    return Answer(id=request.id, outcome="answered", answered_by=AnsweredBy(role="person"), value=value)


def plain_text(step: Step) -> str:
    return "".join(p.get("text", "") for p in step.body.get("message", {}).get("parts", []))


def content_of(part: Part) -> Any:
    return part_to_content(part)
