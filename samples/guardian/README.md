# Local Guardian subprocess fixtures

Run `python3 scripts/check-guardian.py`. The cases create invented Git projects,
with no CI configuration or agent host settings, and invoke the runner as a real
subprocess. The full suite requires Python 3.11+, Git, Bash (the existing gate shell),
and callable Cargo/Rust compiler binaries for the existing Rust setup fixture.
The entry point checks these tools before starting the corpus; missing tools or
an unavailable toolchain fail validation rather than skipping cases.

`cases.json` pins passing execution, short-circuited compound failure, an absent
executable, misleading dependency text, a missing declaration, an invalid base,
and a gate that edits its input. Additional assertions cover human output,
unknown scope and attribution, retained failure output, later edits and commits,
Stop compatibility, and another checkout's inherited Git routing environment.

These prove the local mechanism, not adoption cost on a real consuming project
or enforcement inside an agent host. No tool-specific findings are parsed.
The read-only `guardian status` cases cover no evidence, successful evidence,
failure, a missing command, and stale evidence. They also assert that
status leaves project files and saved receipts unchanged, keeps host trust and
live enforcement unknown, and reports a compound gate only as the command that
actually ran.

The setup cases additionally require Cargo with an installed toolchain and
exercise the dependency-free `rust-local/` crate offline through step 1. The
manifest and lockfile use `.fixture` suffixes and are materialized under their
Cargo names only in the temporary project, so this fixture does not become a
fourth project in the repository detection contract. Its lockfile and build-output ignore keep generated artifacts out of freshness
comparisons. Invented tagged baseline repositories exercise payload validation,
read-only previews, repeated application, native Codex wiring, retained unrelated
hooks, immutable updates and truthful post-update failure evidence. The tests
never launch an agent host or assert that hooks are trusted.

`test_setup_hosts.py` adds separate selected-Claude and selected-Codex setup flows:
read-only preview, one-host application, shared skill link, existing gate run,
selected-host status and repeat-apply idempotence. It also keeps foreign host
settings and skill links intact and verifies that an explicitly inspected other
host does not inherit the selected host's lifecycle overlay.

The lifecycle suites exercise the same public CLI. `test_update.py` proves
candidate-pin verification, failed and interrupted transition recovery,
preserved user edits and shared-pin conflicts. `test_pause.py` covers pause,
local checks while paused, resume prerequisites and unrelated host settings.
`test_remove.py` covers exact ownership, retained checks and shared caches,
modified-region conflicts and repeated removal. `test_switch.py` covers both
host directions, unchanged pins, target prerequisites and failed transitions.
They run through the existing `agent-guard` CI context; no new guard policy or
required CI context is introduced.

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

Automatic completion (#308) is exercised by `test_completion.py` through real
Stop/recorder/Guardian subprocesses in invented temporary repositories. It
observes start counts, source/configuration bytes, receipts, status, timeout and
child-process termination, interruption, concurrent Stops, regular recovery,
wrong/partial/stale evidence, clean checkouts, changed commands and explicit
unverified handoff. The same matrix runs independently for each native payload.
`test_setup_hosts.py` also invokes the installed hook commands for Claude and
Codex independently and checks pause/resume/switch/removal with activation.
These run through `scripts/check-guardian.py`; existing freshness and lifecycle
cases remain part of the same entry point. The synthetic payloads prove protocol
and process behavior, not live host enforcement or human interaction. Live
observations and pilot measurements of the new automation remain unperformed.

## First setup with a published release

`test_real_release.py` runs Claude Code and Codex independently from invented
projects without Guardian configuration or a gate declaration. It uses the
published **v1.3.0** payload at
`8940116445bbeed3637983e1cd756629eafba7d5`. Prepare that release explicitly before
running the existing entry point, including in a shallow checkout:

```sh
git fetch --no-tags --depth=1 origin refs/tags/v1.3.0:refs/tags/v1.3.0
python3 scripts/check-guardian.py
```

The existing `agent-guard` CI job performs that fetch and verifies the peeled tag
commit. The test also refuses a missing or mismatched tag/commit, and exercises
public setup rejection of missing and mismatched payloads. No synthetic release
substitution or skipped success is permitted. Payload preparation happens before
the tests; hooks do not download runtimes or tools.

Output identifies the payload version/commit separately from the current setup
checkout's commit and dirty state. Both hosts exercise the public setup preview,
application, regular `run` with its recorder, and read-only `status`. Inventory
assertions prove the initially absent declaration is created by setup and preview
changes nothing; execution output and current evidence prove the declared gate
ran. Each case isolates its project, home and cache and needs neither agent host
installed or authenticated. Automatic completion remains disabled.

These are fixture results for the current entry point with an older published
payload. They establish neither live host trust/enforcement nor real deployment,
pilot adoption cost or maintenance cost. Status keeps unobserved host properties
explicitly unverified; existing lifecycle and ownership suites remain the source
of their respective regression coverage.
