"""R2C (Remote-to-Caller): an extension for A2A and MCP.

A remote (an A2A agent or an MCP server) uses R2C to ask its caller a
question, request an approval, and hand back artifacts, without changing
its own logic. The shapes live in ``standard/v1`` of the repository.
"""

from importlib.metadata import version as _version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the four names are loaded on first use, see `__getattr__` below
    from .remote import A2AOptions, MCPOptions, Remote, RemoteError

__all__ = [
    "MCP_KEY",
    "STANDARD_VERSION",
    "URI",
    "A2AOptions",
    "MCPOptions",
    "Remote",
    "RemoteError",
    "__version__",
]

__version__ = _version("ext-r2c")

STANDARD_VERSION = "1"
"""Major version of the standard this package implements."""

URI = f"https://github.com/timezlab/ext-r2c/tree/main/standard/v{STANDARD_VERSION}"
"""A2A extension URI: declared in ``capabilities.extensions``, sent in the
``A2A-Extensions`` header, and used as the key in ``metadata``."""

MCP_KEY = "io.github.timezlab/r2c"
"""Key under ``_meta`` in the MCP binding."""

_REMOTE_NAMES = frozenset({"A2AOptions", "MCPOptions", "Remote", "RemoteError"})


def __getattr__(name: str) -> Any:
    """``Remote`` and its three companions, loaded on first use (PEP 562): ``import ext_r2c`` and
    ``import ext_r2c.core`` stay as light as they were, and ``from ext_r2c import Remote`` works
    with no extra installed."""
    if name in _REMOTE_NAMES:
        from . import remote

        value = getattr(remote, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *_REMOTE_NAMES})
