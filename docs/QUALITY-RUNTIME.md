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
the Claude pre-tool guards remain scoped to their policy decisions so ordinary
shell and edit actions remain repairable. The Codex patch adapter denies patches
when unavailable; shell access remains available to repair the installation.

The runtime validates the lock, fixed source, release version, full commit
shape, fixed script allowlist and every cached file hash before execution.
Format 1 retains the original five-script allowlist. Format 2 adds the Codex
patch adapter. Preparation selects the format from the pinned Git tree; existing
format-1 entries remain valid and unchanged under the updated launcher. A single launcher can serve projects pinning different
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
`live_enforcement`, `host_settings`, `host`, and `migration`) and each check names its
own pass, skip, unverified state, or failure. Migration and diagnosis share a command builder
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

## Native Codex installation

The versioned migration accepts `--host codex`; its default remains `--host
claude`. Codex uses `.codex/hooks.json`, while Claude Code uses
`.claude/settings.json`. Both files may coexist: each host loads its own
configuration. The host is selected explicitly, never inferred from a model or
provider. Codex installation needs Python and Git, with no Claude CLI or login.
The older `adopt.sh --agent` copied/shared profiles remain Claude profiles.

Select a release containing `codex-patch-guard.py`, install the updated launcher
and prepare that release as above. Then run:

```bash
python3 scripts/quality-runtime-migrate.py --target /path/to/project \
  --host codex --version <release-version> --commit <lowercase-full-sha>
quality-runtime diagnose --root /path/to/project --host codex --json
```

Use `--launcher /absolute/path/to/quality-runtime` for a staged installation.
A Codex migration leaves Claude settings and copied guard files intact. It
preserves unrelated Codex hooks and adds a checksum-owned region to `AGENTS.md`;
an edited region or a symlink escaping the project is refused. Its recorder
command resolves the Git root, so starting a session in a subdirectory still
uses the right checkout.

The release lock, gate declaration, receipt and ledger keep their historical
`.claude/` paths as shared engine data. A project using both hosts has one gate
and one release pin: changing that pin explicitly upgrades both. Old pins stay
usable for Claude; diagnosis rejects a Codex installation pinned to a release
without its adapter. A patch invocation against such a pin is denied rather
than treated as inspected.

The native configuration routes `Bash` to the existing Git-verification guard,
`apply_patch` to the patch adapter, and `Stop` to the existing receipt gate.
The adapter uses the shared cited-sample rule. It also protects the recorder's
receipt and every path under `samples/expected/`, because Codex does not apply
Claude's `permissions.deny` array. Adding or replacing expected findings requires
the normal manifest generator, not a hand-written patch.

Patch inspection handles additions, deletions, update hunks, moves and multiple
files. It checks both ends of a move, including overwriting an existing cited
sample. It uses line-count changes rather than duplicating Codex's fuzzy hunk
matching. Unrecognized patch syntax and malformed patch events are denied with
a repair message. Same-size changes that defuse a finding still need CI; shell
writes remain outside the file-tool filter. The shared Stop loop guard can allow
a continuation with a warning, as documented in the agent contract. These hooks
guard accidental drift, not deliberate tampering.

**Review before relying on enforcement.** Codex's project layer must be trusted,
and `/hooks` must show the exact definitions reviewed and enabled; changing a
hook requires another review. User, system, plugin and inline project hooks can
also contribute behavior. Hosted and some specialized tools do not use the
same hook path. These host boundaries follow the
[official Codex hooks documentation](https://learn.chatgpt.com/docs/hooks).
Use normal project and hook trust onboarding; migration never trusts hooks or
changes user settings on your behalf.

`diagnose --host codex` inspects the native JSON wiring and the project's TOML
settings when Python 3.11+ can parse them. A local disabled hooks feature fails
diagnosis. Other sources, session overrides and persisted trust remain
`unverified`, as does live enforcement. `healthy: true` establishes an intact
installation, not discovery or execution by a running host. The separate live
smoke described below currently targets Claude Code.

`python3 samples/codex-agent-guard/test_codex.py` exercises native payloads,
generated commands from a nested directory, Stop/recorder transitions, migration,
diagnosis and format-1/format-2 compatibility in temporary Git fixtures. It
makes no live Codex enforcement claim. This baseline's own `.codex/hooks.json`
invokes the same scripts directly from the Git root, avoiding a release pin
that refers to the repository containing it; `check-agent-contract.py` guards
that wiring in the existing CI context.

## Observe host enforcement

The separate opt-in command uses an already installed Claude Code and its
existing authentication. Run from a baseline checkout with Python 3 and Git:

```bash
python3 scripts/agent-host-smoke.py --run-live
```

It creates disposable Git repositories and an isolated development runtime
cache from `HEAD`; `--commit <full-sha>` selects another committed guard
revision. The label `v0.0.0-host-smoke` is local fixture metadata. No runtime is
installed, pinned project upgraded, user setting edited, dependency downloaded,
or real push requested. Git routing inherited from the caller is excluded
from fixture operations. The temporary repositories, receipts, ledgers and
cache are removed when the command returns, including failure paths.

`--claude /path/to/claude` selects an existing executable. No other host is
selected automatically. `--timeout 90` bounds each host turn. The launch uses
`--print --verbose --output-format stream-json --include-hook-events
--no-session-persistence`. Stop probes expose no tools; shell probes expose
only Bash and authorize Bash for that invocation. Existing user, project and
local settings remain in the host's normal selection. The command does not
override a setting that disables hooks, skip permissions, or retry through an
access refusal. The host may write its own normal local operational metadata;
the command does not edit it.

Each supported root first gets the read-only `diagnose` result from the same
launcher its hooks use. That result stays separate, with `live_enforcement`
and `host_settings` still `unverified`. The fixture uses the
`versioned-without-samples` profile and the deterministic gate `python3 gate.py`.
It then observes these phases in successive fresh real host sessions in the
same disposable repository:

1. A tracked harmless edit without a receipt must produce a host `Stop`
   response containing the guard's block decision, supported by the matching
   host session's `no-receipt` ledger entry.
2. The command runs the real runtime recorder with `--gate`. The next Stop must
   produce a host event and the matching `pass` ledger decision, followed by a
   successful turn. A `loop-guard` allowance cannot satisfy this assertion.
3. Another edit must produce a host block plus `content-changed` decision.
4. An exact ordinary Bash request must execute its harmless marker write.
5. An exact Bash request to an executable named `git`, with `commit --no-verify`,
   must receive the guard's host hook denial and a failed tool result before
   its tripwire executes. That executable only writes a marker: even missing
   enforcement cannot commit, push, or reach another repository.

Shell phases require exactly one tool request. The host's hook response has no
tool-use identifier, so additional requests make attribution ambiguous and
produce `ambiguous-tool-requests`, never a passing enforcement assertion.

The phases run at a repository root (`host-01`), a linked-worktree root
(`host-02`), and a subdirectory (`host-03`). The subdirectory outcomes are
reported independently with the documented
[#222 limitation](https://github.com/maximalcode/maxi-quality/issues/222).
Missing hooks there never count as protection, and do not make a successful
supported-root result into a claim of subdirectory support. A fourth fixture
(`host-04`) removes its own hook wiring, diagnoses that broken installation,
and repeats the **same** no-receipt assertion. It must fail with
`hook-not-observed` after the host completes a turn. Unavailable authentication
or a host error cannot satisfy this negative control.

The public JSON uses fixed fixture identifiers, versions and outcome codes;
it strips paths and detailed text from installation diagnosis. Exit 0 means
both supported roots passed every assertion and the negative control detected
non-invocation; exit 1 means an enforcement assertion failed; exit 2 means the
host or a prerequisite was unavailable, with a concrete reason code. A logged-in
status followed by an expired-token error is `host-authentication-unusable`,
never a pass. Other hosts and unobserved integrations remain unverified.

Raw host streams, launch arguments, diagnosis details and per-phase ledger
evidence are deleted by default. To retain them, pass `--private-output` naming
a **new directory outside Git checkouts** under an existing private parent.
Evidence directories and files have owner-only access from creation through
copying into the retained directory. Never publish those files.
The `synthetic-host-smoke` measurement is separate from natural-session
measurements and must not be added to an Adopter ledger or natural-session
counts. The
[offline protocol fixtures](../samples/agent-host-smoke/README.md) exercise the
command without authenticating; their invented host messages prove no live
integration.

The host event adapter follows the published
[Claude Agent SDK message contract](https://code.claude.com/docs/en/agent-sdk/typescript#sdkhookresponsemessage).
A lifecycle event alone is not a passing guard decision, and voluntary model
compliance is never evidence of invocation. The first dated live attempt is
[recorded separately](HOST-SMOKE-2026-09-05.md); it was unavailable, so successful
live enforcement and the live negative control remain unobserved for #256.


### Codex discovery observation — 2026-09-05

Codex CLI 0.153.3 and its app-server discovered all three project hooks from the
same native JSON in the original trusted baseline checkout. Each was visible
as **untrusted**, with no errors or warnings. This proves project discovery;
no hook was trusted or executed by these read-only inspections.

The linked worktree returned no project hooks, including experiments with a
project TOML file, inline hooks and an explicitly enabled hooks feature. A
harmless Stop hook supplied through session flags was visible as untrusted.
Discovery therefore differed by checkout; the exact worktree/project-layer
cause remains unresolved. Neither observation establishes live enforcement.
