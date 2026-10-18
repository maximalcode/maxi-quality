# Analysis scope

Analysis scope records what one execution provides evidence for, including
omissions and uncertainty. It is separate from finding counts and test line
coverage. Collection, rendering and publication are non-gating in v1: their
failure must not change an existing analysis verdict or start additional
analysis. [ADR 0004](adr/0004-analysis-scope-belongs-to-its-run.md) explains the
accepted boundaries.

## Which execution the evidence describes

The quality workflow collects its own language, job, matrix-leg and tool
records. The standing report performs an independent full Layer 2 scan and
uses only that scan's evidence. It does not import Layer 1 or Rust results from
another quality run.

The JSON contract uses `schema_version: 1` with `kind: layer2-scope`,
`workflow-scope` or the transported `workflow-scope-fragment`.
These records keep producer, workflow invocation, run ID, attempt,
commit, ref, scan mode and execution start separate from collection time.
Changed-only analysis also records its baseline. Gate and report producers
and individual matrix/action fragments have distinct identities. A collector
accepts only fragments for its own invocation and current attempt.

A failed-jobs-only rerun can leave expected jobs whose current-attempt evidence
is missing. Previous successful fragments are not relabelled as fresh. Missing
fragments alone establish neither that a job never started nor that it
examined zero files.

## Files and transport

The reusable Layer 2 action exposes a `scope` output naming
`$RUNNER_TEMP/maxi-quality-layer2-scope.json`. Its artifact name begins with
`maxi-quality-layer2-` and includes producer, run, attempt, job and a unique
fragment identifier. Direct scanner callers can request the same evidence with
`--scope-out FILE`; `scripts/layer2_scope.py` owns this JSON contract.

The quality workflow uses `actions/workflow-scope` for its manifest, per-job
fragments and final `maxi-quality-workflow-scope.json`. Transport names include
the gate producer, run, attempt and invocation discriminator; hashed fragment
suffixes keep project paths out of artifact-name syntax while JSON retains
the raw matrix leg. `scripts/workflow_scope.py` reconciles the own-run records.
A missing current-attempt manifest produces partial evidence with unknown
presence; it does not rediscover the collector runner's empty workspace.

Language jobs obtain a standalone recorder from the action checkout through
its `helper` mode. They do not require baseline scripts in the Adopter tree.
Command records are handed to the fragment action through `tools-file`; missing
or malformed command evidence makes collection incomplete. A recording failure
does not replace the command's original exit status.

## Presence, execution and outcome

Language presence is observed independently of selection. A present language
excluded by the selection input is skipped; an absent supported language is
not applicable. A failed observation is unknown, not absent. Observing a
deselected unsupported project does not activate its validation or analysis.

Execution state is `run`, `skipped`, `not_applicable` or `unknown`, with a
reason. Outcome is separate: success, failure, cancellation or unknown. An
analysis failure can have complete scope evidence; a successful analysis can
have incomplete evidence. Setup failure does not establish that an analyzer
ran, and a command blocked by an earlier failure remains unexecuted.

An Adopter's npm/pnpm lint script and configured build plugins are opaque
boundaries. The outer command can be observed without establishing which
nested analyzers ran. Optional dead-code tools retain disabled, unavailable,
no-applicable-input and actual-execution distinctions. The optional coverage
job is represented as a job; its test percentages are not analysis-scope
measurements.

## Measurements and their limits

Every tool has examined, unparsed and policy-excluded slots. Each slot carries
status, count, unit, method and reason. Known counts are nonnegative integers;
unknown and not-applicable counts are `null`. Unlike units are never added into
one total or percentage.

For Semgrep:

- Examined counts unique normalized paths from the scanner's scanned-target
  list. It means scanner-reported selected or attempted targets, not proof
  that every rule completed on every target.
- Unparsed counts unique paths with the existing per-file error types,
  including timeouts and memory failures. This gap count can overlap examined
  targets; it is not subtracted from examined.
- Observed policy exclusions count unique whole-target skip records attributed
  by Semgrep to CLI path exclusions. Other ignore mechanisms and rule-specific
  skips remain distinct. No second approximate matcher or counterfactual scan
  is used.

The pinned Semgrep invocation requests verbose skip evidence. Missing skip
metadata is unknown, not zero. A skipped directory can be a single unexpanded
target path; it is not presented as a count of its descendant source files.
Malformed or inconsistent measurement evidence preserves uncertainty and raw
diagnostics rather than fabricating a clean zero.

Gitleaks records history/worktree mode, the effective range or baseline and
fallback behavior. OSV records dependency-input and resolution limits, with
license checking and SBOM production represented as separate invocations.
Native dependency or component counts do not become source-file counts.
Unsupported counts explain what the tool did not expose.

Rust scope distinguishes requested configuration from actual Cargo
compiler-artifact messages: package, target kind/name, enabled features and
freshness. A cached artifact is not labelled newly processed. Partial failure
retains emitted evidence without claiming unfinished units completed. Package
metadata alone does not prove execution, and the Cargo package target object
is not the platform target. Without reliable platform evidence, that value is
unknown; the absence of a CLI target flag does not establish the host platform.
The workflow adds no target/feature combinations, cache or forced rebuild.

The Clippy command record carries this evidence in `tools[].rust`.
`requested` describes command flags and observed configuration inputs;
`observed.artifacts` retains package, target, profile, feature and freshness
identity from emitted Cargo records. `observed.build_finished` records Cargo's
completion result, while compiler messages and the original diagnostic stream
preserve failure evidence. Requested configuration alone does not establish an
observed platform. The extra JSON diagnostic mode belongs to the existing
Clippy invocation.

## Diagnostics and delivery

Artifacts retain full emitted scanner errors and relevant diagnostic streams
before temporary output is removed, preserving existing secret redaction.
Summaries use escaped, bounded excerpts with visible truncation and an
artifact reference. An unavailable diagnostic is identified explicitly, as is a failed capture
that retained only part of the output.
Artifacts stay in the producing repository under its access and retention
rules; public fixtures and documentation use invented or public examples.

Finalization and transport run after ordinary detection, setup and analysis
failures. Artifact publication and summary rendering are attempted
independently. Cancellation is best effort when finalization can run; forced
termination, runner loss and artifact-service failure can prevent delivery.
Local fixtures and structural workflow checks do not establish live GitHub
recovery from those conditions.

## Standing history

The standing issue retains the newest 52 entries by execution time, with a
deterministic tie-break. Entries identify run and attempt: separate same-day
runs remain distinct and reprocessing one identity is idempotent. Legacy daily
rows remain legacy entries with unknown scope. Retention counts entries, not
days. A failed or incomplete attempt is not represented as zero findings.

Compact comparison metadata lives with the history; full evidence stays in
artifacts. Repeated metadata is stored once, and the report keeps diagnostic
excerpts for the current presentation rather than every older history entry.
The history encoding is versioned separately and retains readers for earlier
metadata and daily-row formats. Expired artifacts do not erase history. Malformed optional scope
metadata makes comparison unavailable while preserving parseable history. If
prior history cannot be safely preserved, the report refuses to replace it
with an empty history.

Finding and per-tool scope deltas are shown together against the immediate
chronological predecessor, including failed or unavailable predecessors.
Unknown data is never a zero baseline. Smaller examined scope, more gaps and
more observed policy exclusions are qualified visibly. Changed tool selection,
versions, rules, effective configuration/exclusions or mode are flagged even
when counts match. Incompatible units/methods are not numerically compared;
incomplete conditions do not establish stability. Counts alone do not prove
identical files or rules, explain a scope change, or establish improvement.

The report job serializes the scan and issue update by repository and label,
and execution order controls which entry is current. An older run completing
later cannot replace a newer report or discard retained entries. GitHub may
replace a queued run with a newer pending run; serialization does not guarantee
that every queued or cancelled execution reaches the report.

## Verification boundaries

| Fixture or check | Evidence provided |
|---|---|
| `samples/layer2-scope/` | Scanner/action failure paths, nullable measurements, full diagnostics and independent non-gating publication |
| `samples/layer2-changed-only/` | Actual scanner/action behavior across complete and shallow Git histories; full versus changed-only scope |
| Existing `policy` CI fixtures | Pinned Semgrep policy ablations, default-ignore controls, partial/all-unparsed results and fatal error classification |
| `samples/workflow-scope/` | Actual detector and collector bodies, language selection, matrix transport, missing fragments and current-attempt reconciliation |
| `samples/workflow-scope/test_language_tools.py` | Actual language command boundaries, earlier-failure prevention, optional dead-code behavior and collection faults |
| `samples/workflow-scope/test_rust_scope.py` | Pinned Cargo fixture through the existing Rust command boundary: default features, cached rerun and partial compilation |
| `samples/report-history/` | Independent Layer 2 history, failure entries, comparison qualifiers and retention through the public renderer/action boundaries |

These are fixture and structural proofs. They do not establish private Adopter
behavior, platform outage recovery or delivery of a new release payload.
