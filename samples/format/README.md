# samples/format — the formatter's test suite

Five files, deliberately laid out wrong in five specific ways. They exist
because of the rule in `CLAUDE.md` §5: *every config in `configs/` must be
proven by an intentionally-bad sample that fails.* A format config that nothing
fails is indistinguishable from no format config at all.

They live here rather than inside `samples/typescript`, `samples/python` or
`samples/dotnet` for the reason `samples/semgrep/` and `samples/policy/` are
also separate (`docs/STATUS.md` §4): **a fixture for one subsystem must not
shift another subsystem's expected counts.** A misformatted file dropped into
`samples/python` would land in `samples/expected/ruff.json`; one in
`samples/typescript` would move the ESLint manifest. Nothing here is linted,
type-checked or compiled — these files are read by the formatters and by
nothing else.

They are exempt from the format gate itself via `.prettierignore` and by the
gate's own target lists. Formatting them would delete the test.

## What each file proves

| File | Tool | Fails because |
|---|---|---|
| `bad-format.ts` | `prettier --check` | mangled spacing, wrong quotes, no semicolons |
| `needs-width-100.ts` | `prettier --check` | **passes** under our config, fails under Prettier's default `printWidth: 80` |
| `bad_format.py` | `ruff format --check` | mangled spacing and quotes |
| `needs_width_100.py` | `ruff format --check` | **passes** under our config, fails under ruff's default `line-length = 88` |
| `MissingFinalNewline.cs` | `dotnet format whitespace` | **passes** with no `.editorconfig`, fails with the one we ship |

## The two-direction files are the point

`bad-format.ts` and `bad_format.py` prove a formatter ran. They do **not**
prove *which config* it ran with — Prettier's defaults reject them just as
readily, so those two alone would stay green if `configs/typescript/prettier.config.mjs`
were deleted outright.

The other three are ablations, in the sense `CONTRIBUTING.md` uses the word:
each is formatted **correctly under our settings and incorrectly under the
tool's defaults**, so the gate flips on exactly one setting.

- `needs-width-100.ts` has a line between 81 and 100 characters. Green at
  `printWidth: 100`, rewrapped at Prettier's default 80.
- `needs_width_100.py` is the same shape against ruff's default `line-length = 88`.
- `MissingFinalNewline.cs` ends without a trailing newline. `dotnet format
  whitespace` does not care by default; `insert_final_newline = true` in
  `configs/editorconfig` is what makes it an error — measured 2026-08-05, and
  it is why the C# step in CI runs the file **both** with and without the
  shipped `.editorconfig` and requires the verdicts to differ.

Without those three, all three format configs could be replaced by empty files
and every check here would still pass.
