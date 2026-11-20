"""Shared fixtures: where the standard lives."""

from pathlib import Path

import pytest

from r2c_check import standard_path


@pytest.fixture(scope="session")
def standard_dir() -> Path:
    """The `standard/v1` folder of the repository checkout (or `R2C_STANDARD_DIR`)."""
    path = standard_path()
    if not path.is_dir():
        pytest.fail(
            f"standard folder not found at {path}; run the tests from a repository checkout "
            "or set R2C_STANDARD_DIR",
            pytrace=False,
        )
    return path
