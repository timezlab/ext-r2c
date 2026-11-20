# Contract: the `AgentSource` contract suite

The suite lives in `python/tests/agent_source_suite.py`. `python/tests/test_agent_source.py`
runs it, parametrised over two fakes in `python/tests/fake_sources.py`. Later, the bridges
(005 onward) run the same suite against their own sources.

## The fakes

Both fakes run the same script. The only difference is how they pause.

1. yield `ActivityEvent(step "Preparing", running)`;
2. ask the scripted request: a `question` (one `text` field), or an `approval` (a `tool_call`
   with `allow | deny`), chosen by the input text;
3. on the answer:
   - an answered question: yield `ReplyChunk("Got: <value>")`;
   - an `allow`: yield `ReplyChunk("Done")`;
   - a `deny`: yield `ReplyChunk("Not done: <reason>")`;
   - a declined answer: yield `ReplyChunk("Declined")`;
4. yield `ActivityEvent(step "Preparing", done)`, then `UsageEvent` (`output_tokens: 3`).

The two pause styles:
- **Checkpoint fake:** yields `Ask` and ends. It keeps the pending step in a dict that the test
  passes in, which stands in for the framework's checkpointer. A second instance sharing that
  dict acts as the same remote after a restart. `resume` reads the step from the dict.
- **Live fake:** `answer = await ctx.ask(request)` inside `run`.

## Scenarios (every one runs against both fakes)

| # | Scenario | Expected events (after the driver adds its own) |
|---|---|---|
| S1 | question answered | activity, ask, answer, reply "Got: …", activity, usage, done |
| S2 | approval allowed | activity, ask, answer, reply "Done", activity, usage, done |
| S3 | approval denied with a reason | …, reply "Not done: <reason>", …, done; the source saw the reason |
| S4 | declined | …, reply "Declined", …, done |
| S5 | cancelled while paused | activity, ask, error `cancelled`; the source is not resumed (checkpoint) or saw a declined answer (live) |
| S6 | delivered with nothing pending | `Run.deliver` raises `ValueError`; the run is unchanged |
| S7 | restart | a new driver, given the pending request and the answer, gives answer, reply, activity, usage, done for a checkpoint source, and one error `lost` for a live source |
| S8 | the source raises after the ask | …, answer, error `failed`; no done |
| S9 | a source yields a second `Ask` before the first is answered | error `protocol` |
| S10 | sequence | in every scenario: exactly one terminal event, and nothing after it |

S7 is the one scenario whose result depends on the style. The style is the source's own
declaration (`pause`), so the test reads `source.pause` and no fake is special-cased. Every
other scenario expects the same events from both fakes.
