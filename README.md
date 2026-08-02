# maxi-quality

A reusable static-analysis baseline. One repo holds the lint/analyzer config and
the custom rules; your projects **consume** it instead of copy-paste-drifting
their own.

Free tools only — OSS analyzers plus the GitHub Actions free tier. Zero spend is
a requirement, not a preference.

---

## What you actually get

Two layers that do different jobs. **They are adopted independently, and they
cost wildly different amounts.** Knowing which is which is the whole decision.

| | **Layer 2** — the umbrella | **Layer 1** — the deep pass |
|---|---|---|
| What it is | Semgrep with this repo's 12 conventions, Gitleaks, OSV-Scanner | Your compiler and linter turned up: typescript-eslint `strict-type-checked`, Roslyn + SonarAnalyzer + Roslynator with `TreatWarningsAsErrors`, Ruff + mypy `strict` |
| Scope | Identical for every repo, any stack | Per language, only the ones you have |
| Config in your repo | **none** | 2–3 files copied in per language |
| How it runs | one job, no token, no checkout of this repo | your own build and lint step |
| Finds | secrets, vulnerable deps, injection, my own conventions | type holes, floating promises, dead code, un-disposed resources |
| **Can it grandfather your backlog?** | **yes** | **no** |

That last row is the one that decides your week.

### The ratchet asymmetry

Semgrep supports `--baseline-commit`, so Layer 2 can be told *"only fail on
code changed since this ref."* Your entire existing backlog is grandfathered on
day one and the gate still holds the line on everything new.

**Compilers and linters have no equivalent.** There is no per-finding
grandfathering in ESLint, Roslyn or mypy — a rule is either on and failing your
build, or off. So Layer 1 is all-or-nothing per rule, and adopting it on an
existing codebase is a cleanup sprint, not a config change.

Measured on real private codebases (full detail in
[`docs/STATUS.md`](docs/STATUS.md)):

| | Findings | What it takes to go green |
|---|---|---|
| **Layer 2**, Consumer A | 57 after rule tuning (70 before) | one line — `changed-only: origin/main`, and they are deferred |
| **Layer 2**, Consumer B | 15 after rule tuning (17 before) | same |
| **Layer 1** C#, Consumer A | **197** (~120 after tuning) | fix them, on a repo *already* at 0 warnings under its own strict props |
| **Layer 1** TS, Consumer A | **445** | fix them |
| **Layer 1** TS, Consumer B | **4,902** | fix them — see below |

So: **start with Layer 2.** It is one line of YAML, it grandfathers everything,
and it is the layer that catches leaked credentials and vulnerable dependencies.
Add Layer 1 per language when someone has the time to spend, one language at a
time.

### What this does not claim

- **Layer 1's first-run number says as much about your repo as about the
  baseline.** Consumer B's 4,902 traces to one root cause — an untyped boundary
  spraying `any` through 194 files. Signal-to-noise there was 36 bug-class
  findings inside 4,902, which is a bad trade; Consumer A was 35 inside 445,
  which is a good one. Measure before you commit.
- **Layer 1 TypeScript is not universally adoptable today.** `typescript-eslint`
  8.x supports `typescript >=4.8.4 <6.1.0`. A repo on TypeScript 7 gets a hard
  exit, not a degraded run.
- **12 conventions is not a security product.** The Semgrep rules are pattern
  matchers with a known evasion tail. They are a floor under obvious mistakes,
  next to Gitleaks and OSV-Scanner which do the shape-matching properly.
- **Nothing here has a dashboard.** SonarQube was evaluated and lost on
  detection — 1 of 8 planted TS bugs
  ([`EVAL-vs-sonarqube.md`](docs/EVAL-vs-sonarqube.md)). What replaced it is a
  [weekly report](#the-standing-report--what-the-gate-forgets) written into a
  GitHub issue.
- **Every number in `docs/` was measured, not estimated.** Where something was
  not measured, it says so.

---

**[`docs/CONCEPT.md`](docs/CONCEPT.md) is the source of truth** for the full
design and the layer model. The rest of this README is the adoption guide for
what exists today; anything still to be built is in the issue tracker.

> **The credentials in `samples/semgrep/` are fake and deliberate.** They are
> bait for the `hardcoded-secret-*` rules, and CI asserts those rules fire on
> them — so a secret scanner run against this repo **will** report findings, and
> that is the intended state. Every one is in `samples/`; none was ever valid.
> Gitleaks needs no action (`.gitleaks.toml` path-allowlists that directory and
> is loaded automatically); other scanners should exclude `samples/`. Details in
> [`SECURITY.md`](SECURITY.md) and
> [`samples/semgrep/README.md`](samples/semgrep/README.md).

Measurements in `docs/` refer to real private codebases as **Consumer A** (C# +
TypeScript monorepo), **Consumer B** (TypeScript app) and **Consumer C** (Python
service). The numbers are real; the names are not mine to publish. Bare issue
numbers in prose are provenance from the pre-publication tracker, which stayed
private — they are not this repo's issue numbers, which start fresh at #1.

Contributions: read [`CONTRIBUTING.md`](CONTRIBUTING.md) first — the ruleset is
capped at **12 conventions**, and the cap is the feature.

---

## Status: TypeScript, C# and Python

| Piece | State |
|---|---|
| Shared `.editorconfig` | ✅ `configs/editorconfig` |
| TypeScript — ESLint + tsconfig | ✅ `configs/typescript/` |
| C#/.NET — Roslyn + Sonar + Roslynator | ✅ `configs/dotnet/` |
| Python — Ruff + mypy strict | ✅ `configs/python/` — 13 rule families |
| Samples proving all three fail | ✅ `samples/` |
| Semgrep ruleset (Layer 2) | ✅ `semgrep/` — 12 conventions |
| `scan.sh` (Semgrep + Gitleaks + OSV) | ✅ `scripts/scan.sh` |
| Reusable CI workflow, `@v1` tag | ✅ `.github/workflows/quality.yml` + `actions/layer2/` |
| Java | ⬜ deliberately not built until a real project needs it |
| SonarQube CE dashboard | ❌ **dropped.** Measured in [`EVAL-vs-sonarqube.md`](docs/EVAL-vs-sonarqube.md) and lost: 1 of 8 planted TS bugs out of the box, no rule id for `no-floating-promises` or the `no-unsafe-*` family, custom C#/TS rules unavailable in every edition. The C# value is already banked in-build via `SonarAnalyzer.CSharp`. |

The acceptance test that gated the first tag: a scratch consumer repo,
onboarded from this README alone, went red in CI on a planted floating
promise — with the `dotnet` job correctly skipping itself and Layer 2 running
this repo's rules without any token in the consumer.

---

## What a consuming project does

### 0. The short way — `adopt.sh`

First, get the baseline onto your machine. Every command below refers to it as
`$BASELINE`, so this is the only line that depends on where you put it:

```bash
git clone https://github.com/maximalcode/maxi-quality.git
BASELINE="$PWD/maxi-quality"
```

Sections 1–5 below are what adoption actually consists of. `adopt.sh` does all
of it: detects which languages the repo really contains, copies the handful of
files that .NET and ESLint cannot consume remotely, and scaffolds the CI call.

```bash
"$BASELINE"/scripts/adopt.sh <repo> --dry-run   # look first
"$BASELINE"/scripts/adopt.sh <repo>
```

It **never overwrites an existing file** without `--force`. A repo that already
has its own `Directory.Build.props` gets a `skip` and a warning telling you to
merge by hand — silently replacing someone's build config is not a decision a
script should make. Re-running is safe: the C# `.editorconfig` section is
appended once, not once per run.

`--ref v1.0.4` pins the workflow to an immutable tag instead of the moving `v1`.
`--no-workflow` skips the CI scaffold.

CI proves this end-to-end in both directions: a repo adopted by the script
builds the clean fixture at 0 errors/0 warnings **and** rejects the bad fixture
with exactly the same 13 errors as the hand-configured sample. An adoption that
produced a gate which didn't gate would be worse than none, because it would
look green.

Read on if you'd rather do it by hand, or want to know what the script wrote.

> **Sections 2–4 are Layer 1** — one per language, and each is the expensive,
> non-grandfatherable half described above. **Section 5 is Layer 2**, the one
> line of YAML. If you are adopting on an existing repo, do section 5 first and
> come back to 2–4 when you have time budgeted.

### 1. Shared `.editorconfig` (every language)

```bash
cp "$BASELINE"/configs/editorconfig <repo>/.editorconfig
```

UTF-8, LF, final newline, trimmed trailing whitespace, 2-space default with
4-space for C#/Java/Python. For a C# repo, append the C# layer as well — see
below.

### 2. TypeScript — Layer 1

Like the .NET props, the TS pair is an **adopt-time copy** (concept G2: "copy
2–3 small files, done"). Two small files get stamped in and refreshed
deliberately:

```bash
cp "$BASELINE"/configs/typescript/eslint.config.mjs <repo>/eslint.base.mjs
cp "$BASELINE"/configs/typescript/tsconfig.strict.json <repo>/tsconfig.base.json
```

**Why a copy and not a dependency.** The design originated under a hard
constraint — the baseline was private, so a consumer's `GITHUB_TOKEN` could not
clone it and a git/npm dependency was impossible. That constraint is gone, and
the copy stayed, because the rest of the justification outlived it: a copy keeps
your install self-contained, makes every rule change arrive as a reviewable diff
in *your* repo, and means a bad day here cannot break your build. Publishing a
real npm package is now possible; it would be a deliberate decision measured
against those three, not an automatic one.

Install the toolchain (peer dependencies — they live in *your* project):

```bash
npm i -D eslint @eslint/js typescript-eslint typescript @types/node
```

Your entire `eslint.config.mjs`:

```js
import base from './eslint.base.mjs';

export default [
  ...base,
  { languageOptions: { parserOptions: { tsconfigRootDir: import.meta.dirname } } },
];
```

Your entire `tsconfig.json`:

```json
{
  "extends": "./tsconfig.base.json",
  "compilerOptions": { "rootDir": "src", "outDir": "dist", "types": ["node"] },
  "include": ["src"]
}
```

Then gate it — `--max-warnings 0` is what makes the `no-console` warning count:

```json
{ "scripts": { "lint": "eslint src --max-warnings 0" } }
```

**What you get:** `typescript-eslint` `strict-type-checked` +
`stylistic-type-checked` (type-aware, so it catches floating promises and `any`
leaks that a syntax-only linter cannot), plus `eqeqeq`, strict `no-unused-vars`
with a `_` escape hatch, and `ban-ts-comment` requiring a written reason.

**Two things to know:**
- Type-aware linting needs every linted file covered by a `tsconfig.json`.
  If yours isn't at the project root, that's what `tsconfigRootDir` is for.
- `typescript-eslint` 8.x supports `typescript >=4.8.4 <6.1.0`. TypeScript 7 is
  outside that range today; this repo pins `~6.0.3`.

### 3. C# / .NET — Layer 1

.NET has no remote "extends" for build props, so this is the one accepted copy
in the baseline. It is small and changes rarely.

```bash
cp "$BASELINE"/configs/dotnet/Directory.Build.props <repo>/Directory.Build.props
cat "$BASELINE"/configs/dotnet/dotnet.editorconfig >> <repo>/.editorconfig
```

That's it — MSBuild picks up `Directory.Build.props` for every project beneath
it. No `.csproj` changes.

**What you get:** `AnalysisLevel=latest-recommended`, `TreatWarningsAsErrors`,
`EnforceCodeStyleInBuild` (so `IDExxxx` style rules fail the build, not just the
IDE), nullable reference types on, plus `SonarAnalyzer.CSharp` and
`Roslynator.Analyzers` as `PrivateAssets=all` analyzer-only references.

**Two things to know:**
- Analyzer versions are pinned, not floating. With `TreatWarningsAsErrors`, an
  analyzer upgrade that adds rules is a breaking change — bump it deliberately.
- If the repo already has a `Directory.Build.props`, merge the properties in
  rather than overwriting, or `<Import Project="..."/>` this one at the top.

---

### 4. Python — Layer 1

Two tools, because they catch disjoint things: Ruff does not do inference, and
mypy does not flag a bare `except` or a hardcoded password.

```bash
cp "$BASELINE"/configs/python/ruff.toml <repo>/ruff.base.toml
cp "$BASELINE"/configs/python/mypy.ini  <repo>/mypy.ini
printf 'extend = "./ruff.base.toml"\n' > <repo>/ruff.toml
```

Then add `ruff` and `mypy` to your dev dependencies. CI runs the versions *you*
pin — it does not substitute its own.

**What you get:** 13 Ruff rule families (`E W F I B C4 UP N SIM ASYNC S T20
RUF`) at line-length 100, plus mypy `strict` with `warn_unreachable` and
`explicit_package_bases` on top.

**The one thing that will bite you:** Ruff's `select` and `per-file-ignores`
**replace** what they inherit rather than merging, and neither warns when they
do. Write `[lint.per-file-ignores]` in your own `ruff.toml` and you silently
drop the baseline's waivers — including `assert`-in-tests, so every test file
starts failing `S101`. Always use the `extend-` forms:

```toml
extend = "./ruff.base.toml"

[lint.extend-per-file-ignores]     # extend-, not bare
"scripts/**" = ["T20"]

[lint]
extend-select = ["PL"]             # extend-, not bare
```

`adopt.sh` writes the correct forms for you, and CI asserts it.

mypy has no `extend` at all, so `mypy.ini` is a genuine copy — add your
`[mypy-*]` sections for untyped third-party imports directly to it.

**Global `ignore` is deliberately empty.** An exemption belongs in
`per-file-ignores` where it is scoped and greppable; a global ignore is
invisible at the call site and applies to production code as readily as to the
one place that needed it.

---

### 5. CI — Layer 2, and the whole point

Your entire `.github/workflows/quality.yml`:

```yaml
name: quality
on: [push, pull_request]
jobs:
  quality:
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1
```

That one job auto-detects languages by lockfile/project glob and runs, per
detected language: the TS lint (npm or corepack-pnpm — a pnpm repo must pin
`"packageManager"` in package.json), the .NET build (the props make the build
the analysis run), and the Layer 2 umbrella (Semgrep + Gitleaks + OSV-Scanner).

**No token, no secret, no checkout of this repo.** The Layer 2 job receives
this repo's rules through GitHub's own action-download mechanism. Because this
repo is public, any repo may call it — there is nothing to configure and no
access policy to grant.

> For the record, since it shaped the design: while the baseline was private,
> consumers had to be owned by the same account, because a private repo's
> Actions access policy can open it to that account's own repos and to nothing
> else. That was the one real adoption limit, and going public removed it.

Adoption ratchet for a legacy repo (concept §8):

```yaml
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1
    with:
      changed-only: origin/main
```

---

## Layer 2 — the cross-language umbrella

Identical for every repo regardless of stack. Run it locally with:

```bash
./scripts/scan.sh                      # this repo
./scripts/scan.sh ~/path/to/other-repo # any repo
```

Three tools, one gate:

1. **Semgrep** with this repo's `semgrep/` rules — the selfmade part.
2. **Gitleaks** — secrets in the working tree and history.
3. **OSV-Scanner** — known-vulnerable dependencies via lockfiles.

`scan.sh` resolves each tool as **native binary → `uvx`/`docker` fallback →
skipped with a loud warning**. Nothing is ever silently not-run; the summary
names every tool and its verdict. Exit codes: `0` clean, `1` findings, `2` a tool
was unavailable under `--require-tools`, `3` usage error.

### Adopting on an existing repo (concept §8)

Do not big-bang-fix legacy findings. Start new-code-only, then tighten:

```bash
./scripts/scan.sh --changed-only origin/main --no-fail   # week 1: report only
./scripts/scan.sh --changed-only origin/main             # week 2: gate new code
./scripts/scan.sh                                        # once the tree is clean
```

`--changed-only` passes `--baseline-commit` to Semgrep and limits Gitleaks to
commits since the ref. OSV-Scanner has no changed-only mode on purpose — a
vulnerable dependency is vulnerable no matter which commit introduced it.

### SBOM and licence compliance

Both come out of OSV-Scanner, which is already installed and pinned for the
vulnerability scan. No fourth tool, no second supply chain to trust.

```bash
./scripts/scan.sh --sbom sbom.cdx.json                    # CycloneDX 1.6, never gates
./scripts/scan.sh --licenses 'MIT,Apache-2.0,ISC,BSD-3-Clause'   # gates
```

The **SBOM never gates** — an inventory is not a finding. It is produced by the
weekly [standing report](#the-standing-report--what-the-gate-forgets), which
summarises it as a licence breakdown in the issue and uploads the full CycloneDX
document as a workflow artifact.

The **licence gate is opt-in and has no default allowlist**, on purpose. Measured
against this repo's own tree, a plausible-looking allowlist flags
`SonarAnalyzer.CSharp` and `typing-extensions` as *non-standard* and `pathspec`
as MPL-2.0. A default would be wrong for someone on day one, and a licence gate
nobody chose is a licence gate everybody disables. Turn it on when you have a
policy:

```yaml
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1
    with:
      licenses: 'MIT,Apache-2.0,ISC,BSD-2-Clause,BSD-3-Clause'
```

Your own workspace packages resolve to `UNKNOWN` and will trip any allowlist —
add `UNKNOWN`, or exclude them in an `osv-scanner.toml`. The inventory in the
standing report shows you the real set before you commit to one.

---

## The standing report — what the gate forgets

`quality.yml` is a **gate**: it answers *is this PR clean?* On a repo adopted
with `--changed-only` it deliberately says nothing about the backlog it
grandfathered. That is correct for a gate and useless as a view of where the
repo stands — and it was the one thing SonarQube genuinely did better
([EVAL-vs-sonarqube.md](docs/EVAL-vs-sonarqube.md); it lost on detection, not on
memory).

So there is a second workflow that keeps state. **The database is a GitHub
issue** — one per repo, updated in place forever, holding the current breakdown,
the dependency inventory, and a history table that grows a row per run. There is
no server and no cloud here on purpose; code scanning would be the better store
but needs Advanced Security on a private personal-account repo, which is the paid
path.

```yaml
name: quality-report
on:
  schedule: [{ cron: '0 6 * * 1' }]
  workflow_dispatch:
permissions:
  contents: read
  issues: write            # REQUIRED — a reusable workflow cannot raise its own
jobs:
  report:
    uses: maximalcode/maxi-quality/.github/workflows/quality-report.yml@v1
```

Never a new issue per run. A weekly bot that opens issues becomes noise, noise
gets muted, and a muted report is worse than no report. The workflow outputs the
issue number so a caller can **assert the report actually landed** — without
that, a broken report path is indistinguishable from a clean repo, which is
precisely how it shipped broken once.

---

## Coverage — a ratchet, not a threshold

A fixed threshold is unusable on an existing repo. Below where you already are it
gates nothing; above it, every PR is red until someone does a coverage sprint.
Both end with the number being ignored.

So the gate asks the only question that is always answerable: **did this change
make it worse?** The floor is whatever the repo already achieves, it lives in a
committed file, and it only ever goes up. Same shape as `--changed-only`:
grandfather the backlog, refuse to grow it.

The consumer runs its own tests — this baseline cannot drive a test suite that
needs services, fixtures and a database, and every attempt to guess a "standard"
test command produces a gate that is skipped or wrong. It runs the part that is
genuinely shared:

```yaml
      - run: pnpm test --coverage.reporter=lcov     # or dotnet test --collect:"XPlat Code Coverage"
      - uses: maximalcode/maxi-quality/actions/coverage@v1
        with:
          report: |
            coverage/lcov.info
            **/coverage.cobertura.xml
```

lcov and Cobertura are both accepted, detected **by content, not by filename** —
`coverage.xml`, `cobertura.xml`, `lcov.info` and `coverage.info` are all in
circulation and CI configs rename them freely. Multiple reports are summed, so a
monorepo passes all of them and gets one number.

Line coverage only, deliberately: branch coverage is reported inconsistently
across producers, and a ratchet built on a number two tools disagree about fires
on tool upgrades rather than on real regressions.

Locally:

```bash
python3 scripts/coverage.py --report coverage/lcov.info --write   # record the first floor
python3 scripts/coverage.py --report coverage/lcov.info           # check
```

**Raising the floor is your commit, not ours.** `raise: true` rewrites the file;
it does not commit it. Committing from CI is a write to your default branch and
this baseline does not take that permission on your behalf. If you want it
automatic, that is six lines in your own workflow:

```yaml
      - uses: maximalcode/maxi-quality/actions/coverage@v1
        id: cov
        with: { report: coverage/lcov.info, raise: 'true' }
      - if: github.ref == 'refs/heads/main' && steps.cov.outputs.raised == 'true'
        run: |
          git config user.name github-actions
          git config user.email github-actions@github.com
          git commit -am "chore: raise coverage floor to ${{ steps.cov.outputs.coverage }}%"
          git push
```

Three failure modes are treated as errors rather than passes, because each one
turns the ratchet into a permanently green step: a report with **zero measurable
lines** (a broken coverage run, not 100%), a **missing report file**, and an
**unparseable floor** (never silently restarted from today's number).

---

## The ruleset — 12 conventions, 19 rule ids

Semgrep patterns are language-specific, so a convention whose C# and TypeScript
syntax differ needs one rule id per language with an identical message. That is
why 12 conventions produce 19 ids. **The cap is on conventions, and it is 12,
hard** — new ones get added when a real bug slips through, never speculatively.

| Convention | Rule id(s) | TS | C# |
|---|---|:--:|:--:|
| **general** | | | |
| TODO without a tracked issue | `todo-without-issue` | ✅ | ✅ |
| Empty catch block | `catch-and-swallow-{ts,dotnet}` | ✅ | ✅ |
| Printf-debugging left behind | `debug-print-left-behind-{ts,dotnet}` | ✅ | ✅ |
| Blocking on a Task | `sync-over-async` | — | ✅ |
| **security** | | | |
| SQL built by concat/interpolation | `sql-string-concat-{ts,dotnet}` | ✅ | ✅ |
| Shell command from interpolation | `command-injection-{ts,dotnet}` | ✅ | ✅ |
| MD5/SHA1/DES/RC4, any case, all DES variants | `weak-crypto` | ✅ | ✅ |
| Secret-named var assigned a literal | `hardcoded-secret-{ts,dotnet}` | ✅ | ✅ |
| **conventions** (mine) | | | |
| Ambient clock instead of injected | `no-ambient-clock` | ✅ | ✅ |
| Mutation without an authz gate | `mutation-requires-authz-{ts,dotnet}` | ✅ | ✅ |
| 403 for an invisible resource | `no-permission-denied-for-invisible-resource-{ts,dotnet}` | ✅ | ✅ |
| double/float for money | `no-float-for-money` | — | ✅ |

`no-ambient-clock` and `weak-crypto` are single rule ids covering both languages
— that is the concept §10 criterion (*the same rule fires in a TS and a C#
sample*) and it is asserted by the samples below.

**Division of labour with Gitleaks:** Gitleaks catches secrets whose *shape* is a
known token (AWS keys, GitHub PATs, JWTs). `hardcoded-secret-*` catches the
homegrown ones it cannot fingerprint, by matching the variable **name** instead.

---

## Verify

The `samples/` directory is this repo's test suite: intentionally-bad code that
the baseline **must** reject. If a sample ever passes, the config regressed —
fix the config, not the sample.

```bash
npm install
npm run verify:ts
```

Expect **8 errors** and a non-zero exit: floating promise, explicit `any`, unsafe
assignment, unsafe return, unsafe member access, `==`, unused variable, non-null
assertion.

```bash
cd samples/dotnet && dotnet build
```

Expect **13 errors, 0 warnings** and a non-zero exit, covering all five planted
classes:

| Planted bug | Caught by |
|---|---|
| unused private field | `CS0414`, `IDE0051`, `S1144` |
| culture-insensitive comparison | `CA1304`, `CA1310`, `CA1311`, `CA1862`, `RCS1155` |
| un-disposed `IDisposable` | `S2930` |
| unreachable code | `CS0162` |
| unused local | `CS0219`, `IDE0059`, `S1481` |

Note the `IDisposable` leak is caught by Sonar's `S2930`, not Roslyn's `CA2000`
— `CA2000` is not enabled at `latest-recommended`. The coverage is there; it just
comes from the third-party analyzer, which is a good argument for keeping Sonar
in the baseline rather than relying on the built-ins alone.

```bash
cd samples/dotnet-tests && dotnet build
```

Expect **3 errors, 0 warnings**. This sample asserts from both sides, because a
relaxation is only correct if it stays narrow:

| Rule | Expected | Why |
|---|---|---|
| `S1199`, `CA1822`, `S2325` | **silent** | real test idioms — arrange/act/assert blocks, non-static helpers |
| `CS0414`, `IDE0051`, `S1144` | **fire** | an unread private fixture is a dead test, not an idiom |

Checking only that it fails would pass just as happily if the waiver had
swallowed everything. Control run: **6 errors** with the waiver removed, **3**
with it.

EF Core migration scaffolds (`Migrations/<timestamp>_Name.cs`) are exempt from
the **Style** category only — `CA*`/`S*`/`RCS*` still run there, so raw SQL
hand-written into an `Up()` is still analysed. `samples/dotnet/Migrations/`
proves it.

```bash
pip install -r samples/python/requirements-dev.txt
ruff check --output-format=concise samples/python
mypy --config-file configs/python/mypy.ini samples/python/src
```

Expect **14 Ruff errors** and **5 mypy errors**, both non-zero exit. The Ruff
fixture plants at least one finding per selected family — CI asserts family
coverage separately from the total, because a total alone would still read as 14
if half the ruleset were switched off and something else fired twice:

| Family | Planted | Family | Planted |
|---|---|---|---|
| `E` | line over 100 | `N` | `GetUser` not lowercase |
| `W` | invalid escape `\d` | `SIM` | if/else that is a ternary |
| `F` | unused import | `ASYNC` | blocking `open()` in `async def` |
| `I` | unsorted import block | `S` | hardcoded password |
| `B` | mutable default arg | `T20` | stray `print()` |
| `C4` | unnecessary generator | `RUF` | un-stored `create_task` |
| `UP` | deprecated `typing.List` | | |

The mypy five are split into their own fixture on purpose: ruff and mypy find
disjoint bugs, and a shared file would let one tool's config break while the
other's findings kept the total looking plausible.

### The other direction

```bash
npm run verify:ts:clean
cd samples/dotnet-clean && dotnet build
ruff check samples/python-clean
mypy --config-file configs/python/mypy.ini samples/python-clean/src
```

All must **pass** — zero findings, zero warnings. `samples/typescript-clean`,
`samples/dotnet-clean` and `samples/python-clean` are the correct counterparts
of every planted bug: the floating promise awaited, the `any` boundary replaced
with `unknown` plus a type guard, `ToLower()` replaced with an ordinal
comparison, the `StreamReader` wrapped in a `using`, the bare `create_task`
replaced with a `gather` that holds its references.

The baseline is strict but adoptable, and that is now a test rather than a
promise — a config that flags everything is as useless as one that flags
nothing. If a clean fixture ever starts failing, the config became over-strict;
fix the config, never silence the fixture.

### Layer 2

```bash
./scripts/scan.sh
```

Expect exit `1` with **32 Semgrep findings across all 19 rule ids**, and Gitleaks
plus OSV-Scanner clean.

`samples/semgrep/` sits deliberately **outside** the `samples/typescript` and
`samples/dotnet` projects, so adding Semgrep bait can never shift the Layer 1
samples' expected finding counts. Those files are never compiled or linted —
Semgrep only parses them.

Each Semgrep sample also carries **negative controls** that must stay silent, so
the rules are provably not just matching on names:

| Negative control | Proves |
|---|---|
| `TODO(#412):` / `TODO(#918):` | `todo-without-issue` accepts a tracked TODO |
| `createUser()` calling `authz.require(...)` | `mutation-requires-authz-*` sees the gate |
| `readUser()` | reads are not treated as mutations |
| `decimal NetTotal` | `no-float-for-money` accepts the correct type |
| `tokenEndpoint = 'https://…'` | `hardcoded-secret-*` exempts a bare endpoint URL |
| `UNASSIGNED_TOKEN = 'none'` | …and exempts a short sentinel |
| `db.query('… WHERE id = ?', [id])` | `sql-string-concat-ts` accepts a parameterised query |
| `createHash('sha256')`, `createCipheriv('aes-256-gcm', …)` | `weak-crypto` accepts modern algorithms |

The secret rule's exemptions are themselves gated: `connectionString =
'postgres://admin:…@db.internal/prod'` **must** fire in both languages, proving
the URL exemption is credential-aware rather than a blanket hole. That pair —
one exemption, one must-fire counterexample — is what makes the guard safe.

**On the planted secrets:** `samples/semgrep/` contains fake credentials as bait,
which Gitleaks flags on sight. `.gitleaks.toml` allowlists that one path.
Verified honestly — same committed history, default rules vs the allowlist:

```
default rules, no allowlist  → WRN leaks found: 2
with .gitleaks.toml          → INF no leaks found
```

Note Gitleaks auto-loads `.gitleaks.toml` from the repo root, so a "control" run
without `--config` is *not* a control. Keep that allowlist path-scoped to
fixtures — a suppression is how a real leak gets committed.

### Coverage and SBOM

`samples/coverage/` and `samples/sbom/` are fixtures with hand-checked numbers,
so a parser regression shows up as a wrong number rather than as a plausible one:

```bash
python3 scripts/coverage.py --report samples/coverage/lcov.info --floor-file /tmp/f.json
```

| Fixture | Expected | Proves |
|---|---|---|
| `lcov.info` | 65.00% (13/20) | `LF:`/`LH:` summary path |
| `cobertura.xml` | 75.00% (30/40) | root attributes are trusted over `<line>` counting — the file lists one filename under **two** `<class>` entries, exactly as coverlet emits for a two-type file |
| `lcov-no-summary.info` | 40.00% (2/5) | `DA:`-only fallback |
| `cobertura-no-summary.xml` | 66.67% (4/6) | `<line>`-counting fallback |
| both of the first two | 71.67% (43/60) | multiple reports are summed, not averaged |
| `sbom/cyclonedx.json` | MIT 2, Apache-2.0 1, `MIT OR Apache-2.0` 1, UNKNOWN 2 | all three CycloneDX licence spellings — `license.id`, `license.name`, `expression` — plus components with none |

The SBOM fixture matters because osv-scanner emits `"licenses": []` — key present,
array empty — unless the bare `--licenses` flag is passed. Without it the report
renders a tidy table of *N* UNKNOWNs and looks entirely fine.

---

## Requirements

Node 24 / npm 11 and .NET SDK 10 were used to verify. Anything reasonably recent
should work; the TypeScript peer range above is the one real constraint.

Layer 2 tools are optional locally — `scan.sh` falls back to `uvx` (Semgrep) or
`docker` (all three) and warns loudly if it cannot run one. To install them
natively:

```bash
brew install semgrep gitleaks osv-scanner
```

`scan.sh` targets **bash 3.2**, the version macOS actually ships, so it runs from
`/bin/bash` with no Homebrew bash required.

## Conventions

Every commit is authored as `maximalcode`; the ruleset is capped at 12
conventions; `samples/` is the test suite and a sample that stops failing means
the config regressed. Those rules, plus the v1 scope boundary, are in
[`CLAUDE.md`](CLAUDE.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

Development history and the issue tracker live in a separate private repo. This
is the published baseline, not a published audit of anyone's code.
