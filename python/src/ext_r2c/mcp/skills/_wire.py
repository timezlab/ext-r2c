"""The only module that knows the shapes of MCP Skills on the wire (spec 005, research R16).

The shapes are those of the **beta** revision of the extension (`io.modelcontextprotocol/skills`),
read on 2026-11-21 over the base protocol 2026-07-28; `contracts/wire-mapping.md` records how they
are mapped. The extension is Beta and may break: when it changes, this module and the spike
(`tests/test_skills_spike.py`) fail first, and nothing else needs to know why.

Two kinds of model live here. The *server* models (`Skill`, `ListSkillsResult`, ...) validate what
the server builds. The *client* models (`RawListSkillsResult`, `RawGetSkillResult`) keep each skill
entry raw, so a caller can refuse one malformed entry on its own instead of failing the whole page.
The requests are typed classes on purpose: the SDK keeps the parameters of a typed request and
drops those of an untyped one (R2).
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

import mcp_types as types
from pydantic import BaseModel, ConfigDict, Field

EXTENSION_ID: Final = "io.modelcontextprotocol/skills"
METHOD_LIST: Final = "skills/list"
METHOD_GET: Final = "skills/get"
METHOD_DIRECTORY: Final = "resources/directory/read"


class _Model(BaseModel):
    """Fields it does not know are ignored (a later revision may add some). Every field has a one-word
    name, so the wire name is the Python name; `_meta` has an explicit alias and `meta` also works."""

    model_config = ConfigDict(populate_by_name=True)


# --- An entry of the list ---------------------------------------------------------------------------


class SkillResource(_Model):
    """One file of a skill: where to read it, and what to check it against once read."""

    uri: str
    digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    size: Annotated[int, Field(strict=True, ge=0)]


class Skill(_Model):
    """One skill: its `SKILL.md` URI, its frontmatter verbatim, and every file it is made of."""

    uri: str
    frontmatter: dict[str, Any]
    resources: list[SkillResource]
    meta: dict[str, Any] | None = Field(alias="_meta", default=None)


# --- Results of the server --------------------------------------------------------------------------


class ListSkillsResult(types.PaginatedResult, types.CacheableResult):
    skills: list[Skill]
    result_type: types.ResultType = "complete"


class GetSkillResult(types.CacheableResult):
    skill: Skill
    result_type: types.ResultType = "complete"


class ReadDirectoryResult(types.PaginatedResult, types.CacheableResult):
    """The direct children of a directory. A child is an ordinary MCP resource: a file with its
    type, or a folder with the type `inode/directory`."""

    resources: list[types.Resource]
    result_type: types.ResultType = "complete"


# --- Results as the client reads them ---------------------------------------------------------------


class RawListSkillsResult(types.PaginatedResult, types.CacheableResult):
    skills: list[Any]
    result_type: types.ResultType = "complete"


class RawGetSkillResult(types.CacheableResult):
    skill: Any
    result_type: types.ResultType = "complete"


# --- Requests ---------------------------------------------------------------------------------------


class GetSkillParams(types.RequestParams):
    uri: str


class ReadDirectoryParams(types.PaginatedRequestParams):
    uri: str


class ListSkillsRequest(types.PaginatedRequest[Literal["skills/list"]]):
    method: Literal["skills/list"] = "skills/list"


class GetSkillRequest(types.Request[GetSkillParams, Literal["skills/get"]]):
    method: Literal["skills/get"] = "skills/get"
    params: GetSkillParams


class ReadDirectoryRequest(types.Request[ReadDirectoryParams, Literal["resources/directory/read"]]):
    method: Literal["resources/directory/read"] = "resources/directory/read"
    params: ReadDirectoryParams
