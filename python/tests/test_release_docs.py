"""The documents of the first pre-release (spec 008): the known limits, the install address in every README
and the maintainer's runbook. They are read from the repository checkout, like the example.
"""

from __future__ import annotations

import re
from importlib.metadata import metadata, version
from pathlib import Path

import pytest

from release_fixtures import REPO, load_script

REPOSITORY = "timezlab/ext-r2c"
BLOB = f"https://github.com/{REPOSITORY}/blob/main/"
KNOWN_LIMITS = REPO / "docs" / "known-limits.md"
RELEASING = REPO / "docs" / "releasing.md"
AGENTS = REPO / "AGENTS.md"
ROOT_README = REPO / "README.md"
PYTHON_README = REPO / "python" / "README.md"
EXAMPLE_README = REPO / "examples" / "langgraph_agent" / "README.md"
READMES = {"root": ROOT_README, "python": PYTHON_README, "example": EXAMPLE_README}
EXTRAS_LINE = "ext-r2c[a2a,mcp,langgraph]"

# The nine steps of the maintainer's runbook (FR-017, research R8), in order: each is a word that its own
# `##` heading must hold, as a whole word and in this order.
RUNBOOK_STEPS = (
    ("number", r"\bnumber\b"),
    ("version commit", r"\bversion commit\b"),
    ("private-token scan", r"\bscan\b"),
    ("push", r"\bpush\b"),
    ("manual run", r"\bmanual run\b"),
    ("tag", r"\btag\b"),
    ("afterwards", r"\bafterwards\b"),
    ("failed run", r"\bfails\b"),
    ("published mistake", r"\bpublished\b"),
)

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


# --- what sections 2 and 3 share ------------------------------------------------------------------------


def read_doc(path: Path) -> str:
    if not path.is_file():
        pytest.fail(f"{path} is missing; run the tests from a repository checkout", pytrace=False)
    return path.read_text()


def shown(path: Path) -> str:
    return str(path.relative_to(REPO))


def without_fences(markdown: str) -> str:
    """The prose of a Markdown file: its fenced code blocks hold comment lines that are not headings."""
    return re.sub(r"^```.*?^```[^\n]*$", "", markdown, flags=re.M | re.S)


@pytest.fixture(scope="module")
def wheel_version() -> str:
    """The version of the installed wheel: the number the READMEs, the changelog and the notes must name."""
    return version("ext-r2c")


def wheel_address(v: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/v{v}/ext_r2c-{v}-py3-none-any.whl"


# --- section 2: the install address and the sentence about PyPI, in every README ------------------------


def test_the_address_written_in_the_readmes_is_the_one_the_release_scripts_make(wheel_version: str) -> None:
    common = load_script("release_common")
    assert wheel_address(wheel_version) == common.address(REPOSITORY, wheel_version)


@pytest.mark.parametrize("name", READMES)
def test_each_readme_has_the_install_line_of_the_wheel_it_ships_with(name: str, wheel_version: str) -> None:
    line = f"{EXTRAS_LINE} @ {wheel_address(wheel_version)}"
    assert line in read_doc(READMES[name]), f"{shown(READMES[name])} has no install line {line!r}"


@pytest.mark.parametrize("name", READMES)
def test_no_readme_names_the_address_of_another_release(name: str, wheel_version: str) -> None:
    found = set(re.findall(r"https://github\.com/[^\s\"')]*/releases/download/[^\s\"')]+", read_doc(READMES[name])))
    stale = sorted(found - {wheel_address(wheel_version)})
    assert not stale, f"{shown(READMES[name])} names another release: {stale}"


def test_no_install_command_in_the_documents_names_the_bare_package() -> None:
    """`pip install ext-r2c` would fetch whatever PyPI holds under that name: every line says where from."""
    command = re.compile(r"\b(?:uv pip install|pip install|uv add)\b")
    bare = []
    for path in [*READMES.values(), *sorted((REPO / "docs").rglob("*.md"))]:
        for number, line in enumerate(read_doc(path).splitlines(), 1):
            if command.search(line) and "ext-r2c" in line and "@ https://" not in line and ".whl" not in line:
                bare.append(f"{shown(path)}:{number}: {line.strip()}")
    assert not bare, "an install line without an address or a wheel path:\n" + "\n".join(bare)


@pytest.mark.parametrize("name", ["root", "python"])
def test_both_readmes_say_the_bare_name_on_pypi_is_not_this_project(name: str) -> None:
    text = " ".join(read_doc(READMES[name]).split())
    assert "bare name `ext-r2c` on PyPI is not this project" in text, shown(READMES[name])


@pytest.mark.parametrize("name", ["root", "python"])
def test_both_readmes_link_the_known_limits(name: str) -> None:
    readme = READMES[name]
    links = re.findall(r"\]\(([^)\s#]*known-limits\.md)(?:#[^)]*)?\)", read_doc(readme))
    assert links, f"{shown(readme)} does not link docs/known-limits.md"
    for target in links:
        if target.startswith(BLOB):
            resolved = REPO / target[len(BLOB) :]
        else:
            assert "://" not in target, f"{target} is not this repository's page"
            resolved = readme.parent / target
        assert resolved.resolve() == KNOWN_LIMITS.resolve(), f"{target} is not docs/known-limits.md"


@pytest.mark.parametrize("name", ["root", "python"])
def test_both_readmes_say_alpha_and_not_pre_alpha(name: str) -> None:
    text = read_doc(READMES[name])
    assert "pre-alpha" not in text.lower(), f"{shown(READMES[name])} still says pre-alpha"
    assert re.search(r"\balpha\b", text, flags=re.I), f"{shown(READMES[name])} does not say alpha"


# --- section 3: the runbook, the layout, the metadata, the changelog and the notes ---------------------


def test_the_runbook_has_a_heading_for_each_step_in_order() -> None:
    found = re.findall(r"^#{2,6} +(.+?) *$", without_fences(read_doc(RELEASING)), flags=re.M)
    position = -1
    for step, pattern in RUNBOOK_STEPS:
        hits = [i for i, heading in enumerate(found) if re.search(pattern, heading, flags=re.I)]
        assert hits, f"docs/releasing.md has no heading for the step '{step}' (a heading with {pattern})"
        later = [i for i in hits if i > position]
        assert later, f"the heading for '{step}' comes before the heading of the step above it"
        position = later[0]


def test_the_runbook_holds_the_commands_and_the_promises_it_makes() -> None:
    text = " ".join(read_doc(RELEASING).split())
    for needle in (
        "gh workflow run release.yml --ref main",
        "git tag -a v",
        "same sitting",
        "not in this repository",
        "known-limits.md",
    ):
        assert needle in text, f"docs/releasing.md does not hold {needle!r}"
    assert "gh release create" not in text, "the workflow creates the release; the maintainer never does by hand"
    assert text.index("gh workflow run release.yml") < text.index("git tag -a v"), "the manual run comes before the tag"


def test_agents_md_links_the_runbook_and_the_known_limits_and_stays_short() -> None:
    text = read_doc(AGENTS)
    for path in ("docs/releasing.md", "docs/known-limits.md"):
        assert re.search(rf"^\|.*`{re.escape(path)}`", text, flags=re.M), f"AGENTS.md has no Docs row for {path}"
    assert len(text.splitlines()) <= 150, "AGENTS.md is a table of contents: 150 lines at most"


def test_architecture_md_names_the_release_scripts_and_workflows() -> None:
    text = read_doc(REPO / "ARCHITECTURE.md")
    for needle in ("scripts/release/", "release.yml", "wheel.yml", "python.yml"):
        assert needle in text, f"ARCHITECTURE.md does not name {needle}"


def test_the_classifier_matches_the_stage_of_the_installed_version(wheel_version: str) -> None:
    status = [c for c in (metadata("ext-r2c").get_all("Classifier") or []) if c.startswith("Development Status ::")]
    assert len(status) == 1, status
    assert "Pre-Alpha" not in status[0], f"{status[0]!r} is the stage of the skeleton, not of {wheel_version}"
    stage = re.search(r"(a|b|rc)\d+$", wheel_version)
    if stage and stage[1] == "a":
        assert status == ["Development Status :: 3 - Alpha"]
    elif stage:
        assert status == ["Development Status :: 4 - Beta"]


def test_the_changelog_has_a_dated_section_for_the_version_under_a_fresh_unreleased(wheel_version: str) -> None:
    common = load_script("release_common")
    text = read_doc(REPO / "CHANGELOG.md")
    try:
        body = common.changelog_section(text, wheel_version)
    except common.Refusal as refusal:
        pytest.fail(refusal.line(), pytrace=False)
    assert body.strip()
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings[0] == "## [Unreleased]", "the first section is the fresh [Unreleased]"
    assert headings[1].startswith(f"## [{wheel_version}] - "), "the release follows it"
    unreleased = text.split("## [Unreleased]", 1)[1].split("\n## ", 1)[0]
    assert not any(line.strip() and not line.startswith("#") for line in unreleased.splitlines()), "[Unreleased] starts empty"


def test_the_notes_of_the_real_repository_have_the_three_parts(
    tmp_path: Path, wheel_version: str, capsys: pytest.CaptureFixture[str]
) -> None:
    notes = load_script("notes")
    out = tmp_path / "notes.md"
    code = notes.main(["--repository", REPOSITORY, "--out", str(out)])
    assert code == 0, capsys.readouterr().err
    text = out.read_text()
    status, limits, changes = "## Status", "## Known limits", f"## Changes in {wheel_version}"
    for heading in (status, limits, changes):
        assert text.count(heading + "\n") == 1, f"the notes do not hold {heading!r} once"
    assert text.index(status) < text.index(limits) < text.index(changes)
    assert wheel_address(wheel_version) in text, "the status block holds the address of this wheel"
    last = text[text.index(changes) + len(changes) :]
    assert any(line.strip() and not line.startswith("#") for line in last.splitlines()), "the changes part is not empty"


def python_floor() -> str:
    """The oldest Python the installed wheel accepts, from its own metadata (`>=3.11` gives `3.11`)."""
    spec = metadata("ext-r2c")["Requires-Python"]
    assert spec.startswith(">="), f"expected a lower bound, got {spec!r}"
    return spec[2:]


@pytest.mark.parametrize("name", ["root", "python"])
def test_both_readmes_name_the_python_they_need(name: str) -> None:
    text = " ".join(read_doc(READMES[name]).split())
    assert f"Python {python_floor()} or newer" in text, shown(READMES[name])


def test_the_notes_name_the_python_they_need(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "notes.md"
    code = load_script("notes").main(["--repository", REPOSITORY, "--out", str(out)])
    assert code == 0, capsys.readouterr().err
    assert f"Python {python_floor()} or newer" in " ".join(out.read_text().split())


def test_the_notes_link_nothing_by_a_relative_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The notes are shown on the release page, where `docs/x.md` points nowhere: every link is a full address."""
    out = tmp_path / "notes.md"
    code = load_script("notes").main(["--repository", REPOSITORY, "--out", str(out)])
    assert code == 0, capsys.readouterr().err
    relative = [t for t in re.findall(r"\]\(([^)\s]+)", out.read_text()) if not t.startswith(("https://", "#"))]
    assert not relative, f"links that a release page cannot follow: {relative}"
