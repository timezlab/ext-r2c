"""A fake `gh` for the release-script tests (spec 008, research R3). Not collected by pytest.

`FakeGh` writes an executable `gh` into a temporary directory, puts that directory first on `PATH`, and
keeps its state (releases, assets, the failures to inject) in a JSON file the fake reads and writes on
every call; the bytes of the assets live in a folder beside it. It implements **exactly** the calls the
scripts are allowed to make (the table of research R3, flags included) and refuses any other with exit
status 99, so a new call has to be added here first. Every call, allowed or not, is appended to a log the
test reads with `calls()`.

A write to a *published* release (an edit, an upload, a deleted asset) is also refused, with exit status 98,
and recorded in `violations()`: a script that tries it fails visibly, and a test can assert there were none.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

FAKE_SOURCE = r'''#!{python}
"""The fake gh. State: $FAKE_GH_STATE (JSON). Log: $FAKE_GH_LOG (one JSON list per line). Assets: $FAKE_GH_STORE."""
import json
import os
import sys
from pathlib import Path

state_path = os.environ["FAKE_GH_STATE"]
log_path = os.environ["FAKE_GH_LOG"]
store = Path(os.environ["FAKE_GH_STORE"])
argv = sys.argv[1:]

with open(log_path, "a") as log:
    log.write(json.dumps(argv) + "\n")

with open(state_path) as f:
    state = json.load(f)


def save():
    with open(state_path, "w") as f:
        json.dump(state, f)


def fail(message, code=1):
    sys.stderr.write(message + "\n")
    sys.exit(code)


def unexpected(why):
    state.setdefault("unexpected", []).append(argv)
    save()
    fail("fake gh: unexpected call (" + why + "): " + " ".join(argv), 99)


state["calls"] = state.get("calls", 0) + 1
save()
fail_at = state.get("fail_at")
if fail_at is not None and state["calls"] == fail_at:
    fail("gh: injected failure at call %d (HTTP 502)" % fail_at)
if state.get("network_down"):
    fail("error connecting to api.github.com")

releases = state.setdefault("releases", {})


def api(path):
    # repos/OWNER/NAME/releases/tags/TAG : 200 only for a published release, 404 for a draft or none.
    parts = path.split("/")
    if len(parts) == 6 and parts[0] == "repos" and parts[3] == "releases" and parts[4] == "tags":
        release = releases.get(parts[5])
        if release is None or release["draft"]:
            fail("gh: Not Found (HTTP 404)")
        print(json.dumps({"tag_name": parts[5], "draft": False, "prerelease": release["prerelease"]}))
        return
    unexpected("api path")


if argv[:1] == ["api"] and len(argv) == 2:
    api(argv[1])
    sys.exit(0)

if argv[:1] != ["release"]:
    unexpected("not a release call")

VALUE_FLAGS = {"--limit", "--json", "--title", "--notes-file", "--pattern", "--dir", "--repo"}
positional, flags = [], {}
rest = argv[1:]
i = 0
while i < len(rest):
    word = rest[i]
    if word in VALUE_FLAGS:
        if i + 1 >= len(rest):
            unexpected("flag without a value")
        flags[word] = rest[i + 1]
        i += 2
    elif word.startswith("--"):
        flags[word] = True
        i += 1
    else:
        positional.append(word)
        i += 1
if "--repo" not in flags:
    unexpected("no --repo")
del flags["--repo"]
sub = positional[0] if positional else ""


def need(release_exists=True):
    tag = positional[1] if len(positional) > 1 else ""
    release = releases.get(tag)
    if release_exists and release is None:
        fail("release not found", 1)
    return tag, release


def write_to(release):
    if not release["draft"]:
        state.setdefault("violations", []).append(argv)
        save()
        fail("fake gh: a write to a published release: " + " ".join(argv), 98)


def asset_names(release):
    return release.setdefault("assets", [])


if sub == "list" and len(positional) == 1 and flags == {"--limit": "200", "--json": "tagName,isDraft,isPrerelease"}:
    rows = [{"tagName": tag, "isDraft": r["draft"], "isPrerelease": r["prerelease"]} for tag, r in releases.items()]
    print(json.dumps(rows))
elif sub == "create" and len(positional) == 2:
    tag = positional[1]
    notes = flags.get("--notes-file")
    if flags != {"--draft": True, "--prerelease": True, "--latest=false": True, "--verify-tag": True,
                 "--title": tag, "--notes-file": notes}:
        unexpected("create flags")
    if tag in releases:
        fail("a release with the same tag name already exists: " + tag, 1)
    releases[tag] = {"draft": True, "prerelease": True, "notes": Path(notes).read_text(), "assets": []}
    save()
    print("https://example.invalid/releases/tag/" + tag)
elif sub == "edit" and len(positional) == 2:
    tag, release = need()
    if set(flags) == {"--notes-file", "--prerelease", "--latest=false"} and flags["--prerelease"] is True:
        write_to(release)
        release["notes"] = Path(flags["--notes-file"]).read_text()
        release["prerelease"] = True
    elif flags == {"--draft=false": True, "--prerelease": True, "--latest=false": True}:
        write_to(release)
        if not state.get("publish_is_noop"):
            release["draft"] = False
    else:
        unexpected("edit flags")
    save()
elif sub == "view" and len(positional) == 2 and flags == {"--json": "assets"}:
    tag, release = need()
    sizes = [{"name": n, "size": len((store / tag / n).read_bytes())} for n in asset_names(release)]
    print(json.dumps({"assets": sizes}))
elif sub == "delete-asset" and len(positional) == 3 and flags == {"--yes": True}:
    tag, release = need()
    write_to(release)
    name = positional[2]
    if name not in asset_names(release):
        fail("asset not found: " + name, 1)
    release["assets"].remove(name)
    (store / tag / name).unlink()
    save()
elif sub == "upload" and len(positional) >= 3 and flags == {"--clobber": True}:
    tag, release = need()
    write_to(release)
    (store / tag).mkdir(parents=True, exist_ok=True)
    for file in positional[2:]:
        name = os.path.basename(file)
        if name in state.get("lose_on_upload", []):
            continue
        (store / tag / name).write_bytes(Path(file).read_bytes())
        if name not in asset_names(release):
            release["assets"].append(name)
    save()
elif sub == "download" and len(positional) == 2 and set(flags) == {"--pattern", "--dir"} and flags["--pattern"] == "*":
    tag, release = need()
    target = Path(flags["--dir"])
    target.mkdir(parents=True, exist_ok=True)
    altered = state.get("altered_on_download", {})
    for name in asset_names(release):
        data = altered[name].encode() if name in altered else (store / tag / name).read_bytes()
        (target / name).write_bytes(data)
else:
    unexpected("not in the table")
'''

WRITE_SUBCOMMANDS = {"create", "edit", "delete-asset", "upload", "delete"}


class FakeGh:
    """The fake `gh` on `PATH`, with a state the test can set and a log it can read."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bin = tmp_path / "fake-bin"
        self.bin.mkdir()
        self.store = tmp_path / "fake-gh-store"
        self.store.mkdir()
        self.state_path = tmp_path / "fake-gh-state.json"
        self.log_path = tmp_path / "fake-gh-log.jsonl"
        self.log_path.write_text("")
        self.state_path.write_text(json.dumps({"releases": {}}))
        gh = self.bin / "gh"
        gh.write_text(FAKE_SOURCE.replace("{python}", sys.executable))
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_GH_STATE", str(self.state_path))
        monkeypatch.setenv("FAKE_GH_LOG", str(self.log_path))
        monkeypatch.setenv("FAKE_GH_STORE", str(self.store))

    # --- the state ---------------------------------------------------------------------------------

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def update(self, **changes: object) -> None:
        state = self.state()
        state.update(changes)
        self.state_path.write_text(json.dumps(state))

    def add_release(
        self,
        tag: str,
        *,
        draft: bool = False,
        prerelease: bool = True,
        assets: dict[str, bytes] | None = None,
        notes: str = "",
    ) -> None:
        state = self.state()
        names = sorted(assets or {})
        state["releases"][tag] = {"draft": draft, "prerelease": prerelease, "notes": notes, "assets": names}
        self.state_path.write_text(json.dumps(state))
        (self.store / tag).mkdir(parents=True, exist_ok=True)
        for name, data in (assets or {}).items():
            (self.store / tag / name).write_bytes(data)

    def release(self, tag: str) -> dict | None:
        return self.state()["releases"].get(tag)

    def asset(self, tag: str, name: str) -> bytes:
        return (self.store / tag / name).read_bytes()

    def fail_at(self, call_number: int) -> None:
        """The call with this 1-based number (every call counts, `api` included) exits 1."""
        self.update(fail_at=call_number)

    def alter_on_download(self, name: str, text: str) -> None:
        """A download of this asset returns `text` instead of what was uploaded."""
        state = self.state()
        state.setdefault("altered_on_download", {})[name] = text
        self.state_path.write_text(json.dumps(state))

    def lose_on_upload(self, name: str) -> None:
        """An upload of this file succeeds and stores nothing."""
        state = self.state()
        state.setdefault("lose_on_upload", []).append(name)
        self.state_path.write_text(json.dumps(state))

    def publish_does_nothing(self) -> None:
        """`release edit --draft=false` succeeds and the release stays a draft."""
        self.update(publish_is_noop=True)

    def call_count(self) -> int:
        return int(self.state().get("calls", 0))

    # --- the log -----------------------------------------------------------------------------------

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def writes(self) -> list[list[str]]:
        """The calls that change a release: `release create`, `edit`, `delete-asset`, `upload`, `delete`."""
        return [c for c in self.calls() if c[:1] == ["release"] and c[1:2] and c[1] in WRITE_SUBCOMMANDS]

    def unexpected(self) -> list[list[str]]:
        """The calls the table refused (exit 99)."""
        return self.state().get("unexpected", [])

    def violations(self) -> list[list[str]]:
        """The writes to a published release the fake refused (exit 98)."""
        return self.state().get("violations", [])
