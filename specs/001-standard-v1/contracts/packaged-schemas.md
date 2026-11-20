# Contract: schemas inside the Python package

- **Location in the installed package:** `ext_r2c/schema/v1/` holds `question.json`,
  `approval.json`, `answer.json`, `artifact-meta.json`, `activity.json` and `usage.json`, and
  nothing else.
- **Reading them:** `importlib.resources.files("ext_r2c") / "schema" / "v1" / "<file>"`. This
  feature adds no public Python function; a loader comes with spec 002.
- **Byte-identical:** each packaged file is byte for byte the file in `standard/v1/schema/` of
  the same commit.
- **Source:** the build hook `python/hatch_build.py` copies the schemas at build time.
  - It reads `../standard/v1/schema` when building from a checkout, and `standard/v1/schema` when
    building the wheel from the sdist.
  - It fails the build if neither directory exists.
  - No copy is committed under `python/src/`.
- **Stability:** the path `ext_r2c/schema/v1/` is public from this feature on. A v2 standard adds
  `ext_r2c/schema/v2/` beside it.
