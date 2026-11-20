"""Build hook: put the standard's v1 schemas inside the wheel as `ext_r2c/schema/v1/`.

`uv build` builds the sdist first, then the wheel from the unpacked sdist, so the schemas are found
in one of two places: `../standard/v1/schema` in a checkout, `standard/v1/schema` in the sdist.
"""

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class SchemaHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        for source in (root.parent / "standard" / "v1" / "schema", root / "standard" / "v1" / "schema"):
            if source.is_dir():
                build_data["force_include"][str(source)] = "ext_r2c/schema/v1"
                return
        raise FileNotFoundError(f"standard/v1/schema not found next to or inside {root}")
