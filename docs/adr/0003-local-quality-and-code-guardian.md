---
status: accepted
---

# Local quality checks and an independently usable Code Guardian

Accepted by the owner on 2026-09-26. Setup complexity and uncertainty about
what actually runs undermine the baseline's usefulness. Local quality checks
are the common foundation; CI/CD is optional, and a Code Guardian can be the
primary way an Adopter uses the baseline. Consistent checks, verified agent
work and a clear account of what was checked are all required outcomes.

This records a design decision, not delivered functionality or a task list.
Existing tests and host observations retain their original scope. In
particular, fixture success does not establish everyday adoption cost.

## Product boundaries

- Local checks work without an agent or CI. The Guardian coordinates those
  checks, enforces the project's completion policy and assesses changes
  against an identified task description, issue or specification. Without a
  requirements source it can report defects, but cannot confirm requirements
  are satisfied. It asks for clarification when the gap affects the judgement.
- A skill and a local command share one setup and update path. Existing project
  checks are retained; gaps, conflicts and proposed tightening are presented
  for a deliberate choice. Adopters do not choose runtime storage models as
  part of ordinary setup.
- Explicit review is the initial entry point, with optional automatic
  completion checks. A complete implementation orchestrator is outside this
  scope. Automatic completion checks use agreed local checks and current
  evidence; a full AI review is explicitly requested or agreed once per task,
  rather than repeated after every small edit.
- A review invocation does not edit source or configuration. A review-and-repair
  invocation authorizes the executing agent to fix findings and rerun affected
  checks. Architectural concerns do not authorize an unsolicited large rewrite.
- Executed checks, failures, unchecked areas and AI concerns remain separately
  visible. Failed checks cannot produce a verified result; unavailable tools
  mean unverified. An explicit human override is visible and does not turn a
  failed or missing check into passing evidence.
- Assessment defaults to the change. Existing findings are reported separately;
  tools may inspect the whole project. Findings whose age cannot be established
  remain unclassified rather than being silently treated as old or new.
- Each project selects a fixed version for the new setup path. Updates are
  deliberate, describe relevant changes and run project checks. Existing
  installations remain usable during transition. This does not retroactively
  change the moving-v1 contract or authorize a breaking change under v1.

## Host selection and human decisions

Clarified by the owner on 2026-10-14. Claude Code is the primary working host;
Codex is used occasionally. Both must support the agreed quality workflow
through their native integrations. This is compatibility of the project policy,
not a promise that every host feature is identical.

Clarified again by the owner on 2026-10-16: ordinary use is centred on one
selected host. The setup skill targets the host in which it is invoked; a
host-neutral entry offers an explicit choice. Supporting both hosts does not
make installing, operating or verifying both a prerequisite for ordinary setup
or updates. The previously proposed requirement to verify both hosts together
before updating was not accepted. Shared quality logic and native host adapters
remain the design; the ordinary experience does not include dual-host
coordination.

Host selection is an installation choice, not an instruction to rewrite settings
whenever a different host starts. Existing integrations are shown before any
proposed transition. A host switch is deliberate and respects the same
ownership boundaries as pause and removal; the presence of another host's
settings does not authorize their deletion. This clarification does not impose
a blanket prohibition on another host's configuration existing in the repository.

Ordinary setup should be simple, with useful defaults and a configuration file
or guided setup for deliberate choices. These are interfaces to the same setup
and update path, not independently maintained configurations or a requirement
to choose a runtime storage model.

For the simplified update path, unsuccessful verification of a requested
update leaves the previous version active. The failed update evidence remains
available for diagnosis and the owner decides whether to proceed. This changes
the intended update experience from the shipped apply-then-check behavior; it
does not describe a completed change or silently reinterpret existing results.

Pausing and removal are separate operations for a selected host. Pausing retains
its setup and visibly marks automatic enforcement inactive. Removing an
integration removes only its owned settings. Either operation preserves the
other host's integration, existing project checks, unrelated settings and shared
runtime files used by other repositories. Paused enforcement is not passing
check evidence.

The quality goals include less duplicate and unnecessary code, fewer unsupported
assumptions, less manual lint work, and fewer unproductive automatic repair
cycles. False findings, stylistic noise and unrelated old findings all undermine
that goal. These are evaluation criteria, not a claim that a linter can establish
design quality or that less code is always better.

Independent review and targeted exploration of existing code are the desired
subagent capabilities in the surrounding workflow. Exploration supports reuse
before implementation; independent review challenges the resulting change.
The owner assigned their role definitions and workflow coordination to
maxi-skills. maxi-quality and Guardian own the checks, evidence, status and
substantive requirements of a quality review. Host adapters translate those
shared requirements into each host's native integration. Guardian remains
usable without maxi-skills; the public baseline does not require that private
repository, and does not duplicate its multi-agent workflow.

Human involvement belongs at the start, when a blocker or decision requires
judgement, and at the end. Routine corrections can proceed within the agreed
task. After at most two unsuccessful correction attempts for the same problem,
the agent stops repairing it and reports the cause or uncertainty, what it
tried, and the decision needed. An unresolved requirement or necessary
architectural decision requires human input immediately. Checks and requirements
are not weakened to manufacture a pass. This is the agreed workflow rule for
both hosts, not a new blocking hook. It does not expand Guardian into the
complete implementation orchestrator excluded above. A new blocking rule still
requires an actual escaped failure under the existing guard budget.

## Selective adoption and maintenance cost

Accepted by the owner on 2026-10-14. An Adopter may select only formatting,
only security checks, only Guardian around existing project checks, or the
complete baseline. Setup proposes a useful selection and allows deliberate
adjustments; it does not make every capability mandatory. The selected checks'
actual prerequisites still apply. This replaces the concept's original goal of
requiring both analysis layers in every repository; it does not remove either
layer or change an existing installation without a deliberate update.

Status distinguishes what was checked, what was deliberately disabled, and what
could not run because a prerequisite was unavailable. A minimal selection does
not imply that the whole baseline was checked. A successful selected check does
not turn an unselected or unavailable check into passing evidence.

The design succeeds only if both adoption effort in projects and maintenance
effort for the baseline owner improve. Reducing visible setup at the cost of
duplicated policy, more release coordination or additional compatibility work
is not sufficient. The pilot evaluates both sides against the acceptance
criteria below.

This decides independent selection of capabilities, not a number of packages,
repository boundaries or independent release schedules. Those remain open until
the actual usage and maintenance benefits justify them. No new guard rule,
language or external support obligation follows from this choice.

## Follow-up pilot acceptance

The owner accepted a bounded follow-up in the existing private Rust CLI/library
project: its existing checks plus Guardian, without requiring the complete
baseline or CI. Claude Code is used first, then Codex, across five ordinary
tasks. Following the 2026-10-16 clarification, these are separate observations
with each selected host, rather than a requirement for simultaneous operation.
The pilot includes setup, version changes, pause and removal;
deliberately failing lifecycle cases belong in a disposable copy. The project's
identity and task details remain private.

Acceptance requires:

- Setup through one entry point takes at most ten minutes of human work,
  without manual hook edits. Human effort is measured separately from command
  execution time.
- Each selected host clearly reports which checks executed and which are missing.
- Failed update verification leaves the previous version active. Pausing or
  removing one host preserves the other host and the previously agreed
  ownership boundaries.
- A comparable shared-rule change and version update require less maintenance
  time or fewer manual steps than the current approach, with shared rules still
  maintained in one place. The current approach supplies the comparison;
  separate repositories or fewer visible files are not themselves evidence of
  improvement.

These observations initially evaluate Guardian's independent use. They do not
establish formatting-only, security-only or every other capability combination,
nor does five-task observation establish long-term effectiveness. This records
the accepted evaluation boundary and success criteria, not completed results or
authorization to implement or roll out changes during this design conversation.

## Trade-offs and evidence

A CI-centred design leaves local agent work dependent on a later remote result.
A Guardian-only design would make ordinary quality checks depend on AI access.
The chosen separation makes both optional while sharing the project checks.
It also means a successful check and an AI judgement must never be collapsed
into an unexplained green result.

The first acceptance setting is an existing private Rust CLI/library project
with real owner work, using the selected agent host without a CI dependency.
Its identity stays outside public records. The evidence must cover setup,
checking an actual change, authorized repair when needed, and a clear account
of remaining uncertainty without making the owner choose runtime variants or
assemble multiple instructions. Successful migration is distinct from proof
of a fresh installation. No such new pilot result is claimed here.

This decision supersedes ADR 0001's exclusion of quality judgement and the
former concept exclusion of AI review. It preserves the public audience and
support boundary, free/OSS tooling rule, language admission criteria and
12-convention limit. It adds no paid-service requirement and grants no
release promotion or consumer rollout authorization.
