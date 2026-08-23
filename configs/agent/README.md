# The agent contract

The baseline speaks on two surfaces. CI is the gate. `configs/editor/` is the
frozen contract that makes the editor show what CI shows. Neither reaches the
third one: **the agent session that writes the code in the first place.**

A `CLAUDE.md` is advisory — the model reads it and can drift from it. Hooks are
not: a `PreToolUse` hook's deny decision stops the tool call before it runs, and
a `Stop` hook's block decision refuses the end of the turn and feeds its reason
back as the next instruction. A `permissions.deny` rule is stronger still — it
is enforced by Claude Code before a hook is consulted at all. The model does not
get a vote in any of the three.

This directory is the frozen contract for four rules, and **only** four.

| File | Enforces |
|---|---|
| [`settings.json`](settings.json) | the wiring — two `PreToolUse` matchers, one `Stop`, and the `permissions.deny` array |
| [`../../scripts/agent-guard/stop-gate.py`](../../scripts/agent-guard/stop-gate.py) | a session may not call it done on code the gate has not seen |
| [`../../scripts/agent-guard/sample-guard.py`](../../scripts/agent-guard/sample-guard.py) | an edit that weakens `samples/` is refused |
| [`../../scripts/agent-guard/no-verify-guard.py`](../../scripts/agent-guard/no-verify-guard.py) | a commit or push may not skip `hooks/pre-commit` |
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
  done", "the test suite may not be weakened to make a red gate green", "the
  receipt and the expectation manifests are not yours to rewrite", "the commit
  hook may not be switched off". Every one of those is meaningless without the
  baseline, and every one is the kind of rule that drifts the moment it is
  hand-copied into a `CLAUDE.md`.

Four rules is the whole budget, for the same reason the Semgrep ruleset is
capped at twelve conventions: a guard list is infinitely expandable and feels
productive. It went from two to four on #161, and the honest account of why is
narrower than "they were needed": **only one of the two closes a hole this file
had already named.** §3 said a session could write the receipt by hand, and the
`Edit` deny closes the file-tool half of exactly that. The `--no-verify` guard
closes a hole nothing here had written down — `hooks/pre-commit` was reachable
from a session and no line of this contract said so. That is the weaker
justification of the two and it is recorded as such, because "it seemed
obviously right" is how a rule budget stops being a budget. A fifth needs a real
failure that got through.

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

### `PreToolUse` on `Edit|Write|MultiEdit` — the test suite may not be weakened

`Edit`, `Write` and `MultiEdit` under `samples/` are checked for two shapes:
removing entries from a manifest in `samples/expected/`, and removing lines from
a fixture file some manifest cites. Everything else passes, including adding a
new failing case to an existing fixture.

### `permissions.deny` — the file tools may not touch the receipt or a manifest

Two rules, and the spelling of each is load-bearing:

```json
"deny": [
  "Edit(/.claude/agent-guard-receipt.json)",
  "Edit(/samples/expected/**)"
]
```

**They are `Edit(...)` rules and never `Write(...)`.** Claude Code checks file
permissions against `Edit(path)` and `Read(path)` rules only; a path rule
written for `Write`, `MultiEdit`, `NotebookEdit` or `Glob` is accepted, never
consulted, and warns once at startup. Accepted-and-ignored looks exactly like
protection until somebody relies on it, so `selftest.py` asserts the spelling
rather than trusting it. An `Edit` rule covers every built-in tool that edits
files, `Write` included — the tool name in the rule is not the tool it governs.

**The single leading `/` is load-bearing too.** It anchors at the settings
source — the project root, for the project settings this fragment becomes — and
matches there and nowhere else. Drop it and gitignore's bare-name semantics
match the file at any depth; double it and `//` anchors at the filesystem root
and matches nothing in the repo at all. All three spellings survive review.

**There is no `Read` deny.** The hooks read the manifests themselves —
`sample-guard.py` compares the finding sets, and a `Read` deny would also block
the tools that do it. A rule that breaks the guard it is protecting is not a
harder rule, it is a broken one.

### `PreToolUse` on `Bash` — a commit may not skip the hooks

`git commit --no-verify` switches off `hooks/pre-commit`, the local half of this
baseline, and it is what a session reaches for when a commit is refused and the
refusal looks like plumbing. `no-verify-guard.py` refuses it on `commit` and on
`push`, and refuses `-n` on `commit` — but **not** on `push`, where git's own
`-n` means `--dry-run` and denying it would block the safest command in git.

It is a hook and not a deny rule because neither rule form works here. The
permissions reference is explicit that a `Bash(command:...)` rule is ignored
with a startup warning, since a compound command bypasses it; and it devotes a
warning to how fragile argument-matching prefix rules like
`Bash(git commit --no-verify *)` are — options before the argument, variables,
extra spaces. Its recommended answer to both is a `PreToolUse` hook, so the
tokenizer is the thing under test and `samples/agent-guard/` tests it as one.

## 3. What this does NOT do — read this before trusting it

**It guards drift, not malice**, and #161 moved where that line sits without
moving which side of it this contract is on.

**The file tools can no longer write the receipt, and Bash still can.** The
`Edit` deny rules are enforced by Claude Code itself, before any hook is
consulted; §5 states exactly what evidence that claim rests on, and a matched
pair of live runs in §5a shows the refusal and its absence. They reach the built-in file tools and the shell commands Claude Code
recognises, and the permissions reference says plainly that they "don't apply to
arbitrary subprocesses that read or write files indirectly". A heredoc, a
redirect or a three-line Python script writes either file and nothing here sees
it.

For a **manifest** that is survivable, and the Stop gate is why: whatever wrote
the bytes, they are in `git status` at the end of the turn, the fingerprint
moves, and the gate has to run again over the new content.
`samples/agent-guard/cases/stop-07-untracked-file.json` is that assertion.

For the **receipt** there is no backstop, and there cannot be one: the receipt
is the Stop gate's own input, so a forged receipt with a matching fingerprint
passes. That is the boundary. The failure this exists to stop is a model that
forgets, not one that lies, and a guard sold as tamper-proof gets trusted for
things it cannot do.

**The sample guard catches deletion-shaped weakening only.** It does not decide
whether a fixture still fires — that needs the toolchain the fixture is for, five
of them, minutes each. A same-size edit that defuses a finding in place (`==` to
`===`, dropping an `any`) passes it. That case is caught by
`scripts/check-expected.py` in CI, which diffs the finding set per rule id and
names the rule that stopped firing. **This hook is the fast filter in front of
that gate, never a replacement for it.**

**The `--no-verify` guard reads a command, not what the command does.** A shell
script, a `Makefile` target or a git alias that itself commits with
`--no-verify` passes it, because the flag is not in the text Claude asked to
run. Same boundary, same answer.

**It has never run in a consumer.** See §6.

## 4. Fail open on our own plumbing, fail closed on policy

`hooks/pre-commit` has the same rule and gives the same reason: a guard that
blocks on its own broken plumbing teaches people to switch it off, and then it
is not catching the real thing either.

There is one difference, and it is why these are Python rather than a shell
one-liner: **an agent hook is not bypassable by the party it constrains.** The
model cannot pass `--no-verify`. So no git, an unreadable receipt, a malformed
payload, a `file_path` that is missing, a `Bash` command whose quotes do not
balance — every one of those allows the action and says so on stderr. Only a
policy violation blocks.

The loop guard is part of this. Claude Code overrides a `Stop` hook after it
blocks eight times in a row; `stop_hook_active` is true once the hook has already
forced a continuation, and it exits early. Without it, a repo whose gate cannot
pass — a broken toolchain, a pre-existing failure — is a repo where no session
can end.

**The deny rules have no fail-open, because they have nothing to fail.** They
are two strings, evaluated by Claude Code. That is their advantage over a hook
and it is also their cost: a rule that is wrong is wrong silently and forever,
which is the entire argument for §5's structural checker.

## 5. Evidence

`samples/agent-guard/` is 52 cases. Every hook case runs the real hook as a
subprocess with a real payload on stdin and parses stdout the way Claude Code
does; the `stop-` and `edit-` cases build a real git repository first, and the
`noverify-` cases do not, because a command guard reads a string and has no
opinion about the repository it stands in. Two kinds of case are not a hook
invocation at all — `changed-` calls `changed_files()` directly, and `deny-`
runs nothing. `samples/agent-guard/README.md` has the table.
`scripts/agent-guard/selftest.py` runs them all, and the `agent-guard` job in
`ci.yml` runs that.

**The corpus proves the hooks, and nothing in it proves the wiring.** Every
case runs a script as a subprocess with a payload on stdin, which is exactly why
no case routes through a `matcher` and no case reads a `command`. Narrow the
`Edit|Write|MultiEdit` matcher by one tool, rename a hook script without
touching `settings.json`, or let the count in the paragraph above drift by one,
and every case still passes while this file describes a contract the wiring does
not implement.

`scripts/check-agent-contract.py` is the guard for the seams between the four
parts, and the `agent-guard` job runs it in two more steps — the check, and the
checker's own mutations. Every `command` against the script it names and every
script against some `command`; the matchers against the prose in both
directions; the case counts in both READMEs against `cases/`; every mutation
row, cited case, cited section and link against what exists; the deny array
against the block quoted in §2 and the table in §5a; and every reference in §6
against its own `as of <date>`. **It reads the numbers here and refuses to
write them** — a checker that updates its own expectations agrees with itself
forever, which is the argument `check-expected.py` and `editor-parity.py
--update` already make about their own corpora.

Its own mutations are executable rather than tabled, and the difference is
cost: `selftest` stages the contract in a temp tree, breaks one thing, and
asserts the run names what moved. That runs in a second, so there is no reason
to record it in prose the way the tables below have to be. What no mutation
reaches is marked at the site, for the same reason the zero rows below are
published rather than dropped.

**The deny rules are the exception, and it is paid for rather than granted.** A
`permissions.deny` rule cannot be exercised headlessly — there is no way to make
Claude Code's permission layer fire from a fixture — so no sample can fail
without it. That is precisely the shape CONTRIBUTING.md's "`samples/` is the
test suite" rule exists to catch, and it is the shape `configs/editor/` already
had. It is paid for the same way, in three parts:

1. `selftest.py`'s `permissions` mode asserts the rules' **internal
   consistency**: that every rule names `Edit` or `Read` and not one of the four
   tool names Claude Code accepts and never consults, that it carries a path
   rather than a bare tool name or a `param:value` form, that the pattern
   parses, and that it matches the literal paths it is meant to — and only
   those — against a planted tree.
2. This section states what evidence each claim rests on, including which lines
   no fixture can reach.
3. §5a records one dated live observation, because a structurally consistent
   rule that Claude Code does not enforce the way the docs read is still a rule
   that protects nothing.

**Do not read this as a precedent.** A config that could have a failing sample
and does not is still a violation.

**The suite was mutation-tested, and here are the numbers**, because a fixture
that passes a broken guard proves nothing.

The four scripts, on 2026-08-22 (`sample-guard.py`, `stop-gate.py`,
`record-gate.py`, `guard.py`) and 2026-08-23 (`no-verify-guard.py`):

| Mutation | Cases failed |
|---|---|
| `no-verify-guard.py` never denies | 8 |
| a substring search replaces the tokenizer | 9 |
| `sample-guard.py` never denies | 7 |
| `stop-gate.py` ignores the fingerprint | 3 |
| the receipt is not excluded from the fingerprint | 3 |
| `stop-gate.py` ignores a failing verdict | 2 |
| `-n` is not recognised as `--no-verify` on `commit` | 2 |
| `-n` is also denied on `push` (git's own asymmetry ignored) | 1 |
| short flags are compared whole rather than per character | 1 |
| a value-taking option does not consume its word | 1 |
| an attached `--opt=value` consumes the next word anyway | 1 |
| compound commands are not split on `&&` | 1 |
| lines are not split before lexing | 1 |
| global options before the subcommand are not skipped | 1 |
| `git` is matched as a literal token rather than a basename | 1 |
| the `--` pathspec terminator is ignored | 1 |
| an untokenisable command blocks instead of allowing | 1 |
| the `stop_hook_active` loop guard is removed | 1 |
| `record-gate.py` hashes after the run instead of before | 1 |
| `record-gate.py` swallows the gate's exit code | 1 |
| a rename's old path is dropped from the changed set | 1 |
| the edited path is not resolved through symlinks | 1 |
| manifest removals are not compared | 1 |
| **`replace_all` is modelled as a single replacement** | **0 — and cannot be** |
| **the repo root is not re-resolved** | **0 — and cannot be** |
| **the deny check compares the whole token, not the option name** | **0 — and cannot be** |

And the `permissions` mode, mutated on 2026-08-23 in both directions — the rule
in the fragment, and the checker that reads it:

| Mutation | Cases failed |
|---|---|
| the rule is spelled `Write(...)`, `MultiEdit(...)` or `NotebookEdit(...)` | 3 |
| the rule is a `param:value` form, an empty pattern, or a bare directory | 3 |
| the rule loses its tool name entirely | 3 |
| the leading `/` is dropped, doubled, or the filename left bare | 2 |
| the pattern is widened to `/.claude/*.json` | 2 |
| the checker treats a `/`-anchored rule as matching at any depth | 2 |
| the checker's `**` stops crossing directories | 1 |
| **the checker's planted-tree exhaustiveness assertion is removed** | **0 — and cannot be** |

The rows at zero are the point of publishing tables rather than a pass rate.
Every occurrence of a `replace_all` edit carries the same line delta, so its
SIGN does not change with the number of replacements. `git rev-parse
--show-toplevel` already returns a resolved path, so re-resolving it is
unfalsifiable belt-and-braces. `--no-verify` takes no value, so comparing the
option name rather than the whole token is a distinction no command can express.
And the exhaustiveness assertion refuses a FIXTURE that plants a path it has no
opinion about — there is no case shape for "this case must fail", so it guards
the next author and no run can prove it. All four are kept, and each one carries
a comment at its own site saying no fixture reaches it, because a line that looks
tested and is not is worse than one openly marked.

One more thing `selftest.py` carries that no row above can move: `rule_matcher()`
models all four anchor forms the permissions reference documents — `//`, `~/`,
`/` and bare — and `glob_regex()` handles `?`, while today's two rules use only
the `/` anchor and no `?`. Those branches are not speculative generality, they
are the same anchor-slip failure one level up: a checker that models three of
four anchors does not reject the fourth, it silently resolves it somewhere else
and reports a clean run. They are commented at the site for the same reason.

**One real defect was found this way and is worth recording**, because reading
the code did not find it: the receipt is written *after* the fingerprint it
records, and it is itself an untracked file — so it changed the very hash it was
storing, and a passing gate's receipt never matched the next stop. Every session
would have been unendable. `stop-02-receipt-pass-fresh` is the case that caught
it; `EXCLUDED` in `guard.py` is the fix.

### 5a. The deny rules, observed live

**2026-08-23, Claude Code 2.1.236.** Five headless sessions
(`claude -p --permission-mode acceptEdits --allowedTools Edit`), each in a
throwaway git repository whose `.claude/settings.json` carried nothing but the
`permissions` block under test. `acceptEdits` matters: without a deny rule the
edit goes through unattended, so anything that stops it is the rule.

| `permissions.deny` | `Edit` target | Result |
|---|---|---|
| `Edit(/.claude/agent-guard-receipt.json)` | `.claude/agent-guard-receipt.json` | **refused** — `File is in a directory that is denied by your permission settings.` |
| `[]` | `.claude/agent-guard-receipt.json` | refused **differently** — an approvable prompt calling it a sensitive file, not a denial |
| `Edit(/samples/expected/**)` | `samples/expected/eslint.json` | **refused**, same denial text |
| `Edit(/samples/expected/**)` | `sub/samples/expected/eslint.json` | **succeeded**, file rewritten |
| `[]` | `samples/expected/eslint.json` | **succeeded**, file rewritten |

Three things this shows that the structural checker cannot:

- The rules are enforced, and the refusal is a **deny** rather than a prompt.
  Rows 1 and 2 are the same file, the same session shape, and two different
  refusals; only row 1 is unconditional.
- **The anchor behaves as documented.** Rows 3 and 4 hold the rule constant and
  move the file: `/samples/expected/**` refuses at the project root and permits
  the nested copy. That is the exact assertion
  `deny-03-manifests-are-covered-to-any-depth-inside.json` makes on paper, and
  nothing but a live run can confirm the paper is right.
- Rows 4 and 5 are the negative controls. A rule that denied everything, or an
  environment that denied everything, would pass rows 1 and 3 and fail these.

One observation that is worth keeping and is **not** evidence of the mechanism:
a first attempt asked the session to flip the receipt's verdict from `fail` to
`pass`, and it read the settings, refused on its own judgement, and never called
`Edit` at all. That measures the model, not the rule. The runs above were
rewritten as edits a session has no reason to object to, so the permission layer
is the only thing left that can refuse.

## 6. What has NOT been measured

**Adoption cost.** CONTEXT.md is explicit that it is measured by a Consumer
turning it on and living with the result, never by a fixture built here. That
has not happened. Consumer A is the intended first measurement (#152) and the
cell in `docs/STATUS.md` says unmeasured until it is.

The cost is not the hooks firing. It is a blocked session belonging to a
contributor who did not choose this, and it is API drift: **there is no
documented schema version for the hooks format, and none for the permissions
format either** — that was checked twice, on 2026-08-22 and again on 2026-08-23,
and the docs are silent both times — so there is nothing to pin a compatibility
claim to. The hooks were built against `code.claude.com/docs/en/hooks` as of
**2026-08-22** and the deny rules against
`code.claude.com/docs/en/permissions` as of **2026-08-23**; those dates are the
only version statement available. The one hard number is in §5a: the behaviour
recorded there is Claude Code **2.1.236**, and the permissions reference itself
puts minimum versions on the file-permission checks (2.1.208 for edits, 2.1.228
for writes, 2.1.210 for the unconsulted-rule warning), so a consumer on an older
build has the rules and not the enforcement.

## 7. Adopting it by hand

`adopt.sh` does not write these yet — that is deliberate and it is a separate
issue. Until then:

1. Copy `scripts/agent-guard/*.py` to the consumer's `.claude/agent-guard/`.
2. Merge `settings.json` into the consumer's `.claude/settings.json` — **both**
   keys. `hooks` without `permissions` drops half the contract silently, and
   `permissions` is the half with no runtime evidence that it is missing.
3. Append `CLAUDE.fragment.md` to the consumer's `CLAUDE.md`.
4. Add `.claude/agent-guard-receipt.json` to `.gitignore` — it is per-checkout
   state. Nothing breaks if you forget; it is excluded from the fingerprint
   either way.

**Check the startup output once after merging.** A deny rule Claude Code will
not consult — the `Write(...)` spelling, a tool name that does not exist — warns
at startup and then never mentions itself again. `selftest.py` catches that for
the rules shipped here; it cannot catch a hand-merge that mangled one.

**The scripts are copied, not referenced by tag**, and that is a real cost, not
an oversight: a hook command is a path on disk, and Claude Code has no remote
consumption. It is the same trade the C# and Rust configs already make because
MSBuild and Cargo cannot consume theirs remotely either.

**Checked-in hooks require workspace trust.** A contributor cloning the repo is
asked once, by Claude Code, before any of this runs. That prompt is a feature —
executable policy arriving in someone's tree should be something they see.

## 8. A naming collision worth knowing about

`hooks/` at the repo root is the **git** pre-commit hook, installed by
`adopt.sh --hooks`. It has nothing to do with this directory — except that
`no-verify-guard.py` exists to stop a session switching that one off, which is
the only place the two meet. Two unrelated things called hooks, one repo; the
flag for this one, when it exists, will not be `--hooks`.
