<!-- maxi-quality: agent guard — written by `adopt.sh --agent`.
     Keep the markers, and the checksum in the BEGIN one: re-running --agent
     uses it to tell an older baseline's text (which it refreshes) from an edit
     of your own (which it refuses rather than overwrite). See
     configs/agent/README.md §7a. -->
<!-- BEGIN maxi-quality agent-guard -->

## The gate, and how a session ends

<!-- maxi-quality:if-samples -->
This repo's quality baseline is enforced by three hooks and two deny rules in
`.claude/settings.json`. They are not advice — they refuse.
<!-- /maxi-quality:if-samples -->
<!-- maxi-quality:unless-samples -->
This repo's quality baseline is enforced by two hooks and one deny rule in
`.claude/settings.json`. They are not advice — they refuse.
<!-- /maxi-quality:unless-samples -->

**Run the gate through the recorder, not directly:**

<!-- maxi-quality:unless-shared -->
```bash
python3 .claude/agent-guard/record-gate.py --gate
```
<!-- /maxi-quality:unless-shared -->
<!-- maxi-quality:if-shared -->
```bash
python3 .claude/agent-guard/shim.py record-gate --gate
```

The scripts themselves live once, at `~/.claude/agent-guard/`, and `shim.py`
runs them from there — so this repo commits one file instead of four and a fix
is one commit rather than one per repo. If that shared install is missing, the
shim says so and refuses; it never lets a gate look like it ran.
<!-- /maxi-quality:if-shared -->

`--gate` runs the command this repo declares in `.claude/agent-guard.json`,
whole and through one shell, so a gate written as `a && b` is recorded as a
gate rather than as its first half. It passes the gate's exit code straight
through. (`-- <command>` still works for an ad-hoc run, and is what you want
when the thing you are running is not the declared gate.)

A session cannot end while the working tree holds changes the gate has not
seen. If it refuses, the message says which of the four cases you are in: never
ran, ran and failed, ran something that was not this repo's gate, or ran against
different content.

<!-- maxi-quality:if-samples -->
**Do not write `.claude/agent-guard-receipt.json` by hand.** The `Edit` tool is
refused on it, and so is any edit under `samples/expected/` — those are deny
rules in `.claude/settings.json`, not advice. A shell command still reaches both
files, and for the receipt nothing downstream can tell: it is the gate's own
input, so a hand-written one passes. It is the single action here that turns a
guard into a lie.
<!-- /maxi-quality:if-samples -->
<!-- maxi-quality:unless-samples -->
**Do not write `.claude/agent-guard-receipt.json` by hand.** The `Edit` tool is
refused on it — that is a deny rule in `.claude/settings.json`, not advice. A
shell command still reaches the file, and nothing downstream can tell: it is
the gate's own input, so a hand-written one passes. It is the single action
here that turns a guard into a lie.
<!-- /maxi-quality:unless-samples -->

**Do not pass `--no-verify` to `git commit` or `git push`.** That is refused
too. It switches off this repo's commit hook, which is the last check before
content the gate has not seen becomes a commit. If the hook is failing for a
reason that is not your change, say so — do not route around it.

<!-- maxi-quality:if-samples -->
**`samples/` is the test suite, and it may not be weakened.** An edit that
removes an expected finding from `samples/expected/`, or removes lines from a
fixture a manifest cites, is refused. If a rule genuinely should stop firing,
change the config that stopped firing it and regenerate the manifest, so the
diff shows why. Adding a new failing case is always allowed and always welcome.
<!-- /maxi-quality:if-samples -->

<!-- END maxi-quality agent-guard -->
