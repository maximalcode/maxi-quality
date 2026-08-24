# Changelog

What changed between the tags a consumer can pin, and — the part that matters
here — **what can turn a green build red.**

## How to read this

[`README.md`](README.md) states the version contract; this file is the
mitigation that makes it survivable. Two classes, and the line between them is
the whole thing:

- A **Finding change** — a new rule, an analyzer bump, a tightened config — is
  **deliberately not breaking**. It lands on the moving `@v1` tag and it can
  fail a build that passed yesterday. Ratcheting up is the product. Every one
  of them is in a **Rule changes** section below, and that section is the
  entire reason an adopter is allowed to trust `@v1`.
- A **Mechanism change** — an input removed or renamed, a job renamed,
  detection behaviour altered, or anything new you must have in your own
  repository — **is breaking, and gets a new major tag.** There has never been
  one. `v2` gets cut when a Mechanism change actually needs it, and no `v2`
  machinery gets built before then.

**If you cannot take a Finding change unannounced, pin a `v1.x.y` tag.** They
never move. `@v1` follows `main` within about a minute of a promotion.

Read **Rule changes** before every bump. The rest is context.

## A note on the numbering

This repo was published as a fresh repository rather than by flipping an
existing one's visibility, so its public history begins at **v1.0.4** — there
is no public v1.0.0 through v1.0.3 to backfill. `CLAUDE.md` §2 has the reason.

---

## [Unreleased]

Everything on `develop` since v1.0.5. **Part of this has been live on `@v1`
since 2026-08-17**, when a promotion moved the tag and no immutable tag was cut
alongside it; the next immutable tag names it.

### Rule changes

**None.** No rule id was added, removed or re-severitied, no analyzer version
moved, and no shipped language config changed. The Semgrep ruleset has held at
40 rule ids across 12 conventions since v1.0.5.

Two things in this window look like Finding changes and are not:

- **The coverage gate is opt-in and off by default.** `coverage-report:`
  defaults to `''` and the whole job is `if: inputs.coverage-report != ''`.
  Wire it and you also get the patch gate, which fails when the lines a change
  *adds* fall below `coverage-patch-threshold` (**default 50**) — so opting in
  is the act that can turn a build red, not upgrading.
- **`dependency-cruiser` was measured, not adopted.** Analysis only; nothing
  was wired in.

### Added

- **Coverage gate**, wired by one input: aggregate ratchet over lcov and
  Cobertura, plus a patch gate over the lines a change adds — which the
  aggregate cannot see, because one new untested function inside a large
  well-covered repo does not move it.
- **`configs/editor/`** — the per-language editor settings contract, so the
  editor shows what CI shows, plus `adopt.sh --editor` to compose them into a
  consumer's `.vscode/` files for detected languages only.
- **`configs/agent/`** — three hooks and two `permissions.deny` rules for the
  third surface, the agent session that writes the code. **Not consumed by
  `@v1`**: the scripts are copied by hand, nothing in `actions/` or
  `quality.yml` references them, and adoption cost has not been measured in any
  consumer.

### Changed

- **Layer 2 installs semgrep against a pinned interpreter** rather than the
  ambient one, and puts it in a per-job directory instead of wherever pipx
  defaulted. Same semgrep version, so no finding moves; this fixes a clean
  self-hosted Linux box failing with `No module named pip`.
- The quality gate runs on macOS runners as well as `ubuntu-latest`.

### Fixed

- `release-tag.yml` no longer checks out the untrusted commit it never read,
  and its write credential is scoped to the one job that pushes the tag.

---

## [v1.0.5] — 2026-08-13

The release that tripled the ruleset and took the baseline from two languages
to five. **The largest Finding change this repo has shipped**; read the section
below before bumping onto it.

### Rule changes

- **Semgrep: 19 rule ids → 40**, still within the 12-convention cap. Most of
  the increase is per-language ids for conventions that already existed —
  Semgrep patterns are language-specific, so one convention needs a separate id
  per language when the syntax differs.
- **Three new Layer 1 languages**, each with its own analyzer set, each able to
  fail a build that had no gate before: **Python** (Ruff + mypy), **Rust**
  (clippy pedantic + rustfmt + cargo-deny), **Java** (Error Prone + NullAway at
  ERROR, Spotless/palantir, Maven only).
- **`eslint-plugin-sonarjs` adopted** for TypeScript — five bug classes
  typescript-eslint has no rule for. Two of its rules were switched back off
  after a real-code run disqualified them.
- **Dead code and unused dependencies gated**: knip for TypeScript, deptry for
  Python.
- **The .NET naming rules shipped switched off** in v1.0.4 and nothing would
  have said so. Turning them on is a Finding change on any C# repo.
- **Formatting is now enforced**, not merely configured.
- **SQL and shell injection rules widened** to catch strings built one step
  away from the sink, and security rules corrected where they missed shapes
  they advertised.

### Added

- A **policy file** so consumers can scope and exclude, with every knob failing
  loud rather than silently doing nothing.
- Findings **on the PR diff**, and an opt-in pre-commit hook.
- OpenSSF Scorecard and CodeQL **on this repo only** — CodeQL cannot gate a
  private consumer at any free tier, which is why it is declined for consumers.

### Fixed

- **Three gates reported success without running.** If you were on v1.0.4,
  assume they were not gating.
- A file Semgrep cannot parse is now a coverage gap, not a scan failure.

---

## [v1.0.4] — 2026-08-02

First public release. A two-layer static-analysis baseline for **TypeScript and
C#**: Layer 1 the language toolchains at warnings-as-errors, Layer 2 Semgrep
with 19 rule ids plus secret and dependency scanning.
