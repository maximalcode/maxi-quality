# The agent guard's test suite

Thirty-one cases, one JSON file each, in [`cases/`](cases). Every one builds a
real git repository in a temp directory, runs the real hook script as a
subprocess with a real payload on stdin, and parses stdout the way Claude Code
parses it. Run them:

```bash
python3 scripts/agent-guard/selftest.py
```

`ci.yml`'s `agent-guard` job runs exactly that, and it is a required check on
both branches.

## Why the assertion is the decision, not the exit code

Both hooks always exit 0 and carry their verdict in JSON — the hook docstrings
give the reasons, and they are different for the two events. So `exit 0` is
equally true of a hook that blocked, a hook that allowed, and a hook that
silently did nothing at all. The suite asserts the **parsed decision**, and
asserts that an allow prints *nothing whatsoever*. A hook that grows a stray
`print` still exits 0; here it fails.

## Why a real git repo per case

The two things most likely to break are both git-shaped: what counts as a
changed file (a rename is two paths, an untracked file is a change, a deleted
one still has to hash), and whether a path comparison survives a symlink. The
temp dir is `realpath`-resolved in the fixture **on purpose** — on macOS
`/tmp` is `/private/tmp`, so a hook that compares paths without resolving both
sides passes on a runner and fails on a developer's machine.

## The negative controls matter as much as the blocks

Five cases exist to prove the guard stays out of the way: an edit outside
`samples/`, an edit that grows a fixture, an edit to an uncited clean fixture, a
brand-new manifest, and a tool the matcher should never have routed here. A
guard that also objects to ordinary work is a guard someone switches off within a
day, and then the real one is not running either.

Three more are the fail-open cases — not a git repo, a payload with no
`file_path`, a stop that has already forced one continuation. An agent hook
cannot be bypassed by the party it constrains, so its own plumbing failures must
allow. Those cases are what stop a "harden this" change from quietly making a
broken install unsurvivable.

## Measured teeth

A fixture suite that passes a broken guard proves nothing, so every shipped
script was mutation-tested on 2026-08-22:

| Mutation | Cases failed |
|---|---|
| `sample-guard.py` never denies | 7 |
| `stop-gate.py` ignores the fingerprint | 3 |
| the receipt is not excluded from the fingerprint | 3 |
| `stop-gate.py` ignores a failing verdict | 2 |
| the `stop_hook_active` loop guard is removed | 1 |
| `record-gate.py` hashes after the run instead of before | 1 |
| `record-gate.py` swallows the gate's exit code | 1 |
| a rename's old path is dropped from the changed set | 1 |
| the edited path is not resolved through symlinks | 1 |
| manifest removals are not compared | 1 |
| **`replace_all` is modelled as a single replacement** | **0 — and cannot be** |
| **the repo root is not re-resolved** | **0 — and cannot be** |

The last two rows are the point of publishing the table rather than a pass
rate. Every occurrence of a `replace_all` edit carries the same line delta, so
its SIGN does not change with the number of replacements: a shrink is a shrink
at one occurrence or at ten, and no fixture can tell the two models apart while
the rule counts lines. And `git rev-parse --show-toplevel` already returns a
resolved path, so re-resolving it is unfalsifiable belt-and-braces. Both lines
are kept and both are commented as uncovered, because a line that looks tested
and is not is worse than one openly marked.

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

`fingerprint: "current"` in a receipt is computed by the runner after the tree is
final, never written into the fixture. A hash copied into a case file rots the
moment a fixture changes by one byte, and rots green.
