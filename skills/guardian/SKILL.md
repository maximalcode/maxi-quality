---
name: guardian
description: Set up local quality checks, review a change against a named task, or review and repair scoped findings using Guardian evidence. Use for requested Guardian setup, pinned updates, review, or review-and-repair.
---

# Guardian

Use the current authenticated agent host for AI assessment and the project's
existing local checks for execution evidence. Local checks work without AI or CI.

## Establish the operation

Resolve this file's physical path (follow installation symlinks). Its directory
is `skills/guardian` in a trusted maxi-quality checkout; the checkout root is
`BASELINE`. Verify `BASELINE/scripts/guardian.py` exists. If the skill was copied
alone, report the missing checkout and use the installation instructions in
`BASELINE/docs/GUARDIAN-SKILL.md` once that checkout is available. Do not fetch or
upgrade runtime code during review.

Read the target project's agent and contribution instructions. Establish its Git
root, the requested operation, task/issue/spec source and comparison base. Read
the supplied requirements; a name or inaccessible link alone is not assessed
requirements. Resolve the base to a commit and retain it throughout the review.
Ask for a base if neither the request nor project context establishes one.

Default to **review**. **Review-and-repair** authorizes fixes only within the
named task and agreed scope. **Setup/update** changes configuration only when
requested. This skill does not authorize commits, publishing, a background
coordinator or an architectural rewrite.

## Setup or deliberate update

For this operation, read `BASELINE/docs/GUARDIAN-SETUP.md`. Invoke the same local
entry as a human, starting with its read-only preview:

```bash
python3 "$BASELINE/scripts/guardian.py" setup "$PROJECT" --json
```

Preserve the existing whole gate and quality settings. When a gate is absent,
show the discovered suggestions and establish the user's intended checks before
selecting `--gate`; a lint-only command does not prove tests ran. Preview the
selected arguments, explain their concrete changes, then apply that same
selection with `--apply` within the user's setup authorization. A pinned update
uses the explicitly selected immutable `--version`, matching `--commit` and
local `--source`. Keep runtime storage internal to setup.

Automatic completion is opt-in. Use `--guardian codex` only when that native
integration is requested; it uses local checks and current recorder evidence,
not a full AI review after each edit. Report configuration, trust and observed
native enforcement separately. Missing hook support, disabled features or
unaccepted definitions mean **unavailable enforcement**; unknown host trust or
unobserved enforcement stays **unverified**. A script or setup success is not a
live host observation. Preserve setup refusals and failed post-update checks.

## Review and measured evidence

Read `BASELINE/docs/GUARDIAN.md` for result fields and freshness limits. Capture
the initial source/configuration state, including existing uncommitted work.
Inspect the declared gate before execution: review-only must leave source and
configuration unchanged. If the gate formats, repairs, generates tracked source,
or has uncertain write behavior, use an isolated copy including the current
changes, or report that check unavailable pending a safe execution method. Label
copy-based evidence with its actual root; it cannot authorize the original
working tree's completion. Logs, recorder receipts and ordinary build outputs
are permitted. Never silently restore or discard user changes.

Run the existing whole gate, including on a failing result:

```bash
python3 "$BASELINE/scripts/guardian.py" run "$PROJECT" --base "$BASE" --task "$TASK" --json
```

Omit `--task` when no source was supplied. Preserve the returned JSON and read
its stdout/stderr files. Do not replace execution with an AI prediction, split a
compound command into invented per-check passes, or treat an unavailable command
as success. If a shell starts and returns 127, retain the failed execution; only
separate evidence can establish the missing prerequisite. A command that could
not start is unexecuted/incomplete, distinct from a check that ran and failed.

Assess the diff, current uncommitted changes and supplied requirements using the
current host. Keep AI concerns, requirements conclusions and unchecked areas
separate from the runner's observations. Without an accessible task/spec, state
**“Cannot confirm requirements completion.”** Without an authenticated host,
AI assessment is **unavailable**; the local runner remains usable.

Finding age defaults to **unknown**. Label a finding pre-existing only with
cited evidence: for example, the same finding reproduced at the fixed base with
the same relevant command/configuration. A red base alone cannot attribute every
current failure. Keep verified old findings separate and preserve current
failures. AI opinion or an unchanged line alone does not prove a failure's age.

## Authorized repair and final report

In review mode, report scoped repair suggestions and compare the final source
and configuration with the initial state. Unexpected changes mean the read-only
contract was not met; report the discrepancy without claiming a clean review.
In review-and-repair mode, fix only the authorized findings, preserve unrelated
work, and treat all prior check evidence as potentially stale after edits.
Rerun the whole declared gate after repairs (this pilot has no reliable mapping
from edits to individual affected checks). Retain the failed attempt as history.
Stop and report a blocker if repair needs broader scope or remains unresolved
after two attempts.

Before claiming verification, check the final report against the current tree:

```bash
python3 "$BASELINE/scripts/guardian.py" check "$REPORT" --json
```

Rerun on stale/unknown evidence; changed tooling or external inputs also require
a new run. Never write a receipt or modify execution evidence by hand.

Report these independently, with local evidence links when available:

- **Context:** operation, project, task source (including accessibility), resolved
  base/merge base, checked HEAD and content fingerprint.
- **Executed checks:** exact command, actual exit code, outcome, freshness,
  output/report paths and any checks a short circuit left unexecuted or unknown.
- **Unavailable/unchecked:** missing prerequisites, unknown analysis scope,
  unexecuted checks, and host enforcement status when requested.
- **AI assessment:** requirements assessment and concerns with file/line evidence,
  separated into introduced, evidenced pre-existing and unknown age. AI
  conclusions do not change the runner's `requirements: not_assessed` field.
- **Repairs:** authorized edits, remaining defects and post-repair evidence.
- **Human override:** none unless the user explicitly decided to proceed despite
  named failed/unverified evidence. Quote or faithfully record that decision and
  its scope separately, keeping those outcomes visible. The agent cannot issue
  an override, infer one from silence, rewrite a failed receipt, or bypass hooks.

Keep project paths, source, task identifiers and logs local unless explicitly
authorized for a destination where they may be shared.
