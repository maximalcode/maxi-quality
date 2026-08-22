#!/usr/bin/env python3
"""`PreToolUse` hook: refuse an edit that weakens the test suite.

WHAT IT ENFORCES

CONTRIBUTING.md says it in one line: "If a sample stops failing, the config
regressed — fix the config, do not weaken the sample." That is the single
instruction in this repo most likely to be followed backwards under pressure,
because deleting a planted finding turns a red gate green and looks like
progress. This refuses the two shapes that do it:

  1. removing entries from an expectation manifest in `samples/expected/`;
  2. removing lines from a fixture file that a manifest cites.

WHAT IT DELIBERATELY DOES NOT CLAIM

It does NOT decide whether a fixture still fires. That needs the toolchain the
fixture is for — five of them, minutes each — and putting that in front of
every edit is the cost that got the same idea rejected for the `Stop` hook.

So the honest statement of what this catches is DELETION-SHAPED weakening.
A same-size edit that defuses a finding in place — `==` to `===`, dropping an
`any`, renaming a variable so a rule stops matching — passes this hook. That
case is caught by `scripts/check-expected.py` in CI, which diffs the finding
SET per rule id and names the rule that stopped firing. This hook is the fast
filter in front of that gate, not a replacement for it, and it is worth having
only because the feedback arrives before the edit rather than eight minutes
after the push.

AND IT IS BYPASSABLE BY DESIGN OF THE TOOL SURFACE, NOT BY OVERSIGHT

A matcher sees `Edit` and `Write`. It does not see a heredoc in `Bash`, and
the docs say so plainly. `stop-gate.py` is the backstop: whatever wrote the
bytes, they are in `git status` at the end of the turn and the gate has to run
over them. Two hooks, one closing the fast path and one closing the loop.
"""

from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard import ALLOW, deny_tool, read_event, repo_root, warn  # noqa: E402

MANIFEST_DIR = os.path.join("samples", "expected")
SAMPLES = "samples"


def manifests(root: str) -> dict[str, dict]:
    """Every expectation manifest, keyed by repo-relative path."""
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(root, MANIFEST_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                out[os.path.relpath(path, root)] = json.load(fh)
        except (OSError, ValueError):
            continue
    return out


def finding_set(doc: object) -> set[tuple]:
    """The comparable set of findings in a manifest document."""
    if not isinstance(doc, dict):
        return set()
    found = doc.get("findings")
    if not isinstance(found, list):
        return set()
    return {
        (f.get("rule"), f.get("file"), f.get("line"))
        for f in found
        if isinstance(f, dict)
    }


def cited_files(root: str) -> set[str]:
    """Repo-relative fixture paths that some manifest names."""
    cited: set[str] = set()
    for doc in manifests(root).values():
        for rule, path, line in finding_set(doc):
            if isinstance(path, str):
                cited.add(path)
    return cited


def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, ValueError):
        return None


def proposed_text(tool: str, ti: dict, current: str | None) -> str | None:
    """The file content this tool call would leave behind, or None if unknown.

    None means "cannot tell" and every caller treats it as allow — the hook
    refuses on evidence, never on ignorance.
    """
    if tool == "Write":
        content = ti.get("content")
        return content if isinstance(content, str) else None

    if current is None:
        return None

    if tool == "Edit":
        old, new = ti.get("old_string"), ti.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        if old not in current:
            # The edit will fail anyway; nothing to judge.
            return None
        # replace_all is honoured, because refusing to model it would let the
        # one form that removes the MOST lines through unexamined.
        return (current.replace(old, new)
                if ti.get("replace_all") else current.replace(old, new, 1))

    if tool == "MultiEdit":
        edits = ti.get("edits")
        if not isinstance(edits, list):
            return None
        text = current
        for edit in edits:
            if not isinstance(edit, dict):
                return None
            old, new = edit.get("old_string"), edit.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str):
                return None
            if old not in text:
                return None
            text = (text.replace(old, new)
                    if edit.get("replace_all") else text.replace(old, new, 1))
        return text

    return None


def main() -> int:
    event = read_event()
    if event is None:
        warn("sample-guard: unreadable hook payload; allowing the call")
        return ALLOW

    tool = event.get("tool_name")
    ti = event.get("tool_input")
    if tool not in ("Edit", "Write", "MultiEdit") or not isinstance(ti, dict):
        return ALLOW

    raw = ti.get("file_path")
    if not isinstance(raw, str) or not raw:
        return ALLOW

    root = repo_root(event.get("cwd"))
    if root is None:
        return ALLOW

    # The path may be absolute or relative to the session's cwd, and either
    # may run through a symlink — /tmp on macOS is /private/tmp, and a repo
    # under it compares unequal to itself unless both sides are resolved.
    base = event.get("cwd") if isinstance(event.get("cwd"), str) else root
    target = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(base, raw))
    # Belt and braces: `git rev-parse --show-toplevel` already returns a
    # resolved path, so no fixture can falsify this line and the mutation
    # table in the README says so rather than leaving it looking covered. The
    # TARGET side above is the one under test, and it is the one that breaks.
    rroot = os.path.realpath(root)
    if not (target == rroot or target.startswith(rroot + os.sep)):
        return ALLOW
    rel = os.path.relpath(target, rroot)

    # Everything outside samples/ is ordinary work this hook has no opinion on.
    if rel != SAMPLES and not rel.startswith(SAMPLES + os.sep):
        return ALLOW

    current = read_text(target)
    proposed = proposed_text(tool, ti, current)
    if proposed is None:
        return ALLOW

    # --- a manifest: compare the finding sets ------------------------------
    if rel.startswith(MANIFEST_DIR + os.sep) and rel.endswith(".json"):
        if current is None:
            return ALLOW  # a NEW manifest removes nothing
        try:
            after = finding_set(json.loads(proposed))
        except ValueError:
            # The result would not parse. CI fails loudly on that; this hook
            # does not stand in for it.
            return ALLOW
        removed = finding_set(json.loads(current)) if current.strip() else set()
        gone = removed - after
        if gone:
            listed = ", ".join(sorted({str(r) for r, _f, _l in gone})[:5])
            deny_tool(
                f"This edit removes {len(gone)} expected finding(s) from {rel} "
                f"({listed}). An expectation manifest is the assertion, not a "
                "record of what currently happens: deleting an entry makes the "
                "gate agree with the regression.\n\nIf the rule genuinely "
                "should no longer fire, change the CONFIG that stopped firing "
                "it and regenerate with `--update`, so the diff shows why. If "
                "you are removing a fixture on purpose, say so and a human "
                "will do it."
            )
            return ALLOW
        return ALLOW

    # --- a cited fixture: refuse a shrink ----------------------------------
    if rel in cited_files(root) and current is not None:
        before, after = len(current.splitlines()), len(proposed.splitlines())
        if after < before:
            deny_tool(
                f"This edit removes {before - after} line(s) from {rel}, which "
                "an expectation manifest in samples/expected/ cites as the "
                "location of a planted finding. samples/ is the test suite: a "
                "fixture that stops failing means the config regressed.\n\n"
                "Fix the config instead. Adding a NEW failing case to this "
                "file is always allowed."
            )
            return ALLOW

    return ALLOW


if __name__ == "__main__":
    sys.exit(main())
