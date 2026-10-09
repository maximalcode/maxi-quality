# Layer 2 scope evidence

The Layer 2 action writes `layer2-scope.json` for its own execution when it is
given `--scope-out` by `scripts/scan.sh`. The file uses schema version `1` and
is an evidence record, not another quality gate. It keeps the execution
identity, analysis result, collection completeness, each scanner invocation,
and the full diagnostics emitted by the invocation together.

Gate and standing-report runs identify themselves as `gate` and `report`.
Their artifact names include the producer, workflow run, attempt, and job, so a
report cannot replace a gate's evidence. `started_at` belongs to the execution
identity; `collection.finalized_at` is recorded separately after the scanners
finish.

Each tool has an execution `state` (`run`, `skipped`, `not_applicable`, or
`unknown`) and an independent `outcome` (`success`, `failure`, `cancelled`, or
`unknown`). A missing tool is `skipped` with an `unavailable` reason code; an
explicit skip or disabled optional invocation remains visible. A requested tool
starts as `unknown` until its command boundary is entered. The three source-file
measurements are always present with a unit, method, and reason. Their count is
an integer only when trustworthy scanner evidence exists; otherwise it is
`null` and the status is `unknown` or `not_applicable`. Layer 2 counter
instrumentation is deliberately a later tranche.

The artifact and the readable job summary are attempted independently on
ordinary failures. The summary is bounded and escapes diagnostic excerpts; the
artifact retains the complete diagnostic text. Runner loss, force cancellation,
and artifact-service failure can prevent delivery and remain operational limits.

The evidence is collected from fixture and structural checks in this repository.
It does not claim a live GitHub observation or change an Adopter's existing
analysis verdict.
