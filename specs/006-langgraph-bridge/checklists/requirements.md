# Specification Quality Checklist: LangGraph bridge (`ext_r2c.bridges.langgraph`)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-22
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs) — the spec names LangGraph and
      LangChain calls (`interrupt()`, `HumanInTheLoopMiddleware`, the stream modes) because the
      bridge is an adapter for them and the feature description asks for what the installed
      packages do; those facts sit in one dated Context section, and the requirements say what
      the caller sees, not which call produces it. How a thing is done is left to the plan
      (D5, D9, D10 name the choices the plan makes by test)
- [X] Focused on user value and business needs
- [X] Written for the readers named in the stories (owners of a LangGraph agent, the people who
      write `Remote`); the same register as specs 003 to 005
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain — the open choices are written as defaults D1–D11
      in "Decisions taken in this draft"; D2 (a small core piece) and D3 (changes to the shared
      suite) touch spec 002 and are the two the maintainer is asked about first
- [X] Requirements are testable and unambiguous
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic — they name the protocols, the Python versions the
      project supports, the shared suite and the checkpointer file, and no library API
- [X] All acceptance scenarios are defined
- [X] Edge cases are identified
- [X] Scope is clearly bounded (Out of scope in Assumptions)
- [X] Dependencies and assumptions identified (the installed package versions, the scripted
      model, the doors' handling of a reply across a pause, the bounds of the extra)

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria (FR → story scenarios and SC:
      FR-001–004 → US1 and SC-001, SC-002, SC-010; FR-005–007 → US1, US5, SC-009; FR-008–013 →
      US4, SC-007, SC-008; FR-014–023 → US2, US3, US5, SC-003–SC-006; FR-024–025 → US6, SC-011;
      FR-026–030 → SC-001, SC-010, SC-012)
- [X] User scenarios cover primary flows (wrap and serve, approvals, restart, timeline, other
      pauses, tools)
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

- Iteration 1 of 3: all items pass. Self-review after the first draft fixed two mismatches with
  the existing suite (usage once per turn, not at each pause; the batch rule for an answer the
  bridge has no record of) and added the missing "Out of scope" list.
- Open for the plan, not for the spec: the lower and upper bounds of the extra; how to tell, in
  the stream, a tool that starts from one that `per_call` pauses (D5); the settle mechanism for a
  new input on a pause (D9); how `input_required` is detected on a real `response_format` (D10);
  how the allowed decisions of a `per_call` interrupt are read from its response schema; how
  hand-written interrupts that run in parallel are ordered; whether a door limits an artifact's
  size; the file layout under `bridges/langgraph/`.
- Verified in a scratch environment before this spec (2026-11-22, not committed): stream parts
  and pending interrupts of both middleware modes, partial resume by interrupt id, the stuck
  `batched` thread after a refused resume, a restart over a SQLite file, a tool that raises,
  hand-written interrupts (also inside a tool), standard content blocks and usage details, a
  tool's JSON Schema, a new input on a paused agent, the stream's task events.
- Gate: the maintainer approves this spec before `plan.md` is written.
