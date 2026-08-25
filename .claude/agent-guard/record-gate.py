#!/usr/bin/env python3
"""Run the gate, and record what it verified.

    python3 scripts/agent-guard/record-gate.py -- npm run gate

Runs the command with its output going where it always would, then writes
`.claude/agent-guard-receipt.json` describing the verdict and a fingerprint of
exactly the content the command saw. The command's own exit code is this
script's exit code, so putting the wrapper in front of a gate never changes
what CI or a human sees.

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
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import RECEIPT, fingerprint, repo_root  # noqa: E402

USAGE = "usage: record-gate.py [--] <command> [args...]"


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print(USAGE, file=sys.stderr)
        return 3

    root = repo_root()
    if root is None:
        print("record-gate: not inside a git working tree", file=sys.stderr)
        return 3

    # BEFORE the command runs — see the module docstring.
    before = fingerprint(root)

    # No shell. The command arrives as a list from the caller's own shell, and
    # re-quoting it through `sh -c` here would turn a path with a space into
    # two arguments that fail in a way nobody would attribute to this wrapper.
    try:
        rc = subprocess.run(args).returncode
    except (OSError, FileNotFoundError) as exc:
        print(f"record-gate: could not run {args[0]!r}: {exc}", file=sys.stderr)
        return 3

    path = os.path.join(root, RECEIPT)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Written whole and replaced atomically: a receipt truncated by a Ctrl-C
    # mid-write is unparseable, and unparseable is treated as absent, which
    # would silently discard a passing run.
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "fingerprint": before,
                "verdict": "pass" if rc == 0 else "fail",
                "exit_code": rc,
                "command": " ".join(args),
            },
            fh,
            indent=2,
            sort_keys=True,
        )
        fh.write("\n")
    os.replace(tmp, path)

    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
