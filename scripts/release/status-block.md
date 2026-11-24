This is **{{tag}}**, an alpha pre-release of the Python SDK (package version `{{version}}`). The standard it implements, `standard/v1`, is a draft until its first outside adopter, so names and shapes may change. The package's version and the standard's version are separate numbers.

Install it by its full address. There is no version range that finds it, and no `--pre` is needed:

```text
ext-r2c[a2a,mcp,langgraph] @ {{address}}
```

The wheel is `{{wheel}}`; `SHA256SUMS` on this page lists its checksum and the source archive's. The bare name `ext-r2c` is **not** this project's address: PyPI has no package of that name today, and anyone may register it.

The example of two agents that call each other is in `examples/langgraph_agent/` of the tagged source; run it from a checkout of `{{tag}}`.
