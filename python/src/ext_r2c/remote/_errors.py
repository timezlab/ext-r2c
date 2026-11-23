"""``RemoteError``: every configuration problem of a ``Remote``, in one error (spec 007, D10)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

__all__ = ["RemoteError"]


class RemoteError(ValueError):
    """A ``Remote`` that cannot be built. ``problems`` lists every problem found, so the owner
    fixes them in one pass. Each one reads ``"<argument>: <what is wrong>; <what to do>"`` and
    carries no value the owner typed, except the name of a tool, a door or a keyword they chose
    (contracts/remote-api.md). The error can be pickled and copied."""

    problems: tuple[str, ...]

    def __init__(self, problems: Iterable[str]) -> None:
        if isinstance(problems, str):
            raise TypeError("RemoteError takes a list of problems, not one string")
        listed = tuple(problems)
        if not listed:
            raise ValueError("a RemoteError lists at least one problem")
        for problem in listed:
            if not isinstance(problem, str):
                raise TypeError(f"a problem is a str, not {type(problem).__name__}")
        self.problems = listed
        count = f"{len(listed)} problem" + ("" if len(listed) == 1 else "s")
        super().__init__("\n".join([f"Remote cannot be built: {count}", *(f"- {p}" for p in listed)]))

    def __reduce__(self) -> tuple[Any, ...]:
        # `args` holds the formatted text, which `__init__` would refuse as a bare string.
        return (type(self), (list(self.problems),))
