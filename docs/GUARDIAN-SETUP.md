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

## Recover an unavailable prerequisite

Use this flow after a failed first run or post-update verification, including
through the Guardian skill. Preview's `verification: not_run` leaves check
prerequisites unverified. The common entry's `next_step` points here; the runner
reports **cause unknown**. Separate inspection can support a diagnosis. The
runner does not parse the shell command or classify stderr as a dependency failure.

1. Retain the run's JSON and its `stdout` and `stderr` files. Report the exact
   `command`, `argv`, working directory, `execution` and observed error/output.
   For setup verification, these are inside `verification`. A shell that starts
   and returns 127 is an executed, failed gate; a shell that cannot start is
   `not_run`/`incomplete`. An `a && b` failure may leave `b` unexecuted. Report
   only the subcommands whose execution the output or inspected script proves.
2. Read the selected gate and the project's setup instructions. Identify a
   prerequisite from that declaration, an inspected script or an explicit
   project instruction. Check its visibility from the project root in the same
   process environment used for the gate. For an inspected direct command named
   `fixture-check`, this lookup executes no check:

   ```bash
   cd "$PROJECT"
   bash -c 'command -v -- "$1"' guardian-inspect fixture-check
   ```

   If the project instructions or owner provide an installation path, inspect
   that specific path for existence and executable permission:

   ```bash
   test -f "$KNOWN_EXECUTABLE" && test -x "$KNOWN_EXECUTABLE"
   ```

   Record the lookup result and inspected path. An unsuccessful lookup proves
   only that this shell cannot resolve the name; it does not prove the tool is
   uninstalled. A file with executable permission may still have an unavailable
   interpreter or loader. A wrapper may change its own PATH or environment;
   inspect that context before attributing a transitive failure to this lookup.
3. Choose the next step from the evidence, keeping diagnosis separate from the
   retained execution result:

   | Evidence | Report and next step |
   | --- | --- |
   | Required executable exists at an inspected installation path, but the gate's lookup cannot resolve its name | **PATH visibility problem.** Show the known directory and propose a process-local PATH correction for a rerun. File presence alone does not prove the rerun will succeed. |
   | The gate or inspected instructions require a specific executable path and that path is absent | **Missing executable at that path.** Use the project's documented provisioning step, citing it, or ask the owner how it is provisioned. Do not describe this as only a PATH problem. |
   | An available check ran and inspection ties its failure to an assertion, lint finding or other check condition | **Failing check.** Report the finding and scoped repair; dependency-like stderr or exit 127 does not override that evidence. |
   | The prerequisite cannot be established, including an opaque wrapper with unexplained output | **Unknown cause.** Link retained output and name the missing evidence: inspect the wrapper's implementation/setup instructions or obtain them from the owner. Do not invent a package or installation command. |

4. State the concrete proposed correction before making it. Apply it only
   within the owner's authorization; otherwise leave it as the next action.
   There are no implicit downloads, global PATH/settings edits, weakened checks
   or hook-trust changes in this recovery flow. When a known directory has been
   deliberately selected, a one-process correction looks like this:

   ```bash
   PATH="$KNOWN_BIN:$PATH" python3 "$BASELINE/scripts/guardian.py" run "$PROJECT" \
     --base "$BASE" --task "$TASK" --json
   ```

   Keep the original declaration and rerun the **whole gate**, even if only its
   first command was unavailable. Report the new command, exit, output and
   freshness alongside the earlier failed attempt. Preserve the earlier report
   and logs; the recorder replaces its latest receipt only by executing again.
   `guardian.py check "$REPORT" --json` can check content freshness, but cannot
   validate a changed environment. An environment correction always needs a
   new run. Explanation or inspection alone never turns the failed run green.

The [invented prerequisite fixtures](../samples/guardian/README.md#prerequisite-recovery)
record the observed friction, recovery steps and remaining manual work. They
prove the local interfaces; they do not establish native host enforcement or
discovery of arbitrary toolchains.

## Enable Guardian

Use the same entry with the selected native host and an immutable release. The
host-specific skill invokes its own host by default; the host-neutral local
command requires an explicit selection:

```bash
python3 scripts/guardian.py setup /path/to/project --guardian claude \
  --version v1.3.0 --commit <full-commit-for-that-release> \
  --source /path/to/maxi-quality
```

For Codex, replace `claude` with `codex`:

```bash
python3 scripts/guardian.py setup /path/to/project --guardian codex \
  --version v1.3.0 --commit <full-commit-for-that-release> \
  --source /path/to/maxi-quality
```

The version and commit above illustrate the syntax. The selected immutable
release must contain the requested host adapter. Setup requires a matching local release tag and
validates every guard payload file before application. Missing or incompatible
payloads refuse with a prerequisite; there is no moving-release fallback or
implicit download. Add `--apply` after inspecting the selection.

Fresh Guardian setup uses the existing versioned runtime internally. It installs
a release-specific launcher outside the project, prepares the immutable cache,
and writes only the selected host integration, its project-local skill link,
instructions, release lock, selected-host ownership state and runtime-state
ignores. The project-local skill links to the skill in the trusted source
checkout, so the runner and instructions stay shared. An existing skill path is
preserved and reported as a conflict. Unrelated hook entries and settings remain
intact.
Normal setup has no storage-mode question. Existing versioned profiles retain
unrelated hooks and settings. A deliberate pinned update previews the old and
requested pins and owned hook changes, then diagnoses the newly selected
launcher before running the actual project gate against that candidate setup.
A passing gate commits the new selection. A failed, incomplete or catchably
interrupted check restores the prior lock, owned wiring, state and receipt while
retaining the failed run report. The old launcher remains untouched.

An update writes a small journal in the worktree's Git metadata before it
changes project files. Status and setup preview remain read-only and report an
unfinished transition as incomplete. After a hard process termination, run
`setup --apply` explicitly to restore the previous setup. Recovery proceeds
only when no recorded setup or gate process remains active and every candidate
file still matches the journal; user edits are preserved and reported as a
conflict. A hard power loss cannot run recovery itself, and another setup
process must be invoked to complete it. Do not start a second update while the
journal reports a live process.

If another Guardian host shares the project's runtime pin, preview names that
integration and the shared effect. An update that would move its effective pin
is refused until the installations are reconciled deliberately. Native host
trust and live hook enforcement remain separate observations.

**Host trust and live enforcement remain unverified.** Review and trust the
exact hook definitions in the selected host. For Codex, use `/hooks`. A
successful setup or gate run proves neither host trust nor live enforcement.
Project configuration that disables hooks or adds ambiguous inline hook
configuration must be reconciled first.

## Update deliberately

Repeat setup with `--version`, `--commit` and the local `--source` for the
requested release. Preview shows the old and requested pins and every proposed
file change. Application validates the payload, selects and diagnoses the new
launcher, then runs the selected project's gate through the normal Guardian
runner. The returned evidence retains the candidate pin, actual command, output
paths and exit code. Failed payload validation preserves the previous usable
selection. Failed or incomplete project verification restores the previous
selection and returns a nonzero status while retaining the candidate run report.

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
