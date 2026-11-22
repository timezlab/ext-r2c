"""The limits of one skill (SEP-2640): how many files it may list and how many bytes they may hold in
all. The server refuses to build a skill over them (phase 6) and the client refuses an entry over
them (phase 4); one number, so the two cannot drift apart."""

from __future__ import annotations

from typing import Final

MAX_FILES: Final = 512
MAX_BYTES: Final = 16 * 1024 * 1024
