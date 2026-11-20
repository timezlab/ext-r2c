"""What one round of a tool call knows about its caller (spec 004, research R5, R8).

Activation, form support and the owner are read per round: each `tools/call` request carries
its own client capabilities, so a retry without the R2C key gets no R2C `_meta` (R2C-ACT-3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import mcp_types as types
from mcp.server.request_state import authenticated_principal

from .. import MCP_KEY
from ..core import Activity, Limits
from ._codec import progress_params
from ._state import RoundLedger

__all__ = ["Round", "form_supported", "is_active", "owner_of"]


def _capabilities(ctx: Any) -> types.ClientCapabilities | None:
    session = getattr(ctx, "session", None)
    return getattr(session, "client_capabilities", None)


def is_active(ctx: Any) -> bool:
    """The R2C key is in this request's client extensions."""
    caps = _capabilities(ctx)
    return caps is not None and MCP_KEY in (caps.extensions or {})


def form_supported(ctx: Any) -> bool:
    """The request declares elicitation, and not URL mode only (a bare ``elicitation: {}`` is form)."""
    caps = _capabilities(ctx)
    elicitation = caps.elicitation if caps is not None else None
    if elicitation is None:
        return False
    return elicitation.form is not None or elicitation.url is None


def owner_of(ctx: Any) -> str:
    """The principal the SDK's boundary binds the state to, or ``anonymous`` without authentication."""
    return authenticated_principal(ctx) or "anonymous"


@dataclass
class Round:
    """One ``tools/call`` request as the door sees it, with the door's settings."""

    ctx: Any
    active: bool
    form: bool
    owner: str
    token: str | int | None
    clock: Callable[[], datetime]
    limits: Limits
    ledger: RoundLedger
    ttl: float
    sent: int = 0

    async def progress(self, activity: Activity) -> None:
        """A progress notification on this request's stream, numbered from 1 (R2C-MCP-6). Nothing
        without a progress token; a reasoning activity only when active."""
        if self.token is None or (activity.type == "reasoning" and not self.active):
            return
        self.sent += 1
        params = progress_params(activity, self.token, self.sent, active=self.active)
        await self.ctx.session.send_notification(types.ProgressNotification(params=params),
                                                 related_request_id=self.ctx.request_id)
