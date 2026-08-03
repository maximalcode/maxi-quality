#!/usr/bin/env python3
"""Snapshot what configs/python/ RESOLVES TO, and fail when a setting silently
disappears.

WHY THIS EXISTS, AND WHY THE FIXTURES ARE NOT ENOUGH

The Python twin of scripts/snapshot-eslint-rules.mjs, scripts/snapshot-tsconfig.mjs
and scripts/snapshot-msbuild-props.sh, and it exists for the same measured
reason (#8). samples/python pins the 14 ruff findings and the 5 mypy findings it
produces. CI additionally asserts that all 13 selected ruff FAMILIES are
represented — which is real coverage, and still not enough:

  - `ignore = []` is the config's most load-bearing empty value, and no fixture
    can see it. Adding `ignore = ["S", "T20"]` leaves twelve families firing,
    the count moves by two, and a manifest regenerated in the same commit hides
    it entirely. In the resolved rule set those rules simply vanish, by name.
  - `line-length = 100` was chosen against a real consumer rather than taken
    from ruff's default of 88. One fixture line happens to exceed both, so E501
    fires either way and the number is unasserted.
  - mypy `strict = True` IS AN ALIAS whose contents move between releases. The
    five findings come from base type checking plus warn_unreachable; not one
    of them proves warn_return_any, disallow_any_generics, strict_equality or
    no_implicit_reexport is on. Downgrade `strict` to a hand-picked list and
    every fixture stays green.
  - per-file-ignores is a SUPPRESSION. A widened one shows up as findings that
    stop appearing, which is the shape a regenerated manifest launders.

So this asserts the CONFIGURATION rather than the output.

IT IS EACH TOOL'S OWN RESOLVER, NOT A READ OF THE TOML/INI. Reading the files
would assert what we wrote. `ruff --show-settings` and mypy's own
`process_options` assert what the tool resolved — after `extend`, after
defaults, and after any alias expansion. For mypy that distinction is the entire
point: `strict = True` is one line in the ini and fourteen booleans in the
resolver.

MACHINE-SPECIFIC KEYS ARE DROPPED, not snapshotted: ruff's dump carries
project_root, src and cache_dir, which differ on every machine and would make
the snapshot unusable rather than strict.

A ruff or mypy upgrade CAN change this snapshot — a new rule in a selected
family, a check added to `strict`. That is the intended behaviour and matches
the policy for the other three snapshots: the bump PR is where a human reads the
diff and decides. Regenerate with --write and say in the commit message what
moved and why.

Usage:
  scripts/snapshot-python-settings.py --check    # CI: diff against the snapshot
  scripts/snapshot-python-settings.py --write    # regenerate it deliberately

Exit codes: 0 snapshot matches · 1 the resolved settings drifted · 3 usage error
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
RUFF_CONFIG = REPO / "configs" / "python" / "ruff.toml"
MYPY_CONFIG = REPO / "configs" / "python" / "mypy.ini"
TARGET = REPO / "samples" / "python"
SNAPSHOT = REPO / "configs" / "python" / "settings.snapshot.json"

# mypy's `strict` is an alias. These are the booleans it expands to plus the two
# the config sets on top of it, read back off the resolved Options object rather
# than parsed out of the ini — which is the only way to see the expansion.
MYPY_KEYS = [
    "check_untyped_defs",
    "disallow_any_generics",
    "disallow_incomplete_defs",
    "disallow_subclassing_any",
    "disallow_untyped_calls",
    "disallow_untyped_decorators",
    "disallow_untyped_defs",
    "explicit_package_bases",
    "extra_checks",
    "implicit_reexport",
    "strict_equality",
    "strict_optional",
    "warn_no_return",
    "warn_redundant_casts",
    "warn_return_any",
    "warn_unreachable",
    "warn_unused_configs",
    "warn_unused_ignores",
]


def ruff_settings() -> dict:
    out = subprocess.run(
        ["ruff", "check", "--config", str(RUFF_CONFIG), "--show-settings", str(TARGET)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    def scalar(key: str) -> str | None:
        m = re.search(rf"^{re.escape(key)} = (.*)$", out, re.M)
        return m.group(1).strip() if m else None

    def rule_list(key: str) -> list[str]:
        """ruff prints lists across many lines; collect the entries."""
        m = re.search(rf"^{re.escape(key)} = \[\n(.*?)^\]", out, re.M | re.S)
        if not m:
            return []
        return [ln.strip().rstrip(",") for ln in m.group(1).splitlines() if ln.strip()]

    def per_file_ignores() -> list[str]:
        """Pair each glob with the rules it waives, as `<glob> -> R1, R2`.

        The raw dump also carries an `absolute_matcher` holding the checkout
        path, so the lines cannot be snapshotted as printed — they would encode
        whoever ran it. `basename_matcher` is the pattern as written in
        ruff.toml and is what actually needs pinning.
        """
        block = re.search(r"^linter\.per_file_ignores = \{\n(.*?)^\}", out, re.M | re.S)
        if not block:
            return []
        entries = []
        for chunk in re.finditer(
            r'basename_matcher = "([^"]+)".*?data = \[\n(.*?)\n\s*\]', block.group(1), re.S
        ):
            rules = sorted(ln.strip().rstrip(",") for ln in chunk.group(2).splitlines() if ln.strip())
            entries.append(f"{chunk.group(1)} -> {', '.join(rules)}")
        return sorted(entries)

    return {
        # THE ONE THAT MATTERS. `select` minus `ignore`, fully resolved — so a
        # global ignore removes rules from this list by name.
        "enabled_rules": sorted(rule_list("linter.rules.enabled")),
        "per_file_ignores": per_file_ignores(),
        "line_length": scalar("linter.line_length"),
        "target_version": scalar("linter.unresolved_target_version"),
        "preview": scalar("linter.preview"),
    }


def mypy_settings() -> dict:
    from mypy.main import process_options

    _, opts = process_options(
        ["--config-file", str(MYPY_CONFIG), str(TARGET / "src")], require_targets=False
    )
    return {k: getattr(opts, k) for k in MYPY_KEYS}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("--check", "--write"):
        print("usage: snapshot-python-settings.py --check | --write", file=sys.stderr)
        return 3

    resolved = {"ruff": ruff_settings(), "mypy": mypy_settings()}
    # A resolver that returns nothing is a snapshot that asserts nothing, and it
    # would compare equal to itself forever.
    if not resolved["ruff"]["enabled_rules"]:
        print("::error::ruff resolved 0 enabled rules — refusing to snapshot that", file=sys.stderr)
        return 1
    serialised = json.dumps(resolved, indent=2, sort_keys=True) + "\n"

    if mode == "--write":
        SNAPSHOT.write_text(serialised)
        n = len(resolved["ruff"]["enabled_rules"])
        print(f"wrote {SNAPSHOT.relative_to(REPO)} — {n} ruff rules, {len(MYPY_KEYS)} mypy settings")
        return 0

    if not SNAPSHOT.exists():
        print(
            f"::error::{SNAPSHOT.relative_to(REPO)} is missing. Run: "
            "scripts/snapshot-python-settings.py --write",
            file=sys.stderr,
        )
        return 1

    committed = SNAPSHOT.read_text()
    if committed == serialised:
        n = len(resolved["ruff"]["enabled_rules"])
        print(f"python settings snapshot matches — {n} ruff rules, {len(MYPY_KEYS)} mypy settings")
        return 0

    # Name what moved. A bare "files differ" leaves two JSON blobs to diff by
    # eye, and the point of this check is that a REMOVED rule is easy to miss.
    before = json.loads(committed)
    print("::error::the resolved Python settings drifted:", file=sys.stderr)
    for tool in ("ruff", "mypy"):
        b, a = before.get(tool, {}), resolved[tool]
        for key in sorted(set(b) | set(a)):
            bv, av = b.get(key), a.get(key)
            if bv == av:
                continue
            if isinstance(bv, list) and isinstance(av, list):
                for gone in sorted(set(bv) - set(av)):
                    print(f"  REMOVED  {tool}.{key}: {gone}", file=sys.stderr)
                for new in sorted(set(av) - set(bv)):
                    print(f"  ADDED    {tool}.{key}: {new}", file=sys.stderr)
            else:
                print(f"  CHANGED  {tool}.{key}: {bv!r} -> {av!r}", file=sys.stderr)
    print(
        "If this was deliberate, regenerate with: scripts/snapshot-python-settings.py --write",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
