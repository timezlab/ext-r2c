# Contract: what the skills extension puts on the wire

Phase 1 of [plan.md](../plan.md). Normative source: the beta text of MCP Skills
(`specification/beta/skills.mdx` and `schema/beta/schema.json` in the ext-skills repository, read
2026-11-21; base protocol 2026-07-28). This file records how the package maps it. If the two
disagree, the beta text wins and this file is wrong.

## Declaration

`server/discover` carries `capabilities.extensions["io.modelcontextprotocol/skills"] =
{"directoryRead": <bool>}` (an empty object is also valid) and the `resources` capability. The
client sends no capability for it.

## URIs

| What | Form | Notes |
|---|---|---|
| a skill's `SKILL.md` | `skill://<skill-path>/SKILL.md` | the last segment of `<skill-path>` equals `name` |
| a supporting file | `skill://<skill-path>/<file-path>` | |
| a directory | `skill://<skill-path>` or `…/<dir>` | no trailing slash; `mimeType: inode/directory` |

Every segment is `urllib.parse.quote(segment, safe="")`; the first is the authority and is a valid
`reg-name`; two skills whose first segments differ only in case are a duplicate (build error).
A request URI is compared as a whole string with the served set (R3).

## `skills/list`

Request `params`: `{_meta, cursor?}`. Result:

```json
{
  "resultType": "complete",
  "skills": [
    {
      "uri": "skill://billing/refunds/SKILL.md",
      "frontmatter": {"name": "refunds", "description": "Handle a refund request.", "license": "MIT"},
      "resources": [
        {"uri": "skill://billing/refunds/SKILL.md", "digest": "sha256:<64 hex>", "size": 412},
        {"uri": "skill://billing/refunds/templates/reply.md", "digest": "sha256:<64 hex>", "size": 96}
      ]
    }
  ],
  "nextCursor": "<opaque>",
  "ttlMs": 300000,
  "cacheScope": "private"
}
```

Every served skill appears exactly once across the pages; entries are sorted by `uri`; a page has
at most `page_size` entries; `nextCursor` is absent on the last page. The cursor is opaque
(base64url of `<generation>.<offset>`); a cursor that does not decode, is from another generation
or points past the end is `-32602`.

## `skills/get`

Request `params`: `{_meta, uri}`. Result: `{resultType, skill, ttlMs, cacheScope}`, with `skill`
the same object as a list entry. The URI must be a served skill's `SKILL.md` URI; anything else
is `-32602` (message: `No skill is served at <uri>`). No `Mcp-Name` header is used.

## `resources/read` (the SDK's own method)

| Case | Answer |
|---|---|
| a served file | `contents[0]` with `uri`, `mimeType`, and `text` if the bytes decode as UTF-8 and re-encode identically, else `blob` (base64) |
| `SKILL.md` | `mimeType: text/markdown`; the registered resource's `name` and `description` are the frontmatter's |
| a URI that is not a served file (`..`, `%2e%2e`, backslash, query, fragment, trailing slash, wrong case, a directory, a skill the filters exclude, a file the scan left out) | `-32602` from the SDK (`Unknown resource`), nothing read |
| a served file whose bytes on disk no longer match the entry | `-32603`, `The skills changed on disk since they were scanned; refresh them.`, no bytes |
| a served file whose URI the catalogue no longer holds (after a refresh) | `-32602` |

A resource's `_meta` is empty: the package sets no key (any key it set would use the
`io.modelcontextprotocol.skills/` prefix).

## `resources/directory/read` (only when `directoryRead` is true)

Request `params`: `{_meta, uri, cursor?}`. Result:

```json
{
  "resultType": "complete",
  "resources": [
    {"uri": "skill://billing/refunds/SKILL.md", "name": "refunds", "description": "Handle a refund request.", "mimeType": "text/markdown"},
    {"uri": "skill://billing/refunds/templates", "name": "templates", "mimeType": "inode/directory"}
  ],
  "ttlMs": 300000,
  "cacheScope": "private"
}
```

Direct children only, sorted by name, paged like the list. A URI that is not a served directory
(a file, a prefix above skills, a skill the filters exclude, anything unknown) is `-32602`; an
empty directory is `"resources": []`. When `directoryRead` is false the method is not bound and
the SDK answers `-32601`.

## Errors

| Code | When |
|---|---|
| `-32602` | unknown skill URI; unserved file; not a directory; bad or stale cursor; wrong parameter type |
| `-32603` | a read whose bytes no longer match the entry; an unexpected failure (the message names no host path) |
| `-32601` | `resources/directory/read` with `directoryRead` off |

The client turns every failed check into a `SkillRefused`; those are host-side conditions and cause
no wire traffic of their own (the text's "Verification failures are host-side").
