"""What the skills extension says on the wire and how it names things (spec 005, research R2, R3,
R9, R11 and `contracts/wire-mapping.md`): names, URIs, content types, cursors and the beta models.
Pure units: no folder, no server."""

from __future__ import annotations

import base64
import copy
import mimetypes
import pickle
from typing import Any

import mcp_types as types
import pytest
from ext_r2c.mcp.skills import _wire
from ext_r2c.mcp.skills._content import as_text_or_bytes, mime_for
from ext_r2c.mcp.skills._cursor import MAX_CURSOR_LENGTH, CursorError, decode_cursor, encode_cursor
from ext_r2c.mcp.skills._uris import (
    SCHEME,
    SKILL_FILE,
    char_unsafe,
    encode_uri,
    fold_authority,
    last_segments,
    name_unsafe,
    segment_ok,
    skill_name_ok,
)
from ext_r2c.mcp.skills._wire import (
    GetSkillParams,
    GetSkillRequest,
    GetSkillResult,
    ListSkillsRequest,
    ListSkillsResult,
    RawGetSkillResult,
    RawListSkillsResult,
    ReadDirectoryParams,
    ReadDirectoryRequest,
    ReadDirectoryResult,
    Skill,
    SkillResource,
)
from pydantic import ValidationError

DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def wire(model: Any) -> dict[str, Any]:
    """The JSON the model puts on the wire: by alias, without what is unset."""
    dumped: dict[str, Any] = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return dumped


# --- Names -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a", "a-b", "a1", "1", "0a", "abc-def-ghi", "a" * 64])
def test_a_valid_skill_name(name: str) -> None:
    assert skill_name_ok(name)


@pytest.mark.parametrize(
    "name",
    ["", "a" * 65, "A", "Abc", "-a", "a-", "-", "a--b", "a_b", "a b", "a.b", "é", "a\n", "\na", "ａ", "a٣", "a/b"],
)
def test_an_invalid_skill_name(name: str) -> None:
    assert not skill_name_ok(name)


@pytest.mark.parametrize("name", [None, 1, b"a", ["a"]])
def test_a_name_that_is_not_text_is_invalid(name: object) -> None:
    assert not skill_name_ok(name)


# --- URIs ------------------------------------------------------------------------------------------


def test_the_scheme_and_the_skill_file() -> None:
    assert SCHEME == "skill"
    assert SKILL_FILE == "SKILL.md"


def test_a_skill_uri() -> None:
    assert encode_uri(("team", "billing", "refunds"), file="SKILL.md") == "skill://team/billing/refunds/SKILL.md"


def test_a_directory_uri_has_no_trailing_slash() -> None:
    assert encode_uri(("team", "billing", "refunds")) == "skill://team/billing/refunds"
    assert encode_uri(("greetings",)) == "skill://greetings"


def test_a_file_below_a_folder() -> None:
    assert encode_uri(("team", "x"), file=("templates", "reply.md")) == "skill://team/x/templates/reply.md"


@pytest.mark.parametrize(
    ("char", "escaped"),
    [(" ", "%20"), ("é", "%C3%A9"), ("%", "%25"), ("+", "%2B"), ("#", "%23"), ("?", "%3F"), ("\\", "%5C"), ("/", "%2F")],
)
def test_a_special_character_in_a_segment_becomes_percent_escapes(char: str, escaped: str) -> None:
    assert encode_uri(("x", f"a{char}b"), file="SKILL.md") == f"skill://x/a{escaped}b/SKILL.md"
    assert encode_uri((f"a{char}b",), file=f"c{char}d.md") == f"skill://a{escaped}b/c{escaped}d.md"


def test_unreserved_characters_stay() -> None:
    segment = "AZaz09-._~"
    assert encode_uri((segment,), file="SKILL.md") == f"skill://{segment}/SKILL.md"


def test_the_uri_is_pure_ascii() -> None:
    segments = ("café", "日本語", "emoji 😀", "a@b:c[d]", "q\"'<>;=&$!*(),", "tab\there", "nul\x00")
    uri = encode_uri(segments, file="файл.txt")
    assert uri.isascii()
    assert " " not in uri
    assert uri.count("/") == len(segments) + 2  # scheme's two plus one before each segment after the first, and the file


@pytest.mark.parametrize("segments", [(), ("a", ""), ("a", "."), ("a", ".."), ("",)])
def test_a_segment_that_names_no_folder_is_refused(segments: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        encode_uri(segments)


def test_an_empty_or_dotted_file_part_is_refused() -> None:
    for bad in ("", ".", "..", ("a", ""), ("..", "b")):
        with pytest.raises(ValueError):
            encode_uri(("x",), file=bad)


def test_the_folded_uri_ignores_case_in_the_first_segment_only() -> None:
    assert fold_authority("skill://Team/x") == fold_authority("skill://team/x")
    assert fold_authority("skill://TEAM") == fold_authority("skill://team")
    assert fold_authority("skill://team/x") != fold_authority("skill://teams/x")
    assert fold_authority("skill://team/A") != fold_authority("skill://team/b")  # only the first segment counts
    assert fold_authority("skill://team/A") == "skill://team/A"  # and the rest is kept as it is


def test_the_folded_uri_folds_ascii_only() -> None:
    # An authority is compared as the host of a URI: RFC 3986 lowers ASCII letters, nothing else.
    assert fold_authority(encode_uri(("É",))) != fold_authority(encode_uri(("é",)))
    assert fold_authority(encode_uri(("É",))) == fold_authority(encode_uri(("É",)))


@pytest.mark.parametrize("segment", ["a", "caf%C3%A9", "a%20b", "50%25", "x+y", "SKILL.md", "...", ".hidden"])
def test_a_segment_that_decodes_to_a_name_is_ok(segment: str) -> None:
    assert segment_ok(segment)


@pytest.mark.parametrize(
    "segment",
    ["", ".", "..", "%2e", "%2E%2E", "a%2Fb", "a%5Cb", "a\\b", "a%0Ab", "a\nb", "%1b", "%7f", "a%E2%80%AEb", "a%E2%80%A8b", "a%C2%85b"],
    ids=["empty", "dot", "dot-dot", "encoded-dot", "encoded-dot-dot", "encoded-slash", "encoded-backslash", "backslash", "encoded-line-feed",
         "line-feed", "escape", "delete", "bidi-override", "line-separator", "next-line"],
)
def test_a_segment_that_is_not_a_name_is_not_ok(segment: str) -> None:
    assert not segment_ok(segment)


@pytest.mark.parametrize("name", ["a", "café", "日本語", "x y", "a" + chr(0x301), chr(0x1F468) + chr(0x200D) + chr(0x1F4BB)])
def test_a_name_that_is_text_in_any_script_is_not_unsafe(name: str) -> None:
    assert not name_unsafe(name)


@pytest.mark.parametrize("code", [0x00, 0x0A, 0x1B, 0x7F, 0x85, 0x5C, 0x061C, 0x200E, 0x200F, 0x2028, 0x2029, 0x202A, 0x202E, 0x2066, 0x2069])
def test_a_control_a_line_break_a_bidi_control_and_a_backslash_are_unsafe(code: int) -> None:
    assert char_unsafe(chr(code)) and name_unsafe("a" + chr(code) + "b")


@pytest.mark.parametrize("code", [0x20, 0x2F, 0x2E, 0x2027, 0x202F, 0x2065, 0x206A, 0x200D, 0x0301])
def test_the_neighbours_of_those_are_not_unsafe(code: int) -> None:
    assert not char_unsafe(chr(code))


@pytest.mark.parametrize(
    "segments",
    [("greetings",), ("team", "billing", "refunds"), ("team", "a b", "café", "50%", "x+y", "q?r#s")],
)
def test_last_segments_round_trips_an_encoded_uri(segments: tuple[str, ...]) -> None:
    uri = encode_uri(segments, file="SKILL.md")
    assert last_segments(uri, len(segments) + 1) == (*segments, "SKILL.md")
    assert last_segments(uri, 2) == (segments[-1], "SKILL.md")
    assert last_segments(uri, 1) == ("SKILL.md",)


def test_last_segments_returns_what_there_is() -> None:
    assert last_segments("skill://a/b/SKILL.md", 10) == ("a", "b", "SKILL.md")
    assert last_segments("skill://a/b/SKILL.md", 0) == ()


@pytest.mark.parametrize(
    "uri", ["", "skill:/a/SKILL.md", "skill:a/SKILL.md", "SKILL.md", "a/SKILL.md", "://a/SKILL.md", "1x://a/SKILL.md", "a b://a/SKILL.md"]
)
def test_last_segments_of_a_uri_that_does_not_begin_with_a_scheme_and_two_slashes(uri: str) -> None:
    assert last_segments(uri, 2) == ()


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("http://a/b/SKILL.md", ("b", "SKILL.md")),
        ("docs://x/SKILL.md", ("x", "SKILL.md")),
        ("file:///x/SKILL.md", ("x", "SKILL.md")),
        ("X-Skill+v1.2://a/SKILL.md", ("a", "SKILL.md")),
    ],
)
def test_last_segments_reads_any_scheme_because_the_extension_privileges_none(uri: str, expected: tuple[str, ...]) -> None:
    assert last_segments(uri, 2) == expected


def test_last_segments_decodes_percent_escapes() -> None:
    assert last_segments("skill://x/caf%C3%A9/SKILL.md", 2) == ("café", "SKILL.md")
    assert last_segments("skill://x/a%2Fb/SKILL.md", 2) == ("a/b", "SKILL.md")


def test_last_segments_does_not_read_a_query_or_a_fragment_apart() -> None:
    assert last_segments("skill://x/a/SKILL.md?v=1", 1) == ("SKILL.md?v=1",)
    assert last_segments("skill://x/a/SKILL.md#top", 1) == ("SKILL.md#top",)


# --- Content types and text versus bytes -----------------------------------------------------------

MIME_TABLE = {
    "md": "text/markdown",
    "txt": "text/plain",
    "json": "application/json",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "toml": "application/toml",
    "csv": "text/csv",
    "html": "text/html",
    "css": "text/css",
    "js": "text/javascript",
    "ts": "text/typescript",
    "py": "text/x-python",
    "sh": "text/x-shellscript",
    "xml": "application/xml",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "zip": "application/zip",
}


@pytest.mark.parametrize(("extension", "mime"), sorted(MIME_TABLE.items()))
def test_the_mime_table(extension: str, mime: str) -> None:
    assert mime_for(f"file.{extension}") == mime


@pytest.mark.parametrize(
    "name", ["data.xyz", "Makefile", "archive.tar.gz", "trailing.", "no-extension", "x.mdx", "x.m", "md", "png", "txt", ""]
)
def test_an_unknown_extension_is_octet_stream(name: str) -> None:
    assert mime_for(name) == "application/octet-stream"


def test_the_extension_is_compared_in_lower_case() -> None:
    assert mime_for("README.MD") == "text/markdown"
    assert mime_for("Logo.PNG") == "image/png"
    assert mime_for("a.JpEg") == "image/jpeg"


def test_a_path_is_read_by_its_last_component() -> None:
    assert mime_for("templates/reply.md") == "text/markdown"
    assert mime_for("dir.md/file.bin") == "application/octet-stream"


def test_skill_md_is_markdown() -> None:
    assert mime_for("SKILL.md") == "text/markdown"


def test_the_host_mime_database_is_not_consulted(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("mimetypes was consulted")

    monkeypatch.setattr(mimetypes, "guess_type", boom)
    monkeypatch.setattr(mimetypes, "guess_extension", boom)
    assert mime_for("a.md") == "text/markdown"
    assert mime_for("a.unknown") == "application/octet-stream"


@pytest.mark.parametrize(
    ("data", "text"),
    [
        (b"plain ascii\n", "plain ascii\n"),
        ("café ☕ 日本".encode(), "café ☕ 日本"),
        (b"", ""),
        (b"\xef\xbb\xbfwith a mark", "﻿with a mark"),
        (b"line one\r\nline two\r\n", "line one\r\nline two\r\n"),
        (b"nul \x00 inside", "nul \x00 inside"),
    ],
)
def test_bytes_that_are_utf_8_are_text(data: bytes, text: str) -> None:
    got = as_text_or_bytes(data)
    assert type(got) is str
    assert got == text
    assert got.encode("utf-8") == data


@pytest.mark.parametrize(
    "data",
    [
        "café".encode("latin-1"),
        b"\xff",
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        b"\xc0\x80",  # an overlong NUL
        b"\xed\xa0\x80",  # a lone surrogate, encoded
        b"abc\xe2\x82",  # a cut multi-byte character
        b"\xef\xbb",  # a cut byte-order mark
    ],
)
def test_bytes_that_are_not_utf_8_stay_bytes(data: bytes) -> None:
    got = as_text_or_bytes(data)
    assert type(got) is bytes
    assert got == data


# --- Cursors ---------------------------------------------------------------------------------------


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def test_a_cursor_round_trips() -> None:
    for offset in (0, 1, 24, 25, 59):
        assert decode_cursor(encode_cursor("g1f3", offset), "g1f3", 60) == offset


def test_a_cursor_is_opaque_url_safe_text_without_padding() -> None:
    cursor = encode_cursor("0123456789abcdef", 25)
    assert cursor
    assert all(c.isascii() and (c.isalnum() or c in "-_") for c in cursor)
    assert "=" not in cursor
    assert "/" not in cursor
    assert encode_cursor("g", 1) != encode_cursor("g", 2) != encode_cursor("h", 2)


def test_the_last_valid_offset_is_one_before_the_total() -> None:
    assert decode_cursor(encode_cursor("g", 59), "g", 60) == 59


@pytest.mark.parametrize(
    "cursor",
    ["", "!!!", "abc$", "a b", "é", "YWJj==", "MQ==", "a\n", "====", "A" * 257, "AAAA" * 100],
)
def test_a_cursor_that_is_not_ours(cursor: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(cursor, "g", 60)


@pytest.mark.parametrize(
    "text",
    ["g", "g,3", "g.", ".3", "g.x", "g.-1", "g.1.5", "g.+3", "g. 3", "g.3 ", "g.٣", "g.007", "g.1e1", "g.0x1", "g.3.", "g.²", "g.①"],
)
def test_a_cursor_of_a_wrong_shape(text: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(b64(text), "g", 10**9)


def test_the_cursor_length_cap_is_exact() -> None:
    fits = encode_cursor("g" * 190, 5)  # 192 bytes make 256 characters, no padding
    assert len(fits) == MAX_CURSOR_LENGTH == 256
    assert decode_cursor(fits, "g" * 190, 60) == 5
    over = encode_cursor("g" * 191, 5)  # one byte more: a cursor of the right form and generation, too long
    assert len(over) > MAX_CURSOR_LENGTH
    with pytest.raises(CursorError):
        decode_cursor(over, "g" * 191, 60)


def test_a_cursor_that_decodes_but_is_not_written_that_way_is_refused() -> None:
    good = encode_cursor("g", 1)
    assert decode_cursor(good, "g", 60) == 1
    # Each of these decodes to the same bytes as `good` under a lenient base64 reader.
    for variant in (good + "=", good + "==", good + "\n", " " + good, good[:2] + "!" + good[2:]):
        with pytest.raises(CursorError):
            decode_cursor(variant, "g", 60)


def test_a_cursor_of_another_generation() -> None:
    with pytest.raises(CursorError):
        decode_cursor(encode_cursor("other", 1), "g", 60)
    with pytest.raises(CursorError):
        decode_cursor(encode_cursor("g1", 1), "g", 60)  # a prefix is not the same generation
    with pytest.raises(CursorError):
        decode_cursor(encode_cursor("g", 1), "g1", 60)


def test_a_cursor_past_the_end() -> None:
    with pytest.raises(CursorError):
        decode_cursor(encode_cursor("g", 60), "g", 60)  # nothing is left after the last one
    with pytest.raises(CursorError):
        decode_cursor(encode_cursor("g", 61), "g", 60)
    with pytest.raises(CursorError):
        decode_cursor(encode_cursor("g", 0), "g", 0)  # an empty list has no second page


def test_the_cursor_error_is_a_value_error_with_a_fixed_message() -> None:
    with pytest.raises(CursorError) as caught:
        decode_cursor("!!!", "g", 60)
    assert isinstance(caught.value, ValueError)
    with pytest.raises(CursorError) as other:
        decode_cursor(encode_cursor("zz", 1), "g", 60)
    assert str(caught.value) == str(other.value)


def test_the_cursor_error_survives_a_pickle_and_a_copy() -> None:
    error = CursorError()
    for again in (pickle.loads(pickle.dumps(error)), copy.copy(error), copy.deepcopy(error)):
        assert type(again) is CursorError
        assert str(again) == str(error)


def test_a_cursor_is_not_built_from_a_dotted_generation_or_a_negative_offset() -> None:
    with pytest.raises(ValueError):
        encode_cursor("a.b", 1)
    with pytest.raises(ValueError):
        encode_cursor("g", -1)
    with pytest.raises(ValueError):
        encode_cursor("", 1)


# --- Wire models -----------------------------------------------------------------------------------


def skill(name: str = "refunds", uri: str = "skill://billing/refunds/SKILL.md", **extra: Any) -> Skill:
    return Skill(
        uri=uri,
        frontmatter={"name": name, "description": "Handle a refund request.", "license": "MIT"},
        resources=[
            SkillResource(uri=uri, digest=DIGEST, size=412),
            SkillResource(uri=uri.removesuffix("SKILL.md") + "templates/reply.md", digest=OTHER_DIGEST, size=96),
        ],
        **extra,
    )


SKILL_JSON = {
    "uri": "skill://billing/refunds/SKILL.md",
    "frontmatter": {"name": "refunds", "description": "Handle a refund request.", "license": "MIT"},
    "resources": [
        {"uri": "skill://billing/refunds/SKILL.md", "digest": DIGEST, "size": 412},
        {"uri": "skill://billing/refunds/templates/reply.md", "digest": OTHER_DIGEST, "size": 96},
    ],
}


def test_a_skill_has_no_meta_unless_it_is_given() -> None:
    assert wire(skill()) == SKILL_JSON
    assert "_meta" not in wire(skill())
    assert wire(skill(meta={"io.modelcontextprotocol.skills/x": 1}))["_meta"] == {"io.modelcontextprotocol.skills/x": 1}


def test_the_list_result_matches_the_contract() -> None:
    result = ListSkillsResult(skills=[skill()], next_cursor="Zy4y", ttl_ms=300_000, cache_scope="private")
    assert wire(result) == {
        "resultType": "complete",
        "skills": [SKILL_JSON],
        "nextCursor": "Zy4y",
        "ttlMs": 300_000,
        "cacheScope": "private",
    }


def test_the_last_page_has_no_next_cursor() -> None:
    result = ListSkillsResult(skills=[skill()], ttl_ms=0, cache_scope="public")
    assert wire(result) == {"resultType": "complete", "skills": [SKILL_JSON], "ttlMs": 0, "cacheScope": "public"}


def test_the_get_result_matches_the_contract() -> None:
    result = GetSkillResult(skill=skill(), ttl_ms=300_000, cache_scope="private")
    assert wire(result) == {"resultType": "complete", "skill": SKILL_JSON, "ttlMs": 300_000, "cacheScope": "private"}


def test_the_directory_result_matches_the_contract() -> None:
    result = ReadDirectoryResult(
        resources=[
            types.Resource(
                uri="skill://billing/refunds/SKILL.md",
                name="refunds",
                description="Handle a refund request.",
                mime_type="text/markdown",
            ),
            types.Resource(uri="skill://billing/refunds/templates", name="templates", mime_type="inode/directory"),
        ],
        ttl_ms=300_000,
        cache_scope="private",
    )
    assert wire(result) == {
        "resultType": "complete",
        "resources": [
            {
                "uri": "skill://billing/refunds/SKILL.md",
                "name": "refunds",
                "description": "Handle a refund request.",
                "mimeType": "text/markdown",
            },
            {"uri": "skill://billing/refunds/templates", "name": "templates", "mimeType": "inode/directory"},
        ],
        "ttlMs": 300_000,
        "cacheScope": "private",
    }


def test_an_empty_directory_result() -> None:
    assert wire(ReadDirectoryResult(resources=[], ttl_ms=1, cache_scope="private"))["resources"] == []


def test_the_result_type_is_always_complete() -> None:
    assert ListSkillsResult(skills=[]).result_type == "complete"
    assert GetSkillResult(skill=skill()).result_type == "complete"
    assert ReadDirectoryResult(resources=[]).result_type == "complete"


@pytest.mark.parametrize("scope", ["shared", "", "Private"])
def test_a_cache_scope_is_public_or_private(scope: str) -> None:
    with pytest.raises(ValidationError):
        GetSkillResult(skill=skill(), cache_scope=scope)  # type: ignore[arg-type]


def test_a_ttl_is_not_negative() -> None:
    with pytest.raises(ValidationError):
        GetSkillResult(skill=skill(), ttl_ms=-1)


@pytest.mark.parametrize(
    "digest",
    [
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        "sha256:" + "g" * 64,
        "sha512:" + "a" * 64,
        "SHA256:" + "a" * 64,
        "a" * 64,
        "sha256:" + "a" * 64 + "\n",
        " sha256:" + "a" * 64,
        "",
    ],
)
def test_a_resource_rejects_a_digest_that_is_not_sha256_and_lowercase_hex(digest: str) -> None:
    with pytest.raises(ValidationError):
        SkillResource(uri="skill://a/SKILL.md", digest=digest, size=1)


@pytest.mark.parametrize("size", [-1, 1.5, 3.0, "3", True, None])
def test_a_resource_rejects_a_size_that_is_not_a_natural_number(size: object) -> None:
    with pytest.raises(ValidationError):
        SkillResource(uri="skill://a/SKILL.md", digest=DIGEST, size=size)  # type: ignore[arg-type]


def test_a_resource_accepts_an_empty_file_and_the_largest_size() -> None:
    assert SkillResource(uri="skill://a/e.txt", digest=DIGEST, size=0).size == 0
    assert SkillResource(uri="skill://a/e.bin", digest=DIGEST, size=16_777_216).size == 16_777_216


def test_unknown_fields_are_ignored() -> None:
    parsed = Skill.model_validate({**SKILL_JSON, "future": {"x": 1}, "resources": [{**SKILL_JSON["resources"][0], "x": 1}]})
    assert parsed.uri == SKILL_JSON["uri"]
    assert parsed.resources[0].size == 412
    assert "future" not in wire(parsed)


def test_a_skill_reads_back_from_the_wire() -> None:
    parsed = Skill.model_validate({**SKILL_JSON, "_meta": {"k": 1}})
    assert parsed.meta == {"k": 1}
    assert wire(parsed)["_meta"] == {"k": 1}


def test_the_server_models_check_every_entry_they_carry() -> None:
    with pytest.raises(ValidationError):
        ListSkillsResult(skills=[{"uri": "skill://a/SKILL.md"}])  # type: ignore[list-item]
    with pytest.raises(ValidationError):
        GetSkillResult(skill={"uri": "skill://a/SKILL.md"})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ReadDirectoryResult(resources=[{"name": "no uri"}])  # type: ignore[list-item]


def test_a_skill_needs_its_uri_frontmatter_and_resources() -> None:
    for missing in ("uri", "frontmatter", "resources"):
        raw = {k: v for k, v in SKILL_JSON.items() if k != missing}
        with pytest.raises(ValidationError):
            Skill.model_validate(raw)


def test_the_typed_requests_keep_their_parameters() -> None:
    assert wire(ListSkillsRequest()) == {"method": "skills/list"}
    assert wire(ListSkillsRequest(params=types.PaginatedRequestParams(cursor="c1"))) == {
        "method": "skills/list",
        "params": {"cursor": "c1"},
    }
    assert wire(GetSkillRequest(params=GetSkillParams(uri="skill://a/SKILL.md"))) == {
        "method": "skills/get",
        "params": {"uri": "skill://a/SKILL.md"},
    }
    assert wire(ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://a", cursor="c2"))) == {
        "method": "resources/directory/read",
        "params": {"uri": "skill://a", "cursor": "c2"},
    }
    assert wire(ReadDirectoryRequest(params=ReadDirectoryParams(uri="skill://a")))["params"] == {"uri": "skill://a"}


def test_the_request_parameters_need_a_uri_that_is_text() -> None:
    with pytest.raises(ValidationError):
        GetSkillParams.model_validate({})
    with pytest.raises(ValidationError):
        GetSkillParams.model_validate({"uri": 5})
    with pytest.raises(ValidationError):
        ReadDirectoryParams.model_validate({"cursor": "c"})


def test_the_client_models_keep_the_entries_raw() -> None:
    raw = {
        "resultType": "complete",
        "skills": [{"anything": 1}, 5, "text", None, SKILL_JSON],
        "nextCursor": "n",
        "ttlMs": 10,
        "cacheScope": "public",
    }
    parsed = RawListSkillsResult.model_validate(raw)
    assert parsed.skills == raw["skills"]
    assert parsed.next_cursor == "n"
    assert (parsed.ttl_ms, parsed.cache_scope, parsed.result_type) == (10, "public", "complete")
    got = RawGetSkillResult.model_validate({"resultType": "complete", "skill": 7, "ttlMs": 1, "cacheScope": "private"})
    assert got.skill == 7


def test_the_client_models_take_a_result_without_hints() -> None:
    assert RawListSkillsResult.model_validate({"skills": []}).skills == []
    assert RawListSkillsResult.model_validate({"skills": []}).next_cursor is None


def test_the_client_directory_result_is_the_server_one() -> None:
    parsed = ReadDirectoryResult.model_validate(
        {"resources": [{"uri": "skill://a/SKILL.md", "name": "a", "mimeType": "text/markdown"}], "ttlMs": 1, "cacheScope": "private"}
    )
    assert parsed.resources[0].mime_type == "text/markdown"


def test_the_extension_id_and_the_method_names() -> None:
    assert _wire.EXTENSION_ID == "io.modelcontextprotocol/skills"
    assert ListSkillsRequest().method == _wire.METHOD_LIST == "skills/list"
    assert GetSkillRequest(params=GetSkillParams(uri="u")).method == _wire.METHOD_GET == "skills/get"
    assert ReadDirectoryRequest(params=ReadDirectoryParams(uri="u")).method == _wire.METHOD_DIRECTORY == "resources/directory/read"


def test_the_wire_module_names_the_beta_revision_and_the_base_protocol() -> None:
    doc = _wire.__doc__ or ""
    assert "beta" in doc.lower()
    assert "2026-11-21" in doc
    assert "2026-07-28" in doc
