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
receipt, when the recorded verdict is a failure, when the recorded run is not
this repo's declared gate, or when the fingerprint no longer matches. Each of
those gets a different message, because "the gate failed" and "the gate never
ran" are different problems.

The receipt is written by `record-gate.py`. Declare the gate once:

```json
{ "gate_command": "npm run gate" }
```

and run it through the wrapper:

```bash
python3 .claude/agent-guard/record-gate.py --gate
```

It passes the command's exit code straight through, so putting it in front of a
gate changes nothing a human or CI sees. The `-- <command>` form is still there
for an ad-hoc run:

```bash
python3 .claude/agent-guard/record-gate.py -- npm run gate
```

**`--gate` exists because the other form could not be printed** (#178). The
refusal has to tell a session what to run, and interpolating a declared gate
into `record-gate.py -- <gate>` put any `&&`, `;` or `|` in it OUTSIDE the
wrapper. Pasted, half the gate ran unrecorded, and the receipt said `"pass"` for
a run whose second half had failed — through the message the guard itself
printed, so the session had done nothing wrong. `--gate` carries no operators
and hands the declared string to one shell, whole.

With no `gate_command` declared, the refusal names `--gate` anyway and says to
declare one. It used to print `-- <the gate command your CLAUDE.md names>`,
which is the same trap one step further out and the state every freshly adopted
tree is in, since `--agent` cannot declare a gate for you. `--gate` with nothing
declared exits 3 and says what to write — a loud wrong answer instead of a quiet
one.

That fixed the instruction. The receipt is checked too: **a passing, perfectly
fresh receipt for a command that is not the declared gate is refused.** The
fingerprint cannot see that case — the content really was checked, by a check
that was only part of what this repo calls checking. Two shapes count as having
run the gate: `--gate`, which records the declared string in a field of its own,
and an argv that is either the `bash -c '<gate>'` rendering `--gate` executes —
also the workaround from before it existed — or the declaration parsed as an
argv, which is how a one-command gate has always been run.

The comparison is on **argvs, not on strings**, so `bash -c "a && b"` and
`bash -c 'a && b'` are one gate rather than two. What stops that normalisation
from going too far is `SHELL_OPERATORS`: `a && b` splits to a list containing a
bare `&&`, and handing that list to exec runs a program called `a` — so the
declaration-as-argv shape is refused for any declaration a shell would do more
with. Without that, the exact case #178 is about walks back in through the door
the quoting fix opened.

The `--` form stays legal for an ad-hoc run, and with a gate declared it now
**warns on stderr** that the receipt it is about to write will not satisfy the
`Stop` hook. The place to say that is where the command was chosen, not at the
end of the next turn.

**The recorder records for the repo it belongs to, or for nobody** (#192). An
adopted copy sits at `<repo>/.claude/agent-guard/`, so the tree above it names
the repo unambiguously; a cwd that disagrees is a mistake, and it is refused
with nothing written. Before that, running one repo's recorder from inside
another wrote a *passing* receipt into the bystander and left the intended repo
ungated — silent, and permissive in the wrong direction.

The rule is deliberately narrow. This repo's own scripts live in
`scripts/agent-guard/`, not `.claude/agent-guard/`, so it does not fire for
them — which is why every `record` fixture, all of which run the baseline's
scripts against a temp repo, still passes.

**The fingerprint is taken before the command runs, not after.** A formatter is
a gate that edits; fingerprinting afterwards would record a passing verdict for
content no tool had read.

### `PreToolUse` on `Edit|Write|MultiEdit` — the test suite may not be weakened

`Edit`, `Write` and `MultiEdit` under `samples/` are checked for two shapes:
removing entries from a manifest in `samples/expected/`, and removing lines from
a fixture file some manifest cites. Everything else passes, including adding a
new failing case to an existing fixture.

### One install for many repos — `--shared` (#193)

`adopt.sh <repo> --agent` copies four scripts, 984 lines, into every consumer.
Across a fleet that is the same fix committed once per repo. `--shared` puts
**101 lines** there instead — a single `shim.py` — and the scripts live once:

```bash
scripts/adopt.sh --install-shared          # once per machine
scripts/adopt.sh <repo> --agent --shared   # once per repo
```

The wiring routes through the shim (`shim.py stop-gate`) and the shim `execv`s
the real script out of `~/.claude/agent-guard/`, so stdin, stdout and the exit
code are the child's. Re-running `--install-shared` after a `git pull` updates
every `--shared` repo at once.

**Copying stays the default**, and that is an ADR 0001 decision rather than a
preference: an outside adopter runs one command and gets a tree that works,
with no second install step and nothing to go missing.

**A missing shared body REFUSES.** Everything else here fails open on plumbing
— `guard.py`'s header explains why, and it is right — but a missing body is not
plumbing, it is the guard being absent, and absence that allows is the silent
failure this whole design exists to prevent. So it is graded by what each hook
protects: `stop-gate` blocks the turn and names the install; `no-verify-guard`
denies a `git commit`/`push` and nothing else, because a missing guard must not
make every Bash call refuse; `sample-guard` warns and allows, since the Stop
hook above is already refusing; `record-gate` exits 3, because a recorder that
cannot run must not look like one that ran.

That property is why this is a shim and not a Claude Code plugin. A plugin
cannot carry `permissions.deny` at all — its `settings.json` takes only `agent`
and `subagentStatusLine`, and unknown keys are silently ignored — and with a
plugin uninstalled a repo holds a config claiming it is adopted and nothing
else: no hook, no rule, no message. The shim is committed, so the repo can say
what it expects.

### The guard's own state is never a change

Two things under `.claude/` are written by the guard rather than by you, and
both are excluded from the fingerprint: the receipt, and the `__pycache__`
Python writes beside the hook scripts the first time one is imported.

The receipt's exclusion was found by `stop-02-receipt-pass-fresh` before any of
this ran in CI — it is written *after* the fingerprint it records, so leaving it
in changed the very hash it was storing and no session could ever have ended.
The cache is the same bug wearing different clothes, and it was invisible here
for a year because this repo's `.gitignore` already had `__pycache__/`. A Rust,
C# or TypeScript consumer has no reason to, and got a refused stop over a file
no human touched.

`adopt.sh` writes both `.gitignore` lines as well. That is deliberate belt and
braces: the ignore line is tidier, the fingerprint exclusion is the half that
still works when someone deletes it, and a guard whose correctness depends on a
line anyone can remove is not guarding.

### Two of the five only fire where they can (#182)

`sample-guard.py` and `Edit(/samples/expected/**)` are hardcoded to this repo's
fixture layout — `samples/` and `samples/expected/`, as module constants, not
config. In a consumer that has neither, the hook is reachable, runs, and allows
everything; the deny rule matches no file that exists.

So `--agent` installs them **only in a tree that has `samples/expected/`**, and
the `CLAUDE.md` region describes what actually landed: three hooks and two deny
rules where they can fire, two hooks and one deny rule where they cannot. The
defect this fixes is not the inert pair — it is a consumer's `CLAUDE.md`
stating, confidently and specifically, that it is protected by a rule that can
never run.

They are not made configurable. A consumer pointing this at their own fixture
manifests is the obvious next idea and nobody has asked for it; CLAUDE.md §4 is
explicit that a config with no real project behind it is dead weight. Re-running
`--agent` after a `samples/expected/` appears installs both, and refreshes the
prose to match.

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

`samples/agent-guard/` is 64 cases. Every hook case runs the real hook as a
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
`record-gate.py`, `guard.py`) and 2026-08-23 (`no-verify-guard.py`), with the
`--gate` rows added 2026-08-25 (#178):

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
| the refusal interpolates the gate into `--` instead of printing `--gate` | 2 |
| the undeclared case prints an interpolation slot again | 1 |
| `--gate` splits the declared string instead of handing it to one shell | 3 |
| `--gate` records a pass when nothing is declared | 1 |
| the receipt joins its argv with spaces instead of `shlex.join` | 3 |
| the receipt is not checked against the declared gate at all | 3 |
| the comparison is on the joined strings, not on the argvs | 3 |
| a bare operator is not treated as a word only a shell can run | 1 |
| only the `--gate` spelling counts as having run the declared gate | 1 |
| the wrapper does not warn on a run that is not the declared gate | 1 |
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

### 6a. The baseline runs its own contract, as of 2026-08-25

`scripts/adopt.sh . --agent`, committed (#166). Not the adoption-cost
measurement above — that one still requires a Consumer and a contributor who
did not choose this. This is the **in-house-demand** half of the same test:
before a language ships here it has to be written in a repo the owner
maintains, and the agent contract was the one surface asking others to adopt
something the baseline itself did not.

It runs from a **copy** under `.claude/agent-guard/`, not a symlink to
`scripts/agent-guard/`, so this tree drifts exactly the way a consumer's will.
`check-agent-contract.py` G9 is what notices; nothing else could, because all 64
fixtures in `samples/agent-guard/` run the source.

The gate is declared in `.claude/agent-guard.json` as `python3
scripts/agent-guard/selftest.py && python3 scripts/check-agent-contract.py` —
deliberately not the full `ci.yml`. Twenty-eight contexts needing .NET, Java and
Rust toolchains and a network is minutes on every stop, and the same argument
that made the `Stop` hook read a receipt instead of running the gate applies to
what the receipt is a receipt OF.

**On the day, that line was written `bash -c '...'`,** and the block quoted
below prints it that way because that is what the session was handed. It was a
workaround for #178, which is fixed; the declaration is the plain `&&` form now
and the instruction is `--gate`. The transcript is left as it was rather than
tidied, because a record that gets edited to match the current code is no longer
a record of anything.

**A live session was blocked on 2026-08-25.** This is the observation the
milestone actually needed, and it is separate from the fixtures: all 64 cases in
`samples/agent-guard/` invoke the hooks as subprocesses on synthetic payloads,
so none of them can tell you whether Claude Code *wires* them. It was reached
deliberately — one real uncommitted edit to this file, the gate not run — and
the turn could not end. Verbatim, as the session received it:

```
The gate has not run. 1 file(s) differ from HEAD and there is no
.claude/agent-guard-receipt.json.

Run it, then stop:

  python3 .claude/agent-guard/record-gate.py -- bash -c 'python3 scripts/agent-guard/selftest.py && python3 scripts/check-agent-contract.py'

If it fails, fix what it reports — do not record a receipt by hand.
```

Running that line recorded the gate, and the next stop was allowed. First stop
blocked, gate recorded, stop allowed — the whole loop, in a real session, in
this tree.

**Two details worth keeping, because both were nearly assumed instead.** The
hooks arrived mid-session and were live without a restart. And the stop *before*
this one was allowed rather than blocked, correctly: the tree was clean at that
moment, and `stop-gate.py` returns early when nothing differs from `HEAD` — a
read-only session must not be made to run a gate. The blocked case and the
allowed case were both observed, which is what separates "it refuses" from "it
refuses everything".

Two defects the dogfood found in its own first hour, neither of which any
fixture had reached:

- **The `bash -c` in that gate command is a workaround, not a preference.**
  Declared the natural way — `a && b` — the printed instruction binds the `&&`
  outside the recorder, so half the gate runs unrecorded and a receipt can say
  `"verdict": "pass"` for a run whose second half failed. The guard's own
  message is what produces it. Opened as #178 and **fixed** the same day:
  `record-gate.py --gate`, plus a receipt check that refuses a run which is not
  the declared gate. §2 has the reasoning; `stop-15` through `stop-20` are the
  cases.
- **Re-running `--agent` skips an existing `CLAUDE.md` region rather than
  refreshing it**, so the one part of the contract that says what the rules ARE
  is the one part re-adoption does not upgrade. §7a and #177 — **since fixed**:
  the region refreshes, and refuses an edit of yours rather than overwriting it.

Both are recorded rather than fixed here, which is the rule this dogfood is
run under: a cost found by living with it is the measurement, and fixing it in
the same branch would delete the evidence.

## 7. Adopting it

```bash
"$BASELINE"/scripts/adopt.sh <repo> --agent --dry-run   # look first
"$BASELINE"/scripts/adopt.sh <repo> --agent
```

Opt-in, like `--hooks` and `--editor`, and for a stronger reason than either:
this is executable policy arriving in someone's tree. It writes the four things
§7a lists below, and it is the one flag in that script that **merges** rather
than refusing when the target exists — `.vscode/settings.json` is a file a
consumer may not have, and `.claude/settings.json` is a file a consumer running
Claude Code almost certainly does. Refuse-if-exists there would mean this never
adopts anywhere it matters.

It is also the one flag that is **exclusive** (#183). `--hooks` and `--editor`
add to an adoption; this run installs the contract and writes nothing else — no
language config, no `.editorconfig`, no workflow — so the language layer is a
second run without the flag, and passing `--editor` or `--hooks` in the same one
is a usage error rather than a silent choice between them. Two reasons, and the
second decided it: the contract has no language in it, and adopting both at once
makes the result unattributable — nobody can afterwards say whether a session
found the guard annoying or the two hundred new lints. §6's adoption cost is
measured by a consumer turning this on and living with the result, and in a repo
that has not already adopted the language layer the old behaviour made that
measurement impossible to attribute. It also means a repo in
a language this baseline has never heard of can adopt the contract, which the
old behaviour refused to do: it stopped at detection.

The refusal names the runs that do work, and there are **two** trees where that
is one run rather than two. In this repo, `--editor` and `--hooks` against the
baseline are the self-adopt refusal. And in a repo with no language the baseline
detects, the layerless run itself warns "Nothing to do" and exits 1 — which is
the tree this flag was just opened up for, so the success footer does not offer
a language-layer run there either. Both messages ask one predicate before
naming that second run rather than assuming it exists.

Every command those messages print is run by the `adopt` job from the directory
it was printed in, and the fixtures now include a tree with no detectable
language — a remedy nobody executes is how `scripts/agent-guard/stop-gate.py`
came to print a path that did not exist in an adopted tree, and a check whose
fixtures all carry a manifest is one that cannot catch the same defect in the
population this flag newly admits.

The merge has ownership: baseline hook entries are matched by their `command`
string and deny rules by the rule string, and appended to what is already
there. Nothing of the consumer's is replaced, reordered or removed, and
re-running adds nothing twice. `scripts/agent-settings.py` holds it.

It **refuses** a `.claude/settings.json` it cannot fully read — one that does
not parse, or a `hooks` key whose shape is not the documented one — and the
refusal skips the whole flag rather than just that file. Half a contract is a
`CLAUDE.md` that says these rules refuse, in a repo where nothing refuses, and
the next session reads it and believes it. The run exits 6 having written
nothing at all — since #183 there is no "rest of the adoption" for it to fall
back on, because an `--agent` run is the contract and only the contract.

### 7a. What lands, and by hand if you would rather

1. `scripts/agent-guard/*.py` to the consumer's `.claude/agent-guard/`.
2. `settings.json` merged into the consumer's `.claude/settings.json` — **both**
   keys. `hooks` without `permissions` drops half the contract silently, and
   `permissions` is the half with no runtime evidence that it is missing.
3. `CLAUDE.fragment.md` appended to the consumer's `CLAUDE.md`, between the
   markers it carries — that is how a later baseline replaces the region
   without a merge.
4. `.claude/agent-guard-receipt.json` added to `.gitignore` — it is per-checkout
   state. Nothing breaks if you forget; it is excluded from the fingerprint
   either way.

**Re-running `--agent` refreshes the `CLAUDE.md` region** (#177), so
re-adoption is the upgrade path for the prose exactly as it already is for the
scripts and the settings merge. `scripts/agent-region.py` owns it, the same
shape `scripts/pom-region.py` uses for the Java block: everything between the
markers is replaced, everything outside them comes back byte-identical, and a
region that is already current is not rewritten at all.

**A region you edited yourself is refused, not overwritten.** The BEGIN marker
carries a checksum of the text as it was installed, which is the only way to
tell an older baseline's fragment — refresh it, that is the point — from your
own edit, which nobody asked us to touch. The refusal prints the diff and
writes nothing; `--force` is the way through, and on an `--agent` run that is
the only thing `--force` means.

A region installed before this existed carries no checksum. It is refused the
same way, once, with a message saying so — and a region whose text is already
current is *stamped* with one rather than left permanently unverifiable.

One thing `--agent` does not do, and cannot: declare what your gate command is.
Write `.claude/agent-guard.json` as `{ "gate_command": "<your gate>" }` once.
Without it the `Stop` hook still blocks and simply cannot name what to run, and
a refusal with no remedy attached is a refusal that gets worked around — and
`--gate` has nothing to run, so it exits 3 and writes no receipt rather than
recording a pass for a gate nobody named.

**`selftest.py` is no longer copied at all** (#191). It is this repo's own
corpus runner, it needs `samples/agent-guard/` which adoption does not carry,
and it could never run in a consumer — 508 lines, 29% of what the old install
weighed, in every tree that would ever exist. Both this section and `adopt.sh`'s
completion text used to describe it as dead weight and ship it anyway.

**What lands is derived from what your tree wires**, not from a glob:
`agent-settings.py scripts` reads the hook commands for your profile and names
the files, so a tree with no `samples/expected/` gets four scripts rather than
six. `adopt.sh` also removes an orphan a previous adoption left behind — a hook
script no command names is the condition `check-agent-contract.py` G1 fails the
baseline for, and it should not be tolerable in a consumer either. Only names
that exist under `scripts/agent-guard/` are ever removed.

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
the only place the two meet. Two unrelated things called hooks, one repo — so
this one's flag is `--agent`, and `--hooks` still means the git one. Passing
`--hooks` installs the pre-commit hook and no part of this contract; passing
`--agent` does the reverse. Neither implies the other, and since #183 they do
not compose either — `--agent` is exclusive, so the two are two runs. Both
surfaces are still available to the same repo; what changed is that asking for
them in one command is a usage error instead of a bundle.
