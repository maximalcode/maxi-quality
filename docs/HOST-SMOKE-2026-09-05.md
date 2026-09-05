# Host smoke observation — 2026-09-05

**Unavailable for both hosts. No live enforcement assertion passed.** The available Claude
Code 2.1.236 reported a logged-in account through `auth status --json`, but the
actual disposable repository-root launch failed with an expired OAuth session
that could not be refreshed. No host hook lifecycle event was emitted.

The [public outcome record](../samples/agent-host-smoke/observation-2026-09-05.json)
contains only fixture metadata, versions and outcome codes. The tested guard
revision was `16b1e41145bbec0413e4dfdc9abdec1b6bcaa626`, prepared in an isolated
cache with the development label `v0.0.0-host-smoke`. Fixture `host-00` used the
`versioned-without-samples` profile, a declared deterministic `python3 gate.py`
gate, and a harmless uncommitted edit. Read-only installation diagnosis was
healthy; its live-enforcement and host-settings fields remained unverified.

The launch used the existing host and normal settings selection, with print
mode, verbose stream-JSON output, hook lifecycle events, no session persistence,
and no exposed tools. This was the initial real-host probe during development
of the repeatable command, before the complete harness was in place. It is
recorded as an unavailable attempt, **not** a successful harness run. Raw output
was retained privately; the disposable repository and cache were removed.

The command's offline tests subsequently reproduced this failure shape: a
successful authentication-status query followed by an authentication error
returns exit 2 with `host-authentication-unusable`, preserves the separate
healthy diagnosis, and leaves the negative control `not-run`. Offline protocol
simulation also checks the recorder, content changes and removed wiring, but
direct fixture hook calls and invented host messages are not live evidence.

For [#256](https://github.com/maximalcode/maxi-quality/issues/256), the real
no-receipt refusal, fresh receipt allowance, stale receipt refusal, ordinary
shell allowance, skip-verification denial, linked-worktree and subdirectory
observations, and wiring-removed negative control remain **unobserved**. The
issue is incomplete. No host switch, credential change, installation, or user
settings override was used to obtain a different result. This synthetic
attempt contributes nothing to natural-session measurements.

The complete harness also made a separate native Codex CLI 0.153.3 attempt,
recorded in the [Codex public outcome record](../samples/agent-host-smoke/observation-codex-2026-09-05.json).
It used the committed guard revision
`76db4f3bba15a09d6ceae81b58908e216b537c8d` and the same isolated development
runtime profile. Native `account/read` was usable. Before any model turn,
`hooks/list` at `host-01` (repository root), `host-02` (linked worktree) and
`host-03` (subdirectory) each reported zero project hooks. The independent
installation diagnoses were healthy. The command returned exit 2,
`host-project-hooks-not-discovered`; all enforcement observations remained
empty. `host-04` had zero discovered hooks after removing its wiring, but its
real-turn negative assertion remained `not-run`.

These newly created projects had received no project or hook trust onboarding.
No task or model turn was started by the adapter, and no trust or configuration
was changed to force discovery. Raw protocol responses, which may contain
account information, were retained only in new private directories outside
Git with owner-only directory/file access. The owned repositories and cache
were removed. This preflight result establishes neither runtime invocation nor
a passing negative control.

A separate read-only comparison of the native hook source showed that Codex
0.153.3 discovers a linked worktree's project hooks from its original checkout:
three hooks appeared when the same candidate JSON was temporarily present in
the original checkout, and disappeared when that source was removed. The
candidate file was removed after inspection; none of those hooks was trusted
or executed. The harness models that source location in its disposable layout.

The Codex adapter's offline protocol test covers the full phase sequence and
removed-wiring control, including Stop continuation and interruption. Its
shell assertion deliberately requires native command request/result items;
whether PreToolUse denial actually emits the assumed item sequence remains
unverified. A host that omits it cannot pass from hook feedback alone. Both
hosts' live observations are still required to complete #256.
