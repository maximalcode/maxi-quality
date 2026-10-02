# Local setup and pinned updates

Use the local entry from a trusted maxi-quality checkout (Python 3.11+ and Git):

```bash
python3 scripts/guardian.py setup /path/to/project
```

The default is a read-only preview. It reports the existing gate, runtime
profile and release, discovered Rust quality configuration, selected commands,
host integration, and proposed file contents. It does not run project commands,
download anything, prepare the persistent cache, or install a launcher.
Temporary staging directories are removed after validation. `--apply` explicitly
applies the same selection. Repeating an unchanged selection writes nothing.

For a project without a gate, setup lists Rust command suggestions and refuses
until a command is explicitly selected. It neither infers tests from a successful
command nor silently adds them to a lint-only gate. Select the whole command:

```bash
python3 scripts/guardian.py setup /path/to/project \
  --gate 'cargo fmt --check && cargo test --offline'
# Inspect the preview, then repeat with --apply.
python3 scripts/guardian.py setup /path/to/project \
  --gate 'cargo fmt --check && cargo test --offline' --apply
python3 scripts/guardian.py run /path/to/project --base HEAD --task 'local task'
```

Local checks need no AI, agent hooks, or CI workflow. The gate declaration lives
in `.claude/agent-guard.json` for compatibility with the existing recorder; this
filename does not require Claude Code. Existing declaration fields and compound
commands are preserved unless `--gate` explicitly selects a replacement.
Existing Rust manifests and quality settings are inspected and retained, not
rewritten to impose a stricter baseline. Toolchains must already be available;
setup does not provision them. The selected gate controls its own subprocesses
and any downloads those commands perform.

## Enable Guardian

Use the same entry with the selected native host and an immutable release:

```bash
python3 scripts/guardian.py setup /path/to/project --guardian codex \
  --version v1.2.0 --commit <full-commit-for-that-release> \
  --source /path/to/maxi-quality
```

The version and commit above illustrate the syntax; select a release that
contains native Codex support. Setup requires a matching local release tag and
validates every guard payload file before application. Missing or incompatible
payloads refuse with a prerequisite; there is no moving-release fallback or
implicit download. Add `--apply` after inspecting the selection.

Fresh Guardian setup uses the existing versioned runtime internally. It installs
a release-specific launcher outside the project, prepares the immutable cache,
and writes only the selected Codex integration, instructions, release lock and
runtime-state ignores. Unrelated hook entries and settings remain intact.
Normal setup has no storage-mode question. Existing versioned hook commands and
launcher selections are preserved on updates.

**Host trust and live enforcement remain unverified.** Review and trust the exact
hook definitions through Codex `/hooks`. A successful setup or gate run proves
neither host trust nor live enforcement. Project configuration that disables
hooks or adds ambiguous inline hook configuration must be reconciled first.

## Update deliberately

Repeat setup with `--version`, `--commit` and the local `--source` for the
requested release. Preview shows the old and requested pins and every proposed
file change. Application validates the payload before activation, then runs the
selected project gate through `guardian run`. The returned evidence retains the
actual command, output paths and exit code. Failed payload validation preserves
the previous usable selection. A failed post-update gate leaves the new pin
visible, reports `applied_checks_failed` and returns a nonzero status; it never
claims successful verification or silently rolls back evidence.

Existing copied/shared profiles are kept on their current delivery path. They
can preview and reapply their existing setup, and explicitly select a gate,
without being migrated. Selecting an immutable update for such a legacy profile
refuses with an explicit migration prerequisite; the existing
[legacy and versioned installation commands](QUALITY-RUNTIME.md) remain usable.
This pilot does not redesign those legacy delivery modes.

Unreadable, conflicting or unsupported configuration refuses before target
writes. Existing CI workflows are never changed. If workflows exist, PyYAML is
required to check their pins against a selected release; conflicts must be
resolved deliberately outside setup. The setup fixtures prove the local
mechanism only. Real migration cost, fresh-installation observation and live
host trust are separate evidence.
