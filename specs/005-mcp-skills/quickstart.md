# Quickstart: validating MCP Skills

Run commands from `python/` unless a step says otherwise. They are the same commands CI runs
(`.github/workflows/python.yml`). Nothing here starts a network port: the round trips run over the
in-process transport of `tests/mcp_transport.py`.

## 1. Build and install

```sh
rm -rf dist && uv build
uv venv --python 3.11 ../.ci-venv
uv pip install --python ../.ci-venv dist/*.whl --group dev
```

The dev group brings `mcp>=2.3,<3` and `PyYAML>=6.0.3,<7`. Repeat with Python 3.12 and 3.13
before claiming done (SC-008).

## 2. The skills suite on the installed wheel

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider tests/test_skills_*.py
```

Expected: every test passes. In particular:
- the end-to-end test lists, gets and reads every file of the three fixture skills with a real MCP
  SDK client, and each byte equals the file on disk (SC-001);
- each tampering test is refused by the client with a named check and returns nothing (SC-002);
- each of the 12 or more unreachable URIs is `-32602` with no byte (SC-003);
- the recorded transport shows 0 `resources/read` after a listing and N after N files (SC-004);
- each build error names the folder and the reason, and a broken excluded skill starts (SC-005);
- the combined server passes its skills flows next to an R2C flow (SC-006);
- a server with more skills than a page lists each exactly once (SC-007).

## 3. The whole suite

```sh
../.ci-venv/bin/pytest -q -W error::UserWarning -p no:cacheprovider
```

Expected: everything of specs 001–004 still passes unchanged, with both replays reporting the same
counts as before (the skills code adds no example to `standard/`).

## 4. Core only, A2A only, MCP only

```sh
uv venv --python 3.11 ../.core-venv && uv pip install --python ../.core-venv dist/*.whl
../.core-venv/bin/python -I tests/core_only.py        # core only: ok

uv venv --python 3.11 ../.a2a-venv && uv pip install --python ../.a2a-venv "$(ls dist/*.whl)[a2a]"
../.a2a-venv/bin/python -I tests/a2a_only.py          # a2a only: ok

uv venv --python 3.11 ../.mcp-venv && uv pip install --python ../.mcp-venv "$(ls dist/*.whl)[mcp]"
../.mcp-venv/bin/python -I tests/mcp_only.py          # mcp only: ok (now also serves and loads a skill)
```

The first two must not need `PyYAML`; the third gets it from the `[mcp]` extra.

## 5. By hand (optional)

```python
import asyncio, pathlib, tempfile
from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from ext_r2c.mcp import SkillsClient, SkillsExtension

root = pathlib.Path(tempfile.mkdtemp())
(root / "refunds").mkdir()
(root / "refunds" / "SKILL.md").write_text(
    "---\nname: refunds\ndescription: Handle a refund request.\n---\nAsk for the order number first.\n")

server = MCPServer("docs", extensions=[SkillsExtension([root])])
# serve `server` over any transport the SDK offers; with a connected Client `c`:
#   skills = SkillsClient(c, origin="docs")
#   item = (await skills.list()).skills[0]
#   loaded = await skills.load(item)          # verified; loaded.instructions.text()
```

Expected: `list` returns one item whose `uri` is `skill://refunds/SKILL.md`; `load` returns its
`SKILL.md` after the size, digest and frontmatter checks. Edit the file on disk and call `load`
again: the server answers `-32603` (the skills changed); call `refresh()` on the extension and the
new digest is served.

## 6. Public-repo hygiene

Before every commit, the maintainer's leak scan (its pattern is kept outside the repository)
runs over the added lines; fixtures use invented names, no local paths and `example.com` only.
