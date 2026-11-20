"""The agent card of a remote that speaks R2C (R2C-ACT-1, spec 003 research R13)."""

from __future__ import annotations

from collections.abc import Sequence

from a2a.types import AgentCapabilities, AgentCard, AgentExtension, AgentInterface, AgentSkill

from .. import URI
from ..core import CardInfo

__all__ = ["agent_card"]

DESCRIPTION = "Asks questions and approvals, reports activity and usage, presents artifacts."


def agent_card(
    info: CardInfo,
    url: str,
    *,
    streaming: bool = True,
    input_modes: Sequence[str] = ("text/plain",),
    output_modes: Sequence[str] = ("text/plain",),
) -> AgentCard:
    """The card for ``info`` served at ``url`` (JSON-RPC, A2A 1.0). It declares R2C with
    ``required: false``: a caller that does not know R2C can still use the remote. a2a-sdk
    leaves ``required`` out of the JSON, since false is its default."""
    return AgentCard(
        name=info.name,
        description=info.description,
        version=info.version,
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(
            streaming=streaming,
            extensions=[AgentExtension(uri=URI, description=DESCRIPTION, required=False)],
        ),
        default_input_modes=list(input_modes),
        default_output_modes=list(output_modes),
        skills=[
            AgentSkill(id=s.id, name=s.name, description=s.description, tags=list(s.tags), examples=list(s.examples))
            for s in info.skills
        ],
    )
