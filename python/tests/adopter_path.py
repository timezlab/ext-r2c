"""Run in the adopter's venv: the wheel with `[a2a,mcp,langgraph]` and `uvicorn`, no dev group, no pytest.

It does what the example's README tells an adopter to do (spec 008, FR-008): from the example's folder, run
`python main.py --auto` with no model named, so the scripted stand-in answers and no key or network is used.
It passes when the example ends well and prints the two replies the README shows.

Not collected by pytest (no `test_` prefix). CI runs it from `python/` as:
    python -I tests/adopter_path.py
It prints `adopter path: ok`, or the last lines of what went wrong and exits 1.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "langgraph_agent"
TIMEOUT_SECONDS = 120
REPLIES = (
    "Reply: Stock report for 2026-10: ACME 120, GLOBEX 40. Published.",
    "Reply: The reporter says: Stock report for 2026-10: ACME 120, GLOBEX 40. Not published: the approval was refused.",
)


def fail(message: str, output: str = "") -> None:
    print(f"adopter path: FAILED: {message}", file=sys.stderr)
    for line in output.strip().splitlines()[-25:]:
        print(f"    {line}", file=sys.stderr)
    raise SystemExit(1)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> None:
    if importlib.util.find_spec("pytest") is not None:
        fail("pytest is installed: this is not the adopter's venv (no dev group)")
    if not (EXAMPLE / "main.py").is_file():
        fail(f"the example is not at {EXAMPLE}; run this from a checkout of the tagged source")
    env = {k: v for k, v in os.environ.items() if k != "R2C_EXAMPLE_MODEL"}
    env["PLANNER_URL"] = f"http://127.0.0.1:{free_port()}"
    env["REPORTER_URL"] = f"http://127.0.0.1:{free_port()}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # leave no __pycache__ in the tagged source
    try:
        done = subprocess.run(
            [sys.executable, "main.py", "--auto"],
            cwd=EXAMPLE,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as expired:
        output = (expired.stdout or b"").decode(errors="replace") if isinstance(expired.stdout, bytes) else (expired.stdout or "")
        fail(f"`python main.py --auto` did not finish in {TIMEOUT_SECONDS} s", output)
    output = done.stdout + done.stderr
    if done.returncode != 0:
        fail(f"`python main.py --auto` exited with status {done.returncode}", output)
    for reply in REPLIES:
        if reply not in done.stdout:
            fail(f"the output does not hold the reply the README shows: {reply!r}", output)
    print("adopter path: ok")


if __name__ == "__main__":
    main()
