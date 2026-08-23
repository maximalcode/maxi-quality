<!-- maxi-quality: agent guard — appended by hand today, by adopt.sh later.
     Keep the markers; they are how the region is upgraded without a merge. -->
<!-- BEGIN maxi-quality agent-guard -->

## The gate, and how a session ends

This repo's quality baseline is enforced by three hooks and two deny rules in
`.claude/settings.json`. They are not advice — they refuse.

**Run the gate through the recorder, not directly:**

```bash
python3 .claude/agent-guard/record-gate.py -- <this repo's gate command>
```

That runs the gate exactly as it always ran, passes its exit code straight
through, and records what it verified. A session cannot end while the working
tree holds changes the gate has not seen. If it refuses, the message says which
of the three cases you are in: never ran, ran and failed, or ran against
different content.

**Do not write `.claude/agent-guard-receipt.json` by hand.** The `Edit` tool is
refused on it, and so is any edit under `samples/expected/` — those are deny
rules in `.claude/settings.json`, not advice. A shell command still reaches both
files, and for the receipt nothing downstream can tell: it is the gate's own
input, so a hand-written one passes. It is the single action here that turns a
guard into a lie.

**Do not pass `--no-verify` to `git commit` or `git push`.** That is refused
too. It switches off this repo's commit hook, which is the last check before
content the gate has not seen becomes a commit. If the hook is failing for a
reason that is not your change, say so — do not route around it.

**`samples/` is the test suite, and it may not be weakened.** An edit that
removes an expected finding from `samples/expected/`, or removes lines from a
fixture a manifest cites, is refused. If a rule genuinely should stop firing,
change the config that stopped firing it and regenerate the manifest, so the
diff shows why. Adding a new failing case is always allowed and always welcome.

<!-- END maxi-quality agent-guard -->
