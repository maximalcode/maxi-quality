# Versioned agent guard runtime

Agent guard code is distributed through a small launcher installed outside a
consumer repository. A migrated repository commits one data file,
`.claude/quality-runtime.json`, and hook wiring that invokes the launcher with
the consumer project root. No guard Python file or local shim is copied into
the consumer.

The lock has exactly these fields:

```json
{
  "schema": 1,
  "source": "maximalcode/maxi-quality",
  "version": "v1.2.0",
  "commit": "<lowercase full Git object id>",
  "guard_enabled": true
}
```

The launcher resolves a cache entry by that immutable commit. An explicit
prepare step reads each guard file from the pinned Git object and atomically
installs it under `<cache-root>/<commit>/`, with a content manifest. Hooks do
not download or change the cache, so two projects can use different pins
offline and a bad cache cannot silently select another release.

Prepare a cache entry from a checked out baseline source with:

```bash
python3 scripts/quality-runtime.py prepare \
  --source /path/to/maxi-quality --version v1.2.0 \
  --commit <lowercase-full-sha>
```

`prepare` requires the source to carry the matching release tag. The
`--allow-untagged-development` switch exists only for local fixture testing.
Install the launcher itself from a trusted pinned source, outside consumer
trees, with `quality-runtime.py install --source ... --commit ...`; its default
destination is `~/.local/bin/quality-runtime` (an explicit `--install-root`
is available for staging).

Migrate a consumer with:

```bash
python3 scripts/quality-runtime-migrate.py --target /path/to/project \
  --version v1.2.0 --commit <lowercase-full-sha>
```

The launcher defaults to `$MAXI_QUALITY_RUNTIME_CACHE`, then
`$XDG_CACHE_HOME/maxi-quality/runtime`, and finally `~/.cache/maxi-quality/runtime`.
The default hook commands resolve `$HOME/.local/bin/quality-runtime` directly,
including in GUI sessions with a restricted `PATH`. A missing launcher or cache is reported with
a repair instruction; Stop blocks the turn, the recorder exits nonzero, and
the pre-tool guards remain scoped to their policy decisions so ordinary shell
and edit actions remain repairable.

The runtime validates the lock, fixed source, release version, full commit
shape, fixed script allowlist and every cached file hash before execution.
The cache format remains 1; existing cache entries continue to work with
updated launchers. A single launcher can serve projects pinning different
guard releases, regardless of the launcher source in those releases. It does
not authenticate a Git repository or protect against a user who can modify
both the lock and cache. The cache is a
distribution convenience, not a security boundary; the repository's CI and
release process remain the source of release authenticity.

Migration also preserves unrelated `.gitignore` entries and adds the recorder's
receipt, temporary receipt and local event ledger. These records stay local to
the checkout; only the release lock is committed. Workflow-only consumers can
use `--guard-disabled` to create a lock without installing agent hooks.

## Diagnose an installation

After migration, inspect one checkout through the same launcher used by its
hooks:

```bash
quality-runtime diagnose --root /path/to/project
quality-runtime diagnose --root /path/to/project --json
```

`diagnose` is read-only. It validates the release lock and immutable cache,
checks the configured `gate_command` and that project settings have not
disabled hooks, and compares the owned hook matchers, executable branch,
execution mode, launcher availability and `permissions.deny` entries with the
selected installation profile. Unrelated hooks and permission entries are
ignored. The JSON result has stable keys (`schema`, `status`, `healthy`,
`installation_profile`, `release`, `configured_gate`, `checks`,
`live_enforcement`, `host_settings`, and `migration`) and each check names its
own pass, skip, or failure. Migration and diagnosis share a command builder
inside the single-file launcher. Diagnosis accepts exact generated commands,
the earlier generated form without a missing-launcher fallback, and direct
invocations with the generated quoting. It rejects other shell programs, even
if they might be equivalent; comments, wrappers and alternate root quoting
cannot stand in for the supported commands. An asynchronous owned hook is also
reported as broken because it cannot enforce a guard decision.

Launcher identity is checked by comparing its bytes with the trusted launcher
running the diagnosis, without executing or importing the candidate. That
comparison is independent of the project's guard pin. Run diagnosis through
the trusted launcher named by the hooks: a different copy, even one with only
a comment changed, cannot verify that candidate. This assumes the executing
diagnoser itself is trusted; it is not an authenticity check or proof that
Python, the shell or the host will execute it successfully. Relative paths use
the project root, and HOME/PATH resolution uses the diagnoser's environment.

`live_enforcement` and `host_settings` are `unverified`: a static diagnosis
cannot prove that an agent host loaded or executed a hook during a real
session, or infer host overrides from the project files.

The supported profiles are `versioned-with-samples`,
`versioned-without-samples`, and `disabled`. The latter is a deliberate
workflow-only profile and reports `not-enabled` when no guard hooks remain;
it never reports enforcement. `--guard-disabled` writes the disabled lock but
does not remove existing hooks. A disabled lock alongside recognized runtime
hooks or references to legacy guard scripts reports `broken`, requiring the
owner to reconcile the profile and wiring. Diagnosis does not repair either.
Malformed settings also fail; absent settings are valid for a clean disabled
profile.
The presence of `samples/expected/` selects the first profile, so a missing
sample hook is a failure in that profile rather than a way to opt out. A
checkout with the old copied or shared guard is classified as `legacy-copied`
or `legacy-shared` and reports the migration command.

An unavailable launcher, missing or corrupt cache, release-lock mismatch,
missing gate, or changed owned wiring is never healthy. A caller that cannot
start the launcher must treat that as unavailable, for example:

```bash
if command -v quality-runtime >/dev/null 2>&1; then
  quality-runtime diagnose --root "$PWD" --json
else
  echo 'quality-runtime is unavailable; diagnosis was not performed' >&2
  exit 2
fi
```

The diagnosis does not run the declared gate, write settings, receipts,
ledgers, locks or caches, and does not fetch dependencies. The existing
`prepare` operation remains the explicit cache writer.
