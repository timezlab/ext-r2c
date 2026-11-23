"""``Remote``: the one adapter on the remote side (spec 007).

It wraps an existing remote (an agent, tools, skill folders) and serves it over A2A, MCP or both
from one ASGI app, so the remote's own logic does not change. Import the names from ``ext_r2c``:
``from ext_r2c import Remote, RemoteError, A2AOptions, MCPOptions``. A door's package is loaded
only when that door is exposed, and no bridge is ever imported here. See
``specs/007-remote/contracts/remote-api.md``.
"""

from __future__ import annotations

from ._errors import RemoteError
from ._options import A2AOptions, MCPOptions
from ._remote import Remote

__all__ = ["A2AOptions", "MCPOptions", "Remote", "RemoteError"]
