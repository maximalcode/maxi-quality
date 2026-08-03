# Python, uv

```bash
"$BASELINE"/scripts/adopt.sh .    # writes ruff.base.toml + mypy.ini
uv sync
uv run ruff check src && uv run mypy src
```

**The `extend-` prefixes in `ruff.toml` are the thing to copy carefully.** Ruff's
plain `select` and `per-file-ignores` *replace* what they inherit rather than
merging, and neither warns when they do. Writing `[lint.per-file-ignores]` here
silently drops the baseline's own waivers — including `assert`-in-tests, so every
test file starts failing `S101`.

`mypy.ini` is a genuine copy because mypy has no `extend` at all. Add your
`[mypy-*]` sections for untyped third-party imports directly to it.
