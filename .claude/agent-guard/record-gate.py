#!/usr/bin/env python3
"""Run the gate, and record what it verified.

    python3 scripts/agent-guard/record-gate.py --gate
    python3 scripts/agent-guard/record-gate.py -- npm run gate

Runs the command with its output going where it always would, then writes
`.claude/agent-guard-receipt.json` describing the verdict and a fingerprint of
exactly the content the command saw. The command's own exit code is this
script's exit code, so putting the wrapper in front of a gate never changes
what CI or a human sees.

THE TWO FORMS, AND WHY THERE ARE TWO (#178)

`--` takes an argv the caller's own shell has already split. `--gate` takes no
command at all: it reads `gate_command` out of `.claude/agent-guard.json` and
runs THAT, whole, through one shell.

The second form exists because the first cannot be printed. The Stop hook's
refusal has to tell a session what to run, and interpolating a declared gate
into `record-gate.py -- <gate>` put any `&&`, `;` or `|` in it OUTSIDE this
wrapper: pasted, half the gate ran unrecorded and the receipt said "pass" for
a run whose second half had failed. `--gate` carries no operators, so there is
nothing left to paste wrong.

Note which input each form takes, because it is the whole of the reasoning
below about shells: `--` receives an argv, and `--gate` receives a string that
was never anything but a shell command.

WHY THE FINGERPRINT IS TAKEN BEFORE, NOT AFTER

A formatter is a gate that edits. Fingerprinting afterwards would record the
post-format tree as verified when what was checked was the pre-format one —
and worse, it would record a passing verdict for content no tool has read.
Taken before, a gate that rewrites files leaves a receipt that no longer
matches, and the next stop asks for another run. That is the correct outcome
and it is cheap: the second run is a no-op on already-formatted code.

WHY A FAILING RUN IS RECORDED AT ALL

Deleting the receipt on failure and writing one on success would be simpler,
and it would make "the gate failed" indistinguishable from "the gate never
ran". They deserve different messages: one is a bug to fix, the other is a
step to take. So the verdict is a field, not the file's existence.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import (  # noqa: E402
    CONFIG,
    RECEIPT,
    InspectionError,
    fingerprint,
    gate_argv,
    gate_command,
    is_declared_gate,
    repo_root,
)

USAGE = ("usage: record-gate.py --gate\n"
         "       record-gate.py [--] <command> [args...]")


def main(argv: list[str]) -> int:
    args = argv[1:]
    declared = None
    want_gate = bool(args) and args[0] == "--gate"
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print(USAGE, file=sys.stderr)
        return 3

    root = repo_root()
    if root is None:
        print("record-gate: not inside a git working tree", file=sys.stderr)
        return 3

    # WHICH REPO IS THIS FOR? (#192)
    #
    # `repo_root()` with no argument answers "whichever tree the shell happens
    # to be standing in". For the two hooks that is right — they get the repo
    # from the payload's `cwd`, which is where Claude is working. This script
    # has no payload, so it used cwd alone, and running one repo's recorder
    # from inside another wrote a PASSING receipt into the bystander: the
    # intended repo stayed ungated, and the other one's next stop was allowed.
    # Reproduced before this was written.
    #
    # An adopted install names its repo unambiguously — the script sits at
    # `<repo>/.claude/agent-guard/`, so the tree above it IS the answer, and a
    # cwd that disagrees is a mistake rather than a choice. Refusing is right
    # there: guessing either way silently gates the wrong tree.
    #
    # Any other layout falls through to cwd deliberately. That covers this
    # repo's own `scripts/agent-guard/` (which the fixtures run with cwd set to
    # a temp repo, legitimately) and leaves room for a shared install outside
    # any working tree, which #193 is about. The rule is deliberately narrow:
    # it closes the case where the script KNOWS better, and stays silent where
    # it does not.
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here) == "agent-guard" \
            and os.path.basename(os.path.dirname(here)) == ".claude":
        owner = repo_root(os.path.dirname(os.path.dirname(here)))
        if owner is not None and os.path.realpath(owner) != os.path.realpath(root):
            print("record-gate: this recorder belongs to\n"
                  f"  {owner}\n"
                  "but it was run from\n"
                  f"  {root}\n\n"
                  "Recording here would write a passing receipt into a repo "
                  "whose gate nobody ran, and leave the other one ungated. "
                  "Nothing was written. cd into the repo you meant, and run "
                  "its own recorder.", file=sys.stderr)
            return 3

    if want_gate:
        if len(args) > 1:
            print("record-gate: --gate takes no command; it runs the one "
                  f"{CONFIG} declares", file=sys.stderr)
            return 3
        declared = gate_command(root)
        if declared is None:
            # Nothing is written. A receipt for a gate that was never named
            # would be a pass for a run that did not happen, which is worse
            # than the absent receipt the Stop hook already knows how to
            # report.
            print(f"record-gate: no gate_command in {CONFIG}. Declare it "
                  'once:\n\n  echo \'{ "gate_command": "<your gate>" }\' > '
                  f"{CONFIG}\n\nOr pass the command directly: "
                  "record-gate.py -- <your gate>", file=sys.stderr)
            return 3
        args = list(gate_argv(declared))

    # A wrapped run of something that is not the declared gate is legal — the
    # `--` form is there for exactly that — but it produces a receipt the Stop
    # hook will refuse, and the useful place to say so is here, where the
    # command was chosen, rather than at the end of the next turn.
    if not want_gate:
        declared_here = gate_command(root)
        if declared_here is not None and not is_declared_gate(
                {"command": shlex.join(args)}, declared_here):
            print(f"record-gate: this is not the gate {CONFIG} declares, so "
                  "the receipt will not satisfy the Stop hook.\n"
                  f"  declared:  {declared_here}\n"
                  "  run it with --gate to record the declared gate instead.",
                  file=sys.stderr)

    try:
        receipt = execute_and_record(root, args, declared)
    except (InspectionError, OSError) as exc:
        print(f"record-gate: could not run or record the gate: {exc}", file=sys.stderr)
        return 3
    return receipt["exit_code"]


class RecordingError(OSError):
    """The command finished, but its receipt could not be persisted."""

    def __init__(self, receipt, cause):
        super().__init__(str(cause))
        self.receipt = receipt


def execute_and_record(root, args, declared, *, cwd=None, stdout=None, stderr=None):
    """Execute once and write the authoritative receipt; callers may retain output.

    The CLI keeps its historical working directory. Local project runners pass
    the explicit project root as cwd. Inspection and start failures raise, so a
    caller cannot mistake an older receipt for this invocation's result.
    """
    before = fingerprint(root)
    rc = subprocess.run(args, cwd=cwd, stdout=stdout, stderr=stderr).returncode
    receipt = {
        "fingerprint": before,
        "verdict": "pass" if rc == 0 else "fail",
        "exit_code": rc,
        # Preserve quoting: joining argv with spaces describes a different
        # command when the declaration contains shell operators (#178).
        "command": shlex.join(args),
        **({"gate_command": declared} if declared is not None else {}),
    }
    path = os.path.join(root, RECEIPT)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Atomic replacement keeps interrupted writes from becoming receipts.
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        raise RecordingError(receipt, exc) from exc

    return receipt


if __name__ == "__main__":
    sys.exit(main(sys.argv))
