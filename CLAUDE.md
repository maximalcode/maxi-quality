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

**One correction to a claim this file used to make.** It said the free Semgrep
registry "ships no C# rules". That is true of **`p/security-audit` specifically**
— scanning a tree with three C# files, its language table shows no `csharp` row
at all — and false of the registry as a whole: `p/owasp-top-ten` runs 27 C#
rules and `p/csharp` is a 27-rule C# pack (`EVAL-vs-oss-tools.md` §2d). Neither
changes the verdict, and both are worth stating correctly, because a wrong
reason for a right decision is how the decision gets overturned later.

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
  branches carry the same 20 required checks, admins included.
- **Tags gate the consumers.** Projects pin the baseline by tag (`@v1`), so an
  updated ruleset never silently breaks an old project. Do not tag until the
  step that the tag represents is actually verified working. The immutable
  `v1.0.x` tags are cut by hand, one per release worth naming; only `v1` moves
  on its own.
- **`samples/` is the test suite.** Every config in `configs/` must be proven by
  an intentionally-bad sample that fails. If a sample stops failing, the config
  regressed — fix the config, do not weaken the sample.

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
