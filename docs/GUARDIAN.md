# Local Guardian check evidence

Run a project's existing declared gate without CI or an agent host:

```bash
python3 /path/to/maxi-quality/scripts/guardian.py run /path/to/project \
  --base HEAD --task 'named task or spec'
```

The project must be a Git working-tree root with a commit and an existing
`.claude/agent-guard.json` containing a nonempty `gate_command`. No host settings
are needed. The runner does not install tools or write source or configuration.
It executes the declared command from that root, whole, through the recorder's
Bash invocation. An `a && b` gate is one command with one exit code; when `a`
fails, no success is invented for `b`. Normal gate build outputs are permitted.
A gate that itself edits source leaves stale evidence and requires revalidation;
the runner is not a sandbox for arbitrary project commands.

`--base` resolves to a commit and must share an ancestor with HEAD. The report
records both the resolved base and merge base. This describes comparison context;
it does not narrow the gate to changed files or run a baseline checkout. `--task`
is an optional requirements reference, never a claim of requirements completion.

Add `--json` for machine-readable stdout. Gate stdout and stderr are retained as
local files and cannot corrupt the JSON stream. Human output names their paths.
Reports and logs live in a unique `guardian-*` directory inside this worktree's
Git metadata. They may contain private source, commands or paths; they are local
evidence, not a public or paste-safe summary. Removing that directory removes the
saved report and logs without changing the recorder's receipt.

The optional [Guardian skill](GUARDIAN-SKILL.md) invokes these same interfaces
and adds a separately identified AI assessment.

## Version 1 result contract

Every run emits a JSON object with `schema_version: 1`:

| Field | Meaning |
| --- | --- |
| `project_root`, `working_directory` | Canonical target root and command cwd |
| `comparison` | Requested base, resolved commit and merge base; unresolved values are null |
| `command`, `argv` | Exact declaration and the single shell invocation; null before selection |
| `checked_state` | HEAD and the recorder's before-execution content fingerprint, or null |
| `execution` | `not_run`, `succeeded` or `failed`, plus the actual child `exit_code` or null |
| `outcome` | `succeeded`, `failed`, `stale` or `incomplete` |
| `freshness` | `current`, `stale` or `unknown` at observation time |
| `analysis_scope` | `unknown`: no file-level coverage parser exists |
| `finding_attribution` | `unknown`: no finding-age parser exists |
| `requirements` | Optional reference and `assessment: not_assessed` |
| `receipt` | Existing recorder receipt path after recording, otherwise null |
| `stdout`, `stderr`, `report_path` | Local evidence paths, or null if not created |
| `created_at`, `error` | UTC observation time and any incomplete-run explanation |
| `next_step` | Recovery guidance for failed/incomplete execution, a rerun instruction for stale evidence, or null on success; never a prerequisite diagnosis |

Nonzero child exits are retained. The runner exits 0 only for a successful,
current observation, preserves a positive child exit, and otherwise exits 3.
A child terminated by a signal retains its negative subprocess return code in
JSON and yields `128 + signal` at the CLI. A shell's 127 remains a failed gate;
stderr words do not establish which dependency is absent. Inspection, declaration
and process-start errors are incomplete evidence, never a clean result.
Failed/incomplete runs point to the common entry's
[prerequisite recovery steps](GUARDIAN-SETUP.md#recover-an-unavailable-prerequisite).
Explicit inspection can establish a diagnosis for the owner's report; it never
rewrites the runner's observation or replaces a whole-gate rerun.

The report is an observation, not another receipt authority. The recorder still
writes `.claude/agent-guard-receipt.json`, and existing Stop behavior is unchanged.
The runner's explicit root overrides inherited Git checkout routing variables.

Check saved evidence after an edit or commit:

```bash
python3 /path/to/maxi-quality/scripts/guardian.py check /path/to/result.json --json
```

This returns the original outcome and current freshness, and exits 0 only when a
successful observation still matches the root, HEAD, content fingerprint and gate
declaration. It never updates the receipt or saved report. Freshness shares the
recorder's scope: Git-visible changed files, not ignored build outputs, external
dependency data or the environment. It cannot prove that tooling or remote data
has stayed unchanged. Rerun the gate when those inputs change.

Evidence: [`samples/guardian/`](../samples/guardian/README.md) runs real
subprocesses against invented repositories. Existing recorder and Stop fixtures
remain in [`samples/agent-guard/`](../samples/agent-guard/README.md).
