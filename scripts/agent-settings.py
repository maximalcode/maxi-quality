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


def _shape(value: object) -> str:
    """A type name a reader recognises. `NoneType` is not one of those."""
    return "null" if value is None else type(value).__name__


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
            f"{where}: `hooks` is {_shape(hooks)}, and the documented "
            "shape is an object keyed by event name. Nothing was written."
        )
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise Refused(
                f"{where}: `hooks.{event}` is {_shape(groups)}, and the "
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
                    f"{_shape(entries)}, and the documented shape is an "
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
    # `key not in` rather than `get(...) is None` at both levels. An explicit
    # null is NOT an absent key: it reaches the merge as a real value, and
    # `{}.setdefault("deny", [])` on a dict that already holds None hands back
    # the None. Treating the two as the same is how this used to answer a
    # malformed settings.json with a traceback instead of the sentence below.
    if "permissions" not in settings:
        return
    permissions = settings["permissions"]
    if not isinstance(permissions, dict):
        raise Refused(
            f"{where}: `permissions` is {_shape(permissions)}, and the "
            "documented shape is an object. Nothing was written."
        )
    if "deny" not in permissions:
        return
    deny = permissions["deny"]
    if not isinstance(deny, list) or any(not isinstance(r, str) for r in deny):
        raise Refused(
            f"{where}: `permissions.deny` is not an array of strings. A deny "
            "rule is a string; anything else in that array is a rule Claude "
            "Code will not enforce. Nothing was written."
        )


def validate(settings: object, where: str) -> dict:
    if not isinstance(settings, dict):
        raise Refused(
            f"{where}: the top level is {_shape(settings)}, not a JSON "
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
            text = fh.read()
    except OSError as exc:
        raise Refused(f"{path}: cannot be read ({exc}). Nothing was written.") from exc
    # An empty file is the one unparseable case that involves no guessing: it
    # says nothing, so merging into it can lose nothing. `touch
    # .claude/settings.json` is common enough that refusing it would be a
    # refusal with no useful remedy — "fix your JSON" about a file with none.
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise Refused(
            f"{path}: does not parse as JSON ({exc}). This file is strict "
            "JSON, not JSONC — a trailing comma or a comment is enough. Fix it "
            "and re-run. Nothing was written."
        ) from exc
    return validate(data, path)


# --- the merge itself --------------------------------------------------------


def commands_in(groups: list) -> set:
    """Every `command` string already present under one event, at any depth."""
    return {
        entry["command"]
        for group in groups
        for entry in group.get("hooks", [])
    }


# Every command this script has ever written points inside this directory. A
# consumer's own hooks do not, so the marker is what separates "ours to
# reclaim" from "theirs to leave alone" — the distinction the append-only rule
# was missing (#196).
OURS = "/.claude/agent-guard/"


def prune_ours(target: dict, keep: set) -> list[str]:
    """Drop hook entries WE wrote that this run no longer wires.

    THE FAILURE THIS EXISTS FOR (#196)

    `merge_hooks` appends and never removes, deliberately: it must not delete a
    consumer's own entries. But entries pointing into `.claude/agent-guard/`
    are not the consumer's, they are this script's, and leaving a stale one is
    not conservative — it is a `settings.json` naming a file that adoption has
    since stopped installing.

    That is not a cosmetic inconsistency. A hook whose script is missing fails
    at exec, before any of guard.py's fail-open handling can run, and Claude
    Code treats a PreToolUse hook error as blocking. The result is a repo where
    every Bash, Write and Edit call fails — observed, in this repo and in a
    consumer whose broken state had already been committed and merged.

    Reached by two ordinary paths, neither of them a mistake on its own: a
    profile that narrows (#182 stopped wiring the samples rules in a tree with
    no manifests) and a mode change (#193's --shared wires a shim instead of
    the scripts).
    """
    removed = []
    for event, groups in list((target.get("hooks") or {}).items()):
        for group in groups:
            surviving = []
            for entry in group.get("hooks", []):
                cmd = entry.get("command", "")
                if OURS in cmd and cmd not in keep:
                    removed.append(f"hooks.{event}: - {cmd}")
                    continue
                surviving.append(entry)
            group["hooks"] = surviving
        # A group we emptied is ours too; one the consumer emptied was already
        # empty and is left exactly as found.
        target["hooks"][event] = [g for g in groups if g.get("hooks")]
    return removed


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


# The two rules that only fire in a tree with expectation manifests: the hook
# that refuses a weakening edit under `samples/`, and the deny rule over
# `samples/expected/`. Named by the substring that identifies each, because a
# rule is identified by its command/rule string everywhere else in this file
# and adding a second identity scheme is how the two drift apart.
SAMPLES_ONLY_COMMAND = "sample-guard.py"
SAMPLES_ONLY_DENY = "/samples/expected/"


def without_samples(baseline: dict) -> dict:
    """The baseline minus the two rules a tree with no manifests cannot use.

    WHY THIS IS DROPPED RATHER THAN SHIPPED-AND-INERT (#182)

    `sample-guard.py` hardcodes `samples/` and `samples/expected/`. In a
    consumer that has neither, the hook is reachable, runs, and allows
    everything — and the deny rule matches no file that exists. Installed
    anyway, they made a tree whose CLAUDE.md stated it was protected by three
    hooks and two deny rules, a third of which could never fire. That is the
    "looks adopted and enforces nothing" outcome adopt.sh's own comments say it
    exists to avoid, one level in.

    Not made configurable, though a consumer pointing this at their own fixture
    manifests is the obvious next idea: no consumer has asked, and CLAUDE.md §4
    is explicit that a config with no real project behind it is dead weight.
    Re-running `--agent` after a `samples/expected/` appears installs both.
    """
    out = json.loads(json.dumps(baseline))
    groups = (out.get("hooks") or {}).get("PreToolUse") or []
    for group in groups:
        group["hooks"] = [e for e in group.get("hooks", [])
                          if SAMPLES_ONLY_COMMAND not in e.get("command", "")]
    out.setdefault("hooks", {})["PreToolUse"] = [g for g in groups if g.get("hooks")]
    deny = ((out.get("permissions") or {}).get("deny")) or []
    out.setdefault("permissions", {})["deny"] = [
        r for r in deny if not (isinstance(r, str) and SAMPLES_ONLY_DENY in r)]
    return out


# The two scripts no hook command names, and why each is still installed.
#   guard.py       — imported by every hook; nothing runs it directly.
#   record-gate.py — the CLI a human or CI runs to produce the receipt. The
#                    Stop hook's refusal prints it by name, so a tree without
#                    it has a remedy that does not exist.
UNWIRED_BUT_NEEDED = ("guard.py", "record-gate.py")


SHIM = "shim.py"


def shared(baseline: dict) -> dict:
    """The same wiring, routed through the shim instead of the scripts (#193).

    `.../stop-gate.py`  ->  `.../shim.py stop-gate`

    Derived from the same baseline rather than kept as a second settings file,
    for the reason the profile is: two files drift, and the drift is invisible
    because no consumer holds both. A repo installed with --shared and one
    installed without must wire the SAME rules; only where the code lives
    differs.
    """
    out = json.loads(json.dumps(baseline))
    for groups in (out.get("hooks") or {}).values():
        for group in groups:
            for entry in group.get("hooks", []):
                cmd = entry.get("command", "")
                if not cmd.endswith('.py"'):
                    continue
                head, _, tail = cmd.rpartition("/")
                name = tail[:-len('.py"')]
                entry["command"] = f'{head}/{SHIM}" {name}'
    return out


def scripts_for(baseline: dict) -> list[str]:
    """The .py files a tree wired with `baseline` actually needs.

    Derived from the hook commands rather than listed, so there is ONE place
    that decides what a profile installs. adopt.sh copies this set and
    check-agent-contract.py G9 compares against it; a hardcoded list in either
    would be a second source of truth for the question the first one answers,
    which is the drift this whole script exists to prevent (#191).

    What this excludes, deliberately:

      * `selftest.py` — the baseline's own corpus runner. It needs
        samples/agent-guard/, which adoption does not carry, so it can never
        run in a consumer. 508 lines, 29% of the old install, in every tree
        that would ever exist. Both `adopt.sh` and configs/agent/README.md
        described it as dead weight and copied it anyway.
      * `sample-guard.py` in a tree with no expectation manifests — #182
        stopped WIRING it there and the copy loop was not revisited, so a
        consumer got a hook script nothing referenced. That is the condition
        `check-agent-contract.py` G1 fails the baseline for.
    """
    names = {c.rsplit("/", 1)[-1].rstrip('"')
             for groups in (baseline.get("hooks") or {}).values()
             for group in groups
             for entry in group.get("hooks", [])
             for c in [entry.get("command", "")] if c.endswith('.py"') or c.endswith(".py")}
    return sorted(names | set(UNWIRED_BUT_NEEDED))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    m = sub.add_parser("merge", help="merge the baseline into a target settings.json")
    m.add_argument("--baseline", required=True)
    m.add_argument("--target", required=True)
    m.add_argument(
        "--shared",
        action="store_true",
        help="wire the shim instead of copied scripts (#193)",
    )
    m.add_argument(
        "--without-samples",
        action="store_true",
        help="omit the two rules that only fire in a tree with expectation "
             "manifests under samples/expected/ (#182)",
    )
    m.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change and write nothing. adopt.sh runs this "
             "first on every run, so a refusal costs the consumer no half-"
             "adopted tree.",
    )
    v = sub.add_parser("verify", help="every hook command names a file that exists")
    v.add_argument("--target", required=True, help="the settings.json to check")
    v.add_argument("--root", required=True, help="what ${CLAUDE_PROJECT_DIR} means")
    s = sub.add_parser("scripts", help="the .py files a profile actually needs")
    s.add_argument("--baseline", required=True)
    s.add_argument("--without-samples", action="store_true")
    s.add_argument("--shared", action="store_true",
                   help="ignored; the shared body carries every script")
    args = parser.parse_args(argv)

    if args.mode == "verify":
        # Deliberately NOT going through load(): this asks whether the file we
        # just wrote is usable, and a file too broken to parse is the loudest
        # possible answer to that.
        try:
            with open(args.target, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"agent-settings: cannot read {args.target}: {exc}",
                  file=sys.stderr)
            return 1
        missing = []
        for groups in ((doc.get("hooks") or {}) if isinstance(doc, dict) else {}).values():
            for group in groups:
                for entry in group.get("hooks", []):
                    cmd = entry.get("command", "")
                    if '"' not in cmd:
                        continue
                    if OURS not in cmd:
                        # A consumer's own hook pointing at their own missing
                        # script is their business and predates this run.
                        # Refusing their adoption over it would be this script
                        # taking responsibility for a file it never wrote.
                        continue
                    path = cmd.split('"')[1].replace("${CLAUDE_PROJECT_DIR}", args.root)
                    if not os.path.isfile(path):
                        missing.append(path)
        for m in missing:
            print(f"agent-settings: a hook command names a missing file: {m}",
                  file=sys.stderr)
        return 1 if missing else 0

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
    if args.without_samples:
        baseline = without_samples(baseline)
    if getattr(args, "shared", False) and args.mode == "merge":
        baseline = shared(baseline)
    if args.mode == "scripts":
        print("\n".join(scripts_for(baseline)))
        return 0

    try:
        target = load(args.target)
    except Refused as exc:
        print(f"agent-settings: refused. {exc}", file=sys.stderr)
        return 1

    keep = {e.get("command", "")
            for groups in (baseline.get("hooks") or {}).values()
            for g in groups for e in g.get("hooks", [])}
    changed = prune_ours(target, keep) + merge_hooks(target, baseline) \
        + merge_deny(target, baseline)
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
