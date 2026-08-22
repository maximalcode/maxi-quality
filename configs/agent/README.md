# The agent contract

The baseline speaks on two surfaces. CI is the gate. `configs/editor/` is the
frozen contract that makes the editor show what CI shows. Neither reaches the
third one: **the agent session that writes the code in the first place.**

A `CLAUDE.md` is advisory — the model reads it and can drift from it. Hooks are
not: a `PreToolUse` hook's deny decision stops the tool call before it runs, and
a `Stop` hook's block decision refuses the end of the turn and feeds its reason
back as the next instruction. The model does not get a vote.

This directory is the frozen contract for two rules, and **only** two.

| File | Enforces |
|---|---|
| [`settings.json`](settings.json) | the hook wiring — one `PreToolUse` matcher, one `Stop` |
| [`../../scripts/agent-guard/stop-gate.py`](../../scripts/agent-guard/stop-gate.py) | a session may not call it done on code the gate has not seen |
| [`../../scripts/agent-guard/sample-guard.py`](../../scripts/agent-guard/sample-guard.py) | an edit that weakens `samples/` is refused |
| [`../../scripts/agent-guard/record-gate.py`](../../scripts/agent-guard/record-gate.py) | runs the gate and records what it verified |
| [`CLAUDE.fragment.md`](CLAUDE.fragment.md) | the workflow, in the consumer's own `CLAUDE.md` |

---

## 1. The seam: what belongs here and what does not

Decided on #152. The dividing test is one question — **does the rule reference
the baseline itself?**

- **Per-user, out of scope.** Blocking `git push --force`, `reset --hard`,
  `clean`. Those protect a person in every repo they touch, they belong in
  `~/.claude`, and shipping personal preference into someone else's tree is not
  this repo's job. There is no `--force` guard here and there will not be one.
- **Per-repo, in scope.** "The gate ran on the changed files before you said
  done", "the test suite may not be weakened to make a red gate green". Both are
  meaningless without the baseline, and both are the kind of rule that drifts
  the moment it is hand-copied into a `CLAUDE.md`.

Two rules is the whole budget, for the same reason the Semgrep ruleset is capped
at twelve conventions: a guard list is infinitely expandable and feels
productive. A third rule needs a real failure that got through, not a good idea.

## 2. What is enforced, precisely

### `Stop` — the gate has to have run

At the end of every turn the hook fingerprints the content that differs from
`HEAD` — tracked edits, staged changes, untracked files git would not ignore,
and both sides of a rename — and compares it against
`.claude/agent-guard-receipt.json`. The stop is refused when there is no
receipt, when the recorded verdict is a failure, or when the fingerprint no
longer matches. Each of those gets a different message, because "the gate failed"
and "the gate never ran" are different problems.

The receipt is written by `record-gate.py`, which wraps the real command:

```bash
python3 .claude/agent-guard/record-gate.py -- npm run gate
```

It passes the command's exit code straight through, so putting it in front of a
gate changes nothing a human or CI sees. Declare the command once in
`.claude/agent-guard.json` and the refusal message names it:

```json
{ "gate_command": "npm run gate" }
```

**The fingerprint is taken before the command runs, not after.** A formatter is
a gate that edits; fingerprinting afterwards would record a passing verdict for
content no tool had read.

### `PreToolUse` — the test suite may not be weakened

`Edit`, `Write` and `MultiEdit` under `samples/` are checked for two shapes:
removing entries from a manifest in `samples/expected/`, and removing lines from
a fixture file some manifest cites. Everything else passes, including adding a
new failing case to an existing fixture.

## 3. What this does NOT do — read this before trusting it

**It guards drift, not malice.** Every check here is defeated by a session that
writes the receipt file by hand, and none of it is hardened against that. It
does not need to be: the failure it exists to stop is a model that forgets, not
a model that lies. This matters because a guard sold as tamper-proof gets
trusted for things it cannot do.

**The sample guard catches deletion-shaped weakening only.** It does not decide
whether a fixture still fires — that needs the toolchain the fixture is for, five
of them, minutes each. A same-size edit that defuses a finding in place (`==` to
`===`, dropping an `any`) passes it. That case is caught by
`scripts/check-expected.py` in CI, which diffs the finding set per rule id and
names the rule that stopped firing. **This hook is the fast filter in front of
that gate, never a replacement for it.**

**A tool matcher does not see every write.** The docs are explicit: "Claude can
also create or modify files by running shell commands", and the recommended
answer is a `Stop` hook that scans the working tree once per turn. So a heredoc
in `Bash` walks straight past `sample-guard.py`. It does not walk past
`stop-gate.py` — whatever wrote the bytes, they are in `git status` at the end of
the turn, and `samples/agent-guard/cases/stop-07-untracked-file.json` is that
assertion.

**It has never run in a consumer.** See §6.

## 4. Fail open on our own plumbing, fail closed on policy

`hooks/pre-commit` has the same rule and gives the same reason: a guard that
blocks on its own broken plumbing teaches people to switch it off, and then it
is not catching the real thing either.

There is one difference, and it is why these are Python rather than a shell
one-liner: **an agent hook is not bypassable by the party it constrains.** The
model cannot pass `--no-verify`. So no git, an unreadable receipt, a malformed
payload, a `file_path` that is missing — every one of those allows the action
and says so on stderr. Only a policy violation blocks.

The loop guard is part of this. Claude Code overrides a `Stop` hook after it
blocks eight times in a row; `stop_hook_active` is true once the hook has already
forced a continuation, and it exits early. Without it, a repo whose gate cannot
pass — a broken toolchain, a pre-existing failure — is a repo where no session
can end.

## 5. Evidence

`samples/agent-guard/` is 31 cases. Each builds a real git repository in a temp
directory and runs the real hook as a subprocess with a real payload on stdin;
nothing imports a function. `scripts/agent-guard/selftest.py` runs them, and the
`agent-guard` job in `ci.yml` runs that.

**The suite was mutation-tested, and here are the numbers** (2026-08-22),
because a fixture that passes a broken guard proves nothing:

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

**One real defect was found this way and is worth recording**, because reading
the code did not find it: the receipt is written *after* the fingerprint it
records, and it is itself an untracked file — so it changed the very hash it was
storing, and a passing gate's receipt never matched the next stop. Every session
would have been unendable. `stop-02-receipt-pass-fresh` is the case that caught
it; `EXCLUDED` in `guard.py` is the fix.

## 6. What has NOT been measured

**Adoption cost.** CONTEXT.md is explicit that it is measured by a Consumer
turning it on and living with the result, never by a fixture built here. That
has not happened. Consumer A is the intended first measurement (#152) and the
cell in `docs/STATUS.md` says unmeasured until it is.

The cost is not the hooks firing. It is a blocked session belonging to a
contributor who did not choose this, and it is hook-API drift: **there is no
documented schema version for the hooks format** — that was checked, and the docs
are silent — so there is nothing to pin a compatibility claim to. This contract
was built against the reference at `code.claude.com/docs/en/hooks` as of
**2026-08-22**, and that date is the only version statement available.

## 7. Adopting it by hand

`adopt.sh` does not write these yet — that is deliberate and it is a separate
issue. Until then:

1. Copy `scripts/agent-guard/*.py` to the consumer's `.claude/agent-guard/`.
2. Merge `settings.json` into the consumer's `.claude/settings.json`.
3. Append `CLAUDE.fragment.md` to the consumer's `CLAUDE.md`.
4. Add `.claude/agent-guard-receipt.json` to `.gitignore` — it is per-checkout
   state. Nothing breaks if you forget; it is excluded from the fingerprint
   either way.

**The scripts are copied, not referenced by tag**, and that is a real cost, not
an oversight: a hook command is a path on disk, and Claude Code has no remote
consumption. It is the same trade the C# and Rust configs already make because
MSBuild and Cargo cannot consume theirs remotely either.

**Checked-in hooks require workspace trust.** A contributor cloning the repo is
asked once, by Claude Code, before any of this runs. That prompt is a feature —
executable policy arriving in someone's tree should be something they see.

## 8. A naming collision worth knowing about

`hooks/` at the repo root is the **git** pre-commit hook, installed by
`adopt.sh --hooks`. It has nothing to do with this directory. Two unrelated
things called hooks, one repo; the flag for this one, when it exists, will not
be `--hooks`.
