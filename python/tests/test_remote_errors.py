"""A mistake fails when the `Remote` is built (spec 007, story 2; research R6 and R7).

Section 1 is `RemoteError` itself. The later sections are one test per row of the build-problem
table, the order of the three error kinds, and what a message may say.
"""

from __future__ import annotations

import pytest
from ext_r2c import RemoteError

# --- 1. `RemoteError` -----------------------------------------------------------------------------


def test_a_remote_error_is_a_value_error_that_lists_its_problems() -> None:
    error = RemoteError(["url: not given; pass the public address of the app", "tools: MCP is not exposed"])
    assert isinstance(error, ValueError)
    assert error.problems == ("url: not given; pass the public address of the app", "tools: MCP is not exposed")
    assert isinstance(error.problems, tuple) and all(isinstance(p, str) for p in error.problems)


def test_its_text_says_what_failed_and_lists_one_problem_per_line() -> None:
    error = RemoteError(["agent: not given", "url: not given"])
    lines = str(error).splitlines()
    assert lines[0].startswith("Remote cannot be built:") and "2 problems" in lines[0]
    assert lines[1:] == ["- agent: not given", "- url: not given"]
    assert str(RemoteError(["agent: not given"])).splitlines()[0] == "Remote cannot be built: 1 problem"


def test_a_remote_error_needs_at_least_one_problem() -> None:
    with pytest.raises(ValueError, match="at least one problem"):
        RemoteError([])
    with pytest.raises(TypeError):
        RemoteError("agent: not given")  # a bare string would be read as a list of letters
    with pytest.raises(TypeError):
        RemoteError(["agent: not given", 3])  # type: ignore[list-item]


def test_a_remote_error_can_be_raised_and_caught_as_a_value_error() -> None:
    with pytest.raises(ValueError) as caught:
        raise RemoteError(["agent: not given"])
    assert caught.value.args == (str(caught.value),)
