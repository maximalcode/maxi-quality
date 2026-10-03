# Local Guardian pilot evidence

Observation date: 2026-10-03. Scope: [issue #273](https://github.com/maximalcode/maxi-quality/issues/273).

**Owner acceptance pending.** A separate invented Rust fixture completed fresh
local-check setup and checking. An owner-selected private Rust CLI/library
project also completed a real task and local review without CI. Its initial
setup exposed a baseline defect tracked separately in
[#283](https://github.com/maximalcode/maxi-quality/issues/283). The original
refusal remains evidence of unmet first-attempt usability; a successful repair
does not erase that cost. The owner has not yet given the required setup/clarity
verdict, so the complete pilot is not claimed as passed.

## Environment and prerequisites

| Item | Observed version or scope |
| --- | --- |
| Original baseline / fresh fixture | `d8c1ba172afee2fc84d6d7ab4c89eb72fee2a066` (development commit) |
| Corrected setup / final real review | `5ab652697412274f0f5ac97e73eccf8be195a4b7` (development fix for #283; not a release promotion) |
| OS | macOS 15.7.8, arm64 |
| Python | 3.14.7 |
| Git | 2.50.1 (Apple Git-155) |
| Rust / Cargo | 1.97.1 / 1.97.1 |
| rustfmt | 1.9.0-stable |
| Agent host | Current authenticated Codex desktop session; bundled CLI reports 0.153.4 |
| Host enforcement | Not installed or observed in the fresh local-only fixture |

Python, Git, Bash, Cargo, rustc and rustfmt were already installed. The invented
crate has no dependencies; its check ran offline. No CI completion, CI
credentials, additional provider account or tool installation was needed.
The CLI version identifies the available executable, not proof of native hook
support or trust in the desktop session.

## Fresh installation: observed

The fixture was materialized in a new temporary Git repository from
`samples/guardian/rust-local/`, renaming `Cargo.toml.fixture` and
`Cargo.lock.fixture` to their Cargo names. The existing `src/lib.rs` was copied
unchanged. `/target/` was ignored before the initial commit. An invented
`SPEC.md` required local formatting verification and the existing unit test,
preservation of the crate, no CI or host hooks, and idempotent setup.

Every operation below used the common `scripts/guardian.py` entry from the
recorded baseline. `PROJECT` denotes only that invented fixture. The comparison
base was its initial committed `HEAD`; the run recorded the resolved commit,
merge base, checked HEAD and content fingerprint locally.

| Operation | Observed result |
| --- | --- |
| `setup "$PROJECT" --json` | Exit 3, `refused`: no declared gate. Rust suggestions were shown; no files changed. |
| `setup "$PROJECT" --gate 'cargo fmt --check && cargo test --offline' --json` | Exit 0, `preview`: proposed only `.claude/agent-guard.json`; no files changed. |
| Same selected setup with `--apply` | Exit 0, `applied`: wrote the gate declaration; `verification: not_run`. |
| Repeat the same application | Exit 0, `unchanged`: no proposed changes and identical file contents. |
| `run "$PROJECT" --base HEAD --task SPEC.md --json` | Exit 0, `succeeded`, current evidence. |
| `check "$REPORT" --json` | Exit 0, original outcome `succeeded`, freshness `current`. |

The exact executed gate was:

```bash
cargo fmt --check && cargo test --offline
```

This remained one compound command and one recorded exit code. Its success and
captured Cargo output establish that formatting verification completed and Cargo
ran **one unit test, passed**, followed by **zero documentation tests**. There
was no failed check or repair in this fresh observation. Clippy, dependency and
secrets scans were not selected or run. The runner correctly left file-level
analysis scope and finding attribution `unknown`, and requirements assessment
`not_assessed`.

Byte comparisons confirmed that the manifest, lockfile and source matched the
fixture originals after execution. No `.github/`, `.codex/` or
`.claude/settings.json` was created. Ordinary build output and local recorder
evidence were created. The before/after comparisons around discovery, preview
and reapplication passed.

## AI assessment and usability evidence

The current agent read `skills/guardian/SKILL.md` and the setup/result
documentation, then used the same entry as the CLI. Separately from the runner's
unassessed requirements field, the AI assessment is that the observed fresh
fixture met its invented setup spec: selected checks executed, crate contents
were preserved, no host hooks or CI workflow appeared, and reapplication was
idempotent. This assessment concerns only the invented fresh fixture; the separate real
task is described below.

The agent explicitly selected one compound gate after discovery refused to
guess. There were no storage-mode choices, manual repairs or owner interventions
in the fixture. There were six Guardian invocations including discovery,
preview, application, the idempotence probe, execution and freshness checking.
The setup commands took approximately 0.5–0.7 seconds each and the gate invocation
4.7 seconds on this machine; these are command timings, not human onboarding
time or real-project adoption cost.

An agent operated the flow after reading multiple existing documents. This does
**not** demonstrate that an owner can reach the result from one setup guide, that
the host discovers an installed skill, or that the setup/clarity goal is met.
No global skill installation or settings change was performed. No human
override was supplied or inferred.

## Existing installation and real task

The owner selected an existing private Rust CLI/library project and authorized
setup, a small real task, and local review. Work took place on an isolated
branch from its established development base. The accessible task source,
resolved base, final revision, source/configuration snapshots, exact commands,
reports and PR remain private. The public record contains aggregate evidence
only; no consumer identifiers, source excerpts, paths or task numbers.

The existing installation used the copied legacy guard with one declared gate.
Its project instructions intentionally share a local symbolic link. The common
setup preview refused that link even though this operation did not write
instructions. No target file changed. The defect was reproduced with invented
files and returned to step 2 as #283; it was not repaired by changing the
consumer's instruction arrangement or manually composing a different setup.

After the fix passed the recorded baseline gate (92 guard cases, contract
validation and 19 Guardian subprocess tests) and both review axes, the same
common entry was repeated on the real checkout. Preview succeeded; apply and
reapply returned `unchanged` with no file changes. The selected gate and copied
legacy profile were preserved. The final review then ran through that same
entry, returned exit 0, and passed the subsequent freshness check. Git-visible
source/configuration hashes matched before and after all five operations. This
proves adoption of the new entry around an existing installation, not conversion
to a new runtime profile. It also does not prove native Codex integration.

The task added a missing fixture-validation step to the existing local gate.
Four independently broken disposable fixture copies each failed and identified
the failing fixture. Committed fixture data was preserved. The full gate then
reported one dependency advisory. Running the same gate on an untouched checkout
of the comparison base reproduced the same advisory; this establishes the age
of that particular finding. It does not classify every possible finding as old.
A narrow dependency patch repaired it, and the entire gate was rerun.

The final task revision passed local fixture validation, formatting, compiler
lint checks, tests and dependency-policy checks: **16 tests passed, two existing
live-network tests were ignored**. Four fixture renders succeeded. A non-failing
license-allowance warning remained visible. No CI completion was needed. The
runner retained the whole declared gate as one command rather than inventing
per-tool result objects; logs supplied the tool-specific observations above.

Separately sourced AI assessment found the task requirements satisfied. Standards
and Spec review each reported zero findings on the committed change. The
runner's requirements field remained `not_assessed`; its analysis scope and
finding attribution remained `unknown`. No human override was supplied. Review
findings and base reproduction did not rewrite the failed observations into
success. An initial exploratory run overlapped implementation edits, produced
stale failed evidence, and was discarded as a verification result; later runs
used fixed content and preserved the failed history.

## Adoption cost and limits

The selected dependency-check executable was already installed but absent from
the session's PATH. A process-local PATH addition made it available; no global
configuration or package installation was needed for that prerequisite. The
dependency patch itself required the package manager's ordinary registry access.
This real-project observation was local and independent of CI, not an offline
execution claim. The separate fresh fixture did run offline.

The observed interventions were one session PATH correction, one baseline setup
bug repair, and one consumer dependency patch followed by revalidation. No owner
intervention was required after target/task selection. Agent-operated recovery
is not evidence of effortless owner onboarding; there is no measured human
onboarding duration. The existing profile is preserved rather than converted to
another storage scheme. Automatic completion was not opted into, and native
host trust or enforcement was not observed.

The owner was asked for a setup/clarity verdict after receiving the real results;
no answer has yet been recorded. Autonomous execution authorization is not an
acceptance verdict. This is also not evidence of long-term reliability,
natural-session usefulness or false-positive rate, and none of the guard fixture
counts is used as a substitute for adoption-cost measurement.

Raw private reports remain local. Public fresh-fixture JSON reports, stdout/stderr,
resolved fixture commits and file comparisons are retained with the session's
worktree metadata and temporary fixture, not committed here. Neither kind of
record proves file-level analysis coverage beyond its stated limits.
