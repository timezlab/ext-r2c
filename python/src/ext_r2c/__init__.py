"""R2C (Remote-to-Caller): an extension for A2A and MCP.

A remote (an A2A agent or an MCP server) uses R2C to ask its caller a
question, request an approval, and hand back artifacts, without changing
its own logic. The shapes live in ``standard/v1`` of the repository.
"""

from importlib.metadata import version as _version

__all__ = ["MCP_KEY", "STANDARD_VERSION", "URI", "__version__"]

__version__ = _version("ext-r2c")

STANDARD_VERSION = "1"
"""Major version of the standard this package implements."""

URI = f"https://github.com/timezlab/ext-r2c/tree/main/standard/v{STANDARD_VERSION}"
"""A2A extension URI: declared in ``capabilities.extensions``, sent in the
``A2A-Extensions`` header, and used as the key in ``metadata``."""

MCP_KEY = "io.github.timezlab/r2c"
"""Key under ``_meta`` in the MCP binding."""
