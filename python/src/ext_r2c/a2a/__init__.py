"""The A2A door of R2C, on a2a-sdk (install the ``[a2a]`` extra).

Remote side: ``SourceExecutor`` serves an ``ext_r2c.core.AgentSource``; ``R2CTask`` helps a
hand-written a2a-sdk executor speak R2C; ``agent_card`` and ``a2a_app`` assemble the card and
the app. Caller side: ``R2CClient``. See ``specs/003-a2a-binding/contracts/a2a-api.md``.
"""

from __future__ import annotations

__all__: list[str] = []
