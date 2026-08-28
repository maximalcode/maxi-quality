#!/usr/bin/env python3
"""Run a guard script from the shared install, or refuse loudly (#193).

This is the whole of what `adopt.sh --agent --shared` puts in a repo. The
scripts themselves live once, at `~/.claude/agent-guard/`, so a fix is one
commit instead of one per consumer.

    python3 .claude/agent-guard/shim.py stop-gate

WHY THIS IS COMMITTED AND THE BODY IS NOT

The body is per-machine; the shim is per-repo, and it is committed so that the
repo can say what it expects. That is the property a plugin cannot have: with
a plugin uninstalled, a tree carries a config claiming it is adopted and
nothing else — no hook, no rule, no message. Here the wiring is present, the
shim runs, and it says exactly what is missing.

WHY A MISSING BODY REFUSES RATHER THAN WARNING

Everything else in this contract fails OPEN on plumbing, deliberately:
guard.py's header explains that an agent hook cannot be bypassed by the party
it constrains, so a broken install must not make a repo unendable. A missing
body is NOT plumbing. It is the guard being absent, and absence that allows is
the exact silent failure this design exists to prevent.

So the degraded behaviour is graded by what each hook is protecting:

  stop-gate         BLOCK. The turn cannot end. This is the backstop for the
                    other two, and it is the one refusal that cannot be
                    walked around, so it carries the install instruction.
  no-verify-guard   DENY, but only for a git commit/push. A missing body must
                    not mean every Bash call is refused; it must mean the one
                    command that would slip past the absent guard is.
  sample-guard      allow, with a warning. Its absence cannot let work escape
                    the repo — the Stop hook above is still refusing — and
                    denying every edit would make a broken install unusable.
  record-gate       exit 3. A recorder that cannot run must not look like one
                    that ran.
"""

from __future__ import annotations

import json
import os
import sys

BODY = os.path.join(os.path.expanduser("~"), ".claude", "agent-guard")
INSTALL = "scripts/adopt.sh --install-shared   (from your maxi-quality checkout)"


def missing(name: str) -> int:
    """Say what is absent, in the shape the caller's event understands."""
    where = f"The shared agent guard is not installed at {BODY}.\n\nInstall it:\n\n  {INSTALL}"
    if name == "stop-gate":
        json.dump({"decision": "block", "reason":
                   f"{where}\n\nThis repo is wired for the guard and the guard "
                   "is not here, so nothing is checking that your gate ran."},
                  sys.stdout)
        sys.stdout.write("\n")
        return 0
    if name == "no-verify-guard":
        # Only for the command that would otherwise slip past. Reading the
        # payload crudely is right here: this path exists because the real
        # tokenizer is absent, and erring toward refusal is the safe direction.
        try:
            cmd = (json.loads(sys.stdin.read() or "{}")
                   .get("tool_input", {}).get("command", ""))
        except (ValueError, AttributeError):
            cmd = ""
        if "git" in cmd and ("commit" in cmd or "push" in cmd):
            json.dump({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason":
                    f"{where}\n\nUntil it is, this repo cannot tell a "
                    "`--no-verify` from an ordinary commit, so commits and "
                    "pushes are refused rather than let through unchecked."}},
                sys.stdout)
            sys.stdout.write("\n")
        return 0
    print(f"agent-guard: {where}", file=sys.stderr)
    return 3 if name == "record-gate" else 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: shim.py <script-name> [args...]", file=sys.stderr)
        return 3
    name = argv[1]
    target = os.path.join(BODY, name + ".py")
    if not os.path.isfile(target):
        return missing(name)
    # execv, not import: the child keeps this process's stdin, stdout and exit
    # code exactly, which is the whole contract with Claude Code. An import
    # would put this file's own frames in any traceback and make `__main__`
    # mean something different than when the script is run directly.
    os.execv(sys.executable, [sys.executable, target, *argv[2:]])
    return 3  # unreachable; execv does not return


if __name__ == "__main__":
    sys.exit(main(sys.argv))
