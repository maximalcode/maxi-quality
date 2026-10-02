# Guardian skill

The [Guardian skill](../skills/guardian/SKILL.md) adds an AI assessment to the
[local runner](GUARDIAN.md). It uses the same [setup entry](GUARDIAN-SETUP.md),
without another check engine, provider account or CI dependency. Python 3.11+,
Git, Bash and the project's check tools are required; AI assessment uses the
current authenticated Codex host.

Install from a trusted local checkout containing this skill. Keep that checkout
at a deliberately selected commit; the skill follows that checkout and never
updates itself. Link the directory rather than copying only `SKILL.md`, because
its physical location identifies the shared runner and documentation:

```bash
BASELINE=/absolute/path/to/maxi-quality
mkdir -p "$HOME/.agents/skills"
test ! -e "$HOME/.agents/skills/guardian" &&
  test ! -L "$HOME/.agents/skills/guardian" &&
  ln -s "$BASELINE/skills/guardian" "$HOME/.agents/skills/guardian"
```

The existence checks leave an existing destination intact; reconcile it deliberately
rather than overwriting another skill. Have the current host discover the skill
and invoke it, for example:

- `$guardian setup local checks for this project` previews the existing checks
  and applies the agreed setup. It preserves existing check declarations.
- `$guardian review this change against task SPEC.md, base develop` executes
  checks and separately assesses the named requirements, leaving source and
  configuration unchanged.
- `$guardian review-and-repair against SPEC.md, base develop` additionally
  permits fixes within that task, followed by revalidation.

A review without a task source cannot confirm requirements completion. A failed
check, a check that could not run, and an AI concern remain separate facts.
Human overrides appear only when explicitly supplied by the user; they neither
change a failed result nor disable enforcement. Old findings require evidence
of their age; uncertain findings stay unknown.

Automatic completion is a separate opt-in through the existing native Codex
setup. It uses the declared local gate and recorder freshness, not another AI
review after every edit. Hook configuration, trust and live enforcement are
separate observations; unavailable prerequisites and unobserved enforcement
must be reported as such. Installation of this skill alone installs no hooks.
Without an agent host, use the local runner directly; AI assessment is unavailable.

## Evidence limits and demo

Run `python3 scripts/check-guardian.py`. The skill integration fixture installs
a directory symlink in a temporary skill root, resolves the shared runner from
that physical location, and compares its commands and outcomes with direct CLI
execution. It also exercises failure, incomplete execution, missing task,
read-only source/configuration, and stale evidence followed by scoped repair.
These are subprocess proofs of the interfaces, not an automated proof that an
AI follows every instruction or that native hooks execute.

For an interactive demo, use an invented Git project with `source.txt`, a
`SPEC.md` requiring its contents to be `repaired`, and a declared Python check
that compares those contents. Start with `source.txt` containing `original`.
Ask the current host for a named-task review against HEAD, then a review with no
spec. Verify the exact failed command remains visible and the latter cannot
confirm requirements completion. Give an explicit decision to proceed despite
that failure and verify the report records an override without changing the
receipt. Finally request review-and-repair of that spec: only `source.txt`
should change, the failed observation should become stale, and the rerun should
pass. Remove the declaration in a separate invented project to demonstrate
unavailable execution. With no baseline reproduction, the failure's age is
unknown. Live trust/enforcement and real adoption cost remain separate evidence.
