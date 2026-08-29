# The agent guard's test suite

Sixty-eight cases, one JSON file each, in [`cases/`](cases). Run them:

```bash
python3 scripts/agent-guard/selftest.py
```

`ci.yml`'s `agent-guard` job runs exactly that, and it is a required check on
both branches. The same job runs `scripts/check-agent-contract.py`, which holds
the count in the line above to the number of files in `cases/` — the count is
this README's to state and that script's to read, never to update.

## Five kinds of case, and why the fifth is different

| Prefix | `hook` | What it runs |
|---|---|---|
| `stop-` | `stop` | the real `stop-gate.py`, as a subprocess, on a real repo |
| `edit-` | `sample` | the real `sample-guard.py`, the same way |
| `noverify-` | `noverify` | the real `no-verify-guard.py`, the same way |
| `changed-` | `changed` | `changed_files()` directly, on a real repo |
| `deny-` | `permissions` | **nothing runs.** See below |

`stop-`, `edit-` and `noverify-` run the real script as a subprocess with a
real payload on stdin, and parse stdout the way Claude Code parses it — nothing
imports a hook and calls a function. `stop-` and `edit-` build a real git
repository first; `noverify-` does not, for the reason two sections down.
`changed-` is the one direct call, and it exists because a fingerprint over the
wrong file set is still "some hash" and no hook decision can tell the two apart.

`deny-` cases cannot do that, and it is worth being blunt about it. A
`permissions.deny` rule is enforced inside Claude Code; there is no headless way
to make one fire. So those cases assert the rules' **internal consistency**
against `configs/agent/settings.json`: that every rule names `Edit` or `Read`
and not one of the tool names Claude Code accepts and never consults, that it
carries a path rather than a bare tool name or a `param:value` form, that the
pattern parses, and that it matches the literal paths it is meant to — and only
those — against a planted tree.

That is the `configs/editor/` shape, and the price is the same one
[`configs/agent/README.md`](../../configs/agent/README.md) §5 sets out in full —
including why it is not a precedent. Do not restate it here; there are already
enough copies of that paragraph to make the next policy change a five-file
edit.

## Why the assertion is the decision, not the exit code

All three hooks always exit 0 and carry their verdict in JSON — the hook
docstrings give the reasons, and they are different for the two events. So
`exit 0` is equally true of a hook that blocked, a hook that allowed, and a hook
that silently did nothing at all. The suite asserts the **parsed decision**, and
asserts that an allow prints *nothing whatsoever*. A hook that grows a stray
`print` still exits 0; here it fails.

## Why a real git repo per case

The two things most likely to break are both git-shaped: what counts as a
changed file (a rename is two paths, an untracked file is a change, a deleted
one still has to hash), and whether a path comparison survives a symlink. The
temp dir is `realpath`-resolved in the fixture **on purpose** — on macOS
`/tmp` is `/private/tmp`, so a hook that compares paths without resolving both
sides passes on a runner and fails on a developer's machine.

The `noverify-` cases set `"git": false`: the command guard reads a string and
has no opinion about the repository it is standing in, so building one would be
a fixture asserting something the hook does not do.

## The negative controls matter as much as the blocks

Seventeen cases exist to prove the guards stay out of the way: an edit outside
`samples/`, an edit that adds a manifest entry, an edit that grows a fixture, an
edit to an uncited clean fixture, a brand-new manifest, a tool the matcher should
never have routed here, an ordinary `git commit -m`, `npm test -- -n`,
`git push -n` (which is `--dry-run`, not `--no-verify`), and the four shapes
where a hook-skipping flag is really an option's VALUE — `-m "--no-verify"`,
`--message --no-verify`, `--message=--no-verify`, and anything after a `--`
pathspec terminator. Four more arrived with #178, and they are the same
argument one level in: the `Stop` hook now checks the receipt against the
DECLARED gate, so every honest spelling of running it has to keep standing — a
one-command gate run the ordinary way, the `bash -c '...'` form people used
before `--gate` existed, a plain declaration run wrapped, and a declaration
quoted with `"` rather than `'`. A guard that also objects to ordinary work is a guard someone switches
off within a day, and then the real one is not running either.

Five more are the fail-open cases — not a git repo, a payload with no
`file_path`, a `Bash` payload with no `command`, a `Bash` command whose quotes do
not balance, a stop that has already forced one continuation. An agent hook cannot be bypassed by the party
it constrains, so its own plumbing failures must allow. Those cases are what
stop a "harden this" change from quietly making a broken install unsurvivable.

## Measured teeth

A fixture suite that passes a broken guard proves nothing, so every shipped
script was mutation-tested — the first four on 2026-08-22, `no-verify-guard.py`
and the `permissions` mode on 2026-08-23. The full tables, including the rows
that no fixture can reach and the argument for why, are in
[`configs/agent/README.md`](../../configs/agent/README.md) §5. The headline: the
worst mutation of each script fails between 1 and 9 cases, and four lines across
the whole contract are marked uncovered rather than left looking tested.

It also earned its keep before it ever ran in CI: `stop-02-receipt-pass-fresh`
caught a real self-reference defect — the receipt is written after the
fingerprint it records and is itself an untracked file, so it changed the hash it
was storing and no session could ever have ended. Reading the code did not find
that.

## Adding a case

Add the JSON file, watch it fail, then change the hook until it passes. Each case
carries a `why` field and it is not decoration — a case whose reason is "more
coverage" is a case nobody can correctly delete later. State the failure it
stops.

A `stop-` case can run the wrapper for real instead of hand-writing a receipt:
`record: {"command": [...]}` is the argv form, `record: {"gate": true}` is
`--gate`, which reads the case's own `config`. Prefer either to a hand-written
receipt when what you are asserting involves the wrapper at all.

`fingerprint: "current"` in a receipt is computed by the runner after the tree is
final, never written into the fixture. A hash copied into a case file rots the
moment a fixture changes by one byte, and rots green.

A `deny-` case's `denied` and `allowed` lists must together be **exactly** the
tree it plants. A planted path in neither list is a path the case has no opinion
about, and a case with no opinion is how a rule's blast radius grows with
nothing in the diff to notice.
