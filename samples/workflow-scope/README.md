# Workflow scope fixture

This fixture exercises the public `scripts/workflow_scope.py` command boundary
and extracts the real detector shell body from `.github/workflows/quality.yml`
against an invented checkout. It proves the additive presence observation,
selection states, current-attempt fragment filtering, matrix-leg reconciliation,
missing-record handling, cancellation metadata, and all-outcome collector
wiring.

The deterministic language fixtures run with the existing detector context.
The pinned Rust suite runs in the existing `layer1-rust` CI context after it
installs Cargo 1.97.1, and executes the committed `rust-fixture`. It records Cargo's own
`compiler-artifact`, `compiler-message` and `build-finished` JSON messages,
including target and feature selection, fresh artifacts, default-feature
omission, partial compilation, and format-before-Clippy short-circuiting. The
helper re-renders compiler messages after capture so the job remains readable
while the complete raw stream is retained. The fixture proves local pinned-tool
behavior and helper delivery from an invented adopter checkout; it does not
claim consumer configuration or live workflow transport.

The fixture does not claim live GitHub cancellation, runner loss, artifact
service recovery, or a released action payload. The workflow wiring is checked
structurally; the command behavior is executed locally.
