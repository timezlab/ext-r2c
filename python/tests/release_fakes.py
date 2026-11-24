"""A fake `gh` for the release-script tests (spec 008, research R3). Not collected by pytest.

`FakeGh` writes an executable `gh` into a temporary directory, puts that directory first on `PATH`, and
keeps its state (releases, assets, the failures to inject) in a JSON file the fake reads and writes on
every call. It implements **exactly** the calls the scripts are allowed to make and refuses any other with
exit status 99, so a new call has to be added here first. Every call, allowed or not, is appended to a log
the test reads with `calls()`.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

FAKE_SOURCE = r'''#!{python}
"""The fake gh. State: $FAKE_GH_STATE (JSON). Log: $FAKE_GH_LOG (one JSON list per line)."""
import json
import os
import sys

state_path = os.environ["FAKE_GH_STATE"]
log_path = os.environ["FAKE_GH_LOG"]
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
    fail("fake gh: unexpected api path: " + path, 99)


if argv[:1] == ["api"] and len(argv) == 2:
    api(argv[1])
    sys.exit(0)

fail("fake gh: unexpected call: " + " ".join(argv), 99)
'''


class FakeGh:
    """The fake `gh` on `PATH`, with a state the test can set and a log it can read."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bin = tmp_path / "fake-bin"
        self.bin.mkdir()
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

    # --- the state ---------------------------------------------------------------------------------

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def update(self, **changes: object) -> None:
        state = self.state()
        state.update(changes)
        self.state_path.write_text(json.dumps(state))

    def add_release(self, tag: str, *, draft: bool = False, prerelease: bool = True) -> None:
        state = self.state()
        state["releases"][tag] = {"draft": draft, "prerelease": prerelease}
        self.state_path.write_text(json.dumps(state))

    # --- the log -----------------------------------------------------------------------------------

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]
