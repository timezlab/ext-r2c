# Exactly four kinds in v1

**Status:** accepted, 2026-11-20.

## Context

A broader vocabulary was proposed first: `question`, `approval`, `plan`, `step`, `live_view`,
`evidence`/`provenance`, `caller_context`. Each kind is a schema to keep, examples to write, and
a behaviour every client must handle.

## Decision

v1 has exactly four kinds: `question`, `approval`, `answer`, `artifact`.

- **No `plan` / `step`.** Progress is the remote's own A2A SSE status text (`working`) or MCP
  `notifications/progress`, relayed by the caller.
- **No `live_view`.** A live page is an `artifact` with `presentation: "live"` and
  `state: open | closed`.
- **`provenance` and `caller_context` deferred.** The rule "MUST ignore an unknown kind or
  field" makes adding them later non-breaking.
- `question` and `approval` share `title` (required) and `description` (optional, markdown).
  There is no `impact` or `reason` on the request; the approval answer has an optional `reason`,
  mainly for `deny`.

## Alternatives

- **Progress as a kind.** Gives start/finish, duration and nesting, but makes every remote
  install something for what SSE already shows.
- **Keep the seven kinds.** More to specify and test before anyone has used the first four.

## Consequences

- **Better:** a small standard a remote can adopt in an afternoon; every kind has a clear "use
  when / do not use".
- **Worse:** no structured progress (no step list, no durations) and no per-figure provenance
  in v1.
- **Must now be true:** clients and remotes ignore unknown kinds and fields; a new kind is a
  minor, additive change.
