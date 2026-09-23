#!/usr/bin/env python3
"""Codex PreToolUse adapter for apply_patch, using the shared sample policy.

Codex has no Claude permissions.deny array. This adapter refuses patch writes
at the receipt and expectation-manifest paths, and deletion-shaped weakening
of cited samples. Bash writes and specialized tools remain outside this filter.
An unknown patch grammar is denied with an actionable error, never silently
accepted as a checked patch. This is a drift guard, not a security boundary.
"""
from __future__ import annotations

import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guard import ALLOW, deny_tool, read_event, repo_root, warn  # noqa: E402


_sample = runpy.run_path(os.path.join(os.path.dirname(__file__), "sample-guard.py"))
fixture_shrink_reason = _sample["fixture_shrink_reason"]
read_text = _sample["read_text"]


class UnsupportedPatch(ValueError):
    pass


def changes(command: str) -> list[tuple[str, str, str | None, list[str]]]:
    """Read native patch file sections, without executing or writing the patch."""
    lines = command.strip().splitlines()
    if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise UnsupportedPatch("expected native Begin Patch / End Patch markers")
    result = []
    i = 1
    while i < len(lines) - 1:
        header = lines[i]
        kind = next((k for k in ("Add", "Update", "Delete")
                     if header.startswith(f"*** {k} File: ")), None)
        if kind is None:
            raise UnsupportedPatch("unrecognized file header")
        path = header.split(": ", 1)[1]
        if not path or "\x00" in path:
            raise UnsupportedPatch("empty or invalid file path")
        i += 1
        move = None
        if i < len(lines) - 1 and lines[i].startswith("*** Move to: "):
            if kind != "Update":
                raise UnsupportedPatch("only Update File can move a file")
            move = lines[i].split(": ", 1)[1]
            if not move or "\x00" in move:
                raise UnsupportedPatch("empty or invalid move path")
            i += 1
        body = []
        while i < len(lines) - 1:
            line = lines[i]
            if any(line.startswith(f"*** {k} File: ") for k in ("Add", "Update", "Delete")):
                break
            if kind == "Delete":
                raise UnsupportedPatch("Delete File has no patch body")
            if kind == "Add" and not line.startswith("+"):
                raise UnsupportedPatch("Add File expects added lines")
            if kind == "Update" and not (
                line.startswith((" ", "+", "-", "@@ "))
                or line in ("", "@@", "*** End of File")
            ):
                raise UnsupportedPatch("unrecognized update line")
            body.append(line)
            i += 1
        if kind == "Update" and not body:
            raise UnsupportedPatch("Update File has no hunk")
        result.append((kind, path, move, body))
    if not result:
        raise UnsupportedPatch("patch has no file changes")
    return result


def relative_path(raw: str, cwd: str, root: str) -> str | None:
    target = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(cwd, raw))
    if target != root and not target.startswith(root + os.sep):
        return None
    return os.path.relpath(target, root)


def main() -> int:
    event = read_event()
    if event is None:
        deny_tool("Codex patch guard could not read the hook payload; repair the hook input before retrying.")
        return ALLOW
    if event.get("tool_name") != "apply_patch":
        return ALLOW
    ti = event.get("tool_input")
    if not isinstance(ti, dict) or not isinstance(ti.get("command"), str):
        deny_tool("Codex patch guard requires tool_input.command containing the native patch; repair the hook input.")
        return ALLOW
    root = repo_root(event.get("cwd"))
    if root is None:
        warn("codex-patch-guard: not a Git checkout; protection is unavailable")
        return ALLOW
    root = os.path.realpath(root)
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else root
    try:
        operations = changes(ti["command"])
    except UnsupportedPatch as exc:
        deny_tool(f"Codex patch guard could not check this patch: {exc}. Use the native apply_patch format and retry.")
        return ALLOW
    for kind, raw, move, body in operations:
        for path in (raw, move):
            if path is None:
                continue
            rel = relative_path(path, cwd, root)
            if rel == ".claude/agent-guard-receipt.json":
                deny_tool("The gate receipt is recorder output. Run record-gate --gate; do not edit the receipt by hand.")
                return ALLOW
            if rel is not None and rel.startswith("samples/expected/"):
                deny_tool("Expectation manifests in samples/expected/ are assertions. Change the config and regenerate the manifest through its checker; do not patch expected findings by hand.")
                return ALLOW
        rel = relative_path(raw, cwd, root)
        current = read_text(os.path.join(root, rel)) if rel is not None else None
        delta = sum(line.startswith("+") - line.startswith("-") for line in body)
        if move is not None:
            destination = relative_path(move, cwd, root)
            existing = read_text(os.path.join(root, destination)) if destination is not None else None
            if existing is not None:
                if current is None:
                    deny_tool("Codex patch guard cannot check a move into this checkout from an unreadable source; use an in-checkout source and retry.")
                    return ALLOW
                reason = fixture_shrink_reason(root, destination, len(existing.splitlines()),
                                               len(current.splitlines()) + delta)
                if reason:
                    deny_tool(reason)
                    return ALLOW
        if rel is None or current is None:
            continue
        before = len(current.splitlines())
        # Native update hunks add/remove whole lines. Context and @@ selectors
        # don't change the count, including the optional End of File marker.
        # No attempt is made to reimplement Codex's fuzzy context matching.
        if kind == "Delete" or (move is not None and relative_path(move, cwd, root) != rel):
            after = 0
        elif kind == "Add":
            after = len(body)  # Add File can overwrite an existing path.
        else:
            after = before + delta
        reason = fixture_shrink_reason(root, rel, before, after)
        if reason:
            deny_tool(reason)
            return ALLOW
    return ALLOW


if __name__ == "__main__":
    sys.exit(main())
