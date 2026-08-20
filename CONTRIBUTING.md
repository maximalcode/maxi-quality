# Contributing

This is a personal baseline that happens to be public. Issues and discussion are
welcome; please read the three hard rules first. The first two are why the
project has stayed useful rather than growing into a rule zoo. The third is why
a merge here does not surprise anyone downstream.

## Rule 1 — the ruleset is capped at 12 conventions

Twelve. Not "twelve for now". The budget is **fully spent**, and the inventory
is in [`docs/REFERENCE.md`](docs/REFERENCE.md#the-ruleset--12-conventions-28-rule-ids).

Adding a thirteenth convention means **removing one**. This is not gatekeeping
for its own sake: rule-writing is infinitely expandable and feels productive, so
without a hard cap the ruleset grows until it produces more noise than signal
and someone switches it off. A cap forces every rule to keep earning its place.

A new rule is justified by **a real bug that slipped through** — a link to the
incident, the PR, or the outage. It is never justified by "this would be nice to
catch". If your rule is genuinely better than one of the twelve, say which one it
replaces and why.

Note the distinction: **12 conventions, currently 40 rule ids.** Semgrep patterns
are language-specific, so one convention needs a separate id per language when
the syntax differs. Splitting an existing convention into a per-language id is
not new scope. Inventing a new convention is.

## Rule 2 — `samples/` is the test suite, and you may not weaken it

Every config is proven by an intentionally-bad sample that must fail, with an
**exact expected set of findings**, plus a `-clean` counterpart that must pass with zero
findings. Both halves matter: a config that flags everything is as useless as one
that flags nothing.

If a sample stops failing, **the config regressed — fix the config.** Never make
a sample pass by adding a disable comment, a `NoWarn`, or a suppression inside
the fixture. Never adjust an expected count to match new output without saying,
in the commit message, what changed and why the new number is correct.

The same applies to a rule's escape hatch. If a rule's message tells you how to
satisfy it, there must be a fixture proving that instruction actually works. This
is not hypothetical: `catch-and-swallow` told people to explain the silence in a
comment, comments are not AST nodes, and following the instruction verbatim did
not clear the finding — 4 out of 4 real-world hits were false positives.

**A fixture cannot prove a configuration**, only the part of it the fixture
happens to reach, so every config also has a snapshot of what it *resolves to*.
All four must be regenerated deliberately when a tool is bumped:

```bash
node scripts/snapshot-eslint-rules.mjs --check     # the enabled ESLint rule set
node scripts/snapshot-tsconfig.mjs --check         # tsc --showConfig
./scripts/snapshot-msbuild-props.sh --check        # dotnet msbuild -getProperty
python3 scripts/snapshot-python-settings.py --check # ruff + mypy's own resolvers
```

Each asks the **tool's own resolver**, never the config file — the file says
what we wrote, the resolver says what survived `extends`, conditions, defaults
and alias expansion. For mypy that gap is the whole point: `strict = True` is
one line in the ini and fourteen booleans in the resolver.

They exist because the gap was measured, not imagined. 94% of the ESLint
baseline could be deleted with every finding assertion green. Every flag in
`tsconfig.strict.json` could be deleted with no job running `tsc` at all. And
the three `dotnet_naming_rule` blocks shipped enforcing nothing, because the
severity that governs the build was never set — a config can be **switched
off**, not merely unbaited, and those two look identical from outside.

**When you add a compiler flag, ablate its fixture.** Turn that one flag off and
confirm your new error is the one that disappears. An error attributed to the
wrong flag leaves CI red for a reason that survives deleting the flag you meant
to test — which has already happened once, and is written up in
[`samples/typescript-strict/README.md`](samples/typescript-strict/README.md).

## Rule 3 — PRs go to `develop`, never to `main`

`main` is not a checkpoint, it is a **release**. The moving `v1` tag follows it
automatically, so anything that lands on `main` is running in every consuming
repo that pinned `@v1` within about a minute.

So the flow is:

```
  feature branch ──PR──▶ develop ──PR──▶ main ──▶ v1 moves
     your work            default        maintainer   consumers
                          branch         decides      pick it up
```

`develop` is the default branch, so `gh pr create` and the web UI already target
it — you should not have to change the base. Both branches carry the same
protection: 26 required checks, admins included, branch must be up to date, no
force-pushes, no direct commits.

Promoting `develop` to `main` is a maintainer decision, because it is where the
version gets chosen. It is not part of a contribution, and a PR that targets
`main` will be asked to retarget rather than merged.

## Practical

- **Conventional commits**: `feat:`, `fix:`, `chore:`, `docs:`, `ci:`. One
  logical commit per unit of work.
- **Branch off `develop`, then PR back into it.** CI is the gate; nothing lands
  on either long-lived branch directly.
- **Third-party actions are pinned to a full commit SHA**, never a tag, and CI
  fails if one is not. Keep the tag as a trailing comment so Dependabot can still
  bump it.
- **Everything is free/OSS.** Zero spend is a success criterion, not a
  preference. A change that requires a paid tier will be declined regardless of
  merit.
- **Claims get measured.** The comparisons in `docs/` exist because assertions
  in this repo have been wrong before and were caught by running them. If you
  argue a tool or rule is better, bring the numbers.

## Running the test suite

`samples/` is this repo's test suite: intentionally-bad code the baseline
**must** reject, and clean counterparts it **must** accept. If a bad sample ever
passes, the config regressed — fix the config, not the sample. If a clean sample
starts failing, the config became over-strict — again fix the config, and never
silence it with a disable comment or a `NoWarn` inside the fixture.

It runs in about two minutes and needs Node, the .NET SDK, Python, the pinned
Rust toolchain (plus cargo-deny), and either the Layer 2 tools natively or
Docker. The full command list is in [`docs/STATUS.md`](docs/STATUS.md) §3.

### TypeScript

```bash
npm install
npm run verify:ts          # expect 14 errors, non-zero exit
npm run verify:ts:clean    # expect ZERO findings
```

Nine of the 14 come from `bad.ts` — floating promise, explicit `any`, unsafe
assignment, unsafe return, unsafe member access, `==`, unused variable, dead
store, non-null assertion — and five from `sonarjs.ts`, which baits the classes
SonarJS adds and typescript-eslint has no rule for:

| Planted bug | Rule |
|---|---|
| both `if`/`else` branches identical | `sonarjs/no-all-duplicated-branches` |
| two functions with identical bodies | `sonarjs/no-identical-functions` |
| a collection read but never filled | `sonarjs/no-empty-collection` |
| catastrophic-backtracking regex (ReDoS) | `sonarjs/slow-regex` |
| `eval` on a non-literal | `sonarjs/code-eval` |

SonarJS scored **1 of 8** against `bad.ts` when it was evaluated, which on our own
fixtures makes it look worthless — our fixtures bait our rules, so that scoreboard
under-counts by construction. The table above is the reverse probe, and it is what
earned the plugin its place (`docs/EVAL-vs-oss-tools.md` §2b).

Four of its rules are switched off, each for a measured reason. One is worth
knowing about: `sonarjs/no-redundant-optional` asks you to delete the `| undefined`
from `retries?: number | undefined`, and under the `exactOptionalPropertyTypes`
this baseline also ships, doing so makes `tsc` reject the code. A linter that
contradicts the compiler shipped in the same baseline is not a trade-off, it is a
bug, so the rule is off and `samples/typescript-clean` carries the shape to keep
it off.

The **compiler** is a separate gate with a separate fixture:

```bash
npm run verify:ts:types    # expect 12 diagnostics, exit 2
node scripts/snapshot-tsconfig.mjs --check
```

`tsconfig.strict.json` ships to every consumer and was once run by **nothing** —
13 of its 14 hand-written flags could each have been deleted with every job still
green. `samples/typescript-strict/` closes that: one file per flag, named after
the flag, pinned by rule/file/line. Each mapping was checked by **ablation** —
turning that one flag off and confirming that specific error is the one that
disappears. Worth the trouble: `noImplicitReturns` was first baited with a fixture
that actually failed on `strictNullChecks`, so deleting the flag would have left
CI red and looking fine.

Four flags no fixture can reach — `isolatedModules`, `esModuleInterop`,
`forceConsistentCasingInFileNames` and the emit trio — are covered by
`configs/typescript/tsconfig.snapshot.json`, which asserts what `tsc --showConfig`
**resolves** rather than what the JSON file says.

### The pre-commit hook

`hooks/pre-commit` is the one script here most likely to run on a laptop rather
than a runner, and **macOS still ships bash 3.2.57 as `/bin/bash`**. It was
written with `mapfile` and aborted every commit with `command not found` until
that was caught — by running it, not by reading it. CI greps the file for bash 4
constructs, with comments stripped, because the hook documents the bug by name
and an unstripped guard fails on its own explanation.

Test it the way it runs: install it into a scratch repo with `adopt.sh --hooks`
and drive real `git commit` calls. Calling the script directly misses both of
its interesting failure modes — git supplies its own environment, and the thing
being scanned is the **index**, not the working tree.

### The formatters

```bash
npm run verify:format      # Prettier, expect ZERO reformatted
ruff format --check --config configs/python/ruff.toml samples/python samples/python-clean
dotnet format whitespace samples/dotnet-clean --verify-no-changes
```

`samples/format/` is their fixture directory, and it is worth reading before
adding to it because a format fixture fails the usual test for a good one.

**A misformatted file proves a formatter ran. It does not prove which config it
ran with** — the tool's own defaults reject mangled code just as readily, so
`bad-format.ts` and `bad_format.py` stay red even if the config beside them is
deleted. That is the same trap as `samples/policy/`'s original `exclude`
fixture, which excluded a directory semgrep skips by default and so passed while
asserting nothing.

So each format config also gets an **ablation** fixture — a file that is correct
under our settings and wrong under the tool's defaults, checked both ways round
with the two verdicts required to differ:

| Fixture | Green under | Red under |
|---|---|---|
| `needs-width-100.ts` | `printWidth: 100` | Prettier's default 80 |
| `needs_width_100.py` | `line-length = 100` | ruff's default 88 (`--isolated`) |
| `MissingFinalNewline.cs` | no `.editorconfig` | `insert_final_newline` from `configs/editorconfig` |

The C# one is the clearest case for why this is necessary: for C# almost
everything in `configs/editorconfig` agrees with `dotnet format`'s own defaults,
so without an ablation the whole file could be emptied and the gate would stay
green.

Two mechanical things that will trip you up:

- `samples/format/` is in `.prettierignore` so `npm run format` cannot repair
  the fixtures. The gate steps pass `--ignore-path /dev/null` to look past it.
- `MissingFinalNewline.cs` is stored **without** a trailing newline. Most editors
  add one on save, so CI checks for that explicitly before running the ablation
  — write it with `printf`, not by hand.

### C# / .NET

```bash
cd samples/dotnet && dotnet build          # expect 23 errors, 0 warnings
cd ../dotnet-tests && dotnet build         # expect 3 errors, 0 warnings
cd ../dotnet-clean && dotnet build         # expect 0 errors, 0 warnings
```

| Planted bug | Caught by |
|---|---|
| unused private field | `CS0414`, `IDE0051`, `S1144` |
| culture-insensitive comparison | `CA1304`, `CA1310`, `CA1311`, `CA1862`, `RCS1155` |
| un-disposed `IDisposable` | `S2930` |
| unreachable code | `CS0162` |
| unused local | `CS0219`, `IDE0059`, `S1481` |
| interface without the `I` prefix | `IDE1006`, `S101` |
| type not PascalCase | `IDE1006`, `S101` |
| private field without `_camelCase` | `IDE1006` — **and nothing else** |
| unnecessary using · unread member · unused parameter · `null` into a non-nullable | `IDE0005`, `IDE0052`, `IDE0060`, `CS8625`, `CA1805` |

The three `dotnet_naming_rule` blocks once shipped enforcing **nothing** — not for
want of a fixture, but because `dotnet_diagnostic.IDE1006.severity` was never set,
so the build never reported them. Two of the three were masked by analyzers that
happen to overlap; the private-field convention was caught by no layer at all.

`samples/dotnet-tests` asserts from **both** sides, because a relaxation is only
correct if it stays narrow: `S1199`, `CA1822` and `S2325` must stay **silent** on
real test idioms, while `CS0414`, `IDE0051` and `S1144` must still **fire** on an
unread private fixture. Checking only that it fails would pass just as happily if
the waiver had swallowed everything. Control run: 6 errors with the waiver
removed, 3 with it. Since #56 the silent side also covers `IDE1006` under a
`tests/` path — `tests/FixtureNaming.cs` plants the un-prefixed fixture field
Consumer A measured 333 of, and `samples/dotnet/Naming.cs` stays the positive
control proving the diagnostic still fires outside test paths.

### Python

```bash
pip install -r samples/python/requirements-dev.txt
ruff check --output-format=concise samples/python      # expect 14 errors
mypy --config-file configs/python/mypy.ini samples/python/src   # expect 11
ruff check samples/python-clean                        # expect ZERO
```

The Ruff fixture plants at least one finding per selected family, and CI asserts
**family coverage separately from the total** — a total alone would still read 14
if half the ruleset were switched off and something else fired twice.

The mypy half is split across two files and the split is the point. `strict = True`
is an **alias**, not a setting: one line that expands to fourteen booleans.
`bad_types.py` would stay green if `strict` were downgraded to a hand-picked list,
so `bad_strict.py` baits the expansion itself — `warn_return_any`,
`disallow_any_generics`, `strict_equality`, `disallow_untyped_calls`.
`settings.snapshot.json` proves the alias **expands**; `bad_strict.py` proves the
expansion **does something**.

### Rust

```bash
npm run verify:rust        # expect 8 findings, non-zero exit (one is an ERROR: unsafe_code at forbid)
npm run verify:rust:clean  # expect ZERO warnings
(cd samples/rust && cargo deny check advisories)   # expect RUSTSEC-2021-0003, and only it
```

The eight findings cover every enabled tier — the `rust` group at `forbid`
(`unsafe_code`), `clippy::all`, `pedantic`, the curated nursery picks and a
cargo pick — and CI asserts tier coverage separately from the manifest, the
same belt the 13 Ruff families get. The advisory bait (`smallvec 1.6.0`) sits
behind a `cfg(windows)` gate: the lockfile entry is what cargo-deny reads, and
no CI run ever builds the vulnerable crate. `settings.snapshot.json`'s Rust
twin (`configs/rust/settings.snapshot.json`) pins the **resolved** lint argv —
`forbid=unsafe_code` versus `deny` is invisible to every fixture, and the
snapshot is the only check that sees it.

### Dead code and unused dependencies

```bash
npm run verify:knip          # expect 7 findings, non-zero exit
npm run verify:knip:clean    # expect ZERO
pip install -r samples/python/requirements-dev.txt -r samples/deptry/requirements.txt
(cd samples/deptry && deptry src)            # expect DEP001 + DEP002
(cd samples/deptry-clean && deptry src)      # expect ZERO
```

Three ablations carry this suite, and each exists because the obvious assertion
proves nothing on its own:

- `samples/knip-clean` passes — and passes just as happily with `knip.json`
  moved aside unless its entry point is one knip would *not* find by default.
  The fixture's entry is `src/clean.ts` for exactly that reason.
- `samples/deptry-workspace` is clean **per package** and *not* clean scanned as
  one tree. Without the second half, a fixture with nothing to find would pass
  identically and `scripts/deptry-targets.py` would be unfalsifiable.
- The gating set is asserted separately from detection. knip finds seven things
  in `samples/knip`; only three of them may fail a build, and
  `scripts/deadcode-gate.py` is what decides which — so CI asserts the split at
  every setting a consumer can be in, including the `changed-only` ratchet in
  both directions.

The gating sets are deliberately narrower than what each tool reports: they hold
exactly the issue types the evaluation measured. **Widening one needs a
measurement, not an edit** — the same rule Rule 1 puts on the Semgrep cap.

### Layer 2 and the policy file

```bash
./scripts/scan.sh          # expect exit 1, 130 findings across all 40 rule ids
```

Each Semgrep sample carries **negative controls** that must stay silent, so the
rules are provably not just matching on names — a tracked `TODO(#412):`, all four
authz gates, a parameterised query, Prisma's tagged-template form, Dapper's
parameters, `return NotFound()`, a documented `catch`, an exception filter,
`createHash('sha256')`. Every exemption has bait behind it as well as a control:
an exemption with no counterexample is a hole nobody can see, and one with no
*positive* fixture can stop matching without anything going red.

The policy file has its own suite in `samples/policy/`, and every fixture there is
asserted **twice** — once with its policy and once with the policy ablated away.
That is not ceremony: the `exclude` fixture first excluded a directory called
`vendor/`, passed, and passed just as happily with the policy deleted, because
semgrep skips `vendor/` by default. See
[`samples/policy/README.md`](samples/policy/README.md).

### Examples

`examples/` holds copyable consumer repos. CI asserts each one scans clean, is
detected as the language it claims, and — for any that carry a `.maxi-quality.yml`
— that the policy actually resolves. A documented example that would not work is a
worse bug than no example.
