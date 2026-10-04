# Local Guardian subprocess fixtures

Run `python3 scripts/check-guardian.py`. The cases create invented Git projects,
with no CI configuration or agent host settings, and invoke the runner as a real
subprocess. They require only Python, Git and Bash (the existing gate shell).

`cases.json` pins passing execution, short-circuited compound failure, an absent
executable, misleading dependency text, a missing declaration, an invalid base,
and a gate that edits its input. Additional assertions cover human output,
unknown scope and attribution, retained failure output, later edits and commits,
Stop compatibility, and another checkout's inherited Git routing environment.

These prove the local mechanism, not adoption cost on a real consuming project
or enforcement inside an agent host. No tool-specific findings are parsed.

The setup cases additionally require Cargo with an installed toolchain and
exercise the dependency-free `rust-local/` crate offline through step 1. The
manifest and lockfile use `.fixture` suffixes and are materialized under their
Cargo names only in the temporary project, so this fixture does not become a
fourth project in the repository detection contract. Its lockfile and build-output ignore keep generated artifacts out of freshness
comparisons. Invented tagged baseline repositories exercise payload validation,
read-only previews, repeated application, native Codex wiring, retained unrelated
hooks, immutable updates and truthful post-update failure evidence. The tests
never launch an agent host or assert that hooks are trusted.

`skill-review.json` defines the invented named task, failing gate and scoped
repair for the installed skill's interface fixture. The test resolves a linked
skill to the same runner as the CLI, retains failed evidence across an external
human-decision note, and verifies freshness before and after repair. It does
not simulate an actual human decision or prove AI obedience. The interactive
[skill demo](../../docs/GUARDIAN-SKILL.md#evidence-limits-and-demo) covers the
reporting instructions separately.

## Prerequisite recovery

Issue #285 was reproduced against `9cf827e` with invented local projects before
selecting a change. An executable installed outside the gate's PATH and an
absent executable both returned 127 through the common entry. A visible check
returned 19 for an assertion failure; an opaque wrapper returned 42 with no
established cause. The runner retained each failure correctly. Setup preview
selected the existing command and reported `verification: not_run`, but neither
preview nor the failed run supplied a recovery next step.

The change adds `next_step` to the common entry and an explicit inspection
workflow to the skill. It deliberately leaves dependency diagnosis outside the
runner. The fixtures exercise setup and run, then perform the documented
inspection separately; they do not simulate an AI diagnosis.

| Case | Inspected evidence and owner action |
| --- | --- |
| Installed outside PATH | The direct executable exists and is executable at the fixture's known installation path; the same Bash environment cannot resolve it. Select that directory for a process-local PATH correction, then rerun the whole compound gate. |
| Genuinely absent | The gate requires an explicit executable path that does not exist. Report it missing at that path; use documented provisioning or obtain instructions, without guessing an install command. |
| Ordinary check failure | Available fixture executables deliberately return 127, or 19 with misleading dependency text. Inspect the check condition; neither the exit code nor stderr proves a missing tool. |
| Opaque failure | Execution fails but identifies no prerequisite. Report unknown cause, retain the output, and request or inspect the wrapper's implementation/setup evidence. |

The PATH recovery assertions keep the exact compound declaration, prove the
tail did not run on failure, and run both parts after the deliberate correction.
They check current successful evidence, the latest recorder receipt, and the
unchanged earlier failed report/output. `check` continues to return failure for
the old report even after the new successful run. Preview snapshots establish
that no project configuration or prior evidence changed.

**Manual interventions before and after:** both flows require four explicit
actions after the first failure: read the gate and retained output, inspect the
lookup and known installation path, choose the environment correction, and
rerun the whole gate. Before this change, the operator had to devise that
sequence. After it, the common entry points to the complete recovery workflow
and the skill brings the evidence and next action into its report. The measured
improvement is discoverable guidance, not fewer environment changes or an
automatic installer. Preview does not fix PATH, download tools, weaken a check
or change hook trust. These invented subprocess proofs establish neither real
adoption cost nor reliable AI obedience or native host enforcement.
