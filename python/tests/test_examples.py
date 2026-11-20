"""Every wire example: format, real protocol envelope, every R2C object, answer pairing.

Every invalid example: fails its kind's schema exactly where it says.
"""

from pathlib import Path
from typing import Any

import pytest

from r2c_check import (
    EXAMPLE_FORMAT,
    INVALID_FORMAT,
    EnvelopeError,
    check_a2a,
    check_format,
    check_mcp,
    error_paths,
    example_files,
    find_r2c_objects,
    form_schema,
    load_json,
    load_schemas,
    pointer,
    subschema_validator,
    unknown_kinds,
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


def test_some_valid_example_carries_an_unknown_kind(standard_dir: Path) -> None:
    known = set(load_schemas(standard_dir))
    found: list[tuple[str, str]] = []
    for p in VALID:
        try:
            found += unknown_kinds(load_json(p), known)
        except EnvelopeError:
            continue  # a broken example fails its own test_valid_example
    assert found, "no valid example carries an unknown kind, so R2C-CORE-5 is never exercised"


def _answer_problems(answer: dict[str, Any], request: dict[str, Any], schemas: dict[str, Any]) -> list[str]:
    """Why an answer's value does not fit its request (empty when it fits, or when declined)."""
    if answer.get("outcome") != "answered":
        return []
    value = answer.get("value")
    if request["kind"] == "question":
        errors = error_paths(validator(form_schema(request)), value)
        return [f"value does not fit question {request['id']} at {errors}"] if errors else []
    errors = error_paths(subschema_validator(schemas["answer"], "approval_value"), value)
    if errors:
        return [f"not an approval value at {errors}"]
    if value["decision"] not in request["decisions"]:
        return [f"decision {value['decision']!r} not offered"]
    args_schema = request.get("subject", {}).get("args_schema")
    if value["decision"] == "edit" and args_schema:
        errors = error_paths(validator(args_schema), value["args"])
        return [f"edited args break args_schema at {errors}"] if errors else []
    return []


@pytest.mark.parametrize("path", VALID, ids=_id)
def test_valid_example(path: Path, standard_dir: Path) -> None:
    example = load_json(path)
    problems = check_format(example, EXAMPLE_FORMAT)
    assert not problems, f"example format: {problems}"
    assert example["binding"] == path.parent.name, "binding does not match the folder"

    schemas = load_schemas(standard_dir)
    requests: dict[str, dict[str, Any]] = {}
    answers: list[tuple[int, str, dict[str, Any], dict[str, Any]]] = []
    reasks: list[tuple[int, str]] = []
    for n, step in enumerate(example["steps"]):
        if example["binding"] == "a2a":
            check_a2a(step["type"], step["body"])
        else:
            check_mcp(step)
        for where, obj in find_r2c_objects(example["binding"], step["body"], f"/steps/{n}/body"):
            kind = obj["kind"]
            if kind not in schemas:
                continue  # unknown kind: ignored by the standard (R2C-CORE-5)
            errors = [f"{pointer(e.absolute_path) or '/'}: {e.message}" for e in validator(schemas[kind]).iter_errors(obj)]
            assert not errors, f"{where}: {kind} fails its schema: {errors}"
            if kind in ("question", "approval"):
                requests[obj["id"]] = obj
                if "errors" in obj:
                    reasks.append((n, obj["id"]))
            elif kind == "answer" and obj["id"] in requests:
                answers.append((n, where, obj, requests[obj["id"]]))

    # An answer the remote asks again for (same id, with `errors`) must fail; any other must fit.
    for n, where, answer, request in answers:
        problems = _answer_problems(answer, request, schemas)
        if any(rid == answer["id"] and m > n for m, rid in reasks):
            assert problems, f"{where}: re-asked with errors, but the answer fits its request"
        else:
            assert not problems, f"{where}: {problems}"


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
