# maxi-quality

> **Status:** TypeScript, C#, Python and Rust shipped and verified. Java
> deliberately not built until a project needs it. Current state and every
> measurement:
> [STATUS.md](STATUS.md)
> **Repo:** `maximalcode/maxi-quality` — public (CLAUDE.md §2)
> **Adopting:** [ADOPTION.md](ADOPTION.md) · **Looking something up:** [REFERENCE.md](REFERENCE.md)
> **Identity:** all commits as `maximalcode` (see §2)
> **`#NN`:** provenance from the private pre-publication tracker. Not this
> repo's issue numbers, which start fresh at #1.
> **Planned work** lives in the issue tracker, not in this document.

A personal, reusable static-analysis baseline that makes every current and future
project (TypeScript, C#/.NET, Python, Rust) professional by default — free tools only,
one-time setup, stamped onto new repos in minutes.

**On CodeQL — measured 2026-08-02, and it is not wired in.** Publishing this
repo made CodeQL free *for this repo*, which was a reason to measure it, not to
adopt it. Measured: 1 of 8 planted TypeScript findings, 2 of 19 Python, 4 of 30
C#, and 0 false positives on the clean fixtures. It is in a class of its own on
one thing — interprocedural taint tracking, 4 of 4 on probes where this
baseline's pattern rules score 0 of 4. None of that is available downstream:
free code scanning is public-repos-only on Free/Pro plans, and the CodeQL CLI
licence separately forbids use on a non-open-source codebase. **Every consumer
of this baseline is private, so CodeQL can only ever be a self-check here.**
Full numbers in [EVAL-vs-oss-tools.md](EVAL-vs-oss-tools.md).

---

## 1. Goals & non-goals

### Goals

| # | Goal |
|---|---|
| G1 | One repo holds all lint/analysis config + custom rules; projects **consume** it, never copy-paste-drift it. |
| G2 | New project onboarding ≤ 10 minutes: copy 2–3 small files, done. |
| G3 | Two layers everywhere (see §4/§5). |
| G4 | Runs both locally (fast, pre-commit) and in CI (gate, reusable workflow). |
| G5 | 100% free: OSS tools + GitHub Actions free tier, no paid SaaS. (Originally "optional self-hosted SonarQube CE" — dropped, §6.) |

**G3 in detail:**
- *Layer 1 (deep, per language):* compiler-integrated analyzers — best signal.
- *Layer 2 (broad, cross-language):* Semgrep with **my own rules**, plus secrets
  + dependency scanning. Same bar for every repo regardless of stack.

### Non-goals

- No paid tools, no per-repo SaaS onboarding (SonarCloud etc. optional later).
- Not a monorepo of my projects — only the quality tooling lives here.
- No auto-fix bots, no AI review pipeline (separate idea; Semgrep rules stay
  deterministic).
- No chasing 100% rule coverage on day one — start strict-but-adoptable,
  ratchet up.

---

## 2. Identity rail (hard rule, same as Consumer A)

Everything in this repo is authored as the **maximalcode** GitHub user — never
the personal/global identity.

**First command after `git init`, before any commit:**

```bash
git config user.name maximalcode
git config user.email 213183497+maximalcode@users.noreply.github.com
```

Repo-local (`git config`, no `--global`) so other repos are unaffected.

**Verify before the first commit of every session:**
`git config user.name` must print `maximalcode` — if not, STOP and fix.

**gh CLI:** `gh auth status` must show the repo is created/pushed via the
maximalcode account. With multiple accounts, run `gh auth switch -u maximalcode`
before `gh repo create`.

Put this same rule into the new repo's own `CLAUDE.md` so any AI session working
there enforces it. State it as a hard stop — "missing or wrong identity ⇒ STOP"
— not as a preference.

**Set-and-forget alternative** — global conditional include:

```ini
# ~/.gitconfig
[includeIf "gitdir:~/path/to/maxi-quality/"]
    path = ~/.gitconfig-maximalcode
```


```ini
# ~/.gitconfig-maximalcode
[user]
    name = maximalcode
    email = 213183497+maximalcode@users.noreply.github.com
```

Works per parent folder too (e.g. `gitdir:~/maximalcode/**`) if all such
projects live under one directory.

---

## 3. Repo layout

```
maxi-quality/
├── README.md                     # what this is, what it costs, is it real
├── CLAUDE.md                     # identity rail + repo conventions
├── .maxi-quality.yml             # this repo's own policy — it is a consumer of
│                                 #   itself, and this keeps samples/policy out
│                                 #   of its rule manifest
├── docs/                         # ADOPTION (how), REFERENCE (every input and
│                                 #   rule id), CONCEPT (design, this file),
│                                 #   STATUS (state + gotchas), EVAL-* (measured
│                                 #   comparisons)
├── examples/                     # copyable consumer repos, one per shape;
│                                 #   CI asserts each scans clean and resolves
├── configs/
│   ├── editorconfig              # shared .editorconfig (all languages)
│   ├── typescript/
│   │   ├── eslint.config.mjs     # typescript-eslint strict-type-checked base
│   │   ├── prettier.config.mjs   # the formatter (§4a) — printWidth 100 to match
│   │   │                         #   editorconfig, single quotes to match the tree
│   │   └── tsconfig.strict.json  # "extends"-able strict compiler options
│   ├── dotnet/
│   │   ├── Directory.Build.props # AnalysisLevel, WarningsAsErrors, analyzers
│   │   └── dotnet.editorconfig   # C# style + severity overrides
│   └── python/
│       ├── ruff.toml             # 13 rule families, extend-able
│       └── mypy.ini              # mypy strict (a COPY — mypy has no extend)
├── semgrep/
│   ├── general/                  # cross-language: no TODO-without-issue,
│   │                             #   no printf-debugging, no broad
│   │                             #   catch-and-swallow, …
│   ├── security/                 # raw SQL concat, command injection sinks,
│   │                             #   hardcoded secret patterns, weak crypto
│   └── conventions/              # MY rules, per stack — e.g. "service mutation
│                                 #   methods must call Authz", "no
│                                 #   PERMISSION_DENIED for invisible resources"
│                                 #   (from Consumer A rails)
├── actions/                      # composite actions — how the rules reach a
│   ├── layer2/                   #   consumer. They resolve through GitHub's own
│   ├── report-issue/             #   action download, so a consumer needs no PAT
│   └── coverage/                 #   and no checkout of this repo
├── .github/
│   └── workflows/
│       ├── quality.yml           # REUSABLE gate (on: workflow_call)
│       └── quality-report.yml    # REUSABLE standing report (§11)
├── samples/                      # intentionally-bad code per language;
│                                 #   doubles as the baseline's own test suite.
│                                 #   format/, semgrep/ and policy/ are kept
│                                 #   apart so one subsystem's fixtures cannot
│                                 #   move another's expected counts
└── scripts/
    ├── adopt.sh                  # bootstrap a repo: detect languages, copy stubs
    ├── check-pins.sh             # bump policy: pin consistency + upstream drift
    ├── coverage.py               # coverage ratchet (§12) — lcov + Cobertura
    ├── policy.py                 # resolve a consumer's .maxi-quality.yml (§13)
    ├── quality-report.py         # renders the standing report body (§11)
    └── scan.sh                   # run full Layer 2 locally (semgrep+gitleaks+osv)
```

---

## 4. Layer 1 — per-language config (consumed, not copied)

| Language | Tooling | How a project consumes it |
|---|---|---|
| **TypeScript** | typescript-eslint `strict-type-checked` (+ `stylistic`) + `eslint-plugin-sonarjs`; Prettier for layout (§4a) | `eslint.base.mjs` + `tsconfig.base.json` are copied in at adopt time, like the .NET props — a git devDep cannot npm-install in a consumer's CI. The project's own `eslint.config.mjs` stays ~3 lines |
| **C#/.NET** | built-in Roslyn `latest-recommended`, `SonarAnalyzer.CSharp`, `Roslynator.Analyzers`, `TreatWarningsAsErrors` | copy `Directory.Build.props` — .NET has no remote-extends; this is the one accepted copy (small, rarely changes) |
| **Java** — *not built* | Error Prone (+ NullAway), SpotBugs; Checkstyle only for style | **Nothing exists in `configs/java/` and nothing will until a real project needs it** (§9). This row is the plan, not a shipped config. |
| **Python** | Ruff, 13 families (`E W F I B C4 UP N SIM ASYNC S T20 RUF`) + mypy `strict` | `ruff.toml` supports `extend = <path>` — but use the `extend-` forms of `select`/`per-file-ignores`, the bare ones REPLACE. mypy has no extend: `mypy.ini` is a copy |
| **Rust** | clippy `all` + `pedantic` + curated nursery/cargo picks, `unsafe_code = "forbid"`, `-Dwarnings` in CI only; cargo-deny for RustSec advisories + duplicate versions (#58) | the C# pattern, by necessity: Cargo cannot consume `[lints]` remotely, so adopt.sh appends the block to the consumer's own `Cargo.toml` (marker-guarded) and copies `rustfmt.toml` + `deny.toml`. Semgrep's Rust support is experimental — clippy IS the conventions layer |

**Principle:** compiler-adjacent analyzers do the bug-finding; style stays
minimal. Formatting is autofixed, never argued about.

### 4a. Formatting

This section used to promise "Prettier/Biome / `dotnet format` /
google-java-format / Ruff-format" and the tree shipped one of the four, gating
nothing (#42). What ships now:

| Language | Formatter | Config | Gated by |
|---|---|---|---|
| **TypeScript** | Prettier | `configs/typescript/prettier.config.mjs` | `npm run verify:format` |
| **Python** | `ruff format` | the `[format]` section of `configs/python/ruff.toml` | `ruff format --check` |
| **C#/.NET** | `dotnet format whitespace` | `configs/editorconfig` | `dotnet format whitespace --verify-no-changes` |
| **Rust** | `cargo fmt` | `configs/rust/rustfmt.toml` — stable options only, `newline_style = "Unix"` the one non-default | `cargo fmt --check` |
| **Java** | — | — | nothing, and nothing until a real project needs it (§9) |

Three things this table is careful about, each of which was measured rather
than assumed:

- **`dotnet format whitespace`, not bare `dotnet format`.** The bare form runs
  Code Style analysis and every analyzer reference — 622 of them on a sample
  project — so it re-reports the build gate's own diagnostics under the
  formatter's exit code. Two unrelated failures behind one red check.
- **Biome is not a second option.** Offering two formatters for one language
  means two possible layouts for the same file, which is the argument the
  section claims to end. Prettier, because every file already conformed to it.
- **Java is out of the table, not pending in it.** Same rule as the Layer 1 row
  above: no consuming project, no config.

Adopting cost nothing here — measured 2026-08-05, all three formatters
reformat **zero** files in this repo, so the gate started green and only ever
fires on future drift. Each config is proven by a fixture in `samples/format/`
that is correct under *our* settings and wrong under the *tool's defaults*, so
deleting a config turns a check red instead of leaving it quietly true.

---

## 5. Layer 2 — cross-language umbrella (identical for every repo)

Runs locally via `scripts/scan.sh` and in CI via the reusable workflow:

1. **Semgrep OSS** with the `semgrep/` rules from this repo, pinned by git ref.
   This is the selfmade part — every convention I care about becomes a 10-line
   YAML rule once, then applies to every project forever.
2. **Gitleaks** — secrets in the diff and history.
3. **OSV-Scanner** — known-vulnerable dependencies (npm, NuGet, Maven, pip via
   lockfiles). It also produces the **CycloneDX SBOM** and the optional
   **licence-allowlist gate** — same binary, same pin, no fourth tool.

The licence gate ships with **no default allowlist**. Measured against this
repo's own tree, a plausible one flags `SonarAnalyzer.CSharp` and
`typing-extensions` as *non-standard* and `pathspec` as MPL-2.0. A policy nobody
chose is a policy everybody disables; the inventory in §11 is on by default
instead, and the gate turns on when a repo has an actual policy.

---

## 6. ~~Optional Layer 2b — SonarQube CE dashboard~~ — DROPPED

Measured against this baseline and lost: 1 of 8 planted TypeScript bugs caught
out of the box, no rule id at all for `no-floating-promises` or the
`no-unsafe-*` family, and custom C#/TS rules unavailable in every Sonar edition.
The C# analyzer value is already banked in-build through `SonarAnalyzer.CSharp`.

The old rule was "worth it once ≥3 active projects consume the baseline" — that
trigger is **void**. Reaching three consumers is not a reason to build it; only
new evidence would be. Full measurement in
[`EVAL-vs-sonarqube.md`](EVAL-vs-sonarqube.md).

---

## 7. The reusable CI workflow

`quality.yml` lives in this repo with `on: workflow_call` and inputs like
`languages: "ts,dotnet"` (or auto-detect by lockfiles). A consuming repo adds
exactly this:

```yaml
# .github/workflows/quality.yml — in each project, this is ALL of it
name: quality
on: [push, pull_request]
jobs:
  quality:
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1
```

Jobs inside: per-language lint/build-with-analyzers, then semgrep + gitleaks +
osv-scanner. Failing rule = failing check.

Version the baseline with tags (`@v1`) so an updated ruleset never breaks old
projects silently — projects upgrade by bumping the tag.

---

## 8. Adoption paths

**New project:**
`"$BASELINE"/scripts/adopt.sh <repo-path>` — detects languages, drops the
stub workflow plus the 1–3 consume-files, prints what it did.

**Existing project (e.g. Consumer A):**
Adopt in *new-code-only* mode first — Semgrep on changed files, warnings-not-errors
for one week, then flip to error. Never big-bang-fix 500 legacy warnings; use
per-file suppressions with a linked issue.

---

## 9. What gets built next

Layers 1 and 2, the reusable workflow, `adopt.sh` and the three shipped
languages exist today; §2–§8 describe what they do. What is *not* built yet, and
why, lives in the issue tracker rather than here — a plan in a document is a
task list nobody closes.

The one rule that governs what gets added: **a config for a language with no
real consuming project is dead weight.** It gets written the day a project needs
it, not before.

---

## 10. Success criteria

- A brand-new TS or C# repo goes from `git init` to failing-CI-on-a-planted-bug
  in under 10 minutes, using only this repo's README.
- The same Semgrep convention rule fires in both a TS and a C# sample.
- Consumer A runs the baseline in CI without weakening any existing gate.
- Zero spend: OSS tools + GitHub Actions free tier only.

---

## 11. The standing report — memory, not gating

A gate has no memory. `quality.yml` answers *is this PR clean?*, and on a repo
adopted with `--changed-only` it says nothing about the backlog it grandfathered.
That was the one thing SonarQube did better (`docs/EVAL-vs-sonarqube.md` — it
lost on detection, not on memory).

**The database is a GitHub issue.** One per repo, updated in place forever,
holding the current Semgrep breakdown, the dependency/licence inventory from the
SBOM, and a history table that grows a row per run. No server, no cloud — code
scanning would be the better store but needs Advanced Security on a private
personal-account repo, which is the paid path.

Constraints that are not negotiable here:

- **One issue, never one per run.** A weekly bot that opens issues becomes noise,
  noise gets muted, and a muted report is worse than none.
- **The report never fails a build.** Failing on findings is the gate's job.
- **A parse failure must not wipe history.** The body IS the persistence layer.
- **The workflow outputs the issue number**, so a caller can assert the report
  landed. Without that, a broken report path and a clean repo look identical —
  which is how it shipped broken once (#46).

---

## 12. Coverage — a ratchet, not a threshold

A fixed threshold on an existing repo either sits below where you already are
(gating nothing) or above it (every PR red until someone does a coverage sprint).
Both end with the number ignored. The ratchet asks the only always-answerable
question: *did this change make it worse?*

- The floor is a **committed file** in the consuming repo. Not a cache (evicted
  after 7 days — a ratchet that forgets is a threshold of zero), not a repository
  variable (the default token cannot write one), not the report issue (a fork PR
  cannot read-modify-write it and two PRs would race).
- **Line coverage only.** Branch coverage is reported inconsistently across
  producers; a ratchet built on a number two tools disagree about fires on tool
  upgrades instead of on regressions.
- **The consumer runs its own tests.** This baseline cannot drive a suite that
  needs services and a database, and guessing a "standard" test command produces
  a gate that is skipped or wrong. It owns the remembering, not the running.
- **Raising the floor is the consumer's commit.** The action rewrites the file;
  committing to someone's default branch is a permission this baseline does not
  take on their behalf.
- A broken coverage run, a missing report and an unparseable floor are all
  **errors**, never passes. Each one otherwise turns the ratchet permanently
  green, which is the shape of every gate bug this repo has actually hit.

---

## 13. The policy file — configurable, but not negotiable

Layer 2 shipped as take-it-or-leave-it. The design intent was that one identical
umbrella covers every repo regardless of stack (§5), and that is still right —
but it left a consumer exactly two ways to say *"that rule does not apply to
us"*: a per-finding `nosemgrep` comment, and deleting the workflow file. The
second one is what actually happens, and a deleted gate is worse than a
configurable one.

So `.maxi-quality.yml` in the **consumer** selects rule groups, disables a rule,
downgrades one to a warning, excludes paths, and points at the consumer's own
rules. It is optional; with no policy file nothing changes.

The constraints are the design, not the schema:

- **Unknown keys, rule ids and group names are hard errors.** Every silent-knob
  bug this repo has shipped had one shape — Ruff's bare `select` replacing what
  it inherits, `pattern-not-regex` ignored a level too high,
  `dotnet_diagnostic.IDE1006.severity` never set — and all three looked identical
  to a working config from outside. A policy that cannot be applied stops the run
  rather than applying half of itself.
- **The mechanism is verified, not trusted.** `--exclude-rule` and `--exclude`
  both fail silently when given a form semgrep does not recognise, so the
  resolver asserts *after* the scan that disabled rules really are absent and
  excluded paths really are unreported. A knob that did not take is a failure,
  not a partial policy.
- **The resolved policy is snapshotted**, not the file. Same division of labour
  as `configs/*/…snapshot.json`: what it says has been wrong before, what it
  resolves to is the thing worth asserting.
- **Secrets and vulnerable dependencies are not configurable.** Gitleaks and
  OSV-Scanner have no `disable`, and there is no key that makes the gate
  advisory. `--no-fail` exists for the standing report (§11) and only for that.

What this does *not* relax: the ruleset is still capped at 12 conventions, and a
consumer narrowing what applies to them is not the same as the baseline growing.
