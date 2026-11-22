"""The limits of the skills code (SEP-2640 and spec 005): one number for each, so that the server that
refuses to build over it and the client that refuses an entry over it cannot drift apart.

`MAX_FILES` and `MAX_BYTES` are the extension's own: how many files one skill may list, and how many
bytes they may hold in all. `MAX_NAME_LENGTH` and `MAX_DESCRIPTION_LENGTH` are those of the Agent
Skills format. `MAX_DEPTH` and `MAX_DIRECTORIES` are this package's, and only the server holds them:
how deep a scan goes, and how many folders it searches or a skill may hold, so that a tree it was
pointed at cannot make a scan run for long or take much memory. They are not on the wire.
"""

from __future__ import annotations

from typing import Final

MAX_FILES: Final = 512
MAX_BYTES: Final = 16 * 1024 * 1024
MAX_NAME_LENGTH: Final = 64
MAX_DESCRIPTION_LENGTH: Final = 1024
MAX_DEPTH: Final = 32  # folders below the root of a scan, and below the folder of a skill
MAX_DIRECTORIES: Final = 1024  # folders a scan searches that are not skills, and folders one skill holds
