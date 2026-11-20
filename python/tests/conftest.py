"""Shared fixtures: where the standard lives."""

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def standard_dir() -> Path:
    """The `standard/v1` folder of the repository checkout (or `R2C_STANDARD_DIR`)."""
    override = os.environ.get("R2C_STANDARD_DIR")
    path = Path(override) if override else Path(__file__).resolve().parents[2] / "standard" / "v1"
    if not path.is_dir():
        pytest.fail(
            f"standard folder not found at {path}; run the tests from a repository checkout "
            "or set R2C_STANDARD_DIR",
            pytrace=False,
        )
    return path
