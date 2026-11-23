"""``RemoteError``: every configuration problem of a ``Remote``, in one error (spec 007, D10)."""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["RemoteError"]


class RemoteError(ValueError):
    """A ``Remote`` that cannot be built. ``problems`` lists every problem found, so the owner
    fixes them in one pass. Each one reads ``"<argument>: <what is wrong>; <what to do>"`` and
    carries no value the owner typed."""

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
