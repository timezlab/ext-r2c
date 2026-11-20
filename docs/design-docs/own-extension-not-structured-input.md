# One own extension, not a layer on Structured Input

**Status:** accepted, 2026-11-20. Supersedes the 2026-11-19 choice to build on Structured Input.

## Context

A2A has an experimental extension, Structured Input v1, that attaches a JSON Schema to an
`input-required` message. R2C needs more than a schema: who should answer, approvals with a
subject, a way to decline, re-asks with errors, and artifact presentation. The first design put
a small R2C vocabulary on top of Structured Input.

## Decision

R2C is **one self-contained extension**. `question`, `approval` and `answer` travel as a
DataPart whose `data` is the R2C object, marked by `metadata[URI] = {}`. The answer carries
`value`; a re-ask carries `errors`. `artifact` is a native A2A Artifact with `metadata[URI]`.
The MCP binding uses core elicitation. Validation schemas are generated from the form by the
SDK and never sent.

## Alternatives

- **Structured Input + R2C vocabulary.** No client understands Structured Input alone, so it
  buys no reach. Every part would carry two keys and a repeated `id`, the answer would be split
  across two extensions, and R2C would depend on an experimental spec pinned by commit.
- **Agent Stack Approval v1 + Form Request v1.** Two envelopes, a near-empty text fallback, and
  a URI from another ecosystem.

## Consequences

- **Better:** one URI to activate, one object per part, one place for every rule; the shape is
  ours to keep stable.
- **Worse:** a client that only speaks Structured Input gets nothing structured from us.
- **Must now be true:** every request still carries a text fallback, so a client without R2C
  can continue in text. Structured Input stays a possible compatibility mode for later.
