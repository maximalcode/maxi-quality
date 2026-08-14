#!/usr/bin/env python3
"""Turn a knip or deptry result set into a gate verdict (#97).

WHY THIS EXISTS

#39 measured the dead-code class and #51/#52 adopted the two winners, but
neither tool gated anything: `scripts/adopt.sh` printed them under a heading
that said OPTIONAL, and `.github/workflows/ci.yml` ran them against this repo's
own fixtures. `quality.yml` — the thing a consumer actually calls — ran neither.
So the layer was measured, fixtured, documented and absent from every consuming
repo. This file is the missing verdict.

It exists as a script rather than as `knip; deptry` in the workflow because the
raw exit code answers the wrong question. Three of the conditions #39 and #51/#52
measured are about WHICH findings may fail a build, and none of them can be
expressed by an exit code:

1. **Some issue types cannot be adjudicated in-repo.** 19 of the 26 real-code
   findings in #39 were exports with no in-repo reference in a PUBLISHED
   LIBRARY, where that is indistinguishable from public API. Gating those ships
   an unfixable finding, and an unfixable gate gets deleted. So the gating set
   is an argument, and the workflow's `dead-code-exports` input is what widens
   it for an application.

2. **An existing repo has a backlog.** The Layer 2 promise in README.md is that
   `changed-only` lets a repo grandfather one, and a dead-code gate that fails
   400 times on day one gets deleted rather than fixed. knip and deptry cannot
   take a file list — reachability is a whole-graph question, and a file becomes
   dead because of an edit somewhere else — so the scan is always FULL and the
   filtering happens here, on the results. Everything is reported; only findings
   in changed files gate.

   The honest limit of that, stated because it is a real hole rather than a
   subtlety: deleting the last import of an untouched file makes that file dead
   without changing it, so under `changed-only` the finding is advisory. Same
   trade-off Layer 2's `--baseline-commit` already makes, one graph edge further
   out.

3. **A result set that cannot be read is not a clean one.** Same rule as
   scripts/policy.py: a missing, empty or unparseable input exits 3. "The tool
   did not really run" must never render as "nothing was found".

WHAT GATES, AND WHY ONLY THAT

The gating sets below are deliberately NARROWER than what each tool reports.
They contain exactly the issue types #39 measured, and nothing else — every
other type is reported as advisory, so it is visible without being load-bearing.
Widening one is a decision with a measurement attached, not an edit here.

Exit codes: 0 clean · 1 gating findings · 3 usage or parse error
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_parsers():
    """Borrow scripts/check-expected.py's parsers rather than writing new ones.

    Two readers of one tool's JSON is how the docker and native semgrep paths
    came to disagree about `--changed-only` (docs/STATUS.md §4), and the
    manifests in samples/expected are what pin those parsers — so reusing them
    means the fixtures already prove the shape this file gates on.

    importlib because the filename has a hyphen and cannot be imported.
    """
    path = os.path.join(HERE, "check-expected.py")
    spec = importlib.util.spec_from_file_location("check_expected", path)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable in-tree
        raise SystemExit(f"error: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- what may fail a build ----------------------------------------------------
#
# knip. `files`, `dependencies` and `unlisted` are the three that hold whoever
# wrote the code and whatever the repo publishes: an unimported file is
# unreachable, a declared-but-unused dependency is an install nobody needs, and
# an imported-but-undeclared one is a build that works by accident.
KNIP_GATE = ("files", "dependencies", "unlisted")

# Application code only. In a published library an export with no in-repo
# reference IS the product — 19 of 26 in #39 — so this set is opt-in per repo
# and never a default.
KNIP_GATE_EXPORTS = ("exports", "types", "enumMembers", "namespaceMembers")

# deptry. DEP001 (imported, not declared) and DEP002 (declared, not imported)
# are the two #39 planted and the two it confirmed, 2 of 2, with zero false
# positives including the import-name ≠ package-name control (bs4 /
# beautifulsoup4). DEP003 (transitive) and DEP004 (misplaced dev dependency)
# were never measured here, so they report and do not gate.
DEPTRY_GATE = ("DEP001", "DEP002")

GATE_SETS = {
    "knip": KNIP_GATE,
    "deptry": DEPTRY_GATE,
}


def read_changed(path: str) -> set:
    """The repo-relative paths changed since the base ref, one per line.

    Produced by the caller with `git diff --name-only BASE...HEAD`, so the
    "since the merge base" semantics match what a reviewer sees in the pull
    request rather than everything that landed on the base branch meanwhile.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except OSError as exc:
        # Exit 3, not 1. An unreadable ratchet list is a MECHANISM failure, and
        # exit 1 is this script's word for "there are findings" — the caller
        # would read a broken ratchet as a repo with dead code in it.
        print(f"error: cannot read the changed-file list {path}: {exc}", file=sys.stderr)
        raise SystemExit(3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tool", required=True, choices=sorted(GATE_SETS))
    ap.add_argument(
        "--input",
        required=True,
        metavar="FILE",
        help="the tool's machine-readable output ('-' for stdin)",
    )
    ap.add_argument(
        "--gate-exports",
        action="store_true",
        help="knip only: also gate unused exports and types. APPLICATION CODE "
        "ONLY — in a published library an unreferenced export is public API.",
    )
    ap.add_argument(
        "--changed-list",
        metavar="FILE",
        help="ratchet mode: a file of repo-relative changed paths. Findings "
        "outside it are reported and do not gate. Absent = everything gates.",
    )
    ap.add_argument(
        "--package-dir",
        default="",
        help="the repo-relative directory the tool ran in. Both tools report "
        "paths relative to it and git reports them relative to the repo root, "
        "so this is what makes --changed-list match the right files; it also "
        "names the package in the output, for a matrix job whose runs all land "
        "in one log. One argument rather than a prefix and a label, because "
        "two parameters that are always derived from the same directory are "
        "two chances to derive one of them differently.",
    )
    args = ap.parse_args()

    check_expected = _load_parsers()

    try:
        if args.input == "-":
            text = sys.stdin.read()
        else:
            with open(args.input, encoding="utf-8") as fh:
                text = fh.read()
    except OSError as exc:
        print(f"error: cannot read {args.input}: {exc}", file=sys.stderr)
        return 3

    if not text.strip():
        # Never a pass. An empty file is what a crashed tool leaves behind, and
        # "the tool died" must not be indistinguishable from "nothing found".
        print(
            f"error: {args.tool} produced no output at {args.input}. Refusing to "
            "read that as a clean result — an empty result set and a tool that "
            "did not run look identical from here.",
            file=sys.stderr,
        )
        return 3

    try:
        findings = check_expected.PARSERS[args.tool](text)
    except Exception as exc:  # noqa: BLE001 — any parse failure is exit 3, never 0
        print(f"error: cannot parse {args.tool} output: {exc}", file=sys.stderr)
        return 3

    gating_types = set(GATE_SETS[args.tool])
    if args.tool == "knip" and args.gate_exports:
        gating_types |= set(KNIP_GATE_EXPORTS)

    changed = read_changed(args.changed_list) if args.changed_list else None
    package = args.package_dir.strip("/")
    if package in ("", "."):
        package, prefix = "", ""
    else:
        prefix = package + "/"

    gate, advisory = [], []
    for f in findings:
        repo_path = prefix + f["file"] if prefix else f["file"]
        entry = (f["rule"], repo_path, f["line"])
        if f["rule"] not in gating_types:
            advisory.append((entry, "not in the gating set"))
        elif changed is not None and repo_path not in changed:
            advisory.append((entry, "unchanged since the base ref"))
        else:
            gate.append(entry)

    where = f" — {package}" if package else ""
    print(f"── {args.tool}{where} ──")
    for (rule, path, line), why in sorted(advisory, key=lambda e: (e[0][1], e[0][2])):
        # Printed, always. A downgrade nobody can see is a delete with extra
        # steps — the same argument policy.py makes for its warn-only findings.
        print(f"  advisory  {rule:<16} {path}:{line}  ({why})")
    for rule, path, line in sorted(gate, key=lambda e: (e[1], e[2])):
        print(f"  GATE      {rule:<16} {path}:{line}")

    # Machine-readable, in the shape policy.py already established, so a future
    # coverage manifest (#95) can read the same numbers the gate did rather than
    # re-deriving them from the pretty output above.
    print(f"{args.tool}_gate={len(gate)}")
    print(f"{args.tool}_advisory={len(advisory)}")

    if gate:
        print(
            f"::error::{len(gate)} {args.tool} finding(s) fail the gate"
            f"{where}. Deletion is the fix — see docs/ADOPTION.md."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
