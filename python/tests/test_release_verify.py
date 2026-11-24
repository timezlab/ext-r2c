"""`scripts/release/verify.py`: after publishing, the files anyone can download are the files that were tested
(spec 008, contracts/scripts.md, FR-013). A local HTTP server on 127.0.0.1 stands in for GitHub's download
address; the script is given its `--base-url` for that, and by default builds the real address.
"""

from __future__ import annotations

import hashlib
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from release_fixtures import DEFAULT_VERSION, load_script, make_dist, planted

VERSION = DEFAULT_VERSION
TAG = f"v{VERSION}"
REPOSITORY = "owner/name"
WHEEL = f"ext_r2c-{VERSION}-py3-none-any.whl"
SDIST = f"ext_r2c-{VERSION}.tar.gz"
SUMS = "SHA256SUMS"


@pytest.fixture(scope="module")
def verify():
    return load_script("verify")


class Public:
    """A server that serves a release's files and records every request it gets."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.fail_first: dict[str, int] = {}  # name -> how many of its first requests answer 503
        self.cut_first: dict[str, int] = {}  # name -> how many of its first requests are cut off in the middle
        self.short_first: dict[str, int] = {}  # name -> how many of its first requests promise 100 bytes and send 5
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (the name the base class calls)
                name = self.path.rsplit("/", 1)[-1]
                owner.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                if owner.fail_first.get(name, 0) > 0:
                    owner.fail_first[name] -= 1
                    self.send_error(503)
                elif owner.cut_first.get(name, 0) > 0:
                    owner.cut_first[name] -= 1
                    self.send_response(200)
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.write(b"20\r\nshort")  # a chunk of 32 bytes is announced, 5 arrive, the line closes
                    self.wfile.flush()
                    self.close_connection = True
                elif owner.short_first.get(name, 0) > 0:
                    owner.short_first[name] -= 1
                    self.send_response(200)
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.write(b"short")  # urllib's read(n) hands these 5 bytes over without an error
                    self.wfile.flush()
                    self.close_connection = True
                elif name in owner.files and self.path == f"/releases/download/{TAG}/{name}":
                    body = owner.files[name]
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(404)

            def log_message(self, *args: object) -> None:  # keep the test output quiet
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/releases/download/{TAG}/"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def public(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> Iterator[Public]:
    """A good release: the wheel, the sdist and the list that names them, served."""
    dist = make_dist(tmp_path / "built")
    assert load_script("sums").main(["write", "--dir", str(dist)]) == 0
    capsys.readouterr()
    served = Public({name: (dist / name).read_bytes() for name in (WHEEL, SDIST, SUMS)})
    yield served
    served.close()


def argv(public: Public, out: Path, **overrides: str) -> list[str]:
    values = {
        "--tag": TAG,
        "--repository": REPOSITORY,
        "--dir": str(out),
        "--base-url": public.base_url,
        "--attempts": "1",
        "--pause": "0",
    }
    values.update(overrides)
    return [part for pair in values.items() for part in pair]


def refused(verify, args: list[str], capsys: pytest.CaptureFixture[str], ident: str = "public-differs") -> str:
    assert verify.main(args) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith(f"refused [{ident}]:"), err
    assert "\n" not in err, "a refusal is one line"
    return err


def list_with(files: dict[str, bytes], wheel: bytes | None = None, sdist: bytes | None = None) -> bytes:
    """A `SHA256SUMS` for the given contents, in the format `sha256sum` writes."""
    lines = {
        WHEEL: hashlib.sha256(files[WHEEL] if wheel is None else wheel).hexdigest(),
        SDIST: hashlib.sha256(files[SDIST] if sdist is None else sdist).hexdigest(),
    }
    return "".join(f"{sha}  {name}\n" for name, sha in sorted(lines.items())).encode()


# --- the good run ------------------------------------------------------------------------------------------


def test_files_that_equal_the_list_pass_and_are_kept(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "public"
    assert verify.main(argv(public, out)) == 0
    assert f"verify ok: {VERSION}" in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in out.iterdir()} == public.files
    assert sorted(path.rsplit("/", 1)[-1] for path, _ in public.requests) == sorted([WHEEL, SDIST, SUMS])


def test_no_request_carries_an_authorization_header_or_the_token_in_the_environment(
    verify, public: Public, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = planted("token-github")
    monkeypatch.setenv("GH_TOKEN", token)
    monkeypatch.setenv("GITHUB_TOKEN", token)
    assert verify.main(argv(public, tmp_path / "public")) == 0
    assert public.requests, "the server was reached"
    for path, headers in public.requests:
        assert "authorization" not in headers, path
        assert token not in path and all(token not in value for value in headers.values()), path


def test_the_default_address_is_the_one_an_adopter_installs_from(verify) -> None:
    from release_common import address

    base = verify.base_url(REPOSITORY, TAG)
    assert base == f"https://github.com/{REPOSITORY}/releases/download/{TAG}/"
    assert base + WHEEL == address(REPOSITORY, VERSION)


# --- what is refused ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [WHEEL, SDIST])
def test_an_archive_that_differs_from_the_list_is_refused_and_named(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    secret_text = "alice@acme-corp" + ".io"
    public.files[name] = secret_text.encode()
    err = refused(verify, argv(public, tmp_path / "public"), capsys)
    assert name in err
    assert secret_text not in err, "a refusal never quotes what it read"


def test_a_list_that_names_other_bytes_is_refused(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    public.files[SUMS] = list_with(public.files, wheel=b"some other wheel")
    err = refused(verify, argv(public, tmp_path / "public"), capsys)
    assert WHEEL in err


def test_a_list_without_the_sdist_is_refused(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    only_wheel = f"{hashlib.sha256(public.files[WHEEL]).hexdigest()}  {WHEEL}\n"
    public.files[SUMS] = only_wheel.encode()
    err = refused(verify, argv(public, tmp_path / "public"), capsys)
    assert SDIST in err


@pytest.mark.parametrize("name", [WHEEL, SDIST, SUMS])
def test_a_file_that_is_not_there_is_refused_with_its_name_and_the_status(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    del public.files[name]
    err = refused(verify, argv(public, tmp_path / "public"), capsys)
    assert name in err and "404" in err


def test_a_server_that_is_not_there_is_refused(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argv(public, tmp_path / "public")
    public.close()
    err = refused(verify, args, capsys)
    assert "could not download" in err


# --- a release that is a moment late -----------------------------------------------------------------------


def test_a_file_that_answers_late_is_asked_again(verify, public: Public, tmp_path: Path) -> None:
    public.fail_first[SUMS] = 1
    assert verify.main(argv(public, tmp_path / "public", **{"--attempts": "2"})) == 0
    assert [path.rsplit("/", 1)[-1] for path, _ in public.requests].count(SUMS) == 2


def test_a_body_that_is_cut_off_is_asked_again(verify, public: Public, tmp_path: Path) -> None:
    public.cut_first[SUMS] = 1
    assert verify.main(argv(public, tmp_path / "public", **{"--attempts": "2"})) == 0
    assert [path.rsplit("/", 1)[-1] for path, _ in public.requests].count(SUMS) == 2


def test_a_body_that_is_cut_off_on_the_last_attempt_is_a_refusal_not_a_crash(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    public.cut_first[SUMS] = 1
    err = refused(verify, argv(public, tmp_path / "public"), capsys)
    assert SUMS in err and "could not download" in err


def test_a_body_shorter_than_it_promised_is_asked_again(verify, public: Public, tmp_path: Path) -> None:
    public.short_first[WHEEL] = 1
    assert verify.main(argv(public, tmp_path / "public", **{"--attempts": "2"})) == 0
    assert [path.rsplit("/", 1)[-1] for path, _ in public.requests].count(WHEEL) == 2


def test_a_body_shorter_than_it_promised_is_a_download_failure_not_a_checksum_mismatch(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    public.short_first[WHEEL] = 1
    err = refused(verify, argv(public, tmp_path / "public"), capsys)
    assert WHEEL in err and "could not download" in err and "cut off" in err


def test_an_address_without_its_last_slash_still_names_the_files(verify, public: Public, tmp_path: Path) -> None:
    assert verify.main(argv(public, tmp_path / "public", **{"--base-url": public.base_url.rstrip("/")})) == 0


def test_one_attempt_is_one_attempt(verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    public.fail_first[SUMS] = 1
    refused(verify, argv(public, tmp_path / "public"), capsys)
    assert [path.rsplit("/", 1)[-1] for path, _ in public.requests].count(SUMS) == 1


# --- misuse ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"--repository": "owner"},
        {"--repository": "owner/name\n"},
        {"--base-url": "file:///etc/"},
        {"--attempts": "0"},
        {"--pause": "nan"},
        {"--pause": "inf"},
        {"--pause": "-1"},
    ],
)
def test_bad_arguments_are_misuse_and_make_no_request(
    verify, public: Public, tmp_path: Path, bad: dict[str, str]
) -> None:
    with pytest.raises(SystemExit) as caught:
        verify.main(argv(public, tmp_path / "public", **bad))
    assert caught.value.code == 2
    assert public.requests == []


@pytest.mark.parametrize(
    ("tag", "ident"),
    [("0.1.0a1", "version-grammar"), ("x0.1.0a1", "version-grammar"), ("v1.0.0", "prerelease-only")],
)
def test_a_tag_that_is_not_v_and_a_pre_release_is_refused_before_any_request(
    verify, public: Public, tmp_path: Path, capsys: pytest.CaptureFixture[str], tag: str, ident: str
) -> None:
    refused(verify, argv(public, tmp_path / "public", **{"--tag": tag}), capsys, ident)
    assert public.requests == []
