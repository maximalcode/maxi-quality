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
| 3 | rust-analyzer runs `cargo check` unless told `check.command: clippy` — pedantic/nursery lints invisible in-editor | **VERIFIED** | `rust-analyzer.check.command`, **default `"check"`**. That is what the manifest proves: the default is not `clippy`. The consequence — `cargo check` runs the compiler's own check pass and never loads the clippy driver, so the whole of `configs/rust/lints.toml` is invisible — is a fact about cargo rather than about the manifest, and it is the one behavioural step in this table. |
| 4 | The base C# extension, not C# Dev Kit — Dev Kit's licence gates on paid VS subscriptions | **VERIFIED, and sharpened** | The vendor's own FAQ: free "for personal, academic, and open-source projects", and "for commercial purposes, teams of up to 5 can also use the C# Dev Kit at no cost" — above five, a Visual Studio Professional or higher subscription. The same page states the base C# extension is "fully open source" and "licensed under the MIT license", while Dev Kit is closed source. **See the note below on the part of #111's claim that did NOT check out.** Separately confirmed from the base extension's manifest: `ms-dotnettools.csharp` declares **no** `extensionDependencies` or `extensionPack` on `csdevkit`, so recommending the base alone is a coherent install and not a half-configured one. |

Four for four. None was refuted, and each is one settings line — except #4,
which is one *unwanted* recommendation, because VS Code steers users to Dev Kit
on its own and silence there is not a decision the adopter ever sees.

**One detail of #111's row 4 could not be confirmed, and is not repeated
here.** #111 wrote the threshold as "5 developers / $1M revenue / 250 PCs". The
five-developer rule is on the vendor's own FAQ, quoted above. The revenue and
device figures are the Visual Studio **Community** enterprise definition, which
Dev Kit is widely reported to have shipped under — but the FAQ does not state
them, and the licence text itself is behind a page that serves no readable
content to a plain fetch. So this contract asserts the five-developer rule and
stops there.

It costs the argument nothing, because the argument was never really about
price: **Dev Kit is closed source, and this baseline is free/OSS only**
(`CLAUDE.md` §5). That disqualifies it on its own terms, at any team size, and
it is a fact the vendor states plainly rather than one that needs a licence
lawyer. The base extension is MIT.

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

### The non-divergences, recorded so they are not re-investigated

Six keys in this directory are pinned at a value that is **already the
extension's default**. None of them is a divergence, and listing them is the
point — the next reader should not have to re-derive which keys are load-bearing
and which are defensive:

| Key | Default, and why it is pinned anyway |
|---|---|
| `ruff.importStrategy` | `"fromEnvironment"` — precisely the failure mode row #2 describes, one global user setting away. A default that is currently right is not a default that is guaranteed. |
| `mypy-type-checker.cwd` | `"${workspaceFolder}"` — the discovery that makes the copied `mypy.ini` at the repo root readable at all. |
| `dotnet.server.useOmnisharp` | `false` — the switch between two entirely different language servers; the OmniSharp one cannot show this gate's findings. |
| `semgrep.ignoreCliVersion` | `false` — findings *and* parse errors differ between Semgrep versions. |
| `semgrep.scan.pro_intrafile` | `false` — account-gated; this baseline is free/OSS only. |
| `semgrep.scan.secrets` | `false` — same, and `layer2` already runs gitleaks. |

### The contract values, in one place

**This block is the source.** `scripts/check-editor-contract.py` parses it and
asserts every fragment agrees — so the divergence facts live here once, rather
than in the doc and in the script and in the templates, where only one pairing
could ever be guarded. Editing a value here without editing the fragment fails
CI, and so does the reverse.

```
semgrep.settings.json      semgrep.scan.onlyGitDirty                          = false
python.settings.json       mypy-type-checker.importStrategy                   = "fromEnvironment"
python.settings.json       mypy-type-checker.reportingScope                   = "workspace"
rust.settings.json         rust-analyzer.check.command                        = "clippy"
dotnet.settings.json       dotnet.backgroundAnalysis.analyzerDiagnosticsScope = "fullSolution"
dotnet.settings.json       dotnet.backgroundAnalysis.compilerDiagnosticsScope = "fullSolution"
typescript.settings.json   typescript.tsdk                                    = "node_modules/typescript/lib"
typescript.settings.json   typescript.enablePromptUseWorkspaceTsdk            = true
```

---

## 2. The C# licensing trap, stated once

`ms-dotnettools.csdevkit` is in `extensions.json`'s **`unwantedRecommendations`**,
not merely absent from `recommendations`.

The reasoning is in that file at the key, so it travels with the copy. The
short form is two independent disqualifications, either of which is enough:

1. **It is not OSS.** Dev Kit is closed source; `CLAUDE.md` §5 is free/OSS
   only, and that is a success criterion rather than a preference.
2. **It attaches a paid-subscription requirement.** Commercial teams above five
   developers need a Visual Studio Professional or higher subscription — a
   threshold a growing team crosses without anyone re-reading a licence.

The base extension carries the Roslyn analyzer and `.editorconfig` severity
handling that `configs/dotnet` is actually built on, it is MIT-licensed, and it
needs nothing from Dev Kit.

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
| Python | `samples/python-clean` | Ruff, mypy | **no manifest** — the assertion is *zero findings*, by exit code | `layer1-python` |
| Rust | `samples/rust` | clippy | `samples/expected/clippy.json` | `layer1-rust` |
| Rust | `samples/rust-clean` | clippy | `samples/expected/clippy-clean.json` | `layer1-rust` |
| Java | `samples/java` | javac (Error Prone, NullAway) | `samples/expected/java.json` | `layer1-java` |
| Java | `samples/java-clean` | javac | `samples/expected/java-clean.json` | `layer1-java` |
| Java | `samples/java-lint` | javac (`-Xlint` / `-Werror`) | `samples/expected/java-lint.json` | `layer1-java` |
| Semgrep (all languages) | the whole tree | Semgrep | `samples/expected/semgrep.json` | `layer2`, `layer2-counts` |

`samples/python-clean` is the one clean half with no manifest — every other
language's is a committed finding set, and this one is an exit code. It is a
row rather than an exclusion because "the Problems panel is empty" is a
perfectly measurable parity claim; it just is not a set diff. Step 3 has to
treat it as its own kind of assertion.

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
- **Problems-panel sources that no gate produces.** The two bullets above are
  gates a panel cannot be diffed against; this is the reverse, and step 3 has
  to exclude it by name or every Java run reads as a parity failure. There is
  exactly one today: **JDT's own null analysis**, if a team enables it (§4). It
  is not NullAway and `layer1-java` never asserts it, but it is a real
  bug-finder, so this contract excludes its diagnostics from the diff rather
  than switching it off in the editor.
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

- **Leaves JDT's own null analysis alone**, deliberately. An earlier draft
  pinned `java.compile.nullAnalysis.mode: "disabled"`, reasoning that JDT null
  analysis is not NullAway — different inference, different annotations,
  different findings — so leaving it on gives a panel that reports nulls the
  gate never asserts *while still missing* the NullAway findings it does.

  That reasoning was right about the facts and wrong about the conclusion.
  Every key here names the CI behaviour it pins; `"disabled"` would have named
  the *absence* of one, which makes it a measurement convenience rather than a
  contract term. It is also a working bug-finder, and switching it off to keep
  step 3's diff tidy optimises for the measurement over the developer. The
  draft justified it by claiming step 3 would otherwise need "an unbounded
  exclusion list" — overstated: JDT null-analysis diagnostics are one
  identifiable source, and §3 names them as an exclusion.

  The default is `"interactive"`, which asks before enabling, so nothing is
  imposed in either direction. Turn it on if your team wants it; its findings
  are outside this contract.
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

## 7. How strong each key is, in four categories

No key in this directory is proven by a sample, because none can be — that is
this whole directory's problem, and the reason
`scripts/check-editor-contract.py` exists at all.
So "how strong is this key" has four honest answers, and they are not
interchangeable:

**a. Closes a verified divergence.** The eight settings in §1's contract-values
block. Each one is backed by a published default that demonstrably differs from
what CI does, so switching it off provably changes what the editor reports.
These are the load-bearing keys.

**b. Pinned defensively at a value that is already the default.** The six in
§1's non-divergence table. They change nothing today; they stop a global user
setting or a future default flip from reintroducing a divergence.

**c. Pinned to match the gate's argv, with no fixture separating it.**
`rust-analyzer.check.allTargets` — `layer1-rust` passes `--all-targets`, but all
8 findings in `samples/expected/clippy.json` are in `src/main.rs`, so
`samples/rust` produces the same set either way. Matching the argv is the
justification; a fixture is not. `rust-analyzer.check.extraArgs` is the same
shape.

**d. Reaches nothing measurable at all.** Every key in
[`java.settings.json`](java.settings.json), for the reason in §4 — the gate's
findings cannot enter the Problems panel, so no setting there can be checked
against them. And `semgrep.scan.exclude`, which ships empty: it is the slot a
repo's `paths.exclude` entries go into by hand, and nothing generates it.

The formatter routing keys (`editor.defaultFormatter`, `editor.formatOnSave`)
are category **a** where the repo took the formatter — `layer1-typescript`,
`layer1-python` and `layer1-rust` all gate a `--check` — and inert where it did
not, which is why the TypeScript fragment marks its pair OPTIONAL.

---

## 8. Still open

- **The demo moment, and live confirmation of all six rows** — [#151]. [#120]
  asks for a side-by-side for one language: Problems panel with these settings
  against the committed expectation, and the same window at the defaults
  showing the divergence. It needs an editor and a human at it; §1 says exactly
  what evidence the verdicts above do and do not rest on. Rust is the pair to
  capture — at the default there is no clippy lint at all, so the contrast is
  total.
- **`adopt.sh --editor`** — [#126].
- **The five-pair parity run and its ablation** — the step after that, which
  is what §3's table exists to serve.

[#111]: https://github.com/maximalcode/maxi-quality/issues/111
[#120]: https://github.com/maximalcode/maxi-quality/issues/120
[#126]: https://github.com/maximalcode/maxi-quality/issues/126
[#129]: https://github.com/maximalcode/maxi-quality/issues/129
[#151]: https://github.com/maximalcode/maxi-quality/issues/151
