# Contract: the public API of `ext_r2c.core`

Everything below is importable from `ext_r2c.core`. Names not listed here are private
(underscore modules). Types are in [../data-model.md](../data-model.md).

## Modules

```
python/src/ext_r2c/core/
  __init__.py      re-exports the names below
  _schemas.py      packaged schema loader, format checker, $ref scan
  models.py        the six wire models and their parts; parse, to_json, Unknown, InvalidObject
  forms.py         answer_schema, mcp_form, answer_from_mcp, edit_offered, NotAskableOverMcp
  check.py         check_answer, decision, check_size, Limits, Problem
  fallback.py      fallback_text
  events.py        run events and Content
  source.py        AgentSource, RunContext, RunInput, CardInfo, CardSkill, Driver, Run, thread_id
  tools.py         ToolSpec, tool_from_function, InvalidArguments
```

`ext_r2c/__init__.py` keeps `URI`, `MCP_KEY`, `STANDARD_VERSION` and `__version__`, and adds no
core name in this spec.

## Schemas

```python
def schema(kind: str) -> dict[str, Any]               # a deep copy of the packaged schema
def schema_kinds() -> tuple[str, ...]                 # the six kinds
```

Loaded with `importlib.resources` from `ext_r2c/schema/v1/`, once, with no network access.

## Models

```python
def parse(obj: Mapping[str, Any]) -> R2CObject | Unknown        # raises InvalidObject
def to_json(model: R2CObject) -> dict[str, Any]                 # raises InvalidObject
class InvalidObject(ValueError):
    errors: list[tuple[str, str]]                              # (json pointer, message)
class Unknown:  kind: str; data: dict[str, Any]
```

Each model also has `Model.parse(obj)`, which raises `InvalidObject` when the object is another
kind.

## Forms

```python
def answer_schema(question: Question) -> dict[str, Any]
def edit_offered(approval: Approval) -> bool                   # False on an external $ref
def mcp_form(request: Question | Approval) -> McpForm          # raises NotAskableOverMcp
def answer_from_mcp(request: Question | Approval, action: Literal["accept", "decline", "cancel"],
                    content: Mapping[str, Any] | None) -> Answer
```

The exact mappings are in [forms.md](forms.md).

## Answer checking

```python
def check_answer(answer: Answer, request: Question | Approval, *,
                 now: datetime | None = None, limits: Limits = Limits()) -> list[Problem]
def decision(answer: Answer, request: Approval, *, now: datetime | None = None
             ) -> Literal["allow", "edit", "deny"]
def check_size(*, text: str | None = None, raw_base64: str | None = None,
               limits: Limits = Limits()) -> Problem | None
```

`now` defaults to the current UTC time. `check_answer` runs in this order and returns every
problem it finds:

1. size: the answer's JSON is larger than `message_bytes` gives `too_large` and stops;
   - the answer fails its own schema (`value` with `declined`, or none with `answered`) gives
     `invalid_answer` and stops;
2. `wrong_id`;
3. `expired`;
4. `caller_on_approval`;
5. a declined answer stops here;
6. a question's value against `answer_schema` gives `invalid_value`, one problem per field;
7. an approval's value:
   - against `approval_value` gives `invalid_value`;
   - a decision that is not offered gives `not_offered`, and so does `edit` when `edit_offered`
     is false;
   - `args` against `args_schema` give `invalid_args`, one problem per argument.

`decision` returns `deny` for a declined or expired answer. It fails closed: an answer for
another `id`, from the `caller`, or with a decision that is not offered also gives `deny`.

## Fallback text

```python
def fallback_text(obj: Question | Approval | Activity) -> str
```

The format is in [forms.md](forms.md#fallback-text).

## Run events, sources, driver

```python
class AgentSource(Protocol):
    card: CardInfo
    pause: Literal["checkpoint", "live"]
    def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]: ...
    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]: ...  # checkpoint

class Driver:
    def __init__(self, source: AgentSource) -> None
    def start(self, thread_id: str, input: RunInput) -> Run
    def resume(self, thread_id: str, request: Question | Approval, answer: Answer) -> Run

class Run:                                   # async iterator of RunEvent
    pending: Question | Approval | None
    async def deliver(self, answer: Answer) -> None   # to the pending Ask; ValueError otherwise
    async def cancel(self) -> None

def thread_id(door: Literal["a2a", "mcp"], owner: str, context_id: str) -> str
```

- `Driver.resume` is for a run this driver does not hold, as after a restart. While the driver
  still holds the run, `Run.deliver` is the way to answer it.
- A source that is not one of the two styles is refused by `Driver(...)` with `TypeError`.

## Tools

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    call: Callable[[Mapping[str, Any]], Awaitable[Any]]

def tool_from_function(fn: Callable[..., Any], *, name: str | None = None,
                       description: str | None = None) -> ToolSpec
class InvalidArguments(ValueError):  problems: list[Problem]
```

## Stability

v0.x: these names may change between minor versions until the first outside adopter. The doors
(003, 004) and the bridge (005) use only the names above.
