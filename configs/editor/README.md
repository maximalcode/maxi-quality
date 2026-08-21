# The editor contract

The baseline's configs are read by CI. A developer sees the findings at PR
time, not while typing — and the official editor extensions, installed
unaided, do **not** show what CI shows. An editor that disagrees with the gate
is worse than no editor integration, because an empty Problems panel reads as
"nothing wrong" rather than "nothing measured".

This directory is the frozen contract for closing that gap: one settings
fragment per language, plus the shared extension list, every key annotated with
the CI behaviour it pins.

**Nothing here is written into a consumer's tree yet.** `adopt.sh` does not
know about this directory ([#120] ships the contract, [#126] ships
`adopt.sh --editor`, and the five-pair parity run that measures whether it
worked is [#129]'s successor step). Copy the fragments by hand until then.

| File | Against |
|---|---|
| [`extensions.json`](extensions.json) | all — the recommendation list, and the one *unwanted* recommendation |
| [`typescript.settings.json`](typescript.settings.json) | `layer1-typescript` |
| [`dotnet.settings.json`](dotnet.settings.json) | `layer1-dotnet`, `layer1-dotnet-tests` |
| [`python.settings.json`](python.settings.json) | `layer1-python` |
| [`rust.settings.json`](rust.settings.json) | `layer1-rust` |
| [`java.settings.json`](java.settings.json) | `layer1-java` — **partially**, see §4 |
| [`semgrep.settings.json`](semgrep.settings.json) | `layer2` — **not portable**, see §5 |

The fragments are JSONC. VS Code parses `.vscode/settings.json` and
`.vscode/extensions.json` as JSONC, so the annotations survive the copy —
which is the point: a settings line whose justification lives somewhere else
becomes a settings line nobody dares delete. `configs/typescript/tsconfig.strict.json`
already uses the same form.

---

## 1. The divergences, verified

**How these were verified, precisely.** Each verdict below rests on the
extension's own published manifest — the `contributes.configuration` block that
*defines* the default — read from that extension's source repository, plus the
vendor's own licence terms for the C# row. That is the authoritative statement
of what the default is, and it is falsifiable: re-read the manifest and the
number is either still there or it moved.

It is **not** the same evidence as watching the Problems panel. The manifest
proves the default; it does not prove what that default does to a real finding
set on a real sample pair. That second half is the demo moment [#120] asks for
and it is still open — see §8.

### The four [#111] predicted

| # | Claim | Verdict | The evidence |
|---|---|---|---|
| 1 | The Semgrep extension defaults `onlyGitDirty: true` — it scans the uncommitted diff, not the window CI scans | **VERIFIED** | `semgrep.scan.onlyGitDirty`, type boolean, **default `true`**. The extension's own docs put it plainly: it displays "findings for lines that have changed since the last commit", and is "On by default". |
| 2 | The mypy extension defaults `importStrategy: useBundled` — a bundled mypy, not this repo's pin | **VERIFIED** | `mypy-type-checker.importStrategy`, enum `["useBundled", "fromEnvironment"]`, **default `"useBundled"`**. |
| 3 | rust-analyzer runs `cargo check` unless told `check.command: clippy` — pedantic/nursery lints invisible in-editor | **VERIFIED** | `rust-analyzer.check.command`, **default `"check"`**. `cargo check` emits compiler diagnostics and no clippy lint at all, so the whole of `configs/rust/lints.toml` is invisible at the default. |
| 4 | The base C# extension, not C# Dev Kit — Dev Kit's licence gates on paid VS subscriptions | **VERIFIED** | Dev Kit is licensed under the Visual Studio terms: free for individuals and for commercial teams **up to 5 users**; 6+ needs a Visual Studio Professional (or higher) subscription; an organisation over **250 PCs or $1M annual revenue** needs a paid subscription regardless of team size. Separately confirmed from the base extension's manifest: `ms-dotnettools.csharp` declares **no** `extensionDependencies` or `extensionPack` on `csdevkit`, so recommending the base alone is a coherent install and not a half-configured one. |

Four for four. None was refuted, and each is one settings line — except #4,
which is one *unwanted* recommendation, because VS Code steers users to Dev Kit
on its own and silence there is not a decision the adopter ever sees.

### Two more, found by the same pass

[#111] did not name these. They are the same class of bug as #1 and #2 and they
are just as load-bearing:

| # | Divergence | Verdict | The evidence |
|---|---|---|---|
| 5 | **VS Code type-checks TypeScript with its own bundled compiler, not the repo's.** `layer1-typescript` runs `./node_modules/.bin/tsc` and asserts an exact diagnostic set; the editor uses whatever TypeScript VS Code shipped with. | **VERIFIED** | `typescript.tsdk` has **no default at all**. Its own description says that when configured as a workspace setting it *allows* switching "with the `TypeScript: Select TypeScript version` command" — it does not switch by itself. `typescript.enablePromptUseWorkspaceTsdk` **defaults to `false`**, so by default the editor does not even offer. See §6: this is the one divergence a settings file cannot fully close. |
| 6 | **Three of the five languages scope diagnostics to open files.** The gate always runs over a tree. | **VERIFIED** | `mypy-type-checker.reportingScope` **defaults to `"file"`**; `dotnet.backgroundAnalysis.analyzerDiagnosticsScope` and `dotnet.backgroundAnalysis.compilerDiagnosticsScope` both **default to `"openFiles"`**. Both are pinned to their whole-tree value in the fragments. The TypeScript equivalent is `typescript.tsserver.experimental.enableProjectDiagnostics` (**default `false`**) and it is **deliberately not pinned** — it is marked experimental, and this contract does not put an experimental flag on the parity path. TypeScript therefore keeps a known open-files scope; step 3 must account for it. |

For mypy, #6 is not merely "shows less". mypy is a whole-program checker, so a
per-file scope can report a *different* result for the same line, not a subset
of the same one.

### One non-divergence, recorded so it is not re-investigated

`ruff.importStrategy` already defaults to `"fromEnvironment"` — the good value.
It is pinned anyway, and the fragment says why: it is precisely the failure
mode row #2 describes, it is one global user setting away, and a default that
is currently right is not the same as a default that is guaranteed.

---

## 2. The C# licensing trap, stated once

`ms-dotnettools.csdevkit` is in `extensions.json`'s **`unwantedRecommendations`**,
not merely absent from `recommendations`.

The reasoning is in that file at the key, so it travels with the copy. The
short form: this baseline's premise is zero spend (`CLAUDE.md` §5), and Dev
Kit's licence attaches a paid-subscription requirement that triggers on
thresholds — 250 PCs, $1M revenue — an adopting team does not necessarily know
it has crossed. Recommending it would ship that trap as a default. The base
extension carries the Roslyn analyzer and `.editorconfig` severity handling
that `configs/dotnet` is actually built on, and it needs nothing from Dev Kit.

---

## 3. The authoritative expectation source

Step 3 diffs the Problems panel against a committed expectation. This table is
that expectation, named once, so the parity run cannot invent its own notion of
"the correct findings".

Every row is a manifest of `rule id + file + line`, diffed by
`scripts/check-expected.py`. A scalar count is *not* an expectation source and
none is listed as one — the reasoning is in that script's docstring.

| Language / layer | Sample | Tool | Authoritative expectation | Asserted by |
|---|---|---|---|---|
| TypeScript | `samples/typescript` | ESLint | `samples/expected/eslint.json` | `layer1-typescript` |
| TypeScript | `samples/typescript-clean` | ESLint | `samples/expected/eslint-clean.json` | `layer1-typescript` |
| TypeScript | `samples/typescript-strict` | `tsc` | `samples/expected/tsc.json` | `layer1-typescript` |
| TypeScript | `samples/typescript-clean` | `tsc` | `samples/expected/tsc-clean.json` | `layer1-typescript` |
| TypeScript | `samples/knip` | knip | `samples/expected/knip.json` | `layer1-typescript` |
| TypeScript | `samples/knip-clean` | knip | `samples/expected/knip-clean.json` | `layer1-typescript` |
| C# | `samples/dotnet` | `dotnet build` | `samples/expected/dotnet.json` | `layer1-dotnet` |
| C# | `samples/dotnet-clean` | `dotnet build` | `samples/expected/dotnet-clean.json` | `layer1-dotnet` |
| C# | `samples/dotnet-tests` | `dotnet build` | `samples/expected/dotnet-tests.json` | `layer1-dotnet-tests` |
| Python | `samples/python` | Ruff | `samples/expected/ruff.json` | `layer1-python` |
| Python | `samples/python` | mypy | `samples/expected/mypy.json` | `layer1-python` |
| Python | `samples/deptry` | deptry | `samples/expected/deptry.json` | `layer1-python` |
| Python | `samples/deptry-clean` | deptry | `samples/expected/deptry-clean.json` | `layer1-python` |
| Rust | `samples/rust` | clippy | `samples/expected/clippy.json` | `layer1-rust` |
| Rust | `samples/rust-clean` | clippy | `samples/expected/clippy-clean.json` | `layer1-rust` |
| Java | `samples/java` | javac (Error Prone, NullAway) | `samples/expected/java.json` | `layer1-java` |
| Java | `samples/java-clean` | javac | `samples/expected/java-clean.json` | `layer1-java` |
| Java | `samples/java-lint` | javac (`-Xlint` / `-Werror`) | `samples/expected/java-lint.json` | `layer1-java` |
| Semgrep (all languages) | the whole tree | Semgrep | `samples/expected/semgrep.json` | `layer2`, `layer2-counts` |

### The rows that are deliberately not in that table

Three kinds of gate exist here that a Problems panel cannot be diffed against,
and naming them is part of the contract — otherwise step 3 either measures the
wrong thing or silently skips it:

- **Formatters.** `samples/format` is gated by a formatter's exit code
  (`prettier --check`, `ruff format --check`, `cargo fmt --check`,
  `mvn spotless:check`) and by ablations proving a setting is not the tool's
  default. There is no finding set. The editor equivalent is format-on-save
  producing no diff, which is a different measurement and belongs in step 3 as
  one.
- **`samples/expected/deptry-targets.json`.** A manifest, but of *which
  directories get scanned*, not of findings — `scripts/deptry-targets.py`'s
  enumeration, diffed as JSON. Nothing in an editor corresponds to it.
- **Snapshot files** (`configs/*/*.snapshot.json`). These pin *resolved
  configuration* — what the build system computed after every inheritance layer
  had its say — not diagnostics. A drift there is a config regression, and it
  would show up in the tables above as findings moving.

---

## 4. Java has no in-editor parity, and no setting fixes it

`layer1-java`'s gate is Error Prone and NullAway, escalated to ERROR. Error
Prone is a **javac plugin**. `redhat.java` produces its Problems-panel
diagnostics with the **Eclipse compiler (ECJ)** — its own completion engine
setting defaults to `"ecj"`, and there is a `java.jdt.ls.javac.enabled` option
that is explicitly experimental, off by default, and requires Java 25.

So there is no settings key that routes Error Prone or NullAway into the
Problems panel. This is a property of the extension's architecture, not a
configuration mistake, and it will not be closed by trying harder.

What [`java.settings.json`](java.settings.json) does instead:

- **Switches JDT's own null analysis OFF** (`java.compile.nullAnalysis.mode:
  "disabled"`, against a default of `"interactive"`). This is the one
  judgement call in this contract and it deserves the label. JDT null analysis
  is not NullAway — different inference, different annotations, different
  findings. Left on, the panel reports nulls the gate never asserts *while
  still missing* the NullAway findings it does assert: wrong in both
  directions, and step 3 would need an unbounded exclusion list to measure
  anything at all. A team that wants JDT's null analysis for its own sake
  should turn it back on and treat it as outside this contract.
- **Makes the pom the editor reads and the pom Maven reads the same file**
  (`java.configuration.updateBuildConfiguration: "automatic"`). `adopt.sh`
  writes the lint block into the consumer's `pom.xml` as a marker-delimited
  region; the default waits for a click before re-reading a changed pom.
- **Leaves `java.format.settings.url` unset and format-on-save off.**
  `configs/java/pom-lints.xml` formats with Spotless running
  palantir-java-format in AOSP style. That key takes an Eclipse formatter
  profile XML — a different formatter with different output. Pointing it
  anywhere would make every save fight `mvn spotless:check`. Format with
  `mvn spotless:apply`.

Java is therefore the language where the honest answer is "run the build".

---

## 5. The Semgrep rules are not in a consumer's tree

The largest gap in this contract, and it is structural rather than a missing
setting.

The Semgrep extension reads rules from `semgrep.scan.configuration`, which
takes YAML files, directories of them, or URLs. `scan.sh` passes this repo's
three rule directories as `--config` arguments. But **a consumer's checkout
does not contain them.** `adopt.sh` writes configs, a `.maxi-quality.yml`
policy file and a workflow call; the rules reach the scan from inside the
composite action, in the baseline's own tree or a container mount. There is
nothing local for the extension to point at.

[`semgrep.settings.json`](semgrep.settings.json) is therefore written for a
checkout of **this** repository — which is the tree step 3's parity run
measures, so it is the right thing to freeze now. Making it portable is step
2's problem ([#126]), and the two candidate resolutions both have a cost worth
stating before someone picks one casually:

- **Ship a copy of the rules into the consumer's tree.** Gives the extension
  local paths. Adds a twelve-file copy to the drift surface — the same failure
  shape as the copied `.editorconfig` and the copied `[lints]` block, both of
  which needed their own CI guard to stay honest.
- **Point at URLs.** No copy, but it pins rules by URL rather than by the `@v1`
  tag the rest of adoption uses, and the extension would fetch per-file.

A third, less obvious cost applies either way: `.maxi-quality.yml`'s
`rules.disable` and `rules.warn` have **no** settings equivalent. This confirms
[#111]'s prediction exactly — the extension's only filters are
`semgrep.scan.exclude` and `semgrep.scan.include`, both path-based. Path
excludes map; rule-level policy does not. A repo that disabled a rule in policy
still sees it in the editor, and full policy-aware parity stays with
`scripts/scan.sh`.

---

## 6. What no settings file can do

`typescript.tsdk` names a path. As a workspace setting it *allows* the switch;
`typescript.enablePromptUseWorkspaceTsdk` makes VS Code *offer* it. Neither
performs it. Accepting the workspace TypeScript version is a one-time human
action per workspace, and it is deliberate on VS Code's part — running a
compiler out of a repository's `node_modules` is code execution from the
checkout.

So divergence #5 is narrowed by the contract, not closed by it. Step 3's
protocol has to include "accept the workspace TypeScript prompt" as an explicit
setup step, or it will measure the bundled compiler and record a divergence
that the settings were never able to fix.

---

## 7. Which keys are pinned by a fixture, and which are not

Most keys here pin something a sample proves: turn the key off and a named
manifest stops matching. Two do not, and they are labelled in place rather than
left to look identical to the rest:

- `rust-analyzer.check.allTargets` — pinned to match `layer1-rust`'s
  `--all-targets`. All 8 findings in `samples/expected/clippy.json` are in
  `src/main.rs`, so `samples/rust` produces the same set either way. Matching
  the gate's argv is the justification; a fixture is not.
- `semgrep.scan.exclude` — ships empty. It is the slot a repo's
  `paths.exclude` entries go into by hand, and nothing generates it, so there
  is nothing to prove yet.

Everything else in this directory either changes a finding set on an existing
sample or is a recommendation rather than a setting.

---

## 8. Still open

- **The demo moment.** [#120] asks for a side-by-side for one language:
  Problems panel with these settings against the committed expectation, and
  the same window at the defaults showing the divergence. It needs an editor
  and a human at it; §1 says exactly what evidence the verdicts above do and
  do not rest on.
- **`adopt.sh --editor`** — [#126].
- **The five-pair parity run and its ablation** — the step after that, which
  is what §3's table exists to serve.

[#111]: https://github.com/maximalcode/maxi-quality/issues/111
[#120]: https://github.com/maximalcode/maxi-quality/issues/120
[#126]: https://github.com/maximalcode/maxi-quality/issues/126
[#129]: https://github.com/maximalcode/maxi-quality/issues/129
