# ext-r2c

**What:** R2C (Remote-to-Caller), an extension for A2A and MCP. A **remote** (an A2A agent or
an MCP server) uses it to ask its **caller** a `question`, request an `approval`, and hand back
an `artifact`, and reports `activity` and `usage`; the caller replies with an `answer`. One
adapter, `Remote` (`ext_r2c.Remote`, built in spec 007), wraps an existing remote and exposes it
over A2A, MCP or both from one ASGI app, so its own logic does not change.
**This repo** holds the standard (`standard/`) and the Python SDK (`python/`). It is **public**:
neutral data only (constitution VI).
**State:** see `WORKSTATE.md` first — what exists, what is next, what is waiting for approval.

## Identifiers

- A2A URI: `https://github.com/timezlab/ext-r2c/tree/main/standard/v1`
- MCP `_meta` key: `io.github.timezlab/r2c`
- PyPI `ext-r2c` (not reserved yet), import `ext_r2c`; npm later `@timezlab/ext-r2c`

## Principles (inviolable, full text in `.specify/memory/constitution.md`)

1. JSON Schema in `standard/vN/schema/` is the single source of shape.
2. Wire examples in `standard/vN/examples/` are the shared test suite.
3. A remote's own logic stays unchanged: one install, one wrapping line.
4. An extension, never a protocol: no core changes; ignore unknown kinds and fields.
5. An approval is answered by a human or a policy, never a model.
6. Public: no private names, hosts, figures or local paths anywhere.
7. Test first, against the installed wheel.
8. Small core (`pydantic`, `jsonschema`); bindings behind extras; imports one way.
9. The major version is in the URI; v1 is draft until the first outside adopter.

## Conventions

- **Language:** everything committed is English. Chat with the maintainer may be Vietnamese.
- **Specs (Spec Kit):** `specs/NNN-<short-name>/{spec,plan,tasks}.md` at the repo root. Never
  confuse `specs/` (our feature work) with `standard/` (the R2C standard itself).
- **Gate:** no behaviour code before `spec.md` + `plan.md` are approved by the maintainer.
- **Code style:** `snake_case.py`, `PascalCase` classes, typed (`py.typed` ships).
- **Tests:** `uv build` in `python/`, install the wheel into a clean venv, run pytest there
  (see `README.md`). CI does the same on 3.11, 3.12, 3.13.
- **Commits:** straight to `main`, explicit pathspec, no AI co-author trailer; push only on the
  maintainer's go.

## Docs

| When you need to...                              | Read                                                        |
|--------------------------------------------------|-------------------------------------------------------------|
| Know the current state and the next step         | `WORKSTATE.md`                                              |
| Understand the layout and import rules           | `ARCHITECTURE.md`                                           |
| Explain R2C end to end (white paper, not normative) | `docs/whitepaper.md`                                     |
| Know the whole v1 design and why                 | `docs/research/2026-11-20-r2c-v1-design-brief.md`           |
| Know why R2C is not built on Structured Input    | `docs/design-docs/own-extension-not-structured-input.md`    |
| Know why the first four kinds                    | `docs/design-docs/four-kinds.md`                            |
| Know why `activity`, `usage` and the streamed reply | `docs/design-docs/activity-and-usage-kinds.md`           |
| Know why one adapter (`Remote`) for A2A, MCP or both | `docs/design-docs/one-remote-two-doors.md`              |
| Know the names of `Remote` and how its one app is composed | `specs/007-remote/contracts/remote-api.md`, `app-composition.md` |
| Know why the standard and SDK share a repo, and why `standard/` | `docs/design-docs/standard-and-sdk-in-one-repo.md` |
| Know why no model ever answers an approval       | `docs/design-docs/approval-never-answered-by-a-model.md`    |
| Know why the thread is keyed by owner and context | `docs/design-docs/thread-per-owner-and-context.md`         |
| Know why MCP Skills has a small YAML reader and the nearest `SKILL.md` wins | `docs/design-docs/skills-frontmatter-and-nesting.md` |
| Know how a LangGraph pause becomes an ask and an answer returns to the graph | `docs/design-docs/langgraph-pause-to-ask.md` |
| See the SDK in use (two LangGraph agents calling each other) | `examples/langgraph_agent/README.md`            |
| Read the normative standard                      | `standard/v1/README.md`                                     |
| Find active feature work                         | `specs/NNN-<name>/`                                         |

## Harness

- Rules: `.claude/rules/` (mirrored in `.agents/rules/`): docs-as-code, spec-driven,
  planning-first, tdd, quality-gates, systematic-debugging, parallel-agents.
- Skills: `.agents/skills/<name>/` (linked from `.claude/skills/`); Spec Kit skills
  (`speckit-*`) live in `.claude/skills/` as installed by `specify init` 0.13.4.
- Reviewers: `.claude/agents/code-reviewer.md`, `.claude/agents/security-reviewer.md`.
