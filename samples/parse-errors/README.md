# samples/parse-errors — a file semgrep cannot read is not a scan that failed

Fixtures for #43. Two directories, because the fix has two halves and each one
is a way of being wrong.

## What went wrong

`scripts/policy.py classify` treated **any** non-empty `.errors` as a broken
scan and exited 2. A real C# codebase that uses C# 12 primary constructors —
`public sealed class Thing(Dep dep)` — hit that on every such file:

```
Ran 22 rules on 29 files: 0 findings.
error: semgrep reported 6 error(s); refusing to treat the result as a
finding set: Syntax error ...
```

Two problems, of different severity:

1. **The gate was red on green code.** There is nothing a consumer can do about
   semgrep's parser, and a check that fails for reasons you cannot fix is a
   check people learn to ignore.
2. **The worse one: those files were not being scanned at all.** A parse error
   means no rule ran against the file. That was being reported as a *failure*,
   which at least made noise — but never as what it actually is, a hole in
   coverage with a name and a count.

`semgrep 1.172.0` is the newest release on PyPI as of 2026-08-05 and `1.145.0`
behaves identically, so upgrading is not a fix.

## What the two directories prove

| Directory | Contents | Expected |
|---|---|---|
| `mixed/` | one unparseable file **and** one parseable file with a planted finding | **not** a scan failure: gate reports the finding, plus `semgrep_unparsed=1` and a named Coverage block |
| `total/` | the unparseable file alone | exit **2** — every file semgrep looked at failed to parse, so `results: []` means "nobody looked" |

`total/` is the guard against overcorrecting. Downgrading parse errors to a
warning without it would mean a repo whose entire house style semgrep cannot
read reports a clean gate forever.

`mixed/Parseable.cs` is the other guard, in the other direction: without a real
finding beside the unparseable file, "1 unparsed, gate clean" cannot be
distinguished from "semgrep fell over and reported nothing".

## Why it lives outside the scanned tree

Excluded in the repo's own `.maxi-quality.yml`, for the reason `samples/policy/`
is: a fixture for one subsystem must not shift another's expected counts. Here
that is not just tidiness — `scripts/check-expected.py` **refuses any run whose
`.errors` is non-empty**, so an unparseable file left in the scanned tree would
fail `layer2-counts` outright, and the fixture would be untestable in the very
repo that ships it.

CI scans each directory explicitly as a target, the same way the policy
fixtures are driven.

## Do not "fix" these files

`PrimaryConstructor.cs` is valid C# and compiles. It is here precisely because
semgrep cannot parse it. Rewriting it into a conventional constructor deletes
the test.
