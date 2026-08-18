# EVAL — extend `scripts/coverage.py`, or depend on `diff-cover`?

> **Date:** 2026-08-18 · **Verdict:** **extend `coverage.py`**. Keep
> `diff-cover` as the correctness cross-check it earned, not as a dependency.
> **Measured**, on `samples/coverage/patch`: both implementations, both report
> formats, four inputs, checked against a hand-count.
>
> Nothing in `configs/` or `semgrep/` was touched to produce this. The only
> production change is the `--diff-file` flag on `scripts/coverage.py`, which
> measures and does not gate — the gate is a separate step.

Issue #112 named the defect and left one question open: coverage of the changed
lines is computable from data the ratchet already parses, so is it better to
compute it or to install a tool that already does? #112 also said how to settle
it — *"by comparing both against the same fixture, not by taste"*. This is that
comparison.

Versions: `diff_cover` **10.0.0** (Apache-2.0), the current release; Python
3.9.6 locally, `python3` as shipped on `ubuntu-latest` in CI.

---

## 1. The defect, reproduced first

`samples/coverage/patch` is one commit: a well-covered module gains an exported
function no test calls. Full derivation in that directory's `README.md`.

| | before | after |
| --- | ---: | ---: |
| lines measured | 8,000 | 8,004 |
| lines hit | 7,600 | 7,600 |
| aggregate | 95.00% | 94.95% |

The floor is `95.00` — the value measured immediately before the change, the
tightest floor a repo can hold. The aggregate falls 0.05pp; the ratchet's own
tolerance is 0.1pp. It prints `status=ok` and exits 0, and it would do the same
in a repo that re-ran `--write` after every merge. **Four added lines are
untested and the gate is green.** That is the whole case for a second number.

## 2. The two implementations agree

Same reports, same diffs, same run — `scripts/patch-coverage-demo.sh`:

| input | measured added lines | covered | `coverage.py` | `diff-cover` |
| --- | ---: | ---: | --- | --- |
| `changed.diff` — the untested function | 4 | 0 | **0.00%** | **0%** |
| `partial.diff` — same function + two covered edits | 6 | 2 | **33.33%** | **33%** |
| `docs-only.diff` | 0 | — | **n/a** | *"No lines with coverage information"* |
| empty diff (`/dev/null`) | 0 | — | **n/a** | *"No lines with coverage information"* |

Identical for **both** `lcov.info` and `cobertura.xml`, and identical to the
hand-count. `diff-cover` names the same four lines individually: *"Missing lines
62-65"*.

`partial.diff` exists because `changed.diff` alone cannot tell a correct
implementation from one that returns 0% unconditionally. Both pass the 2-of-6
case too.

So detection is a tie, and the decision falls to what each costs to hold.

## 3. Where they differ

Four differences, all measured, none of which changes the verdict on
correctness:

**a. `diff-cover` truncates the percentage.** `total_percent_covered()` is
`int(float(covered) / total * 100)`: 2 of 6 prints `33`, not `33.33`. It only
ever rounds toward failing, so it is safe for a threshold — but a gate whose
number is a whole percent cannot express a 0.5pp difference, and the ratchet
next door reports two decimals.

**b. Zero measurable lines is reported as 100% in its JSON.** The console and
markdown reports say *"No lines with coverage information in this diff"*, which
is the right answer, and `--fail-under` cannot fail on it. But the same function
returns `100` when `total_lines == 0`, and `--json-report` publishes
`"total_percent_covered": 100` for a docs-only PR. As a gate that is harmless;
as a *number* handed to a badge, a dashboard or a report that averages it, it is
the empty-diff lie #112 asked to be designed out. `coverage.py` prints
`patch_coverage=n/a` and keeps `n/a` a word all the way to stdout.

**c. `diff-cover` cannot read two report formats in one run.** Given an lcov
file and a Cobertura file together it raises
`ValueError: Mixing LCov and XML reports is not supported yet` — an uncaught
traceback, not a diagnostic. `coverage.py --report` is repeatable and sums
across formats, and CI has asserted that merged number since the ratchet
shipped. **Consumer A is a C#-plus-TypeScript monorepo**, i.e. exactly the
repo that produces both at once. This is the one difference that is not
cosmetic.

**d. A changed file that no report measures disappears from `diff-cover`'s
output.** Its `src_stats` is simply empty for that file. That is correct for a
Markdown file and dangerous for a source file the test run never loaded — the
two are indistinguishable at this layer, and the second is precisely what a
patch gate exists to catch. `coverage.py` counts them (`patch_files_unmeasured`)
and warns. Neither tool *resolves* it; only one of them *says* it.

**e. `diff-cover` requires git-style diff headers; `diff -u` output is
rejected.** Without a `diff --git a/… b/…` line it raises
`GitDiffError: Hunk has no source file`, even though the `+++ b/…` header names
the file. Neither implementation is troubled by the real input — `git diff`
emits both lines — but it is worth knowing which of the two parses a plain
unified diff.

Where the two parsers were pushed at the same corner, they agreed. A change
adding a line that itself begins with `++` emits `+++ x`, which is a file
header by prefix and an added line by position; both report the two added lines
and neither loses one. `coverage.py` gets there by tracking the hunk lengths,
which is also what lets it reject a truncated diff instead of quietly measuring
the lines it did find.

## 4. What each costs to hold

| | extend `coverage.py` | adopt `diff-cover` |
| --- | --- | --- |
| new runtime dependency | none — Python stdlib | `diff_cover` + `chardet`, `Jinja2`, `MarkupSafe`, `pluggy`, `Pygments` (16 MB installed) |
| network on the gate's critical path | none | a PyPI install per run (~1.7 s warm, and a PyPI outage is a red gate) |
| needs a git repository at runtime | no | **yes, even with `--diff-file`** — it shells out to `git rev-parse` to resolve report paths, and dies with a `CommandError` traceback outside a repo |
| version pinning | n/a | a hand-pin: Dependabot has no ecosystem for a version inside an action input, which is why `scripts/check-pins.sh` exists (#13) |
| code to review and own | +291 lines in a file that already existed, of which **105 are the computation** (`parse_diff`, `match_report_path`, `measure_changed_lines`, `read_diff`) — the rest is docstring | none, plus reading someone else's for (a)–(d) |
| what the composite action becomes | unchanged: bash plus `python3 scripts/coverage.py` | gains an install step it has never had |
| formats | lcov + Cobertura, mixable | lcov *or* XML; also Clover and JaCoCo, which nothing here emits |
| licence | ours | Apache-2.0, fine |

The line that decides it is the third row combined with §3c. The coverage
action is currently pure bash plus one stdlib script — no installs, no network,
no registry between a consumer's PR and its gate. Adding `diff-cover` puts a
package install on every consumer's critical path to buy a number this repo can
already compute in 105 lines, and buys it in a form that cannot read two of the
report formats those consumers emit at the same time.

**Free/OSS only (`CLAUDE.md` §5) does not decide this** — `diff-cover` is
Apache-2.0 and costs nothing. It lost on dependency surface and on mixed-format
support, which is worth saying plainly: this is not the reflexive no.

## 5. Verdict

**Extend `scripts/coverage.py`.** `--diff-file` intersects the per-line hit map
it already parses with the added lines of a unified diff. Step 1 ships it as
measurement only: it prints `patch_coverage`, `patch_lines_found`,
`patch_lines_hit`, `patch_files_changed` and `patch_files_unmeasured`, and fails
nothing.

**`diff-cover` stays, as the cross-check.** `scripts/patch-coverage-demo.sh`
installs the pinned version and runs both on every CI run of this repo, so the
day the intersection drifts, a second implementation says so. That is the value
it actually has here, and it costs consumers nothing because it never reaches
them.

## 6. What this settles, and what it does not

Settled, and not to be re-litigated without new measured evidence: **the
intersection is ours**, and **`n/a` is a word, not a number**. Decision D-b is
undisturbed — a fixed configurable bar on changed lines rather than a second
ratchet — and worth one observation: `diff-cover`'s truncation (§3a) would have
made a bar phrased as "≥ the file's current coverage" unreadable at one decimal.

Two things this measurement deliberately did **not** answer, because a
measurement cannot answer them — both are gate policy, and there is no gate
here:

- **What an unmeasured changed file means** (§3d). The tool reports
  `patch_files_unmeasured` and warns; it does not decide whether that is a
  failure or an unavoidable Markdown false positive.
- **What an ambiguous path means.** `match_report_path` returns `None` rather
  than guessing when two report entries could be the same file. Reporting an
  unknown as unknown is right for measurement; whether it is an error is a
  different question.

Both belong in the tracker before anything gates, not in this document —
`CLAUDE.md` §4.

## 7. What would overturn this

New measured evidence, per `CLAUDE.md` §2 — not preference. Specifically: a
consuming repo emitting a format `coverage.py` cannot parse but `diff-cover`
can; the composite action acquiring a package install for some other reason
(the dependency argument then costs nothing extra); or the demo showing the two
implementations disagreeing on a real diff, which would mean the 105 lines are
wrong and the tie in §2 never existed.
