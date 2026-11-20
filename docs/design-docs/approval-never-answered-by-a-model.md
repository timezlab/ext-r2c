# An approval is answered by a human or a policy, never by a model

**Status:** accepted, 2026-11-20.

## Context

R2C deliberately lets agents talk to agents: a remote may ask the caller agent
(`answer_by: caller`) or hold a plain multi-turn text exchange. Approvals are different: they
guard actions that are hard to undo. A caller also wants "Always allow" so the same harmless
action is not approved twenty times.

## Decision

- An `approval` never has `answer_by: caller`, and its `answer` never has `answered_by: caller`.
- `answered_by` is the client's claim, which the remote cannot check, so this is a **MUST on the
  client**.
- Remembering is **client policy**: a rule applied by code (for example after the user clicked
  "Always allow") may answer an approval, recorded as `answered_by: policy`. A model never
  applies it, and it never applies to `answer_by: approver` (four-eyes approval asks every time).
- There is **no `remember` field** on the wire. The remote keeps no per-user state and sees every
  policy answer.
- A `question` with `answer_by: person` should reach a person; with nobody there it is
  `declined`.

## Alternatives

- **Let the caller agent approve when the user approved something similar before.** Rejected:
  "similar" is a model's judgement on an irreversible action.
- **A `remember` flag on the answer, honoured by the remote.** The remote would hold per-user
  allow-lists it cannot attribute, and the caller could no longer show what was auto-approved.

## Consequences

- **Better:** every irreversible action traces to a human or to a rule a human set.
- **Worse:** an unattended run (U3) can only proceed through a policy; otherwise the approval
  expires as `deny`.
- **Must now be true:** callers implement the policy store and its scope themselves; the
  standard defines only `answered_by: policy`.
