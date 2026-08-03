# EVAL — this baseline vs. the mature open-source field

> **Date:** 2026-08-02 · **Verdict:** adopt **one** ESLint plugin, conditionally;
> fix **two** of our own rules that this evaluation found broken; adopt nothing
> else.
> **Analysis only** — nothing in `configs/`, `semgrep/`, `scripts/` or
> `samples/` was changed to produce this document. Every probe file lives
> outside the repo.
>
> Companion to [`EVAL-vs-sonarqube.md`](EVAL-vs-sonarqube.md), which asked
> whether a Sonar **server** should replace this baseline. This one asks the
> broader question: of everything free and mature in the field, what is worth
> adding?

---

## 0. The asymmetry that decides most of this

**This repo is public. Every repo that consumes it is private.**

That cuts one way and one way only. A tool that is free *because* a repo is
public can gate **this** repo and can never gate a single consumer — and this
repo is a baseline that private repos consume, so a gate that runs here and
nowhere else protects nothing that matters. For every candidate the first
question is therefore not "is it good?" but:

> **Does it work for a private consumer, on a free tier, yes or no?**

| Candidate | Free for a **private** consumer? | Licence |
|---|:--:|---|
| `eslint-plugin-sonarjs` | **yes** — an npm package, nothing else | LGPL-3.0-only |
| `eslint-plugin-unicorn` | **yes** | MIT |
| `eslint-plugin-security` | **yes** | Apache-2.0 |
| Semgrep OSS + registry packs | **yes** — packs fetch anonymously | LGPL-2.1 (CLI) |
| Bandit | **yes** | Apache-2.0 |
| OSV-Scanner / Trivy / Grype | **yes** | Apache-2.0 |
| Gitleaks | **yes** | MIT |
| TruffleHog | **yes** | AGPL-3.0 |
| **GitHub CodeQL** | **NO** | see below |
| **SonarQube Cloud, Free plan** | **partial, and not usefully** | proprietary SaaS |

**CodeQL is blocked twice over, by two independent documents.** The product:
*"If you are on a GitHub Free or GitHub Pro plan, you can only use code scanning
on repositories that are publicly available."* And the CLI, separately, forbids
using the software *"in connection with any codebase that is not an Open Source
Codebase (e.g., code in a private repo in GitHub)"* unless you hold a paid
GitHub Advanced Security licence. So neither "run it in Actions" nor "run the
CLI ourselves" is available to a private consumer. **CodeQL is at best a
self-check on this baseline, and it is scored below in exactly those words.**

**SonarQube Cloud's Free plan does cover private projects** — up to 50k LOC and
5 members — so it is not blocked outright. It is blocked in practice: **no
custom quality profiles and no custom quality gates**, *"only main branch
analysis"*, and pull-request analysis *"only if the target branch is the main
branch"*. A gate that cannot analyse a feature branch cannot fail a PR, and a
profile you cannot customise cannot enable the rules
[`EVAL-vs-sonarqube.md` §1f](EVAL-vs-sonarqube.md) showed are off by default.
Add that private source is uploaded to a third party. Measured verdict from the
earlier document stands: **1 of 8**.

Everything else on the list passes the private test and is scored on detection
alone.

---

## 1. What the baseline detects today

Built by reading `configs/` and `semgrep/`, not the README.

### 1a. Layer 1 — TypeScript (`configs/typescript/`)

`eslint.config.mjs` = `eslint:recommended` + `strictTypeChecked` +
`stylisticTypeChecked`, type-aware via `projectService`, plus four deliberate
overrides (`eqeqeq` with `null: 'ignore'`, a stricter `no-unused-vars`,
`ban-ts-comment` requiring a ≥10-char description, `no-console` as a warning).
`tsconfig.strict.json` adds the compiler half: `strict`,
`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride`,
`noImplicitReturns`, `noFallthroughCasesInSwitch`,
`noPropertyAccessFromIndexSignature`, `useUnknownInCatchVariables`,
`verbatimModuleSyntax`, `isolatedModules`.

**Bug classes:** unhandled promise rejections; `any` propagation
(assignment/return/member-access/call/argument); type-unsound narrowing;
unchecked index access; loose equality; unused code; unsound suppression.

### 1b. Layer 1 — C#/.NET (`configs/dotnet/`)

`AnalysisLevel=latest-recommended` + `EnableNETAnalyzers` +
`EnforceCodeStyleInBuild` + `TreatWarningsAsErrors` + `Nullable=enable`, plus
`SonarAnalyzer.CSharp` and `Roslynator.Analyzers` as build-time analyzers.
Test projects waive six rules, each justified by a measured finding.

**Bug classes:** null-reference (nullable reference types); the CA/IDE/S/RCS
analyzer families as build errors — culture-sensitive string ops, disposal
bugs, dead code, unused members, unreachable code.

### 1c. Layer 1 — Python (`configs/python/`)

`ruff.toml` selects thirteen families — `E W F I B C4 UP N SIM ASYNC S T20 RUF`
— at line length 100, with an empty global `ignore`. `mypy.ini` is `strict`
plus `warn_unreachable`, `explicit_package_bases`, `namespace_packages`.

**Bug classes:** undefined names and unused imports; mutable default arguments;
blocking calls inside `async def`; dangling asyncio tasks; the whole
`flake8-bandit` security family; stray `print`; and, from mypy, missing
annotations, wrong return types, argument-type mismatches, unnarrowed
`Optional`, unreachable code.

### 1d. Layer 2 — the 12 conventions, 19 rule ids

| # | Convention | Rule ids | Languages | Severity |
|---|---|---|---|---|
| 1 | catch-and-swallow | `-ts`, `-dotnet` | TS, C# | ERROR |
| 2 | debug-print-left-behind | `-ts`, `-dotnet` | TS, C# | WARNING |
| 3 | sync-over-async | `sync-over-async` | C# | ERROR |
| 4 | todo-without-issue | `todo-without-issue` | generic (`.ts .tsx .js .mjs .cs`) | WARNING |
| 5 | command-injection | `-ts`, `-dotnet` | TS, C# | ERROR |
| 6 | hardcoded-secret | `-ts`, `-dotnet` | TS, C# | ERROR |
| 7 | sql-string-concat | `-ts`, `-dotnet` | TS, C# | ERROR |
| 8 | weak-crypto | `weak-crypto` | TS + C# (one id) | ERROR |
| 9 | mutation-requires-authz | `-ts`, `-dotnet` | TS, C# | ERROR |
| 10 | no-ambient-clock | `no-ambient-clock` | TS + C# (one id) | ERROR |
| 11 | no-float-for-money | `no-float-for-money` | C# | ERROR |
| 12 | no-permission-denied-for-invisible-resource | `-ts`, `-dotnet` | TS, C# | ERROR |

Re-run today: **`Ran 19 rules on 15 files: 60 findings`**, matching
`samples/expected/semgrep.json` exactly.

### 1e. The corpus everything below is scored against

| Fixture | Planted findings | Re-verified today |
|---|--:|---|
| `samples/typescript/src/bad.ts` (ESLint) | 8 | 8 ✅ |
| `samples/dotnet/` (Roslyn) | 13 | 13 ✅ |
| `samples/dotnet-tests/` (Roslyn) | 3 | 3 ✅ |
| `samples/python/src/bad.py` (Ruff) | 14 | 14 ✅ |
| `samples/python/src/bad_types.py` (mypy) | 5 | 5 ✅ |
| `samples/semgrep/` TypeScript | 30 | 60 total ✅ |
| `samples/semgrep/` C# | 30 | (same run) |
| **Total** | **103** | |
| every `-clean` fixture | **0** | 0 ✅ |

### 1f. The gap the coverage map itself exposes: Python gets none of the 12

`grep "languages:"` over `semgrep/` returns `csharp` ×9, `typescript` ×7,
`[typescript, csharp]` ×2, `generic` ×1 — and the `generic` rule's
`paths.include` lists `.ts .tsx .js .mjs .cs`. So:

> **`semgrep --config semgrep samples/python samples/python-clean` →
> `Ran 19 rules on 0 files: 0 findings`.**

Python is a shipped Layer 1 language with **zero Layer 2 convention coverage**.
Measured against a probe that translates all twelve conventions into Python,
`configs/python/ruff.toml` already covers six of them by accident of the `S`,
`T20` and `SIM` families:

| Convention | Covered by our Ruff config? |
|---|---|
| debug-print-left-behind | ✅ `T201` |
| catch-and-swallow | ✅ `S110` (+`SIM105`) |
| weak-crypto | ✅ `S324` |
| sql-string-concat | ✅ `S608` |
| command-injection | ✅ `S605` |
| hardcoded-secret | ⚠️ **partial** — `S105` fired on the token, **not** on `postgres://admin:pw@host` |
| todo-without-issue | ❌ |
| sync-over-async | ❌ |
| no-ambient-clock | ❌ |
| no-float-for-money | ❌ |
| mutation-requires-authz | ❌ |
| no-permission-denied-for-invisible-resource | ❌ |

The partial row is the interesting one: the userinfo-URL shape is exactly what
the #17 value-guard work made the TS and C# rules catch, and Python has the
old hole. Per `CLAUDE.md` §4, adding a per-language id to an **existing**
convention is not new scope, so closing this does not touch the cap.

---

## 2. Scoreboards

### 2a. TypeScript ESLint plugins, on `samples/typescript/src/bad.ts`

Same shape as [`EVAL-vs-sonarqube.md` §1f](EVAL-vs-sonarqube.md). All runs
type-aware, Node globals declared, ESLint 10.8.0.

| Planted bug | baseline | sonarjs 4.2.0 (recommended, 217 on) | unicorn 72.0.0 (recommended, 306 on) | security 4.0.1 (14 on) |
|---|:--:|:--:|:--:|:--:|
| floating promise | ✅ | ❌ | ❌ | ❌ |
| explicit `any` | ✅ | ❌ | ❌ | ❌ |
| unsafe assignment from `any` | ✅ | ❌ | ❌ | ❌ |
| unsafe return of `any` | ✅ | ❌ | ❌ | ❌ |
| unsafe member access on `any` | ✅ | ❌ | ❌ | ❌ |
| `==` | ✅ | ❌ | ❌ | ❌ |
| unused variable | ✅ | ✅ (×2 rules) | ❌ | ❌ |
| non-null assertion | ✅ | ❌ | ❌ | ❌ |
| **total** | **8/8** | **1/8** | **0/8** | **0/8** |
| findings on `typescript-clean` | **0** | **0** | **0** | **0** |

Against the 30 planted Layer 2 TypeScript findings in `samples/semgrep/`:

| | sonarjs | unicorn | security |
|---|:--:|:--:|:--:|
| planted Layer 2 TS findings matched | **4/30** | **0/30** | **4/30** |
| which ones | weak-crypto ×3 (incl. the uppercase `MD5` and `des-ede3-cbc` evasions), untracked TODO ×1 | — | `detect-child-process` on 4 of our 6 command-injection lines |
| extra findings on the same file | 3 | 32 | 0 |

**On the extras.** `sonarjs/todo-tag` fired three times where our convention
fires once: on the untracked TODO (agreeing with us), on a section-header
comment whose only "TODO" is inside the string `todo-without-issue`, and on
`TODO(#412)` — the tracked TODO our convention **deliberately** exempts.
Unicorn's 32 were dominated by `name-replacements` asking for `db`→`database`,
`dir`→`directory`, `doc`→`document`, `res`→`response`; not one was a planted
defect.

**A note on being fair to SonarJS.** `recommended` turns on 217 of the plugin's
279 rules, so the `1/8` above is not the plugin's ceiling. Turning on **all
279** raises Layer 2 TS from 4/30 to **10/30** — `sonarjs/os-command` is off by
default and catches all six command-injection lines, and it is precision-
oriented rather than a blanket hotspot (probed: a literal `exec('ls -la')` does
**not** fire). But all-279 also puts **2 findings on
`samples/typescript-clean/src/clean.ts`** — `file-header` and
`arrow-function-convention`, both rules that need options nobody supplied.
Under this repo's own rule that a config flagging the clean fixture has
regressed, **all-279 is disqualified and `recommended` is the honest column.**

### 2b. What they catch that we structurally cannot

The scoreboards above are scored on *our* fixtures, which bait *our* rules — so
they under-count by construction. This probe does the reverse: seven defects
drawn from the classes SonarJS claims and typescript-eslint has no counterpart
for, plus four from Unicorn's and five from `security`'s.

| Planted defect | baseline | sonarjs | unicorn | security |
|---|:--:|:--:|:--:|:--:|
| both `if`/`else` branches identical | ❌ | ✅ `no-all-duplicated-branches` | ✅ | ❌ |
| `else if` repeats the first condition | ✅ `no-dupe-else-if` | ✅ | ❌ | ❌ |
| `x && x && y` | ✅ `no-unnecessary-condition` | ✅ | ✅ | ❌ |
| loop body always returns | ❌ | ❌ | ❌ | ❌ |
| always-true guard | ✅ `no-unnecessary-condition` | ✅ | ❌ | ❌ |
| two functions with identical bodies | ❌ | ✅ `no-identical-functions` | ❌ | ❌ |
| collection read but never filled | ❌ | ✅ `no-empty-collection` | ❌ | ❌ |
| `isNaN` instead of `Number.isNaN` | ❌ | ❌ | ✅ | ❌ |
| `removeEventListener(fn.bind(…))` | ❌ | ❌ | ✅ | ❌ |
| catastrophic-backtracking regex (ReDoS) | ❌ | ✅ `slow-regex` | ❌ | ✅ |
| `eval` on a non-literal | ❌ | ✅ `code-eval` | ❌ | ✅ |
| `fs.readFileSync` on a built path | ❌ | ❌ | ❌ | ✅ |
| **new bug classes each adds over the baseline** | — | **5** | **3** | **3** |

So SonarJS's unique contribution is real and it is five classes:
all-duplicated-branches, identical-functions, empty-collection, ReDoS, and
`eval`. That is the strongest case in this document for adopting anything.

### 2c. The cost of noise, measured on real working code

The `-clean` fixtures are 89 lines of TypeScript and 54 of Python — enough to
disqualify an over-strict config, not enough to estimate real-world noise. So
each plugin was also run over `scripts/snapshot-eslint-rules.mjs`: 151 lines of
this repo's own working JavaScript, which has no known defects. (It is not
currently linted by the baseline, so "clean" here means *by inspection*, not
*by gate* — but it is the most realistic non-fixture TypeScript-family code
this repo contains.)

| Plugin | Findings on that one real file | Defects among them |
|---|--:|--:|
| `eslint-plugin-security` | **10** — every one `detect-object-injection` | **0** |
| `eslint-plugin-unicorn` | **16** — `no-null`, `name-replacements`, `catch-error-name`, `no-array-sort`, … | **0** |

`detect-object-injection` also fired in the probe above on
`map[key]` where `map` is a `Record<string, number>` — idiomatic, type-safe
TypeScript. This is the rule's documented behaviour, not a defect in it: it
flags every computed member access. On a codebase with any table-driven code it
is a permanent 10-findings-per-file tax with a zero true-positive rate.

### 2d. Semgrep's own OSS registry packs

Run anonymously via `uvx semgrep`, against the full bad corpus (8 files) and
the clean fixtures.

| Pack | Rules in pack | Rules actually run | Planted findings caught | On `-clean` |
|---|--:|--:|:--:|:--:|
| `p/security-audit` | 225 | 99 | **0 of 103** | 0 |
| `p/owasp-top-ten` | 560 | 250 | **3 of 103** | 0 |
| `p/csharp` | — | 27 | 3 of 30 C# | — |

The three `p/owasp-top-ten` findings are all `csharp-sqli`, on `Bad.cs` lines
62, 69 and 99. It misses the four Dapper entry points our
`sql-string-concat-dotnet` catches (`Query`, `QueryAsync`, `Execute`,
`ExecuteAsync`), and it correctly stays silent on the parameterised negative
control.

**One correction to the record.** `CLAUDE.md` §2 says the free registry "ships
no C# rules". That is true of `p/security-audit` specifically — scanning a
directory containing three C# files, its language table shows `ts` and
`<multilang>` rows and **no `csharp` row at all** — but it is not true of the
registry as a whole: `p/owasp-top-ten` runs 27 C# rules and `p/csharp` is a
27-rule C# pack. The claim should be narrowed to the pack it was measured on.

**And one finding against our own ruleset**, which is the most useful thing in
this section. On an ASP.NET Core probe where the SQL string is assembled in a
private helper and passed to `ExecuteReader`, `csharp-sqli` fires and
**`sql-string-concat-dotnet` does not** — our rule requires the concatenation to
appear syntactically inside `new SqlCommand(...)`, a Dapper call, or a
`CommandText` assignment. The same is true of `sql-string-concat-ts` and
`command-injection-ts` on the equivalent Express probe. Control: inline the
concatenation at the sink in the same file and our rules fire, 2 of 2. This is
a real false-negative class, not a fixture artefact.

### 2e. Bandit vs. the Ruff `S` family we already run

| Corpus | Bandit 1.9.4 | Ruff 0.16.1 with `configs/python/ruff.toml` |
|---|--:|--:|
| `samples/python/src/` (19 planted) | 1 (`B105`) | 14 + 5 mypy |
| 8-defect Bandit-class probe | 11 | **9** |
| `samples/python-clean/` | 0 | 0 |

Bandit's one finding on our fixtures is `B105` on `bad.py:21` — the same line,
the same defect, as Ruff's `S105`. On the probe built specifically from Bandit's
own check classes, Ruff matched every actual defect at an identical id
(`S602 S506 S301 S113 S501 S324 S306 S307 S104`). Bandit's two extra findings
were `B403`/`B404` — *"consider possible security implications associated with
importing pickle/subprocess"* — which fire on the import statement, not on a
defect.

**Bandit found 0 defects that our existing Python config does not already
find.**

### 2f. Dependency scanning: OSV-Scanner vs. Trivy vs. Grype

Fixture: an npm lockfile and a `requirements.txt` pinned to eight
long-since-fixed vulnerable versions. Advisory ids normalised across
GHSA/PYSEC/CVE via the tools' own alias data, then compared as
(package × advisory) pairs.

| | OSV-Scanner 2.4.0 | Trivy 0.72.0 | Grype 0.116.1 |
|---|--:|--:|--:|
| pairs found | 67 | **68** | 67 |
| pairs missed vs. the union | 1 | 0 | 1 |
| packages identified | 8/8 | 8/8 | 8/8 |
| this repo's real tree | clean | clean | clean |

Trivy's single extra is `NSWG-ECO-516` on `lodash@4.17.15`, from the Node.js
Ecosystem Security Working Group feed — an advisory with no CVE, for a package
that all three already flag under seven other ids. **On 68 findings the three
tools agree 67 times.**

Where they do not agree is .NET, and it matters here:

| NuGet manifest | OSV-Scanner | Trivy | Grype |
|---|--:|--:|--:|
| `.csproj` with `PackageReference`, **no lock file** | **4** | 0 | 0 |
| the same project with `packages.lock.json` | 7 | 7 | 7 |

Trivy and Grype scanned no target at all in the first row. This baseline ships
.NET dependencies as `PackageReference` in `Directory.Build.props`/`.csproj`
and `RestoreLockedMode` is conditional on a lock file already existing — so the
first row is the shape a consumer actually has today. It also shows a real
coverage limit of our own setup: **without `packages.lock.json`, OSV sees only
direct dependencies (4), and a lock file raises that to the full transitive
graph (7).**

### 2g. Secret scanning: Gitleaks vs. TruffleHog

Corpus: the four planted credential literals in `samples/semgrep/`, scanned
with default rules (the repo's `.gitleaks.toml` allowlist bypassed, so the
detectors compete on equal terms). TruffleHog was run `--no-verification`.

| Planted literal | Gitleaks 8.30.1 | TruffleHog 3.96.0 | our Semgrep rules |
|---|:--:|:--:|:--:|
| `sk_live_…` in `bad.ts:20` | ✅ `stripe-access-token` | ✅ `Stripe` | ✅ |
| `ghp_…` in `Bad.cs:34` | ✅ `generic-api-key` | ❌ | ✅ |
| `postgres://admin:pw@…` in `bad.ts:23` | ❌ | ✅ `Postgres` | ✅ |
| `postgres://admin:pw@…` in `Bad.cs:36` | ❌ | ✅ `Postgres` | ✅ |
| **total** | **2/4** | **3/4** | **4/4** |
| findings on `-clean` fixtures | 0 | 0 | 0 |
| false positives, whole-repo history scan | **0** | **1** | 0 |

The history row used Gitleaks with this repo's `.gitleaks.toml`, whose allowlist
covers `samples/semgrep/` only. That does not flatter it: TruffleHog's one false
positive is outside that path, and Gitleaks did not flag it either.

That confirms the division of labour `semgrep/security/hardcoded-secret.yaml`
already documents: the shape-matching scanners catch known token formats, our
name+value rules catch the homegrown ones — and here they catch all four.

TruffleHog's one false positive is worth naming precisely: scanning the full
history it flagged `semgrep/security/hardcoded-secret.yaml` as containing a
Postgres credential, because the file's own comment documents the pattern
`postgres://user:pass@host`. It also reported `verified_secrets: 0` — by
default TruffleHog outputs **only verified** results, and verification means
sending the candidate credential to the provider's API. For a private
consumer's CI that is credential-shaped material leaving the build, which is a
deliberate decision rather than a default to inherit.

### 2h. CodeQL 2.26.2 — measured, and it changes nothing

Scored anyway, because §0 disqualifies it for consumers but not for this repo.
Suites: `security-extended` and `security-and-quality`, run from the official
bundle.

| Database | Queries | Findings | Of our planted findings |
|---|--:|--:|:--:|
| TypeScript, bad fixtures | 103 / 201 | 0 / 4 | **1 of 8** Layer 1, **0 of 30** Layer 2 |
| TypeScript, `-clean` | 103 / 201 | 0 / 0 | — |
| Python, bad fixtures | 50 / 172 | 1 / 3 | **2 of 19** |
| Python, `-clean` | 50 / 172 | 0 / 0 | — |
| C#, `samples/semgrep/` (`--build-mode=none`) | 63 / 164 | 0 / 8 | **4 of 30** |
| C#, `samples/dotnet-clean/` (real build) | 63 / 164 | 0 / 0 | — |

CodeQL contributed exactly one finding nothing else in the baseline produces:
`py/clear-text-logging-sensitive-data` on `bad.py:37`, where the fixture prints
the hardcoded password. It also flagged `cs/catch-of-all-exceptions` on
`Bad.cs:170` — the documented negative control our `catch-and-swallow` rule is
built to stay silent on.

The C# row carries a caveat: `samples/semgrep/*.cs` are parse-only fixtures by
design and were extracted with `--build-mode=none`, which is CodeQL's reduced-
accuracy mode. Treat 4 of 30 as a floor.

**Where CodeQL is genuinely in a different class**, and the reason this section
exists at all:

| Probe: tainted HTTP input → helper function → sink | CodeQL | our Semgrep rules | `p/owasp-top-ten` |
|---|:--:|:--:|:--:|
| Express `req.query` → `buildQuery()` → `db.query` | ✅ `js/sql-injection` | ❌ | ❌ |
| Express `req.query` → `archiveCommand()` → `exec` | ✅ `js/command-line-injection` | ❌ | ❌ |
| ASP.NET `[FromQuery]` → `BuildSql()` → `ExecuteReader` | ✅ `cs/sql-injection` | ❌ | ✅ |
| ASP.NET `[FromQuery]` → `BuildArgs()` → `Process.Start` | ✅ `cs/command-line-injection` | ❌ | ❌ |
| | **4/4** | **0/4** | **1/4** |

Interprocedural taint tracking is a capability a pattern matcher does not have,
and it finds the exact shape real handlers take. **And it is unavailable to
every consumer of this baseline, at any free tier, by two separate licences.**
That is the honest summary: the biggest capability gap in this baseline is one
that no free tool can close for a private repo.

---

## 3. Verdict

### 3a. Adopt: one plugin, conditionally

> **`eslint-plugin-sonarjs@4.2.0` at `recommended`, with `sonarjs/todo-tag` and
> `sonarjs/no-unused-vars` turned off.**

**Landed 2026-08-03, exactly as written above** — see `configs/typescript/eslint.config.mjs`
and the five-class fixture in `samples/typescript/src/sonarjs.ts`. The clean
fixture still reports zero. Everything below is the measurement as taken; it is
not rewritten to match the outcome.

It is the only candidate that clears every bar: it works for a private consumer
(it is an npm package), it scores **0 findings on the clean fixtures**, and the
probe in §2b shows it contributes **five genuine bug classes** the baseline has
no counterpart for. It is a Layer 1 analyzer plugin, so it does not touch the
12-convention cap — the C# side already banks Sonar's engine the same way
through `SonarAnalyzer.CSharp`.

The two conditions are both measured, not precautionary:

- **`sonarjs/todo-tag` off.** It fires on `TODO(#412)`, which convention 4
  deliberately exempts. Two layers disagreeing about one line is worse than
  either verdict alone — the same reasoning already written into
  `debug-print-left-behind-ts`.
- **`sonarjs/no-unused-vars` off.** On `bad.ts:48` the combined config reports
  the one unused variable three times (`@typescript-eslint/no-unused-vars`,
  `sonarjs/no-unused-vars`, `sonarjs/no-dead-store`). Keep `no-dead-store` —
  a dead store is not the same defect — and drop the exact duplicate.

Two costs to record: the package is 12 MB with 13 runtime dependencies, and it
declares **`typescript: ">=5 <6.1.0"` as a hard `dependency`, not a peer**. That
is compatible with this repo's `~6.0.3` today and will conflict the day a
consumer moves to TypeScript 6.1.

### 3b. Fix, in our own rules

Two false-negative classes this evaluation found, both inside existing
conventions and therefore not new scope:

1. **SQL and command strings assembled one function away from the sink are
   invisible to us** (§2d). `csharp-sqli` from a free registry pack catches the
   C# case we miss.
2. **Python has no Layer 2 convention coverage at all** (§1f) — six of the
   twelve have no Python equivalent from any tool we run, and `hardcoded-secret`
   has the userinfo-URL hole in Python that was already closed for TS and C#.

### 3c. Do not adopt — the honest negatives, with the numbers

| Candidate | Measured | Why not |
|---|---|---|
| **`eslint-plugin-unicorn`** | 0/8, 0/30, **16 findings / 0 defects** on real working JS | 341 rules for 3 bug classes, only 2 of which SonarJS does not also cover, and the preset's dominant output is renaming variables |
| **`eslint-plugin-security`** | 0/8, 4/30, **10 findings / 0 defects** on one real file | `detect-object-injection` flags every computed member access; SonarJS already covers its ReDoS and `eval` rules |
| **`p/security-audit`** | **0 of 103** | it found nothing, on any language, in the entire corpus |
| **`p/owasp-top-ten`** | **3 of 103** | worth keeping in mind as a source of *rule ideas* (§2d), not as a gate |
| **Bandit** | **0 defects Ruff does not already find** | `configs/python/ruff.toml` already runs the `S` family; Bandit's extras are import advisories |
| **Trivy** | 68 vs OSV's 67; **0** on a `.csproj` without a lock file | one non-CVE advisory of difference, and it cannot read the .NET manifest shape this baseline ships |
| **Grype** | 67 vs OSV's 67; **0** on a `.csproj` without a lock file | identical detection, same .NET limitation |
| **TruffleHog** | 3/4 vs Gitleaks' 2/4, **1 false positive** on our own rule file | complementary, but verification-by-default sends candidate credentials to third-party APIs from a private CI |
| **CodeQL** | 1/8 TS, 2/19 Python, 4/30 C#; **4/4** on taint probes | **cannot run on a private repo under any free tier** — a self-check on this baseline, not coverage for anything downstream |
| **SonarQube Cloud Free** | 1/8, from the earlier evaluation | no custom quality profiles, main-branch-only analysis; and private source uploaded |

Nine of the ten candidates are declined, and six of those are declined with the
most useful conclusion available: **we already cover this.**

---

## 4. What was run, and where

macOS 24.6.0, Node 24.18.1, .NET SDK 10.0.301, Docker 29.6.2. Probe files and
scratch fixtures were created **outside** the repository; the working tree was
verified clean before and after.

**Tool versions:** ESLint 10.8.0 · typescript-eslint 8.65.0 · TypeScript 6.0.3 ·
`eslint-plugin-sonarjs` 4.2.0 · `eslint-plugin-unicorn` 72.0.0 ·
`eslint-plugin-security` 4.0.1 · Semgrep 1.172.0 (OSS) · Ruff 0.16.1 ·
mypy 2.3.0 · Bandit 1.9.4 · Gitleaks 8.30.1 · TruffleHog 3.96.0 ·
OSV-Scanner 2.4.0 · Trivy 0.72.0 · Grype 0.116.1 · CodeQL 2.26.2
(`codeql-bundle-v2.26.2`).

**Baseline controls re-run today:** `npm run verify:ts` → 8 errors ·
`verify:ts:clean` → 0 · `samples/dotnet` → 13 distinct errors ·
`samples/dotnet-tests` → 3 · `samples/dotnet-clean` → build succeeded ·
`ruff` → 14 / 0 · `semgrep --config semgrep .` → `Ran 19 rules on 15 files:
60 findings`.

**Probes written for this evaluation** (all outside the repo): a 7-defect
SonarJS-class file, a 4-defect Unicorn-class file, a 5-defect
`eslint-plugin-security`-class file, a 12-convention Python translation, an
8-check Bandit-class Python file, an npm+pip lockfile pair pinned to eight
known-vulnerable versions, a NuGet `.csproj` with and without
`packages.lock.json`, an Express handler and an ASP.NET Core controller each
routing tainted input through a helper into a SQL and a command sink, and an
inlined control for the last pair.

**External sources:**

- [Cannot enable CodeQL in a private repository](https://docs.github.com/en/code-security/code-scanning/troubleshooting-code-scanning/cannot-enable-codeql-in-a-private-repository) — Free/Pro plans, public repositories only
- [CodeQL CLI licence](https://github.com/github/codeql-cli-binaries/blob/main/LICENSE.md) — not for use "in connection with any codebase that is not an Open Source Codebase"
- [SonarQube Cloud subscription plans](https://docs.sonarsource.com/sonarqube-cloud/administering-sonarcloud/managing-subscription/subscription-plans) — Free plan: private projects to 50k LOC, 5 members, main-branch-only, no custom quality profiles or gates
