# EVAL — does the editor show what the gate shows?

> **Status: pre-registered, not yet run.** The protocol, the exclusions and the
> bar below were written *before* any window was opened, which is the same
> discipline the presentation-layer eval uses — a bar written after the numbers
> is not a bar. The matrix lands here as a dated section when [#121] is run;
> until then this document states what will be measured and what the result
> decides, and claims no result.

## 0. What this measures, and what it cannot

`adopt.sh --editor` writes `.vscode/settings.json` and `.vscode/extensions.json`
so the **official** extensions read the configs the gate already reads. Whether
that works is not a question the rest of this repo can answer: every other
config here is proven by a sample that fails without it, and a settings file
cannot be, because there is no headless VS Code (`CLAUDE.md` §5).

So the measurement is a person at an editor, and the unit is a **cell**: one
row of [`configs/editor/README.md`] §3's expectation table, in one of two
conditions.

| Condition | What is in the tree |
|---|---|
| **with** | the composed `.vscode/` files in place |
| **without** | `.vscode/` deleted — what an adopter who installed the extensions unaided actually sees |

The `without` column is the one that decides whether the flag is worth
shipping. If the defaults already agree with the gate, the settings pin nothing
and `--editor` is dead weight; #121's second acceptance criterion exists to
force that answer into the open rather than let parity in the `with` column
imply value.

## 1. The protocol

Per cell, in a checkout of **this** repository — not a consumer tree, for the
reason in §5 of the contract:

1. Open only the sample folder as the workspace. A wider folder puts a
   neighbouring sample's findings in the panel.
2. Put the tree in the cell's condition.
3. Install the recommended extensions, reload, and let the language server
   settle. For TypeScript, **accept the workspace-compiler prompt** — §6 of the
   contract explains why no settings file can accept it for you, and a run that
   skips this measures VS Code's bundled compiler and records a divergence the
   settings were never able to fix.
4. Right-click in the Problems panel → **Copy All**.
5. Hand the dump to the differ.

```bash
python3 scripts/editor-parity.py run --run-dir .parity      # walks every cell
python3 scripts/editor-parity.py matrix --run-dir .parity   # renders the table
```

The observing is manual and irreducibly so. The **diffing is not**, and that is
the half that invents cells: §3's table is twenty rows over nineteen manifests,
six of those rows use a different path base from the other fourteen, and a rule
id compared by eye is how a cell comes to read "assumed". `scripts/editor-parity.py` computes each
cell from the dump, so a cell exists only where an observation was pasted;
`matrix` names the un-run ones on stderr rather than omitting them.

### The verdicts, defined before the run

| Verdict | When |
|---|---|
| `PARITY` | every manifest finding present, at error severity, with nothing extra |
| `DIVERGES` | anything else — and the cell says which of missing / extra / demoted |

**A demoted finding is a divergence.** A finding the gate raises as an error and
the panel shows as a warning is present but not equivalent, and a count of rows
in the panel cannot tell the two apart. Splitting them out is the point of the
column.

### What is excluded, by name

- **JDT's own null analysis**, per §3 of the contract. It is a real bug-finder
  that no gate here produces, so its diagnostics are excluded from the diff
  rather than switched off in the editor. Matched on JDT's published message
  phrasings; a Java marker that misses those patterns is reported as an ordinary
  extra, so the failure mode is a cell a human must classify rather than a
  finding silently swallowed. [#151] row 6 is what settles the phrasings.
- **Formatters, `deptry-targets.json`, and the config snapshots** — §3's own
  "rows that are deliberately not in that table". None of them is a finding set,
  so none can be diffed against a panel.
- **Semgrep in a consumer tree** — [ADR 0002]. Not an exclusion from this run:
  the Semgrep row *is* measured here, because this repo is the one tree where
  those rule paths resolve. What is declined is shipping the fragment onward.

## 2. What the ablation column must show, per language

#121's second criterion is that the `without` column shows "at least the
divergences step 1 verified". §1 of the contract verified six, from the
extensions' published manifests. Transcribed here as predictions **before** the
run, so the ablation is measured against something rather than read for
plausibility:

| Language / layer | At the defaults, the panel should… | §1 row |
|---|---|---|
| **Rust** | show **no clippy finding at all** — `cargo check` never loads the clippy driver, so the whole of `configs/rust/lints.toml` is invisible. The cleanest contrast in the set: 8 expected, 0 shown | 3 |
| **Python** (mypy) | run a *bundled* mypy at *per-file* scope. Not a subset of the gate's result — mypy is a whole-program checker, so the same line can report differently | 2, 6 |
| **Python** (Ruff) | show **no divergence**. `ruff.importStrategy` is pinned at what is already the default, defensively | non-divergence table |
| **C#** | scope diagnostics to open files: close every tab and the findings go with them | 6 |
| **TypeScript** (`tsc`) | type-check with VS Code's own bundled compiler, not the repo's pin | 5 |
| **Semgrep** | scan only the uncommitted diff. On a clean worktree over already-committed bait, that is an **empty panel** | 1 |
| **Java** | show nothing from the gate in *either* condition — see below | §4, architectural |

A language whose `without` column matches its `with` column is a language whose
settings pin nothing, and the matrix must say so rather than let parity in the
`with` column imply value. Ruff is the one row where that outcome is *predicted*;
anywhere else it is a finding.

The C# Dev Kit row (§1 row 4) is deliberately absent from this table. It is an
unwanted *recommendation*, not a settings key, so it produces no cell in either
condition — §2 of the contract is where it is argued.

### Two outcomes settled by architecture, not by observation

Recording these here keeps the run from reading them as failures:

- **Java's gate findings cannot reach the panel at all.** Error Prone is a javac
  plugin; `redhat.java` produces diagnostics with the Eclipse compiler. §4 of
  the contract calls this a property of the extension's architecture, not a
  configuration mistake. Java's cells are expected to read `DIVERGES` with every
  finding missing, in **both** conditions — which is why the ablation column is
  the only thing that can distinguish "the settings do nothing here" from "the
  settings are broken here".
- **TypeScript keeps a known open-files scope.** §1 row 6 records that
  `typescript.tsserver.experimental.enableProjectDiagnostics` is deliberately
  not pinned, because this contract does not put an experimental flag on the
  parity path.

Everything else in §1 of the contract rests on the extensions' published
manifests — authoritative for *what the default is*, and explicitly not the same
evidence as watching a panel. This run is the second kind.

## 3. The bar, pre-registered

This run binds decision **D-a** and is what [#122] — the standing "should it be
a custom extension?" eval — consumes. The bar, written before the numbers:

- **The matrix shows parity in the `with` column, per language, wherever §2
  above does not predetermine otherwise** → #122 closes as parity, citing the
  matrix. That is a success, not a failure to find something.
- **The matrix records a gap the official extensions cannot close via
  settings** → #122 is armed, and evaluates a custom extension against *exactly
  those gaps* — not against the general idea of an extension.
  **The two gaps §2 predicts do not arm it.** Java's absence from the panel and
  TypeScript's open-files scope are already known, already argued, and already
  written down; if they counted, #122 would be armed before the run and the
  matrix would decide nothing. Arming needs a gap this run *discovers*. Java
  reopens only on a change to how `redhat.java` compiles, which is upstream's
  decision and not a gap a custom extension is the answer to.
- **The `without` column shows no divergence for a language** → the settings for
  that language pin nothing, and the matrix must say so. That is an argument
  against shipping them, and it is the reading the ablation exists to make
  possible.

A gap the run finds does **not** reopen #121. It becomes its own issue, filed
from the matrix and named in the cell, per that issue's fourth criterion.

## 4. The residual that no result changes

`.maxi-quality.yml`'s `rules.disable`, `rules.warn` and `rules.groups` have no
settings equivalent — the Semgrep extension's only filters are path-based. So
policy-aware parity stays with `scripts/scan.sh` whatever this matrix says, and
that is stated where an adopter reads it rather than only here: `README.md`'s
Limits, [`docs/ADOPTION.md`] §5b, and the generated header of the
`.vscode/settings.json` `--editor` writes. The reasoning is [ADR 0002].

[#121]: https://github.com/maximalcode/maxi-quality/issues/121
[#122]: https://github.com/maximalcode/maxi-quality/issues/122
[#151]: https://github.com/maximalcode/maxi-quality/issues/151
[`configs/editor/README.md`]: ../configs/editor/README.md
[`docs/ADOPTION.md`]: ADOPTION.md
[ADR 0002]: adr/0002-no-in-editor-semgrep-parity.md
