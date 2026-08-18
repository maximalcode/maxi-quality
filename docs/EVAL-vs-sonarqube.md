# EVAL — this baseline vs. self-hosted SonarQube Community Build

> **Date:** 2026-07-31 · **Verdict:** keep the baseline; adopt one Sonar
> component (as a library, not a server); un-park nothing else.
> **Analysis only** — nothing in `configs/`, `semgrep/` or `scripts/` was
> touched to produce this document.
>
> **`#NN` references** throughout are from the pre-publication tracker, which
> stayed private (CLAUDE.md §2). They record what was decided and when. They are
> **not** this repo's issue numbers — the public tracker starts fresh at #1, so
> any overlap is coincidence.
>
> **2026-08-18:** detection is settled and is not re-run. A separate
> **presentation-layer** eval is pre-registered under the milestone *sonarqube —
> presentation layer, measured*; §1b carries the hosting note.

This answers one question: *is hand-rolling this baseline better than just
running free SonarQube?* Everything asserted about Sonar's edition boundaries
was checked against current primary sources (linked in §3), because those
boundaries move. Everything asserted about this repo was re-run, not read out
of `STATUS.md`.

---

## 1. The real question: this baseline vs. free SonarQube

### 1.0 One correction to the premise, up front

The brief says *"SonarCloud's free tier is public-repo only."* **That is no
longer accurate.** SonarQube Cloud's Free plan explicitly covers *"Analysis of
private projects — Up to 50k LOC"*, with 5 members. So there are **two** free
Sonar options for a private repo, not one:

| Option | Private repos? | Real blockers for this use case |
|---|---|---|
| **SonarQube Cloud, Free plan** | yes, **≤50k LOC**, 5 members | **no custom quality profiles**, main-branch-only, PR analysis only against main, and your private source is uploaded to Sonar's cloud |
| **SonarQube Community Build, self-hosted** | yes, unlimited LOC | server + database to run; branch/PR analysis absent (§1c) |

The "no custom quality profiles" limit is decisive against Cloud Free — §1f
shows the rules that matter most for TypeScript are *off by default in Sonar
way*, and on the Free Cloud plan you cannot turn them on. Combined with shipping
private source to a third party, Cloud Free is out.

**So the brief's framing is right in its conclusion — self-hosted Community
Build is the realistic comparison — but for a different reason than stated.**

Other genuinely-free options worth naming and dismissing:

- **GitHub CodeQL** — confirmed still gated: *"If you are on a GitHub Free or
  GitHub Pro plan, you can only use code scanning on repositories that are
  publicly available."* Private repos need a paid Code Security licence.
  That was decisive while this repo was private; publishing removed the
  constraint, and CodeQL is now merely one more thing that would have to be
  measured before adoption.
- **`eslint-plugin-sonarjs`** — Sonar's own JS/TS rules, LGPL, as a plain ESLint
  plugin, **no server**. This one is not dismissed; see §2.2.
- **Qodana Community / OpenGrep** — viable but strictly lateral moves; neither
  changes the analysis below.

### 1a. Zero spend

Confirmed. This repo is private and stays private (`CLAUDE.md` §2), which rules
out CodeQL free and makes Cloud Free unusable (§1.0). Community Build is
free-as-in-beer and self-hosted, so it satisfies the hard constraint on price.
**Price is not where Sonar loses.**

> **Superseded 2026-08-01 — the premise, not the conclusion.** `CLAUDE.md` §2 was
> reversed and the baseline is now published, so CodeQL free and Sonar Cloud Free
> are both available. That changes nothing here: Sonar lost on **detection**
> (§2), not on price, and this section already says price is not where it loses.
> Both now qualify for the same treatment as anything else — measured against
> `samples/` and reported with numbers before adoption.

### 1b. Upkeep

Community Build is a Java server, not a CLI:

- **Database:** *"The embedded H2 database is not recommended for production"* —
  production needs PostgreSQL, SQL Server, or Oracle. So it's minimum two
  containers plus a volume, and a database whose backup is now your problem.
- **RAM:** 4 GB minimum for a small-scale instance; Elasticsearch runs in-process
  and wants its heap resident.
- **Java:** JDK 21 or 25.
- **Upgrades — this is the sharp edge.** *"A new version of SonarQube Community
  Build is released every month"* and *"There is no active version or Long-Term
  Active (LTA) version concepts for SonarQube Community Build, meaning bug and
  security issues won't be fixed until the next Community Build version."*
  No LTA and no backports means the only supported posture is *upgrade monthly,
  forever* — with a database migration each time. Community Build also has no
  guaranteed upgrade path to the paid editions if you ever want one.

Against this: `scan.sh` is a bash script. It has no server, no database, no
persistent state, no attack surface, and no upgrade cadence — the tools are
pinned or fetched per-run, and `STATUS.md` already documents deliberate version
pinning as policy.

**For a one-person setup, a monthly forced upgrade of a stateful Java service
with a database is a real recurring tax — call it 1–2 h/month plus the
occasional bad migration.** The baseline's equivalent tax is ~0, and its
`--require-tools` flag means the failure mode is a loud skip rather than silent
non-coverage.

> **Superseded 2026-08-18 — the hosting premise, not the conclusion.** This
> section costed a server that did not exist, so every figure here was
> hypothetical. A self-hosted instance exists now, which makes the presentation
> layer measurable rather than theoretical. It changes **none** of §1c, §1d, §1f
> or §1g — those are analysis-capability gaps invariant to hardware. The
> monthly-upgrade, no-LTA, no-backport tax is unchanged too: an instance gives
> that cost a home, it does not reduce it. Quantifying it is Q4 of the
> pre-registered eval.

### 1c. Branch and PR analysis — this is decisive

Confirmed from Sonar's own documentation: *"Branch analysis is available
starting in Developer Edition"* and *"Pull Request analysis is available
starting in Developer Edition."* For Community Build, the main branch *"is the
only branch you can analyze."*

Work through what that means for a CI gate:

- A PR builds a **feature branch**. Community Build cannot analyze it.
- Therefore Sonar CE cannot produce a per-PR quality gate. It can only tell you
  that `main` got worse — **after** the bad code has already landed.
- The workaround is the third-party `sonarqube-community-branch-plugin`, which
  its own README describes as not maintained or supported by SonarSource, with
  no upgrade path to commercial editions. Bolting an unsupported binary plugin
  into a server you must upgrade monthly (§1b) is a maintenance trap, not a
  solution.

The entire purpose of the reusable workflow is *a failing check on a pull request*. Community
Build structurally cannot do that job. **This alone disqualifies Sonar CE as a
replacement for the CI gate.** Semgrep + ESLint + `dotnet build` are per-commit
CLIs; they neither know nor care what branch they are on.

### 1d. Custom rules — the decisive one for the *value*

The 12 conventions are the whole selfmade contribution. Sonar's own extension
guide gives the custom-rule support matrix:

- **XPath 1.0:** Flex, PL/SQL, PL/I, XML.
- **Java plugin API:** COBOL, Java, PHP, Python, RPG.
- **C#, VB.NET, JavaScript, TypeScript:** *neither*. The only mechanism is
  Generic Issue Reports / SARIF import — i.e. **you run some other analyzer and
  import its findings.**

So for this repo's exact stack — TypeScript and C# — **authoring a custom rule
inside Sonar is not merely hard, it is not offered.** There is no Java-plugin
escape hatch either. The question "is a Java plugin feasible?" is moot: for C#
and TS there is no plugin API to write against.

Compare the cost of a convention here. `mutation-requires-authz.yaml` is 54
lines for *both* languages — ~25 lines per language, declarative, diffable,
reviewable, and testable by a sample file. The whole ruleset is under 600 lines of
YAML.

**Sonar's only path to these 12 conventions is to run Semgrep anyway and import
the SARIF.** That is not a replacement for the baseline; it is the baseline plus
a database.

### 1e. Overlap already banked for C#

`configs/dotnet/Directory.Build.props` already carries
`SonarAnalyzer.CSharp 10.31.0.145097` as a `PrivateAssets=all` analyzer
reference. Sonar's C# rule engine therefore already runs on every
`dotnet build`, with `TreatWarningsAsErrors`, no server, no scanner, no token.
Today's run proves it: `S2930`, `S1144`, `S1481` fired as build errors.

What a server would add for C#:

| Server adds | Worth it? |
|---|---|
| Dashboard, trend, historical debt | Real, but a solo dev reads CI output, not a trend chart |
| Security hotspot review workflow | A ceremony for teams; noise for one person |
| Taint analysis (cross-method injection flow) | **Not in Community Build** — Developer Edition and up |
| Rules missing from the NuGet | The gap is precisely the `SonarAnalyzer.Security` taint rules (e.g. `S3649`) — the ones CE doesn't have anyway |

There is also a cost: `SonarScanner for .NET` must wrap the build in a
`begin` → `build` → `end` sequence, pointed at a live server with
`sonar.host.url` and a token. That converts an offline `dotnet build` into a
build with a network dependency on a service you maintain.

**Verdict for C#: a Sonar server adds a dashboard and nothing else that CE can
deliver. The engine is already banked, for free, at build time.**

### 1f. Type-aware TypeScript — where the gap is widest

This is the sharpest finding in the document, and it is confirmed two
independent ways.

**Evidence 1 — Sonar's own rule inventory.** SonarJS's complete external and
decorated rule tables (which map every Sonar rule id to the ESLint rule
implementing it) contain **zero** references to `no-floating-promises`,
`no-unsafe-assignment`, `no-unsafe-return`, `no-unsafe-member-access`,
`no-unsafe-call`, or `no-unsafe-argument`. No Sonar rule id implements them. The
nearest, `S6544`, maps to `no-misused-promises` — a *different* rule.

**Evidence 2 — Sonar's default profile.** From `Sonar_way_profile.json` in
SonarJS (448 rules) and the per-rule metadata:

| Sonar rule | ESLint rule it maps to | In "Sonar way"? |
|---|---|---|
| `S4204` | `no-explicit-any` | ❌ `defaultQualityProfiles: []` |
| `S2966` | `no-non-null-assertion` | ❌ `[]` |
| `S1440` | `eqeqeq` | ❌ `[]` |
| `S6544` | `no-misused-promises` | ✅ |
| `S1481` / `S1854` | unused local / dead store | ✅ |

**Evidence 3 — empirical.** Running `eslint-plugin-sonarjs@4.2.0` (Sonar's own
JS/TS rules, `recommended` = all 279) with full type information over the
identical `samples/typescript/src/bad.ts`:

```
48:9  error  Remove the declaration of the unused 'taxRate' variable  sonarjs/no-unused-vars
48:9  error  Remove this useless assignment to variable "taxRate"     sonarjs/no-dead-store

✖ 2 problems
```

**One of the eight planted bugs.** And running `no-misused-promises` (i.e.
S6544, which *is* in Sonar way) directly against the file produces **zero
findings** — confirming it does not catch the floating promise on line 25.

Scoreboard on the same file:

| Planted bug | this baseline | Sonar CE, Sonar way | Sonar CE, hand-tuned profile |
|---|:--:|:--:|:--:|
| floating promise (`saveUser('ada');`) | ✅ | ❌ | ❌ **no such rule exists** |
| explicit `any` | ✅ | ❌ | ✅ (enable S4204) |
| unsafe assignment from `any` | ✅ | ❌ | ❌ **no such rule** |
| unsafe return of `any` | ✅ | ❌ | ❌ **no such rule** |
| unsafe member access on `any` | ✅ | ❌ | ❌ **no such rule** |
| `==` | ✅ | ❌ | ✅ (enable S1440) |
| unused variable | ✅ | ✅ | ✅ |
| non-null assertion | ✅ | ❌ | ✅ (enable S2966) |
| **total** | **8/8** | **1/8** | **4/8** |

To be fair to Sonar: `eslint-plugin-sonarjs` is not byte-identical to the
server-side analyzer, and the 4/8 column assumes a hand-built quality profile
(possible in self-hosted CE, impossible on Cloud Free). But the three lines of
evidence agree, and the four permanently-missing rows are missing because **no
Sonar rule id implements them at all** — that is not a profile setting.

The answer to *"does Sonar's TS analyzer match `strict-type-checked`?"* is
**no, and not by a small margin.** `any`-propagation and floating-promise
detection — the two highest-value type-aware checks — have no Sonar equivalent
in any edition.

The converse is also true and worth saying: SonarJS has 279 rules,
~250 of which typescript-eslint has no counterpart for (cognitive complexity,
duplicated branches, identical conditions, nested control flow). See §2.2.

### 1g. Dependency and secret scanning

| | Baseline | SonarQube Community Build |
|---|---|---|
| **Secrets** | Gitleaks — today's run: `10 commits scanned`, `no leaks found` | **Included** in Community Build, 60+ rules out of the box |
| **Secrets in history** | ✅ scans commit history | ❌ analyses the checked-out tree; a secret committed then deleted is invisible |
| **Custom secret patterns** | ✅ `.gitleaks.toml` + `hardcoded-secret-*` Semgrep rules | ❌ *"SonarQube Community Build doesn't support defining custom rules based on your own secret patterns"* |
| **Dependency vulns (SCA)** | OSV-Scanner — today's run scanned `package-lock.json` (92 packages) and the `.props` NuGet refs, `No issues found` | ❌ **Not in CE.** SCA ships in *SonarQube Advanced Security*, a paid add-on *"starting in Enterprise Edition"* |

Sonar CE is credible on secrets (this is genuinely its strongest free feature)
but weaker on history and custom patterns, and it has **no dependency scanning
at all** at any free tier. OSV-Scanner has no replacement in the Sonar stack.

### 1h. Local dev loop

Measured today: **`./scripts/scan.sh` — 3.02 s, exit 1**, no daemon, no network
service, works offline once tool images are cached. That is comfortably inside a
pre-commit hook, and `--changed-only` narrows it further.

Sonar's equivalent requires: server up, database up, `sonar.host.url`
reachable, a token, and for C# a `begin`/`build`/`end` wrapper around MSBuild.
Results land in a web UI rather than the terminal. Sonar's own answer to
"lint locally" is not the server at all — it's SonarQube for IDE in connected
mode, which is a *third* moving part.

**Not close.** A gate you run in 3 seconds gets run; a gate that needs
`docker compose up` first does not.

### 1i. Portability and lock-in

The baseline: ESLint flat config, MSBuild props, YAML rules, one bash script.
Every artifact is plain text in git, readable without any of the tools
installed, and portable to any CI. The rules are yours.

Sonar CE: since **29 November 2024**, Community Build binaries remain LGPLv3 but
**the bundled analyzers moved to the Sonar Source-Available License v1
(SSALv1)** — a non-compete-restricted, non-OSI licence that also carries an
explicit clause against *"employing, using, or engaging artificial intelligence
technology that is not part of the Program to … analyze … the data provided by
the Program."* Findings live in a PostgreSQL schema you do not own the shape of;
quality profiles live in the server, not in git; and Community Build has no
supported upgrade path into the commercial editions. Sonar has also shown
willingness to move the free/paid line (SCA into a paid add-on; the 2024
relicensing).

**Betting a personal, decade-scale baseline on that line staying where it is
today is the actual risk**, and it is asymmetric: the baseline can adopt a Sonar
component later (§2.2) far more easily than a Sonar-centric setup could shed one.

### 1j. Scale sensitivity — and where the crossover really is

The design doc then parked Sonar until ≥3 repos consumed the baseline. Testing
that trigger — which this evaluation went on to void:

| Consuming repos | Does Sonar CE become right? |
|---|---|
| **1** | No. Server overhead is pure cost. |
| **3** | **No — and this is the finding.** Nothing about repo count fixes §1c (no PR analysis), §1d (no custom rules for TS/C#), §1f (no `any`/floating-promise rules), or §1g (no SCA). Three repos multiply the *dashboard's* appeal, not Sonar's *analytical* coverage. |
| **10** | Still no, for the same four reasons. What genuinely improves at 10 is the value of a cross-repo overview — but that is a reporting problem, and SARIF import (§2.2) or a static summary solves it without adopting Sonar as the analyzer. |

**The "≥3 repos" trigger is measuring the wrong variable.** Repo count drives
the value of *aggregation*; every one of Sonar CE's disqualifiers is an
*analysis capability* gap that is invariant to repo count. The honest trigger
would be: *"I want cross-repo historical trend badly enough to run and monthly-
upgrade a stateful Java service, and I have accepted that it cannot gate PRs."*
For a one-person operation that condition is unlikely to ever fire.

So: **the original call to park Sonar was right; the reason recorded for it
was wrong**, and the wrong reason has a built-in trigger that will fire in a few
months and re-open a question that is actually settled.

---

## 2. Verdict

### 2.1 Keep the baseline as designed. Do not adopt a Sonar server — not at 3 repos, not at 10.

This is not a defence of existing work. If Sonar CE could gate a PR, or express
"mutations must call the authz gate", or catch a floating promise, the sunk two
sessions would be worth discarding. It can do **none of those three**:

1. **It cannot gate a PR.** Branch and PR analysis start at Developer Edition;
   CE analyses the main branch only. A PR gate is therefore impossible
   on CE. *(§1c)*
2. **It cannot express the 12 conventions.** Custom rule authoring for C# and
   TypeScript is not offered in any edition — not via XPath, not via a Java
   plugin. Its only path is importing SARIF from an external analyzer, i.e.
   running Semgrep anyway. *(§1d)*
3. **It catches 1 of 8 planted TypeScript bugs out of the box, 4 of 8 tuned**,
   and the four it can never catch are the `any`-propagation and
   floating-promise families — with no rule id existing at all. *(§1f)*

Add: no SCA at any free tier (§1g), monthly forced upgrades with no LTA and no
security backports (§1b), a source-available analyzer licence since Nov 2024
(§1i), and a 3-second CLI replaced by a server-plus-database (§1h).

For C# specifically, the thing worth having from Sonar — its rule engine — **is
already banked** via `SonarAnalyzer.CSharp` at build time, and a CE server adds
a dashboard and nothing else (§1e).

### 2.2 The hybrid, named precisely

There is one, and it is small:

> **Sonar replaces nothing. Add `eslint-plugin-sonarjs` to
> `configs/typescript/eslint.config.mjs` as an additional Layer 1 plugin.**

Rationale: it is the exact symmetry of what the C# side already does. C# banks
Sonar's engine as a NuGet analyzer; TypeScript should bank Sonar's engine as an
ESLint plugin. Same trade — Sonar's rules, zero server. It is **additive, not
overlapping**: SonarJS ships 279 rules, and confirmed today it implements *none*
of `no-floating-promises` / `no-unsafe-*`, while typescript-eslint has no
counterpart for its ~250 code-smell rules (cognitive complexity, duplicated
branches, identical conditions, nested control flow).

Two caveats before doing it: (i) 279 rules at `error` on a real codebase is a
false-positive risk, so it must be measured against the clean samples in
`samples/` before it lands; (ii) it adds a
dependency to the consumer's `node_modules`, so it belongs in `peerDependencies`
and in the README's install line.

**This is a later item, not a blocker.** It does not block the reusable workflow.

The *other* possible hybrid — running CE purely as a SARIF sink for Semgrep
findings — is technically supported (`sonar.externalIssuesReportPaths` /
`sonar.sarifReportPaths` work in Community Build). It buys a dashboard and costs
a server plus database plus monthly upgrades. **Not recommended**, but it is the
correct shape *if* a dashboard is ever genuinely wanted, and it is worth
recording because it means adopting Sonar later never requires abandoning the
Semgrep rules.

### 2.3 Effort, compared

Keeping this baseline costs roughly nothing ongoing — the tool pins are bumped
deliberately and nothing else runs. Replacing it with self-hosted Sonar CE costs
a day of setup (compose, PostgreSQL, volumes, backups, a scanner in CI,
`begin`/`end` around the .NET build, and a hand-built quality profile to recover
4 of the 8 TypeScript rules), then **1–2 h/month** of forced upgrades and
database migrations — and it still does not gate PRs and still loses all 12
conventions unless Semgrep is kept anyway. Adding `eslint-plugin-sonarjs`
alongside the baseline is a couple of hours with no ongoing cost.

Replacement is dominated on every axis except "has a dashboard".

---

## 3. What was checked, and where

Verified locally on 2026-07-31 (macOS, Node 24/npm 11, .NET SDK 10, Semgrep via
`uvx`, Gitleaks + OSV-Scanner via Docker):

- `npm run verify:ts` → 8 errors, exit 1
- `samples/dotnet && dotnet build` → 13 errors, 0 warnings, FAILED
- `./scripts/scan.sh` → `Ran 19 rules on 8 files: 26 findings`, exit 1, **3.02 s** (the ruleset has since gained fixtures and branches; it is 60 today)
- distinct semgrep rule ids in output (19) vs `- id:` entries in `semgrep/` (19)
- `gh api repos/maximalcode/maxi-quality/actions/permissions/access` →
  `{"access_level":"none"}`
- `eslint-plugin-sonarjs@4.2.0` (all 279 rules, type-aware) over
  `samples/typescript/src/bad.ts` → 2 findings on 1 planted bug
- `@typescript-eslint/no-misused-promises` (= Sonar S6544) over the same file →
  0 findings
- SonarJS `Sonar_way_profile.json` (448 rules) and per-rule metadata for S4204,
  S2966, S1440, S6544, S1854, S1481

External sources:

- [Adding coding rules — SonarQube Community Build](https://docs.sonarsource.com/sonarqube-community-build/extension-guide/adding-coding-rules) — custom-rule support matrix by language
- [Branch analysis — SonarQube Server](https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/setting-up-the-branch-analysis) and [Pull request analysis](https://docs.sonarsource.com/sonarqube-server/2026.1/analyzing-source-code/setting-up-the-pull-request-analysis) — "available starting in Developer Edition"
- [sonarqube-community-branch-plugin](https://github.com/mc1arke/sonarqube-community-branch-plugin) — unsupported third-party workaround
- [Secrets — SonarQube Community Build](https://docs.sonarsource.com/sonarqube-community-build/analyzing-source-code/languages/secrets) — included; no custom patterns
- [Advanced Security / SCA](https://docs.sonarsource.com/sonarqube-server/advanced-security/analyzing-projects-for-dependencies) — paid add-on from Enterprise Edition
- [Release cycle model](https://docs.sonarsource.com/sonarqube-server/server-update-and-maintenance/update/release-cycle-model) — Community Build monthly, no LTA, no backports
- [Installing the database](https://docs.sonarsource.com/sonarqube-community-build/setup-and-upgrade/pre-installation-steps/installing-the-database) — H2 not for production; 4 GB minimum; JDK 21/25
- [SonarJS rule mapping README](https://github.com/SonarSource/SonarJS/blob/master/packages/analysis/src/jsts/rules/README.md) — external + decorated rule tables
- [SonarQube Cloud subscription plans](https://docs.sonarsource.com/sonarqube-cloud/administering-sonarcloud/managing-subscription/subscription-plans) — Free plan: private projects up to 50k LOC, no custom quality profiles
- [Sonar licensing](https://www.sonarsource.com/license/) and [SSALv1](https://www.sonarsource.com/license/ssal/) — analyzers under SSALv1 since 29 Nov 2024
- [Cannot enable CodeQL in a private repository](https://docs.github.com/en/code-security/code-scanning/troubleshooting-code-scanning/cannot-enable-codeql-in-a-private-repository) — private repos need a paid licence
- [SonarScanner for .NET](https://docs.sonarsource.com/sonarqube-server/analyzing-source-code/scanners/dotnet/introduction) — requires server URL, token, and `begin`/`end` around the build
- [sonar-dotnet issues.md](https://github.com/SonarSource/sonar-dotnet/blob/master/docs/issues.md) — `SonarAnalyzer.Security` (taint) rules absent from the NuGet package

