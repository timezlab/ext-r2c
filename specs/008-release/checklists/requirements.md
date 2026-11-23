# Specification Quality Checklist: The first pre-release, a tested wheel on a GitHub release (`0.1.0a1`)

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-11-23
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs) — a release is GitHub-shaped by the
      maintainer's own request, so the spec names GitHub releases, tags, PEP 440 and SHA-256 and what
      the installed tooling does today (seven dated findings in Context). It names no workflow syntax, no
      action, no script name or language: how the job is split, how CI's checks become shared, and where
      the scripts live are left to the plan (D6, D7 and the Assumptions say so)
- [X] Focused on user value and business needs (the adopter installs in one line and knows the limits;
      the maintainer cannot publish something untested)
- [X] Written for the readers named in the stories (the adopter's engineer, the maintainer) and for the
      people who write the plan; the same register as specs 003 to 007
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain — the open choices are written as defaults D1–D11 in
      "Decisions taken in this draft"; D3 (no PyPI, and the name is free for anyone), D5 (where private
      words may live) and D11 (the publishing steps are not rehearsed) are the three the maintainer is
      asked about first
- [X] Requirements are testable and unambiguous (each FR maps to a story scenario or a success
      criterion; the refusals are a list in FR-004 and each is a test on a fixture)
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic — they name the installer's line, the Python versions the
      project supports, checksums, counts of public releases and files; no workflow syntax
- [X] All acceptance scenarios are defined
- [X] Edge cases are identified (non-normal tag, tag off `main`, a flaky leg, a partial upload, a tag
      already released, a public log, an `example.com` address, the sdist's own tests, a fork, a range
      that skips a pre-release)
- [X] Scope is clearly bounded (Out of scope in Assumptions: PyPI, signing, finals, other platforms,
      any change under `python/src/` or `standard/`, pushing the tag)
- [X] Dependencies and assumptions identified (public repository, default read-only token, the existing
      CI as the one definition of the checks, scripts outside the wheel)

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria (FR → story scenarios and SC:
      FR-001–003 → US1, US2, SC-001, SC-007, SC-011; FR-004–005 → US3, SC-002; FR-006 → US2, SC-003;
      FR-007 → US2, SC-010; FR-008 → US1, SC-001; FR-009 → US3, SC-006, SC-007; FR-010–011 → US2,
      SC-002, SC-003; FR-012 → US3, SC-002; FR-013 → US1, SC-001; FR-014 → SC-005; FR-015–016 → US1,
      US5, SC-008, SC-009; FR-017 → SC-011; FR-018 → US1, SC-009, SC-011; FR-019 → US4, SC-004)
- [X] User scenarios cover primary flows (install, cut, refuse, try without publishing, the notes)
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

- Iteration 1 of 3: all items pass after the self-review below.
- The self-review made four changes to the first draft: the year of the maintainer's first PyPI answer
  was wrong in two places (2020 for 2026); FR-014 and SC-005 spoke of a *step* holding write permission,
  and GitHub gives permission to a *job*; FR-019 asked a manual start to run checks that need a tag
  (the tag equals the version, the tagged commit is on `main`, no published release exists), so those now
  run only on a real start; and D11 was added because the publishing steps cannot be run before the first
  release without a write, which the spec otherwise forbids on a manual start.
- Three facts in Context were measured, not assumed, and are worth re-checking at plan time: PyPI
  answered `404` for the name on 2026-11-23; a scratch `0.1.0a1` wheel installed by address with no
  `--pre` through `pip` and `uv`, and `ext-r2c>=0.1` found nothing; the generic scan found one line in
  the current build (an invented address on `example.com` in the sdist's tests).
- Known gap, stated in D11: the draft, upload, compare and publish steps run for real only once, at the
  first release. The design (a draft, then public) means a failure there leaves nothing public.
