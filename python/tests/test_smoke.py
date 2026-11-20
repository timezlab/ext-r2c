"""The installed wheel exposes the identifiers every binding relies on."""

import subprocess
import sys
from importlib.metadata import version

import ext_r2c


def test_a2a_extension_uri_points_at_standard_v1() -> None:
    assert ext_r2c.URI == "https://github.com/timezlab/ext-r2c/tree/main/standard/v1"


def test_mcp_meta_key() -> None:
    assert ext_r2c.MCP_KEY == "io.github.timezlab/r2c"


def test_standard_version_is_v1() -> None:
    assert ext_r2c.STANDARD_VERSION == "1"
    assert ext_r2c.URI.endswith(f"/v{ext_r2c.STANDARD_VERSION}")


def test_package_version_matches_distribution_metadata() -> None:
    assert ext_r2c.__version__ == version("ext-r2c")


def test_runs_against_installed_package_not_source_tree() -> None:
    assert "site-packages" in (ext_r2c.__file__ or "")


def test_import_loads_no_protocol_sdk() -> None:
    # The test venv has a2a-sdk and mcp installed (test-only), so prove the core does not load them.
    code = "import sys, ext_r2c; print('a2a' in sys.modules or 'mcp' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
