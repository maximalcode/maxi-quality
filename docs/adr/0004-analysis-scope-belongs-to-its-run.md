---
status: accepted
---

# Analysis scope belongs to the run that produced it

Accepted by the owner on 2026-10-09 while planning
[issue #95](https://github.com/maximalcode/maxi-quality/issues/95). Finding
counts cannot establish whether less code was examined. The quality workflow
and standing report therefore share an analysis-scope artifact contract, with
each artifact describing the execution that produced it. This records accepted
design boundaries, not delivered functionality or new measurement evidence.

## Separate runs retain separate evidence

The standing report performs its own full Layer 2 scan. Its finding history is
compared with the scope of that scan. Layer 1 job and Rust scope belong in the
quality workflow's artifact and summary; the standing report does not import
them from another run. A shared format does not imply a shared execution.

Importing the most recent quality artifact would put potentially different
commits, policies and scan modes beside the report's findings. An explicit
cross-run matching mechanism could address that, but is outside this decision.
The accepted consequence is that the standing issue does not contain a Rust
or Layer 1 scope history.

## Measurements state what they count

Every analysis tool already invoked by a workflow is represented, including
tools that did not execute. Measurements keep their tool-specific units;
source-file analysis, Git-history scanning and dependency-input analysis do
not become one total of files covered. Unavailable measurements are unknown
with a reason, separately from measurements that are not applicable.

Semgrep examined, unparsed and policy-excluded counts require measured evidence.
Other tools provide evidence-backed counts where available and explicitly
report unavailable measurements. Requiring numeric file accounting from every
tool before v1 delivery would expand the work beyond making existing analysis
honest. An unavailable count must never be substituted with zero.

Semgrep's examined count means unique targets it reports as selected or
attempted, not proof that every rule ran against every file. Unparsed counts
use the existing per-file error classification, including analysis gaps such
as timeouts, and may overlap examined targets. The UI states that relationship
explicitly. Policy-excluded counts mean observed policy exclusions, separately
from other ignore rules, target limits and disabled rules. They do not claim
how much additional analysis would run with the policy removed.

Rust scope describes the existing Clippy invocation without adding target
builds or feature combinations. Requested configuration is distinct from
evidence of the packages, targets and enabled features actually processed;
incomplete execution and cached results remain distinguishable.

## History identifies runs and exposes changed conditions

Every standing-report run and rerun attempt has its own history identity. The
latest 52 entries remain visible; existing daily entries are retained with
unknown analysis scope. This deliberately replaces same-day replacement,
which could erase a failed scan followed by an exclusion and a successful
rerun. Successful jobs from an earlier attempt are not silently represented as
freshly executed during a failed-jobs-only rerun.

Finding and scope changes are visible together. A smaller scan is not evidence
of improved code quality. Tool, version, active-rule, exclusion or scan-mode
changes are labelled even when counts stay equal. Meaningful numeric deltas
may still be displayed with that qualification; absent trustworthy predecessor
data, the comparison is unavailable rather than measured against zero.

Full scanner error output belongs in the artifact. Summaries can contain
bounded excerpts with a reference to that evidence; a count alone does not
preserve an error. Public baseline material contains no private Adopter data.

## Reporting does not change the gate

Scope reporting is non-gating in v1. A collection or publication problem is
visible but does not change the existing analysis verdict. Existing scanner
and job failures retain their failure behaviour; no minimum analysis-scope
threshold is introduced.

Ordinary detection, installation and analysis failures require an artifact and
summary that state missing evidence. Publication is attempted on cancellation,
but force-cancellation, runner loss and artifact-service failure are explicit
delivery limitations. An unconditional delivery guarantee would require a
separate recovery mechanism, which is outside this decision.

The artifact contract adds no consumer rollout, observation, Guardian
integration, new analysis configuration or release authorization.
