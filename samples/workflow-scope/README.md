# Workflow scope fixture

This fixture exercises the public `scripts/workflow_scope.py` command boundary
and extracts the real detector shell body from `.github/workflows/quality.yml`
against an invented checkout. It proves the additive presence observation,
selection states, current-attempt fragment filtering, matrix-leg reconciliation,
missing-record handling, cancellation metadata, and all-outcome collector
wiring.

The fixture does not claim live GitHub cancellation, runner loss, artifact
service recovery, or a released action payload. The workflow wiring is checked
structurally; the command behavior is executed locally.
