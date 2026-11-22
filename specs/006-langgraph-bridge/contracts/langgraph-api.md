# Contract: the Python API of `ext_r2c.bridges.langgraph`

Phase 1 of [plan.md](../plan.md). Public names are exported from `ext_r2c.bridges.langgraph`;
everything in a module with a leading underscore is private. Needs the `[langgraph]` extra. Types
are the shape, not the final source. The behaviour of a pause, row by row, is in
[pause-mapping.md](pause-mapping.md).

## The core's one addition

```python
# ext_r2c.core (module source.py, exported from ext_r2c.core)
class PauseLost(Exception):
    """A checkpoint source raises it in `resume` when it holds no stopping point for the answer:
    the pause was lost. The driver ends the run `Error("lost", <message>)`; the doors show it as
    they show `lost` from a live source. The message is the reason the caller reads."""
```

- Added test first, with no `langgraph` installed (`tests/test_core_pause_lost.py`, and the
  core-only check).
- `Driver._pump` catches it before the general `Exception`; the reason is `str(exc)`, or "The
  paused run was lost; ask again." when it is empty.
- Nothing else in the core changes. A source that never raises it behaves exactly as before.

## Serving

```python
class LangGraphAgent:
    """A compiled LangGraph graph (a LangChain agent) as an AgentSource of the checkpoint style."""

    pause: Literal["checkpoint"] = "checkpoint"
    card: CardInfo

    def __init__(
        self,
        graph: Pregel,
        *,
        card: CardInfo | None = None,
        reasoning: bool = False,
        expose_tools: Iterable[str] = (),
    ) -> None: ...

    def run(self, input: RunInput, ctx: RunContext) -> AsyncIterator[RunEvent]: ...
    def resume(self, answer: Answer, ctx: RunContext) -> AsyncIterator[RunEvent]: ...
```

**Construction** (all keyword options; the safest value is the default, FR-026):

| Option | Default | Meaning |
|---|---|---|
| `card` | `CardInfo(graph.name, "A LangGraph agent served through R2C.", "0.0.0")` | the agent's card; nothing is read from the graph's prompts or tools |
| `reasoning` | `False` | send reasoning text as `reasoning` activity deltas |
| `expose_tools` | none | tool names whose `args` and result `detail` may appear on the timeline |

**Refused at construction** (nothing is started; each message names the missing piece):

| When | Error |
|---|---|
| not a compiled graph (including an uncompiled `StateGraph`) | `TypeError` ("call `.compile(checkpointer=...)`" for a `StateGraph`) |
| no checkpointer, or one that is not a `BaseCheckpointSaver` | `ValueError` |
| the input schema has no `messages` (D1) | `ValueError` |
| `expose_tools` holds a non-string | `TypeError` |

An in-memory checkpointer works and gives one `UserWarning` per construction: a pause will not
survive a restart (D11).

**`run(input, ctx)`**
- thread: `ctx.thread_id`, as given (FR-005);
- if the thread has a pending middleware approval, it is settled first (D9, FR-007);
- the input becomes one human message (FR-006), or, when it answers an `input_required` question,
  is that answer;
- yields events in the order [pause-mapping.md](pause-mapping.md) fixes, ends right after an `Ask`
  (FR-014), or at the end of the turn after `UsageEvent`.

**`resume(answer, ctx)`**
- rebuilds the pending set from the checkpointer and matches `answer.id`; no match raises
  `PauseLost` before the graph is touched (FR-023);
- checks the answer against what the graph accepts; a refusal raises `ValueError` with the readable
  problems, the graph is not touched and the pause stays pending (FR-020);
- a `batched` answer is recorded; the next call is asked until the batch is complete (FR-019);
- otherwise resumes the graph by interrupt id with the decision or value of the mapping.

**What `run` and `resume` never do:** yield `AnswerEvent`, `Done` or `Error` (the driver does); yield
anything after an `Ask`; answer an approval; call a model; read, convert or drop an input part; write
to the checkpointer except by `aupdate_state` (D9) and the graph's own run.

**Concurrency:** one run per thread at a time (the doors keep one unfinished task per context). The
agent is safe to share across threads; its only shared state is the bounded batch map.

**Cancellation:** the door cancelling a run throws `CancelledError` into the generator; the leg's
`finally` cancels the producer and awaits it, which closes the graph's stream. A paused thread is not
resumed (S5).

## Tools

```python
def tool_from_langchain(tool: BaseTool) -> ToolSpec: ...
def tools_from_langchain(tools: Iterable[BaseTool]) -> list[ToolSpec]: ...
```

| Part | Rule (R16) |
|---|---|
| `name`, `description` | the tool's |
| `input_schema` | the model-visible JSON Schema (`tool_call_schema`), also when `args_schema` is a plain JSON Schema; `title` removed |
| `call(args)` | checks `args` against the schema with `jsonschema`; a breach raises `InvalidArguments` with one `Problem("invalid_args", key, message)` per breaking key and the tool does not run; then awaits `tool.ainvoke(dict(args))`. A sync tool runs off the event loop |
| refused at conversion | an input with an injected argument (`InjectedState`, `InjectedStore`, `ToolRuntime`, `InjectedToolCallId`, `InjectedToolArg`): `TypeError` naming the tool and the argument |
| a list | converted in order; one refusal refuses the whole list (FR-025) |

*Phase 9 (2026-11-22), three additions the table did not say:* `input_schema` has no top-level `description`
either (LangChain puts the tool's description there for a pydantic schema as well); `call` also validates with a
pydantic `args_schema` of the tool itself (the model-visible schema leaves out `extra="forbid"` and validators) and
turns its `ValidationError` into the same `InvalidArguments`; a tool with no `args_schema` and no schema to read
(a legacy single-string `Tool`) is refused at conversion with a `TypeError`. Research R16 has the reasons.

## Imports and packaging

- `ext_r2c.bridges.langgraph` imports `ext_r2c.core`, `langgraph`, `langchain_core`, `jsonschema` and
  `pydantic` only. It imports no door and no other bridge. No other module of `ext_r2c` imports it
  (FR-004).
- Importing it without the extra raises `ImportError("... pip install \"ext-r2c[langgraph]\"")`.
- `pip install "ext-r2c[langgraph]"` brings `langchain>=1.4.6,<2`, `langchain-core>=1.6.10,<2` and
  `langgraph>=1.2.14,<2` and **no checkpointer**; the owner brings theirs. A durable checkpointer
  with async support (for example `langgraph-checkpoint-sqlite`'s `AsyncSqliteSaver`) is what makes
  a pause survive a restart.

## What the README must say (FR-029)

- the one-line wrap, and the three things that are checked at wrap time;
- a durable async checkpointer is needed for a pause to survive a restart; the in-memory one warns;
- `batched` keeps a batch in progress in memory only; use `per_call` where a restart in the middle
  matters;
- one chunk of reply latency (the last chunk is held back to carry `last`);
- `reasoning` and `expose_tools` are off by default, and why;
- an exception's text from a provider reaches the caller as it is;
- a pydantic structured reply in the checkpoint needs the owner's `allowed_msgpack_modules`;
- the queue between the graph and the door is unbounded.
