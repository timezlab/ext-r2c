# Data model: MCP Skills (`ext_r2c.mcp` skills extension)

Phase 1 of [plan.md](plan.md). The MCP types are `mcp_types`'. This file names what the skills
code holds in memory and what it puts on the wire. Signatures are in
[contracts/skills-api.md](contracts/skills-api.md); the wire is in
[contracts/wire-mapping.md](contracts/wire-mapping.md).

## Core and the standard

No change. Skills is not R2C: nothing in `ext_r2c.core`, `ext_r2c.a2a`, `standard/` or the R2C
extension changes, and the skills code imports none of it (R12).

## Server side

### Root and filters

What the owner gives: one or more **root folders**, `include` and `exclude` (glob lists), and the
settings `directory_read`, `ttl_ms`, `cache_scope`, `page_size`. They are validated at
construction and kept, because a refresh scans again with the same values.

### Skill record

One per served skill. Built by the scan, never mutated.

| Field | Type | Meaning |
|---|---|---|
| `name` | str | `frontmatter["name"]`, equal to the last segment of `path` |
| `path` | tuple of str | the folder's path below its root, one decoded segment each |
| `uri` | str | `skill://<encoded path>/SKILL.md` |
| `folder` | str | the skill folder's absolute, resolved path on disk |
| `frontmatter` | dict | every field the author wrote, as plain JSON data (R7) |
| `files` | tuple of file records | `SKILL.md` and every other file, sorted by relative path |
| `dirs` | tuple of tuples of str | every folder below the skill folder that the scan walked, **empty ones too**, each as its names from the skill folder down; sorted by tuple (a folder before what is in it) and without repeats. Last field, default `()` (phase 8) |

Invariants: `files` holds `SKILL.md` exactly once; at most 512 files; the sum of sizes is at most
16,777,216; the URIs of the files are distinct. A hidden folder and a linked folder are not in
`dirs` (the scan never enters them); a folder that holds only what is left out is an empty entry.

### File record

| Field | Type | Meaning |
|---|---|---|
| `uri` | str | `skill://<encoded path>/<encoded relative path>` (pure ASCII, R3) |
| `parts` | tuple of str | the path components below `folder`, decoded, used only to open the file |
| `folder` | str | the owning skill's folder (where the open starts) |
| `size` | int | raw bytes at the scan |
| `digest` | str | `sha256:` and 64 lowercase hex, over those bytes |
| `mime` | str | from the fixed table (R11); `text/markdown` for `SKILL.md` |
| `skill` | str | the owning skill's URI |

The record holds **no bytes**. A read opens the file again, checks it against `size` and
`digest`, and sends the bytes it hashed (R4).

### Directory record

| Field | Type | Meaning |
|---|---|---|
| `uri` | str | `skill://<encoded path>` for a skill root, `…/<encoded dir>` below it, no trailing slash |
| `children` | tuple of child | direct children sorted by name: `(uri, name, mime, is_dir)` |

One per directory of every served skill, root included: the root, every folder that holds a file,
every folder in the skill's `dirs`, and the folders above each of those, so that a child always has a
record. A prefix above skills is not a directory. A folder and a file of one URI are refused as a
`SkillsError` even when the folder is empty.

### Catalogue

The immutable snapshot the extension serves from.

| Field | Meaning |
|---|---|
| `generation` | random token, new on every successful scan; part of every cursor (R9: with a hash of the URI for a directory's cursor) |
| `skills` | skill records sorted by `uri` |
| `by_uri` | exact dictionary from a skill's `uri` to its record |
| `files` | exact dictionary from a file `uri` to its file record |
| `directories` | exact dictionary from a directory `uri` to its record |
| `left_out` | tuple of `LeftOut(path, reason)`; the reason is `hidden`, `symbolic link`, `not a regular file`, `undecodable name` or `unsafe name` (a control character, a line or paragraph separator, a bidirectional control, a backslash); the path has such characters escaped (R17) |

A handler reads `extension.catalogue` once and answers from that object. `refresh()` builds a new
one and assigns it; a failed scan assigns nothing (R5).

### State transitions

```
build:    scan → catalogue (generation g1)  → SDK registers one SkillFile per file URI
refresh:  scan → catalogue' (generation g2) → swap
            ├─ scan fails                    → old catalogue stays, SkillsError raised
            ├─ new file URIs, no server      → old catalogue stays, SkillsError raised
            └─ new file URIs, server given   → server.add_resource(...) for each, then swap
```

Cursors carry `g1`; after the swap they are refused (`-32602`).

## Wire models (`_wire.py`, the only module that knows the beta shapes)

Written against the beta text of 2026-11-21 (base protocol 2026-07-28).

| Model | Fields | Notes |
|---|---|---|
| `SkillResource` | `uri`, `digest`, `size` | one file of a skill |
| `Skill` | `uri`, `frontmatter`, `resources` (`list[SkillResource]`), `_meta` (never set here) | the server never writes `"dynamic"` |
| `ListSkillsResult` | `skills`, `nextCursor?`, `ttlMs`, `cacheScope`, `resultType="complete"` | `PaginatedResult` + `CacheableResult` |
| `GetSkillResult` | `skill`, `ttlMs`, `cacheScope`, `resultType="complete"` | `CacheableResult` |
| `ReadDirectoryResult` | `resources` (resource metadata), `nextCursor?`, `ttlMs`, `cacheScope`, `resultType="complete"` | `PaginatedResult` + `CacheableResult` |
| `GetSkillParams` | `uri`, `_meta` | `RequestParams` |
| `DirectoryParams` | `uri`, `cursor?`, `_meta` | `PaginatedRequestParams` |
| `ListSkillsRequest`, `GetSkillRequest`, `ReadDirectoryRequest` | the typed client requests | R2 |

On the client the result models hold `skills` as a list of raw objects, validated one by one.

## Client side

| Type | Fields | Meaning |
|---|---|---|
| `SkillFileRef` | `uri`, `size`, `digest` | a file the entry lists |
| `SkillItem` | `origin`, `uri`, `name`, `description`, `frontmatter`, `files` (tuple of `SkillFileRef`) | a validated entry; `key` is `(origin, uri)` |
| `Refused` | `uri` (or `None`), `check`, `reason` | an entry the listing could not accept (R13, R17: its name, description, URI of any scheme, files strictly inside its folder, listed once) |
| `SkillListing` | `skills` (tuple of `SkillItem`), `refused` (tuple of `Refused`) | what `list()` returns |
| `SkillContent` | `origin`, `uri`, `data` (bytes) | verified bytes, tagged; untrusted; `text()` decodes strictly |
| `LoadedSkill` | `item`, `instructions` (`SkillContent`, the `SKILL.md`) | what `load()` returns |
| `DirectoryEntry` | `origin`, `uri`, `name`, `mime`, `is_dir` | one child from a directory read |
| `SkillRefused` | `uri`, `check`, `reason` (an exception) | a failed check; no content returned |

`check` is one of: `declaration`, `entry`, `resources` (missing, dynamic, malformed), `limit`,
`unlisted`, `response`, `size`, `digest`, `frontmatter`, `directory`.

Nothing here has a field that is acted on: `frontmatter` is data.
