# Contract: changes to the shared `AgentSource` suite (D3)

Phase 1 of [plan.md](../plan.md). The suite is `python/tests/agent_source_suite.py` (spec 002),
called from `python/tests/test_agent_source.py` with the two fakes of `tests/fake_sources.py`. D3
changes it in three places so that a real, streaming source passes it; **every source, the two fakes
included, passes it as changed**. The 002 contract file gets a dated note (phase 10).

Why a change is needed at all: the suite was written against fakes that emit one reply chunk in a
fixed order (`FULL`), and it asks every source for `answers`, `fail_after_ask` and `double_ask`. A
streaming graph emits many chunks and its tool activity comes where the graph runs it; and a correct
bridge asks one request at a time, so it cannot produce the second ask S9 needs.

## (a) The sequence checks compare a shape

| | Before | After |
|---|---|---|
| helper | `name(event)` gives a short name per event | the same, plus `shape(events)`: drop `activity`, merge consecutive `reply` into one `reply`; the other names stay, and the order of `ask`, `answer`, `usage` and the terminal event is exact |
| `FULL` | `["activity", "ask", "answer", "reply", "activity", "usage", "done"]` | `SHAPE = ["ask", "answer", "reply", "usage", "done"]` |
| reply text | `_replies(events)` is a list of chunk texts, compared as a list | `reply_text(events)` is the chunks joined, compared as one string; the last reply chunk carries `last=True` (new check, FR-008; the fakes' one chunk gets `last=True`, see below) |

Per scenario:

| Scenario | Before | After (shape) |
|---|---|---|
| S1 question answered | `FULL`, `["Got: October stock"]` | `SHAPE`, text `"Got: October stock"` |
| S2 approval allowed | `FULL`, `["Done"]` | `SHAPE`, text `"Done"` |
| S3 denied with a reason | `FULL`, `["Not done: Not before Monday."]`, `answers == [DENY]` | `SHAPE`, the same text, `answers == [DENY]` |
| S4 declined | `FULL`, `["Declined"]` | `SHAPE`, text `"Declined"` |
| S5 cancelled while paused | `["activity", "ask", "error:cancelled"]`, no resume (checkpoint) | `["ask", "error:cancelled"]`, `answers == []` for a checkpoint source |
| S6 delivered with nothing pending | `FULL` | `SHAPE` |
| S7 restart | checkpoint: `["answer", "reply", "activity", "usage", "done"]`; live: `["error:lost"]` | checkpoint: `["answer", "reply", "usage", "done"]`; live: `["error:lost"]` (unchanged) |
| S8 raises after the ask | `["activity", "ask", "answer", "error:failed"]`, a reason | `["ask", "answer", "error:failed"]`, a non-empty reason |
| S9 second ask before the answer | `["activity", "ask", "error:protocol"]`, `run.pending is None` | `["ask", "error:protocol"]`, `run.pending is None` |
| S10 one terminal event, last | `check_sequence` | unchanged |

The fakes need one test-only change: `tests/fake_sources.py` builds its single reply chunk as
`ReplyChunk(text)`, so `last` is `False`; it becomes `ReplyChunk(text, last=True)`, which is what a
source that ends a turn does (FR-008, spec 003's rule). Nothing else in them changes: dropping
`activity` from the shape only loosens what they already do, and that they still emit their activity
is checked in their own tests.

## (b) The graph under test asks with the suite's own payloads

The real source's graph is built so no answer in the suite changes. A scripted model reads the last
human message:
- `"Write the report"`: calls the tool `ask_question`, whose body is `interrupt(<a valid R2C question
  with id "q-1", one text field "title">)`; after the answer the tool returns `"Got: <title>"`, or
  `"Declined"` when the resume value is `None`;
- `"Write the report and publish it"`: calls `ask_approval`, whose body is `interrupt(<a valid R2C
  approval with id "ap-1", decisions allow, deny, subject tool_call>)`; it returns `"Done"` on
  `allow` and `"Not done: <reason>"` on `deny`;
- after a tool result, the model replies with that result's text, streamed in pieces, once.

The suite's ids (`q-1`, `ap-1`) are what the request ids are for a valid hand-written request
(pause-mapping row 4 and 5), and the resume values are the answer's `value` mapping, so
`TITLE`, `ALLOW`, `DENY` and `DECLINED` are used as they are.

## (c) A test-only wrapper around the real source

`tests/langgraph_suite_source.py`: `SuiteSource(store, **options)` wraps a `LangGraphAgent` over a
graph built for the options, and:
- records every answer that reaches `resume` in `answers` (S3, S5);
- exposes `pause`, `card`;
- with `fail_after_ask=True` builds the graph whose tool raises after its `interrupt()` returns (S8);
- with `double_ask=True` yields a second `Ask` right after the first one the agent yields, which is
  what the suite's driver guard (S9) is for; a correct bridge cannot produce it by itself;
- a "restart" (S7) makes a new graph and a new `LangGraphAgent` over the **same** checkpointer
  (`store`): an `InMemorySaver` the test keeps, or the SQLite file of the restart tests.

`tests/test_agent_source.py` gains the real source beside the two fakes: the same parametrised
scenarios, through the same `Driver`.

## Mutation check

A scratch run, recorded in `research.md` like the earlier phases: a list of mutants, each a source or a
suite line changed so that one thing is wrong; the changed suite must fail every one.

| Mutant | Killed by |
|---|---|
| the source drops its reply | S1 to S4 |
| the reply comes before the answer | S1 |
| `usage` is missing | S1 to S4 |
| `usage` comes before the reply | S1 |
| a second `usage` at the pause | S1 |
| the source yields `Done` itself | S10 / the protocol check |
| the reply's last chunk has `last=False` | S1 (new `last` check) |
| the source calls `resume` on a cancelled run | S5 |
| the source never records the answer it got | S3 |
| the source swallows its exception after the ask | S8 |
| the wrapper never yields the second ask | S9 |
| the shape check merged non-consecutive replies | a streamed-reply test of S1 |
| the shape check dropped `usage` | S1 |

The recorded result is "N of N mutants died"; a survivor is either fixed or named as equivalent.
