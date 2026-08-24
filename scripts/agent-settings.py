#!/usr/bin/env python3
"""Merge `configs/agent/settings.json` into a consumer's own one (issue #165).

WHY THIS IS A MERGE AND `--editor` IS NOT

`adopt.sh --editor` refuses when `.vscode/settings.json` already exists, and
that is right for that file: it gates nothing, and a consumer who already has
one has opinions about it. This file is the opposite on both counts. It is
executable policy — the hooks that refuse — and a repo that already runs Claude
Code almost always HAS a `.claude/settings.json`. Refuse-if-exists there would
mean the contract never adopts anywhere it matters, and overwrite would mean
the first thing the baseline does in someone's tree is delete their own hooks.

So: a key-level merge with ownership. Every baseline entry is appended to what
the consumer already has, matched so a second run recognises what the first one
wrote. Nothing of the consumer's is replaced, reordered or removed — not their
hook entries, not their deny rules, not any other key in the file.

WHAT IDENTIFIES A BASELINE ENTRY

A hook entry by its `command` string, a deny rule by the rule string itself.
Nothing else — no marker key, no counter, no separate manifest. Those are the
shapes that go stale when a consumer hand-edits the file, and this file is one
people hand-edit. The `command` strings all contain the agent-guard directory
path, so they are recognisable to a reader as well as to this script.

IT NEVER WRITES A FILE IT CANNOT READ BACK

A settings file this script does not fully understand is refused, and refused
BEFORE anything is written. Two reasons, and the second is the load-bearing
one. A file that does not parse is a file whose contents we would be guessing
at. And a `hooks` key whose shape is not the documented one is a file where
"append to the array" has no meaning — writing a plausible guess there
produces a settings.json Claude Code reports as broken in a startup line
nobody reads, and then the whole contract silently does nothing. Refusing
loudly is strictly better than adopting invisibly.

Usage:
  agent-settings.py merge --baseline configs/agent/settings.json \
                          --target <repo>/.claude/settings.json [--dry-run]

Exit codes:
  0  merged (or already merged — this is idempotent)
  1  refused: the target does not parse, or its shape is not the documented one
  3  usage error
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# The four events this contract knows how to merge into. A baseline that grows
# a fifth is fine; a CONSUMER key we have never heard of is left completely
# alone, which is why this list constrains only what we validate deeply.
KNOWN_EVENTS = ("PreToolUse", "PostToolUse", "Stop", "SubagentStop")


class Refused(Exception):
    """The target cannot be merged into. Nothing has been written."""


def die(msg: str) -> None:
    print(f"agent-settings: {msg}", file=sys.stderr)
    raise SystemExit(3)


# --- shape validation --------------------------------------------------------
#
# Deliberately strict about the two keys this script writes into and silent
# about every other key in the file. Validating a consumer's unrelated settings
# would turn "we could not merge" into "we disapprove of your config", and this
# script has no standing to do that.


def _check_hooks(hooks: object, where: str) -> None:
    if not isinstance(hooks, dict):
        raise Refused(
            f"{where}: `hooks` is {type(hooks).__name__}, and the documented "
            "shape is an object keyed by event name. Nothing was written."
        )
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise Refused(
                f"{where}: `hooks.{event}` is {type(groups).__name__}, and the "
                "documented shape is an array of matcher groups. Nothing was "
                "written."
            )
        for i, group in enumerate(groups):
            at = f"hooks.{event}[{i}]"
            if not isinstance(group, dict):
                raise Refused(f"{where}: `{at}` is not an object. Nothing was written.")
            if "matcher" in group and not isinstance(group["matcher"], str):
                raise Refused(
                    f"{where}: `{at}.matcher` is not a string. Nothing was written."
                )
            entries = group.get("hooks")
            if not isinstance(entries, list):
                raise Refused(
                    f"{where}: `{at}.hooks` is "
                    f"{type(entries).__name__}, and the documented shape is an "
                    "array of hook entries. Nothing was written."
                )
            for j, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise Refused(
                        f"{where}: `{at}.hooks[{j}]` is not an object. Nothing "
                        "was written."
                    )
                if not isinstance(entry.get("command"), str):
                    raise Refused(
                        f"{where}: `{at}.hooks[{j}]` has no string `command`. "
                        "That is the field this merge matches on, so a merge "
                        "into it could not be made idempotent. Nothing was "
                        "written."
                    )


def _check_deny(settings: dict, where: str) -> None:
    permissions = settings.get("permissions")
    if permissions is None:
        return
    if not isinstance(permissions, dict):
        raise Refused(
            f"{where}: `permissions` is {type(permissions).__name__}, and the "
            "documented shape is an object. Nothing was written."
        )
    deny = permissions.get("deny")
    if deny is None:
        return
    if not isinstance(deny, list) or any(not isinstance(r, str) for r in deny):
        raise Refused(
            f"{where}: `permissions.deny` is not an array of strings. A deny "
            "rule is a string; anything else in that array is a rule Claude "
            "Code will not enforce. Nothing was written."
        )


def validate(settings: object, where: str) -> dict:
    if not isinstance(settings, dict):
        raise Refused(
            f"{where}: the top level is {type(settings).__name__}, not a JSON "
            "object. Nothing was written."
        )
    if "hooks" in settings:
        _check_hooks(settings["hooks"], where)
    _check_deny(settings, where)
    return settings


def load(path: str) -> dict:
    """Parse and validate a settings file. A missing file is an empty one."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise Refused(
            f"{path}: does not parse as JSON ({exc}). This file is strict "
            "JSON, not JSONC — a trailing comma or a comment is enough. Fix it "
            "and re-run. Nothing was written."
        ) from exc
    except OSError as exc:
        raise Refused(f"{path}: cannot be read ({exc}). Nothing was written.") from exc
    return validate(data, path)


# --- the merge itself --------------------------------------------------------


def commands_in(groups: list) -> set:
    """Every `command` string already present under one event, at any depth."""
    return {
        entry["command"]
        for group in groups
        for entry in group.get("hooks", [])
    }


def merge_hooks(target: dict, baseline: dict) -> list[str]:
    """Append the baseline's hook entries to the target's. Returns what changed.

    Matching is on the `command` string and NOT on the matcher, so a consumer
    who has moved one of these entries into a group of their own — a different
    matcher, an extra hook beside it — is left alone rather than given a second
    copy. That is the case that decides between "idempotent" and "hooks double
    on every re-adoption", and it is not hypothetical: merging into a group by
    matcher and checking for duplicates within that group only would re-add an
    entry the consumer had deliberately relocated.
    """
    changed: list[str] = []
    base_hooks = baseline.get("hooks") or {}
    if not base_hooks:
        return changed

    hooks = target.setdefault("hooks", {})
    for event, base_groups in base_hooks.items():
        groups = hooks.setdefault(event, [])
        present = commands_in(groups)
        for base_group in base_groups:
            matcher = base_group.get("matcher")
            wanted = [
                entry for entry in base_group.get("hooks", [])
                if entry["command"] not in present
            ]
            if not wanted:
                continue
            # An existing group with the SAME matcher is the one to extend —
            # a second group with an identical matcher is legal and runs, but
            # it reads as a mistake and diffs like one.
            host = next(
                (g for g in groups if g.get("matcher") == matcher),
                None,
            )
            if host is None:
                host = {k: v for k, v in base_group.items() if k != "hooks"}
                host["hooks"] = []
                groups.append(host)
            host.setdefault("hooks", []).extend(json.loads(json.dumps(wanted)))
            for entry in wanted:
                changed.append(f"hooks.{event}: + {entry['command']}")
                present.add(entry["command"])
    return changed


def merge_deny(target: dict, baseline: dict) -> list[str]:
    """Append the baseline's deny rules, in order, skipping ones already there."""
    changed: list[str] = []
    base_deny = ((baseline.get("permissions") or {}).get("deny")) or []
    if not base_deny:
        return changed

    permissions = target.setdefault("permissions", {})
    deny = permissions.setdefault("deny", [])
    for rule in base_deny:
        if rule in deny:
            continue
        deny.append(rule)
        changed.append(f"permissions.deny: + {rule}")
    return changed


def render(settings: dict) -> str:
    """Two-space JSON with a trailing newline — what Claude Code itself writes."""
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def write_atomically(path: str, text: str) -> None:
    """Write via a temp file, and parse the result back before moving it.

    A half-written settings.json is the failure mode this whole script is
    organised around: Claude Code reports it once at startup and then behaves
    as though the file said nothing. The read-back is cheap and turns "we
    produced something unreadable" into an error at the moment it happens.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.maxi-quality.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(tmp, encoding="utf-8") as fh:
            json.load(fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    m = sub.add_parser("merge", help="merge the baseline into a target settings.json")
    m.add_argument("--baseline", required=True)
    m.add_argument("--target", required=True)
    m.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing. adopt.sh runs this "
             "first on every run, so a refusal costs the consumer no half-"
             "adopted tree.",
    )
    args = parser.parse_args(argv)

    try:
        baseline = load(args.baseline)
    except Refused as exc:
        # A broken BASELINE is our bug, not the consumer's, and saying so is
        # the difference between "fix your repo" and "file an issue".
        die(f"the baseline itself is unusable — this is a bug in maxi-quality, "
            f"not in your repo: {exc}")
        return 3  # unreachable; keeps the type checker and the reader honest
    if not baseline:
        die(f"{args.baseline}: not found")

    try:
        target = load(args.target)
    except Refused as exc:
        print(f"agent-settings: refused. {exc}", file=sys.stderr)
        return 1

    changed = merge_hooks(target, baseline) + merge_deny(target, baseline)
    for line in changed:
        print(line)
    if not changed:
        print("already merged — no change")
        return 0
    if not args.dry_run:
        write_atomically(args.target, render(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
