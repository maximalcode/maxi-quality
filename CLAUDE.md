# CLAUDE.md — maxi-quality

Instructions for any AI session working in this repo. Read this before touching
anything.

---

## 1. Identity rail (hard rule)

Every commit in this repo is authored as the **maximalcode** GitHub user — never
the personal/global identity.

**Before the first commit of every session, verify:**

```bash
git config user.name
```

It MUST print `maximalcode`. If it prints anything else, or nothing at all:
**STOP.** Do not commit. Fix it first:

```bash
git config user.name maximalcode
git config user.email 213183497+maximalcode@users.noreply.github.com
```

Repo-local only — never `--global`, so other repos stay untouched.

**gh CLI:** `gh auth status` must show `maximalcode` as the active account before
any `gh` operation that writes (push, PR, release). With multiple accounts:

```bash
gh auth switch -u maximalcode
```

Missing or wrong identity ⇒ **STOP**, tell the user, do not work around it.

---

## 2. This repo is PUBLIC — the consumers are not

Decided 2026-08-01, reversing the previous "private forever" rule. Publishing
was done as a **fresh repo, not a visibility flip**, because the old repo's
history and issue tracker could not be published: 18 commit messages, 73 commit
trees, 16 PR bodies and 9 issues named the real consuming repos. Anonymising
`docs/` had only cleaned the tip.

**That happened twice, and the second time is the lesson.** The first fresh repo
dropped the history but was squashed from the un-anonymised tip, so the *tree*
still carried 95 consumer-identifying references: file-and-line locations of
analyzer findings, class and method names, verbatim quotes from their source,
one consumer's PR number, and a table that de-anonymised the pseudonym scheme
outright. Caught 2026-08-02, before the visibility flip. Three properties
made that repo unpublishable rather than merely wrong, and all three are worth
remembering because each defeats the obvious fix:

- a visibility flip publishes **every commit**, not the tip — so a cleanup
  commit on top removes nothing;
- `refs/pull/N/head` is permanent server-side and survives a force-push — so
  rewriting `main` does not reach it;
- a PR whose diff *removes* the identifiers publishes them on its removed side,
  and GitHub keeps PR diffs forever.

So the order is fixed: **anonymise the tree first, then publish it as a single
commit.** A cleanup PR against an already-pushed repo is not a fix, it is a
second copy.

**Know which repo you are in.**

| Repo | What it is |
|---|---|
| `maximalcode/maxi-quality` | **public, and where all work happens.** Branch, PR, merge here. |
| `maximalcode/maxi-quality-dev` | **private, read-only archive** of the original history and tracker. Do not commit to it, and never push any of it here. |
| the first publication attempt | **private, read-only.** Same rule. Its tree was never anonymised, so it is the one thing that must never be made public or merged from. |

**Visibility is the owner's to flip, never yours.** Do not run
`gh repo edit --visibility ...` in either direction, and do not create a repo
that republishes this one. Going public is effectively irreversible — clones,
forks and caches outlive the setting.

**Nothing about the consuming repos goes in this repo.** They stay private, and
this repo is a public description of a baseline, not a public audit of them.
This rule is now load-bearing rather than aspirational: every commit message,
PR body and issue you write here is public the moment it is pushed, and editing
it afterwards does not remove it — GitHub keeps an edit history any reader can
open, and a renamed issue shows the old title in its timeline. **Get it right
the first time; there is no cleanup pass.**

Measurements are recorded against pseudonyms:

| Pseudonym | What it is |
|---|---|
| **Consumer A** | a private C# + TypeScript monorepo |
| **Consumer B** | a private TypeScript application |
| **Consumer C** | a private Python service |

Never reintroduce the real names, their issue numbers, or file paths from them.
Keep the numbers — measured evidence is the point of `docs/STATUS.md` and it
identifies nobody once the names are gone.

**Public-only tooling is now permitted, but only after it is measured.** Free
CodeQL and SonarCloud become available; that is not a reason to adopt either.
Anything new gets run against `samples/` and reported with numbers before it is
wired in.

The track record says the rule works, and it works **in both directions** — do
not read it as "nothing ever passes", which would just be reflexive rejection
wearing the costume of rigour:

- `p/security-audit` found **0 of the 28** findings our own conventions produced
  on the same files (`docs/STATUS.md` §7, 2026-08-01), and **0 of 103** on the
  bigger corpus a year's worth of fixtures later
  (`docs/EVAL-vs-oss-tools.md` §2d).
- SonarQube found **1 of 8** (`docs/EVAL-vs-sonarqube.md`).
- CodeQL scored well and is still declined — it cannot run on a private repo at
  any free tier, so it could gate this repo and never a consumer
  (`EVAL-vs-oss-tools.md` §2h, issue #23). That asymmetry decides more of this
  than detection scores do.
- **`eslint-plugin-sonarjs` was measured and ADOPTED** (#11) — five bug classes
  typescript-eslint has no rule for, zero findings on the clean fixtures. Nine
  of ten candidates were declined; one was not.
- **`diff-cover` tied on detection and was still not adopted as a dependency**
  (#123, `docs/EVAL-vs-diff-cover.md`). It agrees with `scripts/coverage.py`
  line for line on `samples/coverage/patch`, and lost on what it costs to hold:
  six packages and a PyPI install on every consumer's gate, and it cannot read
  lcov and Cobertura in one run — which is the shape of Consumer A. It stays as
  the cross-check CI runs against our own number. A tie on detection is decided
  by cost, not by preference for our own code.

**One correction to a claim this file used to make.** It said the free Semgrep
registry "ships no C# rules". That is true of **`p/security-audit` specifically**
— scanning a tree with three C# files, its language table shows no `csharp` row
at all — and false of the registry as a whole: `p/owasp-top-ten` runs 27 C#
rules and `p/csharp` is a 27-rule C# pack (`EVAL-vs-oss-tools.md` §2d). Neither
changes the verdict, and both are worth stating correctly, because a wrong
reason for a right decision is how the decision gets overturned later.

**Infrastructure artifacts follow the same rule as consumer identity.** The
presentation-layer eval commits compose and scanner config so the run is
reproducible. Those artifacts carry **placeholder hosts and no credentials**,
runs are against `samples/` only, and no consumer repo is scanned, connected or
named. The deployment itself — real hostnames, tokens, which repos are wired,
backup and restore — is **not published here**. The recipe is public; the
deployment is not. §2 has always covered *who the consumers are*; this covers
*where the analysis runs*, which the pseudonym rules do not reach.

**Free/OSS only still holds.** Public makes branch protection free, which is the
one thing that was genuinely blocked on spend. It does not relax §5.

---

## 3. Source of truth

[`docs/CONCEPT.md`](docs/CONCEPT.md) is the source of truth for what this repo
is, what it contains, and the order things get built in. When in doubt, read it
rather than inventing structure. Keep it in sync if the design genuinely changes;
do not silently diverge from it.

---

## 4. Scope discipline

Shipped and verified: **TypeScript, C#/.NET, Python, Rust and Java.**

Already shipped, do not re-litigate: `quality.yml` + the `layer2` composite
action, `adopt.sh` and `check-pins.sh`, the
dependency bump policy (#13), clean fixtures for all four languages,
`configs/python/` (Ruff + mypy, measured against Consumer C before shipping),
and `configs/rust/` (clippy pedantic + rustfmt + cargo-deny, #58 — the C#
copy pattern, because Cargo cannot consume `[lints]` remotely; Semgrep Rust
rules stay out while upstream support is experimental, and cargo-audit stays
out because cargo-deny's advisories check is the same feed).

**On the Python ruleset specifically:** it is Consumer C's own thirteen families,
not a set invented here. Issue #15 originally proposed `E,F,B,UP,SIM,S`, which
is a strict *subset* — writing that would have downgraded the only consuming
project. If a future session is tempted to trim it, that is the trap. Measure
against Consumer C before narrowing anything.

**Java shipped 2026-08-09 (#10), Maven only.** Error Prone + NullAway at ERROR
+ Spotless/palantir in AOSP style, delivered as a marker-delimited managed
region in the consumer's own `pom.xml` (Maven has no remote lint consumption and
XML has no append, so `scripts/pom-region.py` is the upgrade path). SpotBugs, PMD
and Checkstyle were measured and DECLINED — `EVAL-vs-oss-tools.md` §2p. **Gradle
is not built**: it gets written the day a Gradle consumer exists, and until then
detection fails loud rather than skipping.

Two things about it that are easy to lose. First, `-Werror` and Error Prone do
not compose in one javac invocation — a lint warning suppresses the whole
analyzer pass — and `samples/java-lint` pins that from both sides; do not
"simplify" it away. Second, the adoption cost was **never measured against
Consumer D**, only against a representative fixture built here, and STATUS §5
says so explicitly. Do not quietly fill that cell with a fixture number.

The rule that governs this has not changed: speculative configs for languages
with no real consuming project are dead weight. They get written the day a real
project needs them, not before. Python and Java clear that bar; Gradle does not
yet.

**"A real consuming project" is three tests, not one**, and they are named in
[`CONTEXT.md`](CONTEXT.md): **detection proof** (does it fire on the bugs it
claims?), **adoption-cost proof** (is switching it on survivable?), and
**in-house demand** (is this language written in a repo the owner maintains?).
Cite the one you mean. The fused phrase is how Java came to ship with its
adoption cost unmeasured while the rule as written said it should not have —
which was the right call and the wrong wording, and a wrong wording is how a
right call gets overturned later.

Only in-house demand admits a language. A fixture corpus proves detection and
can never prove demand, so **nothing is added because an outsider asks for it** —
see [ADR 0001](docs/adr/0001-public-adoptable-no-support-obligation.md) and
`docs/CONCEPT.md` §1a.

**SonarQube CE is DROPPED, not parked**, and the "≥3 consuming repos" trigger is
void — repo count is not evidence. It was measured in
`docs/EVAL-vs-sonarqube.md` and lost. Only new measured evidence reopens it; the
issue tracker holds the standing answer so this does not get re-litigated here.

**Planned work belongs in the issue tracker, never in the docs.** A roadmap in a
document is a task list nobody closes. This repo shipped two of them before
they were removed — one a "Next action" list, one a set of proposed changes
still marked "awaiting go-ahead" for work that had shipped days earlier. If it
is something to do, open an issue.

The second scope trap is rule-writing: it is infinitely expandable and feels
productive. The Semgrep ruleset is capped at **12 conventions, hard** — that
budget is now **fully spent** (see the inventory in README.md).

Adding a 13th convention requires removing one, or an explicit decision from the
user to raise the cap. A new rule is justified by *a real bug that slipped
through*, never by "this would be nice to catch".

Note the distinction: 12 **conventions**, currently 40 **rule ids**. Semgrep
patterns are language-specific, so one convention needs a separate id per
language when the syntax differs. Splitting an existing convention into a
per-language id is not new scope; inventing a new convention is.

---

## 5. Conventions

- **Free/OSS tools only.** No paid SaaS, no license-gated features. Zero spend
  is a success criterion, not a preference.
- **Conventional commits** (`feat:`, `chore:`, `docs:`, `fix:`), one logical
  commit per unit of work.
- **Branch off `develop`, PR into `develop`.** `develop` is the default branch
  and where all work lands. `main` is the RELEASE branch: `release-tag.yml`
  moves `v1` on a green push to it, so a merge to `main` is not a checkpoint —
  it ships to every consumer pinning `@v1`. Promoting `develop` to `main` is
  the user's decision, not yours; do not open or merge that PR unasked. Both
  branches carry the same 28 required checks, admins included — one per
  context `ci.yml` produces, and that equality is the point. A job that runs but
  is not on the required list reports and blocks nothing, which is
  indistinguishable from a passing gate in the PR UI. This drifted twice:
  `layer1-rust`, `layer1-java`, `policy` and `examples` shipped without being
  added, so the two newest languages could not fail a merge; then
  `patch-coverage` and `coverage-input` did the same, so the coverage gate this
  repo had just built could not fail one either. **Adding a job to `ci.yml` is
  not done until it is a required context on both branches.**

  Count **contexts, not jobs** — `layer2` is a two-leg matrix, so the job count
  and the context count differ by one, and "one per job" was the wording that
  hid that before anything drifted.
  `workflow-lint` asserts that this number matches `ci.yml`; it cannot read the
  protection API (that needs admin rights a read-only CI token does not have),
  so the number here is the tripwire and setting the contexts is still a
  deliberate act.
- **`main` does not require branches to be up to date; `develop` does.** The
  asymmetry is deliberate, and #89 is why. Promoting `develop` to `main`
  creates a merge commit **on `main`** that `develop` never receives, so every
  release leaves `develop` one commit further behind. With the up-to-date
  requirement on, the next promotion is then unmergeable no matter how green it
  is — and GitHub reports that as `BLOCKED`, the same word it uses for a
  failing check or a missing review, so the symptom points nowhere near the
  cause. It reached three commits, and #87 sat fully green and unmergeable
  until someone queried the compare API by hand.

  **Every required context stays required on both branches.** The only thing
  dropped is the up-to-date requirement, and only on `main`.

  Two alternatives were rejected, and both reasons are worth keeping.
  Automating the back-merge needs the PR opened by something other than
  `GITHUB_TOKEN` — GitHub creates no workflow runs for events that token
  triggers, so `ci` would never run on the PR and its required contexts would
  never report. That is the same deadlock, permanent instead of clearable, and
  the only fix for it is a stored PAT with `pull-requests: write`: a long-lived
  credential bought to save one merge per release, in the repo whose release
  workflow declines a checkout `ref:` over exactly this kind of blast radius.
  A fast-forward-only promotion was the other, and GitHub's PR UI has no
  fast-forward merge.

  **So `develop` sitting a few commits behind `main` is expected, and those
  commits are empty.** The promotion merges carried `develop`'s own tree into
  `main`; only the merge commit itself is missing. Back-merging before a
  release is optional tidying, never a gate, and never a step anything waits
  on.

  What this gives up: a commit that lands on `main` and not on `develop` can be
  reverted by the next promotion, because nothing forces that promotion to have
  seen it. That is a reason not to commit to `main` directly — which this file
  already says — and not a reason to turn the requirement back on.
- **Tags gate the consumers.** Projects pin the baseline by tag (`@v1`), so an
  updated ruleset never silently breaks an old project. Do not tag until the
  step that the tag represents is actually verified working. The immutable
  `v1.0.x` tags are cut by hand, one per release worth naming; only `v1` moves
  on its own.
- **`samples/` is the test suite.** Every config in `configs/` must be proven by
  an intentionally-bad sample that fails. If a sample stops failing, the config
  regressed — fix the config, do not weaken the sample.

  **Two documented exceptions, and they are the only two.** Both are the same
  shape — a config whose enforcement lives inside a program this repo cannot
  drive headlessly, so no sample can fail without it — which is exactly the
  shape this rule exists to catch. Neither is granted; both are paid for the
  same way, and the price is a checker that asserts internal consistency plus a
  README section stating what evidence each claim does and does not rest on:

  - **`configs/editor/`.** A `.vscode/settings.json` cannot be exercised here,
    because there is no headless VS Code. `scripts/check-editor-contract.py` is
    the checker; `configs/editor/README.md` §1 is the statement.
  - **The `permissions.deny` array in `configs/agent/settings.json`** (#161). A
    deny rule is enforced by Claude Code before any hook is consulted, and there
    is no way to make one fire from a fixture. `selftest.py`'s `permissions`
    mode is the checker; `configs/agent/README.md` §5 is the statement, and §5a
    adds one dated live observation, because a structurally consistent rule that
    is not actually enforced still protects nothing.

  Do not read either as a precedent — a new config that could have a sample and
  does not is still a violation.

  Read both exemptions narrowly, because the wording is what a later session
  will act on. The first covers **what the settings do inside an editor**, and
  nothing else: since #126 the *composition* of those fragments into a
  consumer's `.vscode/` files is ordinary behaviour with ordinary end-to-end
  assertions in the `adopt` job, and `configs/editor/` is no longer a directory
  nothing runs. The second covers **the two deny strings and nothing around
  them**: the hooks in the same file are executables, and
  `samples/agent-guard/` runs every one of them as a subprocess on a real
  payload.

---

## Agent skills

Per-repo configuration for the engineering skills. These files are what the
skills read; keep them in sync if the answers change.

### Issue tracker

GitHub Issues on `maximalcode/maxi-quality`, via the `gh` CLI. **The tracker is
public and permanent** — §2's naming rules apply to every issue title, body and
comment. See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Triage labels

The five canonical roles, each label string equal to its name (`needs-triage`,
`needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See
[`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Domain docs

Single-context — `CONTEXT.md` + `docs/adr/` at the repo root, with
`docs/CONCEPT.md` remaining the source of truth (§3). See
[`docs/agents/domain.md`](docs/agents/domain.md).
