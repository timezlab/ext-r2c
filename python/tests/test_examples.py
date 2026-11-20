"""Every wire example: format, real protocol envelope, every R2C object, answer pairing.

Every invalid example: fails its kind's schema exactly where it says.
"""

from pathlib import Path
from typing import Any

import pytest

from r2c_check import (
    EXAMPLE_FORMAT,
    INVALID_FORMAT,
    check_a2a,
    check_format,
    check_mcp,
    error_paths,
    example_files,
    find_r2c_objects,
    form_schema,
    load_json,
    load_schemas,
    subschema_validator,
    validator,
)

VALID = example_files("a2a") + example_files("mcp")
INVALID = example_files("invalid")


def _id(path: Path) -> str:
    return f"{path.parent.name}/{path.name}"


def test_there_are_valid_examples() -> None:
    assert VALID, "no examples in standard/v1/examples/a2a/ or examples/mcp/"


def test_there_are_invalid_examples() -> None:
    assert INVALID, "no examples in standard/v1/examples/invalid/"


def _check_answer(answer: dict[str, Any], request: dict[str, Any], schemas: dict[str, Any], where: str) -> None:
    if answer.get("outcome") != "answered":
        return
    value = answer.get("value")
    if request["kind"] == "question":
        errors = error_paths(validator(form_schema(request)), value)
        assert not errors, f"{where}: answer value does not fit question {request['id']}: {errors}"
    elif request["kind"] == "approval":
        errors = error_paths(subschema_validator(schemas["answer"], "approval_value"), value)
        assert not errors, f"{where}: not an approval value: {errors}"
        assert value["decision"] in request["decisions"], f"{where}: decision not offered"
        args_schema = request.get("subject", {}).get("args_schema")
        if value["decision"] == "edit" and args_schema:
            errors = error_paths(validator(args_schema), value["args"])
            assert not errors, f"{where}: edited args break args_schema: {errors}"


@pytest.mark.parametrize("path", VALID, ids=_id)
def test_valid_example(path: Path, standard_dir: Path) -> None:
    example = load_json(path)
    problems = check_format(example, EXAMPLE_FORMAT)
    assert not problems, f"example format: {problems}"
    assert example["binding"] == path.parent.name, "binding does not match the folder"

    schemas = load_schemas(standard_dir)
    requests: dict[str, dict[str, Any]] = {}
    for n, step in enumerate(example["steps"]):
        if example["binding"] == "a2a":
            check_a2a(step["type"], step["body"])
        else:
            check_mcp(step)
        for where, obj in find_r2c_objects(example["binding"], step["body"], f"/steps/{n}/body"):
            kind = obj["kind"]
            if kind not in schemas:
                continue  # unknown kind: ignored by the standard (R2C "ignore unknown")
            errors = error_paths(validator(schemas[kind]), obj)
            assert not errors, f"{where}: {kind} fails its schema at {errors}"
            if kind in ("question", "approval"):
                requests[obj["id"]] = obj
            elif kind == "answer" and obj["id"] in requests:
                _check_answer(obj, requests[obj["id"]], schemas, where)


@pytest.mark.parametrize("path", INVALID, ids=_id)
def test_invalid_example_fails_where_it_says(path: Path, standard_dir: Path) -> None:
    example = load_json(path)
    problems = check_format(example, INVALID_FORMAT)
    assert not problems, f"invalid-example format: {problems}"
    schemas = load_schemas(standard_dir)
    assert example["kind"] in schemas, f"no schema for kind {example['kind']!r}"
    errors = error_paths(validator(schemas[example["kind"]]), example["object"])
    assert errors, "expected to fail its schema, but it validates"
    assert example["fails_at"] in errors, f"fails at {errors}, not at {example['fails_at']}"
