# maxi-quality

A reusable static-analysis baseline. One repo holds the lint/analyzer config and
the custom rules; your projects **consume** it instead of copy-paste-drifting
their own.

Free tools only — OSS analyzers plus the GitHub Actions free tier. Zero spend is
a requirement, not a preference.

```bash
git clone https://github.com/maximalcode/maxi-quality.git
./maxi-quality/scripts/adopt.sh <your-repo> --dry-run   # look first
./maxi-quality/scripts/adopt.sh <your-repo>
```

That detects your languages, writes the handful of files that cannot be consumed
remotely, and scaffolds the CI call. Full walkthrough:
**[`docs/ADOPTION.md`](docs/ADOPTION.md)**. Copyable worked examples:
**[`examples/`](examples/)**.

---

## What you actually get

Two layers that do different jobs. **They are adopted independently, and they
cost wildly different amounts.** Knowing which is which is the whole decision.

| | **Layer 2** — the umbrella | **Layer 1** — the deep pass |
|---|---|---|
| What it is | Semgrep with this repo's 12 conventions, Gitleaks, OSV-Scanner | Your compiler and linter turned up: typescript-eslint `strict-type-checked`, Roslyn + SonarAnalyzer + Roslynator with `TreatWarningsAsErrors`, Ruff + mypy `strict`, clippy `pedantic` with `-Dwarnings` |
| Scope | Identical for every repo, any stack | Per language, only the ones you have |
| Config in your repo | **none** | 2–3 files copied in per language |
| How it runs | one job, no token, no checkout of this repo | your own build and lint step |
| Finds | secrets, vulnerable deps, injection, my own conventions | type holes, floating promises, dead code, un-disposed resources |
| **Can it grandfather your backlog?** | **yes** | **no** |

That last row is the one that decides your week.

### The ratchet asymmetry

Semgrep supports `--baseline-commit`, so Layer 2 can be told *"only fail on code
changed since this ref."* Your entire existing backlog is grandfathered on day one
and the gate still holds the line on everything new.

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
  weekly report written into a GitHub issue.
- **Every number in `docs/` was measured, not estimated.** Where something was
  not measured, it says so.

---

## Status: TypeScript, C#, Python and Rust

| Piece | State |
|---|---|
| Shared `.editorconfig` | ✅ `configs/editorconfig` |
| TypeScript — ESLint + tsconfig | ✅ `configs/typescript/` |
| C#/.NET — Roslyn + Sonar + Roslynator | ✅ `configs/dotnet/` |
| Python — Ruff + mypy strict | ✅ `configs/python/` — 13 rule families |
| Rust — clippy pedantic + rustfmt + cargo-deny | ✅ `configs/rust/` ([#58](https://github.com/maximalcode/maxi-quality/issues/58)) — clippy is the conventions layer (Semgrep's Rust support is experimental and stays out); `unsafe_code` forbidden; toolchain pinned; Layer 2 needed zero changes |
| Formatting — Prettier / `ruff format` / `dotnet format whitespace` | ✅ gated in CI ([#42](https://github.com/maximalcode/maxi-quality/issues/42)). Adopting cost zero reformatted files here; each config has an ablation fixture in `samples/format/` that is correct under our settings and wrong under the tool's defaults |
| Samples proving all three fail | ✅ `samples/` |
| Semgrep ruleset (Layer 2) | ✅ `semgrep/` — 12 conventions, 28 rule ids |
| `scan.sh` (Semgrep + Gitleaks + OSV) | ✅ `scripts/scan.sh` |
| Findings on the PR diff | ✅ on by default ([#40](https://github.com/maximalcode/maxi-quality/issues/40)) — gating findings as `::error`, policy-downgraded ones as `::warning`. Additive: CI asserts a suppressed or malformed annotation cannot change the exit code. SARIF is out for the same reason CodeQL is |
| Opt-in pre-commit hook | ✅ `adopt.sh --hooks` — gitleaks on the staged diff (~50 ms), Semgrep on the staged **content**, not the working tree. Never installed unasked, never blocks on its own problems, `--no-verify` always works |
| Per-repo policy | ✅ `.maxi-quality.yml` — rule groups, `disable`, `warn`, path excludes, your own rules. Unknown keys are hard errors |
| Reusable CI workflow, `@v1` tag | ✅ `.github/workflows/quality.yml` + `actions/layer2/` |
| Coverage ratchet, SBOM, licence gate | ✅ `actions/coverage/`, both from OSV-Scanner |
| Java | ⬜ deliberately not built until a real project needs it ([#10](https://github.com/maximalcode/maxi-quality/issues/10)) |
| SonarQube CE dashboard | ❌ **dropped.** Measured in [`EVAL-vs-sonarqube.md`](docs/EVAL-vs-sonarqube.md) and lost: 1 of 8 planted TS bugs out of the box, no rule id for `no-floating-promises` or the `no-unsafe-*` family, custom C#/TS rules unavailable in every edition |
| The rest of the free field | 🔍 **measured; one adopted of ten.** [`EVAL-vs-oss-tools.md`](docs/EVAL-vs-oss-tools.md) scores SonarJS, Unicorn, `eslint-plugin-security`, Semgrep's registry packs, Bandit, Trivy, Grype, TruffleHog and CodeQL against the 103 planted findings in `samples/`. Only `eslint-plugin-sonarjs` cleared every bar. The rule that decides most of the rest: a tool that is free only *because* a repo is public can gate this repo and never a consumer |

The acceptance test that gated the first tag: a scratch consumer repo, onboarded
from the docs alone, went red in CI on a planted floating promise — with the
`dotnet` job correctly skipping itself and Layer 2 running this repo's rules
without any token in the consumer.

---

## Where to go next

| You want to | Read |
|---|---|
| put this on a repo | [`docs/ADOPTION.md`](docs/ADOPTION.md) |
| copy something that already works | [`examples/`](examples/) |
| look up an input, flag or rule id | [`docs/REFERENCE.md`](docs/REFERENCE.md) |
| know why it is shaped this way | [`docs/CONCEPT.md`](docs/CONCEPT.md) — the source of truth |
| see what is proven, and what it cost | [`docs/STATUS.md`](docs/STATUS.md) |
| check the tool choices against the field | [`docs/EVAL-vs-oss-tools.md`](docs/EVAL-vs-oss-tools.md) · [`docs/EVAL-vs-sonarqube.md`](docs/EVAL-vs-sonarqube.md) |
| change something here | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

Anything still to be built is in the
[issue tracker](https://github.com/maximalcode/maxi-quality/issues), never in
these documents. A roadmap in a document is a task list nobody closes.

---

## Two things to know before you scan this repo

> **The credentials in `samples/semgrep/` are fake and deliberate.** They are bait
> for the `hardcoded-secret-*` rules, and CI asserts those rules fire on them — so
> a secret scanner run against this repo **will** report findings, and that is the
> intended state. Every one is in `samples/`; none was ever valid. Gitleaks needs
> no action (`.gitleaks.toml` path-allowlists that directory and is loaded
> automatically); other scanners should exclude `samples/`. The same goes for
> dependency scanners: `samples/rust/Cargo.lock` deliberately pins a crate with
> a known RustSec advisory as bait for the cargo-deny gate — target-gated so it
> is never built, and asserted by id in CI. Details in
> [`SECURITY.md`](SECURITY.md) and
> [`samples/semgrep/README.md`](samples/semgrep/README.md).

Measurements in `docs/` refer to real private codebases as **Consumer A** (C# +
TypeScript monorepo), **Consumer B** (TypeScript app) and **Consumer C** (Python
service). The numbers are real; the names are not mine to publish. Bare issue
numbers in prose are provenance from the pre-publication tracker, which stayed
private — they are not this repo's issue numbers, which start fresh at #1.

---

## Conventions

Every commit is authored as `maximalcode`; the ruleset is capped at **12
conventions** and the cap is the feature; `samples/` is the test suite and a
sample that stops failing means the config regressed. Those rules, the branching
flow and the verification procedure are in [`CONTRIBUTING.md`](CONTRIBUTING.md)
and [`CLAUDE.md`](CLAUDE.md).

Development history and the original issue tracker live in a separate private
repo. This is the published baseline, not a published audit of anyone's code.
