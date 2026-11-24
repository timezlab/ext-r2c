"""The check of what anyone can download after a release is published (spec 008, FR-013).

    verify.py --tag TAG --repository OWNER/NAME --dir DIR [--base-url URL] [--attempts N] [--pause SECONDS]

The wheel, the sdist and `SHA256SUMS` are downloaded the way an adopter downloads them: from the public
address, with no credential, and no `Authorization` header. The list must name both archives and both must
equal it. The script then writes nothing but the three files into DIR.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from release_common import (
    REPOSITORY_RE,
    SUMS_LIST,
    Refusal,
    check_sums,
    run_main,
    sdist_name,
    version_from_tag,
    wheel_name,
)

TIMEOUT_SECONDS = 30
LARGEST_FILE = 64 * 1024 * 1024
IDENT = "public-differs"


def base_url(repository: str, tag: str) -> str:
    """Where GitHub serves a release's files to anyone."""
    return f"https://github.com/{repository}/releases/download/{tag}/"


def positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def not_negative(text: str) -> float:
    value = float(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return value


def parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="verify.py", description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--attempts", type=positive, default=1)
    parser.add_argument("--pause", type=not_negative, default=10.0)
    args = parser.parse_args(argv)
    if not REPOSITORY_RE.match(args.repository):
        parser.error("--repository must be OWNER/NAME")
    if args.base_url and not args.base_url.startswith(("http://", "https://")):
        parser.error("--base-url must be an http or https address")
    return args


def fetch(url: str, name: str) -> bytes:
    """One download, with no credential of any kind."""
    request = urllib.request.Request(url, headers={"User-Agent": "ext-r2c-release-verify"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            data = response.read(LARGEST_FILE + 1)
    except urllib.error.HTTPError as error:
        raise Refusal(IDENT, f"could not download {name}: HTTP {error.code}", "wait for the release to be public, or look at it on GitHub") from None
    except (urllib.error.URLError, OSError) as error:
        raise Refusal(IDENT, f"could not download {name}: {getattr(error, 'reason', error)}", "check the address and try again") from None
    if len(data) > LARGEST_FILE:
        raise Refusal(IDENT, f"{name} is larger than {LARGEST_FILE // (1024 * 1024)} MiB", "a release file is far smaller than that")
    return data


def download(base: str, name: str, attempts: int, pause: float) -> bytes:
    for attempt in range(1, attempts + 1):
        try:
            return fetch(base + name, name)
        except Refusal:
            if attempt == attempts:
                raise
            time.sleep(pause)
    raise AssertionError("unreachable: attempts is at least 1")


def body(argv: list[str] | None) -> int:
    args = parse(argv)
    version = version_from_tag(args.tag)
    base = args.base_url or base_url(args.repository, args.tag)
    args.dir.mkdir(parents=True, exist_ok=True)
    for name in (SUMS_LIST, wheel_name(version), sdist_name(version)):
        (args.dir / name).write_bytes(download(base, name, args.attempts, args.pause))
    check_sums(args.dir, IDENT)
    print(f"verify ok: {version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_main(lambda: body(argv))


if __name__ == "__main__":
    sys.exit(main())
