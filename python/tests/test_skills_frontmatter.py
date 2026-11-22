"""The frontmatter reader of the skills extension (spec 005, research R7): a `SKILL.md` gives its
YAML header as plain JSON data, or a `FrontmatterError` with a reason from a fixed set that names
no content and no host path. Pure units: no folder, no server."""

from __future__ import annotations

import sys
import time
from typing import Any

import pytest
from ext_r2c.mcp.skills import _frontmatter
from ext_r2c.mcp.skills._frontmatter import (
    MAX_DEPTH,
    MAX_FRONTMATTER_BYTES,
    REASONS,
    FrontmatterError,
    read_frontmatter,
)


def doc(front: str, body: str = "# Body\n") -> str:
    """A `SKILL.md`: `front` is the text between the fences and ends with a newline."""
    return f"---\n{front}---\n{body}"


def refused(data: bytes | str) -> str:
    """The reason the reader gives for `data`; the test fails if it reads it."""
    with pytest.raises(FrontmatterError) as caught:
        read_frontmatter(data)
    return caught.value.reason


def nested(depth: int) -> str:
    """A flow mapping `depth` levels deep, the top one counted: a valid frontmatter by itself."""
    inner = "1"
    for _ in range(depth):
        inner = '{"k": ' + inner + "}"
    return inner + "\n"


# --- Keeps: every field passes through ------------------------------------------------------------


def test_every_field_passes_through() -> None:
    front = (
        "name: pdf-notes\n"
        "description: Summarise a PDF.\n"
        "license: MIT\n"
        "allowed-tools: Read Grep\n"
        "metadata:\n"
        "  author: example-org\n"
        '  version: "1.0"\n'
        "  tags: [alpha, beta]\n"
        "  nested: {deep: {deeper: 1}}\n"
        "count: 3\n"
        "ratio: 0.5\n"
        "nothing: null\n"
        "blank:\n"
        "on_flag: true\n"
        "off_flag: false\n"
        "list:\n"
        "  - one\n"
        "  - 2\n"
        "  - {three: 3}\n"
    )
    assert read_frontmatter(doc(front)) == {
        "name": "pdf-notes",
        "description": "Summarise a PDF.",
        "license": "MIT",
        "allowed-tools": "Read Grep",
        "metadata": {
            "author": "example-org",
            "version": "1.0",
            "tags": ["alpha", "beta"],
            "nested": {"deep": {"deeper": 1}},
        },
        "count": 3,
        "ratio": 0.5,
        "nothing": None,
        "blank": None,
        "on_flag": True,
        "off_flag": False,
        "list": ["one", 2, {"three": 3}],
    }


def test_the_result_is_plain_data() -> None:
    result = read_frontmatter(doc("a: {b: [1, two]}\n"))
    assert type(result) is dict
    assert type(result["a"]) is dict
    assert type(result["a"]["b"]) is list


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("3", 3),
        ("-4", -4),
        ("+7", 7),
        ("0", 0),
        ("1.5", 1.5),
        ("-0.25", -0.25),
        ("2.5e3", 2500.0),
        ("1e3", 1000.0),  # a number in JSON, so a float here, not the text "1e3"
        ("-2E-2", -0.02),
        ("1E+5", 100000.0),
    ],
)
def test_numbers_keep_their_type(text: str, value: int | float) -> None:
    got = read_frontmatter(doc(f"n: {text}\n"))["n"]
    assert got == value
    assert type(got) is type(value)


@pytest.mark.parametrize("text", ["true", "True", "TRUE"])
def test_true_is_a_boolean(text: str) -> None:
    assert read_frontmatter(doc(f"b: {text}\n")) == {"b": True}


@pytest.mark.parametrize("text", ["false", "False", "FALSE"])
def test_false_is_a_boolean(text: str) -> None:
    assert read_frontmatter(doc(f"b: {text}\n")) == {"b": False}


def test_bytes_and_text_read_the_same() -> None:
    text = doc("name: x\ndescription: café\n")
    assert read_frontmatter(text.encode("utf-8")) == read_frontmatter(text) == {"name": "x", "description": "café"}


# --- Text stays text -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2026-01-02",
        "2026-01-02T03:04:05Z",
        "2026-01-02 03:04:05",
        "yes", "Yes", "YES", "no", "No", "NO", "on", "On", "ON", "off", "Off", "OFF", "y", "n",
        "12:30", "1:30:45",
        "0755", "1_000", "0x1f",
        "<<", "=",
    ],
)  # fmt: skip
def test_a_plain_scalar_that_is_not_json_stays_the_text_the_author_wrote(text: str) -> None:
    got = read_frontmatter(doc(f"value: {text}\n"))["value"]
    assert got == text
    assert type(got) is str


def test_name_no_is_the_string_no() -> None:
    assert read_frontmatter(doc("name: no\ndescription: d\n"))["name"] == "no"


def test_quoted_values_are_text() -> None:
    assert read_frontmatter(doc("a: \"true\"\nb: '3'\nc: \"null\"\n")) == {"a": "true", "b": "3", "c": "null"}


def test_an_explicit_standard_tag_is_allowed() -> None:
    assert read_frontmatter(doc("a: !!str 12\n")) == {"a": "12"}


def test_a_quoted_merge_key_is_an_ordinary_key() -> None:
    assert read_frontmatter(doc('"<<": 1\n')) == {"<<": 1}


# --- Refuses ---------------------------------------------------------------------------------------

# One row per refusal: (id, document, reason). The reasons the rows use are checked against REASONS
# at the end, so a reason that no row can reach is a reason the reader does not need.
REFUSALS: list[tuple[str, bytes | str, str]] = [
    ("duplicate key", doc("name: a\nname: b\n"), "duplicate key"),
    ("duplicate key, nested", doc("m:\n  a: 1\n  a: 2\n"), "duplicate key"),
    ("duplicate key, quoted twin", doc('"a": 1\na: 2\n'), "duplicate key"),
    ("anchor", doc("a: &x 1\n"), "anchor or alias"),
    ("anchor and alias", doc("a: &x 1\nb: *x\n"), "anchor or alias"),
    ("alias alone", doc("b: *x\n"), "anchor or alias"),
    ("merge key", doc("<<: {b: 2}\n"), "merge key"),
    ("python object", doc('a: !!python/object/apply:os.system ["echo hi"]\n'), "unknown tag"),
    ("python name", doc("a: !!python/name:os.system\n"), "unknown tag"),
    ("binary", doc("a: !!binary aGk=\n"), "unknown tag"),
    ("set", doc("a: !!set {x, y}\n"), "unknown tag"),
    ("ordered map", doc("a: !!omap [x: 1]\n"), "unknown tag"),
    ("timestamp tag", doc("a: !!timestamp 2026-01-02\n"), "unknown tag"),
    ("custom tag", doc("a: !foo bar\n"), "unknown tag"),
    ("list on top", doc("- a\n- b\n"), "not a mapping"),
    ("scalar on top", doc("just text\n"), "not a mapping"),
    ("null on top", doc("~\n"), "not a mapping"),
    ("empty", "---\n---\nbody\n", "not a mapping"),
    ("integer key", doc("1: a\n"), "non-string key"),
    ("boolean key", doc("true: a\n"), "non-string key"),
    ("null key", doc("~: a\n"), "non-string key"),
    ("list key", doc("? [a, b]\n: c\n"), "non-string key"),
    ("infinity", doc("a: .inf\n"), "not json"),
    ("minus infinity", doc("a: -.inf\n"), "not json"),
    ("not a number", doc("a: .nan\n"), "not json"),
    ("a float too large", doc("a: 1.0e400\n"), "not json"),
    ("a lone surrogate", doc('a: "\\ud800"\n'), "not json"),
    # JSON text may carry a lone surrogate escape, and a client reads the file as text from it.
    ("a lone surrogate in the text", doc("d: \ud800\n"), "not utf-8"),
    ("a lone surrogate as a key", doc('"\\ud800": 1\n'), "not json"),
    ("too deep", doc(nested(MAX_DEPTH + 1)), "too deep"),
    ("too deep, lists", doc("k: " + "[" * (MAX_DEPTH + 1) + "]" * (MAX_DEPTH + 1) + "\n"), "too deep"),
    ("far too deep", doc("k: " + "[" * 5000 + "]" * 5000 + "\n"), "too deep"),
    ("no opening fence", "name: x\n---\nbody\n", "missing"),
    ("a blank line before the fence", "\n---\nname: x\n---\n", "missing"),
    ("an indented fence", " ---\nname: x\n---\n", "missing"),
    ("an opening fence with a trailing space", "--- \nname: x\n---\n", "missing"),
    ("a longer opening fence", "----\nname: x\n---\n", "missing"),
    ("nothing", "", "missing"),
    ("unclosed", "---\nname: x\n", "unclosed"),
    ("closing fence with a trailing space", "---\nname: x\n--- \nbody\n", "unclosed"),
    ("a longer closing fence", "---\nname: x\n----\nbody\n", "unclosed"),
    ("a closing fence with a comment", "---\nname: x\n--- # end\nbody\n", "unclosed"),
    ("only the opening fence", "---", "unclosed"),
    ("not utf-8 in the frontmatter", b"---\nname: \xff\n---\n", "not utf-8"),
    ("not utf-8 in the body", b"---\nname: x\n---\nbody \xff\n", "not utf-8"),
    ("utf-16", "---\nname: x\n---\n".encode("utf-16"), "not utf-8"),
    ("an unclosed flow list", doc("a: [one, two\n"), "syntax error"),
    ("an unterminated quote", doc('a: "text\n'), "syntax error"),
    ("two values", doc("a: b: c\n"), "syntax error"),
    ("a control character", doc("a: \x07\n"), "syntax error"),
    ("two documents", doc("a: 1\n...\nb: 2\n"), "syntax error"),
    ("too large", doc("d: " + "a" * MAX_FRONTMATTER_BYTES + "\n"), "too large"),
    ("too large in bytes, not in characters", doc("d: " + "é" * 40_000 + "\n"), "too large"),
]  # fmt: skip


@pytest.mark.parametrize(("data", "reason"), [(d, r) for _, d, r in REFUSALS], ids=[i for i, _, _ in REFUSALS])
def test_the_reader_refuses(data: bytes | str, reason: str) -> None:
    assert refused(data) == reason


def test_every_reason_is_reached_and_every_refusal_names_one() -> None:
    assert {reason for _, _, reason in REFUSALS} == set(REASONS)


def test_the_message_is_the_reason_and_names_no_content() -> None:
    secret = "tok-1f9c-secret"
    with pytest.raises(FrontmatterError) as caught:
        read_frontmatter(doc(f"a: [{secret}\n"))
    assert caught.value.reason == "syntax error"
    assert str(caught.value) == caught.value.reason
    assert secret not in repr(caught.value)
    assert isinstance(caught.value, ValueError)


def test_a_tag_that_would_run_code_runs_nothing() -> None:
    front = 'a: !!python/object/apply:builtins.exec ["import sys; sys._r2c_yaml_canary = 1"]\n'
    assert refused(doc(front)) == "unknown tag"
    assert not hasattr(sys, "_r2c_yaml_canary")


def test_an_alias_bomb_is_refused_for_its_aliases_in_bounded_time() -> None:
    nine = ",".join(['"lol"'] * 9)
    lines = [f"a: &a [{nine}]"]
    previous = "a"
    for name in "bcdefghi":
        refs = ",".join([f"*{previous}"] * 9)
        lines.append(f"{name}: &{name} [{refs}]")
        previous = name
    started = time.perf_counter()
    assert refused(doc("\n".join(lines) + "\n")) == "anchor or alias"
    assert time.perf_counter() - started < 5


def test_the_depth_cap_is_exact() -> None:
    assert MAX_DEPTH == 32
    deepest = read_frontmatter(doc(nested(MAX_DEPTH)))
    level = 0
    while isinstance(deepest, dict):
        deepest = deepest["k"]
        level += 1
    assert level == MAX_DEPTH
    assert refused(doc(nested(MAX_DEPTH + 1))) == "too deep"


def test_siblings_are_not_nesting() -> None:
    """The depth counts containers inside containers, not containers one after another."""
    front = "".join(f"k{i}: [[1], {{a: [2]}}]\n" for i in range(MAX_DEPTH * 3))
    assert len(read_frontmatter(doc(front))) == MAX_DEPTH * 3
    assert len(read_frontmatter(doc("l: [" + ",".join(["[1]"] * (MAX_DEPTH * 3)) + "]\n"))["l"]) == MAX_DEPTH * 3


def test_the_size_cap_is_exact_in_bytes() -> None:
    fits = "d: " + "a" * (MAX_FRONTMATTER_BYTES - 4) + "\n"
    assert len(fits.encode("utf-8")) == MAX_FRONTMATTER_BYTES == 65_536
    assert read_frontmatter(doc(fits))["d"] == "a" * (MAX_FRONTMATTER_BYTES - 4)
    over = "d: " + "a" * (MAX_FRONTMATTER_BYTES - 3) + "\n"  # one byte more, inside the value
    assert len(over.encode("utf-8")) == MAX_FRONTMATTER_BYTES + 1
    assert refused(doc(over)) == "too large"


def test_a_multibyte_value_fits_exactly_at_the_cap() -> None:
    fits = "d: " + "é" * ((MAX_FRONTMATTER_BYTES - 4) // 2) + "\n"
    assert len(fits.encode("utf-8")) == MAX_FRONTMATTER_BYTES
    assert read_frontmatter(doc(fits))["d"].startswith("é")


def test_the_size_cap_counts_bytes_not_characters() -> None:
    over = "d: " + "é" * ((MAX_FRONTMATTER_BYTES - 4) // 2 + 1) + "\n"
    assert len(over) < MAX_FRONTMATTER_BYTES < len(over.encode("utf-8"))  # few characters, too many bytes
    assert refused(doc(over)) == "too large"


def test_a_long_body_is_not_the_frontmatter() -> None:
    assert read_frontmatter(doc("name: x\n", body="line\n" * 100_000)) == {"name": "x"}


def test_an_unclosed_frontmatter_in_a_long_file_is_refused_at_once() -> None:
    started = time.perf_counter()
    assert refused("---\nname: x\n" + "line\n" * 2_000_000) == "unclosed"
    assert time.perf_counter() - started < 5


def test_a_failure_inside_the_loader_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def too_deep(*args: Any, **kwargs: Any) -> Any:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(_frontmatter.yaml, "load", too_deep)
    assert refused(doc("a: 1\n")) == "too deep"

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom at /srv/example/secret")

    monkeypatch.setattr(_frontmatter.yaml, "load", boom)
    with pytest.raises(FrontmatterError) as caught:
        read_frontmatter(doc("a: 1\n"))
    assert caught.value.reason == "syntax error"
    assert "/srv" not in str(caught.value)


@pytest.mark.parametrize(
    ("built", "reason"),
    [
        ({"a": object()}, "not json"),
        ({"a": {1, 2}}, "not json"),
        ({"a": b"bytes"}, "not json"),
        ({"a": [1, (2, 3)]}, "not json"),
        ({"a": {"b": float("inf")}}, "not json"),
        ({"a": float("nan")}, "not json"),
        ({"a": "lone \ud800 surrogate"}, "not json"),
        ({"lone \ud800 key": 1}, "not json"),
        ({1: "x"}, "non-string key"),
        ({"a": {None: 1}}, "non-string key"),
    ],
)
def test_what_the_loader_built_is_checked_to_be_json(monkeypatch: pytest.MonkeyPatch, built: Any, reason: str) -> None:
    """The loader cannot build these today; the check is what keeps a later change to it from
    putting a Python object on the wire, so it is tested by handing it the objects directly."""
    monkeypatch.setattr(_frontmatter.yaml, "load", lambda *args, **kwargs: built)
    assert refused(doc("a: 1\n")) == reason


# --- The shape of the document ---------------------------------------------------------------------


def test_the_frontmatter_ends_at_the_next_line_that_is_exactly_three_dashes() -> None:
    assert read_frontmatter("---\nname: x\n---\n---\nmore: 1\n---\n") == {"name": "x"}


def test_a_dash_line_in_the_body_does_not_matter() -> None:
    assert read_frontmatter(doc("name: x\n", body="text\n---\nnot: yaml: at: all\n---\n")) == {"name": "x"}


def test_three_dashes_inside_a_value_do_not_close_it() -> None:
    front = "a: \"x --- y\"\nb: '---'\nc: |\n  first\n  ---\n  last\nd: ---x\n"
    assert read_frontmatter(doc(front)) == {"a": "x --- y", "b": "---", "c": "first\n---\nlast\n", "d": "---x"}


def test_crlf_is_accepted() -> None:
    assert read_frontmatter("---\r\nname: x\r\ndescription: y\r\n---\r\nbody\r\n") == {"name": "x", "description": "y"}


def test_a_closing_fence_may_end_the_file() -> None:
    assert read_frontmatter("---\nname: x\n---") == {"name": "x"}


def test_a_byte_order_mark_is_skipped() -> None:
    data = "---\nname: x\n---\nbody\n"
    assert read_frontmatter(b"\xef\xbb\xbf" + data.encode("utf-8")) == {"name": "x"}
    assert read_frontmatter("\ufeff" + data) == {"name": "x"}


def test_a_second_byte_order_mark_is_not_skipped() -> None:
    assert refused("\ufeff\ufeff---\nname: x\n---\n") == "missing"
