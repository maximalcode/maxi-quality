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

The contract splits breaking from non-breaking and stops there, so until now
the minor and patch positions carried no information. They do now:

- **minor** — a new capability reaches consumers: a new input, language,
  gate, or config directory.
- **patch** — fixes, and Finding changes that add no new capability.

Neither is breaking. Both can turn a green build red, which is why **Rule
changes** is the section to read and not the version number.

Read **Rule changes** before every bump. The rest is context.

## A note on the numbering

This repo was published as a fresh repository rather than by flipping an
existing one's visibility, so its public history begins at **v1.0.4** — there
is no public v1.0.0 through v1.0.3 to backfill. `CLAUDE.md` §2 has the reason.

---

## [v1.2.0] — 2026-09-01

Everything on `develop` since v1.1.0.

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

- **Versioned external agent runtime**: a per-repository release lock selects
  an explicitly prepared cache by immutable commit. Migration removes copied
  guard files, preserves the declared gate and unrelated settings, and updates
  the managed agent instructions. Hook calls work offline and refuse missing
  or damaged runtime state with a repair instruction.
- **Closed release references**: both reusable workflows pin their actions to
  a recorded immutable payload; publication checks the actual referenced Git
  objects before advancing `v1`. Layer 2 also checks that a consumer's optional
  guard lock and workflow SHA/version pins agree.
- **Layer 1 preflight** (`scripts/preflight.py`, #76): a local, report-only
  preview in a disposable copy, with per-language/per-rule bug-class,
  stylistic and unclassified counts. Toolchain and compilation failures are
  explicit incomplete reports; the command always exits zero.
- **Coverage gate**, wired by one input: aggregate ratchet over lcov and
  Cobertura, plus a patch gate over the lines a change adds — which the
  aggregate cannot see, because one new untested function inside a large
  well-covered repo does not move it.
- **`configs/editor/`** — the per-language editor settings contract, so the
  editor shows what CI shows, plus `adopt.sh --editor` to compose them into a
  consumer's `.vscode/` files for detected languages only.
- **`configs/agent/`** — three hooks and two `permissions.deny` rules for the
  third surface, the agent session that writes the code, plus `adopt.sh --agent`
  to install them. **Not consumed by `@v1`**: nothing in `actions/` or
  `quality.yml` references them, the scripts are copied into the consumer's tree
  rather than pinned to a tag, and adoption cost has not been measured in any
  consumer. Opt-in, and **exclusive**: `--agent` installs the contract and
  nothing else — no language config, no `.editorconfig`, no workflow — so the
  language layer is a separate run and combining it with `--editor` or
  `--hooks` is a usage error. It is the only `adopt.sh` flag that MERGES into a
  file you already own — your hook entries and deny rules are appended to, never replaced
  or reordered, and a `.claude/settings.json` it cannot fully read is refused
  with nothing written at all. It is also the only thing the baseline adopts
  into **itself**: this repo now runs the contract it ships, from a copy under
  `.claude/agent-guard/` that `check-agent-contract.py` holds against its
  source — which is how #178 was found in the first hour and fixed inside the
  same window, before any of this reached a tag. Two more found the same way,
  by installing it into a repo that was not this one: the two rules hardcoded to
  `samples/` are now installed only where they can fire, and the text describing
  them says what landed (#182); and re-running refreshes the `CLAUDE.md` region
  instead of skipping it, refusing an edit of your own rather than overwriting
  it (#177). And a third, found while committing the first three real adoptions: Python writes `__pycache__` beside the hook scripts, which the guard now both gitignores and excludes from its own fingerprint — without that, a consumer with no Python section in `.gitignore` committed `.pyc` files and was refused a stop over a file the guard itself had just created. And a fourth, from the owner asking why each repo grew ~1700 lines: **43% of what was copied could not run there** — `selftest.py` needs fixtures adoption does not carry, and `sample-guard.py` kept shipping after #182 stopped wiring it. What lands is now derived from what the tree wires (#191). And `record-gate.py` resolved the target repo from the process cwd, so a recorder run from the wrong directory wrote a passing receipt into a bystander repo and left the intended one ungated (#192).
- **`adopt.sh --agent --shared`** (#193) — 101 lines per repo instead of 984, with the scripts installed once at `~/.claude/agent-guard/` by `--install-shared`. Copying stays the default, so an outside adopter still gets a tree that works from one command. A missing shared body refuses rather than failing open.
- **Fixed: a re-adoption that installs fewer rules than the last one left the old commands wired and deleted the scripts they named** (#196), which made every tool call in the repo fail. `--agent` now reclaims its own entries and verifies, after every run, that each command it wrote names a file that exists. Declare your gate once in
  `.claude/agent-guard.json` and run it as
  `record-gate.py --gate`: the wrapper then executes the whole declared string
  through one shell, and the `Stop` hook refuses a receipt that records
  anything else. The earlier spelling interpolated the gate into an argv, so an
  `&&` in it bound outside the wrapper and half the gate ran unrecorded.

### Changed

- **Layer 2 installs semgrep against a pinned interpreter** rather than the
  ambient one, and puts it in a per-job directory instead of wherever pipx
  defaulted. Same semgrep version, so no finding moves; this fixes a clean
  self-hosted Linux box failing with `No module named pip`.
- The quality gate runs on macOS runners as well as `ubuntu-latest`.

### Fixed

- Dead-code `changed-only` fetches the ancestry of a shallow PR merge or
  branch before selecting changed files. It completes both HEAD and the base
  so a shallow boundary cannot hide the true merge base, and reports missing,
  unrelated or incomplete history explicitly. Full checkouts remain complete.
- Layer 2 `changed-only` preserves complete checkout history and fetches the
  ancestry of a shallow PR merge alongside its base (#240). Previously the
  base fetch truncated full checkouts to 200 commits, and a depth-one PR merge
  made Semgrep fail before it could filter existing findings.
- `release-tag.yml` no longer checks out the untrusted commit it never read,
  and its write credential is scoped to the one job that pushes the tag.
- The rust job now puts `~/.cargo/bin` on `GITHUB_PATH` before touching
  rustup (#209). On a self-hosted runner — the very case the `runner` input
  exists for — rustup installs per-user and the non-login service shell does
  not have it on PATH, so the toolchain step failed with exit 127 on a
  correctly provisioned box. No-op on hosted images, which carry rustup
  system-wide and had masked the gap.

---

## [v1.1.0] — 2026-08-17

**Live on `@v1` since 2026-08-17, and unnamed until now.** A promotion moved
the moving tag and no immutable tag was cut beside it, so this release reached
every consumer pinning `@v1` a week before it had a number. If you are on
`@v1`, you have been running this.

### Rule changes

- **Dead code and unused dependencies are gated, and the gate is ON BY
  DEFAULT.** `quality.yml` now calls `actions/deadcode@v1` — knip over
  TypeScript packages, deptry over Python ones — behind
  `if: inputs.dead-code != 'off'`. Both tools existed here before; what changed
  is that they reach consumers. **New findings appeared in every adopting repo
  that did not set `dead-code: off`.** knip's unused-exports half is gated
  separately and is application-code only.
- **Rust `unmaintained` narrowed from `all` to `workspace`** in
  `configs/rust/deny.toml` — a **relaxation**: unmaintained *transitive* crates
  stopped being reported. The reason is a trap in the key itself: under
  cargo-deny 0.20 `unmaintained` is not a lint level, it selects which
  advisories are reported and everything reported is an error. There is no
  `warn` value, and writing one fails config deserialisation, which takes every
  other check down with it.

### Added

- The quality gate runs on **macOS runners**, not only `ubuntu-latest`.
- The **version contract itself** — `CONTEXT.md`, ADR 0001, and the README
  section this changelog is the other half of.

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
