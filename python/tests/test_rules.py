"""README rules and examples cover each other; no example file goes unread."""

from pathlib import Path

import pytest

from r2c_check import Rule, example_files, load_json, parse_rules


@pytest.fixture(scope="module")
def rules(standard_dir: Path) -> dict[str, Rule]:
    readme = standard_dir / "README.md"
    return parse_rules(readme.read_text(encoding="utf-8")) if readme.is_file() else {}


def _cited(folders: tuple[str, ...]) -> dict[str, set[str]]:
    """Rule id → example files citing it."""
    out: dict[str, set[str]] = {}
    for folder in folders:
        for path in example_files(folder):
            for rid in load_json(path).get("rules", []):
                out.setdefault(rid, set()).add(f"{folder}/{path.name}")
    return out


def test_readme_has_rules(rules: dict[str, Rule]) -> None:
    assert rules, "no rules found in standard/v1/README.md"


def test_every_cited_rule_exists(rules: dict[str, Rule]) -> None:
    unknown = {rid: files for rid, files in _cited(("a2a", "mcp", "invalid")).items() if rid not in rules}
    assert not unknown, f"examples cite rules the README does not define: {unknown}"


def test_every_wire_rule_has_an_example(rules: dict[str, Rule]) -> None:
    cited = _cited(("a2a", "mcp"))
    missing = sorted(rid for rid, r in rules.items() if r.wire and rid not in cited)
    assert not missing, f"wire rules without a valid example: {missing}"


def test_every_schema_rule_has_an_invalid_example(rules: dict[str, Rule]) -> None:
    cited = _cited(("invalid",))
    missing = sorted(rid for rid, r in rules.items() if r.schema and rid not in cited)
    assert not missing, f"schema rules without an invalid example: {missing}"


def test_invalid_examples_cite_schema_rules_only(rules: dict[str, Rule]) -> None:
    wrong = {rid: files for rid, files in _cited(("invalid",)).items() if rid in rules and not rules[rid].schema}
    assert not wrong, f"invalid examples cite rules not marked 'schema': {wrong}"


def test_no_unread_example_file(standard_dir: Path) -> None:
    root = standard_dir / "examples"
    if not root.is_dir():
        return
    stray = [
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and not (p.suffix == ".json" and p.parent.parent == root
                                and p.parent.name in ("a2a", "mcp", "invalid"))
    ]
    assert not stray, f"files no check reads: {stray}"
