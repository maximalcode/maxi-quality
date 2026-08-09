# Adoption guide

The long version of the README's quick start. Section 5 is **Layer 2**, the one
YAML file that every repo starts with. Section 0 is `adopt.sh`, which writes it
for you. Everything else is the by-hand version and the reasoning behind it.

Where to start:

- **New repo** → §5, then §§1–4b when you want the deep per-language checks.
- **Existing repo** → §5 with `changed-only`, which grandfathers your backlog.
  Come back to §§1–4b when you have the time budgeted.
- **Layer 1 by hand** → §§1–4b, one section per language.

Every command below refers to the baseline as `$BASELINE`, so this is the only
line that depends on where you put it:

```bash
git clone https://github.com/maximalcode/maxi-quality.git
BASELINE="$PWD/maxi-quality"
```

> **Sections 2–4b are Layer 1**, one per language, and each is the expensive
> half that cannot be grandfathered. (Rust is 4b rather than 5 so the section
> numbers everything else links to did not all shift by one.)

Runnable versions of all of this live in [`../examples/`](../examples/). Copy a
directory rather than a snippet.

---

## 0. The short way — `adopt.sh`

Sections 1–5 are what adoption actually consists of. `adopt.sh` does all of it:
detects which languages the repo really contains, copies the handful of files
that .NET, ESLint and Cargo cannot consume remotely, and scaffolds the CI call.

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

CI proves this end-to-end in both directions: a repo adopted by the script builds
the clean fixture at 0 errors/0 warnings **and** rejects the bad fixture with
exactly the same 23 errors as the hand-configured sample. An adoption that
produced a gate which didn't gate would be worse than none, because it would look
green.

Read on if you'd rather do it by hand, or want to know what the script wrote.

---

## 1. Shared `.editorconfig` (every language)

```bash
cp "$BASELINE"/configs/editorconfig <repo>/.editorconfig
```

UTF-8, LF, final newline, trimmed trailing whitespace, 2-space default with
4-space for C#/Java/Python. For a C# repo, append the C# layer as well — see
below.

This file is not decoration: for C# it is what `dotnet format whitespace`
actually reads, so it is the formatting policy rather than a hint to editors
(§3a).

---

## 2. TypeScript — Layer 1

Like the .NET props, the TS pair is an **adopt-time copy** (concept G2: "copy 2–3
small files, done"). Two small files get stamped in and refreshed deliberately:

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

`eslint-plugin-sonarjs` is the newest of these and the one worth a sentence. It is
**LGPL-3.0-only** — fine as a dev dependency, since a linter is not linked into
what you ship, but check it against your own policy rather than mine. It also
declares `typescript: ">=5 <6.1.0"` as a hard **dependency** rather than a peer,
so it will conflict the day you move to TypeScript 6.1.

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
with a `_` escape hatch, and `ban-ts-comment` requiring a written reason — and
SonarJS's `recommended` set on top, for five bug classes typescript-eslint has no
rule for at all: both `if`/`else` branches identical, two functions with
identical bodies, a collection read but never filled, a catastrophic-backtracking
regex, and `eval` on a non-literal.

**Two things to know:**

- Type-aware linting needs every linted file covered by a `tsconfig.json`. If
  yours isn't at the project root, that's what `tsconfigRootDir` is for.
- `typescript-eslint` 8.x supports `typescript >=4.8.4 <6.1.0`. TypeScript 7 is
  outside that range today; this repo pins `~6.0.3`.

### 2a. Formatting — Prettier

Optional, and separate from the lint gate on purpose: a formatter finds no bugs.
What it removes is a category of review comment and the layout drift that makes
a real diff hard to read.

```bash
npm i -D prettier
cp "$BASELINE"/configs/typescript/prettier.config.mjs <repo>/prettier.config.mjs
```

```json
{ "scripts": { "format": "prettier --write .", "verify:format": "prettier --check ." } }
```

Two settings in that file are not Prettier defaults, and both exist to stop the
baseline contradicting itself:

- **`printWidth: 100`** — Prettier defaults to 80, while `configs/editorconfig`
  ships `max_line_length = 100` and `configs/python/ruff.toml` ships
  `line-length = 100`. The default would have meant two line lengths in one
  baseline and a formatter fighting the `.editorconfig` next to it.
- **`singleQuote: true`** — matches what TypeScript code here already looks
  like. Prettier's default is double, which would have rewritten every file for
  nothing. Python deliberately keeps double quotes; each language gets its own
  community default.

Everything else in the file is a Prettier default written out explicitly, so a
major bump that changes one arrives as a reviewable one-line diff instead of
unexplained churn in your repo.

**On an existing codebase, run `prettier --write` once, in its own commit, and
add that commit to `.git-blame-ignore-revs`.** A formatting commit mixed into a
behavioural one is unreviewable, and blame that points at it is worse than no
blame. There is no `--changed-only` equivalent here — unlike Layer 2, a
formatter has nothing to grandfather.

There is no ESLint/Prettier conflict to configure away: `typescript-eslint` has
shipped no formatting rules since v6, and measured on this repo's fixtures
Prettier and the lint config disagree about nothing. `eslint-config-prettier` is
not needed and is not installed.

---

## 3. C# / .NET — Layer 1

.NET has no remote "extends" for build props, so this is the one accepted copy in
the baseline. It is small and changes rarely.

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

### `packages.lock.json` — the .NET dependency-scanning trade-off

A `.csproj` pinned to three known-vulnerable NuGet packages, scanned twice
(measured 2026-08-02, OSV-Scanner 2.4.0 —
[`EVAL-vs-oss-tools.md`](EVAL-vs-oss-tools.md) §2f):

| NuGet manifest | Findings |
|---|--:|
| `PackageReference` only, **no lock file** | 4 |
| the same project with `packages.lock.json` | **7** |

Without a lock file, OSV-Scanner reads the `.csproj`/`Directory.Build.props` and
resolves **direct dependencies only**. With one, it resolves the full transitive
graph. All three findings it gains are transitive — and transitive is where
dependency vulnerabilities usually live.

```bash
dotnet restore --use-lock-file   # then commit packages.lock.json
```

**`adopt.sh` will not do this for you, on purpose.** A lock file is a commitment,
not a setting: it has to be regenerated on every dependency change, and
`RestoreLockedMode` in `Directory.Build.props` — conditional on the file existing,
so a repo that never opted in is never broken — turns a stale one into a hard CI
build failure. That is a policy for the consuming repo to accept, the same call
the [licence gate](#sbom-and-licence-compliance) makes for the same reason.

What is *not* left to you is knowing about it. The default posture is not "no lock
file yet"; it is a dependency gate that cannot see past your direct dependencies,
and until now that difference was invisible.

### 3a. Formatting — `dotnet format whitespace`

No new config: the `.editorconfig` from §1 is the policy. Gate it with

```bash
dotnet format whitespace --verify-no-changes
```

**Use the `whitespace` subcommand, not bare `dotnet format`.** Measured
2026-08-05 on SDK 10.0.301: the bare form also runs Code Style analysis and
every analyzer reference — 622 of them on a four-file sample — and re-reports
S101, IDE0005, IDE0052, IDE0060 and CS8625 under the formatter's exit code.
Those are the *build* gate's diagnostics; `Directory.Build.props` already fails
the build on them. Running both means one red check standing for two unrelated
problems, and a formatter that takes as long as a full analysis run.

On a large solution, scope it: `dotnet format whitespace <project> --include
<paths>` takes an explicit file list, which is what makes it usable from a
pre-commit hook.

---

## 4. Python — Layer 1

Two tools, because they catch disjoint things: Ruff does not do inference, and
mypy does not flag a bare `except` or a hardcoded password.

```bash
cp "$BASELINE"/configs/python/ruff.toml <repo>/ruff.base.toml
cp "$BASELINE"/configs/python/mypy.ini  <repo>/mypy.ini
printf 'extend = "./ruff.base.toml"\n' > <repo>/ruff.toml
```

Then add `ruff` and `mypy` to your dev dependencies. CI runs the versions *you*
pin — it does not substitute its own.

**What you get:** 13 Ruff rule families (`E W F I B C4 UP N SIM ASYNC S T20 RUF`)
at line-length 100, plus mypy `strict` with `warn_unreachable` and
`explicit_package_bases` on top.

**The one thing that will bite you:** Ruff's `select` and `per-file-ignores`
**replace** what they inherit rather than merging, and neither warns when they
do. Write `[lint.per-file-ignores]` in your own `ruff.toml` and you silently drop
the baseline's waivers — including `assert`-in-tests, so every test file starts
failing `S101`. Always use the `extend-` forms:

```toml
extend = "./ruff.base.toml"

[lint.extend-per-file-ignores]     # extend-, not bare
"scripts/**" = ["T20"]

[lint]
extend-select = ["PL"]             # extend-, not bare
```

`adopt.sh` writes the correct forms for you, and CI asserts it.

mypy has no `extend` at all, so `mypy.ini` is a genuine copy — add your `[mypy-*]`
sections for untyped third-party imports directly to it.

**Global `ignore` is deliberately empty.** An exemption belongs in
`per-file-ignores` where it is scoped and greppable; a global ignore is invisible
at the call site and applies to production code as readily as to the one place
that needed it.

### 4a. Formatting — `ruff format`

Already configured by the file you copied above; it just needs running.

```bash
ruff format .                     # fix
ruff format --check .             # gate
```

Everything in `[format]` is a ruff default, stated explicitly so a major bump
that changes one is a visible diff rather than churn. The setting that actually
differs is `line-length = 100` from the `[lint]` section — **the formatter reads
it too**, so the same number that decides `E501` also decides where ruff wraps.
Override it in your own `ruff.toml` and you move both at once.

Same advice as Prettier on an existing codebase: one `ruff format` commit on its
own, added to `.git-blame-ignore-revs`.

---

## 4b. Rust — Layer 1

One structural fact shapes all of this: **Cargo cannot consume lint
configuration from a remote package.** `[lints]` / `[workspace.lints]` must
live in the consumer's own `Cargo.toml`, and `rustfmt.toml` / `deny.toml` must
be files on disk. So Rust follows the C# pattern — adopt-time copies, like
`Directory.Build.props` — and `adopt.sh` is the honest way in:

```bash
"$BASELINE"/scripts/adopt.sh <repo>
cd <repo> && cargo generate-lockfile   # then COMMIT Cargo.lock
```

That copies `rustfmt.toml` and `deny.toml` and appends the `[lints]` block to
your manifest (marker-guarded, so re-running never appends twice; a manifest
that already has its own `[lints]` gets a skip and a warning, never a merge
attempt). The CI side is the plain six-line reusable call — the same one every
other language gets. On a workspace root the block arrives as
`[workspace.lints]`, and each member opts in with two lines in its own
manifest:

```toml
[lints]
workspace = true
```

**What you get:** `clippy::all` + `clippy::pedantic` in full — the strictness
tier that matches `strict-type-checked` and `mypy --strict` — plus a curated
cherry-pick of nursery and cargo lints (each pick and each disable justified
by a one-line comment in `configs/rust/lints.toml`), and
`unsafe_code = "forbid"` as the default posture. Warnings become errors **in
CI only**, via `RUSTFLAGS=-Dwarnings` in the `rust` job: a contributor's
local `cargo check` warns instead of walling them mid-refactor. There is no
Semgrep here on purpose — its Rust support is experimental, and clippy *is*
the conventions layer for Rust.

**Five things to know:**

- **The toolchain is pinned, and that is the contract.** With warnings
  promoted to errors, a clippy upgrade that adds lints is a breaking change
  (the STATUS §4 argument), so the job installs a pinned version, never
  `stable`. It lives in the reusable workflow, and `rust-version` is the input
  for a repo that needs to hold one back — bump it deliberately.
- **Commit `Cargo.lock`, or detection stops the run.** The job runs everything
  `--locked`, which cannot run without a lockfile, so a crate that has none is
  a crate clippy would never open. Detection refuses it by name rather than
  reporting "no Rust here" and going green (#70). For a binary the lockfile is
  not hygiene anyway: it is the document cargo-deny and Layer 2's OSV-Scanner
  actually read.
- **The gate does not run your tests.** `cargo fmt --check`, `cargo clippy` and
  `cargo deny` — the same split as the TypeScript and Python jobs, which lint
  and type-check but never invoke a test runner. Keep `cargo test` in a job of
  your own.
- **`unsafe_code` is forbidden, not denied.** `forbid` is what a stray
  `#[allow(unsafe_code)]` cannot waive. A crate that genuinely needs FFI
  lowers it to `"deny"` in its own manifest and documents why — the same
  class of per-repo decision as the C# `packages.lock.json`.
- **There is no ratchet, same as every Layer 1.** An existing codebase will
  be noisy on first run. Waive a single site with `#[allow(clippy::...)]`
  and a written reason — scoped and greppable — rather than a global allow
  in the manifest.

### Upgrading — if you adopted Rust before it joined the workflow

**Delete the `rust:` job from your own `.github/workflows/quality.yml`.** Early
Rust adopters got a whole pinned-toolchain job written into their repo, because
Rust could not ride the reusable workflow yet. It can now (#70), and `@v1` moves
on its own — so the moment this ships, a repo still carrying that job runs
clippy **twice**: once from the baseline, once from a copy whose toolchain pin
only moves when someone re-runs `adopt.sh`.

Nothing can do this for you. `adopt.sh` will not rewrite a workflow file you
own, so re-running it warns and stops; and the tag moving is what triggers the
duplication in the first place, which reaches repos that never re-run anything.
Hence this note.

Two ways out, and do not leave both jobs in place:

- **Keep the baseline's** — delete your `rust:` job. The six-line `quality:`
  call covers Rust. Note it runs `cargo fmt --check`, `cargo clippy` and
  `cargo deny` but **not** `cargo test`; if your old job ran tests, keep that
  part in a job of your own.
- **Keep your own** — pass a `languages:` input without `rust`
  (`languages: ts,dotnet,python`, or `none` for Layer 2 only) so the baseline
  stops running it.

### Formatting — `cargo fmt`

`rustfmt.toml` is deliberately minimal: rustfmt's defaults are the community's
defaults, and only stable options are used. The two stated values that matter:
`max_width = 100` (rustfmt's own default, stated so a major bump cannot move
it silently — and the one line width the whole baseline agrees on) and
`newline_style = "Unix"` (**not** the default, which is "whatever the file
already uses"; the `.editorconfig` mandates LF and the formatter should
enforce the policy, not defer to the incumbent). Same advice as Prettier and
ruff on an existing codebase: one `cargo fmt` commit, alone, in
`.git-blame-ignore-revs`.

### Supply chain — `cargo deny`

One tool, four checks, one supply chain to trust: `advisories` covers what
cargo-audit would (RustSec — so no second tool), `bans` warns on duplicate
semver-incompatible versions, and the **licence allowlist ships empty** for
the same reason the Layer 2 `licenses` input has no default: an allowlist is
a per-repo policy call, and a default would gate wrongly somewhere on day
one. The `rust` job therefore runs `cargo deny check advisories bans`; add
`licenses` to that line when the allowlist holds your policy.

Layer 2 needs **zero Rust changes** — Gitleaks is language-agnostic and
OSV-Scanner reads `Cargo.lock` natively. A Rust repo on the reusable workflow
gets two advisory feeds (OSV aggregates RustSec); the overlap is deliberate,
because cargo-deny also runs locally with no baseline machinery, which is
what a first-commit adoption needs.

---

## 4c. Java (Maven) — Layer 1

**`adopt.sh` does this for you.** Everything below is what it does and why, so
that a hand merge is possible when it refuses.

### What lands in your `pom.xml`, and why it is an edit rather than a file

Maven has no remote lint consumption. Its one real inheritance mechanism is a
parent POM, and that is unavailable twice over: publishing one needs a registry
(this baseline ships no artifacts), and a Spring Boot project's single
`<parent>` slot is already taken. So the config is a **copy** — the same
constraint Cargo imposes on `[lints]`.

Rust gets away with `cat >> Cargo.toml` because TOML appends. XML does not: the
block has to land **inside `<build><plugins>`**. So it arrives as a
marker-delimited managed region:

```xml
<!-- maxi-quality:begin — Java lint baseline. GENERATED, do not hand-edit. ... -->
...
<!-- maxi-quality:end -->
```

Re-running `adopt.sh` replaces everything between the markers and **nothing**
outside them — your own plugins, properties, comments and formatting are
untouched. That is the upgrade path; without it, every baseline bump would be a
hand edit, which is copy-paste-drift with a changelog.

Never hand-edit inside the markers. `scripts/pom-region.py check` is what CI
uses to tell a stale region from a current one.

### When `adopt.sh` refuses — and what to do

If your `pom.xml` already configures `maven-compiler-plugin`, **nothing is
written**. That is not caution, it is correctness: two declarations of one plugin
in one POM is not a merge, it is last-one-wins, so writing the baseline's would
**silently delete the `compilerArgs` you already had**. A repo arriving with
`-Xlint:all -Werror` would come out of adoption *weaker* than it went in.

Merge by hand instead — copy the `<compilerArgs>` and
`<annotationProcessorPaths>` out of `configs/java/pom-lints.xml` into your
existing declaration, keeping your own args, and add the spotless plugin beside
it.

### Three things that will bite, all measured

1. **`-Werror` and Error Prone do not compose.** When javac's own `-Xlint`
   produces a warning, the compile ends before Error Prone's pass runs, so its
   findings are **missing from that build's output**. The build is still red —
   a green build is by definition one where Error Prone ran and found nothing —
   but your first run on an existing codebase may show four lint warnings and
   hide forty analyzer findings behind them. Fix the lint warnings, re-run, and
   the rest appear. Nothing fixes this: not any spelling of javac's should-stop
   policy, and not `<failOnWarning>`, which is implemented by adding `-Werror`.
   The CI job prints a `::warning::` naming it whenever it happens.
2. **`annotationProcessorPaths` turns off classpath processor discovery.** If
   you use Lombok or MapStruct they must be listed there too. That is Maven's
   behaviour, not this baseline's, and it is the one way adopting this can break
   a build that was previously fine.
3. **NullAway is told which code is yours via `${project.groupId}`**, a prefix
   match. If your sources do not live under your groupId, change that one value
   — because getting it wrong means NullAway analyses **nothing** and says so
   nowhere. `samples/java` plants a null dereference that must fire, which is how
   this repo proves its own wiring rather than assuming it.

### Formatting — `mvn spotless:apply`

```bash
mvn spotless:apply     # fix, once, alone
mvn spotless:check     # the gate
```

palantir-java-format in **AOSP** style: 4-space indent at 100 columns, which is
what the shared `.editorconfig` already declares for `*.java`. Deliberately not
bound to a lifecycle phase — a contributor's `mvn test` should not fail on layout
mid-refactor, and CI is the gate. Same split as Rust's `-Dwarnings` living in the
job rather than in the manifest. Run `apply` once, alone, and put that commit in
`.git-blame-ignore-revs`.

### Scope: Maven only

Gradle gets built when a Gradle consumer exists — the same just-in-time rule that
produced this layer. Until then a `build.gradle[.kts]` with no `pom.xml` **stops
the run** rather than skipping, because "no Java here" is a lie about a repo that
plainly has some.

Layer 2 needs **zero Java changes** — Gitleaks is language-agnostic and
OSV-Scanner reads `pom.xml` natively. Unlike Rust, Semgrep supports Java well, so
the conventions are real Layer 2 rules rather than being folded into the Layer 1
analyzer.

---

## 5. CI — Layer 2, and the whole point

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
`"packageManager"` in package.json), the .NET build (the props make the build the
analysis run), and the Layer 2 umbrella (Semgrep + Gitleaks + OSV-Scanner).

**Detection fails loud rather than skipping.** A `package.json` with no
`package-lock.json` or `pnpm-lock.yaml` at or above it stops the run, and so does
a `.csproj` that no solution in the tree references. Both used to detect as "no
such language here" and skip in silence, leaving a green gate over code nothing
had opened. Pass `languages:` without the one you mean to exclude if the skip is
deliberate.

**No token, no secret, no checkout of this repo.** The Layer 2 job receives this
repo's rules through GitHub's own action-download mechanism. Because this repo is
public, any repo may call it — there is nothing to configure and no access policy
to grant.

> For the record, since it shaped the design: while the baseline was private,
> consumers had to be owned by the same account, because a private repo's Actions
> access policy can open it to that account's own repos and to nothing else. That
> was the one real adoption limit, and going public removed it.

Every input is listed in [`REFERENCE.md`](REFERENCE.md).

---

## 5a. Faster feedback — annotations and the pre-commit hook

Neither of these detects anything new. They change **when** and **where** a
finding reaches a human, which is most of what makes a gate usable (#40).

### Findings on the pull-request diff

On by default. Semgrep findings render as annotations on the changed lines
instead of living only in the job log, where a reviewer has to open the log,
read a `file:line` and then go find it. Gating findings become `::error`
annotations; rules your policy downgraded with `warn` become `::warning`, so
the diff never shows red for something the gate deliberately let through.

```yaml
jobs:
  quality:
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1
    with:
      annotate: 'false'       # if your review workflow does not want them
      max-annotations: '50'   # the default
```

**Annotations are additive and cannot change the verdict.** They are emitted
after the gate has been decided, from the same classification the exit code
comes from. CI asserts that directly: with `--max-annotations 0`, a repo with
findings still exits 1, and a deliberately malformed result set still produces
the right gate count.

**The cap is real and the omitted count is always stated.** GitHub drops
annotations past a limit it does not document, and a legacy repo adopted
without the ratchet can produce hundreds. A silent truncation would read as
"that was all of them".

SARIF upload would be the better mechanism and is out for the same reason
CodeQL is: it needs Advanced Security on a private repo
([`EVAL-vs-oss-tools.md`](EVAL-vs-oss-tools.md) §0).

### The pre-commit hook — opt-in

```bash
"$BASELINE"/scripts/adopt.sh <repo> --hooks
```

**Never installed without that flag.** A hook that appears in someone's repo
unasked is the kind of thing people rip out along with everything near it.

It runs Gitleaks on the staged diff (~50 ms, measured) and Semgrep on the
staged content. The credential is the reason it exists: one caught in CI is
eight minutes and a force-push later than the same credential caught at `git
commit`, and by then it is in the remote history and has to be treated as
compromised no matter what you do next.

Three properties worth knowing, because each is the difference between a hook
people keep and one they delete:

- **It scans the index, not the working tree.** `git commit` commits the index,
  so a working-tree scan both misses findings you *are* committing and reports
  ones you are not. The hook materialises the staged blobs before scanning. CI
  asserts both directions: a staged secret blocks even when the file on disk is
  clean, and an unstaged secret does not block.
- **It never blocks on its own problems.** Missing tool, missing baseline,
  Semgrep that will not start — each warns and lets the commit through. CI is
  the gate; a hook that fails closed on its own plumbing just teaches people to
  pass `--no-verify` reflexively.
- **It is bypassable, and says so on every failure.**

```bash
git commit --no-verify                        # skip it once
export MAXI_QUALITY_HOOK_SKIP_SEMGREP=1       # keep the fast half only
export MAXI_QUALITY_BASELINE=/path/to/checkout  # if the baseline moved
```

The baseline path is baked in at install time, so it works for a colleague who
has never heard of this repo; `MAXI_QUALITY_BASELINE` overrides it at run time
if the checkout moves. If `core.hooksPath` is set, the hook installs there
instead of `.git/hooks` — writing to a directory git does not read would look
installed and do nothing.

---

## 6. Adopting on an existing repo — the ratchet

Do not big-bang-fix legacy findings. Start new-code-only, then tighten:

```yaml
    uses: maximalcode/maxi-quality/.github/workflows/quality.yml@v1
    with:
      changed-only: origin/main
```

Locally, the same three steps:

```bash
./scripts/scan.sh --changed-only origin/main --no-fail   # week 1: report only
./scripts/scan.sh --changed-only origin/main             # week 2: gate new code
./scripts/scan.sh                                        # once the tree is clean
```

`--changed-only` passes `--baseline-commit` to Semgrep and limits Gitleaks to
commits since the ref. OSV-Scanner has no changed-only mode on purpose — a
vulnerable dependency is vulnerable no matter which commit introduced it.

A worked version of this is [`../examples/legacy-ratchet/`](../examples/legacy-ratchet/).

---

## 7. Narrowing the rules — `.maxi-quality.yml`

Optional. Without one, nothing changes. The full schema is in
[`REFERENCE.md`](REFERENCE.md#the-policy-file); the short version:

```yaml
rules:
  groups: [general, security, conventions]
  disable: [no-float-for-money]
  warn:    [todo-without-issue]
paths:
  exclude: [legacy]
extends: .maxi-quality/rules
```

`adopt.sh` writes a commented starter, so the knob is discoverable before someone
needs it. **Unknown keys and unknown rule ids are hard errors**, and Gitleaks and
OSV-Scanner are deliberately not configurable.

---

## 8. Coverage — a ratchet, not a threshold

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

## 9. The standing report — what the gate forgets

`quality.yml` is a **gate**: it answers *is this PR clean?* On a repo adopted with
`--changed-only` it deliberately says nothing about the backlog it grandfathered.
That is correct for a gate and useless as a view of where the repo stands — and it
was the one thing SonarQube genuinely did better
([`EVAL-vs-sonarqube.md`](EVAL-vs-sonarqube.md); it lost on detection, not on
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
issue number so a caller can **assert the report actually landed** — without that,
a broken report path is indistinguishable from a clean repo, which is precisely
how it shipped broken once.

---

## SBOM and licence compliance

Both come out of OSV-Scanner, which is already installed and pinned for the
vulnerability scan. No fourth tool, no second supply chain to trust.

```bash
./scripts/scan.sh --sbom sbom.cdx.json                    # CycloneDX 1.6, never gates
./scripts/scan.sh --licenses 'MIT,Apache-2.0,ISC,BSD-3-Clause'   # gates
```

The **SBOM never gates** — an inventory is not a finding. It is produced by the
weekly standing report, which summarises it as a licence breakdown in the issue
and uploads the full CycloneDX document as a workflow artifact.

The **licence gate is opt-in and has no default allowlist**, on purpose. Measured
against this repo's own tree, a plausible-looking allowlist flags
`SonarAnalyzer.CSharp` and `typing-extensions` as *non-standard* and `pathspec` as
MPL-2.0. A default would be wrong for someone on day one, and a licence gate
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

## Requirements

Node 24 / npm 11 and .NET SDK 10 were used to verify. Anything reasonably recent
should work; the TypeScript peer range above is the one real constraint. Rust
needs no extra installs beyond rustup — clippy and rustfmt ship with the
toolchain, and the baseline's `rust` job installs its own pinned cargo-deny
(install the same version locally to match).

Layer 2 tools are optional locally — `scan.sh` falls back to `uvx` (Semgrep) or
`docker` (all three) and warns loudly if it cannot run one. To install them
natively:

```bash
brew install semgrep gitleaks osv-scanner
```

`scan.sh` targets **bash 3.2**, the version macOS actually ships, so it runs from
`/bin/bash` with no Homebrew bash required.
