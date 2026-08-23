#!/usr/bin/env python3
"""`Stop` hook: a session may not call it done on code the gate has not seen.

WHAT IT ENFORCES

At the end of every turn, the content that differs from HEAD is fingerprinted
and compared against the receipt written by `record-gate.py`. No receipt, a
stale one, or a failing one, and the stop is refused with an instruction to
run the gate. This is the rule CLAUDE.md files ask for and nothing enforces:
"run the checks before you say it is finished".

WHY IT IS ALSO THE BACKSTOP FOR THE OTHER HOOK

The docs are explicit that a tool matcher does not see everything: "Claude can
also create or modify files by running shell commands", and the recommended
answer is "a Stop hook that scans the working tree once per turn". So
`sample-guard.py` can be walked around with a heredoc, and this cannot —
whatever wrote the bytes, they are in `git status` at the end of the turn.
That is why the fixture asserts a Bash-written change is caught here.

THE LOOP GUARD IS NOT OPTIONAL

Claude Code overrides a Stop hook after it blocks eight times in a row, and a
hook that keeps blocking burns eight turns before the override. `stop_hook_active`
is true once this hook has already caused a continuation, and the documented
handling is to exit early. Without it, a repo whose gate cannot pass — a
broken toolchain, a pre-existing failure nobody has fixed yet — becomes a repo
where no session can end.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import (  # noqa: E402
    ALLOW,
    RECEIPT,
    block_stop,
    changed_files,
    fingerprint,
    gate_command,
    read_event,
    read_receipt,
    repo_root,
    warn,
)


def instruction(root: str) -> str:
    """What to run, named as concretely as this repo allows."""
    cmd = gate_command(root)
    if cmd:
        return f"python3 scripts/agent-guard/record-gate.py -- {cmd}"
    return (
        "python3 scripts/agent-guard/record-gate.py -- <the gate command your "
        f"CLAUDE.md names>  (or declare it once as gate_command in .claude/"
        "agent-guard.json so this message can name it for you)"
    )


def main() -> int:
    event = read_event()
    if event is None:
        warn("stop: unreadable hook payload; allowing the stop")
        return ALLOW

    # Documented loop guard. Checked before anything else, so a repo that
    # cannot pass its own gate costs one blocked turn rather than eight.
    if event.get("stop_hook_active") is True:
        return ALLOW

    root = repo_root(event.get("cwd"))
    if root is None:
        warn("stop: not inside a git working tree; allowing the stop")
        return ALLOW

    changed = changed_files(root)
    if not changed:
        # Nothing differs from HEAD. There is no such thing as an ungated
        # change here, and a read-only session must not be made to run a gate.
        return ALLOW

    receipt = read_receipt(root)
    current = fingerprint(root)

    if receipt is None:
        block_stop(
            f"The gate has not run. {len(changed)} file(s) differ from HEAD and "
            f"there is no {RECEIPT}.\n\nRun it, then stop:\n\n  "
            f"{instruction(root)}\n\nIf it fails, fix what it reports — do not "
            "record a receipt by hand."
        )
        return ALLOW

    if receipt.get("verdict") != "pass":
        block_stop(
            "The last recorded gate run FAILED"
            + (f" ({receipt['command']})" if isinstance(receipt.get("command"), str) else "")
            + ".\n\nFix what it reported and run it again:\n\n  "
            f"{instruction(root)}"
        )
        return ALLOW

    if receipt.get("fingerprint") != current:
        block_stop(
            "The gate passed, but the working tree has changed since — the "
            "recorded verdict describes code that no longer exists.\n\nRun it "
            f"again, then stop:\n\n  {instruction(root)}"
        )
        return ALLOW

    return ALLOW


if __name__ == "__main__":
    sys.exit(main())
