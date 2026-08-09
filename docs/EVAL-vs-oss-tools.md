# EVAL — this baseline vs. the mature open-source field

> **Date:** 2026-08-02 · **Verdict:** adopt **one** ESLint plugin, conditionally;
> fix **two** of our own rules that this evaluation found broken; adopt nothing
> else.
> **Analysis only** — nothing in `configs/`, `semgrep/`, `scripts/` or
> `samples/` was changed to produce this document. Every probe file lives
> outside the repo.
>
> **Appended 2026-08-05 (issue #39), §2j–§2o and §3d–§3e — verdict:** adopt
> **two** (knip and deptry, both conditionally, each behind its own follow-up
> issue); decline **four** (jscpd, PMD CPD, vulture, Ruff `C90`); confirm
> **one** already shipped (`sonarjs/cognitive-complexity`); record **one** gap
> no free tool closes (unused *public* C# API). The "analysis only" line above
> still holds for the appended sections: the slop corpus was built outside the
> repo, and nothing was wired in.
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

> SonarJS was not in this section when it was written; it was measured against
> real code on adoption, in §2i below.

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

### 2i. SonarJS on real code — the noise run the `-clean` fixtures cannot do

Added 2026-08-03, when the plugin was actually adopted (#11). Placed here rather
than next to §2c so the existing section letters, which other documents link to,
keep pointing at what they always did.

§2c measured Unicorn and `security` against one real file and never gave SonarJS
the same treatment. `samples/typescript-clean` is 89 lines of deliberately
simple code — enough to disqualify an over-strict config, not enough to see what
217 rules at `error` do to a codebase somebody has already written.

Corpus: `zod`, `got` and `zustand` at their default branches, source only, no
tests or `.d.ts`. SonarJS alone, not type-aware, with `todo-tag` and
`no-unused-vars` off as the baseline has them.

| Repo | Lines | Findings | Per KLOC |
|---|--:|--:|--:|
| `zustand` | 1,450 | 14 | 9.7 |
| `got` | 11,220 | 39 | 3.5 |
| `zod` | 31,419 | 467 | 14.9 |
| **total** | **44,089** | **520** | **11.8** |

25 of the 217 enabled rules fired at all, and six were 86% of the output:

| Rule | Findings | Share | Verdict |
|---|--:|--:|---|
| `no-redundant-optional` | 144 | 27.7% | **off — wrong, not merely noisy** |
| `concise-regex` | 125 | 24.0% | **off** — every one is "use `\d` instead of `[0-9]`" |
| `cognitive-complexity` | 100 | 19.2% | **kept** — sampled, real: "reduce from 33 to the 15 allowed" |
| `public-static-readonly` | 35 | 6.7% | kept |
| `no-nested-conditional` | 22 | 4.2% | kept |
| `regex-complexity` | 20 | 3.8% | kept — this is the ReDoS one |

**The finding that matters: `no-redundant-optional` contradicts our own
tsconfig.** It fires on `retries?: number | undefined` and asks you to delete the
union. `configs/typescript/tsconfig.strict.json` sets
`exactOptionalPropertyTypes: true`, under which those two spellings mean
different things — so applying the rule's advice makes `tsc` reject the code:

```
opt.ts(8,14): error TS2375: Type '{ retries: undefined; }' is not assignable to
type 'Config' with 'exactOptionalPropertyTypes: true'.
```

Verified both ways round: as written it compiles, after the fix it does not. Two
halves of one baseline cannot contradict each other, so the rule is off and
`samples/typescript-clean` now carries the shape — re-enabling it makes the
clean fixture dirty and fails CI.

Turning those two off takes real-code output from **11.8 to 5.7 findings per
KLOC, a 52% reduction**, and costs none of the five bug classes in §2b that
justified adopting the plugin.

**A caveat on the corpus, because it changes how the number should be read.**
Three OSS libraries are not a consumer's application, and `zod` alone is 71% of
the lines and 90% of the findings — it is a type-system library, so it is
unusually dense in exactly the constructs the top rules look at. Treat 11.8 as
an upper bound rather than a typical figure. What does *not* depend on the
corpus is the `exactOptionalPropertyTypes` conflict: that is a property of the
two configs and would hold on an empty repository.

---

### 2j. Slop detectors — the disqualifying frame first (issue #39)

Added 2026-08-05. The baseline has no notion of code that is *correct but
should not exist* — a file nobody imports, a dependency nobody uses, a function
duplicated under a second name. Issue #39 asked whether the free field covers
that class. Same method as everything above: the §0 question first, then
detection, then noise on real code.

> **Does it work for a private consumer, on a free tier, yes or no?**

| Candidate | Free for a **private** consumer? | Licence | Maintenance signal (checked 2026-08-05) |
|---|:--:|---|---|
| **knip** 6.31.0 | **yes** — an npm package, nothing else | ISC | ~1 maintainer (sponsored: Vercel, Datadog, …); 15 releases in the 6 weeks to 2026-07-31; 9 open issues |
| **jscpd** 5.0.14 | **yes** — npm package | MIT | ~1 maintainer; mid-rewrite TS→Rust (v4→v5, 2026-06/07); active |
| **PMD CPD** 7.10.0 | **yes** — Java binary / Docker image | BSD-style + Apache-2.0 parts | multi-maintainer, PMD 7.26.0 out 2026-06-29 |
| **deptry** 0.25.1 | **yes** — PyPI package | MIT | 2 maintainers, roughly quarterly; latest 2026-03-18 |
| **vulture** 2.16 | **yes** — PyPI package | MIT | 1 maintainer, slow-but-steady since 2012; latest 2026-03-25 |
| Ruff `C90` | already shipped tool, new `select` entry | MIT (Ruff) | — |
| SonarJS `cognitive-complexity` | already shipped plugin, rule already ON | LGPL-3.0-only (plugin) | — |

**Every candidate passes §0.** All are plain package-manager artifacts with no
account, no source upload and no paid tier, so — unlike CodeQL — nothing here
is disqualified on the asymmetry. What none of them gets for free is the next
two bars. Two notes that are cost, not blockers: knip, jscpd and vulture are
each effectively one person (knip's cadence and sponsorship make that a managed
risk; vulture's is a quiet one), and PMD is the only candidate needing a JVM or
Docker on the runner.

The superseded generation is worth one line each, because all three name their
successor: **ts-prune** (archived 2025-09-19, README: "we recommend knip"),
**depcheck** (archived 2025-06-16, README recommends knip), **unimported**
(archived 2024-03-10, README recommends knip). Evaluating any of them in 2026
would be evaluating a tombstone; knip is the survivor, by its competitors' own
word.

### 2k. The slop corpus, and where it lives

The 103 planted findings in `samples/` are all *defects*, so a dead-code
detector scores 0 against them by construction — that number would look like a
verdict and mean nothing. This evaluation therefore uses a purpose-built
corpus with hand-counted expected findings.

**Where it lives: outside the repo, like every other probe in this document.**
Issue #39's definition of done says "a slop corpus fixture exists", and this
document's header says "Analysis only — every probe file lives outside the
repo". Both cannot hold if the corpus lands in `samples/` during the
evaluation, so the conflict is resolved the way the header demands: the corpus
is a probe, built and versioned outside the tree, and it enters `samples/`
only in the adoption follow-up of whichever tool wins — where it will need the
full fixture treatment (own top-level directory, `-clean` counterpart,
ablation runs, a `.maxi-quality.yml` exclusion). Landing a deliberate-violation
fixture *during* the measurement would also have rewritten
`samples/expected/semgrep.json` mid-evaluation, which is the tail wagging the
dog.

**What it plants, and how it was written.** Three language halves: a TS package
(entry, barrel, dynamic import, 12 files), a Python package (pyproject, 7
files), and a 3-file C# set. Cases were written from the tools' documented
*failure modes*, not their feature lists, and each is marked softball
(documentation says it handles this) or adversarial (a documented or suspected
failure mode). The adversarial set: an export reachable only through a barrel
re-export, a file reachable only through a literal dynamic `import()`, a
dependency whose import name differs from its package name
(`beautifulsoup4`/`bs4`), a function live only through a decorator registry, a
function live only through `importlib` + `getattr`, and a clone pair with
every identifier renamed (type-2). One construction accident is left in the
record because it is itself a result: `tangle.py` initially went unimported,
making its functions genuinely dead — vulture flagged them correctly and the
corpus, not the tool, was wrong. A slop corpus can plant slop by accident.

**TypeScript half — 6 planted findings, 6 negative controls:**

| Planted | knip 6.31.0 (zero config) | jscpd 5.0.14 (min-tokens 50) | CPD 7.10.0 (min-tokens 50) |
|---|:--:|:--:|:--:|
| file imported by nothing | ✅ | — | — |
| unused export | ✅ | — | — |
| unused exported type | ✅ | — | — |
| unused dependency | ✅ | — | — |
| unlisted (undeclared) dependency | ✅ | — | — |
| unused export behind a barrel re-export *(adversarial)* | ✅ | — | — |
| identical 21-line body, function renamed (type-1 clone) | — | ✅ | ✅ |
| same structure, ALL identifiers renamed (type-2, *adversarial*) | — | ❌ | ❌ |
| **total** | **6 of 6** | **1 of 2** | **1 of 2** |
| findings on the 6 negative controls | **0** | 0 | 0 |

The negative controls knip cleared include the two that kill this tool class
in practice: the dynamic `import()` and the barrel. One version note that is
the strongest maintenance signal in this section: knip **5.64.3** flagged a
negative control — a type referenced only in the *signature* of another export
— and **6.31.0 does not**. The FP existed and was fixed within the current
major line. CPD's `--ignore-identifiers` was also tried against the type-2
pair: no change — the flag evidently does not reach the TypeScript tokenizer,
so renamed clones are invisible to **both** duplication tools. jscpd exits 0
even when clones are found unless `--threshold` is set — a gate that defaults
to not gating.

**Python half — 8 planted findings, plus the traps:**

| Planted | deptry 0.25.1 | vulture 2.16 (default confidence) | ruff 0.16.1 `--select C90` |
|---|:--:|:--:|:--:|
| dependency declared, never imported | ✅ DEP002 | — | — |
| module imported, never declared | ✅ DEP001 | — | — |
| unused module-level variable | — | ✅ | — |
| unused function | — | ✅ | — |
| unused class (+ its method) | — | ✅ | — |
| dead stub (`raise NotImplementedError`, never called) | — | ✅ | — |
| function with mccabe complexity 14 | — | — | ✅ C901 (14 > 10, the default) |
| identical 16-line body, function renamed (type-1 clone) | — | jscpd ✅ / CPD ✅ | — |
| **total** | **2 of 2** | **4 of 4** | **1 of 1** |
| false positives on the negative controls | **0** — incl. the `bs4` name-mapping trap | **1** — the decorator-registry function | 0 — complexity-2 control silent |

vulture's split on the two reflection traps is precise and worth recording: a
function reached only via `getattr(mod, "literal")` is **not** flagged (it
special-cases literal getattr names — a separate probe confirmed plain string
literals are *not* treated as uses), while a function registered by decorator
and called through a registry **is** flagged. The decorator case is the shape
every Flask/FastAPI handler has.

**C# half:** jscpd ✅ and CPD ✅ on the renamed-class clone pair — **1 of 1**
each, and both with real C# tokenizers: jscpd reports format `csharp` with
token counts, and CPD's `pmd-cs` module is an ANTLR-generated lexer (the
issue's suspicion that jscpd falls back to line matching for C# was checked
and is wrong). The third file plants an unused **public** method: nothing
fires, no tool claims to, and §2o records why.

### 2l. The clean fixtures — is it over-strict?

| | knip 6.31.0 | jscpd 5.0.14 | CPD 7.10.0 | deptry 0.25.1 | vulture 2.16 | ruff `C90` |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `samples/typescript-clean` | ❌ 4 → ✅ 0 with a 2-key config | ✅ 0 | ✅ 0 | — | — | — |
| `samples/dotnet-clean` | — | ✅ 0 | ✅ 0 | — | — | — |
| `samples/python-clean` | — | ✅ 0 | ✅ 0 | not runnable — no manifest | **❌ 4 findings** | ✅ 0 |
| **total over the three `-clean` fixtures** | **0 with config / 4 without** | **0** | **0** | **—** | **4** | **0** |

Two rows need their story told:

- **knip's 4 default findings are not detector noise, they are entry-point
  declaration.** `clean.ts` does not match knip's default entry pattern
  (`index.{js,ts}`), and the fixture consumes the shared ESLint base config by
  *relative import from outside the project root* — so the three plugin
  devDependencies that base config uses look unused from inside the fixture.
  A two-key `knip.json` (entry + three `ignoreDependencies`) takes it to 0,
  measured in place with the config file held outside the repo. The second
  half generalises: **any consumer adopting this baseline by relative import
  will show the same three-line FP** until knip grows a plugin for that shape
  or the consumer ignores the base config's dependencies; a consumer adopting
  via a published npm package would not, because the dependency graph would be
  declared. That is a real, recurring config cost and it is charged to knip's
  verdict.
- **vulture's 4 findings on `python-clean` are disqualifying, and they are the
  structural kind.** The fixture is library-shaped: public functions that
  nothing inside the fixture calls, because the callers are the point of a
  library. vulture cannot tell a library's exported surface from dead code —
  same blindness in the same place as the C# unused-public-API gap (§2o), but
  here it *fires* instead of staying silent. Under this repo's rule that a
  config flagging the clean fixture has regressed, vulture is disqualified at
  default confidence before the noise run even starts. (`--min-confidence
  100` reports 0 here — and also reports 0 everywhere else; see §2m.)
- deptry's dash is not a pass: it cannot run at all without a dependency
  manifest, which the fixture does not have. On a real consumer that cost is
  zero (they have one), but the fixture cannot prove it clean.

### 2m. Real code, findings per KLOC — is it worth it?

Same reasoning as §2i: a `-clean` fixture answers "is it over-strict?", never
"is it worth it?". Corpus: the three consuming codebases, scanned locally.
Aggregates only — per the pseudonym rule, no file, class or finding detail
from these repos appears here, and a findings table with a location column
would de-anonymise as effectively as a name. Scan scope and file-selection
rule sit in the same row as every number; line counts for the duplication
rows are the scanner's own (`find`+`wc` totals differ slightly because jscpd
skips files it cannot tokenize).

| Corpus + scope | Tool | Findings | Density |
|---|---|---|---|
| Consumer A C#, non-test non-generated `.cs` (no `bin/obj`, no EF migrations), 21,355 lines / 97 files | jscpd 5.0.14 | 101 clones, 931 dup lines | **4.36%** dup lines, 4.7 clones/KLOC |
| same scope, same file list | CPD 7.10.0 | 85 duplications | agrees with jscpd within 16% |
| Consumer A C#, same but **with** the 21,560 generated migration lines | jscpd | 226 clones | **27.19%** — a scope artifact, see below |
| Consumer A TS, non-test `.ts/.tsx` (no `node_modules/dist/.d.ts`), 18,318 lines / 98 files | jscpd | 15 clones, 180 dup lines | 0.98% |
| Consumer B TS, non-test `.ts/.tsx`, 15,544 lines / 108 files | jscpd | 19 clones, 295 dup lines | 1.90% |
| Consumer C Python, non-test `.py` (no `.venv`), 2,966 lines / 31 files | jscpd | 1 clone | 0.27% |
| same | CPD | 1 duplication | agrees |
| Consumer A TS workspace, whole pnpm monorepo, 26,565 non-test lines | knip 6.31.0, zero config | 15 findings | 0.56/KLOC |
| Consumer B TS, whole pnpm monorepo (21 workspaces), 16,277 non-test lines | knip 6.31.0, zero config | 11 findings | 0.68/KLOC |
| Consumer C Python, monorepo **root** | deptry 0.25.1 | 125 findings | 118 of 125 are the workspace artifact |
| Consumer C Python, one member package (the designed granularity) | deptry | 3 findings | — |
| Consumer C Python, `apps` + `libs`, 3,180 lines | vulture 2.16 default | 120 findings | 37.7/KLOC |
| same | vulture `--min-confidence 100` | 0 findings | the knob deletes the tool |
| same, our `ruff.toml` + `C90` at the default max-complexity 10 | ruff 0.16.1 | **0 findings** | 0 |

What the classification pass found, tool by tool:

- **knip is the quietest detector this document has ever measured on real
  code.** 26 findings over 42.8 KLOC of TypeScript across two monorepos —
  SonarJS `recommended` measured 11.8/KLOC on §2i's corpus; knip measures
  **0.61/KLOC**, a 19× difference in the same direction as usefulness.
  Verified by grep, not trusted: **6 true positives confirmed** (five
  never-imported dependencies across both repos, and one dead page-component
  file — the exact artifact class issue #39 exists for), **1 false positive
  confirmed** (a codegen plugin invoked by a non-npm tool knip has no plugin
  for), and the remaining 19 are unused exports/types that are
  *in-repo-unreferenced but structurally indeterminate* — most sit in
  Consumer B's library packages, where an unused export is
  indistinguishable from public API. That last clause is knip's real limit
  and the shape of its correct configuration: dependencies and files gate
  well everywhere; exports gate app code, not library surface.
- **The duplication percentages are honest and the interpretation is not
  flattering to a gate.** The Consumer A C# density (4.36%) is the highest
  real number in the table, and the classification pass punctured it: the
  clones are median-10-lines, mostly within-file, and the sampled majority is
  the repo's *mandated* transaction/idempotency idiom — the same visible
  per-mutation rails that this baseline's own `mutation-requires-authz`
  convention exists to enforce. **Our conventions require the duplication a
  clone gate would flag.** The TS numbers (0.98%, 1.90%) are dominated by
  sibling components and config boilerplate. §2n's literature says exactly
  this: duplication is a change-coupling marker, not a defect predictor.
- **The 27.19% row is the measurement lesson of this evaluation.** With EF
  Core migrations left in scope, Consumer A's C# "duplication" is 27.19%;
  excluding the 31 generated files halves the corpus and takes it to 4.36%.
  The number did not change because the code changed — it changed because the
  denominator was wrong. Issue #39 warned about exactly this for *this
  repo's* snapshots; the consumer-side version (migrations, codegen) is
  worse because it inflates the numerator too.
- **deptry works at the granularity it was designed for and not above it.**
  At Consumer C's monorepo root: 125 findings, of which 105 DEP004 + 13
  DEP001 are the same first-party artifact (workspace packages declared as
  root dev-dependencies, imported as runtime code). At per-package
  granularity: 3 findings on the sampled package. Of the 7 root findings that
  survive classification, one is a **verified true positive** — a heavyweight
  dependency declared and never imported anywhere in the tree — and six are
  direct imports of transitive dependencies, the designed DEP003 catch.
- **vulture's 120 findings decompose as: 100 "unused variable" that are
  pydantic settings/model fields** (framework-populated, read via
  serialization — sampled and confirmed), and 20 methods/functions that are
  route handlers, protocol callbacks, or shared-library public API —
  framework-FP or indeterminate, **zero confirmed true positives in the
  sample**. ≥83% definite-FP before adjudicating the rest, and the only knob
  that removes the noise (`--min-confidence 100`) removes every finding with
  it.
- **Ruff `C90` at the default threshold gates nothing that exists.** 0 of 0
  functions over complexity 10 in the only Python consumer. Adoption would
  start green and stay green until someone writes a tangled function — which
  is the argument *for* a free tripwire and also the argument that there is
  no measured bug behind it. §2n breaks the tie.
- **SonarJS `cognitive-complexity` needs no probe of its own:** it is already
  on in the shipped config (kept deliberately in §2i's noise run at 100 of
  520 findings, sampled real), and a bait function at cognitive complexity 21
  run through `configs/typescript/eslint.config.mjs` fires it — measured
  2026-08-05, "reduce from 21 to the 15 allowed". Status confirmed, nothing
  to adopt.

### 2n. The evidence questions — what the field actually knows

Issue #39 asked three questions to be answered independently of any tool.
Summarised here from the primary literature; full citations in §4.

**Is duplication a defect predictor, or an aesthetic preference?** The
strongest pro-detection result is Juergens et al. (ICSE 2009): across five
industrial systems, ~52% of clone groups had inconsistencies, and roughly
every second-to-third *unintentional* inconsistent change to a clone was a
confirmed fault — 107 developer-confirmed faults. But the same paper states
the mechanism plainly: clones do not cause faults; **inconsistent updates to
clones** do. Göde & Koschke (ICSE 2011) then measured how often that
mechanism fires: most clones are never changed, and only ~3% of clone
modifications are the dangerous kind. And every study that measured
*aggregate* defect association at scale found cloned code at or **below** the
defect density of non-cloned code: Rahman, Bird & Devanbu (MSR 2010/EMSE
2012, four C projects, ~4,700 bugs — "clones may be less defect prone than
non-cloned code"); Sajnani et al. (SCAM 2014, 31 Java projects — 3.7× *lower*
defect density in cloned code); Saini et al. (EMSE 2018, 3,562 projects —
cloned methods no worse). Kapser & Godfrey (EMSE 2008) documented cloning
patterns that are deliberate engineering. **Weight of evidence: duplication
is a change-coupling risk marker, not a defect predictor.** A gate that fails
a build on a duplicated block claims more than the literature will carry —
which is consistent with what §2m measured: the densest real duplication in
the consumers is their mandated idiom, not their bugs.

**Is cyclomatic complexity worth measuring beyond LOC?** The critique is old
and well-replicated: Shepperd (1988) called CC a proxy for LOC; Jay et al.
(2009, 1.2M source files) found a stable linear CC–LOC relationship, "no
explanatory power of its own"; Herraiz & Hassan (2010, ~300K files) concluded
complexity metrics add nothing over LOC. The largest and most careful study —
Landman et al. (2016, 17.6M Java methods + 6.3M C functions) — *softens* that
to "moderate correlation at method granularity", i.e. CC is partially, not
fully, redundant; no study shows the non-redundant part predicting defects
better than length. For cognitive complexity specifically: Muñoz Barón,
Wyrich & Wagner (ESEM 2020, meta-analysis over ~24K comprehension
evaluations) validated that it correlates with comprehension **time**;
Lavazza et al. (JSS 2023) then found it predicts understandability *no
better* than LOC or CC. Both can be true and are. **Weight of evidence: a
complexity budget is a defensible "too big to hold in your head" tripwire,
and no variant of it can claim empirical superiority over a plain length
limit.** That decides Ruff `C90`: a metric with no superiority claim, at a
threshold nothing in the consumer exceeds, is a config line with no bug
behind it. It also right-sizes the already-shipped cognitive-complexity rule:
kept as a tripwire that measured *real* on this repo's own noise run, not as
science.

**Is the "AI slop" premise itself measured?** Split by claim, because the
evidence quality differs sharply. *Duplication is rising:* rests almost
entirely on GitClear's vendor telemetry (2024–2026 reports; 211M changed
lines in the 2025 edition; 8× growth in ≥5-line duplicated blocks during
2024, copy-paste share 8.3%→12.3%) — GitClear sells the analytics that
produce the taxonomy, the dataset is proprietary, there is no per-line AI
attribution, and no peer-reviewed replication exists. *Dead code is rising:*
**unmeasured by anyone** — no study, vendor or academic, directly measures
dead-code growth under AI assistance; the claim is anecdote. *Churn is
rising:* GitClear again, directionally supported by Uplevel (2024, ~800
developers, 41% more PR bugs — also a vendor) and DORA 2024 (survey, delivery
stability −7.2% per 25% AI adoption). What *is* independently established:
AI-generated code has a high raw defect rate (Pearce et al., IEEE S&P 2022 —
~40% of 1,689 Copilot programs vulnerable); assisted users write less secure
code while trusting it more (Perry et al., CCS 2023, n=47); experienced
developers were 19% *slower* with AI while believing themselves 20% faster
(METR RCT, 2025, n=16, 246 real tasks); and Cursor adoption raises
static-analysis warnings and complexity persistently while its velocity gain
fades (He et al. 2025, difference-in-differences, the best causal design in
the set). **Weight of evidence: the quality-erosion direction is real and
independently supported; the specific duplication and churn numbers are
vendor numbers; the dead-code claim has no numbers at all.** Issue #39's
framing does not get a free pass: this evaluation's own measurements — a
verified dead page component, five verified unused dependencies — are the
first non-vendor slop numbers this project has, and they are small.

### 2o. What this evaluation could not measure

Reported per the same rule as a scan that found nothing: saying where nobody
looked is part of the result.

- **Unused public C# API has no free detector, measured and researched.**
  Roslyn's IDE0051 is titled "remove unused *private* member"; Roslynator's
  RCS1213 gates on `Accessibility.Private` in its own source; Sonar's
  S1144/S1481 are private/local-only; `PublicApiAnalyzers` tracks a declared
  API surface, not its use. Even NDepend (paid) excludes public members from
  its dead-code rule *by default* because external callers are invisible.
  The corpus's planted unused public method fired nothing, as predicted. The
  one free lead is JetBrains' InspectCode CLI (free, `--swea` enables
  solution-wide analysis) — **unmeasured here**: whether it emits
  unused-public-member inspections headlessly, and whether its licence terms
  allow gating a private repo's CI, are both unverified. If someone wants
  this gap closed, that is the experiment, and it needs its own issue.
- **C# dead code and unused dependencies beyond duplication were not probed
  on real code.** The C# corpus half covered duplication and the public-API
  gap only; Consumer A's build already banks IDE0051/S1144 for private
  members through Layer 1.
- **jscpd/CPD renamed-clone (type-2) blindness was measured on one pair
  only** — enough to prove existence, not rate. On real code the miss rate is
  unknowable without hand-auditing a consumer, which the pseudonym rule makes
  unpublishable anyway.
- **No per-KLOC comparison to §2i's 11.8 is offered for the new tools on OSS
  code.** The three §2i libraries were not re-cloned; the real-code corpus
  here is the three consumers. The knip 0.61/KLOC and SonarJS 11.8/KLOC
  numbers come from different corpora and are quoted as different orders of
  magnitude, not as a ratio.
- **The AI-attribution question is unmeasurable with these tools.** Nothing
  in §2m distinguishes human slop from generated slop, and per §2n nobody
  else can either. The gate case rests on the findings being worth fixing
  regardless of author.
- **Small denominators.** Consumer C is 3.18 KLOC of non-test Python: one
  finding is 0.31/KLOC, so tools within a few findings of each other are not
  distinguished there. The Python verdicts lean on the corpus and the FP
  classification, not on density deltas.

---

### 2p. SpotBugs and PMD vs. Error Prone, on the Java fixtures (2026-08-09, issue #10)

Issue #10 specified Error Prone and NullAway as the Java Layer 1 and listed
**SpotBugs** as "evaluate; may not clear the bar". Issue #67, filed from the
consuming side, proposed **PMD** "tuned like clippy pedantic". Neither was
pre-judged; both were run.

**Corpus.** `samples/java` (8 planted findings, the four analyzer tiers) and
`samples/java-clean` (idiomatic Spring Boot 4 — records, `JdbcClient`,
constructor injection, a `RowMapper`, an integration-shaped test). Error Prone
was disabled for these runs so the bad fixture would compile — SpotBugs reads
bytecode and cannot run on a build that fails.

**Settings.** SpotBugs 4.9.8.0 at `<effort>Max</effort>` and
`<threshold>Low</threshold>` — its most sensitive configuration, chosen so a
poor result cannot be blamed on a timid one. PMD 3.28.0 at its default ruleset.

| | Planted findings caught (of 8) | Caught that Error Prone does NOT | Findings on the clean fixture |
|---|---|---|---|
| **Error Prone 2.50.0 + NullAway 0.13.8** | 8 | — | **0** |
| **SpotBugs 4.9.8.0** | 4 | **0** | 1 |
| **PMD 3.28.0** | **0** | 0 | 1 |

**SpotBugs: declined.** Its four hits are `EC_BAD_ARRAY_COMPARE`,
`SA_LOCAL_SELF_ASSIGNMENT`, `ES_COMPARING_PARAMETER_STRING_WITH_EQ` and
`NP_NULL_PARAM_DEREF_NONVIRTUAL` — which are, one for one, Error Prone's
`ArrayEquals`, `SelfAssignment` and `ReferenceEquality` plus one of NullAway's
three. **Zero marginal catch**, at the cost of a second tool, a bytecode pass
that cannot run until the build already succeeds, and a report format needing
its own parser.

The clean-fixture finding is the sharper argument: `EI_EXPOSE_REP2` on

```java
public WidgetService(WidgetRepository widgets, Clock clock) {
```

— it flags **constructor injection**, which is the single most universal pattern
in the framework the consuming project is built on. Not a tuning problem: a rule
whose true-positive rate on a Spring codebase is near zero is one every adopter
switches off, and #39's lesson is that the highest-volume rule in a new tool is
the one worth reading first.

**PMD: declined, and more decisively.** Zero of eight. It found no planted bug at
all, and its one finding was on the *clean* fixture — `UnusedFormalParameter` for
`rowNum` in a `RowMapper`, a parameter Spring's own interface requires and that
no implementation can remove. That is the `p/security-audit` result again (0 of
28, then 0 of 103): a mature, widely-deployed tool scoring zero on a corpus of
real planted bugs, because its ruleset is aimed at a different question.

**What would reopen either.** New measured evidence on a bigger corpus, the same
bar `eslint-plugin-sonarjs` cleared and nine other candidates did not. Repo
count, popularity and "it is the standard Java tool" are not evidence.

**Checkstyle was declined without a scoreboard, and the reason is structural
rather than empirical.** CONCEPT §4a's argument against offering two formatters
for one language applies equally to offering a formatter *and* a style linter:
two tools with a view on the same lines is the argument that section exists to
end. Spotless owns layout; Error Prone owns bugs; there is no third question for
Checkstyle to answer that this baseline wants answered.

## 3. Verdict

### 3a. Adopt: one plugin, conditionally

> **`eslint-plugin-sonarjs@4.2.0` at `recommended`, with `sonarjs/todo-tag` and
> `sonarjs/no-unused-vars` turned off.**

**Landed 2026-08-03** — see `configs/typescript/eslint.config.mjs` and the
five-class fixture in `samples/typescript/src/sonarjs.ts`. The clean fixture
still reports zero. Everything below is the measurement as taken; it is not
rewritten to match the outcome.

**With two more rules off than this verdict called for.** Adoption triggered the
real-code noise run in §2i, which the `-clean` fixtures are too small to
substitute for, and it found `sonarjs/no-redundant-optional` asking for a change
that our own `exactOptionalPropertyTypes` makes uncompilable. That rule and
`concise-regex` are off; between them they were 52% of everything the plugin
said about 44,089 lines of real TypeScript. The verdict above is left as
written — it was right about adopting, and incomplete about the conditions.

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

### 3d. Verdicts for the slop detectors (2026-08-05, issue #39)

> **Adopt `knip` and `deptry`, both conditionally. Nothing is wired in by this
> evaluation** — adoption is a follow-up issue per tool, where the slop corpus
> enters `samples/` with the full fixture treatment.

**knip 6.31.0 — adopt, three conditions.** The numbers: **6 of 6** planted
findings with 0 false positives on the corpus including the barrel and
dynamic-import traps; **0 of 6** negative controls flagged; **0 findings** on
`samples/typescript-clean` with a 2-key config; **26 findings over 42.8 KLOC**
(0.61/KLOC) of real TypeScript across two monorepos with zero per-repo config,
of which 6 verified true positives — including a dead page component and five
never-imported dependencies — against 1 verified false positive. It detects
the exact artifact classes issue #39 names, at a noise level 19× below the
plugin this repo already adopted. The conditions, each measured: (1)
per-consumer entry declaration — the clean fixture needed a 2-key config, and
a zero-config run on a non-default layout reports the layout, not defects;
(2) consumers adopting this baseline by relative import must ignore the base
config's three plugin dependencies or knip reports them unused — charged to
knip here, structural until the baseline publishes as a package; (3) the
`exports`/`types` issue types gate application code only — in published
library packages an in-repo-unreferenced export is indistinguishable from
public API, and 19 of the 26 real-code findings sit in that indeterminate
class. Dependencies, unlisted dependencies and unused files gate everywhere.

**deptry 0.25.1 — adopt, one condition.** The numbers: **2 of 2** planted, 0
false positives including the `bs4`/`beautifulsoup4` name-mapping trap; **125
findings at Consumer C's monorepo root of which 118 are one first-party
artifact**, versus **3 findings at the per-package granularity it is designed
for**; 1 verified true positive (a heavyweight dependency declared and never
imported anywhere) and six direct-imports-of-transitives among the real
remainder. The condition is the granularity: deptry runs per package, never at
a workspace root, and the adoption issue must encode that or the gate ships
94% noise on day one.

### 3e. Java (2026-08-09, issue #10)

**Adopted:** Error Prone 2.50.0 (the bug finder), NullAway 0.13.8 at ERROR (the
null-safety layer), Spotless 3.9.0 + palantir-java-format 2.97.0 in AOSP style
(the formatter — 4-space at 100 columns, which is what `configs/editorconfig`
already declares).

**Declined:** SpotBugs (0 marginal findings, 1 false positive on constructor
injection), PMD (0 of 8 planted findings, 1 false positive on a framework-
required parameter), Checkstyle (structural — Spotless already owns layout).
Numbers in §2p.

### 3f. Declined, with the numbers

| Candidate | Measured | Why not |
|---|---|---|
| **jscpd 5.0.14** | 3 of 3 type-1 clones (TS/PY/C#); **0 of 1** renamed clone; 0 on all three `-clean` fixtures; real code 0.27–4.36% dup lines | The densest real duplication it found is Consumer A's *mandated* per-mutation idiom — the visible rails our own `mutation-requires-authz` convention exists to keep visible, so a clone gate fights the baseline's own conventions. The literature (§2n) supports duplication as a change-coupling marker, not a defect predictor; a number this gate would fail builds over predicts nothing. Exit code is 0 on findings unless `--threshold` is set — not a gate by default. Kept in mind as a *report* tool, not adopted as one: the standing report has no duplication row today and adding one is a decision for its own issue, made against §2n, not smuggled in as a footnote. |
| **PMD CPD 7.10.0** | 3 of 3 type-1; **0 of 1** renamed even with `--ignore-identifiers` (TS); 85 vs jscpd's 101 on the identical 21.4-KLOC file list | Agrees with jscpd within 16% while needing a JVM or Docker on every runner; adds no detection jscpd lacks on these languages, and the C#-tokenizer doubt that motivated it was checked and resolved in jscpd's favour. Same §2n objection as jscpd. |
| **vulture 2.16** | 4 of 4 planted + 1 predicted FP (decorator registry); **4 findings on `samples/python-clean`**; **120 findings on 3.18 KLOC** of Consumer C (37.7/KLOC), ≥100 of them pydantic fields, 0 confirmed true positives in the classified sample; `--min-confidence 100` → **0 findings anywhere** | Flags the clean fixture, which is disqualifying by this repo's own rule — and the failure is structural, not tunable: it cannot tell a library's public surface or a framework's field/handler conventions from dead code, and the only confidence level that silences the noise silences the tool. The whitelist/`--ignore-decorators` route is per-consumer curation of every FP class, the exact maintenance shape this baseline exists to avoid. |
| **Ruff `C90`** | 1 of 1 planted (14 > 10 at the unmodified default); 0 on both Python fixtures; **0 findings over 3.18 KLOC** on the only Python consumer | Zero cost, zero noise — and zero findings, on the codebase whose own ruleset this config deliberately mirrors. The Python families are Consumer C's thirteen, measured, not a wishlist (CLAUDE.md §4); C90 is not among them, no bug motivates it, and §2n's literature denies complexity metrics any predictive claim beyond length. Re-open the day a real tangled function ships a real bug — with that function as the fixture. |
| **SonarJS `cognitive-complexity`** | already ON in the shipped config; fired on a complexity-21 bait through `configs/typescript/eslint.config.mjs` (2026-08-05); 100 of 520 findings in §2i's noise run, sampled real, kept | Nothing to adopt — the issue listed it as a candidate and it is inventory. Recorded so the next session does not re-litigate it. |

Two of seven candidates adopted, four declined, one already shipped. One
recommendation is surfaced for the owner rather than decided here, because it
touches the 12-convention cap: the corpus's stub-throw cases
(`throw new Error('TODO: …')`, bare `raise NotImplementedError` outside an
ABC) were caught by **no candidate** — knip sees the file as used, vulture
only flags the Python one when the stub is also uncalled — and
`todo-without-issue` is already most of that shape. Extending it to the three
stub spellings is arguably widening convention 4, not a thirteenth
convention; the measurement is banked here either way, and per CLAUDE.md §4
that widening is an explicit owner decision, not something this evaluation
implements.

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

---

### 4b. Provenance for §2j–§2o and §3d–§3e (2026-08-05)

Same machine as §4. **Tool versions:** knip 6.31.0 (npx; 5.64.3 also run for
the version-delta note) · jscpd 5.0.14 (npx; 4.2.5 cross-checked, agreed on
the corpus) · PMD CPD 7.10.0 (`ghcr.io/pmd/pmd:7.10.0` via Docker; no JVM
installed locally, which is itself a data point for §3e) · deptry 0.25.1
(project-env overlay via `uv run --with deptry`, so package-metadata name
mapping worked as designed) · vulture 2.16 · Ruff 0.16.1 (the repo's pinned
version) · eslint-plugin-sonarjs 4.2.0 through the shipped
`configs/typescript/eslint.config.mjs`.

**The slop corpus lives outside the repository** (scratch space), 22 files +
manifest: a 12-file TS package with installed `node_modules` (the unlisted
dependency deliberately neither declared nor installed), a 7-file Python
package with a venv carrying its real dependencies, 3 C# files. Hand-counted
manifest with each case marked softball or adversarial, written before the
first tool ran. The working tree was verified clean after every in-place run
(`git status --porcelain`).

**Baseline controls re-run 2026-08-05:** `verify:ts` → 14 errors ·
`verify:ts:clean` → 0 · `ruff check` on `samples/python/src` → 14 ·
`ruff --select C90` on both Python fixtures → 0.

**Real-code scans:** file-selection rules and line counts are recorded in the
§2m table rows themselves; duplication line counts are the scanner's own.
Counts were taken from JSON reporters, never from console output (§5 of
STATUS.md, standing lesson). Per the pseudonym rule, scan detail beyond the
aggregates is deliberately unpublished.

**External sources for §2j–§2n** (all checked 2026-08-05):

- [knip issue types](https://knip.dev/reference/issue-types) · [handling issues](https://knip.dev/guides/handling-issues) — defaults, plugin system, barrel/dynamic-import guidance
- [ts-prune](https://github.com/nadeesha/ts-prune) / [depcheck](https://github.com/depcheck/depcheck) / [unimported](https://github.com/smeijer/unimported) — all archived, all recommending knip in their own READMEs
- [jscpd README](https://github.com/kucherenko/jscpd) — Rabin-Karp over tokens; `--min-tokens` default 50; `--threshold` default null (no gate)
- [deptry rules](https://deptry.com/rules-violations/) · [usage](https://deptry.com/usage/) — DEP001–DEP005, package-metadata name mapping, `package_module_name_map`
- [vulture README](https://github.com/jendrikseipp/vulture) — confidence semantics, whitelists, `--ignore-decorators`
- [PMD CPD docs](https://docs.pmd-code.org/latest/pmd_userdocs_cpd.html) · [pmd-cs ANTLR lexer, PR #2280](https://github.com/pmd/pmd/pull/2280) — real C# tokenizer
- [Roslyn IDE0051](https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/style-rules/ide0051) · [Roslynator RCS1213 source](https://github.com/dotnet/roslynator/blob/main/src/Analyzers/CSharp/Analysis/UnusedMember/UnusedMemberAnalyzer.cs) · [PublicApiAnalyzers help](https://github.com/dotnet/roslyn-analyzers/blob/main/src/PublicApiAnalyzers/PublicApiAnalyzers.Help.md) · [NDepend dead-code rule](https://www.ndepend.com/docs/detect-and-remove-dead-code) · [ReSharper CLT / InspectCode](https://www.jetbrains.com/help/resharper/ReSharper_Command_Line_Tools.html) — the §2o gap
- [Ruff C901](https://docs.astral.sh/ruff/rules/complex-structure/) · [mccabe max-complexity default 10](https://docs.astral.sh/ruff/settings/#lint_mccabe_max-complexity)
- §2n literature: [Juergens et al. 2009](https://dl.acm.org/doi/10.1109/ICSE.2009.5070547) · [Göde & Koschke 2011](https://ieeexplore.ieee.org/document/6032470) · [Rahman, Bird & Devanbu 2012](https://link.springer.com/article/10.1007/s10664-011-9195-3) · [Kapser & Godfrey 2008](https://link.springer.com/article/10.1007/s10664-008-9076-6) · [Sajnani et al. 2014](https://ieeexplore.ieee.org/document/6975632/) · [Saini et al. 2018](https://link.springer.com/article/10.1007/s10664-017-9572-7) · [Shepperd 1988](https://digital-library.theiet.org/doi/10.1049/sej.1988.0003) · [Jay et al. 2009](https://content.scirp.org/pdf/jsea20090300001_74742661.pdf) · [Herraiz & Hassan 2010](https://www.oreilly.com/library/view/making-software/9780596808310/ch08.html) · [Landman et al. 2016](https://onlinelibrary.wiley.com/doi/abs/10.1002/smr.1760) · [Campbell, Cognitive Complexity](https://www.sonarsource.com/docs/CognitiveComplexity.pdf) · [Muñoz Barón et al. 2020](https://arxiv.org/abs/2007.12520) · [Lavazza et al. 2023](https://www.sciencedirect.com/science/article/abs/pii/S0164121222002370) · [GitClear 2025](https://www.gitclear.com/ai_assistant_code_quality_2025_research) · [Pearce et al. 2022](https://www.computer.org/csdl/proceedings-article/sp/2022/131600a980/1FlQxERjKCs) · [Perry et al. 2023](https://arxiv.org/abs/2211.03622) · [METR 2025](https://arxiv.org/abs/2507.09089) · [He et al. 2025](https://arxiv.org/pdf/2511.04427) · [Uplevel 2024](https://uplevelteam.com/blog/ai-for-developer-productivity) · [DORA 2024 via Google Cloud](https://cloud.google.com/devops/state-of-devops)
