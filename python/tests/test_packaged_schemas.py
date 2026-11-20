"""The installed package carries the v1 schemas, byte for byte the ones in `standard/v1/schema/`."""

from importlib.resources import files
from pathlib import Path

import pytest

from r2c_check import SCHEMA_FILES

PACKAGED = files("ext_r2c") / "schema" / "v1"


def test_packaged_schemas_are_exactly_the_standard_ones(standard_dir: Path) -> None:
    assert PACKAGED.is_dir(), "ext_r2c/schema/v1 is missing from the installed package"
    packaged = sorted(p.name for p in PACKAGED.iterdir())
    source = sorted(p.name for p in (standard_dir / "schema").glob("*.json"))
    assert packaged == source == sorted(SCHEMA_FILES)


@pytest.mark.parametrize("name", SCHEMA_FILES)
def test_packaged_schema_has_the_same_bytes(name: str, standard_dir: Path) -> None:
    packaged = PACKAGED / name
    assert packaged.is_file(), f"ext_r2c/schema/v1/{name} is missing from the installed package"
    assert packaged.read_bytes() == (standard_dir / "schema" / name).read_bytes()
