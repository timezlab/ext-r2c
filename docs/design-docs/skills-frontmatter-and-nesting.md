# A small YAML reader in `[mcp]`, and the nearest `SKILL.md` wins

**Status:** accepted, 2026-11-22 (spec `005-mcp-skills`; the maintainer approved its draft
decisions D1–D6 on 2026-11-21).

## Context

MCP Skills (SEP-2640, Beta) serves a folder of `SKILL.md` files. Each `SKILL.md` starts with a YAML
header (`name`, `description`, and any field the author adds). The extension passes that header on
"verbatim" as JSON, and a caller **must** check it against the file it fetched. So two sides read
the same YAML: the server, to build the entry it lists, and the caller's client, to check that entry
against the bytes it got. If they read it differently, a good skill is refused, or a tampered one
is accepted.

The MCP Python SDK brings no YAML package. A skills folder may also hold a `SKILL.md` inside another
skill (a worked example, a template, a vendored copy), and the extension says a server MAY publish
a nested skill as its own entry, in which case the outer entry's `resources` lists the nested files
too.

## Decision

1. **One YAML reader, in the `[mcp]` extra, shared by server and client.** `[mcp]` depends on
   `PyYAML>=6.0.3,<7`. The core and `[a2a]` do not need it (`core_only.py` and `a2a_only.py` run
   without it). The package was vetted before it was added (MIT, no install script, no dependency,
   no `MAL-` advisory, none of the eight old advisories applies to 6.0.3; the vet was repeated on
   the day it was added).
2. **The reader is smaller than YAML.** A header is data, so the reader builds only strings, numbers,
   booleans, null, lists and mappings with string keys, and refuses the rest. It is a pure-Python
   `SafeLoader` subclass whose resolvers and constructors are cut to a whitelist:
   - **Refused while the document is composed**, so nothing is built from it: an anchor, an alias,
     a merge key, a tag it does not know (no Python object can be built), a duplicate key, a
     document nested deeper than 32 containers; and a header larger than 64 KiB is refused before
     it is parsed.
   - **Numbers and booleans are JSON-like only.** `true` and `false`; integers such as `3` and
     `-4`; floats such as `1.5` and `2.5e3`; `null`. So `yes`, `no`, `on`, `off`, `12:30`, `0755`,
     `1_000`, `0x1f` and a date such as `2026-01-02` stay **the text the author wrote**. `.inf` and
     `.nan` are refused (JSON cannot carry them).
   - Every failure is one `FrontmatterError` whose `reason` is from a fixed set. The message is
     that reason and nothing else: no file text, no line, no path.
3. **The server accepts a `name` of `^[a-z0-9]+(-[a-z0-9]+)*$`, at most 64 characters** (ASCII only,
   a v1 limit), equal to the folder's name, and a non-empty `description` of at most 1024
   characters. Every other field is passed through unchecked. The client does not apply the
   ASCII character rule, so it does not refuse a valid skill from another server; it applies a looser
   one (1 to 64 printable characters with no space, `/` or `\`, and a description of 1 to 1024
   characters), so an entry no server could have served is refused (amended 2026-11-22, below).
4. **The nearest `SKILL.md` on a path wins.** A folder that holds a regular file named exactly
   `SKILL.md` is a skill folder. A `SKILL.md` deeper in it is an ordinary file of the outer skill:
   it is listed in the outer entry's `resources`, read with `resources/read`, and named
   `SKILL.md` in a directory, but it is not a skill of its own and its folder is not scanned for
   skills. A server that wants a nested skill served puts it in a sibling folder.
5. **A skill's path is the folder's path below its root**, so `skills/team/billing/refunds` under
   the root `skills` is `skill://team/billing/refunds/SKILL.md`, and its last segment equals `name`.

## Alternatives

- **A separate `[skills]` extra for PyYAML.** Cleaner for someone who serves no skills, but one more
  extra to document, and `Remote` (spec 007) would have to name it in its build error.
  Rejected: `[mcp]` is the extra a skills server installs.
- **A hand-written subset parser.** No dependency, but a valid skill the parser misreads is served
  wrongly, and the client, using the same parser, would misread it the same way, so the check would
  agree with the error. Rejected.
- **`ruamel.yaml`.** A larger package with the same vet to do and round-trip features we do not use.
- **Full YAML 1.1 scalars (PyYAML's defaults).** `no` becomes `False`, `12:30` becomes 750, `0755`
  becomes 493, a date becomes an object: the header would no longer be "what the author wrote". The
  author's `name: no` would be refused, and the same header read by a client in another language
  would differ. Rejected for the JSON-like grammar above.
- **Publish nested skills as their own entries.** Allowed by the extension, but then one file has
  two entries in two manifests and is counted twice against the 512-file and 16 MiB limits.
  The simpler rule is conformant, because the text only describes what a server that publishes
  nested skills does, and it says a host never acts on a nested `SKILL.md`'s header, which is what
  serving it as an ordinary file amounts to.

## Consequences

- **Better:** one reader on both sides, so a check cannot disagree with the entry it checks; a
  hostile header cannot grow when it is read, build an object, or hide a duplicate key; the header
  the caller sees is the text the author wrote; one file belongs to one skill.
- **Worse:** `[mcp]` carries a dependency a server with no skills never uses. The reader is a
  subset: a valid YAML header that uses an alias, a merge key, a tag or a YAML 1.1 dialect is
  refused with a named reason, and the client compares the entry's header with what *this* reader
  makes of the file, so an entry from another server that renders a YAML timestamp differently
  from the author's text is refused (a false refusal, the safe direction). A nested skill is not
  discoverable on its own; ASCII-only names are stricter than the skill format's prose.
- **Must now be true:**
  - the server and the client import one reader (`_frontmatter.py`) and neither carries a copy;
  - the reader's whitelist is tested with the dialects above (`yes`, `12:30`, `0755`, `1_000`, a
    date, `.nan`) and with the hostile documents (alias, merge key, tag, duplicate key, depth, size),
    and its messages are tested to carry no file text;
  - `ext-r2c` and `ext-r2c[a2a]` keep working without PyYAML (`core_only.py`, `a2a_only.py`);
  - the PyYAML bound stays `>=6.0.3,<7` and the vet is repeated before the bound moves;
  - the nearest-`SKILL.md` rule and the ASCII `name` rule are documented as v1 limits in
    `python/README.md` and in `specs/005-mcp-skills/contracts/skills-api.md`.

## Amended 2026-11-22 (the outside review of spec 005, `research.md` R17)

- The reader's grammar is unchanged; the "Worse" paragraph is wider than it says. The client's
  comparison fails for **any** value YAML 1.1 types and this reader keeps as text (`yes` as `true`,
  `0755` as 493, `0x1f` as 31, `12:30` as 750, a timestamp), not only for a timestamp, and the
  contract and the README say so. A quoted scalar is always text, and an explicit core tag
  (`!!int`, `!!bool`, `!!float`, `!!str`) is accepted for what it says.
- Point 3 above: the client now refuses a name or a description outside the lengths in the point,
  and a listed file that is not strictly inside the skill's folder; the scheme of the entry's URI is
  not checked (the extension privileges none).
