# Host smoke observation — 2026-09-05

**Unavailable. No live enforcement assertion passed.** The available Claude
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
