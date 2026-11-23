"""The checks of ``Remote(...)``: the types first, then every configuration problem at once
(spec 007, research R6 steps 3 and 4, R7).

``check`` starts nothing and reads no file. A wrong type is a ``TypeError``, the first one found, in
the order of the arguments below. What is wrong with the configuration is collected and raised as
one ``RemoteError``, in the order of the signature of ``Remote``, so the same mistakes always read
the same way. A problem names an argument, a door, a tool or a key; it never says back an address
or a path the owner typed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from ..core import CardInfo, Limits
from ._classify import AgentKind, agent_kind, check_skills, normalise_approve, normalise_tools, typed_entries
from ._doors import kinds
from ._errors import RemoteError
from ._options import A2AOptions, MCPOptions, owned_key_problems, path_problems

__all__ = ["Checked", "check", "warning_texts"]

_ANSWERED_BY = ("person", "approver")  # never a model, and so never the caller's agent (principle V)
_OWNER_SOURCES = ("auth", "token_verifier", "auth_server_provider")  # the SDK's own ways to name a caller

# What each argument of one door is for, said when that door is not exposed (FR-019).
_OF_A2A = {"url": "the address on the card is said", "a2a": "its options are read"}
_OF_MCP = {
    "tools": "tools are served",
    "approve": "an approval before a tool call is asked",
    "skills": "skills are served",
    "resources": "resources are served",
    "prompts": "prompts are served",
    "mcp_tool": "the agent's tool is served",
    "mcp": "its options are read",
}
_NOT_ABSOLUTE = "url: is not an absolute http or https address; begin it with https:// and the public host"


@dataclass(frozen=True)
class Checked:
    """What a checked ``Remote`` holds until ``app()`` builds from it (data-model §1)."""

    doors: tuple[str, ...]
    loaded: Mapping[str, Any]  # the package of each exposed door
    agent: Any
    kind: AgentKind | None
    info: CardInfo | None
    url: str | None
    tools: tuple[Any, ...]  # what the MCP door serves, the agent's tool included
    approve: Mapping[str, Any]
    skills: Any
    resources: tuple[Any, ...]
    prompts: tuple[Any, ...]
    middleware: tuple[Any, ...]
    a2a: A2AOptions
    mcp: MCPOptions
    limits: Limits
    clock: Callable[[], datetime] | None


def check(
    *, doors: tuple[str, ...], loaded: Mapping[str, Any], problems: list[str], agent: Any, card: Any, url: Any,
    tools: Any, approve: Any, skills: Any, resources: Any, prompts: Any, mcp_tool: Any, middleware: Any,
    a2a: Any, mcp: Any, limits: Any, clock: Any,
) -> Checked:
    """What ``Remote(...)`` was given, checked. ``doors`` are the exposed doors that exist, ``loaded``
    their packages and ``problems`` what was wrong with ``expose`` itself."""
    of = kinds(loaded)

    # --- The types: the first wrong one is the error (R6 step 3) ---
    kind = None if agent is None else agent_kind(agent)
    if kind == "source" and not isinstance(agent.card, CardInfo):
        raise TypeError(f"agent: its card is a CardInfo, not {type(agent.card).__name__}")
    served = normalise_tools(tools, of.source_tool)
    named = normalise_approve(approve, of.approve)
    check_skills(skills, of.skills)
    resources = typed_entries("resources", resources, of.resource, "the MCP SDK's Resource objects",
                              "an MCP SDK Resource")
    prompts = typed_entries("prompts", prompts, of.prompt, "the MCP SDK's Prompt objects", "an MCP SDK Prompt")
    middleware = typed_entries("middleware", middleware, of.middleware, "Starlette Middleware objects",
                               "a Starlette Middleware, such as Middleware(SomeClass)")
    _is("a2a", a2a, (A2AOptions, type(None)), "an A2AOptions")
    _is("mcp", mcp, (MCPOptions, type(None)), "an MCPOptions")
    _is("limits", limits, Limits, "a Limits")
    if clock is not None and not callable(clock):
        raise TypeError(f"clock: is a callable that returns the time, not {type(clock).__name__}")
    _is("card", card, (CardInfo, type(None)), "a CardInfo")
    _is("url", url, (str, type(None)), "a str")
    _is("mcp_tool", mcp_tool, bool, "a bool")

    # --- Every problem of the configuration, in the order of the signature (R6 step 4, R7) ---
    found = list(problems)
    if not doors:
        raise RemoteError(found)  # every check below asks which doors there are
    a2a_on, mcp_on = "a2a" in doors, "mcp" in doors
    a2a_options = a2a if a2a is not None else A2AOptions()
    mcp_options = mcp if mcp is not None else MCPOptions()
    info = card if card is not None else agent.card if kind == "source" else None
    agent_tool = of.source_tool(agent) if mcp_on and mcp_tool and kind == "source" else None  # type: ignore[misc]
    if agent_tool is not None:
        served = (*served, agent_tool)

    if agent is None:
        if a2a_on:
            found.append('agent: the A2A door is exposed and there is no agent to serve; give agent=, or take '
                         '"a2a" out of expose')
    elif not a2a_on and kind == "executor":
        found.append('agent: an a2a-sdk executor is served by the A2A door only, which is not exposed; add "a2a" '
                     "to expose, or leave the agent out")
    elif not a2a_on and not mcp_tool:
        found.append('agent: no exposed door serves it; set mcp_tool=True to serve it as an MCP tool, or add "a2a" '
                     "to expose")
    if info is None:
        found.append("card: nothing given has card information (an AgentSource brings its own); "
                     "give card=CardInfo(...)")
    if a2a_on:
        found += _url_problems(url)
    else:
        found += _unserved(_OF_A2A, "A2A", {"url": url is not None, "a2a": a2a is not None})

    if mcp_on:
        if not served and skills is None and not resources and not prompts:
            found.append("tools: the MCP door is exposed and has nothing to serve; give tools=, skills=, resources= "
                         "or prompts=, or mcp_tool=True with an AgentSource")
        found += _name_problems(served, agent_tool)
        found += _approve_problems(named, served, of.source_tool)
        if mcp_tool and agent is None:
            found.append("mcp_tool: there is no agent to serve as a tool; give agent=, or leave mcp_tool out")
        elif mcp_tool and kind == "executor":
            found.append("mcp_tool: an a2a-sdk executor cannot be served as an MCP tool, only an AgentSource can; "
                         "leave mcp_tool out")
    else:
        found += _unserved(_OF_MCP, "MCP", {
            "tools": bool(served), "approve": bool(named), "skills": skills is not None, "resources": bool(resources),
            "prompts": bool(prompts), "mcp_tool": mcp_tool, "mcp": mcp is not None,
        })

    found += path_problems(a2a_options if a2a_on else None, mcp_options if mcp_on else None)
    if mcp_on:
        found += owned_key_problems(mcp_options)
    if found:
        raise RemoteError(found)
    return Checked(
        doors=doors, loaded=loaded, agent=agent, kind=kind, info=info, url=url, tools=served, approve=named,
        skills=skills, resources=resources, prompts=prompts, middleware=middleware, a2a=a2a_options,
        mcp=mcp_options, limits=limits, clock=clock,
    )


def warning_texts(held: Checked) -> list[str]:
    """What a valid ``Remote`` says to its owner once, when it is built (R11), in this order: the A2A
    door's restart warning, then the MCP door's, then the one about the owner of an MCP call. Each begins
    with the setting that answers it."""
    texts = []
    if "a2a" in held.doors and held.a2a.task_store is None:
        texts.append(
            "a2a.task_store: the A2A door keeps a paused task in memory, so a restart loses it and its caller can no "
            "longer answer; pass A2AOptions(task_store=...) with a store that outlives the process, or ignore this "
            "when losing a paused task on a restart is fine"
        )
    if "mcp" in held.doors and held.mcp.security is None and _can_pause(held):
        texts.append(
            "mcp.security: the MCP door can pause a call to ask for an approval, and with no fixed keys a restart "
            "loses the paused call; pass MCPOptions(security=RequestStateSecurity(keys=[...])) with keys that are "
            "the same in every process, or ignore this when a call lost on a restart is fine"
        )
    if held.middleware and "mcp" in held.doors and not _names_an_owner(held.mcp):
        texts.append(
            "mcp.owner: middleware= is given, but the MCP door reads the owner of a call from MCPOptions(owner=...) "
            "or from the SDK's own authentication and has neither, so every MCP caller is one owner in one thread "
            "namespace; pass MCPOptions(owner=...) that returns the user the middleware named, or give the server "
            "the SDK's authentication, or ignore this when one owner for every MCP caller is what you want"
        )
    return texts


def _names_an_owner(options: MCPOptions) -> bool:
    """Whether the MCP door has a way to tell its callers apart: an ``owner`` callable, or one of the
    SDK's own authentication settings in the server's keywords (a setting left ``None`` is none)."""
    return options.owner is not None or any(options.server.get(key) is not None for key in _OWNER_SOURCES)


def _can_pause(held: Checked) -> bool:
    """Whether a call on the MCP door can be paused and retried: a tool that asks for an approval, or a
    source of the checkpoint style (the agent's own tool included). A plain tool answers in one round,
    and a live source needs the same process, which no key gives back."""
    if any(setting is not False for setting in held.approve.values()):
        return True
    source_tool = held.loaded["mcp"].SourceTool
    return any(isinstance(tool, source_tool) and tool.source.pause == "checkpoint" for tool in held.tools)


def _is(argument: str, value: Any, kind: type | tuple[type, ...], what: str) -> None:
    """The type's name is said, never the value: a ``url`` of the wrong type may still be a secret."""
    if not isinstance(value, kind):
        raise TypeError(f"{argument}: is {what}, not {type(value).__name__}")


def _unserved(purposes: Mapping[str, str], door: str, given: Mapping[str, bool]) -> list[str]:
    """One problem for each argument that was given for a door that is not exposed."""
    return [
        f'{argument}: {purpose} by the {door} door, which is not exposed; leave it out, or add "{door.lower()}" '
        "to expose"
        for argument, purpose in purposes.items() if given[argument]
    ]


def _url_problems(url: str | None) -> list[str]:
    """``url`` is the public base address of the app: absolute, ``http`` or ``https``, with a host, and
    with nothing a card must not carry or a path cannot be added to."""
    if url is None:
        return ["url: the A2A door is exposed and its card says where this app is reached; give the public base "
                "address, beginning with https://"]
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return [_NOT_ABSOLUTE]
    if parts.scheme not in ("http", "https"):
        return [_NOT_ABSOLUTE]
    problems = []
    if not host:
        problems.append("url: has no host; give the public host this app is reached at")
    if "@" in parts.netloc:
        problems.append("url: carries user info before the host; remove it, the card shows this address to "
                        "every caller")
    if "?" in url:
        problems.append("url: has a query; remove it, the address is a base that a path is added to")
    if "#" in url:
        problems.append("url: has a fragment; remove it, the address is a base that a path is added to")
    return problems


def _name_problems(served: tuple[Any, ...], agent_tool: Any) -> list[str]:
    """One problem for each name that more than one tool of the MCP door has."""
    names = [tool.name for tool in served]
    problems = []
    for name in dict.fromkeys(names):
        if names.count(name) < 2:
            continue
        if agent_tool is not None and name == agent_tool.name:
            problems.append(f"tools: a tool is named {name}, the name of the agent's own tool; rename it, or leave "
                            "mcp_tool out and give tools= a SourceTool of the agent with another name")
        else:
            problems.append(f"tools: more than one tool is named {name}; give each tool its own name")
    return problems


def _approve_problems(named: Mapping[str, Any], served: tuple[Any, ...], source_tool: Any) -> list[str]:
    """Each name of ``approve`` is a tool of the MCP door that is not an agent, and its approval is
    answered by a person or by an approver."""
    tools = {tool.name: tool for tool in served}
    problems = []
    for name, setting in named.items():
        if name not in tools:
            problems.append(f"approve: names {name}, which is not a tool of the MCP door; name a tool given in "
                            "tools=, or leave it out")
        elif isinstance(tools[name], source_tool):
            problems.append(f"approve: names {name}, a tool that is an agent; leave it out, an agent asks its own "
                            "approvals")
        if not isinstance(setting, bool) and setting.answer_by not in _ANSWERED_BY:
            problems.append(f"approve: the approval of {name} is answered by neither a person nor an approver; "
                            'set answer_by to "person" or "approver"')
    return problems
