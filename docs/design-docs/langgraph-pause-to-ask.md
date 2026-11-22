# A LangGraph pause becomes an ask, and an answer goes back to the graph

**Status:** accepted, 2026-11-22. Spec: [006-langgraph-bridge](../../specs/006-langgraph-bridge/spec.md).
The row-by-row contract is [pause-mapping.md](../../specs/006-langgraph-bridge/contracts/pause-mapping.md);
the evidence for each choice is in [research.md](../../specs/006-langgraph-bridge/research.md) (R3 to R14).

## Context

`LangGraphAgent` serves a compiled LangGraph graph (a LangChain agent) through the A2A and MCP doors
without a change to the graph. A graph stops for a person in five different ways, and the doors know
only two things: an `Ask` (a `question` or an `approval`) and, later, an `Answer`.

The five stops are `HumanInTheLoopMiddleware` in `per_call` mode (one interrupt per gated call, each
with its own id), the same middleware in `batched` mode (one interrupt that holds every gated call and
wants every decision in one resume), a hand-written `interrupt(value)`, two or more of those pending at
once, and a turn that simply ends with a structured reply whose `status` is `input_required` (nothing
is paused; the graph is done and wants the caller to say more).

Three facts about the installed packages shape everything below (spec, "What the installed packages
do"):

- **Finding 2.** A `batched` resume with the wrong number of decisions, or a decision the call does not
  allow, raises `ValueError` **and leaves the thread unable to continue**: a later, correct resume fails
  the same way. A `per_call` refusal leaves the thread intact.
- **Finding 6.** A new human message on a thread that waits for an approval starts the graph over and
  drops the pause, and the model then sees a tool call with no tool message after it, which real
  providers reject.
- **The stream is not the truth.** A pause arrives in the stream as an `__interrupt__` update, but only
  the checkpointer still holds it after the stream, a restart, or a pruned thread, and only its ids
  are the same after a restart.

The open questions are how a pause is read, what the caller is asked, what the graph gets back, what
happens to an answer the graph would refuse, what a new message does to a pending approval, how a tool
that is `running` is told from one that waits for approval, and how `input_required` is told.

## Decision

1. **Pauses are read from the checkpointer, never from the stream** (FR-014, R8). After a leg ends,
   `aget_state(config).interrupts` is classified by shape. Request ids come from the graph's own
   interrupt ids (`lg-<interrupt id>`, `lg-<interrupt id>-<n>` for the n-th call of a batch, the
   object's own id for a hand-written valid R2C request, `lg-ir-<last AI message id>` for
   `input_required`), so the same pause has the same ids after a restart (FR-015).
2. **One ask at a time, and the leg ends right after it** (FR-014). Tool approvals come in the model's
   tool-call order, then the other interrupts in the order LangGraph lists them. Each answer resumes
   only its own interrupt, by id. The bridge never yields an answer, a `Done` or an `Error`; the
   driver does.
3. **What is asked, by kind** (the table at the end has each row with its test):
   - a middleware call becomes an `Approval` for a person (`Subject(type="tool_call", ...)`, only the
     decisions the call allows, `edit` offered only when the tool's schema is found); a call that
     allows only a reply becomes a `Question` with one text field;
   - a hand-written value that is a valid R2C `question` or `approval` for a person or an approver is
     asked as it is; an approval **addressed to the caller** is asked as a `Question` for a person
     (principle V: an approval is answered by a human or a policy, never a model, so no path
     addresses one to the caller); anything else is a `Question` for a person with one text field;
   - a turn that ends `input_required` is a `Question` for the caller, and its answer is **the next
     human message of the thread, not a resume** (D10), read from the final structured reply
     LangChain's `response_format` writes.
4. **An answer is checked before the graph is touched, in this order:** the request is still pending
   (else `PauseLost`, and the driver ends the run `lost`, D2); the core's `check_answer`; the
   graph-side rules (decision allowed, `edit` takes the tool's schema). A refusal raises `ValueError`
   with the readable problems, the graph is not called and the pause stays pending, so a correct
   answer continues the thread. This is what finding 2 asks for: the bridge never sends the resume
   the middleware would choke on (FR-020, SC-005).
5. **A `batched` pause is answered one call at a time and resumed once.** Each answer is recorded in
   memory (at most 1024 records); while a call has no decision the next one is asked and the graph is
   not called; the last answer sends `{"decisions": [...]}` in position order (FR-019, D8). After a
   restart the record is gone, so the batch is asked again from its first call. A `per_call` pause
   keeps nothing in memory. A call is decided once: a second answer for a call that already has a
   decision is refused as `lost` ("already answered"), as an answered `per_call` request is, so a
   replayed or changed answer never turns an approval into a denial or back (R19 S4).
6. **A declined answer.** For a middleware approval it is `reject` (R2C-ANSWER-3), with `note` as the
   message when present, or a refusal when the call does not allow `reject` (the call must not run,
   and the pause stays). For a hand-written approval it is `{"decision": "deny"}` (with `reason` when
   there is a note): the graph reads the same shape it asked for, and the action does not happen. For
   a question of the other kinds the graph gets `None`, its own "no answer", and a respond-only call is
   refused for the same reason as above. A declined `input_required` question ends the run `done`
   with no graph call.
7. **A tool is `running` only while its body runs** (D5). `HumanInTheLoopMiddleware` in `per_call`
   mode makes the stream show a call before it pauses, so the stream cannot tell a running tool from
   one that waits; a per-run `AsyncCallbackHandler`, passed in the `config` of each call, sees
   `on_tool_start` only when a body starts. A call that waits for approval, or is denied, shows no
   activity. The handler also sees which model calls are tagged `nostream`, so their text is not the
   reply while their tokens still count. **The graph object, its nodes and its tools are never edited**
   (this is the reading of FR-001: "one install, one wrapping line"; another caller of the same graph
   sees no difference).
8. **A new message on a thread with a tool call nothing answered settles it first** (D9, FR-007,
   R11, R19 F1). One `aupdate_state` appends the tool messages that finished tasks of the unfinished
   step already produced and, for every other tool call of the AI message the thread ends on, a tool
   message with `status="error"`: "withdrawn" when a middleware approval waits for a person, "did not
   finish" when a run ended on the call (a tool body that asked and was abandoned, a tool that raised,
   a run cancelled in the middle of a tool). The model then reads the new message and sees those calls
   as rejected or failed, with the reason. An approval is written with no `as_node`; any other
   unfinished step is named as the writer (without it LangGraph routes from the model, whose own edge
   has no way back to the model, and raises). The thread's batch record is dropped. A graph that
   ended, or a pause that holds no call (a hand-written `interrupt()` in a plain node), is left as
   LangGraph leaves it. *The approved FR-007 settled only a middleware approval; its reason (the
   model must never see a call with no answer) holds for any call a run left open, and a strict model
   showed a thread that never worked again, so the scope grew (R19 F1).*
9. **One additive core change:** `PauseLost`, raised by a checkpoint source in `resume`, which the
   driver turns into `Error("lost")`. A checkpoint source could otherwise only raise, and the driver
   turns a raise into `failed`, which a caller reads as "do not retry"; `lost` means "ask again".

## Alternatives

- **Ask from the stream's `__interrupt__` part.** Rejected: it is absent after a restart, so a paused
  run could not be resumed, and its ids are not the same.
- **Pass every answer to the middleware and let it raise.** Rejected: in `batched` mode it strands the
  thread (finding 2). The bridge checks first.
- **Settle a pending approval by a rejecting resume.** Rejected (R11): it runs the graph on, so the
  model is called, ungated tools may run and the graph may pause again, and a call that allows only
  `approve` cannot be rejected. A state update writes only what the model must read.
- **Refuse the new message while a pause is pending.** Rejected (D9): a cancelled or abandoned task
  would lock its context for good.
- **Send the new message as it is.** Rejected: finding 6, real providers reject the history.
- **Keep the partial batch in the graph's state.** Rejected (D8): it needs a field the owner would
  add, against principle III. **Ask the whole batch as one request.** Rejected: one request is one
  decision (R2C-APPROVAL-4).
- **Show `running` from the model's request, or hold `running` until the result.** Rejected (D5): a
  tool would be `running` while a person decides, and a denied one would stay `running`; or live
  progress would be lost. **Wrap the graph's tool node to report starts.** Rejected: it edits the
  graph.
- **No core change; `lost` as a word in a `failed` reason.** Rejected (D2): a caller cannot tell the two
  apart.
- **An owner-supplied predicate for `input_required`.** Not now (D10): the structured reply's `status`
  covers the sample's convention, and a predicate can be added later without breaking this.

## Consequences

**Better**
- A pause survives a restart with the same request ids, in `per_call`, in `batched` (asked again) and
  for a hand-written `interrupt()`; each tool body ran once (SC-003).
- A wrong answer never strands a thread, in both modes (SC-005), and a new message never reaches a
  provider with a dangling tool call (SC-009).
- No approval reaches `answer_by: caller` and none is answered by code in the bridge (SC-006).
- The timeline is truthful: no `running` for a call that waits or was denied.

**Worse**
- A restart in the middle of a `batched` pause costs the caller the answers already given. The README
  says to use `per_call` where that matters.
- The bridge reads the shapes `HumanInTheLoopMiddleware` writes (payload type, response schema, tool
  call order), so a change in LangChain can break it. `tests/test_langgraph_spike.py` pins every fact
  the design leans on, and the extra names the lower bounds the tests prove.
- The settle writes the finished ungated tool messages again (a message with the same id replaces it, so
  nothing is duplicated), and writes nothing when the calls are not in the wrapped graph's own messages.
- A tool body with sequential `interrupt()` calls starts again from the top after each answer, as
  LangGraph does; the bridge adds nothing to that.
- A node that runs on a worker thread (a sync node, a sync tool) reports its callbacks from a private
  event loop; the per-run handler hands each event to the loop of the run, so tool activity of a sync
  node is live and a debug-mode loop does not wait for a queue it cannot wake (R19 F2).
- A LangChain tool served on its own refuses a key its schema does not declare (a function tool of the
  core does the same), stricter than JSON Schema's default; a schema that says `additionalProperties` or
  `patternProperties` is taken at its word. Arguments reach the tool through `arun`, not `ainvoke`, which
  would read a `type: "tool_call"` key as an envelope and run other arguments than the ones checked
  (R19 S1, S2).
- The answer to an `input_required` question is a new turn, so its usage counts from zero while the
  doors may treat both turns as one task (D7).
- `UsageEvent` for a turn that ends in an `input_required` question is sent before the question.

**Must now be true**
- The owner brings a durable checkpointer **with async support** for a pause to survive a restart; the
  in-memory one works and warns once.
- Two requests a graph asks at once have distinct ids; two with the same id cannot be told apart and the
  first in order takes the answer.
- The doors keep one unfinished run per owner and context, so the bridge has no concurrent writer on a
  thread. The batch record is per process.
- Every kind of pause in the table below keeps a test; a new kind of pause adds a row and a test first.

## What each pause shows and gets back, and the test that proves it (SC-012)

Test names are in `python/tests/`. A parametrized test is named without its ids. The check
`tests/test_langgraph_adr_table.py` fails when a name below is not a test any more.

### A pause: what the caller sees, what the graph gets (contract, section 1)

| # | The graph pauses with | The caller sees | The graph gets | Proven by |
|---|---|---|---|---|
| 1 | a `per_call` interrupt, one per gated call | an `Approval` per call, one at a time, in the model's order | `approve`; `reject` (+ `message`); `edit` with the call's own tool and the answer's args | `test_two_gated_calls_are_asked_one_at_a_time_in_the_models_order`, `test_three_calls_are_asked_in_order_and_each_decision_reaches_its_own_call`, `test_tool_approvals_come_in_the_models_order_whatever_order_the_graph_lists_them_in`, `test_the_approval_describes_the_call`, `test_only_what_the_call_allows_is_offered`, `test_an_edit_runs_the_tool_with_the_new_arguments`, `test_an_edit_cannot_rename_the_tool`, `test_a_deny_carries_its_reason_to_the_model` |
| 2 | a `batched` interrupt | one `Approval` per call, one at a time, position order | one resume `{"decisions": [...]}`, position order, after the last answer | `test_the_first_answer_of_a_batch_is_recorded_and_the_next_call_is_asked_with_no_graph_call`, `test_the_last_answer_sends_every_decision_in_one_resume_in_position_order`, `test_answers_that_come_out_of_order_still_leave_in_position_order`, `test_a_batch_knows_what_is_decided_and_what_comes_next`, `test_the_decisions_leave_in_position_order_whatever_order_they_came_in` |
| 3 | row 1 or 2, a call that allows only `respond` | a `Question`, one text field | `respond` with the text | `test_a_call_that_allows_only_a_reply_is_asked_as_a_question` |
| 4 | `interrupt(value)`, a valid R2C `question` | that question, with its own id | the answer's `value` mapping | `test_a_valid_question_is_asked_as_it_is_and_the_graph_gets_the_answers_value` |
| 5 | `interrupt(value)`, a valid `approval` for a person or an approver | that approval, with its own id | the answer's `value` mapping | `test_a_valid_approval_for_a_person_or_an_approver_is_asked_as_it_is`, `test_a_hand_written_approval_is_asked_as_it_is_for_a_person_or_an_approver` |
| 6 | `interrupt(value)`, an approval addressed to the caller | a `Question` for a person, never an approval | the answered text | `test_an_approval_addressed_to_the_caller_falls_back_to_a_question_for_a_person`, `test_no_path_that_yields_an_approval_addresses_it_to_the_caller`, `test_the_middleware_never_yields_an_approval_for_the_caller` |
| 7 | `interrupt(value)`, anything else | a `Question` for a person, one text field; a string is the title (200), another value is JSON in the description (2000) | the answered text | `test_a_string_is_asked_as_a_question_for_a_person_with_one_text_field`, `test_a_strings_title_is_cut_at_200_characters_and_an_empty_one_is_replaced`, `test_any_other_value_is_a_question_whose_description_shows_it_as_json`, `test_the_description_of_a_long_string_is_the_whole_text_cut_at_2000_characters`, `test_the_description_of_a_large_value_is_cut_at_2000_characters`, `test_a_mapping_that_looks_like_a_question_but_is_not_valid_is_a_fallback` |
| 8 | the end of a turn with `status: "input_required"` | a `Question` for the caller; the JSON is not the reply | no resume: the answer is the next human message | `test_a_turn_that_says_input_required_is_asked_as_a_question_for_the_caller`, `test_the_title_is_the_first_line_cut_at_200_and_a_longer_message_is_kept_in_the_description`, `test_the_answer_is_the_next_human_message_of_the_same_thread_and_not_a_resume`, `test_only_input_required_with_a_message_is_asked`, `test_the_question_survives_a_restart_with_the_same_id` |
| 9 | several interrupts at once | one at a time: tool approvals in the model's order, then the others | each answer resumes only its own interrupt | `test_parallel_interrupts_are_asked_one_at_a_time_in_the_order_the_graph_lists_them`, `test_an_answer_resumes_only_its_own_interrupt_by_id`, `test_a_fallback_question_comes_after_the_tool_approvals`, `test_parallel_interrupts_come_in_the_same_order_after_a_restart`, `test_two_requests_with_the_same_own_id_are_not_told_apart_and_the_first_in_order_matches` |
| 10 | two `interrupt()` calls in a row in one node | the first, then, after its answer, the second | each answer resumes the interrupt that is pending | `test_interrupts_in_a_row_in_one_node_are_asked_and_answered_in_order` |

Also in section 1: a call whose allowed decisions leave nothing to offer, and a `per_call` payload with
no readable response schema, end `failed` before any ask:
`test_a_call_that_allows_only_an_edit_nobody_can_check_ends_failed_before_any_ask`,
`test_a_per_call_payload_with_no_readable_decisions_ends_failed_before_any_ask`;
`edit` is offered only when the tool's schema is found: `test_a_tool_the_graph_hides_cannot_be_edited`,
`test_the_tools_of_a_create_agent_graph_are_found_by_name_and_a_wrapper_has_none`.

### An answer that cannot be applied (contract, section 2)

| Case | What happens | Proven by |
|---|---|---|
| the id matches no pending interrupt | `PauseLost`, the run ends `lost`, the graph is not started | `test_an_answer_for_a_pause_the_graph_does_not_hold_is_lost_and_the_graph_is_not_started`, `test_resume_raises_pause_lost_naming_the_id`, `test_an_answer_for_another_request_than_the_pending_one_is_lost_and_the_pause_stays_pending`, `test_an_in_memory_checkpointer_holds_nothing_after_a_restart_so_the_answer_is_lost`, `test_an_answer_already_applied_is_lost_the_second_time_and_the_graph_is_not_started`, `test_a_thread_that_was_pruned_is_lost_and_the_graph_is_not_started`, `test_a2a_a_pause_the_new_checkpointer_does_not_hold_ends_the_task_lost`, `test_mcp_a_pause_the_new_checkpointer_does_not_hold_is_an_error_that_says_lost` |
| the `input_required` question's id, and the turn has moved on | `PauseLost` | `test_an_answer_after_the_conversation_moved_on_ends_lost_and_does_not_call_the_graph`, `test_an_answer_when_a_human_message_no_turn_has_answered_yet_follows_ends_lost`, `test_an_answer_to_a_reply_that_no_longer_asks_ends_lost`, `test_an_answer_to_a_question_the_graph_never_asked_ends_lost` |
| a decision the call does not allow, an `edit` it cannot take | `ValueError`, run `failed`, graph untouched, pause still pending, a correct answer continues (both modes) | `test_a_decision_the_call_does_not_allow_is_refused_before_the_graph`, `test_arguments_that_break_the_tools_schema_are_refused_before_the_graph`, `test_a_batch_is_never_sent_with_a_decision_the_graph_would_refuse`, `test_an_answer_the_request_refuses_is_refused_before_the_graph_and_the_pause_stays_pending` |
| `declined` for an approval | `reject`, `note` as the message | `test_a_declined_approval_is_a_reject_with_the_note_as_the_message`, `test_a_declined_approval_with_no_note_is_a_reject_with_no_message` |
| `declined`, the call does not allow `reject` | run `failed`, the call does not run, the pause stays | `test_declining_a_call_that_cannot_be_rejected_ends_failed_and_the_pause_stays` |
| `declined` for a respond-only question | run `failed` as above | `test_declining_a_question_that_only_takes_a_reply_ends_failed_and_the_pause_stays` |
| `declined` for a question of rows 4, 6, 7 | the graph gets `None` | `test_a_declined_question_resumes_the_graph_with_none` |
| `declined` for a hand-written approval (row 5) | the graph gets `{"decision": "deny"}` (+ `reason`) | `test_a_declined_hand_written_approval_is_a_deny_for_the_graph` |
| `declined` for the `input_required` question | run `done`, graph not called | `test_a_declined_question_ends_the_run_done_and_the_graph_is_not_called` |
| a `batched` answer that is not the last | recorded in memory, next call asked, no graph call | `test_the_first_answer_of_a_batch_is_recorded_and_the_next_call_is_asked_with_no_graph_call`, `test_two_threads_keep_their_own_batches` |
| a `batched` answer for a call that already has a decision | refused as `lost`; the first decision stands; the graph is not called | `test_a_second_decision_for_a_position_is_refused_and_the_first_stands`, `test_a_second_answer_for_a_call_already_decided_is_refused_and_the_first_decision_stands` |
| a `batched` answer, no record (a restart in between) | recorded, the batch is asked again from its first call | `test_an_answer_for_a_call_the_agent_has_no_record_of_is_kept_and_the_batch_starts_from_its_first_call`, `test_a_batch_with_its_first_call_answered_is_asked_again_from_its_first_call_after_a_restart`, `test_the_record_is_dropped_when_its_pause_is_found_lost` |

A batch decision with the wrong count cannot be sent by the bridge (it sends one decision per call, in
position order and only when complete): `test_an_incomplete_batch_cannot_be_sent`,
`test_a_position_outside_the_batch_is_refused`.

### A new input while an approval is pending (contract, section 3)

| Rule | Proven by |
|---|---|
| the new message reaches a normal reply; the model sees the withdrawn call as rejected, with the reason | `test_a_new_message_on_a_pending_approval_reaches_a_normal_reply`, `test_the_model_sees_the_withdrawn_call_as_rejected_with_the_reason` |
| what already ran is kept, what did not is withdrawn, both gated calls of one pause | `test_what_already_ran_is_kept_and_what_did_not_is_withdrawn`, `test_a_pause_with_two_gated_calls_withdraws_both`, `test_the_settle_leaves_no_pause_and_is_the_step_that_was_waiting` |
| the withdrawn pause cannot be answered; a batch in progress is dropped | `test_the_withdrawn_pause_cannot_be_answered_any_more`, `test_a_batch_in_progress_is_dropped_when_the_pause_is_withdrawn` |
| a call a run left open without a pause (a tool body that asked and was abandoned, a tool that raised, a run cancelled in a tool) is answered "did not finish" | `test_a_hand_written_interrupt_in_a_tool_body_is_settled_too`, `test_a_new_message_after_a_failed_tool_reaches_a_normal_reply`, `test_a_new_message_after_a_cancel_in_a_running_tool_reaches_a_normal_reply`, `test_an_unanswered_call_is_answered_when_no_pause_is_left`, `test_the_writer_is_named_only_when_one_step_did_not_finish`, `test_what_a_finished_task_made_is_written_again_though_no_call_is_open` |
| an answered pause, a graph that ended, a history already broken, calls that are not the graph's own: nothing is touched | `test_a_new_message_after_an_answered_pause_is_not_touched`, `test_a_graph_that_ended_keeps_the_state_it_ended_with`, `test_nothing_is_written_when_no_call_waits`, `test_nothing_is_written_when_the_calls_are_not_in_the_graphs_own_messages` |

### The stream: what each part becomes (contract, section 4)

| From | Becomes | Proven by |
|---|---|---|
| text of an AI message | reply chunks, hold-one, a blank line between two messages | `test_the_reply_is_the_models_text_in_chunks_and_only_the_last_one_is_last`, `test_a_piece_is_held_until_the_next_one_arrives`, `test_two_messages_with_text_are_separated_by_a_blank_line`, `test_the_first_chunk_is_read_before_the_models_last_token` |
| the held piece | `last=True` at the end of a turn; unmarked at tool calls, at an `Ask`, at an error; an empty closing chunk when nothing is held | `test_text_then_a_tool_then_text_has_one_last_chunk_at_the_end`, `test_a_leg_that_ends_in_an_ask_leaves_its_held_piece_unmarked_and_the_reply_goes_on`, `test_a_graph_that_raises_leaves_its_held_piece_unmarked_before_the_error`, `test_a_reply_that_ends_before_the_tools_is_closed_with_an_empty_last_chunk` |
| a message of a `nostream` model call | nothing (usage still counts) | `test_a_hidden_model_call_never_reaches_the_reply`, `test_the_tokens_of_a_hidden_message_count_because_they_were_spent` |
| a message starting with `{` in a graph with a structured reply | held until its node update; dropped when it asks, else reply text | `test_prose_streams_at_once_and_only_the_json_is_held`, `test_a_message_that_starts_with_a_brace_is_kept_apart_and_dropped_when_it_asks`, `test_a_message_kept_apart_that_does_not_ask_is_reply_text` |
| a tool message, a human message | nothing | `test_a_tool_message_is_never_reply_text`, `test_a_human_message_a_node_writes_is_never_reply_text` |
| a `reasoning` block, option on | `reasoning` activity in readable pieces | `test_with_the_option_on_reasoning_is_one_activity_per_message_in_readable_pieces`, `test_reasoning_is_off_by_default_though_the_model_reasons`, `test_a_sentence_end_lets_the_buffer_leave_once_it_holds_40_characters`, `test_a_long_run_with_no_sentence_end_is_cut_at_a_space_near_400_characters` |
| a file, image, audio or video block with data | a `file` artifact; no data, bad base64 or a vendor kind is skipped | `test_a_file_block_with_bytes_becomes_a_file_artifact`, `test_a_file_block_with_a_url_becomes_a_url_part_and_the_name_is_read_from_its_extras`, `test_a_block_with_no_data_bad_base64_or_a_vendor_kind_is_skipped_and_the_run_goes_on` |
| a tool starts | `running`, only when the body runs | `test_a_tool_call_is_one_activity_running_then_done_with_its_duration`, `test_a_call_waiting_for_approval_has_no_activity_and_a_denied_one_never_has`, `test_running_is_seen_while_the_tool_runs` |
| a tool ends | `done`, or `failed` when the tool message is an error | `test_a_tool_that_reports_an_error_ends_failed_and_the_run_goes_on` |
| a tool raises | `failed`; a pause inside the body stays `running` | `test_a_tool_that_raises_ends_failed_and_then_the_run_ends_failed`, `test_a_tool_that_pauses_inside_its_body_stays_running_and_reports_running_again_when_resumed` |
| an exposed tool | `args` and `detail` (2000); others none | `test_an_exposed_tool_shows_its_args_and_its_result_and_another_tool_does_not`, `test_detail_is_cut_at_2000_characters` |
| an exception out of the stream | each running activity closed `failed`, then the error | `test_when_the_graph_raises_each_activity_still_running_ends_failed_once_before_the_error` |
| the end of a turn | one cumulative `UsageEvent`, the same after a restart, nothing a model did not report | `test_several_model_calls_send_one_cumulative_usage_with_the_model_name_after_the_reply`, `test_the_total_is_the_same_after_a_restart_in_the_middle_of_the_turn`, `test_a_field_the_model_did_not_report_is_absent_not_zero` |
| a leg that ends in an `Ask` | the reply flushed, then the `Ask`; no usage | `test_usage_is_not_sent_at_a_pause_but_once_at_the_end` |
| a reply that spans a pause | the doors keep appending to one reply | `test_a2a_the_last_piece_before_a_pause_is_sent_with_the_question`, `test_mcp_the_last_piece_before_a_pause_is_in_the_final_result` |
| the whole contract, on a real graph | the shared suite S1 to S10 | `test_the_shared_suite_passes_on_a_real_graph`, `test_a_correct_source_asks_one_request_at_a_time` |
