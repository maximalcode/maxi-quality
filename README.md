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
| Semgrep ruleset (Layer 2) | ✅ `semgrep/` — 12 conventions, TypeScript + C# + Python |
| `scan.sh` (Semgrep + Gitleaks + OSV) | ✅ `scripts/scan.sh` |
| Reusable CI workflow, `@v1` tag | ✅ `.github/workflows/quality.yml` + `actions/layer2/` |
| Java | ⬜ deliberately not built until a real project needs it |
| SonarQube CE dashboard | ❌ **dropped.** Measured in [`EVAL-vs-sonarqube.md`](docs/EVAL-vs-sonarqube.md) and lost: 1 of 8 planted TS bugs out of the box, no rule id for `no-floating-promises` or the `no-unsafe-*` family, custom C#/TS rules unavailable in every edition. The C# value is already banked in-build via `SonarAnalyzer.CSharp`. |
| The rest of the free field | 🔍 **measured; one adopted of ten.** [`EVAL-vs-oss-tools.md`](docs/EVAL-vs-oss-tools.md) scores SonarJS, Unicorn, `eslint-plugin-security`, Semgrep's registry packs, Bandit, Trivy, Grype, TruffleHog and CodeQL against the 103 planted findings in `samples/`. Only `eslint-plugin-sonarjs` cleared every bar and it is now in the TypeScript config — zero findings on the clean fixtures, five bug classes the baseline had no rule for. The rule that decides most of the rest: a tool that is free only *because* a repo is public can gate this repo and never a consumer. |

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

`--ref <tag>` pins the workflow to an immutable tag instead of the moving `v1` —
see [Releases](https://github.com/maximalcode/maxi-quality/releases) for the
current one. Deliberately not a version number here: this line has named a
superseded tag twice, and once named `v1.0.3`, which never existed at all. A doc
that hard-codes a version goes stale on the next release by construction, and a
`--ref` a reader copies verbatim is the one place that costs them something.
`--no-workflow` skips the CI scaffold.

CI proves this end-to-end in both directions: a repo adopted by the script
builds the clean fixture at 0 errors/0 warnings **and** rejects the bad fixture
with exactly the same 23 errors as the hand-configured sample. An adoption that
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
npm i -D eslint @eslint/js typescript-eslint typescript @types/node eslint-plugin-sonarjs
```

`eslint-plugin-sonarjs` is the newest of these and the one worth a sentence.
It is **LGPL-3.0-only** — fine as a dev dependency, since a linter is not linked
into what you ship, but check it against your own policy rather than mine. It
also declares `typescript: ">=5 <6.1.0"` as a hard **dependency** rather than a
peer, so it will conflict the day you move to TypeScript 6.1.

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
with a `_` escape hatch, and `ban-ts-comment` requiring a written reason —
and SonarJS's `recommended` set on top, for five bug classes typescript-eslint
has no rule for at all: both `if`/`else` branches identical, two functions with
identical bodies, a collection read but never filled, a
catastrophic-backtracking regex, and `eval` on a non-literal.

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

**Three things to know:**
- Analyzer versions are pinned, not floating. With `TreatWarningsAsErrors`, an
  analyzer upgrade that adds rules is a breaking change — bump it deliberately.
- If the repo already has a `Directory.Build.props`, merge the properties in
  rather than overwriting, or `<Import Project="..."/>` this one at the top.
- **Without a `packages.lock.json`, the Layer 2 dependency scan sees only your
  direct dependencies.** This is the one adopt-time decision the baseline
  deliberately leaves to you, so it is spelled out below rather than buried.

#### `packages.lock.json` — the .NET dependency-scanning trade-off

A `.csproj` pinned to three known-vulnerable NuGet packages, scanned twice
(measured 2026-08-02, OSV-Scanner 2.4.0 — [`docs/EVAL-vs-oss-tools.md`](docs/EVAL-vs-oss-tools.md) §2f):

| NuGet manifest | Findings |
|---|--:|
| `PackageReference` only, **no lock file** | 4 |
| the same project with `packages.lock.json` | **7** |

Without a lock file, OSV-Scanner reads the `.csproj`/`Directory.Build.props`
and resolves **direct dependencies only**. With one, it resolves the full
transitive graph. All three findings it gains are transitive — and transitive
is where dependency vulnerabilities usually live.

```bash
dotnet restore --use-lock-file   # then commit packages.lock.json
```

**`adopt.sh` will not do this for you, on purpose.** A lock file is a
commitment, not a setting: it has to be regenerated on every dependency change,
and `RestoreLockedMode` in `Directory.Build.props` — conditional on the file
existing, so a repo that never opted in is never broken — turns a stale one into
a hard CI build failure. That is a policy for the consuming repo to accept, the
same call the [licence gate](#sbom-and-licence-compliance) makes for the same
reason.

What is *not* left to you is knowing about it. The default posture is not "no
lock file yet"; it is a dependency gate that cannot see past your direct
dependencies, and until now that difference was invisible.

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

**Detection fails loud rather than skipping.** A `package.json` with no
`package-lock.json` or `pnpm-lock.yaml` at or above it stops the run, and so
does a `.csproj` that no solution in the tree references. Both used to detect as
"no such language here" and skip in silence, leaving a green gate over code
nothing had opened. Pass `languages:` without the one you mean to exclude if the
skip is deliberate.

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
3. **OSV-Scanner** — known-vulnerable dependencies via lockfiles. On .NET,
   "lockfiles" is load-bearing: without a `packages.lock.json` it resolves
   direct dependencies only — see
   [the .NET trade-off](#packageslockjson--the-net-dependency-scanning-trade-off).

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

**One-time setup: record a floor.** Run it once with `raise: 'true'` and commit
the `.maxi-quality/coverage.json` it writes. Until that file exists the step
**fails** — a ratchet with nothing to compare against reports ok at any coverage
at all, and that is what the snippet above silently did before, because `raise`
defaults to false and nothing else ever wrote the file.

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

Four failure modes are treated as errors rather than passes, because each one
turns the ratchet into a permanently green step: a report with **zero measurable
lines** (a broken coverage run, not 100%), a **missing report file**, an
**unparseable floor** (never silently restarted from today's number), and **no
floor at all**. The `floor` output reads `none` in that last case rather than
echoing back the measured number, so a run that compared against nothing cannot
be mistaken for one that met its floor exactly.

---

## The ruleset — 12 conventions, 28 rule ids

Semgrep patterns are language-specific, so a convention whose C#, TypeScript and
Python syntax differ needs one rule id per language with an identical message.
That is why 12 conventions produce 28 ids. **The cap is on conventions, and it
is 12, hard** — new ones get added when a real bug slips through, never
speculatively.

The **Py** column is not a Semgrep column. Ruff already covers half of these
conventions outright, and a Semgrep rule for something Layer 1 already catches
is a second finding on one line, not more coverage — so where Ruff has it, the
cell names the Ruff rule and there is no Semgrep id.

| Convention | Rule id(s) | TS | C# | Py |
|---|---|:--:|:--:|:--|
| **general** | | | | |
| TODO without a tracked issue | `todo-without-issue` | ✅ | ✅ | ✅ |
| Empty catch block | `catch-and-swallow-{ts,dotnet}` | ✅ | ✅ | ruff `SIM105` |
| Printf-debugging left behind | `debug-print-left-behind-{ts,dotnet}` | ✅ | ✅ | ruff `T201` |
| Blocking on a Task | `sync-over-async` | — | ✅ | ruff `ASYNC251` |
| **security** | | | | |
| SQL built by concat/interpolation | `sql-string-concat-{ts,dotnet}`, `sql-string-concat-builder-{ts,dotnet}` | ✅ | ✅ | ruff `S608` |
| Shell command from interpolation | `command-injection-{ts,dotnet}`, `command-injection-indirect-{ts,dotnet}` | ✅ | ✅ | ruff `S602` |
| MD5/SHA1/DES/RC4, any case, all DES variants | `weak-crypto` | ✅ | ✅ | ruff `S324` |
| Secret-named var assigned a literal | `hardcoded-secret-{ts,dotnet,python}` | ✅ | ✅ | ✅ |
| **conventions** (mine) | | | | |
| Ambient clock instead of injected | `no-ambient-clock`, `no-ambient-clock-python` | ✅ | ✅ | ✅ |
| Mutation without an authz gate | `mutation-requires-authz-{ts,dotnet,python}` | ✅ | ✅ | ✅ |
| 403 for an invisible resource | `no-permission-denied-for-invisible-resource-{ts,dotnet,python}` | ✅ | ✅ | ✅ |
| double/float for money | `no-float-for-money`, `no-float-for-money-python` | — | ✅ | ✅ |

`no-ambient-clock` and `weak-crypto` are single rule ids covering TypeScript and
C# together — that is the concept §10 criterion (*the same rule fires in a TS
and a C# sample*) and it is asserted by the samples below. Python does not join
them in one id: every pattern in a rule must parse in every language it
declares, and `DateTime.UtcNow` is not Python.

**`hardcoded-secret-python` is the one Python rule that overlaps Ruff on
purpose.** S105 covers most of the convention, with one measured hole —
`CONNECTION_STRING = "postgres://admin:pw@host"` — which is exactly the shape
the TS and C# value guard was built to keep firing. It carries a **fourth** value
guard the other two do not: measured over 4,133 files of Django, Celery,
SQLAlchemy, Flask and httpx, prose in a secret-named constant was the largest
false-positive class the first three guards left, and a credential does not
contain a space.

Layer 2's Python coverage arrived late (issue #21) — Python shipped as a full
Layer 1 language while `semgrep --config semgrep` on a Python tree reported
`Ran 19 rules on 0 files`. Nothing but a `paths.include` list was excluding it.

**A ✅ means every shape the rule advertises, and that is now measured.** These
rules match raw source text in places, so quote style is not interchangeable:
`sql-string-concat-ts` and `command-injection-ts` each cover backtick,
double-quoted and single-quoted forms, `sql-string-concat-ts` covers Prisma's
`$queryRawUnsafe` and `$executeRawUnsafe` alongside `.query` / `.execute` /
`.raw`, and `sql-string-concat-dotnet` covers Dapper's four entry points and
`CommandText` as well as `new SqlCommand`. Each of those branches has its own
fixture, so one going quiet shows up as a named missing finding rather than as a
total that still looks about right.

**Two conventions carry a second rule id for the same bug one step away from the
sink** (issue #20). The sink-anchored rules require the concatenation to sit
syntactically inside the query or exec call, so binding it to a local variable
one line up silenced all of them. The two halves close it differently, and the
difference is the point:

- **SQL** drops the sink and matches the *string* — a literal carrying a SQL
  keyword, concatenated or interpolated, wherever it is built. That reaches a
  helper function as well as a local.
- **Commands** cannot do that: `"ls -la " + dir` and `"Hello " + name` are the
  same shape, so a sink-free command rule is a rule against string concatenation
  and gets switched off. It uses Semgrep's taint mode instead, keeping the sink.

Which leaves one measured gap, stated rather than papered over: **Semgrep OSS
taint is intraprocedural.** It crosses a local variable and not a function call,
so `exec(buildCommand(dir))` is still silent. Interprocedural taint is a Semgrep
Pro feature, and the one free tool in the eval that reached it —
CodeQL — cannot run against a private repo at all
([`EVAL-vs-oss-tools.md`](docs/EVAL-vs-oss-tools.md) §0). The gap has a fixture
of its own in `samples/semgrep/`, kept silent on purpose, so the day something
free does reach it the manifest is where that shows up.

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

Expect **14 errors** and a non-zero exit. Nine from `bad.ts` — floating promise,
explicit `any`, unsafe assignment, unsafe return, unsafe member access, `==`,
unused variable, dead store, non-null assertion — and five from `sonarjs.ts`,
which baits the classes SonarJS adds and typescript-eslint has no rule for:

| Planted bug | Rule |
|---|---|
| both `if`/`else` branches identical | `sonarjs/no-all-duplicated-branches` |
| two functions with identical bodies | `sonarjs/no-identical-functions` |
| a collection read but never filled | `sonarjs/no-empty-collection` |
| catastrophic-backtracking regex (ReDoS) | `sonarjs/slow-regex` |
| `eval` on a non-literal | `sonarjs/code-eval` |

SonarJS scored **1 of 8** against `bad.ts` when it was evaluated, which on our
own fixtures makes it look worthless — our fixtures bait our rules, so that
scoreboard under-counts by construction. The table above is the reverse probe,
and it is what earned the plugin its place (`docs/EVAL-vs-oss-tools.md` §2b).

That is ESLint. The **compiler** is a separate gate with a separate fixture:

```bash
npm run verify:ts:types
node scripts/snapshot-tsconfig.mjs --check
```

Expect **12 diagnostics** and a non-zero exit from the first, and a clean
22-option snapshot from the second. `tsconfig.strict.json` ships to every
consumer and until issue #7 `tsc` was run by **nothing** — 13 of its 14
hand-written flags could each have been deleted with every job still green.

`samples/typescript-strict/` closes that the way `samples/typescript` closes it
for ESLint: one file per flag, named after the flag, pinned by rule/file/line in
`samples/expected/tsc.json`. Each mapping was checked by **ablation** — turning
that one flag off and confirming that specific error is the one that disappears.
Worth the trouble: `noImplicitReturns` was first baited with a fixture that
actually failed on `strictNullChecks`, so deleting the flag would have left CI
red and looking fine.

Four flags no fixture can reach — `isolatedModules`, `esModuleInterop`,
`forceConsistentCasingInFileNames` and the emit trio — are covered by
`configs/typescript/tsconfig.snapshot.json`, which asserts what `tsc --showConfig`
resolves rather than what the JSON file says. The reasoning, and the measured
reason each one is unbaitable, is in
[`samples/typescript-strict/README.md`](samples/typescript-strict/README.md).

```bash
cd samples/dotnet && dotnet build
```

Expect **23 errors, 0 warnings** and a non-zero exit, covering all nine planted
classes:

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

The last four rows are new in #8, and the third of them is the one worth
reading. The three `dotnet_naming_rule` blocks shipped enforcing **nothing** —
not for want of a fixture, but because `dotnet_diagnostic.IDE1006.severity` was
never set, so the build never reported them. Two of the three were masked by
analyzers that happen to overlap; the private-field convention was caught by no
layer at all. Measured, then fixed with one line.

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

Expect **14 Ruff errors** and **11 mypy errors**, both non-zero exit. The Ruff
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

The mypy half is split across two files, and the split is the point. `strict =
True` is an **alias**, not a setting: one line in `mypy.ini` that expands to
fourteen booleans. Every finding in `bad_types.py` comes from base type checking
or from `warn_unreachable`, which the config sets explicitly — so `strict` could
be downgraded to a hand-picked list and the fixture would stay green.
`bad_strict.py` baits the expansion itself:

| Sub-flag of `strict` | Planted | Code |
|---|---|---|
| `warn_return_any` | `Any` laundered into a declared `int` | `no-any-return` |
| `disallow_any_generics` | a bare `list` annotation | `type-arg` |
| `strict_equality` | `str == int`, a comparison that cannot succeed | `comparison-overlap` |
| `disallow_untyped_calls` | typed code calling an unannotated helper | `no-untyped-call` |

`configs/python/settings.snapshot.json` proves the alias **expands**;
`bad_strict.py` proves the expansion **does something**. Same division of labour
as `tsconfig.snapshot.json` and `samples/typescript-strict/`.

The mypy five are split into their own fixture on purpose: ruff and mypy find
disjoint bugs, and a shared file would let one tool's config break while the
other's findings kept the total looking plausible.

### The other direction

```bash
npm run verify:ts:clean
npm run verify:ts:types:clean
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

Expect exit `1` with **100 Semgrep findings across all 28 rule ids**, and Gitleaks
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
| `Require` / `Authorize` / `RequireAsync` / `AuthorizeAsync` | all four `mutation-requires-authz-dotnet` gates are seen |
| `require` / `authorize`, awaited or not | …and both on the TypeScript side |
| `readUser()` | reads are not treated as mutations |
| `decimal NetTotal` | `no-float-for-money` accepts the correct type |
| `tokenEndpoint = 'https://…'` | `hardcoded-secret-*` exempts a bare endpoint URL |
| `UNASSIGNED_TOKEN = 'none'` | …and exempts a short sentinel |
| `db.query('… WHERE id = ?', [id])` | `sql-string-concat-ts` accepts a parameterised query |
| ``prisma.$queryRaw`…` `` | …and the tagged-template form Prisma parameterises for you |
| `conn.Query("… = @id", new { id })` | `sql-string-concat-dotnet` accepts Dapper's parameters |
| `return NotFound()` | `no-permission-denied-*` accepts the fix its message asks for |
| `catch { /* why */ }` | `catch-and-swallow-*` accepts a documented silence |
| `catch (T e) when (…) { /* why */ }` | …including on an exception filter, which it did not until 2026-08-02 |
| `createHash('sha256')`, `createCipheriv('aes-256-gcm', …)` | `weak-crypto` accepts modern algorithms |

Every exemption above has bait behind it as well as a control. That pairing is
the point: an exemption with no counterexample is a hole nobody can see, and an
exemption with no *positive* fixture can stop matching without anything going
red. Both directions are in `samples/expected/semgrep.json`, per rule and line.

The secret rule's exemptions are themselves gated: `connectionString =
'postgres://admin:…@db.internal/prod'` **must** fire in all three languages,
proving the URL exemption is credential-aware rather than a blanket hole. That
pair — one exemption, one must-fire counterexample — is what makes the guard
safe. On the Python side it is also the one shape Ruff's `S105` misses, which is
why that rule exists next to a Layer 1 that already covers most of it.

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

## How this repo is developed

Two long-lived branches, and the split exists for one reason: **`main` is what
consumers are running.** The moving `v1` tag follows `main`, so a merge there is
not a checkpoint — it is a release to everyone who pinned `@v1`.

```
  feature branch ──PR──▶ develop ──PR──▶ main ──▶ v1 moves
     your work            default        release      consumers
                          branch         decision     pick it up
```

| Branch | What it is |
|---|---|
| `develop` | **The default branch, and where every PR goes.** Full CI, protected, no direct pushes. Merged work sits here until it is released. |
| `main` | **The release branch.** A green push to it moves `v1`, automatically, via [`release-tag.yml`](.github/workflows/release-tag.yml). Same protection, same 18 required checks. |

**Contributing, concretely:**

1. Branch off `develop`.
2. Open a PR **against `develop`** — it is the default base, so `gh pr create`
   and the web UI already point there.
3. All 18 CI jobs must pass. They are required checks and admins are not exempt;
   the branch must also be up to date before it merges.
4. Releasing is a separate, deliberate PR from `develop` to `main`. That is not
   a contributor step — it is where the maintainer decides a version.

**On tags.** `v1` moves on its own after a green `ci` run on `main`, because a
moving tag that someone has to remember to move goes stale and everyone assumes
it did not. The immutable `v1.0.x` tags are the opposite: cut by hand, one per
release worth naming, and never rewritten. Pin `@v1` to follow fixes, pin a
`v1.0.x` when you need a ref that cannot change under you.

Nothing here triggers off `develop`. `release-tag.yml` filters on `main` and
additionally refuses to run for anything but a `push` event from this
repository — a fork's branch called `main` matches a branch filter, which is why
the filter is not the gate.

---

## Conventions

Every commit is authored as `maximalcode`; the ruleset is capped at 12
conventions; `samples/` is the test suite and a sample that stops failing means
the config regressed. Those rules, plus the v1 scope boundary, are in
[`CLAUDE.md`](CLAUDE.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

Development history and the issue tracker live in a separate private repo. This
is the published baseline, not a published audit of anyone's code.
