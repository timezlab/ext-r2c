"""The documents of the first pre-release (spec 008): the known limits, the install address in every README
and the maintainer's runbook. They are read from the repository checkout, like the example.
"""

from __future__ import annotations

import re

import pytest

from release_fixtures import REPO

BLOB = "https://github.com/timezlab/ext-r2c/blob/main/"
KNOWN_LIMITS = REPO / "docs" / "known-limits.md"

# One word that identifies each of the seven limits of FR-015.
LIMIT_WORDS = ("memory", "authentication", "loopback", "hop", "Tasks", "PyPI", "draft")


def slugs(markdown: str) -> set[str]:
    """The anchors GitHub gives the headings of a Markdown file."""
    found = set()
    for heading in re.findall(r"^#{1,6} +(.+?) *$", markdown, flags=re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).strip().replace(" ", "-")
        found.add(slug)
    return found


@pytest.fixture(scope="module")
def known_limits() -> str:
    if not KNOWN_LIMITS.is_file():
        pytest.fail(f"{KNOWN_LIMITS} is missing; run the tests from a repository checkout", pytrace=False)
    return KNOWN_LIMITS.read_text()


# --- section 1: docs/known-limits.md -------------------------------------------------------------------


def test_known_limits_starts_with_one_title_line(known_limits: str) -> None:
    lines = known_limits.splitlines()
    assert lines[0].startswith("# ")
    assert not any(line.startswith("# ") for line in lines[1:]), "one title only: the notes supply their own headings"


def test_known_limits_has_one_bullet_for_each_of_the_seven_limits(known_limits: str) -> None:
    bullets = [line for line in known_limits.splitlines() if line.startswith("- ")]
    assert len(bullets) == 7
    matched = []
    for word in LIMIT_WORDS:
        hits = [i for i, bullet in enumerate(bullets) if word in bullet]
        assert hits, f"no bullet speaks of {word!r}"
        matched.append(hits[0])
    assert len(set(matched)) == 7, "each limit has its own bullet"


def test_every_bullet_links_to_the_detail_and_every_link_is_real(known_limits: str) -> None:
    bullets = [line for line in known_limits.splitlines() if line.startswith("- ")]
    for bullet in bullets:
        links = re.findall(r"\]\((https://[^)]+)\)", bullet)
        assert len(links) == 1, f"a bullet has exactly one link to its detail: {bullet!r}"
        url = links[0]
        assert url.startswith(BLOB), url
        path, _, anchor = url[len(BLOB) :].partition("#")
        target = REPO / path
        assert target.is_file(), f"{path} does not exist"
        if anchor:
            assert anchor in slugs(target.read_text()), f"{path} has no heading #{anchor}"
