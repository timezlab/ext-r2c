# Contract: forms, answer mapping, fallback text

The tables below are what `forms.py` and `fallback.py` produce. The README sections they extend
are R2C-QUESTION-5 (§5) and R2C-MCP-2 / R2C-MCP-3 (§12). The plan updates those sections in the
same change (FR-031).

## Answer schema of a question (R2C-QUESTION-5, with Q2)

`{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "properties":
{<key>: <schema>}, "required": [<keys with required: true>]}`, where `<schema>` is:

| Field | `required: true` | `required: false` |
|---|---|---|
| `one`, `other: false` | `{"type": "string", "enum": [labels]}` | same |
| `one`, `other: true` | `{"type": "string", "minLength": 1}` | same |
| `many`, `other: false` | `{"type": "array", "items": {"enum": [labels]}, "uniqueItems": true, "minItems": 1}` | without `minItems` |
| `many`, `other: true` | `{"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": true, "minItems": 1}` | without `minItems` |
| `text` | `{"type": "string", "minLength": 1}` | `{"type": "string"}` |
| `number` | `{"type": "number"}` | same |
| `bool` | `{"type": "boolean"}` | same |

## Flat `requestedSchema` of a question (R2C-MCP-2)

Every property carries `"title": <header>` and `"description": <text>`.

| Field | Properties |
|---|---|
| `one`, `other: false` | `<key>: {"type": "string", "oneOf": [{"const": l, "title": l}, …]}` |
| `one`, `other: true` | as above, plus `<key>_other` |
| `many`, `other: false` | `<key>: {"type": "array", "items": {"anyOf": [{"const": l, "title": l}, …]}}` |
| `many`, `other: true` | as above, plus `<key>_other` |
| `text` / `number` / `bool` | `<key>: {"type": "string" / "number" / "boolean"}` |

`<key>_other` is `{"type": "string", "title": "<header> (other)", "description": "Another
<header in lower case>, if not listed."}`.

`required` lists the keys of fields with `required: true` and `other` not true (a `one` or
`many` with `other: true` is never listed; `<key>_other` is never listed). The `required` key is
left out when the list is empty.

## Flat `requestedSchema` of an approval (R2C-MCP-3)

```json
{"type": "object",
 "properties": {
   "decision": {"type": "string", "title": "Decision",
                "oneOf": [{"const": "allow", "title": "Allow"}, …]},
   "reason":   {"type": "string", "title": "Reason"},
   "<arg>":    {<the argument's property schema>, "title": "<arg>", "default": <current value>}
 },
 "required": ["decision"]}
```

- `decision` lists the offered decisions in the order of `decisions`. `edit` is listed only
  when it survives.
- `edit` survives when `edit_offered(approval)` is true and `args_schema` is flat.
  - `edit_offered(approval)` is false on an external `$ref` (R2C-SAFETY-7).
  - Flat means `type: object` with `properties`. Each property's `type` is `string`, `number`,
    `integer` or `boolean`, or the property is an `enum` of strings. No property uses `$ref`,
    `anyOf`, `oneOf`, `allOf` or `not`, and no property is named `decision` or `reason`.
- An argument's own `enum` becomes `"oneOf": [{"const": v, "title": v}, …]`, and `enum` is
  removed. A string enum without a `type` gets `"type": "string"`. Every other keyword of the
  property (`minimum`, `maximum`, `minLength`, `maxLength`, `format`, `description`) is kept.
- An argument whose current value is absent from `args` gets no `default`.
- When dropping `edit` leaves no decision, `mcp_form` raises `NotAskableOverMcp`.

## Flat response → answer (R2C-MCP-4, with Q1)

| Response | Answer |
|---|---|
| `action: decline` or `cancel` | `{outcome: declined, answered_by: {role: person}}`, no `value` |
| `action: accept`, question | `value` per field below; keys of the content that are not in the form are dropped |
| `action: accept`, approval | `value: {decision, reason?, args?}` as below |

Question fields. Here "other given" means `<key>_other` is a string that is not empty after
stripping spaces.

| Field | Value |
|---|---|
| `one` | `<key>_other` if given, else `<key>` if present, else absent |
| `many` | `<key>` (or `[]`) followed by `<key>_other` if given and not already in it; absent if both are missing |
| `text`, `number`, `bool` | `<key>` if present, else absent |

Approval:
- `decision` is copied as sent.
- `reason` is copied when it is a non-empty string.
- With `decision: edit`, `args` is the approval's current `args` with each `args_schema` property
  present in the content replacing its value.
- With any other decision, argument values in the content are ignored.

## Fallback text

Lines are joined with `\n`. Brackets mark optional parts.

Question:

```
[<error message> …]                    one line per item of `errors`, on a re-ask
[<origin.name> asks: ]<title>
[<description>]
- <header>: <text>[ (<hint>)]          one line per field
```

| Field | Hint |
|---|---|
| `one` | `one of: A, B` or, with `other: true`, `one of: A, B, or another` |
| `many` | `one or more of: A, B` (with `other: true`: `…, or others`) |
| `number` | `a number` |
| `bool` | `yes/no` |
| `text` | none |
| `required: false` | `optional` is added to the hint, separated by `; ` |

Approval:

```
Approval needed[ (<approver_role>)]: <title>
[<description>]
Reply with one of: allow | edit | deny[ (expires <expires_at>)]
```

Only the offered decisions are listed.

Activity: `<label>`, or `<label>: <detail>` when `detail` is present.
