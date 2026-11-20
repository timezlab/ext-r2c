"""Checks for the R2C v1 standard: schemas, wire examples and rules (test code, not shipped).

The file formats are fixed by `specs/001-standard-v1/contracts/`. Envelopes are checked with the
real protocol SDKs: a2a-sdk (protobuf JSON) and mcp-types (2026-07-28 wire models).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

URI = "https://github.com/timezlab/ext-r2c/tree/main/standard/v1"
MCP_KEY = "io.github.timezlab/r2c"
MCP_VERSION = "2026-07-28"
SCHEMA_FILES = (
    "question.json",
    "approval.json",
    "answer.json",
    "artifact-meta.json",
    "activity.json",
    "usage.json",
)


class EnvelopeError(AssertionError):
    """A protocol envelope that the real SDK types reject."""


# --- Locations --------------------------------------------------------------------------------


def standard_path() -> Path:
    """`standard/v1` of the checkout, or `R2C_STANDARD_DIR` (also usable at collection time)."""
    override = os.environ.get("R2C_STANDARD_DIR")
    return Path(override) if override else Path(__file__).resolve().parents[2] / "standard" / "v1"


def example_files(folder: str) -> list[Path]:
    """Sorted `.json` files of `examples/<folder>/` (empty when the folder does not exist)."""
    path = standard_path() / "examples" / folder
    return sorted(path.glob("*.json")) if path.is_dir() else []


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --- Schemas ----------------------------------------------------------------------------------


def kind_of_schema_file(name: str) -> str:
    stem = name.removesuffix(".json")
    return "artifact" if stem == "artifact-meta" else stem


def load_schemas(standard_dir: Path) -> dict[str, dict[str, Any]]:
    """`{kind: schema}` for every schema file present."""
    folder = standard_dir / "schema"
    return {
        kind_of_schema_file(p.name): load_json(p) for p in sorted(folder.glob("*.json"))
    } if folder.is_dir() else {}


def validator(schema: Mapping[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(schema, format_checker=FormatChecker())


def subschema_validator(root: Mapping[str, Any], name: str) -> Draft202012Validator:
    """Validator for `root#/$defs/<name>`, keeping `root`'s other `$defs` resolvable."""
    return validator({
        "$schema": root.get("$schema", "https://json-schema.org/draft/2020-12/schema"),
        "$defs": root.get("$defs", {}),
        "$ref": f"#/$defs/{name}",
    })


def error_paths(v: Draft202012Validator, instance: Any) -> list[str]:
    """JSON Pointers of every validation error, including those nested in `anyOf` / `oneOf`."""
    out: list[str] = []

    def visit(err: Any) -> None:
        out.append(pointer(err.absolute_path))
        for sub in err.context or ():
            visit(sub)

    for err in v.iter_errors(instance):
        visit(err)
    return out


def walk_refs(node: Any) -> Iterator[str]:
    """Every `$ref` value in a schema."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from walk_refs(v)
    elif isinstance(node, list):
        for item in node:
            yield from walk_refs(item)


def closed_objects(node: Any, path: str = "") -> Iterator[str]:
    """Pointers of every subschema that closes an object (forbidden by FR-016)."""
    if isinstance(node, dict):
        for key in ("additionalProperties", "unevaluatedProperties"):
            if node.get(key) is False:
                yield f"{path}/{key}"
        for k, v in node.items():
            yield from closed_objects(v, f"{path}/{escape(k)}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from closed_objects(item, f"{path}/{i}")


# --- JSON Pointer -----------------------------------------------------------------------------


def escape(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def pointer(parts: Any) -> str:
    return "".join(f"/{escape(p)}" for p in parts)


# --- Finding R2C objects ----------------------------------------------------------------------


def find_r2c_objects(binding: str, body: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield `(json_pointer, object)` for each R2C object in a body, by the placement rule."""
    if isinstance(body, list):
        for i, item in enumerate(body):
            yield from find_r2c_objects(binding, item, f"{path}/{i}")
        return
    if not isinstance(body, dict):
        return
    skip: set[str] = set()
    if binding == "a2a":
        meta = body.get("metadata")
        if isinstance(meta, dict) and URI in meta:
            mark = meta[URI]
            data = body.get("data")
            if mark == {} and isinstance(data, dict) and "kind" in data:
                yield f"{path}/data", data
                skip.add("data")
            elif isinstance(mark, dict) and "kind" in mark:
                yield f"{path}/metadata/{escape(URI)}", mark
                skip.add("metadata")
    elif binding == "mcp":
        meta = body.get("_meta")
        if isinstance(meta, dict) and isinstance(meta.get(MCP_KEY), dict):
            value = meta[MCP_KEY]
            base = f"{path}/_meta/{escape(MCP_KEY)}"
            if "kind" in value:
                yield base, value
            elif isinstance(value.get("input_requests"), dict):
                asked = body.get("inputRequests") or {}
                for key, obj in value["input_requests"].items():
                    if key not in asked:
                        raise EnvelopeError(f"{base}/input_requests/{key}: no such key in inputRequests")
                    if isinstance(obj, dict) and "kind" in obj:
                        yield f"{base}/input_requests/{escape(key)}", obj
            skip.add("_meta")
    else:
        raise ValueError(f"unknown binding {binding!r}")
    for k, v in body.items():
        if k not in skip:
            yield from find_r2c_objects(binding, v, f"{path}/{escape(k)}")


# --- A2A envelopes ----------------------------------------------------------------------------

A2A_TYPES = (
    "AgentCard",
    "SendMessageRequest",
    "SendMessageResponse",
    "StreamResponse",
    "Task",
    "GetTaskRequest",
    "SubscribeToTaskRequest",
)


def check_a2a(type_name: str, body: Any) -> None:
    """Parse with the a2a-sdk protobuf types (strict) and check REQUIRED fields."""
    from google.protobuf import json_format
    from google.protobuf.json_format import ParseError

    from a2a.types import a2a_pb2
    from a2a.utils.proto_utils import validate_proto_required_fields

    if type_name not in A2A_TYPES:
        raise EnvelopeError(f"unknown A2A envelope type {type_name!r}")
    try:
        msg = json_format.ParseDict(body, getattr(a2a_pb2, type_name)())
    except ParseError as e:
        raise EnvelopeError(f"A2A {type_name}: {e}") from None
    try:
        validate_proto_required_fields(msg)
    except Exception as e:  # a2a-sdk raises InvalidParamsError with the field list in `.data`
        details = getattr(e, "data", None) or str(e)
        raise EnvelopeError(f"A2A {type_name}: required fields: {details}") from None


# --- MCP envelopes ----------------------------------------------------------------------------

MCP_TYPES = ("request", "result", "notification", "discover")


def dropped_keys(src: Any, dumped: Any, path: str = "") -> list[str]:
    """Keys of `src` missing from the surface dump, i.e. unknown on the wire (`_meta` exempt)."""
    out: list[str] = []
    if isinstance(src, dict) and isinstance(dumped, dict):
        for k, v in src.items():
            if k not in dumped:
                out.append(f"{path}/{escape(k)}")
            elif k != "_meta":
                out += dropped_keys(v, dumped[k], f"{path}/{escape(k)}")
    elif isinstance(src, list) and isinstance(dumped, list):
        for i, (a, b) in enumerate(zip(src, dumped, strict=False)):
            out += dropped_keys(a, b, f"{path}/{i}")
    return out


def _surface_dump(model: Any, data: Any) -> Any:
    from pydantic import TypeAdapter

    adapter = TypeAdapter(model)
    return adapter.dump_python(
        adapter.validate_python(data, by_name=False), by_alias=True, mode="json", exclude_none=True
    )


def _requested_schemas(node: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "requestedSchema" and isinstance(v, dict):
                yield f"{path}/requestedSchema", v
            else:
                yield from _requested_schemas(v, f"{path}/{escape(k)}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _requested_schemas(item, f"{path}/{i}")


def check_mcp(step: Mapping[str, Any]) -> None:
    """Check one MCP step with the 2026-07-28 wire models, rejecting unknown fields."""
    from pydantic import ValidationError

    from mcp_types import methods as m
    from mcp_types._v2026_07_28 import PrimitiveSchemaDefinition
    from mcp_types.jsonrpc import JSONRPCNotification, JSONRPCRequest, JSONRPCResponse

    kind = step.get("type")
    body = step.get("body")
    if kind not in MCP_TYPES or not isinstance(body, dict):
        raise EnvelopeError(f"unknown MCP step type {kind!r} or body not an object")
    try:
        if kind == "request":
            JSONRPCRequest.model_validate(body)
            method = body["method"]
            m.parse_client_request(method, MCP_VERSION, body.get("params"))
            dumped = _surface_dump(m.CLIENT_REQUESTS[(method, MCP_VERSION)], body)
            where = ""
            src = body
        elif kind == "notification":
            JSONRPCNotification.model_validate(body)
            method = body["method"]
            m.parse_server_notification(method, MCP_VERSION, body.get("params"))
            dumped = _surface_dump(m.SERVER_NOTIFICATIONS[(method, MCP_VERSION)], body)
            where = ""
            src = body
        else:
            JSONRPCResponse.model_validate(body)
            method = "server/discover" if kind == "discover" else step.get("method")
            if not method:
                raise EnvelopeError("an MCP result step needs `method`")
            src = body["result"]
            dumped = m.serialize_server_result(method, MCP_VERSION, src)
            m.parse_server_result(method, MCP_VERSION, src)
            where = "/result"
    except (ValidationError, KeyError, ValueError) as e:
        raise EnvelopeError(f"MCP {kind}: {type(e).__name__}: {e}") from None
    unknown = dropped_keys(src, dumped, where)
    if unknown:
        raise EnvelopeError(f"MCP {kind}: unknown fields {unknown}")
    for spath, rs in _requested_schemas(body):
        for name, prop in (rs.get("properties") or {}).items():
            try:
                prop_dump = _surface_dump(PrimitiveSchemaDefinition, prop)
            except ValidationError as e:
                raise EnvelopeError(f"MCP {spath}/properties/{name}: not a primitive: {e}") from None
            extra = dropped_keys(prop, prop_dump, f"{spath}/properties/{escape(name)}")
            if extra:
                raise EnvelopeError(f"MCP requestedSchema: unknown fields {extra}")


# --- Example file formats ---------------------------------------------------------------------

_RULE_ID = {"type": "string", "pattern": r"^R2C-[A-Z][A-Z0-9]*-[0-9]+$"}

EXAMPLE_FORMAT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["title", "binding", "rules", "steps"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "binding": {"enum": ["a2a", "mcp"]},
        "rules": {"type": "array", "minItems": 1, "items": _RULE_ID},
        "steps": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["from", "type", "body"],
                "properties": {
                    "from": {"enum": ["remote", "client"]},
                    "type": {"type": "string"},
                    "method": {"type": "string"},
                    "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                    "body": {"type": "object"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

INVALID_FORMAT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["title", "rules", "kind", "object", "fails_at"],
    "properties": {
        "title": {"type": "string", "minLength": 1},
        "rules": {"type": "array", "minItems": 1, "items": _RULE_ID},
        "kind": {"type": "string"},
        "object": {"type": "object"},
        "fails_at": {"type": "string"},
    },
    "additionalProperties": False,
}


def check_format(example: Any, fmt: Mapping[str, Any]) -> list[str]:
    return [f"{pointer(e.absolute_path)}: {e.message}" for e in validator(fmt).iter_errors(example)]


# --- Form → schema (data-model.md, "Form → schema mapping", A2A column) -----------------------


def field_schema(field: Mapping[str, Any]) -> dict[str, Any]:
    ftype = field["type"]
    other = field.get("other", True)
    labels = [o["label"] for o in field.get("options", [])]
    if ftype == "one":
        return {"type": "string", "minLength": 1} if other else {"type": "string", "enum": labels}
    if ftype == "many":
        items = {"type": "string", "minLength": 1} if other else {"enum": labels}
        return {"type": "array", "items": items, "uniqueItems": True}
    return {"text": {"type": "string"}, "number": {"type": "number"}, "bool": {"type": "boolean"}}[ftype]


def form_schema(question: Mapping[str, Any]) -> dict[str, Any]:
    fields = question["fields"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {f["key"]: field_schema(f) for f in fields},
        "required": [f["key"] for f in fields if f.get("required", True)],
    }


# --- Rules (contracts/rule-format.md) ---------------------------------------------------------

RULE_LINE = re.compile(
    r"^- \*\*(R2C-[A-Z][A-Z0-9]*-[0-9]+)\*\* · (MUST|MUST NOT|SHOULD|SHOULD NOT|MAY) · "
    r"(remote|client|both) · (wire|prose)( · schema)?$"
)


@dataclass(frozen=True)
class Rule:
    id: str
    level: str
    party: str
    wire: bool
    schema: bool


def parse_rules(readme_text: str) -> dict[str, Rule]:
    """Rules by id. Raises ValueError on a malformed tag line or a duplicate id."""
    rules: dict[str, Rule] = {}
    for n, line in enumerate(readme_text.splitlines(), 1):
        if not line.startswith("- **R2C-"):
            continue
        match = RULE_LINE.match(line.rstrip())
        if not match:
            raise ValueError(f"line {n}: malformed rule tag line: {line!r}")
        rid, level, party, mark, schema = match.groups()
        if rid in rules:
            raise ValueError(f"line {n}: duplicate rule id {rid}")
        rules[rid] = Rule(rid, level, party, mark == "wire", schema is not None)
    return rules
