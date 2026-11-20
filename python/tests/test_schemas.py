"""The six v1 schemas: valid draft 2020-12, named under the standard's URI, self-contained, open."""

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from r2c_check import SCHEMA_FILES, URI, closed_objects, load_json, walk_refs

DRAFT = "https://json-schema.org/draft/2020-12/schema"


def test_exactly_the_six_schema_files(standard_dir: Path) -> None:
    folder = standard_dir / "schema"
    present = sorted(p.name for p in folder.glob("*")) if folder.is_dir() else []
    assert present, "no schema files in standard/v1/schema/"
    assert present == sorted(SCHEMA_FILES)


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_is_valid_2020_12_with_its_id(standard_dir: Path, name: str) -> None:
    path = standard_dir / "schema" / name
    assert path.is_file(), f"missing schema file {name}"
    schema = load_json(path)
    assert schema.get("$schema") == DRAFT
    Draft202012Validator.check_schema(schema)
    assert schema.get("$id") == f"{URI}/schema/{name}"


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_is_self_contained(standard_dir: Path, name: str) -> None:
    path = standard_dir / "schema" / name
    assert path.is_file(), f"missing schema file {name}"
    external = [ref for ref in walk_refs(load_json(path)) if not ref.startswith("#")]
    assert external == [], f"{name}: $ref leaving the file: {external}"


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_schema_keeps_objects_open(standard_dir: Path, name: str) -> None:
    path = standard_dir / "schema" / name
    assert path.is_file(), f"missing schema file {name}"
    closed = list(closed_objects(load_json(path)))
    assert closed == [], f"{name}: closed objects break 'ignore unknown': {closed}"
