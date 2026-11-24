# Contract: what a release carries and says

**Plan**: [../plan.md](../plan.md) | **Research**: [../research.md](../research.md) R8, R11, R12

## The three assets

For a release `vX.YaN`, with `V = X.YaN`:

| Asset | Name |
|---|---|
| wheel | `ext_r2c-V-py3-none-any.whl` |
| source distribution | `ext_r2c-V.tar.gz` |
| checksum list | `SHA256SUMS` |

No other asset is attached. The address of an asset is
`https://github.com/OWNER/NAME/releases/download/vV/<asset name>` (for this repository,
`OWNER/NAME` is `timezlab/ext-r2c`).

## `SHA256SUMS`

The format `sha256sum` writes and `sha256sum -c` reads:

```text
<64 lowercase hex digits>  ext_r2c-V-py3-none-any.whl
<64 lowercase hex digits>  ext_r2c-V.tar.gz
```

Two spaces between the digest and the name; lines sorted by name; a final newline; no line for itself; no
path in a name. Verify with `sha256sum -c SHA256SUMS` (Linux) or `shasum -a 256 -c SHA256SUMS` (macOS) in the
folder that holds the files. It is written before any test (research R12) and is what every later step
compares against.

## The install line

One line, as an address with the extras the example needs:

```text
ext-r2c[a2a,mcp,langgraph] @ https://github.com/timezlab/ext-r2c/releases/download/vV/ext_r2c-V-py3-none-any.whl
```

- It installs with `pip` and `uv`, in a `requirements.txt` or on the command line, with **no `--pre`**.
- No version range works (`ext-r2c>=0.1` finds nothing): the address is the pin, and it changes with each
  release.
- The bare name `ext-r2c` is **not** this project's address: PyPI has no package of that name today and
  anyone may register it. Every document says so next to the line.
- It appears in the root `README.md`, `python/README.md`, `examples/langgraph_agent/README.md` and the
  release notes; a test keeps the three READMEs' address equal to the installed wheel's version.

## The release notes

Written by `notes.py`, in this order, nothing typed at release time:

```markdown
## Status

<scripts/release/status-block.md with {{tag}}, {{version}}, {{wheel}}, {{address}} filled>

## Known limits

<docs/known-limits.md, every line after its title, verbatim>

## Changes in V

<the body of "## [V] - DATE" in CHANGELOG.md>
```

**The status block says**, in a few short lines: this is an alpha; the standard's `v1` is a draft until its
first outside adopter, so names and shapes may change; the package's version (SemVer) is separate from the
standard's version; the install line; that the bare PyPI name is not this project; and where the example to
run lives (`examples/langgraph_agent/`, from the tagged source).

**The known limits say** (FR-015, one bullet each, each linking the detail in `python/README.md`):
- state a restart loses (checkpointer, task store, request-state keys) is in memory unless the owner brings a
  durable one;
- no authentication: identity belongs to the deployment;
- the MCP door answers only loopback hosts until the public host is named;
- no relay of a question through more than one hop, and no guard against agents calling each other's
  agents;
- MCP Tasks is not supported;
- the package is not on PyPI;
- v1 is a draft and names may change.

## The release object

Title the tag; pre-release; not latest; draft until every asset is verified (data-model 2); the notes above.
