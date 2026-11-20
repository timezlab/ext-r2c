# Contract: rule format in `standard/v1/README.md`

Every normative rule is one Markdown list item that starts with a tag line:

```
- **R2C-APPROVAL-2** · MUST NOT · client · wire · schema
  An `approval` is never addressed to the caller: `answer_by.role` is `person` or `approver`.
```

Grammar (one regular expression in the check):

```
^- \*\*(R2C-[A-Z]+-[0-9]+)\*\* · (MUST|MUST NOT|SHOULD|SHOULD NOT|MAY) · (remote|client|both) · (wire|prose)( · schema)?$
```

| Part | Meaning |
|---|---|
| `R2C-<AREA>-<n>` | stable identifier; never renumbered or reused once published. Areas: `CORE`, `ACT` (activation and declaration), `QUESTION`, `APPROVAL`, `ANSWER`, `ARTIFACT`, `ACTIVITY`, `USAGE`, `A2A`, `MCP`, `ID`, `SAFETY`, `VERSION` |
| level | RFC 2119 / RFC 8174 keyword, upper case |
| party | who the rule binds: `remote`, `client`, or `both` |
| `wire` / `prose` | `wire`: a valid example shows it; `prose`: it cannot be shown in a message (for example a UI behaviour or a time limit) |
| `schema` | a schema rejects a violation; at least one invalid example proves it |

Rules:

- An identifier appears once as a definition. Text elsewhere may cite it in backticks.
- A rule marked `prose` with `schema` is allowed (for example a field constraint no message
  needs to show); a rule never marked `schema` is listed in the README as "not schema-checked".
- Non-normative sections are headed "(non-normative)" and contain no tag lines.
