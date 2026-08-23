#!/usr/bin/env python3
"""Shared machinery for the three agent-guard hooks.

WHY A FINGERPRINT AND NOT A RE-RUN

The `Stop` hook has to answer "has this repo's gate run against the code the
session is about to call done?". The obvious implementation is to run the gate
inside the hook. That was rejected: Layer 1 on a multi-language monorepo is
minutes, the hook runs on EVERY stop, and a guard that costs minutes per stop
is a guard someone deletes. So the hook answers the question from a receipt —
a recorded verdict plus a fingerprint of exactly what was verified — and the
comparison is a hash, not a toolchain.

WHAT THE FINGERPRINT COVERS

The content of every file that differs from HEAD: tracked modifications,
staged changes, and untracked files git would not ignore. Renames and
deletions move it. A file the gate never saw cannot be inside a receipt that
matches, which is the only property the Stop hook needs.

It deliberately does NOT cover HEAD itself. Committing does not invalidate a
receipt for content that did not change, and rebasing onto new upstream work
does not either — the gate ran on these changes, and CI is what gates the
merge. A receipt is a statement about a diff, not about a commit.

THIS GUARDS DRIFT, NOT MALICE

The `permissions.deny` half of this contract stops the FILE TOOLS writing the
receipt; a shell still can, and the receipt is this hook's own input, so a
hand-written one with a matching fingerprint passes and there is no backstop
that could catch it. None of this is hardened against that and it does not
need to be: the failure it exists to stop is a model that forgets, not a model
that lies. Saying so plainly matters, because a guard sold as tamper-proof
gets trusted for things it cannot do. configs/agent/README.md §3 states the
boundary in full.

FAIL OPEN ON OUR OWN PLUMBING, FAIL CLOSED ON POLICY

`hooks/pre-commit` has the same rule and states the same reason: a guard that
blocks on its own broken plumbing teaches people to switch it off, and then it
is not catching the real thing either. There is one difference here and it is
the reason this file exists rather than a shell one-liner: an agent hook is
NOT bypassable by the party it constrains. The model cannot pass `--no-verify`.
So a plumbing failure — no git, unreadable receipt, malformed stdin — must
exit 0 with a warning, or a broken install becomes a session nobody can end.
A policy failure — the gate did not run, the fixture was weakened — exits 2.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

# Where the receipt lives, relative to the repo root. Inside .claude/ because
# it is session state and belongs with the rest of it; NOT inside .git/,
# because a worktree and its main checkout share neither the working tree nor
# the answer to "was this verified".
RECEIPT = ".claude/agent-guard-receipt.json"

# Never part of a fingerprint — see changed_files().
EXCLUDED = frozenset({RECEIPT, RECEIPT + ".tmp"})

# Exit codes, named because the numbers are a Claude Code contract and not
# ours to choose: 0 lets the tool call or the stop proceed, 2 blocks it and
# feeds stderr back to the model. Any other non-zero is a non-blocking error.
ALLOW = 0
BLOCK = 2


def warn(msg: str) -> None:
    """A plumbing complaint. Goes to stderr, but the caller still exits 0."""
    print(f"agent-guard: {msg}", file=sys.stderr)


def git(*args: str, cwd: str | None = None) -> str:
    """Run git and return stdout, or raise CalledProcessError."""
    return subprocess.run(
        ("git", *args),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def repo_root(start: str | None = None) -> str | None:
    """The working tree root, or None if we are not in one.

    Located from the hook's own cwd rather than from an environment variable,
    so this behaves the same whether or not the caller exported anything.
    """
    try:
        return git("rev-parse", "--show-toplevel", cwd=start).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def changed_files(root: str) -> list[str]:
    """Repo-relative paths that differ from HEAD, sorted, deduplicated.

    `git status --porcelain -z` is the single source: it already merges the
    index and the working tree, already honours .gitignore for untracked
    files, and -z is the only form that survives a path with a space, a quote
    or a newline in it. The rename form carries two NUL-separated paths and
    both matter — a rename is a deletion the gate must not be able to miss.
    """
    try:
        out = git("status", "--porcelain=1", "-z", "--untracked-files=all", cwd=root)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []

    fields = out.split("\0")
    paths: set[str] = set()
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        # The receipt is the guard's OWN state, and it is written AFTER the
        # fingerprint it records. Left in, it changes the very hash it is
        # storing, so a passing gate's receipt never matches the next stop and
        # the session can never end. Found by samples/agent-guard, not by
        # reading this — which is the whole argument for the fixture.
        if path not in EXCLUDED:
            paths.add(path)
        # 'R' or 'C' in either column means the ORIGINAL path is the next
        # field. Consuming it is not optional: leave it in the stream and it
        # gets parsed as a status entry and silently mangles the rest.
        if "R" in status or "C" in status:
            if i < len(fields):
                if fields[i] not in EXCLUDED:
                    paths.add(fields[i])
                i += 1
    return sorted(paths)


def fingerprint(root: str) -> str:
    """A hash over the content of every changed file.

    `git hash-object` is used rather than a file read so that a file which is
    changed-but-absent (deleted, or a rename's old side) has a stable
    representation instead of raising. The path is in the digest too — moving
    identical content to a new path is a change the gate has not seen.
    """
    h = hashlib.sha256()
    for path in changed_files(root):
        full = os.path.join(root, path)
        try:
            blob = git("hash-object", "--", full, cwd=root).strip()
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            blob = "absent"
        h.update(path.encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        h.update(blob.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def read_receipt(root: str) -> dict | None:
    """The recorded verdict, or None if there is not a readable one."""
    try:
        with open(os.path.join(root, RECEIPT), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_event() -> dict | None:
    """The hook payload on stdin, or None if it is not a JSON object.

    Malformed stdin is plumbing, not policy: every caller of this treats None
    as "warn and allow".
    """
    try:
        data = json.loads(sys.stdin.read() or "null")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# The optional per-repo config. Its only job is to let the block message name
# the consumer's real gate command instead of a generic instruction, because a
# refusal that does not say what to run is a refusal the session works around.
CONFIG = ".claude/agent-guard.json"


def gate_command(root: str) -> str | None:
    """The command this repo calls its gate, if it declares one."""
    try:
        with open(os.path.join(root, CONFIG), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    cmd = data.get("gate_command") if isinstance(data, dict) else None
    return cmd if isinstance(cmd, str) and cmd.strip() else None


def emit(payload: dict) -> None:
    """Write a hook decision to stdout.

    Nothing else in these scripts may print to stdout. Claude Code parses the
    WHOLE of stdout as JSON and only when its first non-whitespace character is
    `{`; one stray print and the decision is silently downgraded to plain text
    that nothing acts on. That failure is invisible on exit 0 — it is recorded
    in the debug log and nowhere else — so it is worth one function and this
    comment rather than a bare print at three call sites.
    """
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def deny_tool(reason: str) -> None:
    """Refuse a PreToolUse call, with a reason the model actually receives.

    Exit 2 also blocks, but its stderr is what the model gets, and the JSON
    form is what the docs prefer because the reason is a structured field.
    Exit 0 is correct here: on a blocking event the decision comes from the
    JSON, and exiting 2 as well would block with a WORSE message.
    """
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })


def block_stop(reason: str) -> None:
    """Refuse a stop, with a reason fed back to the model as its next input.

    `Stop` takes a TOP-LEVEL `decision`, not the `hookSpecificOutput` shape
    PreToolUse takes. The two are not interchangeable and swapping them fails
    open — the wrong shape parses as JSON, carries no decision, and the stop
    proceeds with nothing reported.

    Exit 2 would also block, but for `Stop` the docs put its stderr in front
    of the USER only, while this `reason` is fed back to Claude so it keeps
    working. A guard whose instruction reaches only the human has not closed
    the loop it exists to close.
    """
    emit({"decision": "block", "reason": reason})
